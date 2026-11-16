import { describe, expect, it, vi } from 'vitest'
import { SHOW_EVERY_MS } from '@/sim/display'
import type { SocketLike } from '@/sim/link'
import { createSim } from '@/sim/useSim'
import g1SceneJson from '@/test/fixtures/g1.scene.json'
import g1StateJson from '@/test/fixtures/g1.state.json'
import novaSceneJson from '@/test/fixtures/nova.scene.json'
import novaStateJson from '@/test/fixtures/nova.state.json'
import { triangleMeshBytes } from '@/test/samples'

class FakeSocket implements SocketLike {
  onopen: (() => void) | null = null
  onclose: (() => void) | null = null
  onmessage: ((event: { data: unknown }) => void) | null = null
  sent: Record<string, unknown>[] = []

  send(text: string): void {
    this.sent.push(JSON.parse(text))
  }

  close(): void {
    this.onclose?.()
  }

  receive(message: unknown): void {
    this.onmessage?.({ data: JSON.stringify(message) })
  }
}

interface Served {
  scene: unknown
  /** 拿"样子"的时候要不要失败一次。 */
  failScene?: boolean
  sceneStatus?: number
}

/** 假的仿真：一个连接，和一个按网址给东西的 fetch。 */
function setup(served: Served = { scene: novaSceneJson }) {
  const sockets: FakeSocket[] = []
  const asked: string[] = []
  let clock = 1000
  const request = vi.fn(async (input: RequestInfo | URL) => {
    const url = String(input)
    asked.push(url)
    if (url === '/sim/scene') {
      if (served.failScene) throw new Error('网络不通')
      return new Response(JSON.stringify(served.scene), { status: served.sceneStatus ?? 200 })
    }
    if (url.startsWith('/sim/mesh/')) return new Response(triangleMeshBytes())
    return new Response('', { status: 404 })
  }) as unknown as typeof fetch
  const sim = createSim({
    socketUrl: 'ws://test/sim/ws',
    makeSocket: () => {
      const socket = new FakeSocket()
      sockets.push(socket)
      return socket
    },
    request,
    now: () => clock,
  })
  sim.start()
  const socket = sockets[0]!
  socket.onopen?.()
  return {
    sim,
    socket,
    sockets,
    asked,
    served,
    tick: (ms: number) => (clock += ms),
    /** 等拿"样子"和网格的那几步都走完。 */
    settle: () => vi.waitFor(() => expect(sim.loading.value).toBeNull()),
  }
}

const hello = (body: string) => ({ type: 'hello', body, episode: 0 })

describe('刚连上', () => {
  it('收到招呼就去拿身体的样子；拿到之前没有样子、没有状态', async () => {
    const { sim, socket, asked, settle } = setup()
    expect(sim.link.value).toBe('open')
    expect(sim.stale.value).toBe(false)
    expect(sim.scene.value).toBeNull()
    socket.receive(hello('nova'))
    expect(sim.loading.value).toEqual({ done: 0, total: 1 })
    await settle()
    expect(asked).toEqual(['/sim/scene'])
    expect(sim.scene.value!.name).toBe('Nova（核心版）')
    expect(sim.sceneError.value).toBeNull()
    expect(sim.shown.value).toBeNull()
    expect(sim.latest()).toBeNull()
  })

  it('基线：样子拿到以后把 35 个网格都拿来，才算拿到', async () => {
    const { sim, socket, asked, settle } = setup({ scene: g1SceneJson })
    socket.receive(hello('g1'))
    await settle()
    expect(asked.filter((url) => url.startsWith('/sim/mesh/')).length).toBe(35)
    expect(sim.meshes.value.size).toBe(35)
    expect(sim.scene.value!.body).toBe('g1')
  })

  it('样子还在路上时来的状态：先不用（它和手里的样子对不上）；样子到了，后面的状态就用', async () => {
    const { sim, socket, settle } = setup()
    socket.receive(hello('nova'))
    socket.receive(novaStateJson)
    expect(sim.shown.value).toBeNull()
    expect(sim.latest()).toBeNull()
    await settle()
    expect(sim.shown.value!.body).toBe('nova')
    expect(sim.latest()!.time_s).toBe(novaStateJson.time_s)
  })

  it('没有招呼、先来了状态：也照样去拿样子，只拿一次', async () => {
    const { sim, socket, asked, settle } = setup()
    socket.receive(novaStateJson)
    socket.receive(novaStateJson)
    await settle()
    expect(asked).toEqual(['/sim/scene'])
    expect(sim.scene.value!.body).toBe('nova')
  })
})

describe('状态', () => {
  it('3D 用的每一条都是最新的；画面上的数隔 0.1 秒换一次', async () => {
    const { sim, socket, settle, tick } = setup()
    socket.receive(hello('nova'))
    await settle()
    socket.receive({ ...novaStateJson, time_s: 1.0 })
    expect(sim.shown.value!.time_s).toBe(1.0)
    tick(SHOW_EVERY_MS / 2)
    socket.receive({ ...novaStateJson, time_s: 1.03 })
    expect(sim.latest()!.time_s).toBe(1.03)
    expect(sim.shown.value!.time_s).toBe(1.0)
    tick(SHOW_EVERY_MS / 2)
    socket.receive({ ...novaStateJson, time_s: 1.06 })
    expect(sim.shown.value!.time_s).toBe(1.06)
  })

  it('倒了这样的变化马上显示，不等', async () => {
    const { sim, socket, settle, tick } = setup()
    socket.receive(hello('nova'))
    await settle()
    socket.receive(novaStateJson)
    tick(1)
    socket.receive({ ...novaStateJson, fallen: true })
    expect(sim.shown.value!.fallen).toBe(true)
  })

  it('读不懂的消息：记下问题；下一次招呼来了就清掉', async () => {
    const { sim, socket } = setup()
    socket.receive({ type: 'state', body: 'nova' })
    expect(sim.problem.value).toContain('仿真发来的消息读不懂')
    socket.receive(hello('nova'))
    expect(sim.problem.value).toBeNull()
  })
})

describe('换身体', () => {
  it('状态说测试台上换成了别的身体：去拿新的样子；拿到之前不用新身体的状态，画面上不留旧身体的数', async () => {
    const { sim, socket, served, settle } = setup()
    socket.receive(hello('nova'))
    await settle()
    socket.receive(novaStateJson)
    expect(sim.shown.value!.body).toBe('nova')
    served.scene = g1SceneJson
    socket.receive(g1StateJson)
    expect(sim.loading.value).not.toBeNull()
    expect(sim.latest()).toBeNull()
    await settle()
    expect(sim.scene.value!.body).toBe('g1')
    expect(sim.shown.value!.body).toBe('g1')
    expect(sim.latest()!.body).toBe('g1')
  })

  it('拿的中间又换回去了：只留最后要的那个', async () => {
    const { sim, socket, served, settle } = setup({ scene: g1SceneJson })
    socket.receive(hello('g1'))
    served.scene = novaSceneJson
    socket.receive(novaStateJson)
    await settle()
    await vi.waitFor(() => expect(sim.scene.value?.body).toBe('nova'))
    expect(sim.meshes.value.size).toBe(0)
  })
})

describe('样子没拿到', () => {
  it('网络不通：记下原因，不反复去拿；点"再试一次"才再拿', async () => {
    const { sim, socket, asked, served } = setup({ scene: novaSceneJson, failScene: true })
    socket.receive(hello('nova'))
    await vi.waitFor(() => expect(sim.sceneError.value).toBe('网络不通'))
    expect(sim.loading.value).toBeNull()
    socket.receive(novaStateJson)
    socket.receive(novaStateJson)
    expect(asked).toEqual(['/sim/scene'])
    served.failScene = false
    sim.retryScene()
    expect(sim.sceneError.value).toBeNull()
    await vi.waitFor(() => expect(sim.scene.value?.body).toBe('nova'))
    expect(asked).toEqual(['/sim/scene', '/sim/scene'])
  })

  it('仿真答的不是 200：说出来', async () => {
    const { sim, socket } = setup({ scene: {}, sceneStatus: 500 })
    socket.receive(hello('nova'))
    await vi.waitFor(() => expect(sim.sceneError.value).toBe('仿真没有给出身体的样子（500）'))
  })

  it('仿真给的样子不合规约：说出来，不用它', async () => {
    const { sim, socket } = setup({ scene: { body: 'nova' } })
    socket.receive(hello('nova'))
    await vi.waitFor(() => expect(sim.sceneError.value).toContain('身体的样子读不懂'))
    expect(sim.scene.value).toBeNull()
  })
})

describe('连接断了', () => {
  it('断了以后数是旧的：标出来；样子和最后的状态还留着', async () => {
    const { sim, socket, settle } = setup()
    socket.receive(hello('nova'))
    await settle()
    socket.receive(novaStateJson)
    socket.onclose?.()
    expect(sim.link.value).toBe('closed')
    expect(sim.stale.value).toBe(true)
    expect(sim.scene.value).not.toBeNull()
    expect(sim.shown.value).not.toBeNull()
  })

  it('"再连一次"马上重连；关掉以后不再连', () => {
    const { sim, socket, sockets } = setup()
    socket.onclose?.()
    sim.retryLink()
    expect(sockets.length).toBe(2)
    expect(sim.link.value).toBe('connecting')
    sim.stop()
    sim.retryLink()
    expect(sockets.length).toBe(2)
  })
})

describe('命令', () => {
  it('每个操作发出规约里的那条命令', async () => {
    const { sim, socket } = setup()
    const answer = (id: number) => socket.receive({ type: 'ack', id, ok: true, reason: '' })
    const all = [
      sim.reset(),
      sim.pause(),
      sim.resume(),
      sim.setControl(false),
      sim.pushBody('backward', 0.08),
      sim.selectBody('g1'),
    ]
    for (let id = 1; id <= all.length; id++) answer(id)
    await Promise.all(all)
    expect(socket.sent).toEqual([
      { type: 'reset', id: 1 },
      { type: 'pause', id: 2 },
      { type: 'resume', id: 3 },
      { type: 'control', on: false, id: 4 },
      { type: 'push', direction: 'backward', share: 0.08, id: 5 },
      { type: 'body', body: 'g1', id: 6 },
    ])
  })

  it('仿真没照做：带着原因失败', async () => {
    const { sim, socket } = setup()
    const pushed = sim.pushBody('left', 0.04)
    socket.receive({ type: 'ack', id: 1, ok: false, reason: '暂停着的时候推不了，先点继续' })
    await expect(pushed).rejects.toThrow('暂停着的时候推不了')
  })
})
