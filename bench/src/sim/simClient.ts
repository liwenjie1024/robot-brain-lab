import Ajv2020 from 'ajv/dist/2020'
import messageSchema from '../../../contracts/sim/message.schema.json'
import type { SimCommand } from './generated/command'
import type { SimMessage, StateMessage } from './generated/message'
import type { SceneDescription } from './generated/scene'

/**
 * 몸(시뮬레이터)과의 연결. 모델 설명(/scene)을 먼저 받고 WebSocket으로 상태를 받으며 명령을 보낸다.
 * 화면 틀(Vue)과 떨어뜨려 두어 시험하기 쉽고, 나중에 두뇌 쪽에서도 같은 방식을 쓴다.
 */

export type ConnectionPhase = 'loading-scene' | 'connecting' | 'open' | 'reconnecting' | 'failed'

/** id는 이 연결이 붙인다 */
export type OutgoingCommand = SimCommand extends infer C ? (C extends unknown ? Omit<C, 'id'> : never) : never

export interface CommandResult {
  id: string
  accepted: boolean
  /** 거절·실패한 까닭 (사람이 읽는 글) */
  reason?: string
  /** 보내고 답을 받기까지 ms */
  roundTripMs: number
}

export interface SimClientOptions {
  /** /scene, /ws, /meshes 앞에 붙는 주소 (개발 서버가 /sim을 시뮬레이터로 넘긴다) */
  baseUrl: string
  createSocket?: (url: string) => WebSocket
  fetchFn?: typeof fetch
  now?: () => number
  /** 끊기면 이 간격으로 다시 붙는다 (마지막 값을 계속 쓴다) */
  reconnectDelaysMs?: number[]
  commandTimeoutMs?: number
}

export interface SimClientEvents {
  phase: (phase: ConnectionPhase, detail?: string) => void
  scene: (scene: SceneDescription) => void
  state: (state: StateMessage) => void
  invalidMessage: (reason: string) => void
}

const DEFAULT_RECONNECT_DELAYS_MS = [500, 1000, 2000, 5000]
const DEFAULT_COMMAND_TIMEOUT_MS = 2000
const SOCKET_OPEN = 1

interface PendingCommand {
  sentAt: number
  resolve: (result: CommandResult) => void
  timer: ReturnType<typeof setTimeout>
}

const validateMessage = new Ajv2020({ allErrors: false }).compile<SimMessage>(messageSchema)

export class SimClient {
  private socket: WebSocket | null = null
  private readonly pending = new Map<string, PendingCommand>()
  private readonly listeners: { [K in keyof SimClientEvents]: Set<SimClientEvents[K]> } = {
    phase: new Set(),
    scene: new Set(),
    state: new Set(),
    invalidMessage: new Set(),
  }
  private nextId = 1
  private reconnectAttempt = 0
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null
  private closedByUser = false
  private readonly createSocket: (url: string) => WebSocket
  private readonly fetchFn: typeof fetch
  private readonly now: () => number
  private readonly reconnectDelaysMs: number[]
  private readonly commandTimeoutMs: number

  constructor(private readonly options: SimClientOptions) {
    this.createSocket = options.createSocket ?? ((url) => new WebSocket(url))
    this.fetchFn = options.fetchFn ?? ((input, init) => fetch(input, init))
    this.now = options.now ?? (() => performance.now())
    this.reconnectDelaysMs = options.reconnectDelaysMs ?? DEFAULT_RECONNECT_DELAYS_MS
    this.commandTimeoutMs = options.commandTimeoutMs ?? DEFAULT_COMMAND_TIMEOUT_MS
  }

  on<K extends keyof SimClientEvents>(event: K, listener: SimClientEvents[K]): () => void {
    this.listeners[event].add(listener)
    return () => this.listeners[event].delete(listener)
  }

  /** 모델 설명을 받고 연결한다. 설명을 못 받으면 failed가 되고 retry()로 다시 한다. */
  async connect(): Promise<void> {
    this.closedByUser = false
    this.emit('phase', 'loading-scene')
    try {
      const response = await this.fetchFn(`${this.options.baseUrl}/scene`)
      if (!response.ok) {
        throw new Error(`응답 ${response.status}`)
      }
      this.emit('scene', (await response.json()) as SceneDescription)
    } catch (error) {
      this.emit('phase', 'failed', `몸의 모양을 받지 못했습니다 (${describeError(error)}). 시뮬레이터가 떠 있는지 확인해 주세요.`)
      return
    }
    this.openSocket()
  }

  retry(): void {
    this.cancelReconnect()
    this.reconnectAttempt = 0
    void this.connect()
  }

  close(): void {
    this.closedByUser = true
    this.cancelReconnect()
    this.socket?.close()
    this.socket = null
    this.failPending('연결을 닫았습니다')
  }

  meshUrl(meshId: number): string {
    return `${this.options.baseUrl}/meshes/${meshId}`
  }

  send(command: OutgoingCommand): Promise<CommandResult> {
    const id = `bench-${this.nextId++}`
    const sentAt = this.now()
    if (this.socket?.readyState !== SOCKET_OPEN) {
      return Promise.resolve({ id, accepted: false, reason: '몸과 연결되어 있지 않습니다', roundTripMs: 0 })
    }
    return new Promise((resolve) => {
      const timer = setTimeout(() => this.finish(id, false, '답이 없습니다 (시간 초과)'), this.commandTimeoutMs)
      this.pending.set(id, { sentAt, resolve, timer })
      this.socket!.send(JSON.stringify({ ...command, id }))
    })
  }

  private openSocket(): void {
    this.emit('phase', this.reconnectAttempt === 0 ? 'connecting' : 'reconnecting')
    const socket = this.createSocket(socketUrl(this.options.baseUrl))
    this.socket = socket
    socket.onopen = () => {
      this.reconnectAttempt = 0
      this.emit('phase', 'open')
    }
    socket.onmessage = (event) => this.handleMessage(event.data)
    socket.onclose = () => {
      if (this.socket !== socket) {
        return
      }
      this.socket = null
      this.failPending('연결이 끊겨 답을 받지 못했습니다')
      if (!this.closedByUser) {
        this.scheduleReconnect()
      }
    }
  }

  private scheduleReconnect(): void {
    const delays = this.reconnectDelaysMs
    const delay = delays[Math.min(this.reconnectAttempt, delays.length - 1)] ?? 0
    this.reconnectAttempt++
    this.emit('phase', 'reconnecting', `연결이 끊겼습니다. ${Math.round(delay / 100) / 10}초 뒤 다시 붙습니다.`)
    this.reconnectTimer = setTimeout(() => this.openSocket(), delay)
  }

  private cancelReconnect(): void {
    if (this.reconnectTimer) {
      clearTimeout(this.reconnectTimer)
      this.reconnectTimer = null
    }
  }

  private handleMessage(data: unknown): void {
    let message: unknown
    try {
      message = JSON.parse(String(data))
    } catch {
      this.emit('invalidMessage', 'JSON이 아닌 메시지')
      return
    }
    if (!validateMessage(message)) {
      this.emit('invalidMessage', validateMessage.errors?.[0]?.message ?? '규약과 다른 메시지')
      return
    }
    switch (message.type) {
      case 'state':
        this.emit('state', message)
        break
      case 'ack':
        if (message.id) {
          this.finish(message.id, true)
        }
        break
      case 'rejected':
        if (message.id) {
          this.finish(message.id, false, message.reason)
        }
        break
    }
  }

  private finish(id: string, accepted: boolean, reason?: string): void {
    const pending = this.pending.get(id)
    if (!pending) {
      return
    }
    this.pending.delete(id)
    clearTimeout(pending.timer)
    pending.resolve({ id, accepted, reason, roundTripMs: this.now() - pending.sentAt })
  }

  private failPending(reason: string): void {
    for (const id of [...this.pending.keys()]) {
      this.finish(id, false, reason)
    }
  }

  private emit<K extends keyof SimClientEvents>(event: K, ...args: Parameters<SimClientEvents[K]>): void {
    for (const listener of this.listeners[event]) {
      ;(listener as (...values: Parameters<SimClientEvents[K]>) => void)(...args)
    }
  }
}

function socketUrl(baseUrl: string): string {
  const url = new URL(`${baseUrl}/ws`, globalThis.location?.href ?? 'http://localhost/')
  url.protocol = url.protocol === 'https:' ? 'wss:' : 'ws:'
  return url.toString()
}

function describeError(error: unknown): string {
  return error instanceof Error ? error.message : String(error)
}
