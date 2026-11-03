import { describe, expect, it } from 'vitest'
import type { Limits } from '@/sim/generated/scene'
import { DEFAULT_SPEEDS, keyboardAction, pushForce, velocityFor } from './drive'

const LIMITS: Limits = {
  forward: { min: -0.5, max: 1.0 },
  sideways: { min: -0.5, max: 0.5 },
  turn: { min: -1.0, max: 1.0 },
  pushForce: { min: 0, max: 400 },
  pushDurationMs: { min: 10, max: 1000 },
}

function keyEvent(code: string, extra: Partial<KeyboardEvent> = {}, target: EventTarget | null = document.body) {
  return { code, repeat: false, defaultPrevented: false, ctrlKey: false, altKey: false, metaKey: false, target, ...extra }
}

describe('velocityFor', () => {
  it.each([
    ['forward', { forward: 0.5, sideways: 0, turn: 0 }],
    ['backward', { forward: -0.5, sideways: 0, turn: 0 }],
    ['turnLeft', { forward: 0, sideways: 0, turn: 0.6 }],
    ['turnRight', { forward: 0, sideways: 0, turn: -0.6 }],
    ['stepLeft', { forward: 0, sideways: 0.3, turn: 0 }],
    ['stepRight', { forward: 0, sideways: -0.3, turn: 0 }],
    ['stop', { forward: 0, sideways: 0, turn: 0 }],
  ] as const)('%s 버튼은 그 방향 속도만 준다', (action, expected) => {
    expect(velocityFor(action, DEFAULT_SPEEDS, LIMITS)).toEqual(expected)
  })

  it('경계값: 빠르기가 몸이 알린 범위를 넘으면 범위 끝으로 맞춘다 (뒤로는 -0.5까지)', () => {
    const speeds = { walk: 0.9, side: 0.3, turn: 0.6 }

    expect(velocityFor('forward', speeds, LIMITS).forward).toBe(0.9)
    expect(velocityFor('backward', speeds, LIMITS).forward).toBe(-0.5)
  })
})

describe('pushForce', () => {
  it('앞을 볼 때 앞에서 밀면 뒤(-x)로, 왼쪽에서 밀면 오른쪽(-y)으로 민다', () => {
    expect(pushForce('front', 0, 150)).toEqual([-150, 0, 0])
    expect(pushForce('left', 0, 150)).toEqual([0, -150, 0])
  })

  it('로봇이 왼쪽(90도)을 보면 뒤에서 미는 힘은 +y다', () => {
    const [x, y] = pushForce('back', Math.PI / 2, 200)

    expect(x).toBeCloseTo(0)
    expect(y).toBeCloseTo(200)
  })

  it('경계값: 비스듬한 방향에서도 합친 크기가 고른 힘을 넘지 않는다 (몸이 범위 밖이라 거절하지 않게)', () => {
    for (let degrees = 0; degrees < 360; degrees += 7) {
      const [x, y] = pushForce('back', (degrees * Math.PI) / 180, 400)
      expect(Math.hypot(x, y)).toBeLessThanOrEqual(400)
      expect(Math.hypot(x, y)).toBeGreaterThan(399.8)
    }
  })
})

describe('keyboardAction', () => {
  it('WASD·화살표·QE·스페이스를 걷기 동작으로 바꾼다', () => {
    expect(keyboardAction(keyEvent('KeyW'))).toBe('forward')
    expect(keyboardAction(keyEvent('ArrowRight'))).toBe('turnRight')
    expect(keyboardAction(keyEvent('KeyQ'))).toBe('stepLeft')
    expect(keyboardAction(keyEvent('Space'))).toBe('stop')
    expect(keyboardAction(keyEvent('KeyZ'))).toBeNull()
  })

  it('막대(슬라이더)에 초점이 있으면 화살표는 막대 값을 바꾸고 로봇을 움직이지 않는다', () => {
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
    expect(keyboardAction(keyEvent('KeyW', extra))).toBeNull()
  })

  it('입력칸에서 친 글자는 쓰지 않는다', () => {
    expect(keyboardAction(keyEvent('KeyW', {}, document.createElement('input')))).toBeNull()
  })
})
