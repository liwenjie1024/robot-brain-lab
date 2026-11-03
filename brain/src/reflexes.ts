import type { FlightVelocity } from '@shared/sim/generated/message'
import type { Evasion } from '@shared/brain/generated/control'
import type { Reflex } from '@shared/brain/generated/status'
import type { Perception, ThreatView } from './perception'

/** 피하는 빠르기. 경고(1.2초) 동안 옆 가속 15m/s²로 약 10m 벗어나 몸통 폭(약 4m)을 넘긴다. */
export const DODGE_SPEED = 20
/** 쏘는 때가 지나고도 이만큼 더 피하거나 막는다 (경고 시각이 상태 간격만큼 늦게 올 수 있어서) */
const REFLEX_TAIL_S = 0.3

export interface ReflexAction extends Reflex {
  /** 피하기 속도 (피하지 않으면 없음) */
  velocity?: FlightVelocity
  /** 방패로 막을 유닛 (막지 않으면 없음) */
  guardUnit?: string
  /** 이번 판단에서 새로 시작했는지 (반응 시간을 잴 때 쓴다) */
  started: boolean
}

/**
 * 반사: 조준 경고(위협)를 처음 보면 기술과 상관없이 곧바로 피하거나 막는다. 언어 모델을 거치지 않는다.
 *
 * 드론은 조준을 시작할 때의 위치·속도로 쏠 자리를 셈한다. 그래서
 * - 피하기: 새 경고마다 속도를 다시 바꾼다. 피하는 중에 새 드론이 조준하면 그 드론은 피하는 속도로 셈했으므로,
 *   같은 속도로 계속 피하면 맞는다.
 * - 막기: 가장 먼저 쏠 드론 쪽으로 방패를 든다 (그 드론이 쏘고 나면 다음 드론 쪽으로).
 * 같은 경고가 이어지는 동안은 다시 시작하지 않는다 (중복 반응 없음).
 */
export class EvasionReflex {
  private active: ReflexAction | null = null
  private seen = new Set<string>()

  reset(): void {
    this.active = null
    this.seen.clear()
  }

  update(perception: Perception, evasion: Evasion): ReflexAction | null {
    const { threats, simTime } = perception
    const fresh = threats.filter((threat) => !this.seen.has(threat.from))
    this.seen = new Set(threats.map((threat) => threat.from))
    if (evasion === 'none') {
      this.active = null
      return null
    }
    if (this.active && simTime > this.active.until) {
      this.active = null
    }
    const soonest = threats[0]
    const first = fresh[0]
    if (first) {
      const lastFire = Math.max(...threats.map((threat) => threat.secondsToFire))
      const action: ReflexAction = { kind: evasion, threat: first.from, until: simTime + lastFire + REFLEX_TAIL_S, started: true }
      if (evasion !== 'guard') {
        action.velocity = dodgeVelocity(perception, first)
      }
      if (evasion !== 'dodge') {
        action.guardUnit = (soonest ?? first).from
      }
      this.active = action
      return action
    }
    if (this.active) {
      const guardUnit = this.active.guardUnit && soonest ? soonest.from : this.active.guardUnit
      this.active = { ...this.active, guardUnit, started: false }
    }
    return this.active
  }
}

/**
 * 위협 쪽과 직각으로 피한다. 두 직각 방향 중 지금 속도와 반대쪽을 골라 속도가 가장 크게 바뀌게 한다
 * (드론이 셈한 자리에서 가장 멀어진다). 몸의 범위에 맞추는 일은 명령 담당이 한다.
 */
export function dodgeVelocity(perception: Perception, threat: ThreatView): FlightVelocity {
  const angle = threat.bearing ?? 0
  const side = { forward: -Math.sin(angle), sideways: Math.cos(angle) }
  const current = perception.self.velocity
  const sign = side.forward * current.forward + side.sideways * current.sideways > 0 ? -1 : 1
  return { forward: sign * side.forward * DODGE_SPEED, sideways: sign * side.sideways * DODGE_SPEED, up: 0, turn: 0 }
}
