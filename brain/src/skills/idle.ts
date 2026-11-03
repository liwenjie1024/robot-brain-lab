import { GUARD_DOWN, type Intent, STILL } from '../intent'
import type { Skill } from './skill'

/** 아무것도 하지 않고 그 자리에 멈춘다 (공중이면 떠 있는다). */
export class IdleSkill implements Skill {
  readonly name = 'idle' as const

  decide(): Intent {
    return { velocity: STILL, aim: null, guard: GUARD_DOWN, fire: false, activity: '멈춰서 지시를 기다림', target: null }
  }
}
