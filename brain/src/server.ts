import { type WebSocket, WebSocketServer } from 'ws'
import type { BrainMessage } from '@shared/brain/generated/status'
import { STATUS_INTERVAL_MS } from './config'
import { applyControl } from './controls'
import type { System1 } from './system1'

/** 지시 하나는 수백 바이트다. 큰 메시지는 경계에서 끊는다. */
const MAX_CONTROL_BYTES = 4096

/** 화면이 붙는 곳: 두뇌의 상태(1초에 5번)와 판단 기록(생길 때마다)을 보내고, 지시를 받는다. */
export class BrainServer {
  private server: WebSocketServer | null = null
  private timer: ReturnType<typeof setInterval> | null = null
  private stopLog: (() => void) | null = null

  constructor(
    private readonly system1: System1,
    private readonly knownTargets: () => ReadonlySet<string>,
  ) {}

  start(port: number): Promise<number> {
    return new Promise((resolve, reject) => {
      const server = new WebSocketServer({ port, maxPayload: MAX_CONTROL_BYTES })
      server.once('error', reject)
      server.once('listening', () => {
        const address = server.address()
        resolve(typeof address === 'object' && address ? address.port : port)
      })
      server.on('connection', (socket) => this.welcome(socket))
      this.server = server
      this.stopLog = this.system1.log.onDecision((decision) => this.broadcast(decision))
      this.timer = setInterval(() => this.broadcast(this.system1.status()), STATUS_INTERVAL_MS)
    })
  }

  close(): Promise<void> {
    if (this.timer) {
      clearInterval(this.timer)
    }
    this.stopLog?.()
    return new Promise((resolve) => {
      if (!this.server) {
        resolve()
        return
      }
      for (const client of this.server.clients) {
        client.terminate()
      }
      this.server.close(() => resolve())
    })
  }

  private welcome(socket: WebSocket): void {
    send(socket, this.system1.status())
    for (const decision of this.system1.log.recent()) {
      send(socket, decision)
    }
    socket.on('message', (data, isBinary) => {
      const reply = isBinary
        ? { type: 'controlResult' as const, accepted: false, reason: '지시는 글자(JSON)로 보내야 합니다' }
        : applyControl(data.toString(), this.system1, this.knownTargets())
      send(socket, reply)
      if (reply.accepted) {
        this.broadcast(this.system1.status())
      }
    })
  }

  private broadcast(message: BrainMessage): void {
    for (const client of this.server?.clients ?? []) {
      send(client, message)
    }
  }
}

function send(socket: WebSocket, message: BrainMessage): void {
  if (socket.readyState === socket.OPEN) {
    socket.send(JSON.stringify(message))
  }
}
