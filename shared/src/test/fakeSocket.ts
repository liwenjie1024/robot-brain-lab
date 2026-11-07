/** 시험용 WebSocket: 보낸 것을 모으고, 열기·받기·끊기를 시험이 정한 때에 일으킨다 */
export class FakeSocket {
  static instances: FakeSocket[] = []
  readyState = 0
  sent: string[] = []
  onopen: (() => void) | null = null
  onmessage: ((event: { data: unknown }) => void) | null = null
  onclose: (() => void) | null = null

  constructor(readonly url: string) {
    FakeSocket.instances.push(this)
  }

  static create = (url: string): WebSocket => new FakeSocket(url) as unknown as WebSocket

  static latest(): FakeSocket {
    const socket = FakeSocket.instances.at(-1)
    if (!socket) {
      throw new Error('아직 만든 소켓이 없다')
    }
    return socket
  }

  send(text: string) {
    this.sent.push(text)
  }

  close() {
    this.readyState = 3
    this.onclose?.()
  }

  open() {
    this.readyState = 1
    this.onopen?.()
  }

  receive(message: unknown) {
    this.onmessage?.({ data: typeof message === 'string' ? message : JSON.stringify(message) })
  }

  sentFrames(): Record<string, unknown>[] {
    return this.sent.map((text) => JSON.parse(text))
  }

  lastSent(): Record<string, unknown> {
    return JSON.parse(this.sent.at(-1)!)
  }
}
