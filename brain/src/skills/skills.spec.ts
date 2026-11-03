import { describe, expect, it } from 'vitest'
import { drone, mechaStatus, scene, stateMessage } from '../testing'
import { perceive } from '../perception'
import { allowedAimError, EngageSkill, FIRE_ERROR_DEG, PREFERRED_RANGE_M } from './engage'
import { HoldSkill } from './hold'
import { RetreatSkill } from './retreat'

describe('EngageSkill 표적 고르기', () => {
  it('가까운 드론을 고른다', () => {
    const intent = new EngageSkill().decide(scene([drone({ id: 'a', position: [300, 0, 30] }), drone({ id: 'b', position: [150, 0, 30] })]))

    expect(intent.target).toBe('b')
    expect(intent.aim).toBe('b')
  })

  it('무장한 드론과 지금 나를 조준하는 드론을 먼저 노린다', () => {
    const units = [drone({ id: 'near', position: [150, 0, 30] }), drone({ id: 'armed', position: [220, 0, 30], armed: true })]

    expect(new EngageSkill().decide(scene(units)).target).toBe('armed')
    const locking = scene([drone({ id: 'near', position: [150, 0, 30] }), drone({ id: 'locking', position: [280, 0, 30] })], {
      threats: [{ from: 'locking', secondsToFire: 1 }],
    })
    expect(new EngageSkill().decide(locking).target).toBe('locking')
  })

  it('지시받은 표적이 살아 있으면 그것만 노리고, 파괴되면 다른 드론을 고른다', () => {
    const skill = new EngageSkill('far')
    const units = [drone({ id: 'near', position: [150, 0, 30] }), drone({ id: 'far', position: [400, 0, 30] })]

    expect(skill.decide(scene(units)).target).toBe('far')
    expect(skill.decide(scene([units[0]!, drone({ id: 'far', alive: false })])).target).toBe('near')
  })

  it('지금 표적보다 아주 낫지 않으면 표적을 바꾸지 않는다 (오락가락하지 않게)', () => {
    const skill = new EngageSkill()
    skill.decide(scene([drone({ id: 'first', position: [150, 0, 30] })]))

    const slightlyCloser = scene([drone({ id: 'first', position: [150, 0, 30] }), drone({ id: 'second', position: [120, 0, 30] })])
    const muchCloser = scene([drone({ id: 'first', position: [150, 0, 30] }), drone({ id: 'second', position: [60, 0, 30] })])

    expect(skill.decide(slightlyCloser).target).toBe('first')
    expect(skill.decide(muchCloser).target).toBe('second')
  })

  it('빈 상태: 드론이 없으면 멈춰 기다린다', () => {
    const intent = new EngageSkill().decide(scene([]))

    expect(intent.velocity).toEqual({ forward: 0, sideways: 0, up: 0, turn: 0 })
    expect(intent.aim).toBeNull()
    expect(intent.activity).toBe('교전할 드론이 없습니다')
  })
})

describe('EngageSkill 움직임', () => {
  it('왼쪽 드론이면 왼쪽(+)으로 돌고, 뒤에 있으면 먼저 돌기만 한다', () => {
    const left = new EngageSkill().decide(scene([drone({ position: [0, 300, 30] })]))
    const behind = new EngageSkill().decide(scene([drone({ position: [-300, 1, 30] })]))

    expect(left.velocity.turn).toBeGreaterThan(0)
    expect(behind.velocity.forward).toBe(0)
  })

  it('멀면 다가가고, 가까우면 물러나고, 머물 거리 띠 안이면 앞뒤로 움직이지 않는다', () => {
    const at = (x: number) => new EngageSkill().decide(scene([drone({ position: [x, 0, 30] })])).velocity.forward

    expect(at(400)).toBeGreaterThan(0)
    expect(at(60)).toBeLessThan(0)
    expect(at(PREFERRED_RANGE_M + 20)).toBe(0)
  })

  it('표적 높이에 맞춰 오르내린다', () => {
    expect(new EngageSkill().decide(scene([drone({ position: [170, 0, 60] })])).velocity.up).toBeGreaterThan(0)
    expect(new EngageSkill().decide(scene([drone({ position: [170, 0, 10] })])).velocity.up).toBeLessThan(0)
  })
})

describe('EngageSkill 사격', () => {
  const aimedAt = (aimError: number, overrides: Partial<{ ready: boolean; energy: number; distance: number }> = {}) =>
    perceive(
      stateMessage({
        mecha: mechaStatus({
          position: [0, 0, 30],
          heading: 0,
          energy: overrides.energy ?? 100,
          weapon: { ready: overrides.ready ?? true, cooldown: 0, aimTarget: 'drone-1', aimError },
        }),
        units: [drone({ id: 'drone-1', position: [overrides.distance ?? 150, 0, 30] })],
      }),
    )

  it('조준이 맞고 준비되었으면 쏜다', () => {
    expect(new EngageSkill().decide(aimedAt(0.2)).fire).toBe(true)
  })

  it('경계값: 멀수록 더 정확히 겨눈 뒤 쏜다 (어긋남 허용 = 1m를 지나가는 각)', () => {
    expect(allowedAimError(150)).toBeCloseTo(0.382, 2)
    expect(allowedAimError(300)).toBeCloseTo(0.191, 2)
    expect(allowedAimError(50)).toBe(FIRE_ERROR_DEG)
    expect(new EngageSkill().decide(aimedAt(0.3, { distance: 300 })).fire).toBe(false)
    expect(new EngageSkill().decide(aimedAt(0.15, { distance: 300 })).fire).toBe(true)
  })

  it.each([
    ['조준이 어긋남', aimedAtArgs(1.0)],
    ['식는 중', aimedAtArgs(0.1, { ready: false })],
    ['에너지 모자람', aimedAtArgs(0.1, { energy: 10 })],
  ])('%s이면 쏘지 않는다', (_, [error, overrides]) => {
    expect(new EngageSkill().decide(aimedAt(error, overrides)).fire).toBe(false)
  })
})

function aimedAtArgs(error: number, overrides: Partial<{ ready: boolean; energy: number }> = {}) {
  return [error, overrides] as const
}

describe('HoldSkill', () => {
  it('처음 자리를 붙잡고, 밀려나면 그쪽으로 돌아온다', () => {
    const skill = new HoldSkill()
    skill.decide(scene([]))

    const pushedEast = scene([], { mecha: mechaStatus({ position: [20, 0, 30], heading: 0 }) })
    const intent = skill.decide(pushedEast)

    expect(intent.velocity.forward).toBeLessThan(0)
    expect(intent.activity).toContain('20 m 벗어남')
  })

  it('경계값: 조금(1.5m 안) 벗어난 것은 고치지 않는다 (명령을 흔들지 않게)', () => {
    const skill = new HoldSkill()
    skill.decide(scene([]))

    const intent = skill.decide(scene([], { mecha: mechaStatus({ position: [1, 0, 30], heading: 0 }) }))

    expect(intent.velocity).toEqual({ forward: 0, sideways: 0, up: 0, turn: 0 })
  })
})

describe('RetreatSkill', () => {
  it('드론들 반대쪽으로 날며 오르고, 무장한 드론 쪽으로 방패를 든다', () => {
    const intent = new RetreatSkill().decide(scene([drone({ id: 'armed', position: [200, 0, 30], armed: true })]))

    expect(intent.velocity.forward).toBeLessThan(0)
    expect(intent.velocity.up).toBeGreaterThan(0)
    expect(intent.guard).toEqual({ raised: true, unit: 'armed' })
  })

  it('충분히 멀어지면 멈춘다', () => {
    const intent = new RetreatSkill().decide(scene([drone({ position: [900, 0, 30] })], { mecha: mechaStatus({ position: [0, 0, 100], heading: 0 }) }))

    expect(intent.velocity).toEqual({ forward: 0, sideways: 0, up: 0, turn: 0 })
  })
})
