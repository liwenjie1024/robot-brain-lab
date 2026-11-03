import type { SkillName } from '@shared/brain/generated/control'
import type { Intent } from '../intent'
import type { Perception } from '../perception'

/**
 * 기술: 사람(나중에는 느린 뇌)이 고르는 "무엇을 할지". 매 판단마다 지금 보이는 것으로 의도를 정한다.
 * 반사(피하기·막기)는 기술 위에 따로 얹힌다 (reflexes.ts).
 */
export interface Skill {
  readonly name: SkillName
  decide(perception: Perception): Intent
}
