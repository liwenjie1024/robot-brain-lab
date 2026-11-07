import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { SceneDescription } from '../sim/generated/scene'
import type { CombatEvent, ConnectionPhase } from '../sim/simClient'
import { FakeSocket } from '../test/fakeSocket'
import { sceneDescription, stateMessage } from '../test/fixtures'
import { rosDestroyed, rosSceneReply, rosShot, rosState, shotMessage } from '../test/rosFixtures'
import { RosBodyClient } from './rosBodyClient'

const SCENE_POLL_MS = 1000
const COMMAND_TIMEOUT_MS = 1000

let clock = 0
let phases: { phase: ConnectionPhase; detail?: string }[] = []
let scenes: SceneDescription[] = []
let states: number[] = []
let combats: CombatEvent[] = []
let invalid: string[] = []

function createClient() {
  const client = new RosBodyClient({
    url: 'ws://ros:9090',
    createSocket: FakeSocket.create,
    now: () => clock,
    reconnectDelaysMs: [100, 300],
    commandTimeoutMs: COMMAND_TIMEOUT_MS,
    scenePollMs: SCENE_POLL_MS,
  })
  client.on('phase', (phase, detail) => phases.push({ phase, detail }))
  client.on('scene', (scene) => scenes.push(scene))
  client.on('state', (state) => states.push(state.seq))
  client.on('combat', (event) => combats.push(event))
  client.on('invalidMessage', (reason) => invalid.push(reason))
  return client
}

function frames(socket: FakeSocket, op: string) {
  return socket.sentFrames().filter((frame) => frame.op === op)
}

/** 마지막으로 부른 서비스에 답한다 */
function reply(socket: FakeSocket, values: unknown, result = true) {
  const call = frames(socket, 'call_service').at(-1)!
  socket.receive({ op: 'service_response', id: call.id, service: call.service, result, values })
}

/** rosbridge에 붙고, 드라이버가 몸과 붙어 장면 설명을 준다 */
async function opened(client = createClient()) {
  client.connect()
  const socket = FakeSocket.latest()
  socket.open()
  reply(socket, rosSceneReply())
  await vi.waitFor(() => expect(phases.at(-1)?.phase).toBe('open'))
  return { client, socket }
}

beforeEach(() => {
  vi.useFakeTimers()
  FakeSocket.instances = []
  clock = 0
  phases = []
  scenes = []
  states = []
  combats = []
  invalid = []
})

afterEach(() => {
  vi.useRealTimers()
})

describe('RosBodyClient 연결', () => {
  it('rosbridge에 붙으면 붙음 토픽을 받고 장면 설명을 물어, 받으면 상태·사건 토픽을 받고 열린다', async () => {
    const { socket } = await opened()

    expect(scenes).toEqual([sceneDescription()])
    expect(frames(socket, 'subscribe').map((frame) => frame.topic)).toEqual(['/bl01/link', '/bl01/state', '/bl01/combat'])
    expect(frames(socket, 'call_service')[0]).toMatchObject({ service: '/bl01/get_scene', type: 'bl01_msgs/srv/GetScene' })
    expect(phases.map((item) => item.phase)).toEqual(['loading-scene', 'open'])
  })

  it('드라이버가 아직 몸에 붙지 못했으면(available false) 까닭을 알리고 정한 간격 뒤 다시 묻는다 (같은 까닭은 한 번만 알림)', async () => {
    const client = createClient()
    client.connect()
    const socket = FakeSocket.latest()
    socket.open()

    reply(socket, rosSceneReply(false))
    await vi.advanceTimersByTimeAsync(SCENE_POLL_MS)
    reply(socket, rosSceneReply(false))
    await vi.advanceTimersByTimeAsync(SCENE_POLL_MS)
    reply(socket, rosSceneReply())
    await vi.waitFor(() => expect(scenes).toHaveLength(1))

    expect(frames(socket, 'call_service')).toHaveLength(3)
    expect(phases).toEqual([
      { phase: 'loading-scene', detail: undefined },
      { phase: 'connecting', detail: 'ROS 2 드라이버가 아직 몸(시뮬레이터)에 붙지 못했습니다' },
      { phase: 'open', detail: undefined },
    ])
  })

  it('실패: 장면 설명이 JSON이 아니거나 규약과 다르면 붙지 않고 다시 묻는다', async () => {
    const client = createClient()
    client.connect()
    const socket = FakeSocket.latest()
    socket.open()

    reply(socket, { available: true, scene_json: '{not json' })
    await vi.advanceTimersByTimeAsync(SCENE_POLL_MS)
    reply(socket, { available: true, scene_json: JSON.stringify({ robot: {} }) })
    await vi.advanceTimersByTimeAsync(0)

    expect(scenes).toEqual([])
    expect(phases.at(-1)?.phase).toBe('connecting')
  })

  it('중복: 장면 설명을 묻는 동안 붙음 토픽이 와도 한 번만 묻는다', async () => {
    const client = createClient()
    client.connect()
    const socket = FakeSocket.latest()
    socket.open()

    socket.receive({ op: 'publish', topic: '/bl01/link', msg: { data: true } })
    socket.receive({ op: 'publish', topic: '/bl01/link', msg: { data: true } })
    reply(socket, rosSceneReply())
    await vi.waitFor(() => expect(scenes).toHaveLength(1))
    socket.receive({ op: 'publish', topic: '/bl01/link', msg: { data: true } })

    expect(frames(socket, 'call_service')).toHaveLength(1)
  })

  it('드라이버와 몸이 끊기면 명령을 막고 다시 붙는 중으로 알리며, 다시 붙으면 장면 설명부터 다시 받는다 (토픽은 다시 subscribe하지 않음)', async () => {
    const { client, socket } = await opened()

    socket.receive({ op: 'publish', topic: '/bl01/link', msg: { data: false } })
    const blocked = await client.send({ type: 'fire' })
    socket.receive({ op: 'publish', topic: '/bl01/link', msg: { data: true } })
    reply(socket, rosSceneReply())
    await vi.waitFor(() => expect(scenes).toHaveLength(2))

    expect(blocked).toMatchObject({ accepted: false, reason: '몸과 연결되어 있지 않습니다' })
    expect(phases.map((item) => item.phase)).toEqual(['loading-scene', 'open', 'reconnecting', 'open'])
    expect(phases[2]?.detail).toBe('ROS 2 드라이버와 몸(시뮬레이터)의 연결이 끊겼습니다')
    expect(frames(socket, 'subscribe')).toHaveLength(3)
  })

  it('rosbridge와 끊기면 정한 간격 뒤 다시 붙어 토픽을 다시 받는다', async () => {
    const { socket } = await opened()

    socket.close()
    expect(phases.at(-1)).toEqual({ phase: 'reconnecting', detail: 'rosbridge와 연결이 끊겼습니다. 0.1초 뒤 다시 붙습니다.' })
    await vi.advanceTimersByTimeAsync(100)
    const next = FakeSocket.latest()
    next.open()
    reply(next, rosSceneReply())
    await vi.waitFor(() => expect(scenes).toHaveLength(2))

    expect(FakeSocket.instances).toHaveLength(2)
    expect(frames(next, 'subscribe').map((frame) => frame.topic)).toEqual(['/bl01/link', '/bl01/state', '/bl01/combat'])
    expect(phases.at(-1)?.phase).toBe('open')
  })

  it('close()로 닫으면 다시 붙지 않는다', async () => {
    const { client } = await opened()

    client.close()
    await vi.advanceTimersByTimeAsync(10_000)

    expect(FakeSocket.instances).toHaveLength(1)
  })

  it('retry()는 기다리지 않고 바로 새로 붙는다', async () => {
    const { client } = await opened()

    client.retry()

    expect(FakeSocket.instances).toHaveLength(2)
    expect(phases.at(-1)?.phase).toBe('loading-scene')
  })
})

describe('RosBodyClient 상태·사건', () => {
  it('상태 토픽을 규약 모양으로 바꿔 넘긴다', async () => {
    const { socket } = await opened()

    socket.receive({ op: 'publish', topic: '/bl01/state', msg: rosState(stateMessage({ seq: 7 })) })
    socket.receive({ op: 'publish', topic: '/bl01/state', msg: rosState(stateMessage({ seq: 8 })) })

    expect(states).toEqual([7, 8])
  })

  it('사격·격파 사건을 규약 모양으로 넘긴다', async () => {
    const { socket } = await opened()

    socket.receive({ op: 'publish', topic: '/bl01/combat', msg: rosShot(shotMessage()) })
    socket.receive({ op: 'publish', topic: '/bl01/combat', msg: rosDestroyed('drone-1', 4) })

    expect(combats).toEqual([shotMessage(), { type: 'destroyed', simTime: 4, unit: 'drone-1' }])
  })

  it('실패: 모양이 다른 상태나 규약과 다른 값은 버리고 알린다 (다음 상태는 그대로 받는다)', async () => {
    const { socket } = await opened()
    const wrongMode = rosState(stateMessage({ seq: 1 }))
    wrongMode.mecha.mode = 'swimming' as never

    socket.receive({ op: 'publish', topic: '/bl01/state', msg: { seq: 1 } })
    socket.receive({ op: 'publish', topic: '/bl01/state', msg: wrongMode })
    socket.receive({ op: 'publish', topic: '/bl01/state', msg: rosState(stateMessage({ seq: 2 })) })

    expect(states).toEqual([2])
    expect(invalid).toHaveLength(2)
    expect(invalid[0]).toBe('ROS 메시지의 모양이 BL-01 메시지와 다름')
  })
})

describe('RosBodyClient 명령', () => {
  it('명령을 서비스로 부르고, 받으면 accepted와 왕복 시간을 돌려준다', async () => {
    const { client, socket } = await opened()

    const result = client.send({ type: 'aim', unit: 'drone-1' })
    clock = 4
    reply(socket, { accepted: true, reason: '' })

    await expect(result).resolves.toEqual({ id: 'ros-1', accepted: true, roundTripMs: 4 })
    expect(frames(socket, 'call_service').at(-1)).toMatchObject({ service: '/bl01/aim', args: { unit: 'drone-1' } })
  })

  it('실패: 몸이 거절하면 까닭을 그대로 돌려준다', async () => {
    const { client, socket } = await opened()

    const result = client.send({ type: 'fire' })
    reply(socket, { accepted: false, reason: '식는 중입니다 (0.3초 남음)' })

    await expect(result).resolves.toMatchObject({ accepted: false, reason: '식는 중입니다 (0.3초 남음)' })
  })

  it('실패: 서비스 답이 없으면 시간 초과, 답 모양이 다르면 그 까닭으로 끝난다', async () => {
    const { client, socket } = await opened()

    const timedOut = client.send({ type: 'fire' })
    await vi.advanceTimersByTimeAsync(COMMAND_TIMEOUT_MS)
    const malformed = client.send({ type: 'stop' })
    reply(socket, { ok: 1 })

    await expect(timedOut).resolves.toMatchObject({ accepted: false, reason: '/bl01/fire이(가) 답하지 않습니다 (시간 초과)' })
    await expect(malformed).resolves.toMatchObject({ accepted: false, reason: '/bl01/stop의 답 모양이 규약과 다릅니다' })
  })

  it('실패: 몸과 붙기 전에는 보내지 않고 바로 거절한다', async () => {
    const client = createClient()
    client.connect()
    FakeSocket.latest().open()

    const result = await client.send({ type: 'fire' })

    expect(result).toEqual({ id: 'ros-1', accepted: false, reason: '몸과 연결되어 있지 않습니다', roundTripMs: 0 })
    expect(frames(FakeSocket.latest(), 'call_service')).toHaveLength(1)
  })

  it('순서: 답이 보낸 순서와 다르게 와도 명령마다 제 답을 받는다', async () => {
    const { client, socket } = await opened()

    const fire = client.send({ type: 'fire' })
    const stop = client.send({ type: 'stop' })
    const [fireCall, stopCall] = frames(socket, 'call_service').slice(-2)
    socket.receive({ op: 'service_response', id: stopCall!.id, result: true, values: { accepted: true, reason: '' } })
    socket.receive({ op: 'service_response', id: fireCall!.id, result: true, values: { accepted: false, reason: '겨누지 않음' } })

    await expect(fire).resolves.toMatchObject({ id: 'ros-1', accepted: false, reason: '겨누지 않음' })
    await expect(stop).resolves.toMatchObject({ id: 'ros-2', accepted: true })
  })
})
