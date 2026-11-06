import type { PlanStatus, RunResult } from '@shared/brain/generated/status'
import { scoreRun } from '@shared/brain/trialScore'
import type { StateMessage } from '@shared/sim/generated/message'
import type { CombatEvent } from '@shared/sim/simClient'

export type RunOutcome = RunResult['outcome']

const MECHA_ID = 'mecha'
const DECIMALS = 10
/** 시뮬레이션 시각은 실수 오차가 있다 (정확히 제한 시간인 때를 놓치지 않게) */
const TIME_EPSILON_S = 1e-6

export interface RunExtras {
  /** 장면을 되돌린 뒤 두뇌가 맡기까지 늦춘 초 */
  startDelayS: number
  /** 이 판의 반사 반응 시간 평균 (반사가 없었으면 null) */
  reactionMs: number | null
  /** 말로 한 명령의 계획 (기술을 맡긴 판이면 null) */
  plan: PlanStatus | null
}

/**
 * 시험 한 판을 두뇌가 맡은 때부터 지켜보고 결과를 낸다. 결과는 두뇌가 스스로 센 값이 아니라 몸이 알린 값(상태·사격 사건)으로 낸다
 * (시험 대상이 제 점수를 매기지 않게).
 */
export class RunRecorder {
  readonly drones: number
  private readonly startSimTime: number
  private readonly startHp: number
  private readonly maxHp: number
  private last: StateMessage
  private shots = 0
  private hits = 0

  constructor(
    start: StateMessage,
    private readonly timeLimitS: number,
  ) {
    this.last = start
    this.startSimTime = start.simTime
    this.startHp = start.mecha.hp
    this.maxHp = start.mecha.maxHp
    this.drones = aliveDrones(start)
  }

  get elapsedS(): number {
    return this.last.simTime - this.startSimTime
  }

  onCombat(event: CombatEvent): void {
    if (event.type !== 'shot' || event.shooter !== MECHA_ID) {
      return
    }
    this.shots++
    if (event.hit && event.hit.unit !== MECHA_ID) {
      this.hits++
    }
  }

  /** 판이 끝났으면 어떻게 끝났는지 (드론을 다 격파한 것을 먼저 본다) */
  update(state: StateMessage): RunOutcome | null {
    this.last = state
    if (aliveDrones(state) === 0) {
      return 'cleared'
    }
    if (state.mecha.mode === 'destroyed') {
      return 'destroyed'
    }
    return this.elapsedS + TIME_EPSILON_S >= this.timeLimitS ? 'timeout' : null
  }

  result(run: number, outcome: RunOutcome, extras: RunExtras): RunResult {
    const durationS = round(this.elapsedS)
    const clearTimeS = outcome === 'cleared' ? durationS : null
    const kills = this.drones - aliveDrones(this.last)
    const damageTaken = Math.max(0, this.startHp - this.last.mecha.hp)
    const plan = extras.plan
    return {
      run,
      outcome,
      startDelayS: extras.startDelayS,
      durationS,
      clearTimeS,
      drones: this.drones,
      kills,
      damageTaken,
      shots: this.shots,
      hits: this.hits,
      reactionMs: extras.reactionMs,
      planFirstStepMs: plan?.timing.firstStepMs ?? null,
      planTotalMs: plan?.timing.totalMs ?? null,
      planAttempts: plan ? plan.attempts : null,
      score: scoreRun({ drones: this.drones, kills, clearTimeS, timeLimitS: this.timeLimitS, damageTaken, maxHp: this.maxHp }),
    }
  }
}

function aliveDrones(state: StateMessage): number {
  return state.units.filter((unit) => unit.alive).length
}

function round(value: number): number {
  return Math.round(value * DECIMALS) / DECIMALS
}
