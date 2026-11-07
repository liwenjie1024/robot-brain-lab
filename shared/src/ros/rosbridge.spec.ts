import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { FakeSocket } from '../test/fakeSocket'
import { RosbridgeConnection, type ServiceReply } from './rosbridge'

let events: string[] = []
let invalid: string[] = []

function connect() {
  const connection = new RosbridgeConnection(
    'ws://ros:9090',
    { open: () => events.push('open'), close: () => events.push('close'), invalid: (reason) => invalid.push(reason) },
    FakeSocket.create,
  )
  const socket = FakeSocket.latest()
  socket.open()
  return { connection, socket }
}

beforeEach(() => {
  vi.useFakeTimers()
  FakeSocket.instances = []
  events = []
  invalid = []
})

afterEach(() => {
  vi.useRealTimers()
})

describe('rosbridge 토픽 받기', () => {
  it('토픽을 한 번만 subscribe하고, 받은 메시지를 받는 쪽 모두에게 넘긴다', () => {
    const { connection, socket } = connect()
    const first: unknown[] = []
    const second: unknown[] = []

    connection.subscribe('/bl01/state', 'bl01_msgs/msg/State', (message) => first.push(message))
    connection.subscribe('/bl01/state', 'bl01_msgs/msg/State', (message) => second.push(message))
    socket.receive({ op: 'publish', topic: '/bl01/state', msg: { seq: 1 } })
    socket.receive({ op: 'publish', topic: '/bl01/other', msg: { seq: 2 } })

    expect(socket.sentFrames()).toEqual([{ op: 'subscribe', id: 'subscribe:/bl01/state', topic: '/bl01/state', type: 'bl01_msgs/msg/State' }])
    expect(first).toEqual([{ seq: 1 }])
    expect(second).toEqual([{ seq: 1 }])
  })

  it('마지막으로 받는 쪽이 그만 받으면 unsubscribe를 보낸다 (두 번 불러도 한 번만)', () => {
    const { connection, socket } = connect()
    const stopFirst = connection.subscribe('/bl01/combat', 'bl01_msgs/msg/CombatEvent', () => {})
    const stopSecond = connection.subscribe('/bl01/combat', 'bl01_msgs/msg/CombatEvent', () => {})

    stopFirst()
    expect(socket.sent).toHaveLength(1)
    stopSecond()
    stopSecond()

    expect(socket.sentFrames().slice(1)).toEqual([{ op: 'unsubscribe', id: 'subscribe:/bl01/combat', topic: '/bl01/combat' }])
  })

  it('실패: JSON이 아니거나 op가 없는 프레임은 버리고 알린다', () => {
    const { socket } = connect()

    socket.receive('not json')
    socket.receive({ topic: '/bl01/state' })

    expect(invalid).toEqual(['rosbridge가 JSON이 아닌 프레임을 보냄', 'rosbridge 프레임에 op가 없음'])
  })
})

describe('rosbridge 서비스 부르기', () => {
  it('번호를 붙여 call_service를 보내고 같은 번호의 답으로 끝난다 (답 순서가 바뀌어도)', async () => {
    const { connection, socket } = connect()

    const fire = connection.callService('/bl01/fire', 'bl01_msgs/srv/Fire', {}, 1000)
    const aim = connection.callService('/bl01/aim', 'bl01_msgs/srv/Aim', { unit: 'drone-1' }, 1000)
    socket.receive({ op: 'service_response', id: 'call:2', service: '/bl01/aim', result: true, values: { accepted: true, reason: '' } })
    socket.receive({ op: 'service_response', id: 'call:1', service: '/bl01/fire', result: true, values: { accepted: false, reason: '식는 중' } })

    expect(socket.sentFrames()).toEqual([
      { op: 'call_service', id: 'call:1', service: '/bl01/fire', type: 'bl01_msgs/srv/Fire', args: {} },
      { op: 'call_service', id: 'call:2', service: '/bl01/aim', type: 'bl01_msgs/srv/Aim', args: { unit: 'drone-1' } },
    ])
    await expect(aim).resolves.toEqual({ ok: true, values: { accepted: true, reason: '' } })
    await expect(fire).resolves.toEqual({ ok: true, values: { accepted: false, reason: '식는 중' } })
  })

  it('실패: rosbridge가 서비스를 부르지 못하면(result false) 그 까닭으로 끝난다', async () => {
    const { connection, socket } = connect()

    const reply = connection.callService('/bl01/fire', 'bl01_msgs/srv/Fire', {}, 1000)
    socket.receive({ op: 'service_response', id: 'call:1', result: false, values: 'Service /bl01/fire does not exist' })

    await expect(reply).resolves.toEqual({ ok: false, error: 'Service /bl01/fire does not exist' })
  })

  it('실패: 정한 시간 안에 답이 없으면 시간 초과로 끝나고, 늦게 온 답은 버린다', async () => {
    const { connection, socket } = connect()

    const reply = connection.callService('/bl01/fire', 'bl01_msgs/srv/Fire', {}, 500)
    vi.advanceTimersByTime(500)
    socket.receive({ op: 'service_response', id: 'call:1', result: true, values: { accepted: true } })

    await expect(reply).resolves.toEqual({ ok: false, error: '/bl01/fire이(가) 답하지 않습니다 (시간 초과)' })
  })

  it('순서: 답을 기다리는 동안 끊기면 기다리던 부르기를 모두 끊김으로 끝내고 끊김을 한 번 알린다', async () => {
    const { connection, socket } = connect()
    const replies: Promise<ServiceReply>[] = [
      connection.callService('/bl01/fire', 'bl01_msgs/srv/Fire', {}, 1000),
      connection.callService('/bl01/stop', 'bl01_msgs/srv/Stop', {}, 1000),
    ]

    socket.close()
    connection.close()

    for (const reply of replies) {
      await expect(reply).resolves.toEqual({ ok: false, error: 'rosbridge와 연결이 끊겨 답을 받지 못했습니다' })
    }
    expect(events).toEqual(['open', 'close'])
  })

  it('실패: 열리기 전에는 보내지 않고 바로 실패한다', async () => {
    const connection = new RosbridgeConnection('ws://ros:9090', { open() {}, close() {}, invalid() {} }, FakeSocket.create)

    await expect(connection.callService('/bl01/fire', 'bl01_msgs/srv/Fire', {}, 1000)).resolves.toEqual({
      ok: false,
      error: 'rosbridge에 연결되어 있지 않습니다',
    })
    expect(FakeSocket.latest().sent).toEqual([])
  })
})
