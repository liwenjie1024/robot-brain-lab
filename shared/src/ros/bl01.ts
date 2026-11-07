import type { DestroyedMessage, ShotMessage, StateMessage } from '../sim/generated/message'
import type { OutgoingCommand } from '../sim/simClient'

/**
 * BL-01 ROS 2 메시지(ros/src/bl01_msgs)와 몸의 규약(contracts/sim)을 잇는다. ros/src/bl01_driver/convert.py와 거꾸로 짝이다.
 * 받은 메시지는 여기서 규약 모양으로 바꾸고, 쓰는 쪽이 규약 스키마로 확인한다 (바꾸다 모양이 다르면 예외).
 */

export const BL01 = {
  state: { topic: '/bl01/state', type: 'bl01_msgs/msg/State' },
  combat: { topic: '/bl01/combat', type: 'bl01_msgs/msg/CombatEvent' },
  link: { topic: '/bl01/link', type: 'std_msgs/msg/Bool' },
  getScene: { service: '/bl01/get_scene', type: 'bl01_msgs/srv/GetScene' },
} as const

const SERVICE_TYPES: Record<OutgoingCommand['type'], { service: string; type: string }> = {
  velocity: { service: '/bl01/set_velocity', type: 'bl01_msgs/srv/SetVelocity' },
  stop: { service: '/bl01/stop', type: 'bl01_msgs/srv/Stop' },
  aim: { service: '/bl01/aim', type: 'bl01_msgs/srv/Aim' },
  aimPoint: { service: '/bl01/aim_point', type: 'bl01_msgs/srv/AimPoint' },
  lowerAim: { service: '/bl01/lower_aim', type: 'bl01_msgs/srv/LowerAim' },
  guard: { service: '/bl01/guard', type: 'bl01_msgs/srv/Guard' },
  fire: { service: '/bl01/fire', type: 'bl01_msgs/srv/Fire' },
  push: { service: '/bl01/push', type: 'bl01_msgs/srv/Push' },
  reset: { service: '/bl01/reset', type: 'bl01_msgs/srv/Reset' },
}

export interface ServiceCall {
  service: string
  type: string
  args: object
}

/** 몸의 명령 → 서비스 부르기. 빈 글은 '없음' (장면 이름이 없으면 지금 장면, 막을 유닛이 없으면 앞) */
export function serviceCall(command: OutgoingCommand): ServiceCall {
  const target = SERVICE_TYPES[command.type]
  switch (command.type) {
    case 'velocity':
      return {
        ...target,
        args: {
          velocity: { linear: { x: command.forward, y: command.sideways, z: command.up }, angular: { x: 0, y: 0, z: command.turn } },
        },
      }
    case 'aim':
      return { ...target, args: { unit: command.unit } }
    case 'aimPoint':
      return { ...target, args: { point: command.point } }
    case 'guard':
      return { ...target, args: { raised: command.raised, unit: command.unit ?? '' } }
    case 'push':
      return { ...target, args: { force: command.force, duration_ms: command.durationMs } }
    case 'reset':
      return { ...target, args: { scenario: command.scenario ?? '' } }
    case 'stop':
    case 'lowerAim':
    case 'fire':
      return { ...target, args: {} }
  }
}

/* eslint-disable @typescript-eslint/no-explicit-any -- 받은 ROS 메시지는 모양을 모르는 값이다. 바꾼 뒤 규약 스키마로 확인한다 */

/** /bl01/state → 규약의 상태 메시지 (snake_case → camelCase, 빈 글·has_* → null·빠진 필드) */
export function stateFromRos(message: any): StateMessage {
  const mecha = message.mecha
  const weapon = mecha.weapon
  return {
    type: 'state',
    seq: message.seq,
    episode: message.episode,
    simTime: message.sim_time,
    scenario: message.scenario,
    bodies: [...message.bodies],
    mecha: {
      position: vector(mecha.position),
      heading: mecha.heading,
      altitude: mecha.altitude,
      velocity: velocityFromTwist(mecha.velocity),
      command: velocityFromTwist(mecha.command),
      mode: mecha.mode,
      hp: mecha.hp,
      maxHp: mecha.max_hp,
      energy: mecha.energy,
      weapon: {
        ready: weapon.ready,
        cooldown: weapon.cooldown,
        aimTarget: weapon.aim_target || null,
        ...(weapon.has_aim_error ? { aimError: weapon.aim_error } : {}),
        ...(weapon.has_aim_point ? { aimPoint: vector(weapon.aim_point) } : {}),
      },
      guard: { raised: mecha.guard.raised, unit: mecha.guard.unit || null },
      pushing: mecha.pushing,
    },
    units: message.units.map((unit: any) => ({
      id: unit.id,
      kind: unit.kind,
      name: unit.name,
      position: vector(unit.position),
      velocity: vector(unit.velocity),
      hp: unit.hp,
      maxHp: unit.max_hp,
      alive: unit.alive,
      armed: unit.armed,
    })),
    threats: message.threats.map((threat: any) => ({ from: threat.shooter, secondsToFire: threat.seconds_to_fire })),
  }
}

/** /bl01/combat → 규약의 사격·격파 사건 */
export function combatFromRos(message: any): ShotMessage | DestroyedMessage {
  if (message.kind === 'destroyed') {
    return { type: 'destroyed', simTime: message.sim_time, unit: message.unit }
  }
  return {
    type: message.kind,
    simTime: message.sim_time,
    shooter: message.shooter,
    from: vector(message.origin),
    to: vector(message.end),
    ...(message.has_hit ? { hit: { unit: message.hit_unit, damage: message.hit_damage, blocked: message.hit_blocked } } : {}),
  }
}

function velocityFromTwist(twist: any): { forward: number; sideways: number; up: number; turn: number } {
  return { forward: twist.linear.x, sideways: twist.linear.y, up: twist.linear.z, turn: twist.angular.z }
}

function vector(values: any): [number, number, number] {
  const [x, y, z] = values
  return [x, y, z]
}

/* eslint-enable @typescript-eslint/no-explicit-any */
