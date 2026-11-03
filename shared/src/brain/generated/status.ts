// contracts/brain/status.schema.json에서 만든 파일이다. 직접 고치지 말고 npm run contracts 로 다시 만든다.

/**
 * 두뇌가 화면에 보내는 메시지. 상태는 1초에 5번, 판단 기록과 지시의 답은 생길 때마다.
 */
export type BrainMessage = BrainStatus | Decision | ControlResult
/**
 * skill: 기술 바뀜, target: 표적 바뀜, fire: 사격, reflex: 반사 시작, result: 결과(맞힘·격파·피해), command: 몸이 명령을 거절함
 */
export type DecisionKind = 'skill' | 'target' | 'fire' | 'reflex' | 'result' | 'command'

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
