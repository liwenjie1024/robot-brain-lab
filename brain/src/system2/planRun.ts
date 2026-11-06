import type { Evasion, SkillName } from '@shared/brain/generated/control'
import type { PlanStep } from '@shared/brain/generated/plan'
import type { PlanStatus, PlanStepView, PlanTiming } from '@shared/brain/generated/status'
import { describeStep, percent } from '@shared/brain/labels'
import type { Perception } from '../perception'

export type PlanSource = PlanStatus['source']
export type PlanState = PlanStatus['state']

/** 느린 뇌가 빠른 뇌에게 시키는 것 (System1이 이 모양을 갖는다) */
export interface SkillControl {
  setSkill(name: SkillName, target: string | null, evasion: Evasion): void
  setAutonomy(enabled: boolean): void
}

export interface PlanRunDeps {
  skills: SkillControl
  /** 판단 기록에 한 줄 */
  note: (text: string) => void
  nameOf: (id: string) => string
  /** 명령을 받은 때부터 지난 ms */
  elapsedMs: () => number
}

export const THINKING_SAY = '명령을 생각하는 중…'
/** 체력이 낮아 물러날 때는 피하기와 막기를 모두 한다 */
const RETREAT_EVASION: Evasion = 'both'
/** 시뮬레이션 시각은 0.002초씩 더해져 실수 오차가 있다 (정확히 n초 지난 때를 놓치지 않게) */
const TIME_EPSILON_S = 1e-6

/**
 * 계획 하나를 따른다: 단계마다 빠른 뇌의 기술을 바꾸고, 몸의 상태가 올 때마다 그 단계의 until을 보고 다음으로 넘어간다.
 * 단계는 언어 모델이 쓰는 대로 하나씩 들어온다 (다 받기 전에 첫 단계를 시작한다). 마지막 단계의 until이 맞고 계획을 다 받았으면 마친다.
 * 체력이 retreatBelowHp 아래로 떨어지면 단계를 멈추고 물러난다.
 */
export class PlanRun {
  attempts = 0
  private say = THINKING_SAY
  private state: PlanState = 'thinking'
  private steps: PlanStep[] = []
  private current: number | null = null
  /** 지금 단계를 시작한 시뮬레이션 시각 (시작한 뒤 처음 받은 상태의 시각) */
  private stepStartedAt: number | null = null
  private received = false
  private retreatBelowHp = 0
  private error: string | null = null
  private readonly timing: PlanTiming = { firstTokenMs: null, firstStepMs: null, totalMs: null }

  constructor(
    readonly order: string,
    readonly source: PlanSource,
    private readonly deps: PlanRunDeps,
  ) {}

  /** 짜는 중이거나 따르는 중 (그만두거나 실패하거나 마치거나 물러나면 false) */
  get active(): boolean {
    return this.state === 'thinking' || this.state === 'running'
  }

  /** 언어 모델에 (다시) 묻는다. 지난번에 받은 단계는 버린다 (그 단계의 기술은 새 단계가 올 때까지 그대로 한다). */
  startAttempt(): void {
    this.attempts++
    this.steps = []
    this.current = null
    this.stepStartedAt = null
    this.received = false
    if (this.state === 'running') {
      this.state = 'thinking'
    }
  }

  heardFirstToken(): void {
    this.timing.firstTokenMs ??= this.deps.elapsedMs()
  }

  setSay(say: string): void {
    this.say = say
  }

  setRetreatBelowHp(ratio: number): void {
    this.retreatBelowHp = ratio
  }

  addStep(step: PlanStep): void {
    if (!this.active) {
      return
    }
    this.steps.push(step)
    if (this.current === null) {
      this.begin(0)
    }
  }

  /** 계획을 다 받았다 (더 올 단계가 없다) */
  complete(): void {
    this.received = true
    this.timing.totalMs ??= this.deps.elapsedMs()
  }

  update(perception: Perception): void {
    if (this.state !== 'running' || this.current === null) {
      return
    }
    if (perception.self.mode === 'destroyed') {
      this.fail('기체가 파괴됨')
      return
    }
    const hp = hpRatio(perception)
    if (this.retreatBelowHp > 0 && hp < this.retreatBelowHp) {
      this.retreat(hp)
      return
    }
    this.stepStartedAt ??= perception.simTime
    // 한 번에 여러 단계가 맞을 수 있다 (예: 표적이 이미 격파됨). 단계 수만큼만 돈다.
    while (this.state === 'running' && this.isStepMet(perception)) {
      const next = this.current + 1
      if (next < this.steps.length) {
        this.begin(next)
        this.stepStartedAt = perception.simTime
      } else {
        if (this.received) {
          this.finish()
        }
        return
      }
    }
  }

  cancel(reason: string): boolean {
    if (!this.active) {
      return false
    }
    this.state = 'cancelled'
    this.deps.note(`계획을 그만둠: ${reason}`)
    return true
  }

  fail(reason: string): void {
    if (!this.active) {
      return
    }
    this.state = 'failed'
    this.error = reason
    this.deps.note(`계획 실패: ${reason}${this.current === null ? '' : ' (기체는 지금 기술을 그대로 함)'}`)
  }

  view(): PlanStatus {
    return {
      order: this.order,
      source: this.source,
      state: this.state,
      say: this.say,
      steps: this.steps.map((step, index) => ({ ...step, state: this.stepState(index) })),
      current: this.current,
      retreatBelowHp: this.retreatBelowHp,
      attempts: this.attempts,
      timing: { ...this.timing },
      error: this.error,
    }
  }

  private get currentStep(): PlanStep | undefined {
    return this.current === null ? undefined : this.steps[this.current]
  }

  private begin(index: number): void {
    const step = this.steps[index]
    if (!step) {
      return
    }
    this.current = index
    this.stepStartedAt = null
    this.state = 'running'
    this.timing.firstStepMs ??= this.deps.elapsedMs()
    this.deps.note(`단계 ${index + 1}: ${describeStep(step, this.deps.nameOf)}`)
    this.deps.skills.setSkill(step.skill, step.target, step.evasion)
  }

  private isStepMet(perception: Perception): boolean {
    const step = this.currentStep
    if (!step) {
      return false
    }
    switch (step.until) {
      case 'targetDestroyed':
        return !perception.targets.some((target) => target.id === step.target)
      case 'allDestroyed':
        return perception.targets.length === 0
      case 'seconds':
        return perception.simTime - (this.stepStartedAt ?? perception.simTime) + TIME_EPSILON_S >= step.value
      case 'hpBelow':
        return hpRatio(perception) < step.value
      case 'never':
        return false
    }
  }

  private finish(): void {
    this.state = 'done'
    this.deps.note('계획을 마침')
  }

  private retreat(hp: number): void {
    this.state = 'retreating'
    this.deps.note(`체력 ${percent(hp)}% (물러날 선 ${percent(this.retreatBelowHp)}%) → 계획을 멈추고 물러남`)
    this.deps.skills.setSkill('retreat', null, RETREAT_EVASION)
  }

  private stepState(index: number): PlanStepView['state'] {
    if (this.state === 'done') {
      return 'done'
    }
    if (this.current === null || index > this.current) {
      return 'waiting'
    }
    if (index < this.current) {
      return 'done'
    }
    return this.state === 'running' ? 'running' : 'waiting'
  }
}

function hpRatio(perception: Perception): number {
  const { hp, maxHp } = perception.self
  return maxHp > 0 ? hp / maxHp : 0
}
