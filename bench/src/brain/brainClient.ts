import Ajv2020 from 'ajv/dist/2020'
import controlSchema from '../../../contracts/brain/control.schema.json'
import statusSchema from '../../../contracts/brain/status.schema.json'
import type { BrainControl } from '@shared/brain/generated/control'
import type { BrainMessage, BrainStatus, ControlResult, Decision } from '@shared/brain/generated/status'

/**
 * 두뇌(brain)와의 연결. 두뇌는 따로 띄우는 프로그램이라 꺼져 있을 수 있다 (그래도 화면의 나머지는 쓸 수 있다).
 * 받은 메시지는 규약 스키마로 확인하고, 끊기면 간격을 늘려 가며 다시 붙는다.
 */

export type BrainPhase = 'connecting' | 'open' | 'offline'
type OutgoingControl = BrainControl extends infer C ? (C extends unknown ? Omit<C, 'id'> : never) : never

export interface BrainClientOptions {
  url: string
  createSocket?: (url: string) => WebSocket
  reconnectDelaysMs?: number[]
  replyTimeoutMs?: number
}

export interface BrainClientEvents {
  phase: (phase: BrainPhase) => void
  status: (status: BrainStatus) => void
  decision: (decision: Decision) => void
}

const DEFAULT_RECONNECT_DELAYS_MS = [1000, 2000, 5000]
const DEFAULT_REPLY_TIMEOUT_MS = 2000
const SOCKET_OPEN = 1
// 상태 규약은 시험에서 비교할 것(TrialSetup)을 지시 규약에서 가져다 쓴다
const validateMessage = new Ajv2020({ allErrors: false }).addSchema(controlSchema).compile<BrainMessage>(statusSchema)

export class BrainClient {
  private socket: WebSocket | null = null
  private attempt = 0
  private timer: ReturnType<typeof setTimeout> | null = null
  private closed = false
  private nextId = 1
  private readonly pending = new Map<string, (result: ControlResult) => void>()
  private readonly listeners: { [K in keyof BrainClientEvents]: Set<BrainClientEvents[K]> } = {
    phase: new Set(),
    status: new Set(),
    decision: new Set(),
  }
  private readonly createSocket: (url: string) => WebSocket
  private readonly delays: number[]
  private readonly replyTimeoutMs: number

  constructor(private readonly options: BrainClientOptions) {
    this.createSocket = options.createSocket ?? ((url) => new WebSocket(url))
    this.delays = options.reconnectDelaysMs ?? DEFAULT_RECONNECT_DELAYS_MS
    this.replyTimeoutMs = options.replyTimeoutMs ?? DEFAULT_REPLY_TIMEOUT_MS
  }

  on<K extends keyof BrainClientEvents>(event: K, listener: BrainClientEvents[K]): () => void {
    this.listeners[event].add(listener)
    return () => this.listeners[event].delete(listener)
  }

  connect(): void {
    this.closed = false
    this.emit('phase', 'connecting')
    const socket = this.createSocket(this.options.url)
    this.socket = socket
    socket.onopen = () => {
      this.attempt = 0
      this.emit('phase', 'open')
    }
    socket.onmessage = (event) => this.handle(event.data)
    socket.onclose = () => {
      if (this.socket !== socket) {
        return
      }
      this.socket = null
      this.failPending('두뇌와 연결이 끊겼습니다')
      this.emit('phase', 'offline')
      if (!this.closed) {
        const delay = this.delays[Math.min(this.attempt++, this.delays.length - 1)] ?? 0
        this.timer = setTimeout(() => this.connect(), delay)
      }
    }
  }

  retry(): void {
    if (this.timer) {
      clearTimeout(this.timer)
    }
    this.attempt = 0
    this.socket?.close()
    this.connect()
  }

  close(): void {
    this.closed = true
    if (this.timer) {
      clearTimeout(this.timer)
    }
    this.socket?.close()
    this.socket = null
  }

  send(control: OutgoingControl): Promise<ControlResult> {
    if (this.socket?.readyState !== SOCKET_OPEN) {
      return Promise.resolve({ type: 'controlResult', accepted: false, reason: '두뇌와 연결되어 있지 않습니다' })
    }
    const id = `bench-${this.nextId++}`
    return new Promise((resolve) => {
      const timer = setTimeout(() => this.settle(id, { type: 'controlResult', id, accepted: false, reason: '두뇌가 답하지 않습니다' }), this.replyTimeoutMs)
      this.pending.set(id, (result) => {
        clearTimeout(timer)
        resolve(result)
      })
      this.socket!.send(JSON.stringify({ ...control, id }))
    })
  }

  private handle(data: unknown): void {
    let message: unknown
    try {
      message = JSON.parse(String(data))
    } catch {
      return
    }
    if (!validateMessage(message)) {
      return
    }
    switch (message.type) {
      case 'brainStatus':
        this.emit('status', message)
        break
      case 'decision':
        this.emit('decision', message)
        break
      case 'controlResult':
        if (message.id) {
          this.settle(message.id, message)
        }
        break
    }
  }

  private settle(id: string, result: ControlResult): void {
    const resolve = this.pending.get(id)
    if (resolve) {
      this.pending.delete(id)
      resolve(result)
    }
  }

  private failPending(reason: string): void {
    for (const id of [...this.pending.keys()]) {
      this.settle(id, { type: 'controlResult', id, accepted: false, reason })
    }
  }

  private emit<K extends keyof BrainClientEvents>(event: K, ...args: Parameters<BrainClientEvents[K]>): void {
    for (const listener of this.listeners[event]) {
      ;(listener as (...values: Parameters<BrainClientEvents[K]>) => void)(...args)
    }
  }
}

/** 화면 주소에서 두뇌 WebSocket 주소를 만든다 (개발 서버가 /brain을 두뇌로 넘긴다). */
export function brainSocketUrl(path: string, location: Pick<Location, 'protocol' | 'host'> = window.location): string {
  return `${location.protocol === 'https:' ? 'wss:' : 'ws:'}//${location.host}${path}`
}
