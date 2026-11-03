import { describe, expect, it } from 'vitest'
import { LIMITS } from '@shared/test/fixtures'
import { DEFAULT_SPEEDS, keyboardAction, pushForce, velocityFor } from './drive'

function keyEvent(code: string, extra: Partial<KeyboardEvent> = {}, target: EventTarget | null = document.body) {
  return { code, repeat: false, defaultPrevented: false, ctrlKey: false, altKey: false, metaKey: false, target, ...extra }
}

describe('velocityFor', () => {
  it.each([
    ['forward', { forward: 20, sideways: 0, up: 0, turn: 0 }],
    ['backward', { forward: -15, sideways: 0, up: 0, turn: 0 }],
    ['turnLeft', { forward: 0, sideways: 0, up: 0, turn: 0.6 }],
    ['turnRight', { forward: 0, sideways: 0, up: 0, turn: -0.6 }],
    ['strafeLeft', { forward: 0, sideways: 10, up: 0, turn: 0 }],
    ['strafeRight', { forward: 0, sideways: -10, up: 0, turn: 0 }],
    ['climb', { forward: 0, sideways: 0, up: 6, turn: 0 }],
    ['descend', { forward: 0, sideways: 0, up: -6, turn: 0 }],
    ['stop', { forward: 0, sideways: 0, up: 0, turn: 0 }],
  ] as const)('%s 버튼은 그 방향 속도만 준다', (action, expected) => {
    expect(velocityFor(action, DEFAULT_SPEEDS, LIMITS)).toEqual(expected)
  })

  it('경계값: 빠르기가 몸이 알린 범위를 넘으면 범위 끝으로 맞춘다 (뒤로는 -15까지)', () => {
    const speeds = { forward: 30, side: 10, climb: 6, turn: 0.6 }

    expect(velocityFor('forward', speeds, LIMITS).forward).toBe(30)
    expect(velocityFor('backward', speeds, LIMITS).forward).toBe(-15)
  })
})

describe('pushForce', () => {
  it('앞을 볼 때 앞에서 밀면 뒤(-x)로, 왼쪽에서 밀면 오른쪽(-y)으로 민다', () => {
    expect(pushForce('front', 0, 1_000_000)).toEqual([-1_000_000, 0, 0])
    expect(pushForce('left', 0, 1_000_000)).toEqual([0, -1_000_000, 0])
  })

  it('기수가 왼쪽(90도)이면 뒤에서 미는 힘은 +y다', () => {
    const [x, y] = pushForce('back', Math.PI / 2, 2_000_000)

    expect(x).toBeCloseTo(0)
    expect(y).toBeCloseTo(2_000_000)
  })

  it('경계값: 비스듬한 방향에서도 합친 크기가 고른 힘을 넘지 않는다 (몸이 범위 밖이라 거절하지 않게)', () => {
    for (let degrees = 0; degrees < 360; degrees += 7) {
      const [x, y] = pushForce('back', (degrees * Math.PI) / 180, 3_000_000)
      expect(Math.hypot(x, y)).toBeLessThanOrEqual(3_000_000)
      expect(Math.hypot(x, y)).toBeGreaterThan(2_999_990)
    }
  })
})

describe('keyboardAction', () => {
  it('WASD·QE·RF·스페이스는 비행 동작, X는 사격이다', () => {
    expect(keyboardAction(keyEvent('KeyW'))).toBe('forward')
    expect(keyboardAction(keyEvent('ArrowRight'))).toBe('turnRight')
    expect(keyboardAction(keyEvent('KeyQ'))).toBe('strafeLeft')
    expect(keyboardAction(keyEvent('KeyR'))).toBe('climb')
    expect(keyboardAction(keyEvent('KeyF'))).toBe('descend')
    expect(keyboardAction(keyEvent('Space'))).toBe('stop')
    expect(keyboardAction(keyEvent('KeyX'))).toBe('fire')
    expect(keyboardAction(keyEvent('KeyZ'))).toBeNull()
  })

  it('막대(슬라이더)에 초점이 있으면 화살표는 막대 값을 바꾸고 기체를 움직이지 않는다', () => {
    const slider = document.createElement('div')
    slider.setAttribute('role', 'slider')
    const inner = document.createElement('span')
    slider.append(inner)

    expect(keyboardAction(keyEvent('ArrowRight', {}, slider))).toBeNull()
    expect(keyboardAction(keyEvent('ArrowLeft', {}, inner))).toBeNull()
  })

  it.each([
    ['누르고 있어 반복', { repeat: true }],
    ['이미 처리됨', { defaultPrevented: true }],
    ['Ctrl과 함께', { ctrlKey: true }],
    ['Alt와 함께', { altKey: true }],
  ])('%s인 키는 쓰지 않는다', (_, extra) => {
    expect(keyboardAction(keyEvent('KeyX', extra))).toBeNull()
  })

  it('입력칸에서 친 글자는 쓰지 않는다', () => {
    expect(keyboardAction(keyEvent('KeyW', {}, document.createElement('input')))).toBeNull()
  })
})
