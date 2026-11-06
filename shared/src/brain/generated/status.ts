// contracts/brain/status.schema.json에서 만든 파일이다. 직접 고치지 말고 npm run contracts 로 다시 만든다.

/**
 * 두뇌가 화면에 보내는 메시지. 상태는 1초에 5번, 판단 기록과 지시의 답은 생길 때마다.
 */
export type BrainMessage = BrainStatus | Decision | ControlResult
/**
 * 시험에서 비교할 것 하나
 */
export type TrialSetup = SkillTrialSetup | OrderTrialSetup
/**
 * idle: 아무것도 안 함(멈춤), hold: 자리 지키기, engage: 교전, retreat: 물러나기
 */
export type SkillName = 'idle' | 'hold' | 'engage' | 'retreat'
/**
 * 조준 경고를 받았을 때. dodge: 옆으로 피하기, guard: 방패로 막기, both: 둘 다, none: 하지 않음
 */
export type Evasion = 'dodge' | 'guard' | 'both' | 'none'
/**
 * skill: 기술 바뀜, target: 표적 바뀜, fire: 사격, reflex: 반사 시작, result: 결과(맞힘·격파·피해), command: 몸이 명령을 거절함, plan: 느린 뇌의 계획(받음·짬·단계·마침·실패), trial: 시험(판 시작·끝·멈춤)
 */
export type DecisionKind = 'skill' | 'target' | 'fire' | 'reflex' | 'result' | 'command' | 'plan' | 'trial'

export interface BrainStatus {
  type: 'brainStatus'
  simConnected: boolean
  autonomy: boolean
  simTime: number | null
  skill: SkillState
  /**
   * 지금 하는 일 (사람이 읽는 글)
   */
  activity: string
  /**
   * 지금 노리는 유닛
   */
  target: string | null
  reflex: Reflex | null
  metrics: Metrics
  plan: PlanStatus | null
  planner: PlannerStatus
  trials: TrialSeries | null
}
export interface SkillState {
  name: 'idle' | 'hold' | 'engage' | 'retreat'
  /**
   * 지시받은 표적 (없으면 두뇌가 고름)
   */
  target: string | null
  evasion: 'dodge' | 'guard' | 'both' | 'none'
}
/**
 * 지금 하고 있는 반사 행동. kind: dodge 피하기·guard 막기·both 둘 다, threat: 조준한 유닛, until: 끝낼 시뮬레이션 시각
 */
export interface Reflex {
  kind: 'dodge' | 'guard' | 'both'
  threat: string
  until: number
}
/**
 * tickMicrosAvg·Max: 판단 한 번에 걸린 시간(µs, 최근 5초), commandsPerSecond: 몸에 보낸 명령 수, lastReactionMs: 마지막 조준 경고를 본 뒤 반사 명령을 몸이 받기까지(ms), shots·hits·kills: 쏜·맞힌·격파 수, damageTaken: 받은 피해
 */
export interface Metrics {
  tickMicrosAvg: number
  tickMicrosMax: number
  commandsPerSecond: number
  lastReactionMs: number | null
  shots: number
  hits: number
  kills: number
  damageTaken: number
}
/**
 * 지금 계획. source: quick(규칙으로 바로)·cache(기억해 둔 계획)·llm(언어 모델). state: thinking 짜는 중·running 따르는 중·done 마침·failed 실패·cancelled 그만둠·retreating 체력이 낮아 물러나는 중
 */
export interface PlanStatus {
  order: string
  source: 'quick' | 'cache' | 'llm'
  state: 'thinking' | 'running' | 'done' | 'failed' | 'cancelled' | 'retreating'
  say: string
  steps: PlanStepView[]
  current: number | null
  retreatBelowHp: number
  /**
   * 언어 모델에 물은 횟수 (잘못된 계획이면 까닭을 붙여 한 번 더 묻는다)
   */
  attempts: number
  timing: PlanTiming
  error: string | null
}
/**
 * 계획의 한 단계와 진행 (waiting 기다림, running 하는 중, done 끝남)
 */
export interface PlanStepView {
  skill: 'idle' | 'hold' | 'engage' | 'retreat'
  target: string | null
  evasion: 'dodge' | 'guard' | 'both' | 'none'
  until: 'targetDestroyed' | 'allDestroyed' | 'seconds' | 'hpBelow' | 'never'
  value: number
  state: 'waiting' | 'running' | 'done'
}
/**
 * 명령을 받은 때부터 ms. firstTokenMs: 언어 모델의 첫 글자, firstStepMs: 첫 단계를 시작, totalMs: 계획을 다 짬
 */
export interface PlanTiming {
  firstTokenMs: number | null
  firstStepMs: number | null
  totalMs: number | null
}
/**
 * 느린 뇌가 쓰는 언어 모델. available이 false면 짧은 명령(규칙으로 알아듣는 것)만 따른다.
 */
export interface PlannerStatus {
  model: string
  available: boolean
}
/**
 * 시험 한 묶음 (화면에 보이고, 끝나면 results/trials에 JSON으로 남긴다). state: running 도는 중·done 다 돌림·stopped 사람이 멈춤·failed 더 돌릴 수 없음(error에 까닭)
 */
export interface TrialSeries {
  state: 'running' | 'done' | 'stopped' | 'failed'
  scenario: string
  runs: number
  timeLimitS: number
  startSpreadS: number
  /**
   * 시작한 때 (ISO 8601)
   */
  startedAt: string
  finishedAt: string | null
  setups: SetupResults[]
  current: TrialProgress | null
  error: string | null
  /**
   * 결과를 남긴 파일 (남기지 못했으면 null)
   */
  savedTo: string | null
}
export interface SetupResults {
  setup: TrialSetup
  /**
   * 사람이 읽는 이름 (예: 교전 · 피하기)
   */
  label: string
  results: RunResult[]
  summary: SetupSummary | null
}
/**
 * 두뇌에게 이 기술과 조준 경고 반응을 맡겨 시험한다 (표적은 두뇌가 고른다)
 */
export interface SkillTrialSetup {
  kind: 'skill'
  skill: SkillName
  evasion: Evasion
}
/**
 * 판마다 이 말로 명령해 시험한다 (느린 뇌가 판마다 새로 계획을 짠다)
 */
export interface OrderTrialSetup {
  kind: 'order'
  text: string
}
/**
 * 한 판의 결과. outcome: cleared 드론을 다 격파·destroyed 기체가 파괴됨·timeout 제한 시간이 지남. 판은 두뇌가 맡은 때(장면을 되돌린 뒤 startDelayS초)에 시작하고, 시간·피해는 그때부터 시뮬레이션 초로 잰다. damageTaken은 체력이 준 만큼. reactionMs는 이 판의 반사 반응 시간 평균. plan*은 말로 한 명령일 때만.
 */
export interface RunResult {
  run: number
  outcome: 'cleared' | 'destroyed' | 'timeout'
  /**
   * 장면을 되돌린 뒤 두뇌가 맡기까지 늦춘 초
   */
  startDelayS: number
  durationS: number
  clearTimeS: number | null
  drones: number
  kills: number
  damageTaken: number
  shots: number
  hits: number
  reactionMs: number | null
  planFirstStepMs: number | null
  planTotalMs: number | null
  planAttempts: number | null
  /**
   * 0~100 (shared/src/brain/trialScore.ts)
   */
  score: number
}
/**
 * 비교할 것 하나의 여러 판 모음. cleared: 다 격파한 판 수, clearTimeS: 다 격파한 판만, accuracy: 맞힌 수 ÷ 쏜 수 (쏘지 않았으면 null)
 */
export interface SetupSummary {
  runs: number
  cleared: number
  score: Stat
  clearTimeS: Stat | null
  damageTaken: Stat
  accuracy: number | null
  reactionMs: Stat | null
  planFirstStepMs: Stat | null
}
/**
 * 여러 판의 값: 가운데 값(median)·가장 작은 값·가장 큰 값·평균
 */
export interface Stat {
  median: number
  min: number
  max: number
  mean: number
}
/**
 * 지금 도는 판. setup: 비교할 것의 번호(0부터), run: 판 번호(1부터), phase: resetting 장면을 되돌리는 중·waiting 두뇌가 맡기를 기다리는 중(판마다 늦춤)·running 도는 중, elapsedS: 두뇌가 맡은 뒤 지난 시뮬레이션 초
 */
export interface TrialProgress {
  setup: number
  run: number
  phase: 'resetting' | 'waiting' | 'running'
  /**
   * 이 판에서 두뇌가 맡기까지 늦추는 초
   */
  startDelayS: number
  elapsedS: number
}
/**
 * 판단 기록 한 줄. text는 무엇을 보고 무엇을 정했는지.
 */
export interface Decision {
  type: 'decision'
  seq: number
  simTime: number | null
  kind: DecisionKind
  text: string
}
export interface ControlResult {
  type: 'controlResult'
  id?: string
  accepted: boolean
  reason?: string
}
