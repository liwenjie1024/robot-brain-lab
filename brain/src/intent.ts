import type { FlightVelocity } from '@shared/sim/generated/message'

/** 두뇌가 이번 판단에서 "이렇게 하고 싶다"고 정한 것. 몸에 보낼 명령은 명령 담당(Commander)이 바뀐 것만 고른다. */

export type GuardIntent = { raised: false } | { raised: true; unit: string | null }

export interface Intent {
  velocity: FlightVelocity
  /** 겨눌 유닛 (null이면 소총을 내린다) */
  aim: string | null
  guard: GuardIntent
  fire: boolean
  /** 지금 하는 일 (사람이 읽는 글) */
  activity: string
  /** 지금 노리는 유닛 */
  target: string | null
}

export const STILL: FlightVelocity = { forward: 0, sideways: 0, up: 0, turn: 0 }
export const GUARD_DOWN: GuardIntent = { raised: false }
