import { describe, expect, it } from 'vitest'
import type { Evasion, SkillName } from '@shared/brain/generated/control'
import type { PlanStep } from '@shared/brain/generated/plan'
import type { Perception } from '../perception'
import { drone, mechaStatus, perceptionOf } from '../testing'
import { PlanRun, type SkillControl } from './planRun'

class RecordingSkills implements SkillControl {
  readonly skills: [SkillName, string | null, Evasion][] = []
  autonomy: boolean | null = null

  setSkill(name: SkillName, target: string | null, evasion: Evasion): void {
    this.skills.push([name, target, evasion])
  }

  setAutonomy(enabled: boolean): void {
    this.autonomy = enabled
  }
}

function setup() {
  const skills = new RecordingSkills()
  const notes: string[] = []
  let elapsed = 0
  const run = new PlanRun('명령', 'llm', {
    skills,
    note: (text) => notes.push(text),
    nameOf: (id) => (id === 'drone-2' ? '표적 드론 2' : id),
    elapsedMs: () => elapsed,
  })
  return { run, skills, notes, advance: (ms: number) => (elapsed += ms) }
}

const step = (overrides: Partial<PlanStep> = {}): PlanStep => ({
  skill: 'engage',
  target: null,
  evasion: 'dodge',
  until: 'allDestroyed',
  value: 0,
  ...overrides,
})

const BOTH_DRONES = [drone({ id: 'drone-1' }), drone({ id: 'drone-2', name: '표적 드론 2' })]

function at(simTime: number, overrides: { hp?: number; units?: ReturnType<typeof drone>[]; destroyed?: boolean } = {}): Perception {
  return perceptionOf({
    simTime,
    mecha: mechaStatus({ hp: overrides.hp ?? 1000, mode: overrides.destroyed ? 'destroyed' : 'flying' }),
    units: overrides.units ?? BOTH_DRONES,
  })
}

describe('PlanRun', () => {
  it('첫 단계가 들어오면 바로 그 기술을 시키고 첫 단계 시각을 잰다', () => {
    const { run, skills, notes, advance } = setup()
    advance(1450)

    run.addStep(step({ target: 'drone-2', until: 'targetDestroyed', evasion: 'guard' }))

    expect(skills.skills).toEqual([['engage', 'drone-2', 'guard']])
    expect(run.view()).toMatchObject({ state: 'running', current: 0, timing: { firstStepMs: 1450, totalMs: null } })
    expect(notes).toEqual(['단계 1: 교전 (표적 드론 2) · 표적 드론 2을(를) 격파할 때까지'])
  })

  it('표적이 격파되면 다음 단계로, 모든 드론이 격파되면 마지막 단계도 마치고 계획을 마친다', () => {
    const { run, skills, notes } = setup()
    run.addStep(step({ target: 'drone-2', until: 'targetDestroyed' }))
    run.addStep(step({ until: 'allDestroyed' }))
    run.complete()

    run.update(at(1))
    expect(run.view().current).toBe(0)
    run.update(at(2, { units: [drone({ id: 'drone-1' }), drone({ id: 'drone-2', alive: false })] }))
    expect(run.view()).toMatchObject({ current: 1, state: 'running' })
    run.update(at(3, { units: [] }))

    expect(skills.skills.map(([name, target]) => [name, target])).toEqual([
      ['engage', 'drone-2'],
      ['engage', null],
    ])
    expect(run.view()).toMatchObject({ state: 'done', steps: [{ state: 'done' }, { state: 'done' }] })
    expect(notes.at(-1)).toBe('계획을 마침')
  })

  it('경계값: seconds는 단계를 시작한 뒤 처음 받은 상태부터 재고, 정확히 n초가 지나면 넘어간다', () => {
    const { run } = setup()
    run.addStep(step({ skill: 'hold', until: 'seconds', value: 5 }))
    run.addStep(step({ skill: 'retreat', until: 'never' }))
    run.complete()

    run.update(at(10.02))
    run.update(at(15.0))
    expect(run.view().current).toBe(0)
    run.update(at(15.02))

    expect(run.view().current).toBe(1)
  })

  it('hpBelow는 체력 비율이 값 아래로 떨어지면 넘어간다 (같으면 아직)', () => {
    const { run } = setup()
    run.addStep(step({ until: 'hpBelow', value: 0.5 }))
    run.addStep(step({ skill: 'retreat', until: 'never' }))

    run.update(at(1, { hp: 500 }))
    expect(run.view().current).toBe(0)
    run.update(at(2, { hp: 499 }))

    expect(run.view().current).toBe(1)
  })

  it('never는 넘어가지 않고 계속 따른다', () => {
    const { run } = setup()
    run.addStep(step({ skill: 'hold', until: 'never' }))
    run.complete()

    run.update(at(1, { units: [] }))
    run.update(at(500, { units: [] }))

    expect(run.view()).toMatchObject({ state: 'running', current: 0 })
  })

  it('순서: 아직 다음 단계를 받지 못했으면, 지금 단계가 끝나도 마치지 않고 기다렸다가 받으면 넘어간다', () => {
    const { run } = setup()
    run.addStep(step({ until: 'allDestroyed' }))

    run.update(at(1, { units: [] }))
    expect(run.view()).toMatchObject({ state: 'running', current: 0 })
    run.addStep(step({ skill: 'hold', until: 'never' }))
    run.update(at(1.02, { units: [] }))

    expect(run.view()).toMatchObject({ state: 'running', current: 1 })
  })

  it('한 번에 여러 단계가 맞으면(표적이 이미 격파됨) 그 단계들을 건너뛴다', () => {
    const { run, skills } = setup()
    run.addStep(step({ target: 'drone-1', until: 'targetDestroyed' }))
    run.addStep(step({ target: 'drone-2', until: 'targetDestroyed' }))
    run.addStep(step({ skill: 'hold', until: 'never' }))
    run.complete()

    run.update(at(1, { units: [] }))

    expect(run.view().current).toBe(2)
    expect(skills.skills.map(([name]) => name)).toEqual(['engage', 'engage', 'hold'])
  })

  it('체력이 retreatBelowHp 아래로 떨어지면 단계를 멈추고 피하며 막으며 물러난다', () => {
    const { run, skills, notes } = setup()
    run.setRetreatBelowHp(0.3)
    run.addStep(step())

    run.update(at(1, { hp: 300 }))
    expect(run.view().state).toBe('running')
    run.update(at(2, { hp: 290 }))

    expect(run.view().state).toBe('retreating')
    expect(skills.skills.at(-1)).toEqual(['retreat', null, 'both'])
    expect(notes.at(-1)).toBe('체력 29% (물러날 선 30%) → 계획을 멈추고 물러남')
    run.update(at(3, { hp: 290, units: [] }))
    expect(run.view().state).toBe('retreating')
  })

  it('실패: 기체가 파괴되면 계획이 실패한다', () => {
    const { run } = setup()
    run.addStep(step())

    run.update(at(1, { hp: 0, destroyed: true }))

    expect(run.view()).toMatchObject({ state: 'failed', error: '기체가 파괴됨' })
  })

  it('그만두면 기술은 그대로 두고 상태만 바꾼다. 중복으로 그만두면 false', () => {
    const { run, skills } = setup()
    run.addStep(step())

    expect(run.cancel('사람이 그만두게 함')).toBe(true)
    expect(run.cancel('또')).toBe(false)

    expect(run.view()).toMatchObject({ state: 'cancelled', steps: [{ state: 'waiting' }] })
    expect(skills.skills).toHaveLength(1)
    run.addStep(step({ skill: 'hold' }))
    expect(skills.skills).toHaveLength(1)
  })

  it('다시 물으면 지난번 단계를 버리고, 새 첫 단계부터 다시 시킨다 (첫 단계 시각은 처음 것을 둔다)', () => {
    const { run, skills, advance } = setup()
    run.startAttempt()
    advance(1000)
    run.addStep(step({ skill: 'hold' }))

    run.startAttempt()
    advance(2000)
    run.addStep(step({ skill: 'retreat', until: 'never' }))

    expect(run.view()).toMatchObject({ attempts: 2, state: 'running', current: 0, steps: [{ skill: 'retreat' }], timing: { firstStepMs: 1000 } })
    expect(skills.skills.map(([name]) => name)).toEqual(['hold', 'retreat'])
  })
})
