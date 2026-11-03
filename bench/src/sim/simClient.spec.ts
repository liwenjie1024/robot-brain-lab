import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { stateMessage } from '@/test/fixtures'
import type { ShotMessage, StateMessage } from './generated/message'
import type { SceneDescription } from './generated/scene'
import { type CombatEvent, type ConnectionPhase, SimClient } from './simClient'

class FakeSocket {
  static instances: FakeSocket[] = []
  readyState = 0
  sent: string[] = []
  onopen: (() => void) | null = null
  onmessage: ((event: { data: unknown }) => void) | null = null
  onclose: (() => void) | null = null

  constructor(readonly url: string) {
    FakeSocket.instances.push(this)
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

  lastSent(): Record<string, unknown> {
    return JSON.parse(this.sent.at(-1)!)
  }
}

const SCENE = { robot: { name: 'BL-01', description: '', height: 16 }, movingBodies: [1], geoms: [] } as unknown as SceneDescription

const STATE: StateMessage = stateMessage()

let clock = 0
let phases: ConnectionPhase[] = []

function createClient(fetchFn: typeof fetch = async () => new Response(JSON.stringify(SCENE))) {
  const client = new SimClient({
    baseUrl: '/sim',
    createSocket: (url) => new FakeSocket(url) as unknown as WebSocket,
    fetchFn,
    now: () => clock,
    reconnectDelaysMs: [100, 300],
    commandTimeoutMs: 1000,
  })
  client.on('phase', (phase) => phases.push(phase))
  return client
}

async function connected(client = createClient()) {
  await client.connect()
  const socket = FakeSocket.instances.at(-1)!
  socket.open()
  return { client, socket }
}

beforeEach(() => {
  vi.useFakeTimers()
  FakeSocket.instances = []
  clock = 0
  phases = []
})

afterEach(() => {
  vi.useRealTimers()
})

describe('SimClient 연결', () => {
  it('모양을 먼저 받은 뒤 WebSocket으로 붙는다', async () => {
    const scenes: SceneDescription[] = []
    const client = createClient()
    client.on('scene', (scene) => scenes.push(scene))

    await connected(client)

    expect(scenes).toEqual([SCENE])
    expect(FakeSocket.instances[0]!.url).toMatch(/^ws:\/\/.+\/sim\/ws$/)
    expect(phases).toEqual(['loading-scene', 'connecting', 'open'])
  })

  it('모양을 못 받으면 연결 못 함으로 알리고 붙지 않는다', async () => {
    const client = createClient(async () => new Response('', { status: 502 }))

    await client.connect()

    expect(phases.at(-1)).toBe('failed')
    expect(FakeSocket.instances).toHaveLength(0)
  })

  it('끊기면 기다렸다가 다시 붙고, 다시 붙으면 기다리는 간격을 처음부터 센다', async () => {
    const { socket } = await connected()

    socket.close()
    expect(phases.at(-1)).toBe('reconnecting')
    vi.advanceTimersByTime(99)
    expect(FakeSocket.instances).toHaveLength(1)
    vi.advanceTimersByTime(1)
    FakeSocket.instances[1]!.close()
    vi.advanceTimersByTime(300)
    FakeSocket.instances[2]!.open()
    FakeSocket.instances[2]!.close()
    vi.advanceTimersByTime(100)

    expect(FakeSocket.instances).toHaveLength(4)
    expect(phases.at(-1)).toBe('reconnecting')
  })

  it('직접 닫으면 다시 붙지 않는다', async () => {
    const { client } = await connected()

    client.close()
    vi.advanceTimersByTime(10_000)

    expect(FakeSocket.instances).toHaveLength(1)
  })
})

describe('SimClient 상태', () => {
  it('규약에 맞는 상태를 알린다', async () => {
    const { client, socket } = await connected()
    const states: StateMessage[] = []
    client.on('state', (state) => states.push(state))

    socket.receive(STATE)

    expect(states).toEqual([STATE])
  })

  it.each([
    ['JSON이 아님', '{상태'],
    ['필드가 빠짐', { type: 'state', seq: 1 }],
    ['모르는 비행 모드', { ...STATE, mecha: { ...STATE.mecha, mode: 'hovering' } }],
    ['사격에 시작점이 없음', { type: 'shot', simTime: 1, shooter: 'mecha', to: [0, 0, 0] }],
    ['모르는 종류', { type: 'hello' }],
  ])('경계에서 규약과 다른 메시지(%s)는 버리고 센다', async (_, message) => {
    const { client, socket } = await connected()
    const states: StateMessage[] = []
    const invalid: string[] = []
    client.on('state', (state) => states.push(state))
    client.on('invalidMessage', (reason) => invalid.push(reason))

    socket.receive(message)

    expect(states).toHaveLength(0)
    expect(invalid).toHaveLength(1)
  })
})

describe('SimClient 전투 사건', () => {
  it('사격·격파 사건은 빠짐없이 받은 순서대로 알린다', async () => {
    const { client, socket } = await connected()
    const events: CombatEvent[] = []
    client.on('combat', (event) => events.push(event))
    const shot: ShotMessage = {
      type: 'shot',
      simTime: 3.2,
      shooter: 'mecha',
      from: [0, 0, 30],
      to: [150, 0, 25],
      hit: { unit: 'drone-1', damage: 30, blocked: false },
    }

    socket.receive(shot)
    socket.receive({ type: 'destroyed', simTime: 3.2, unit: 'drone-1' })

    expect(events.map((event) => event.type)).toEqual(['shot', 'destroyed'])
    expect(events[0]).toEqual(shot)
  })
})

describe('SimClient 명령', () => {
  it('명령에 번호를 붙여 보내고, 받았다는 답이 오면 걸린 시간과 함께 끝난다', async () => {
    const { client, socket } = await connected()

    const result = client.send({ type: 'velocity', forward: 20, sideways: 0, up: 0, turn: 0 })
    const sent = socket.lastSent()
    clock = 23
    socket.receive({ type: 'ack', id: sent.id, commandType: 'velocity', simTime: 1.2 })

    expect(sent).toMatchObject({ type: 'velocity', forward: 20, id: expect.stringMatching(/^bench-/) })
    await expect(result).resolves.toEqual({ id: sent.id, accepted: true, reason: undefined, roundTripMs: 23 })
  })

  it('거절되면 까닭을 돌려준다', async () => {
    const { client, socket } = await connected()

    const result = client.send({ type: 'velocity', forward: 90, sideways: 0, up: 0, turn: 0 })
    socket.receive({ type: 'rejected', id: socket.lastSent().id, reason: '앞뒤 속도 9이(가) 범위를 벗어났습니다' })

    await expect(result).resolves.toMatchObject({ accepted: false, reason: '앞뒤 속도 9이(가) 범위를 벗어났습니다' })
  })

  it('실패: 답이 없으면 시간이 지나 실패로 끝난다', async () => {
    const { client } = await connected()

    const result = client.send({ type: 'stop' })
    vi.advanceTimersByTime(1000)

    await expect(result).resolves.toMatchObject({ accepted: false, reason: '답이 없습니다 (시간 초과)' })
  })

  it('실패: 연결되지 않았으면 보내지 않고 바로 실패를 돌려준다', async () => {
    const client = createClient()

    await expect(client.send({ type: 'stop' })).resolves.toMatchObject({
      accepted: false,
      reason: '몸과 연결되어 있지 않습니다',
    })
  })

  it('연결이 끊기면 답을 기다리던 명령은 실패로 끝난다', async () => {
    const { client, socket } = await connected()

    const result = client.send({ type: 'reset' })
    socket.close()

    await expect(result).resolves.toMatchObject({ accepted: false, reason: '연결이 끊겨 답을 받지 못했습니다' })
  })

  it('중복: 같은 답이 두 번 오거나 모르는 번호의 답이 와도 한 번만 끝난다', async () => {
    const { client, socket } = await connected()
    const results: boolean[] = []

    void client.send({ type: 'stop' }).then((result) => results.push(result.accepted))
    const id = socket.lastSent().id
    socket.receive({ type: 'ack', id, commandType: 'stop', simTime: 1 })
    socket.receive({ type: 'rejected', id, reason: '늦게 온 답' })
    socket.receive({ type: 'ack', id: 'bench-999', commandType: 'stop', simTime: 1 })
    await vi.runAllTimersAsync()

    expect(results).toEqual([true])
  })

  it('순서: 답이 보낸 순서와 다르게 와도 번호로 제 명령을 찾는다', async () => {
    const { client, socket } = await connected()

    const first = client.send({ type: 'stop' })
    const firstId = socket.lastSent().id
    const second = client.send({ type: 'reset' })
    const secondId = socket.lastSent().id
    socket.receive({ type: 'rejected', id: secondId, reason: '두 번째 거절' })
    socket.receive({ type: 'ack', id: firstId, commandType: 'stop', simTime: 1 })

    await expect(first).resolves.toMatchObject({ id: firstId, accepted: true })
    await expect(second).resolves.toMatchObject({ id: secondId, accepted: false, reason: '두 번째 거절' })
  })
})
