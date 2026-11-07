import type { FlightVelocity, ShotMessage, StateMessage } from '../sim/generated/message'
import { sceneDescription } from './fixtures'

/**
 * rosbridge가 보내는 모양의 BL-01 ROS 2 메시지 (ros/src/bl01_driver/convert.py가 만드는 것과 같게).
 * 규약 모양의 시험용 값에서 만들어, 바꾸기(bl01.ts)가 거꾸로 되돌리는지 견준다.
 */

function rosTwist(velocity: FlightVelocity) {
  return {
    linear: { x: velocity.forward, y: velocity.sideways, z: velocity.up },
    angular: { x: 0, y: 0, z: velocity.turn },
  }
}

export function rosState(state: StateMessage) {
  const mecha = state.mecha
  const weapon = mecha.weapon
  return {
    header: { stamp: { sec: Math.floor(state.simTime), nanosec: 0 }, frame_id: 'odom' },
    seq: state.seq,
    episode: state.episode,
    sim_time: state.simTime,
    scenario: state.scenario,
    bodies: state.bodies,
    mecha: {
      position: mecha.position,
      heading: mecha.heading,
      altitude: mecha.altitude,
      velocity: rosTwist(mecha.velocity),
      command: rosTwist(mecha.command),
      mode: mecha.mode,
      hp: mecha.hp,
      max_hp: mecha.maxHp,
      energy: mecha.energy,
      weapon: {
        ready: weapon.ready,
        cooldown: weapon.cooldown,
        aim_target: weapon.aimTarget ?? '',
        has_aim_error: weapon.aimError !== undefined,
        aim_error: weapon.aimError ?? 0,
        has_aim_point: weapon.aimPoint !== undefined,
        aim_point: weapon.aimPoint ?? [0, 0, 0],
      },
      guard: { raised: mecha.guard.raised, unit: mecha.guard.unit ?? '' },
      pushing: mecha.pushing,
    },
    units: state.units.map((unit) => ({
      id: unit.id,
      kind: unit.kind,
      name: unit.name,
      position: unit.position,
      velocity: unit.velocity,
      hp: unit.hp,
      max_hp: unit.maxHp,
      alive: unit.alive,
      armed: unit.armed,
    })),
    threats: state.threats.map((threat) => ({ shooter: threat.from, seconds_to_fire: threat.secondsToFire })),
  }
}

export function rosShot(shot: ShotMessage) {
  return {
    kind: 'shot',
    sim_time: shot.simTime,
    shooter: shot.shooter,
    origin: shot.from,
    end: shot.to,
    has_hit: shot.hit !== undefined,
    hit_unit: shot.hit?.unit ?? '',
    hit_damage: shot.hit?.damage ?? 0,
    hit_blocked: shot.hit?.blocked ?? false,
    unit: '',
  }
}

export function rosDestroyed(unit: string, simTime: number) {
  return {
    kind: 'destroyed',
    sim_time: simTime,
    shooter: '',
    origin: [0, 0, 0],
    end: [0, 0, 0],
    has_hit: false,
    hit_unit: '',
    hit_damage: 0,
    hit_blocked: false,
    unit,
  }
}

/** /bl01/get_scene의 답 */
export function rosSceneReply(available = true) {
  return { available, scene_json: available ? JSON.stringify(sceneDescription()) : '' }
}

export function shotMessage(overrides: Partial<ShotMessage> = {}): ShotMessage {
  return {
    type: 'shot',
    simTime: 3.5,
    shooter: 'mecha',
    from: [0, 0, 20],
    to: [40, 0, 20],
    hit: { unit: 'drone-1', damage: 100, blocked: false },
    ...overrides,
  }
}
