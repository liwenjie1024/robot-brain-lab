import type { Evasion, SkillName } from '@shared/brain/generated/control'
import type { BrainStatus } from '@shared/brain/generated/status'
import type { StateMessage } from '@shared/sim/generated/message'
import type { SceneDescription } from '@shared/sim/generated/scene'
import type { CombatEvent } from '@shared/sim/simClient'
import type { CommandSender } from './commander'
import type { DecisionLog } from './decisions'
import { perceive } from './perception'
import { System1 } from './system1'
import type { LanguageModel } from './system2/model'
import { System2 } from './system2/system2'

/**
 * 두뇌 전체: 빠른 뇌(System 1)와 느린 뇌(System 2). 몸의 상태는 한 번 읽어 둘에게 준다.
 * 느린 뇌가 먼저 계획의 단계를 넘겨 기술을 바꾸고, 빠른 뇌가 같은 상태로 바로 판단한다.
 * 사람이 기술을 직접 고르거나 조종을 가져가면 느린 뇌의 계획은 그만둔다 (사람이 앞선다).
 */
export class Brain {
  readonly system1: System1
  readonly system2: System2

  constructor(
    sender: CommandSender,
    model: LanguageModel,
    private readonly now: () => number = () => performance.now(),
  ) {
    this.system1 = new System1(sender, now)
    this.system2 = new System2({ skills: this.system1, log: this.system1.log, model, now })
  }

  get log(): DecisionLog {
    return this.system1.log
  }

  setScene(scene: SceneDescription): void {
    this.system1.setScene(scene)
    this.system2.setScene(scene)
  }

  setSimConnected(connected: boolean): void {
    this.system1.setSimConnected(connected)
  }

  onState(state: StateMessage): void {
    const receivedAt = this.now()
    const perception = perceive(state)
    this.system2.update(perception)
    this.system1.decide(perception, receivedAt)
  }

  onCombat(event: CombatEvent): void {
    this.system1.onCombat(event)
  }

  /** 사람이 기술을 직접 고른다 */
  chooseSkill(name: SkillName, target: string | null, evasion?: Evasion): void {
    this.system2.cancel('사람이 기술을 직접 고름')
    this.system1.setSkill(name, target, evasion)
  }

  setAutonomy(enabled: boolean): void {
    if (!enabled) {
      this.system2.cancel('사람이 조종을 가져감')
    }
    this.system1.setAutonomy(enabled)
  }

  /** 말로 한 명령 (느린 뇌가 계획을 짜는 동안 기다리지 않는다) */
  order(text: string): Promise<void> {
    return this.system2.order(text)
  }

  cancelPlan(): boolean {
    return this.system2.cancel('사람이 그만두게 함')
  }

  status(): BrainStatus {
    return { ...this.system1.status(), plan: this.system2.planStatus(), planner: this.system2.plannerStatus() }
  }
}
