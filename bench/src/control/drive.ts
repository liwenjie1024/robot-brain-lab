import type { Limits, Range } from '@shared/sim/generated/scene'

/** 사람이 버튼·키보드로 기체를 날리는 방법. 두뇌 없이 몸과 비행 제어만 시험하거나, 두뇌를 거들 때 쓴다. */

export type FlightAction =
  | 'forward'
  | 'backward'
  | 'turnLeft'
  | 'turnRight'
  | 'strafeLeft'
  | 'strafeRight'
  | 'climb'
  | 'descend'
  | 'stop'
export type PushFrom = 'front' | 'back' | 'left' | 'right'

export interface FlightSpeeds {
  /** 앞뒤로 나는 빠르기 m/s */
  forward: number
  /** 옆으로 나는 빠르기 m/s */
  side: number
  /** 오르내리는 빠르기 m/s */
  climb: number
  /** 도는 빠르기 rad/s */
  turn: number
}

export interface FlightVelocity {
  forward: number
  sideways: number
  up: number
  turn: number
}

export const DEFAULT_SPEEDS: FlightSpeeds = { forward: 20, side: 10, climb: 6, turn: 0.6 }

export const FLIGHT_LABELS: Record<FlightAction, string> = {
  forward: '앞으로',
  backward: '뒤로',
  turnLeft: '왼쪽으로 돌기',
  turnRight: '오른쪽으로 돌기',
  strafeLeft: '왼쪽 옆으로',
  strafeRight: '오른쪽 옆으로',
  climb: '위로',
  descend: '아래로',
  stop: '멈춤',
}

export const PUSH_LABELS: Record<PushFrom, string> = {
  front: '앞에서 밀기',
  back: '뒤에서 밀기',
  left: '왼쪽에서 밀기',
  right: '오른쪽에서 밀기',
}

/** 키보드 (KeyboardEvent.code). 사격은 X (F는 아래로) */
export const KEY_ACTIONS: Readonly<Record<string, FlightAction>> = {
  KeyW: 'forward',
  ArrowUp: 'forward',
  KeyS: 'backward',
  ArrowDown: 'backward',
  KeyA: 'turnLeft',
  ArrowLeft: 'turnLeft',
  KeyD: 'turnRight',
  ArrowRight: 'turnRight',
  KeyQ: 'strafeLeft',
  KeyE: 'strafeRight',
  KeyR: 'climb',
  KeyF: 'descend',
  Space: 'stop',
}
export const FIRE_KEY = 'KeyX'

/** 한 번 미는 시간. 맞았을 때처럼 짧게 친다. */
export const PUSH_DURATION_MS = 200
export const NEWTONS_PER_KILONEWTON = 1000

/** 키를 스스로 쓰는 조작 요소 (밀기 힘 막대는 화살표로 값을 바꾼다) */
const KEY_CONSUMING_CONTROLS = 'input, textarea, select, [contenteditable="true"], [role="slider"]'

export function clampTo(range: Range, value: number): number {
  return Math.min(range.max, Math.max(range.min, value))
}

/** 버튼 하나의 비행 명령. 몸이 알린 범위 안으로 맞춘다 (범위 밖 명령은 몸이 거절한다). */
export function velocityFor(action: FlightAction, speeds: FlightSpeeds, limits: Limits): FlightVelocity {
  const velocity: FlightVelocity = { forward: 0, sideways: 0, up: 0, turn: 0 }
  switch (action) {
    case 'forward':
      velocity.forward = speeds.forward
      break
    case 'backward':
      velocity.forward = -speeds.forward
      break
    case 'turnLeft':
      velocity.turn = speeds.turn
      break
    case 'turnRight':
      velocity.turn = -speeds.turn
      break
    case 'strafeLeft':
      velocity.sideways = speeds.side
      break
    case 'strafeRight':
      velocity.sideways = -speeds.side
      break
    case 'climb':
      velocity.up = speeds.climb
      break
    case 'descend':
      velocity.up = -speeds.climb
      break
    case 'stop':
      break
  }
  return {
    forward: clampTo(limits.forward, velocity.forward),
    sideways: clampTo(limits.sideways, velocity.sideways),
    up: clampTo(limits.up, velocity.up),
    turn: clampTo(limits.turn, velocity.turn),
  }
}

/**
 * 키 입력이 무엇을 할지. 다른 조작 요소가 쓰는 키, 이미 처리된 키, 누르고 있어 반복되는 키,
 * Ctrl·Alt 등과 함께 누른 키(브라우저 단축키)는 쓰지 않는다.
 */
export function keyboardAction(
  event: Pick<KeyboardEvent, 'code' | 'repeat' | 'defaultPrevented' | 'ctrlKey' | 'altKey' | 'metaKey' | 'target'>,
): FlightAction | 'fire' | null {
  if (event.repeat || event.defaultPrevented || event.ctrlKey || event.altKey || event.metaKey) {
    return null
  }
  const target = event.target
  if (target instanceof Element && target.closest(KEY_CONSUMING_CONTROLS)) {
    return null
  }
  if (event.code === FIRE_KEY) {
    return 'fire'
  }
  return KEY_ACTIONS[event.code] ?? null
}

/**
 * 기체 기준 방향에서 미는 힘을 세계 좌표로 바꾼다. "앞에서 밀기"는 기체를 뒤로 민다.
 * @param heading 기수 방향 rad
 * @param newtons 힘의 크기 N
 */
export function pushForce(from: PushFrom, heading: number, newtons: number): [number, number, number] {
  const ahead = { x: Math.cos(heading), y: Math.sin(heading) }
  const left = { x: -Math.sin(heading), y: Math.cos(heading) }
  const toward = {
    front: { x: -ahead.x, y: -ahead.y },
    back: ahead,
    left: { x: -left.x, y: -left.y },
    right: left,
  }[from]
  return [towardZero(toward.x * newtons), towardZero(toward.y * newtons), 0]
}

/**
 * 1N 단위로 자른다. 반올림하면 두 성분을 합친 크기가 고른 힘보다 조금 커져 몸이 범위 밖이라고 거절한다.
 */
function towardZero(value: number): number {
  // 작은 음수를 자르면 -0이 되어 기록·비교에 섞이므로 0으로 둔다.
  return Math.trunc(value) || 0
}
