import type { Evasion, SkillName, StartTrials } from '@shared/brain/generated/control'
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
import { TrialRunner } from './trials/trialRunner'
import { NO_TRIAL_STORE, type TrialStore } from './trials/trialStore'

/**
 * 두뇌 전체: 빠른 뇌(System 1)와 느린 뇌(System 2). 몸의 상태는 한 번 읽어 둘에게 준다.
 * 느린 뇌가 먼저 계획의 단계를 넘겨 기술을 바꾸고, 빠른 뇌가 같은 상태로 바로 판단한다.
 * 사람이 기술을 직접 고르거나 조종을 가져가면 느린 뇌의 계획은 그만둔다 (사람이 앞선다).
 * 시험(trials)은 두뇌 밖의 심판처럼 장면을 되돌리고 두뇌에게 맡긴 뒤, 몸이 알린 값으로 점수를 낸다.
 */
export class Brain {
  readonly system1: System1
  readonly system2: System2
  private readonly trials: TrialRunner
  private lastSimTime: number | null = null

  constructor(
    sender: CommandSender,
    model: LanguageModel,
    private readonly now: () => number = () => performance.now(),
    trialStore: TrialStore = NO_TRIAL_STORE,
  ) {
    this.system1 = new System1(sender, now)
    this.system2 = new System2({ skills: this.system1, log: this.system1.log, model, now })
    this.trials = new TrialRunner({
      sender,
      store: trialStore,
      now,
      note: (text) => this.log.add('trial', text, this.lastSimTime),
      subject: {
        setSkill: (name, target, evasion) => this.system1.setSkill(name, target, evasion),
        setAutonomy: (enabled) => {
          if (!enabled) {
            this.system2.cancel('시험의 한 판이 끝남')
          }
          this.system1.setAutonomy(enabled)
        },
        order: (text) => {
          this.system2.forgetPlans()
          return this.system2.order(text)
        },
        reactionMs: () => this.system1.metrics.averageReactionMs(),
        plan: () => this.system2.planStatus(),
      },
    })
  }

  get log(): DecisionLog {
    return this.system1.log
  }

  setScene(scene: SceneDescription): void {
    this.system1.setScene(scene)
    this.system2.setScene(scene)
    this.trials.setScenarios(scene.scenarios)
  }

  setSimConnected(connected: boolean): void {
    this.system1.setSimConnected(connected)
    this.trials.setSimConnected(connected)
  }

  onState(state: StateMessage): void {
    const receivedAt = this.now()
    const perception = perceive(state)
    this.lastSimTime = state.simTime
    this.system2.update(perception)
    this.system1.decide(perception, receivedAt)
    this.trials.onState(state)
  }

  onCombat(event: CombatEvent): void {
    this.system1.onCombat(event)
    this.trials.onCombat(event)
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

  /** 시험 중에는 사람의 다른 지시를 받지 않는다 (판의 결과가 섞이지 않게) */
  get trialsRunning(): boolean {
    return this.trials.running
  }

  /** 시작할 수 없으면 까닭 */
  startTrials(spec: StartTrials): string | null {
    return this.trials.start(spec)
  }

  stopTrials(): boolean {
    return this.trials.stop()
  }

  status(): BrainStatus {
    return {
      ...this.system1.status(),
      plan: this.system2.planStatus(),
      planner: this.system2.plannerStatus(),
      trials: this.trials.status(),
    }
  }
}
