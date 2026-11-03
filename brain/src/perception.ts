import type { FlightVelocity, GuardStatus, MechaMode, StateMessage, WeaponStatus } from '@shared/sim/generated/message'
import { bearing, length, subtract, type Vec3 } from './geometry'

/**
 * 몸이 보낸 상태를 두뇌가 쓰기 좋게 바꾼 "지금 보이는 것". 판단은 이것만 본다 (몸의 메시지 모양이 바뀌어도 여기만 고친다).
 * 지금은 시뮬레이터가 주는 정확한 값이다. 나중에 센서 잡음·시야를 더하면 여기서 한다.
 */

export interface SelfView {
  position: Vec3
  heading: number
  velocity: FlightVelocity
  mode: MechaMode
  hp: number
  maxHp: number
  energy: number
  weapon: WeaponStatus
  guard: GuardStatus
}

export interface TargetView {
  id: string
  name: string
  position: Vec3
  distance: number
  /** 기수에서 돌아간 각 (왼쪽 +) */
  bearing: number
  hp: number
  maxHp: number
  armed: boolean
}

export interface ThreatView {
  from: string
  secondsToFire: number
  /** 쏘려는 유닛이 있는 쪽 (모르면 null) */
  bearing: number | null
}

export interface Perception {
  simTime: number
  scenario: string
  self: SelfView
  /** 살아 있는 드론, 가까운 순 */
  targets: TargetView[]
  /** 쏘기까지 남은 시간이 짧은 순 */
  threats: ThreatView[]
}

export function perceive(state: StateMessage): Perception {
  const mecha = state.mecha
  const self: SelfView = {
    position: mecha.position,
    heading: mecha.heading,
    velocity: mecha.velocity,
    mode: mecha.mode,
    hp: mecha.hp,
    maxHp: mecha.maxHp,
    energy: mecha.energy,
    weapon: mecha.weapon,
    guard: mecha.guard,
  }
  const positions = new Map(state.units.map((unit) => [unit.id, unit.position]))
  const targets = state.units
    .filter((unit) => unit.alive)
    .map((unit) => ({
      id: unit.id,
      name: unit.name,
      position: unit.position,
      distance: length(subtract(unit.position, mecha.position)),
      bearing: bearing(mecha.position, mecha.heading, unit.position),
      hp: unit.hp,
      maxHp: unit.maxHp,
      armed: unit.armed,
    }))
    .sort((a, b) => a.distance - b.distance)
  const threats = state.threats
    .map((threat) => {
      const position = positions.get(threat.from)
      return {
        from: threat.from,
        secondsToFire: threat.secondsToFire,
        bearing: position ? bearing(mecha.position, mecha.heading, position) : null,
      }
    })
    .sort((a, b) => a.secondsToFire - b.secondsToFire)
  return { simTime: state.simTime, scenario: state.scenario, self, targets, threats }
}
