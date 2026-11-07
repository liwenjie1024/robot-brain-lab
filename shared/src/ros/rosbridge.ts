/**
 * rosbridge 규약(v2, JSON over WebSocket)의 필요한 만큼만: 토픽 받기(subscribe)와 서비스 부르기(call_service).
 * 브라우저·휴대폰은 ROS 2(DDS)에 바로 붙지 못해 ROS 쪽에서도 웹은 rosbridge로 붙는다. 라이브러리(roslibjs) 없이 직접 쓴다.
 * 한 연결의 수명만 맡는다 (다시 붙기는 쓰는 쪽이 새로 만든다).
 */

export type ServiceReply = { ok: true; values: unknown } | { ok: false; error: string }

export interface RosbridgeHandlers {
  open: () => void
  close: () => void
  /** 규약과 다른 프레임 (버리고 알린다) */
  invalid: (reason: string) => void
}

interface PendingCall {
  resolve: (reply: ServiceReply) => void
  timer: ReturnType<typeof setTimeout>
}

const SOCKET_OPEN = 1

export class RosbridgeConnection {
  private readonly socket: WebSocket
  private readonly topics = new Map<string, Set<(message: unknown) => void>>()
  private readonly calls = new Map<string, PendingCall>()
  private nextId = 1
  private closed = false

  constructor(
    url: string,
    private readonly handlers: RosbridgeHandlers,
    createSocket: (url: string) => WebSocket = (address) => new WebSocket(address),
  ) {
    this.socket = createSocket(url)
    this.socket.onopen = () => handlers.open()
    this.socket.onmessage = (event) => this.handleFrame(event.data)
    this.socket.onclose = () => this.handleClose()
  }

  get open(): boolean {
    return this.socket.readyState === SOCKET_OPEN
  }

  /** 토픽을 받는다. 돌려준 함수를 부르면 그만 받는다. */
  subscribe(topic: string, type: string, handler: (message: unknown) => void): () => void {
    let handlers = this.topics.get(topic)
    if (!handlers) {
      handlers = new Set()
      this.topics.set(topic, handlers)
      this.write({ op: 'subscribe', id: `subscribe:${topic}`, topic, type })
    }
    handlers.add(handler)
    return () => {
      handlers.delete(handler)
      if (handlers.size === 0 && this.topics.delete(topic)) {
        this.write({ op: 'unsubscribe', id: `subscribe:${topic}`, topic })
      }
    }
  }

  /** 서비스를 부르고 답을 기다린다. 끊기거나 정한 시간 안에 답이 없으면 실패로 끝난다. */
  callService(service: string, type: string, args: object, timeoutMs: number): Promise<ServiceReply> {
    if (!this.open) {
      return Promise.resolve({ ok: false, error: 'rosbridge에 연결되어 있지 않습니다' })
    }
    const id = `call:${this.nextId++}`
    return new Promise((resolve) => {
      const timer = setTimeout(() => this.settle(id, { ok: false, error: `${service}이(가) 답하지 않습니다 (시간 초과)` }), timeoutMs)
      this.calls.set(id, { resolve, timer })
      this.write({ op: 'call_service', id, service, type, args })
    })
  }

  close(): void {
    this.closed = true
    this.socket.close()
    this.handleClose()
  }

  private write(operation: object): void {
    if (this.open) {
      this.socket.send(JSON.stringify(operation))
    }
  }

  private handleFrame(data: unknown): void {
    let frame: unknown
    try {
      frame = JSON.parse(String(data))
    } catch {
      this.handlers.invalid('rosbridge가 JSON이 아닌 프레임을 보냄')
      return
    }
    if (!isRecord(frame) || typeof frame.op !== 'string') {
      this.handlers.invalid('rosbridge 프레임에 op가 없음')
      return
    }
    if (frame.op === 'publish' && typeof frame.topic === 'string') {
      this.topics.get(frame.topic)?.forEach((handler) => handler(frame.msg))
    } else if (frame.op === 'service_response' && typeof frame.id === 'string') {
      this.settle(frame.id, frame.result === true ? { ok: true, values: frame.values } : { ok: false, error: describeFailure(frame.values) })
    }
  }

  private settle(id: string, reply: ServiceReply): void {
    const pending = this.calls.get(id)
    if (!pending) {
      return
    }
    this.calls.delete(id)
    clearTimeout(pending.timer)
    pending.resolve(reply)
  }

  private handleClose(): void {
    for (const id of [...this.calls.keys()]) {
      this.settle(id, { ok: false, error: 'rosbridge와 연결이 끊겨 답을 받지 못했습니다' })
    }
    this.topics.clear()
    if (!this.closed) {
      this.closed = true
      this.handlers.close()
    }
  }
}

function describeFailure(values: unknown): string {
  return typeof values === 'string' && values ? values : '서비스를 부르지 못했습니다'
}

export function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null
}
