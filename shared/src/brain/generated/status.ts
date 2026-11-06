// contracts/brain/status.schema.json에서 만든 파일이다. 직접 고치지 말고 npm run contracts 로 다시 만든다.

/**
 * 두뇌가 화면에 보내는 메시지. 상태는 1초에 5번, 판단 기록과 지시의 답은 생길 때마다.
 */
export type BrainMessage = BrainStatus | Decision | ControlResult
/**
 * skill: 기술 바뀜, target: 표적 바뀜, fire: 사격, reflex: 반사 시작, result: 결과(맞힘·격파·피해), command: 몸이 명령을 거절함, plan: 느린 뇌의 계획(받음·짬·단계·마침·실패)
 */
export type DecisionKind = 'skill' | 'target' | 'fire' | 'reflex' | 'result' | 'command' | 'plan'

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
