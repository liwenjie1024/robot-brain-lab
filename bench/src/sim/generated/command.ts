// contracts/sim/command.schema.json에서 만든 파일이다. 직접 고치지 말고 npm run contracts 로 다시 만든다.

/**
 * 몸(시뮬레이터)에 보내는 명령. 값의 범위는 몸마다 달라 GET /scene의 limits로 알리고 시뮬레이터가 확인한다.
 */
export type SimCommand = VelocityCommand | StopCommand | PushCommand | ResetCommand
/**
 * 보낸 쪽이 정하는 번호. 시뮬레이터가 받았는지(ack)·거절했는지(rejected)를 이 번호로 알린다.
 */
export type CommandId = string

/**
 * 걷기 속도. 몸의 운동 제어(System 0)가 균형을 잡으며 이 속도로 걷는다. 다음 명령까지 유지한다.
 */
export interface VelocityCommand {
  type: 'velocity'
  id?: CommandId
  /**
   * 앞(+)/뒤(-) 속도 m/s
   */
  forward: number
  /**
   * 왼쪽(+)/오른쪽(-) 속도 m/s
   */
  sideways: number
  /**
   * 왼쪽으로 도는(+) 각속도 rad/s
   */
  turn: number
}
/**
 * 제자리에 선다 (속도 0).
 */
export interface StopCommand {
  type: 'stop'
  id?: CommandId
}
/**
 * 시험용: 몸통(골반)을 잠깐 민다. 넘어지지 않고 버티는지 볼 때 쓴다.
 */
export interface PushCommand {
  type: 'push'
  id?: CommandId
  /**
   * 세계 좌표의 힘 [x, y, z] N (x 앞, y 왼쪽, z 위)
   *
   * @minItems 3
   * @maxItems 3
   */
  force: [number, number, number]
  /**
   * 미는 시간 ms
   */
  durationMs: number
}
/**
 * 처음 자세로 되돌린다.
 */
export interface ResetCommand {
  type: 'reset'
  id?: CommandId
}
