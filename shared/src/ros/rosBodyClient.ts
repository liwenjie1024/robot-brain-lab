import Ajv2020 from 'ajv/dist/2020'
import sceneSchema from '../../../contracts/sim/scene.schema.json'
import type { BodyLink } from '../sim/bodyLink'
import type { SceneDescription } from '../sim/generated/scene'
import {
  type CombatEvent,
  type CommandResult,
  type ConnectionPhase,
  type OutgoingCommand,
  type SimClientEvents,
  validateSimMessage,
} from '../sim/simClient'
import { BL01, combatFromRos, serviceCall, stateFromRos } from './bl01'
import { isRecord, RosbridgeConnection } from './rosbridge'

export interface RosBodyClientOptions {
  /** rosbridge 주소 (예: ws://localhost:9090) */
  url: string
  createSocket?: (url: string) => WebSocket
  now?: () => number
  /** 끊기면 이 간격으로 다시 붙는다 (마지막 값을 계속 쓴다) */
  reconnectDelaysMs?: number[]
  commandTimeoutMs?: number
  /** ROS 2 드라이버가 아직 몸에 붙지 못해 장면 설명이 없을 때 다시 묻는 간격 */
  scenePollMs?: number
}

const DEFAULT_RECONNECT_DELAYS_MS = [500, 1000, 2000, 5000]
const DEFAULT_COMMAND_TIMEOUT_MS = 2000
const DEFAULT_SCENE_POLL_MS = 1000
const NOT_CONNECTED = '몸과 연결되어 있지 않습니다'
const BODY_NOT_LINKED = 'ROS 2 드라이버가 아직 몸(시뮬레이터)에 붙지 못했습니다'
const BODY_LINK_LOST = 'ROS 2 드라이버와 몸(시뮬레이터)의 연결이 끊겼습니다'

const validateScene = new Ajv2020({ allErrors: false }).compile<SceneDescription>(sceneSchema)

/**
 * 몸에 ROS 2로 붙는다 (rosbridge를 거쳐): 장면 설명은 서비스로, 상태·사건은 토픽으로 받고, 명령은 서비스로 보내 답을 받는다.
 * 받은 메시지는 규약 모양으로 바꿔 규약 스키마로 확인한다. SimClient와 같은 모양(BodyLink)이라 두뇌는 그대로 쓴다.
 * 서비스 답과 상태 토픽은 다른 길로 와 순서가 보장되지 않는다 (되돌린 뒤의 상태는 episode로 알아본다).
 */
export class RosBodyClient implements BodyLink {
  private connection: RosbridgeConnection | null = null
  private readonly listeners: { [K in keyof SimClientEvents]: Set<SimClientEvents[K]> } = {
    phase: new Set(),
    scene: new Set(),
    state: new Set(),
    combat: new Set(),
    invalidMessage: new Set(),
  }
  private phase: ConnectionPhase | null = null
  private phaseDetail: string | undefined
  /** 장면 설명을 받았고 드라이버가 몸과 붙어 있다 (명령을 보낼 수 있다) */
  private bodyReady = false
  /** 붙어 있다가 드라이버와 몸이 끊겼다 (다시 붙는 중으로 알린다) */
  private bodyLost = false
  /** 장면 설명을 묻고 답을 기다리는 rosbridge 연결 */
  private sceneRequestedOn: RosbridgeConnection | null = null
  /** 이 rosbridge 연결에서 상태·사건 토픽을 받기 시작했다 */
  private streaming = false
  private reconnectAttempt = 0
  private timer: ReturnType<typeof setTimeout> | null = null
  private closedByUser = false
  private nextId = 1
  private readonly createSocket: (url: string) => WebSocket
  private readonly now: () => number
  private readonly reconnectDelaysMs: number[]
  private readonly commandTimeoutMs: number
  private readonly scenePollMs: number

  constructor(private readonly options: RosBodyClientOptions) {
    this.createSocket = options.createSocket ?? ((url) => new WebSocket(url))
    this.now = options.now ?? (() => performance.now())
    this.reconnectDelaysMs = options.reconnectDelaysMs ?? DEFAULT_RECONNECT_DELAYS_MS
    this.commandTimeoutMs = options.commandTimeoutMs ?? DEFAULT_COMMAND_TIMEOUT_MS
    this.scenePollMs = options.scenePollMs ?? DEFAULT_SCENE_POLL_MS
  }

  on<K extends keyof SimClientEvents>(event: K, listener: SimClientEvents[K]): () => void {
    this.listeners[event].add(listener)
    return () => this.listeners[event].delete(listener)
  }

  connect(): void {
    this.closedByUser = false
    this.open()
  }

  retry(): void {
    this.cancelTimer()
    this.reconnectAttempt = 0
    this.drop()
    this.open()
  }

  close(): void {
    this.closedByUser = true
    this.cancelTimer()
    this.drop()
  }

  async send(command: OutgoingCommand): Promise<CommandResult> {
    const id = `ros-${this.nextId++}`
    const connection = this.connection
    if (!connection?.open || !this.bodyReady) {
      return { id, accepted: false, reason: NOT_CONNECTED, roundTripMs: 0 }
    }
    const startedAt = this.now()
    const call = serviceCall(command)
    const reply = await connection.callService(call.service, call.type, call.args, this.commandTimeoutMs)
    const roundTripMs = this.now() - startedAt
    if (!reply.ok) {
      return { id, accepted: false, reason: reply.error, roundTripMs }
    }
    const values = reply.values
    if (!isRecord(values) || typeof values.accepted !== 'boolean') {
      return { id, accepted: false, reason: `${call.service}의 답 모양이 규약과 다릅니다`, roundTripMs }
    }
    return values.accepted
      ? { id, accepted: true, roundTripMs }
      : { id, accepted: false, reason: typeof values.reason === 'string' ? values.reason : '', roundTripMs }
  }

  private open(): void {
    this.setPhase(this.reconnectAttempt === 0 ? 'loading-scene' : 'reconnecting')
    const connection: RosbridgeConnection = new RosbridgeConnection(
      this.options.url,
      {
        open: () => this.onOpen(connection),
        close: () => this.onClose(connection),
        invalid: (reason) => this.emit('invalidMessage', reason),
      },
      this.createSocket,
    )
    this.connection = connection
  }

  private onOpen(connection: RosbridgeConnection): void {
    this.reconnectAttempt = 0
    this.streaming = false
    this.bodyLost = false
    connection.subscribe(BL01.link.topic, BL01.link.type, (message) => this.onLink(connection, message))
    void this.loadScene(connection)
  }

  /**
   * 장면 설명을 받아야 몸과 붙은 것으로 본다 (드라이버는 몸과 붙어 있을 때만 준다). 못 받으면 조금 뒤 다시 묻는다.
   * 한 번에 하나만 묻는다 (붙음 토픽과 다시 묻기가 겹쳐도).
   */
  private async loadScene(connection: RosbridgeConnection): Promise<void> {
    if (this.sceneRequestedOn === connection) {
      return
    }
    this.cancelTimer()
    this.sceneRequestedOn = connection
    const reply = await connection.callService(BL01.getScene.service, BL01.getScene.type, {}, this.commandTimeoutMs)
    if (this.sceneRequestedOn === connection) {
      this.sceneRequestedOn = null
    }
    if (this.connection !== connection) {
      return
    }
    const scene = reply.ok ? parseScene(reply.values) : null
    if (!scene) {
      this.setPhase(this.bodyLost ? 'reconnecting' : 'connecting', reply.ok ? BODY_NOT_LINKED : reply.error)
      this.timer = setTimeout(() => void this.loadScene(connection), this.scenePollMs)
      return
    }
    this.emit('scene', scene)
    if (!this.streaming) {
      this.streaming = true
      connection.subscribe(BL01.state.topic, BL01.state.type, (message) => this.onState(message))
      connection.subscribe(BL01.combat.topic, BL01.combat.type, (message) => this.onCombat(message))
    }
    this.bodyReady = true
    this.bodyLost = false
    this.setPhase('open')
  }

  /** 드라이버와 몸의 연결이 끊기면 명령을 막고, 다시 붙으면 장면 설명부터 다시 받는다 */
  private onLink(connection: RosbridgeConnection, message: unknown): void {
    const linked = isRecord(message) && message.data === true
    if (!linked && this.bodyReady) {
      this.bodyReady = false
      this.bodyLost = true
      this.setPhase('reconnecting', BODY_LINK_LOST)
      this.cancelTimer()
      this.timer = setTimeout(() => void this.loadScene(connection), this.scenePollMs)
    } else if (linked && !this.bodyReady) {
      void this.loadScene(connection)
    }
  }

  private onState(message: unknown): void {
    const state = this.toContract(() => stateFromRos(message))
    if (state?.type === 'state') {
      this.emit('state', state)
    }
  }

  private onCombat(message: unknown): void {
    const event = this.toContract(() => combatFromRos(message))
    if (event?.type === 'shot' || event?.type === 'destroyed') {
      this.emit('combat', event as CombatEvent)
    }
  }

  /** 받은 ROS 메시지를 규약 모양으로 바꿔 규약 스키마로 확인한다. 바꾸지 못하거나 규약과 다르면 버리고 알린다. */
  private toContract<T>(convert: () => T): T | null {
    let message: T
    try {
      message = convert()
    } catch {
      this.emit('invalidMessage', 'ROS 메시지의 모양이 BL-01 메시지와 다름')
      return null
    }
    if (!validateSimMessage(message)) {
      this.emit('invalidMessage', validateSimMessage.errors?.[0]?.message ?? '규약과 다른 메시지')
      return null
    }
    return message
  }

  private onClose(connection: RosbridgeConnection): void {
    if (this.connection !== connection) {
      return
    }
    this.connection = null
    this.bodyReady = false
    this.cancelTimer()
    if (!this.closedByUser) {
      const delays = this.reconnectDelaysMs
      const delay = delays[Math.min(this.reconnectAttempt, delays.length - 1)] ?? 0
      this.reconnectAttempt++
      this.setPhase('reconnecting', `rosbridge와 연결이 끊겼습니다. ${Math.round(delay / 100) / 10}초 뒤 다시 붙습니다.`)
      this.timer = setTimeout(() => this.open(), delay)
    }
  }

  private drop(): void {
    const connection = this.connection
    this.connection = null
    this.bodyReady = false
    connection?.close()
  }

  private cancelTimer(): void {
    if (this.timer) {
      clearTimeout(this.timer)
      this.timer = null
    }
  }

  /** 같은 단계·같은 까닭은 다시 알리지 않는다 (장면 설명을 다시 물을 때마다 알리지 않게) */
  private setPhase(phase: ConnectionPhase, detail?: string): void {
    if (phase === this.phase && detail === this.phaseDetail) {
      return
    }
    this.phase = phase
    this.phaseDetail = detail
    this.emit('phase', phase, detail)
  }

  private emit<K extends keyof SimClientEvents>(event: K, ...args: Parameters<SimClientEvents[K]>): void {
    for (const listener of this.listeners[event]) {
      ;(listener as (...values: Parameters<SimClientEvents[K]>) => void)(...args)
    }
  }
}

function parseScene(values: unknown): SceneDescription | null {
  if (!isRecord(values) || values.available !== true || typeof values.scene_json !== 'string') {
    return null
  }
  let scene: unknown
  try {
    scene = JSON.parse(values.scene_json)
  } catch {
    return null
  }
  return validateScene(scene) ? scene : null
}
