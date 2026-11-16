// 和仿真的连接（WebSocket）：收招呼和状态，发命令、等答复；断了自己再连。
import { ContractError, readMessage } from '@/sim/contracts'
import type { Command } from '@/generated/command'
import type { Hello, State } from '@/generated/message'

export type LinkStatus = 'connecting' | 'open' | 'closed'

type WithoutId<Each> = Each extends { id: number } ? Omit<Each, 'id'> : never
/** 一条还没有编号的命令（编号由连接来编）。 */
export type CommandBody = WithoutId<Command>

export interface LinkEvents {
  onStatus(status: LinkStatus): void
  onHello(hello: Hello): void
  onState(state: State): void
  /** 收到了读不懂的消息。 */
  onProblem(problem: string): void
}

/** 浏览器的 WebSocket 里这里用到的那几样。测试时换成假的。 */
export interface SocketLike {
  onopen: (() => void) | null
  onclose: (() => void) | null
  onmessage: ((event: { data: unknown }) => void) | null
  send(text: string): void
  close(): void
}

export const ACK_TIMEOUT_MS = 3000
export const FIRST_RETRY_MS = 500
export const LONGEST_RETRY_MS = 5000

interface Waiting {
  done(): void
  fail(reason: Error): void
  timer: ReturnType<typeof setTimeout>
}

export class SimLink {
  private socket: SocketLike | null = null
  private waiting = new Map<number, Waiting>()
  private nextId = 1
  private retryMs = FIRST_RETRY_MS
  private retryTimer: ReturnType<typeof setTimeout> | null = null
  private wanted = false
  private isOpen = false

  constructor(
    private readonly url: string,
    private readonly events: LinkEvents,
    private readonly makeSocket: (url: string) => SocketLike = (address) => new WebSocket(address) as SocketLike,
  ) {}

  /** 连上去。断了会自己再连，直到 close()。 */
  open(): void {
    this.wanted = true
    this.connect()
  }

  /** 断开，不再重连。 */
  close(): void {
    this.wanted = false
    this.cancelRetry()
    this.socket?.close()
  }

  /** 不等了，现在就再连一次。 */
  retryNow(): void {
    if (!this.wanted || this.socket) return
    this.cancelRetry()
    this.connect()
  }

  /** 发一条命令。仿真答复"照做了"就算完成；没照做、没答复、连接断了都算失败，带着原因。 */
  send(command: CommandBody): Promise<void> {
    const socket = this.socket
    if (!socket || !this.isOpen) return Promise.reject(new Error('还没连上仿真，命令发不出去'))
    const id = this.nextId++
    return new Promise<void>((done, fail) => {
      const timer = setTimeout(() => {
        this.waiting.delete(id)
        fail(new Error('仿真没有答复'))
      }, ACK_TIMEOUT_MS)
      this.waiting.set(id, { done, fail, timer })
      socket.send(JSON.stringify({ ...command, id }))
    })
  }

  private connect(): void {
    this.events.onStatus('connecting')
    const socket = this.makeSocket(this.url)
    this.socket = socket
    socket.onopen = () => {
      this.isOpen = true
      this.retryMs = FIRST_RETRY_MS
      this.events.onStatus('open')
    }
    socket.onmessage = (event) => this.receive(event.data)
    socket.onclose = () => {
      // 连不上的时候浏览器也只给一个 close；这里一起处理。
      this.isOpen = false
      this.socket = null
      this.failAll(new Error('和仿真的连接断了'))
      this.events.onStatus('closed')
      if (this.wanted) this.scheduleRetry()
    }
  }

  private receive(data: unknown): void {
    if (typeof data !== 'string') {
      this.events.onProblem('仿真发来的消息不是文字')
      return
    }
    try {
      const message = readMessage(data)
      if (message.type === 'state') this.events.onState(message)
      else if (message.type === 'hello') this.events.onHello(message)
      else this.settle(message.id, message.ok, message.reason)
    } catch (error) {
      if (!(error instanceof ContractError)) throw error
      this.events.onProblem(error.message)
    }
  }

  private settle(id: number | null, ok: boolean, reason: string): void {
    const waiting = id === null ? undefined : this.waiting.get(id)
    if (id === null || !waiting) return
    this.waiting.delete(id)
    clearTimeout(waiting.timer)
    if (ok) waiting.done()
    else waiting.fail(new Error(reason))
  }

  private failAll(reason: Error): void {
    for (const waiting of this.waiting.values()) {
      clearTimeout(waiting.timer)
      waiting.fail(reason)
    }
    this.waiting.clear()
  }

  private scheduleRetry(): void {
    this.retryTimer = setTimeout(() => {
      this.retryTimer = null
      this.connect()
    }, this.retryMs)
    // 连不上就隔得越来越久再试，最久 5 秒一次。
    this.retryMs = Math.min(this.retryMs * 2, LONGEST_RETRY_MS)
  }

  private cancelRetry(): void {
    if (this.retryTimer !== null) clearTimeout(this.retryTimer)
    this.retryTimer = null
  }
}
