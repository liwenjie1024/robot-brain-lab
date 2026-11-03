import { clamp } from '../geometry'
import { GUARD_DOWN, type Intent, STILL } from '../intent'
import type { Perception, TargetView } from '../perception'
import type { Skill } from './skill'

/** 머물 거리 (드론의 사거리 600m 안, 소총이 잘 맞는 거리). 이 띠 안이면 앞뒤로 움직이지 않는다. */
export const PREFERRED_RANGE_M = 170
const RANGE_BAND_M = 50
const RANGE_GAIN = 0.25
const MAX_CLOSING_SPEED = 25
const MAX_BACKING_SPEED = 12
/** 표적 쪽으로 도는 빠르기 = 어긋난 각 × 이 값 (몸이 허용하는 1.2rad/s 안) */
const TURN_GAIN = 1.5
const MAX_TURN = 1.0
/** 표적과 높이를 맞추는 빠르기 = 높이 차 × 이 값 */
const ALTITUDE_GAIN = 0.5
const MAX_CLIMB = 8
/**
 * 쏘아도 되는 어긋남: 총열 방향이 표적 중심에서 이만큼(m) 안을 지나가는 각. 드론 몸통 반지름(1.6m)보다 작게 잡아
 * 거리가 멀수록 더 정확히 겨눈 뒤 쏜다 (150m에서 약 0.38°, 270m에서 약 0.21°). 가까워도 FIRE_ERROR_DEG를 넘지 않는다.
 */
export const FIRE_TOLERANCE_M = 1.0
export const FIRE_ERROR_DEG = 0.5
const SHOT_ENERGY = 20
/** 표적 고르기: 무장한 드론과 지금 나를 조준하는 드론을 먼저 (거리에 곱하는 값, 작을수록 먼저) */
const ARMED_WEIGHT = 0.6
const LOCKING_WEIGHT = 0.5
const WOUNDED_WEIGHT = 0.8
/** 다른 표적이 지금 표적보다 이만큼 더 좋아야 바꾼다 (표적을 오락가락하지 않게) */
const SWITCH_MARGIN = 0.6

/**
 * 교전: 표적을 골라 기수를 돌리고, 거리 띠와 높이를 맞추고, 조준이 맞을 때만 쏜다.
 * target을 주면 그 드론만 노린다 (파괴되면 다른 드론을 고른다).
 */
export class EngageSkill implements Skill {
  readonly name = 'engage' as const
  private current: string | null = null

  constructor(private readonly preferred: string | null = null) {}

  decide(perception: Perception): Intent {
    const target = this.chooseTarget(perception)
    this.current = target?.id ?? null
    if (!target) {
      return { velocity: STILL, aim: null, guard: GUARD_DOWN, fire: false, activity: '교전할 드론이 없습니다', target: null }
    }
    const { self } = perception
    const facing = Math.max(0, Math.cos(target.bearing))
    const rangeError = target.distance - PREFERRED_RANGE_M
    const forward = Math.abs(rangeError) < RANGE_BAND_M ? 0 : clamp(RANGE_GAIN * rangeError * facing, -MAX_BACKING_SPEED, MAX_CLOSING_SPEED)
    const velocity = {
      forward,
      sideways: 0,
      up: clamp(ALTITUDE_GAIN * (target.position[2] - self.position[2]), -MAX_CLIMB, MAX_CLIMB),
      turn: clamp(TURN_GAIN * target.bearing, -MAX_TURN, MAX_TURN),
    }
    const aimed = self.weapon.aimTarget === target.id && (self.weapon.aimError ?? Infinity) < allowedAimError(target.distance)
    const fire = aimed && self.weapon.ready && self.energy >= SHOT_ENERGY
    return { velocity, aim: target.id, guard: GUARD_DOWN, fire, activity: describe(target, self.weapon.aimError, aimed), target: target.id }
  }

  private chooseTarget(perception: Perception): TargetView | undefined {
    const alive = perception.targets
    const preferred = alive.find((target) => target.id === this.preferred)
    if (preferred) {
      return preferred
    }
    const locking = new Set(perception.threats.map((threat) => threat.from))
    const score = (target: TargetView) =>
      target.distance *
      (target.armed ? ARMED_WEIGHT : 1) *
      (locking.has(target.id) ? LOCKING_WEIGHT : 1) *
      (target.hp < target.maxHp ? WOUNDED_WEIGHT : 1)
    const best = alive.reduce<TargetView | undefined>((chosen, target) => (!chosen || score(target) < score(chosen) ? target : chosen), undefined)
    const current = alive.find((target) => target.id === this.current)
    if (current && best && score(best) > score(current) * SWITCH_MARGIN) {
      return current
    }
    return best
  }
}

/** 이 거리에서 쏘아도 되는 어긋남 (도) */
export function allowedAimError(distance: number): number {
  return Math.min(FIRE_ERROR_DEG, (Math.atan(FIRE_TOLERANCE_M / distance) * 180) / Math.PI)
}

function describe(target: TargetView, aimError: number | undefined, aimed: boolean): string {
  const distance = `${Math.round(target.distance)} m`
  if (aimed) {
    return `${target.name} 조준 맞음 (${distance}) — 쏠 수 있으면 쏨`
  }
  if (aimError === undefined) {
    return `${target.name} 쪽으로 도는 중 (${distance})`
  }
  return `${target.name} 겨누는 중 (${distance}, 어긋남 ${aimError.toFixed(1)}°)`
}
