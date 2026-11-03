// contracts/sim/message.schema.json에서 만든 파일이다. 직접 고치지 말고 npm run contracts 로 다시 만든다.

/**
 * 몸(시뮬레이터)이 WebSocket으로 보내는 메시지.
 */
export type SimMessage = StateMessage | AckMessage | RejectedMessage
/**
 * @minItems 3
 * @maxItems 3
 */
export type Vector3 = [number, number, number]
/**
 * standing: 서 있음, fallen: 넘어짐 (골반이 낮거나 많이 기욺)
 */
export type Posture = 'standing' | 'fallen'

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
   * 처음 자세 뒤 지난 시뮬레이션 시각 s
   */
  simTime: number
  /**
   * 움직이는 몸체마다 [x, y, z, qw, qx, qy, qz] 7개씩 (순서는 GET /scene의 movingBodies)
   */
  bodies: number[]
  robot: RobotStatus
}
/**
 * position: 골반 위치 [x, y, z] m (x 앞, y 왼쪽, z 위), velocity: 몸 기준 실제 속도, command: 지금 따르는 걷기 명령
 */
export interface RobotStatus {
  position: Vector3
  /**
   * 바라보는 방향 rad (x축에서 왼쪽으로 돈 각)
   */
  yaw: number
  velocity: Velocity
  command: Velocity
  posture: Posture
  /**
   * 시험용 밀기가 지금 걸려 있는지
   */
  pushing: boolean
}
export interface Velocity {
  /**
   * 앞(+)/뒤(-) m/s
   */
  forward: number
  /**
   * 왼쪽(+)/오른쪽(-) m/s
   */
  sideways: number
  /**
   * 왼쪽으로 도는(+) rad/s
   */
  turn: number
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
