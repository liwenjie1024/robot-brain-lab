import type { Limits, Range } from '@/sim/generated/scene'

/** 사람이 버튼·키보드로 몸을 움직이는 방법. 두뇌가 없을 때 몸만 시험하는 데 쓴다. */

export type DriveAction = 'forward' | 'backward' | 'turnLeft' | 'turnRight' | 'stepLeft' | 'stepRight' | 'stop'
export type PushFrom = 'front' | 'back' | 'left' | 'right'

export interface DriveSpeeds {
  /** 앞뒤로 걷는 빠르기 m/s */
  walk: number
  /** 옆걸음 빠르기 m/s */
  side: number
  /** 도는 빠르기 rad/s */
  turn: number
}

export interface Velocity {
  forward: number
  sideways: number
  turn: number
}

export const DEFAULT_SPEEDS: DriveSpeeds = { walk: 0.5, side: 0.3, turn: 0.6 }

export const DRIVE_LABELS: Record<DriveAction, string> = {
  forward: '앞으로',
  backward: '뒤로',
  turnLeft: '왼쪽으로 돌기',
  turnRight: '오른쪽으로 돌기',
  stepLeft: '왼쪽 옆걸음',
  stepRight: '오른쪽 옆걸음',
  stop: '멈춤',
}

export const PUSH_LABELS: Record<PushFrom, string> = {
  front: '앞에서 밀기',
  back: '뒤에서 밀기',
  left: '왼쪽에서 밀기',
  right: '오른쪽에서 밀기',
}

/** 키보드 (KeyboardEvent.code) */
export const KEY_ACTIONS: Readonly<Record<string, DriveAction>> = {
  KeyW: 'forward',
  ArrowUp: 'forward',
  KeyS: 'backward',
  ArrowDown: 'backward',
  KeyA: 'turnLeft',
  ArrowLeft: 'turnLeft',
  KeyD: 'turnRight',
  ArrowRight: 'turnRight',
  KeyQ: 'stepLeft',
  KeyE: 'stepRight',
  Space: 'stop',
}

/** 키를 스스로 쓰는 조작 요소 (밀기 힘 막대는 화살표로 값을 바꾼다) */
const KEY_CONSUMING_CONTROLS = 'input, textarea, select, [contenteditable="true"], [role="slider"]'

/**
 * 이 키 입력으로 몸을 움직일지. 다른 조작 요소가 쓰는 키, 이미 처리된 키, 누르고 있어 반복되는 키,
 * Ctrl·Alt 등과 함께 누른 키(브라우저 단축키)는 쓰지 않는다.
 */
export function keyboardAction(
  event: Pick<KeyboardEvent, 'code' | 'repeat' | 'defaultPrevented' | 'ctrlKey' | 'altKey' | 'metaKey' | 'target'>,
): DriveAction | null {
  if (event.repeat || event.defaultPrevented || event.ctrlKey || event.altKey || event.metaKey) {
    return null
  }
  const target = event.target
  if (target instanceof Element && target.closest(KEY_CONSUMING_CONTROLS)) {
    return null
  }
  return KEY_ACTIONS[event.code] ?? null
}

/** 한 번 미는 시간. 짧게 툭 쳐서 버티는 힘을 본다. */
export const PUSH_DURATION_MS = 100

export function clampTo(range: Range, value: number): number {
  return Math.min(range.max, Math.max(range.min, value))
}

/** 버튼 하나의 걷기 명령. 몸이 알린 범위 안으로 맞춘다 (범위 밖 명령은 몸이 거절한다). */
export function velocityFor(action: DriveAction, speeds: DriveSpeeds, limits: Limits): Velocity {
  const velocity: Velocity = { forward: 0, sideways: 0, turn: 0 }
  switch (action) {
    case 'forward':
      velocity.forward = speeds.walk
      break
    case 'backward':
      velocity.forward = -speeds.walk
      break
    case 'turnLeft':
      velocity.turn = speeds.turn
      break
    case 'turnRight':
      velocity.turn = -speeds.turn
      break
    case 'stepLeft':
      velocity.sideways = speeds.side
      break
    case 'stepRight':
      velocity.sideways = -speeds.side
      break
    case 'stop':
      break
  }
  return {
    forward: clampTo(limits.forward, velocity.forward),
    sideways: clampTo(limits.sideways, velocity.sideways),
    turn: clampTo(limits.turn, velocity.turn),
  }
}

/**
 * 로봇 기준 방향에서 미는 힘을 세계 좌표로 바꾼다. "앞에서 밀기"는 로봇을 뒤로 민다.
 * @param yaw 로봇이 바라보는 방향 rad
 */
export function pushForce(from: PushFrom, yaw: number, magnitude: number): [number, number, number] {
  const ahead = { x: Math.cos(yaw), y: Math.sin(yaw) }
  const left = { x: -Math.sin(yaw), y: Math.cos(yaw) }
  const toward = {
    front: { x: -ahead.x, y: -ahead.y },
    back: ahead,
    left: { x: -left.x, y: -left.y },
    right: left,
  }[from]
  return [towardZero(toward.x * magnitude), towardZero(toward.y * magnitude), 0]
}

/**
 * 0.1N 단위로 자른다. 반올림하면 두 성분을 합친 크기가 고른 힘보다 조금 커져 몸이 범위 밖이라고 거절한다
 * (400N을 고르면 400.02N이 된다).
 */
function towardZero(value: number): number {
  // 작은 음수를 자르면 -0이 되어 기록·비교에 섞이므로 0으로 둔다.
  return Math.trunc(value * 10) / 10 || 0
}
