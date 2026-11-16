import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { ACK_TIMEOUT_MS, FIRST_RETRY_MS, LONGEST_RETRY_MS, SimLink } from '@/sim/link'
import type { LinkEvents, LinkStatus, SocketLike } from '@/sim/link'
import novaStateJson from '@/test/fixtures/nova.state.json'

/** 假的 WebSocket：记下发了什么，让测试来决定什么时候连上、收到什么、断开。 */
class FakeSocket implements SocketLike {
  onopen: (() => void) | null = null
  onclose: (() => void) | null = null
  onmessage: ((event: { data: unknown }) => void) | null = null
  sent: Record<string, unknown>[] = []
  closed = false

  send(text: string): void {
    this.sent.push(JSON.parse(text))
  }

  close(): void {
    this.closed = true
    this.onclose?.()
  }

  receive(message: unknown): void {
    this.onmessage?.({ data: typeof message === 'string' ? message : JSON.stringify(message) })
  }
}

function setup() {
  const sockets: FakeSocket[] = []
  const statuses: LinkStatus[] = []
  const events = {
    onStatus: vi.fn((status: LinkStatus) => statuses.push(status)),
    onHello: vi.fn(),
    onState: vi.fn(),
    onProblem: vi.fn(),
  } satisfies LinkEvents
  const link = new SimLink('ws://sim/ws', events, (url) => {
    expect(url).toBe('ws://sim/ws')
    const socket = new FakeSocket()
    sockets.push(socket)
    return socket
  })
  /** 连上去，返回这一次的连接。 */
  const open = (): FakeSocket => {
    link.open()
    const socket = sockets.at(-1)!
    socket.onopen?.()
    return socket
  }
  return { link, sockets, statuses, events, open }
}

beforeEach(() => vi.useFakeTimers())
afterEach(() => vi.useRealTimers())

describe('连上和收消息', () => {
  it('先是正在连接，连上以后是已连接', () => {
    const { link, sockets, statuses } = setup()
    link.open()
    expect(statuses).toEqual(['connecting'])
    sockets[0]!.onopen?.()
    expect(statuses).toEqual(['connecting', 'open'])
  })

  it('招呼和状态各交给各的', () => {
    const { open, events } = setup()
    const socket = open()
    socket.receive({ type: 'hello', body: 'nova', episode: 2 })
    socket.receive(novaStateJson)
    expect(events.onHello).toHaveBeenCalledWith({ type: 'hello', body: 'nova', episode: 2 })
    expect(events.onState).toHaveBeenCalledTimes(1)
    expect(events.onState.mock.calls[0]![0].body).toBe('nova')
    expect(events.onProblem).not.toHaveBeenCalled()
  })

  it.each([
    ['不是 JSON', '{ nope', '仿真发来的消息不是 JSON'],
    ['不合规约', '{"type":"hello"}', '仿真发来的消息读不懂'],
  ])('%s的消息：说出问题，连接照常', (_name, text, problem) => {
    const { open, events } = setup()
    const socket = open()
    socket.receive(text)
    expect(events.onProblem.mock.calls[0]![0]).toContain(problem)
    socket.receive({ type: 'hello', body: 'nova', episode: 0 })
    expect(events.onHello).toHaveBeenCalledTimes(1)
  })

  it('不是文字的消息：说出问题', () => {
    const { open, events } = setup()
    open().onmessage?.({ data: new ArrayBuffer(4) })
    expect(events.onProblem).toHaveBeenCalledWith('仿真发来的消息不是文字')
  })
})

describe('发命令', () => {
  it('每条命令带一个新的编号；仿真答复"照做了"就算完成', async () => {
    const { link, open } = setup()
    const socket = open()
    const first = link.send({ type: 'reset' })
    const second = link.send({ type: 'push', direction: 'left', share: 0.04 })
    expect(socket.sent).toEqual([
      { type: 'reset', id: 1 },
      { type: 'push', direction: 'left', share: 0.04, id: 2 },
    ])
    socket.receive({ type: 'ack', id: 1, ok: true, reason: '' })
    socket.receive({ type: 'ack', id: 2, ok: true, reason: '' })
    await expect(first).resolves.toBeUndefined()
    await expect(second).resolves.toBeUndefined()
  })

  it('仿真没有照做：失败，带着仿真说的原因', async () => {
    const { link, open } = setup()
    const socket = open()
    const pushed = link.send({ type: 'push', direction: 'left', share: 0.04 })
    socket.receive({ type: 'ack', id: 1, ok: false, reason: '上一下还没推完' })
    await expect(pushed).rejects.toThrow('上一下还没推完')
  })

  it('答复的顺序和发的顺序不一样：各归各的', async () => {
    const { link, open } = setup()
    const socket = open()
    const first = link.send({ type: 'pause' })
    const second = link.send({ type: 'resume' })
    socket.receive({ type: 'ack', id: 2, ok: false, reason: '仿真出了问题，要先重新开始' })
    socket.receive({ type: 'ack', id: 1, ok: true, reason: '' })
    await expect(first).resolves.toBeUndefined()
    await expect(second).rejects.toThrow('要先重新开始')
  })

  it('同一个答复来两次、不认识的编号、没有编号的答复：都不出错', async () => {
    const { link, open, events } = setup()
    const socket = open()
    const sent = link.send({ type: 'reset' })
    socket.receive({ type: 'ack', id: 1, ok: true, reason: '' })
    socket.receive({ type: 'ack', id: 1, ok: false, reason: '重复的' })
    socket.receive({ type: 'ack', id: 99, ok: true, reason: '' })
    socket.receive({ type: 'ack', id: null, ok: false, reason: '命令读不出来' })
    await expect(sent).resolves.toBeUndefined()
    expect(events.onProblem).not.toHaveBeenCalled()
  })

  it('3 秒没有答复：失败。之后才到的答复不算', async () => {
    const { link, open } = setup()
    const socket = open()
    const sent = link.send({ type: 'reset' })
    const outcome = expect(sent).rejects.toThrow('仿真没有答复')
    vi.advanceTimersByTime(ACK_TIMEOUT_MS)
    await outcome
    socket.receive({ type: 'ack', id: 1, ok: true, reason: '' })
  })

  it('差一点到 3 秒时答复来了：算完成', async () => {
    const { link, open } = setup()
    const socket = open()
    const sent = link.send({ type: 'reset' })
    vi.advanceTimersByTime(ACK_TIMEOUT_MS - 1)
    socket.receive({ type: 'ack', id: 1, ok: true, reason: '' })
    await expect(sent).resolves.toBeUndefined()
  })

  it('还没连上的时候发：马上失败，什么也不发', async () => {
    const { link, sockets } = setup()
    await expect(link.send({ type: 'reset' })).rejects.toThrow('还没连上仿真')
    link.open()
    await expect(link.send({ type: 'reset' })).rejects.toThrow('还没连上仿真')
    expect(sockets[0]!.sent).toEqual([])
  })

  it('等答复的时候连接断了：等着的命令都失败', async () => {
    const { link, open } = setup()
    const socket = open()
    const first = link.send({ type: 'reset' })
    const second = link.send({ type: 'pause' })
    socket.onclose?.()
    await expect(first).rejects.toThrow('和仿真的连接断了')
    await expect(second).rejects.toThrow('和仿真的连接断了')
  })
})

describe('断了再连', () => {
  it('断了以后过 0.5 秒自己再连；连不上就隔得越来越久，最久 5 秒', () => {
    const { open, sockets, statuses } = setup()
    open().onclose?.()
    expect(statuses.at(-1)).toBe('closed')
    const waits = [FIRST_RETRY_MS, 1000, 2000, 4000, LONGEST_RETRY_MS, LONGEST_RETRY_MS]
    waits.forEach((wait, index) => {
      vi.advanceTimersByTime(wait - 1)
      expect(sockets.length).toBe(index + 1)
      vi.advanceTimersByTime(1)
      expect(sockets.length).toBe(index + 2)
      sockets.at(-1)!.onclose?.()
    })
  })

  it('连上以后，下一次断了又从 0.5 秒开始等', () => {
    const { open, sockets } = setup()
    open().onclose?.()
    vi.advanceTimersByTime(FIRST_RETRY_MS)
    sockets[1]!.onclose?.()
    vi.advanceTimersByTime(1000)
    sockets[2]!.onopen?.()
    sockets[2]!.onclose?.()
    vi.advanceTimersByTime(FIRST_RETRY_MS)
    expect(sockets.length).toBe(4)
  })

  it('"再连一次"：不等了，马上连；已经连着或者正在连的时候不重复连', () => {
    const { link, open, sockets } = setup()
    const socket = open()
    link.retryNow()
    expect(sockets.length).toBe(1)
    socket.onclose?.()
    link.retryNow()
    expect(sockets.length).toBe(2)
    link.retryNow()
    expect(sockets.length).toBe(2)
    vi.advanceTimersByTime(LONGEST_RETRY_MS)
    expect(sockets.length).toBe(2)
  })

  it('自己关掉的：不再重连，"再连一次"也不连', () => {
    const { link, open, sockets, statuses } = setup()
    const socket = open()
    link.close()
    expect(socket.closed).toBe(true)
    expect(statuses.at(-1)).toBe('closed')
    vi.advanceTimersByTime(60_000)
    link.retryNow()
    expect(sockets.length).toBe(1)
  })

  it('等着重连的时候关掉：不再连', () => {
    const { link, open, sockets } = setup()
    open().onclose?.()
    link.close()
    vi.advanceTimersByTime(60_000)
    expect(sockets.length).toBe(1)
  })
})
