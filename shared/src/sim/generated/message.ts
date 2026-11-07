// contracts/sim/message.schema.json에서 만든 파일이다. 직접 고치지 말고 npm run contracts 로 다시 만든다.

/**
 * 몸(시뮬레이터)이 WebSocket으로 보내는 메시지. 상태는 제어 주기마다(밀리면 가장 새 것만), 답과 사건은 빠짐없이 만든 순서대로 온다.
 */
export type SimMessage = StateMessage | AckMessage | RejectedMessage | ShotMessage | DestroyedMessage
/**
 * @minItems 3
 * @maxItems 3
 */
export type Vector3 = [number, number, number]
/**
 * landed: 착지(추진기 끔), flying: 비행 중, destroyed: 파괴됨
 */
export type MechaMode = 'landed' | 'flying' | 'destroyed'

/**
 * 제어 주기마다 보내는 지금 상태.
 */
export interface StateMessage {
  type: 'state'
  /**
   * 보낸 순서 (처음으로 되돌려도 계속 는다)
   */
  seq: number
  /**
   * 처음으로 되돌린 횟수 (띄울 때 0, 되돌릴 때마다 1씩). 명령의 답과 상태가 다른 길로 오는 연결(ROS 2)에서도 되돌린 뒤의 상태를 알아본다.
   */
  episode: number
  /**
   * 처음으로 되돌린 뒤 지난 시뮬레이션 시각 s
   */
  simTime: number
  scenario: string
  /**
   * 움직이는 몸체마다 [x, y, z, qw, qx, qy, qz] 7개씩 (순서는 GET /scene의 movingBodies)
   */
  bodies: number[]
  mecha: MechaStatus
  units: UnitStatus[]
  threats: Threat[]
}
/**
 * 기체 상태. position: 몸통 중심 [x, y, z] m, heading: 기수 방향 rad (x축에서 왼쪽으로), altitude: 발바닥 높이 m, velocity: 실제 속도, command: 따르는 비행 명령, hp·maxHp: 체력, energy: 소총 에너지 (0~100)
 */
export interface MechaStatus {
  position: Vector3
  heading: number
  altitude: number
  velocity: FlightVelocity
  command: FlightVelocity
  mode: MechaMode
  hp: number
  maxHp: number
  energy: number
  weapon: WeaponStatus
  guard: GuardStatus
  /**
   * 시험용 밀기가 지금 걸려 있는지
   */
  pushing: boolean
}
/**
 * 기수 방향 기준 속도. forward: 앞 m/s, sideways: 왼쪽 m/s, up: 위 m/s, turn: 왼쪽으로 도는 rad/s
 */
export interface FlightVelocity {
  forward: number
  sideways: number
  up: number
  turn: number
}
/**
 * 빔 소총. ready: 지금 쏠 수 있음, cooldown: 식는 데 남은 초, aimTarget: 겨누는 유닛, aimError: 총열이 겨눈 점에서 벗어난 각(도), aimPoint: 겨눈 점
 */
export interface WeaponStatus {
  ready: boolean
  cooldown: number
  aimTarget: string | null
  aimError?: number
  aimPoint?: Vector3
}
/**
 * 방패. raised: 들고 있음, unit: 막는 쪽의 유닛 (없으면 앞)
 */
export interface GuardStatus {
  raised: boolean
  unit: string | null
}
/**
 * 이 장면의 드론. position·velocity: 세계 좌표, alive: 살아 있음, armed: 반격함
 */
export interface UnitStatus {
  id: string
  kind: 'drone'
  name: string
  position: Vector3
  velocity: Vector3
  hp: number
  maxHp: number
  alive: boolean
  armed: boolean
}
/**
 * 기체를 조준하고 있는 유닛과 쏘기까지 남은 초
 */
export interface Threat {
  from: string
  secondsToFire: number
}
/**
 * 명령을 받아 적용했다.
 */
export interface AckMessage {
  type: 'ack'
  id?: string
  commandType: string
  /**
   * 적용한 시뮬레이션 시각 s
   */
  simTime: number
}
/**
 * 명령을 거절했다. reason은 사람이 읽는 까닭.
 */
export interface RejectedMessage {
  type: 'rejected'
  id?: string
  reason: string
}
/**
 * 사격. from에서 to까지 나갔다 (to는 처음 닿은 곳이나 사거리 끝). hit이 없으면 빗나감.
 */
export interface ShotMessage {
  type: 'shot'
  simTime: number
  shooter: string
  from: Vector3
  to: Vector3
  hit?: Hit
}
/**
 * 맞힌 유닛. blocked: 방패에 막혀 피해가 없음
 */
export interface Hit {
  unit: string
  damage: number
  blocked: boolean
}
/**
 * 유닛이 파괴되었다.
 */
export interface DestroyedMessage {
  type: 'destroyed'
  simTime: number
  unit: string
}
