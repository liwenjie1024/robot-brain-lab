import type { Evasion, SkillName, StartTrials, TrialSetup } from '@shared/brain/generated/control'
import type { PlanStatus, TrialSeries } from '@shared/brain/generated/status'
import { trialSetupLabel } from '@shared/brain/labels'
import type { ScenarioName } from '@shared/sim/generated/command'
import type { StateMessage } from '@shared/sim/generated/message'
import type { ScenarioInfo } from '@shared/sim/generated/scene'
import type { CombatEvent } from '@shared/sim/simClient'
import type { CommandSender } from '../commander'
import { RunRecorder, type RunOutcome } from './runRecorder'
import { summarize } from './trialStats'
import type { TrialStore } from './trialStore'

/** 장면 되돌리기에 몸이 이만큼 안에 답하지 않으면 시험을 멈춘다 */
export const RESET_TIMEOUT_MS = 5000
const DECIMALS = 10
const DELAY_DECIMALS = 100
/** 시뮬레이션 시각은 실수 오차가 있다 (정확히 늦춘 때를 놓치지 않게) */
const TIME_EPSILON_S = 1e-6

const OUTCOME_LABELS: Record<RunOutcome, string> = {
  cleared: '다 격파',
  destroyed: '기체 파괴',
  timeout: '제한 시간 지남',
}

/** 시험이 두뇌에게 시키는 것 (Brain이 채운다) */
export interface TrialSubject {
  setSkill(name: SkillName, target: string | null, evasion: Evasion): void
  setAutonomy(enabled: boolean): void
  /** 말로 명령한다 (기억한 계획을 쓰지 않고 새로 짠다) */
  order(text: string): Promise<void>
  /** 이 판의 반사 반응 시간 평균 */
  reactionMs(): number | null
  plan(): PlanStatus | null
}

export interface TrialRunnerDeps {
  sender: CommandSender
  subject: TrialSubject
  store: TrialStore
  /** 판단 기록에 한 줄 */
  note: (text: string) => void
  now: () => number
  clock?: () => Date
}

type Phase =
  | { kind: 'resetting'; sentAt: number; acknowledged: boolean; episodeBefore: number | null }
  | { kind: 'waiting'; firstSimTime: number; episode: number }
  | { kind: 'running'; recorder: RunRecorder; episode: number }

/**
 * 시험: 비교할 것마다 장면을 처음으로 되돌리고 두뇌에게 맡겨 여러 판을 돌린 뒤, 판마다 결과와 점수를, 모아서 가운데 값을 낸다.
 * 몸과 두뇌는 같은 때 맡으면 같은 결과를 낸다 (재 보니 다섯 판이 모두 똑같았다). 결과를 크게 바꾸는 것은 두뇌가 맡는 때와
 * 드론이 조준하는 때의 어긋남이라, 판마다 맡는 때를 고르게 늦춰(startSpreadS) 그 어긋남을 고루 본다.
 * 비교할 것을 번갈아 돌린다 (1판째를 모두 돌리고 2판째로). 중간에 멈춰도 견줄 수 있고, 시간에 따라 바뀌는 것(GPU 온도 등)이 한쪽에 몰리지 않는다.
 */
export class TrialRunner {
  private series: TrialSeries | null = null
  private phase: Phase | null = null
  private scenarios: ScenarioInfo[] = []
  private simConnected = false
  private lastEpisode: number | null = null

  constructor(private readonly deps: TrialRunnerDeps) {}

  get running(): boolean {
    return this.series?.state === 'running'
  }

  setScenarios(scenarios: ScenarioInfo[]): void {
    this.scenarios = scenarios
  }

  setSimConnected(connected: boolean): void {
    this.simConnected = connected
    if (!connected && this.running) {
      this.end('failed', '몸(시뮬레이터)과 연결이 끊겼습니다')
    }
  }

  /** 시험을 시작한다. 시작할 수 없으면 까닭 */
  start(spec: StartTrials): string | null {
    if (this.running) {
      return '이미 시험 중입니다'
    }
    if (!this.simConnected) {
      return '몸(시뮬레이터)에 연결되어야 시험할 수 있습니다'
    }
    const scenario = this.scenarios.find((item) => item.name === spec.scenario)
    if (!scenario) {
      return `그런 시험 장면이 없습니다: ${spec.scenario}`
    }
    if (scenario.drones === 0) {
      return `${scenario.label}에는 드론이 없어 점수를 낼 수 없습니다`
    }
    this.series = {
      state: 'running',
      scenario: spec.scenario,
      runs: spec.runs,
      timeLimitS: spec.timeLimitS,
      startSpreadS: spec.startSpreadS,
      startedAt: this.timestamp(),
      finishedAt: null,
      setups: spec.setups.map((setup) => ({ setup, label: trialSetupLabel(setup), results: [], summary: null })),
      current: null,
      error: null,
      savedTo: null,
    }
    const spread = spec.startSpreadS > 0 ? `, 맡는 때를 0~${spec.startSpreadS}초 늦춤` : ''
    this.deps.note(`시험 시작: ${scenario.label}, ${spec.setups.length}가지 × ${spec.runs}판 (한 판 ${spec.timeLimitS}초까지${spread})`)
    this.beginRun(0, 1)
    return null
  }

  /** 사람이 멈춘다 (끝난 판의 결과는 남긴다). 돌고 있지 않으면 false */
  stop(): boolean {
    if (!this.running) {
      return false
    }
    this.end('stopped', null)
    return true
  }

  onState(state: StateMessage): void {
    this.lastEpisode = state.episode
    const phase = this.phase
    if (!this.running || !phase) {
      return
    }
    if (phase.kind === 'resetting') {
      this.awaitFirstState(phase, state)
      return
    }
    if (state.episode !== phase.episode) {
      this.end('failed', '시험 중에 다른 곳에서 장면을 처음으로 되돌렸습니다')
      return
    }
    if (phase.kind === 'waiting') {
      this.awaitTakeover(phase, state)
      return
    }
    const outcome = phase.recorder.update(state)
    this.progress().elapsedS = round(phase.recorder.elapsedS)
    if (outcome) {
      this.finishRun(phase.recorder, outcome)
    }
  }

  onCombat(event: CombatEvent): void {
    if (this.phase?.kind === 'running') {
      this.phase.recorder.onCombat(event)
    }
  }

  status(): TrialSeries | null {
    return this.series ? structuredClone(this.series) : null
  }

  private beginRun(setup: number, run: number): void {
    const series = this.series!
    series.current = { setup, run, phase: 'resetting', startDelayS: startDelay(run, series.runs, series.startSpreadS), elapsedS: 0 }
    const phase: Phase = { kind: 'resetting', sentAt: this.deps.now(), acknowledged: false, episodeBefore: this.lastEpisode }
    this.phase = phase
    this.deps.subject.setAutonomy(false)
    // 장면 이름은 몸이 /scene으로 알린 것 가운데 하나다 (start에서 확인함)
    const reset = { type: 'reset', scenario: series.scenario as ScenarioName } as const
    this.deps.sender.send(reset).then(
      (result) => {
        if (this.phase !== phase) {
          return
        }
        if (result.accepted) {
          phase.acknowledged = true
        } else {
          this.end('failed', `몸이 장면 되돌리기를 거절함: ${result.reason ?? ''}`)
        }
      },
      (error: unknown) => {
        if (this.phase === phase) {
          this.end('failed', `장면을 되돌리지 못함: ${error instanceof Error ? error.message : String(error)}`)
        }
      },
    )
  }

  /**
   * 되돌리기의 답을 받고, 되돌린 횟수(episode)가 늘어난 첫 상태가 되돌린 장면의 첫 상태다.
   * 답과 상태의 순서에 기대지 않는다 (ROS 2로 붙으면 서비스 답과 상태 토픽이 다른 길로 온다).
   */
  private awaitFirstState(phase: Extract<Phase, { kind: 'resetting' }>, state: StateMessage): void {
    const reset = phase.acknowledged && (phase.episodeBefore === null || state.episode > phase.episodeBefore)
    if (!reset) {
      if (this.deps.now() - phase.sentAt > RESET_TIMEOUT_MS) {
        this.end('failed', '장면을 처음으로 되돌리지 못했습니다 (몸이 답하지 않음)')
      }
      return
    }
    const series = this.series!
    if (state.scenario !== series.scenario) {
      this.end('failed', `되돌린 장면이 다릅니다: ${state.scenario}`)
      return
    }
    const waiting: Phase = { kind: 'waiting', firstSimTime: state.simTime, episode: state.episode }
    this.phase = waiting
    this.progress().phase = 'waiting'
    this.awaitTakeover(waiting, state)
  }

  /** 정한 만큼 늦춘 뒤 두뇌에게 맡긴다. 판의 시간·피해는 이때부터 잰다 (기다리는 동안 맞은 것은 두뇌 탓이 아니다). */
  private awaitTakeover(phase: Extract<Phase, { kind: 'waiting' }>, state: StateMessage): void {
    const progress = this.progress()
    if (state.simTime - phase.firstSimTime + TIME_EPSILON_S < progress.startDelayS) {
      return
    }
    const recorder = new RunRecorder(state, this.series!.timeLimitS)
    if (recorder.drones === 0) {
      this.end('failed', '이 장면에는 드론이 없어 점수를 낼 수 없습니다')
      return
    }
    this.phase = { kind: 'running', recorder, episode: phase.episode }
    progress.phase = 'running'
    const entry = this.series!.setups[progress.setup]!
    const delay = progress.startDelayS > 0 ? ` (${progress.startDelayS}초 늦춰 맡음)` : ''
    this.deps.note(`시험 ${progress.run}판째: ${entry.label}${delay}`)
    this.apply(entry.setup)
  }

  private apply(setup: TrialSetup): void {
    if (setup.kind === 'skill') {
      this.deps.subject.setSkill(setup.skill, null, setup.evasion)
      this.deps.subject.setAutonomy(true)
    } else {
      void this.deps.subject.order(setup.text)
    }
  }

  private finishRun(recorder: RunRecorder, outcome: RunOutcome): void {
    const series = this.series!
    const { setup, run, startDelayS } = this.progress()
    const entry = series.setups[setup]!
    const plan = entry.setup.kind === 'order' ? this.deps.subject.plan() : null
    const result = recorder.result(run, outcome, { startDelayS, reactionMs: this.deps.subject.reactionMs(), plan })
    entry.results.push(result)
    entry.summary = summarize(entry.results)
    const time = result.clearTimeS === null ? `${result.kills}/${result.drones} 격파` : `${result.clearTimeS}초`
    this.deps.note(`시험 ${run}판째 끝: ${entry.label} — ${OUTCOME_LABELS[outcome]} (${time}, 피해 ${result.damageTaken}, 점수 ${result.score})`)
    const next = setup + 1 < series.setups.length ? { setup: setup + 1, run } : { setup: 0, run: run + 1 }
    if (next.run > series.runs) {
      this.end('done', null)
    } else {
      this.beginRun(next.setup, next.run)
    }
  }

  private end(state: 'done' | 'stopped' | 'failed', error: string | null): void {
    const series = this.series!
    series.state = state
    series.error = error
    series.current = null
    series.finishedAt = this.timestamp()
    this.phase = null
    this.deps.subject.setAutonomy(false)
    const runs = series.setups.reduce((sum, entry) => sum + entry.results.length, 0)
    const how = { done: '다 돌림', stopped: '사람이 멈춤', failed: `더 돌릴 수 없음: ${error ?? ''}` }[state]
    this.deps.note(`시험 끝 (${how}, ${runs}판)`)
    if (runs > 0) {
      void this.save(series)
    }
  }

  private async save(series: TrialSeries): Promise<void> {
    try {
      const path = await this.deps.store.save(structuredClone(series))
      if (this.series === series) {
        series.savedTo = path
      }
    } catch (error) {
      this.deps.note(`시험 결과를 남기지 못함: ${error instanceof Error ? error.message : String(error)}`)
    }
  }

  private progress(): NonNullable<TrialSeries['current']> {
    return this.series!.current!
  }

  private timestamp(): string {
    return (this.deps.clock?.() ?? new Date()).toISOString()
  }
}

function round(value: number): number {
  return Math.round(value * DECIMALS) / DECIMALS
}

/** run판째(1부터)에 두뇌가 맡기까지 늦추는 초: 0, spread÷runs, 2×spread÷runs, … (같은 판 번호는 견줄 것마다 같다) */
export function startDelay(run: number, runs: number, spreadS: number): number {
  return Math.round(((spreadS * (run - 1)) / runs) * DELAY_DECIMALS) / DELAY_DECIMALS
}
