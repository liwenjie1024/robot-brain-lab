// contracts/brain/control.schema.json에서 만든 파일이다. 직접 고치지 말고 npm run contracts 로 다시 만든다.

/**
 * 화면이 두뇌에게 보내는 지시. 기술을 직접 고르거나(setSkill), 말로 명령해 느린 뇌가 계획을 짜게 하거나(order), 같은 시험을 여러 번 돌려 점수를 낸다(startTrials). 두뇌는 controlResult로 답한다.
 */
export type BrainControl = SetSkill | SetAutonomy | Order | CancelPlan | StartTrials | StopTrials
export type ControlId = string
/**
 * idle: 아무것도 안 함(멈춤), hold: 자리 지키기, engage: 교전, retreat: 물러나기
 */
export type SkillName = 'idle' | 'hold' | 'engage' | 'retreat'
/**
 * 조준 경고를 받았을 때. dodge: 옆으로 피하기, guard: 방패로 막기, both: 둘 다, none: 하지 않음
 */
export type Evasion = 'dodge' | 'guard' | 'both' | 'none'
/**
 * 시험에서 비교할 것 하나
 */
export type TrialSetup = SkillTrialSetup | OrderTrialSetup

/**
 * 기술을 고른다. target은 교전할 드론 (없으면 두뇌가 고른다).
 */
export interface SetSkill {
  type: 'setSkill'
  id?: ControlId
  skill: SkillName
  target?: string
  evasion?: Evasion
}
/**
 * enabled: true면 두뇌가 몸에 명령을 보내고, false면 보기만 한다 (사람이 조종).
 */
export interface SetAutonomy {
  type: 'setAutonomy'
  id?: ControlId
  enabled: boolean
}
/**
 * 말로 한 명령 (1~200자). 느린 뇌가 계획을 짜 기술을 차례로 고른다. 받으면 두뇌가 조종을 맡는다.
 */
export interface Order {
  type: 'order'
  id?: ControlId
  text: string
}
/**
 * 지금 짜거나 따르는 계획을 그만둔다 (기체는 지금 기술을 그대로 한다).
 */
export interface CancelPlan {
  type: 'cancelPlan'
  id?: ControlId
}
/**
 * 시험: 비교할 것(setups)마다 장면을 처음으로 되돌려 runs판씩 돌리고, 판마다 결과와 점수를 낸다. 한 판은 드론을 다 격파하거나, 기체가 파괴되거나, timeLimitS초가 지나면 끝난다.
 */
export interface StartTrials {
  type: 'startTrials'
  id?: ControlId
  scenario: string
  /**
   * @minItems 1
   * @maxItems 6
   */
  setups:
    | [TrialSetup]
    | [TrialSetup, TrialSetup]
    | [TrialSetup, TrialSetup, TrialSetup]
    | [TrialSetup, TrialSetup, TrialSetup, TrialSetup]
    | [TrialSetup, TrialSetup, TrialSetup, TrialSetup, TrialSetup]
    | [TrialSetup, TrialSetup, TrialSetup, TrialSetup, TrialSetup, TrialSetup]
  runs: number
  timeLimitS: number
  /**
   * 판마다 두뇌가 맡는 때를 장면을 되돌린 뒤 0~startSpreadS초 사이로 고르게 늦춘다 (n판이면 판마다 startSpreadS÷n씩). 드론이 조준하는 때와 두뇌가 맡는 때의 어긋남을 고루 보려고. 0이면 모든 판이 똑같다 (몸과 두뇌는 같은 때 맡으면 같은 결과를 낸다).
   */
  startSpreadS: number
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
 * 돌고 있는 시험을 멈춘다 (끝난 판의 결과는 남긴다)
 */
export interface StopTrials {
  type: 'stopTrials'
  id?: ControlId
}
