// contracts/sim/command.schema.json에서 만든 파일이다. 직접 고치지 말고 npm run contracts 로 다시 만든다.

/**
 * 몸(시뮬레이터)에 보내는 명령. 값의 범위는 몸마다 달라 GET /scene의 limits로 알리고 시뮬레이터가 확인한다.
 */
export type SimCommand =
  | VelocityCommand
  | StopCommand
  | AimCommand
  | AimPointCommand
  | LowerAimCommand
  | GuardCommand
  | FireCommand
  | PushCommand
  | ResetCommand
/**
 * 보낸 쪽이 정하는 번호. 시뮬레이터가 받았는지(ack)·거절했는지(rejected)를 이 번호로 알린다.
 */
export type CommandId = string
/**
 * @minItems 3
 * @maxItems 3
 */
export type Vector3 = [number, number, number]
/**
 * 시험 장면. empty: 빈 시험장, targets: 멈춘 표적, moving: 움직이는 표적, skirmish: 반격하는 드론
 */
export type ScenarioName = 'empty' | 'targets' | 'moving' | 'skirmish'

/**
 * 비행 속도 (기수 방향 기준). 비행 제어(System 0)가 기체를 똑바로 세운 채 이 속도로 난다. 다음 명령까지 유지한다. forward: 앞(+)/뒤(-) m/s, sideways: 왼쪽(+)/오른쪽(-) m/s, up: 위(+)/아래(-) m/s, turn: 왼쪽으로 도는(+) rad/s
 */
export interface VelocityCommand {
  type: 'velocity'
  id?: CommandId
  forward: number
  sideways: number
  up: number
  turn: number
}
/**
 * 그 자리에 멈춘다 (공중이면 떠 있고, 땅에 닿아 느려지면 추진기를 끄고 선다).
 */
export interface StopCommand {
  type: 'stop'
  id?: CommandId
}
/**
 * 유닛(표적)을 소총으로 겨누고 계속 따라간다. 팔이 실제로 돌아가는 데 시간이 걸린다 (상태의 aimError).
 */
export interface AimCommand {
  type: 'aim'
  id?: CommandId
  unit: string
}
/**
 * 세계 좌표의 한 점을 겨눈다 [x, y, z] m.
 */
export interface AimPointCommand {
  type: 'aimPoint'
  id?: CommandId
  point: Vector3
}
/**
 * 겨누기를 그만두고 소총을 내린다.
 */
export interface LowerAimCommand {
  type: 'lowerAim'
  id?: CommandId
}
/**
 * 방패를 올리거나(raised: true) 내린다. unit을 주면 그 유닛 쪽에서 몸통으로 오는 사격 길에, 없으면 기수 방향 앞에 든다. 방패에 맞은 사격은 피해가 없다.
 */
export interface GuardCommand {
  type: 'guard'
  id?: CommandId
  raised: boolean
  unit?: string
}
/**
 * 빔 소총을 한 번 쏜다. 총열이 실제로 가리키는 방향으로 나간다. 식는 중이거나 에너지가 모자라면 거절한다.
 */
export interface FireCommand {
  type: 'fire'
  id?: CommandId
}
/**
 * 시험용: 몸통을 잠깐 민다 (맞았을 때의 충격을 흉내 낸다). force: 세계 좌표의 힘 [x, y, z] N, durationMs: 미는 시간 ms
 */
export interface PushCommand {
  type: 'push'
  id?: CommandId
  force: Vector3
  durationMs: number
}
/**
 * 처음으로 되돌린다. scenario를 주면 그 시험 장면으로, 없으면 지금 장면으로.
 */
export interface ResetCommand {
  type: 'reset'
  id?: CommandId
  scenario?: ScenarioName
}
