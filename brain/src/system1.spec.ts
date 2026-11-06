import { describe, expect, it } from 'vitest'
import { System1 } from './system1'
import { drone, mechaStatus, RecordingSender, settle, stateMessage } from './testing'

function setup() {
  const sender = new RecordingSender()
  let clock = 0
  const system1 = new System1(sender, () => clock)
  system1.setSimConnected(true)
  return { sender, system1, advance: (ms: number) => (clock += ms) }
}

const ENGAGE_STATE = stateMessage({
  simTime: 5,
  mecha: mechaStatus({ position: [0, 0, 30], heading: 0 }),
  units: [drone({ id: 'drone-1', position: [400, 0, 30] })],
})

describe('System1', () => {
  it('맡기 전에는 몸에 명령하지 않고, 두뇌라면 무엇을 할지만 보여 준다', () => {
    const { sender, system1 } = setup()
    system1.setSkill('engage')

    system1.onState(ENGAGE_STATE)

    expect(sender.sent).toEqual([])
    expect(system1.status().activity).toMatch(/^사람이 조종 중 \(두뇌라면: 표적 드론 1/)
    expect(system1.status().target).toBe('drone-1')
  })

  it('맡으면 교전 명령(다가가기·겨누기)을 보내고, 판단 기록을 남긴다', () => {
    const { sender, system1 } = setup()
    system1.setSkill('engage')
    system1.setAutonomy(true)

    system1.onState(ENGAGE_STATE)

    expect(sender.sent).toContainEqual({ type: 'aim', unit: 'drone-1' })
    expect(sender.sent.find((command) => command.type === 'velocity')).toMatchObject({ forward: 25 })
    expect(system1.log.recent().map((decision) => decision.kind)).toEqual(['skill', 'skill', 'target'])
  })

  it('조준 경고를 받으면 반사로 피하고, 경고를 본 때부터 몸이 받기까지를 반응 시간으로 잰다', async () => {
    const { sender, system1, advance } = setup()
    system1.setSkill('engage', null, 'dodge')
    system1.setAutonomy(true)
    system1.onState(ENGAGE_STATE)
    sender.clear()

    sender.holdReplies = true
    system1.onState({ ...ENGAGE_STATE, simTime: 5.02, threats: [{ from: 'drone-1', secondsToFire: 1.2 }] })
    advance(12)
    sender.flush()
    await settle()

    const dodge = sender.sent.find((command) => command.type === 'velocity')
    expect(dodge).toMatchObject({ sideways: expect.any(Number) })
    expect(Math.abs((dodge as { sideways: number }).sideways)).toBe(20)
    expect(system1.status().reflex).toMatchObject({ kind: 'dodge', threat: 'drone-1' })
    expect(system1.status().metrics.lastReactionMs).toBe(12)
    expect(system1.log.recent().at(-1)?.text).toContain('→ 피하기')
  })

  it('파괴된 기체에는 명령하지 않는다', () => {
    const { sender, system1 } = setup()
    system1.setSkill('engage')
    system1.setAutonomy(true)

    system1.onState({ ...ENGAGE_STATE, mecha: mechaStatus({ mode: 'destroyed', hp: 0 }) })

    expect(sender.sent).toEqual([])
  })

  it('순서: 몸이 처음으로 되돌아가면(시각이 줄면) 지난 명령을 잊고 판단을 새로 시작한다', () => {
    const { sender, system1 } = setup()
    system1.setSkill('engage')
    system1.setAutonomy(true)
    system1.onState(ENGAGE_STATE)
    sender.clear()

    system1.onState({ ...ENGAGE_STATE, simTime: 0.02 })

    expect(sender.types()).toEqual(['velocity', 'aim', 'guard'])
    expect(system1.log.recent().some((decision) => decision.text.includes('처음으로 되돌아가'))).toBe(true)
  })

  it('사격·격파·피해를 세어 지표로 낸다', () => {
    const { system1 } = setup()

    system1.onCombat({ type: 'shot', simTime: 1, shooter: 'mecha', from: [0, 0, 0], to: [1, 0, 0], hit: { unit: 'drone-1', damage: 30, blocked: false } })
    system1.onCombat({ type: 'shot', simTime: 2, shooter: 'mecha', from: [0, 0, 0], to: [1, 0, 0] })
    system1.onCombat({ type: 'destroyed', simTime: 2, unit: 'drone-1' })
    system1.onCombat({ type: 'shot', simTime: 3, shooter: 'drone-2', from: [0, 0, 0], to: [1, 0, 0], hit: { unit: 'mecha', damage: 40, blocked: false } })
    system1.onCombat({ type: 'shot', simTime: 4, shooter: 'drone-2', from: [0, 0, 0], to: [1, 0, 0], hit: { unit: 'mecha', damage: 0, blocked: true } })

    expect(system1.status().metrics).toMatchObject({ shots: 2, hits: 1, kills: 1, damageTaken: 40 })
  })
})
