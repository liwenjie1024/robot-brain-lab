// contracts/brain/control.schema.json에서 만든 파일이다. 직접 고치지 말고 npm run contracts 로 다시 만든다.

/**
 * 화면(나중에는 느린 뇌 System 2)이 두뇌에게 보내는 지시. 두뇌는 controlResult로 답한다.
 */
export type BrainControl = SetSkill | SetAutonomy
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
