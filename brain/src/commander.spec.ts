import { describe, expect, it } from 'vitest'
import { LIMITS } from '@shared/test/fixtures'
import { Commander } from './commander'
import { GUARD_DOWN, type Intent, STILL } from './intent'
import { RecordingSender, settle } from './testing'

function intent(overrides: Partial<Intent> = {}): Intent {
  return { velocity: STILL, aim: null, guard: GUARD_DOWN, fire: false, activity: '', target: null, ...overrides }
}

function setup() {
  const sender = new RecordingSender()
  const rejected: string[] = []
  let sentCount = 0
  const commander = new Commander(sender, { rejected: (_, reason) => rejected.push(reason), sent: () => sentCount++ }, LIMITS)
  return { sender, commander, rejected, sent: () => sentCount }
}

describe('Commander', () => {
  it('처음에는 속도·소총·방패를 모두 보내고, 바뀌지 않으면 다시 보내지 않는다', () => {
    const { sender, commander, sent } = setup()

    commander.apply(intent())
    commander.apply(intent())

    expect(sender.types()).toEqual(['velocity', 'lowerAim', 'guard'])
    expect(sent()).toBe(3)
  })

  it('속도는 단위(0.5m/s, 0.05rad/s)로 맞추고, 작은 흔들림은 보내지 않는다', () => {
    const { sender, commander } = setup()
    commander.apply(intent({ velocity: { forward: 10.3, sideways: 0, up: 0, turn: 0.123 } }))
    sender.clear()

    commander.apply(intent({ velocity: { forward: 10.4, sideways: 0, up: 0, turn: 0.11 } }))

    expect(sender.sent).toEqual([])
  })

  it('경계값: 몸이 알린 범위 밖의 속도는 범위 끝으로 잘라 보낸다 (뒤로 -15, 돌기 1.2)', () => {
    const { sender, commander } = setup()

    commander.apply(intent({ velocity: { forward: -30, sideways: 0, up: 0, turn: 3 } }))

    expect(sender.sent[0]).toEqual({ type: 'velocity', forward: -15, sideways: 0, up: 0, turn: 1.2 })
  })

  it('겨누기·방패는 바뀔 때만 보낸다', () => {
    const { sender, commander } = setup()
    commander.apply(intent())
    sender.clear()

    commander.apply(intent({ aim: 'drone-1', guard: { raised: true, unit: 'drone-2' } }))
    commander.apply(intent({ aim: 'drone-1', guard: { raised: true, unit: 'drone-2' } }))

    expect(sender.sent).toEqual([
      { type: 'aim', unit: 'drone-1' },
      { type: 'guard', raised: true, unit: 'drone-2' },
    ])
  })

  it('중복: 앞 사격의 답이 오기 전에는 다시 쏘지 않는다', async () => {
    const { sender, commander } = setup()
    commander.apply(intent())
    sender.clear()
    sender.holdReplies = true

    commander.apply(intent({ fire: true }))
    commander.apply(intent({ fire: true }))
    sender.flush()
    await settle()
    commander.apply(intent({ fire: true }))

    expect(sender.types()).toEqual(['fire', 'fire'])
  })

  it('실패: 몸이 거절한 명령은 보냈다고 기억하지 않아 다음 판단에서 다시 보내고, 까닭을 알린다', async () => {
    const { sender, commander, rejected } = setup()
    sender.rejectTypes.add('aim')

    commander.apply(intent({ aim: 'drone-1' }))
    await settle()
    sender.rejectTypes.clear()
    commander.apply(intent({ aim: 'drone-1' }))

    expect(sender.types().filter((type) => type === 'aim')).toHaveLength(2)
    expect(rejected).toEqual(['시험용 거절'])
  })

  it('잊으면(몸이 처음으로 되돌아감) 다음 판단에서 모두 다시 보낸다', () => {
    const { sender, commander } = setup()
    commander.apply(intent())
    sender.clear()

    commander.forget()
    commander.apply(intent())

    expect(sender.types()).toEqual(['velocity', 'lowerAim', 'guard'])
  })
})
