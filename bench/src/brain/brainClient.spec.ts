import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { BrainStatus, Decision } from '@shared/brain/generated/status'
import { brainStatus, trialSeries } from '@shared/test/fixtures'
import { BrainClient, type BrainPhase, brainSocketUrl } from './brainClient'

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
    this.onmessage?.({ data: JSON.stringify(message) })
  }
}

const STATUS = brainStatus()

function connected() {
  const phases: BrainPhase[] = []
  const client = new BrainClient({
    url: 'ws://bench/brain',
    createSocket: (url) => new FakeSocket(url) as unknown as WebSocket,
    reconnectDelaysMs: [100, 300],
    replyTimeoutMs: 500,
  })
  client.on('phase', (phase) => phases.push(phase))
  client.connect()
  const socket = FakeSocket.instances.at(-1)!
  socket.open()
  return { client, socket, phases }
}

beforeEach(() => {
  vi.useFakeTimers()
  FakeSocket.instances = []
})

afterEach(() => {
  vi.useRealTimers()
})

describe('BrainClient', () => {
  it('규약에 맞는 상태와 판단 기록을 알리고, 맞지 않는 메시지는 버린다', () => {
    const { client, socket } = connected()
    const statuses: BrainStatus[] = []
    const decisions: Decision[] = []
    client.on('status', (status) => statuses.push(status))
    client.on('decision', (decision) => decisions.push(decision))

    socket.receive(STATUS)
    socket.receive({ type: 'decision', seq: 1, simTime: 3.2, kind: 'reflex', text: '표적 드론 2이(가) 조준함 → 피하기' })
    socket.receive({ type: 'brainStatus', autonomy: 'yes' })

    expect(statuses).toEqual([STATUS])
    expect(decisions.map((decision) => decision.kind)).toEqual(['reflex'])
  })

  it('시험 결과가 든 상태도 규약대로 받는다 (비교한 것의 모양은 지시 규약에서 가져와 확인)', () => {
    const { client, socket } = connected()
    const statuses: BrainStatus[] = []
    client.on('status', (status) => statuses.push(status))
    const withTrials = brainStatus({ trials: trialSeries() })
    const badSetup = structuredClone(withTrials)
    ;(badSetup.trials!.setups[0]!.setup as { kind: string }).kind = 'dance'

    socket.receive(withTrials)
    socket.receive(badSetup)

    expect(statuses).toEqual([withTrials])
  })

  it('지시에 번호를 붙여 보내고, 같은 번호의 답으로 끝난다', async () => {
    const { client, socket } = connected()

    const result = client.send({ type: 'setAutonomy', enabled: true })
    const sent = JSON.parse(socket.sent[0]!)
    socket.receive({ type: 'controlResult', id: sent.id, accepted: true })

    expect(sent).toMatchObject({ type: 'setAutonomy', enabled: true, id: expect.stringMatching(/^bench-/) })
    await expect(result).resolves.toMatchObject({ accepted: true })
  })

  it('실패: 두뇌가 꺼져 있으면 보내지 않고 바로 까닭을 돌려준다', async () => {
    const client = new BrainClient({ url: 'ws://bench/brain', createSocket: (url) => new FakeSocket(url) as unknown as WebSocket })

    await expect(client.send({ type: 'setAutonomy', enabled: true })).resolves.toMatchObject({
      accepted: false,
      reason: '두뇌와 연결되어 있지 않습니다',
    })
  })

  it('실패: 답이 없으면 시간이 지나 실패로 끝난다', async () => {
    const { client } = connected()

    const result = client.send({ type: 'setSkill', skill: 'hold' })
    vi.advanceTimersByTime(500)

    await expect(result).resolves.toMatchObject({ accepted: false, reason: '두뇌가 답하지 않습니다' })
  })

  it('끊기면 꺼짐으로 알리고, 기다리던 지시를 실패로 끝내고, 다시 붙는다', async () => {
    const { client, socket, phases } = connected()

    const result = client.send({ type: 'setSkill', skill: 'hold' })
    socket.close()
    vi.advanceTimersByTime(100)

    expect(phases).toEqual(['connecting', 'open', 'offline', 'connecting'])
    expect(FakeSocket.instances).toHaveLength(2)
    await expect(result).resolves.toMatchObject({ accepted: false, reason: '두뇌와 연결이 끊겼습니다' })
  })
})

describe('brainSocketUrl', () => {
  it('화면 주소에서 두뇌 주소를 만든다 (https면 wss)', () => {
    expect(brainSocketUrl('/brain', { protocol: 'http:', host: 'localhost:5180' })).toBe('ws://localhost:5180/brain')
    expect(brainSocketUrl('/brain', { protocol: 'https:', host: 'lab.test' })).toBe('wss://lab.test/brain')
  })
})
