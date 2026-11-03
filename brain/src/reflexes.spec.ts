import { describe, expect, it } from 'vitest'
import { DODGE_SPEED, EvasionReflex } from './reflexes'
import { drone, mechaStatus, scene } from './testing'

const LEFT_DRONE = drone({ id: 'left', position: [0, 200, 30] })
const AHEAD_DRONE = drone({ id: 'ahead', position: [200, 0, 30] })

function withThreats(threats: { from: string; secondsToFire: number }[], simTime: number, velocity = { forward: 0, sideways: 0, up: 0, turn: 0 }) {
  return scene([LEFT_DRONE, AHEAD_DRONE], {
    simTime,
    threats,
    mecha: mechaStatus({ position: [0, 0, 30], heading: 0, velocity }),
  })
}

describe('EvasionReflex', () => {
  it('조준 경고를 처음 보면 위협 쪽과 직각으로 피한다 (왼쪽 드론이면 앞뒤로)', () => {
    const action = new EvasionReflex().update(withThreats([{ from: 'left', secondsToFire: 1.2 }], 10), 'dodge')

    expect(action?.started).toBe(true)
    expect(Math.abs(action!.velocity!.forward)).toBeCloseTo(DODGE_SPEED)
    expect(action!.velocity!.sideways).toBeCloseTo(0)
    expect(action?.guardUnit).toBeUndefined()
    expect(action?.until).toBeCloseTo(10 + 1.2 + 0.3)
  })

  it('지금 속도와 반대쪽으로 피한다 (속도가 가장 크게 바뀌어 드론이 셈한 자리에서 멀어지게)', () => {
    const movingLeft = { forward: 0, sideways: 10, up: 0, turn: 0 }

    const action = new EvasionReflex().update(withThreats([{ from: 'ahead', secondsToFire: 1.2 }], 0, movingLeft), 'dodge')

    expect(action!.velocity!.sideways).toBeCloseTo(-DODGE_SPEED)
  })

  it('중복: 같은 경고가 이어지는 동안은 다시 시작하지 않는다', () => {
    const reflex = new EvasionReflex()
    reflex.update(withThreats([{ from: 'left', secondsToFire: 1.2 }], 0), 'dodge')

    const again = reflex.update(withThreats([{ from: 'left', secondsToFire: 1.0 }], 0.2), 'dodge')

    expect(again?.started).toBe(false)
    expect(again?.threat).toBe('left')
  })

  it('순서: 피하는 중에 새 드론이 조준하면 속도를 다시 바꾼다 (같은 속도로 계속 피하면 새 드론의 셈에 맞는다)', () => {
    const reflex = new EvasionReflex()
    const first = reflex.update(withThreats([{ from: 'ahead', secondsToFire: 1.2 }], 0), 'dodge')
    const dodging = first!.velocity!

    const second = reflex.update(withThreats([{ from: 'ahead', secondsToFire: 0.2 }, { from: 'left', secondsToFire: 1.2 }], 1.0, dodging), 'dodge')

    expect(second?.started).toBe(true)
    expect(second?.threat).toBe('left')
    expect(second?.velocity).not.toEqual(dodging)
    expect(second?.until).toBeCloseTo(1.0 + 1.2 + 0.3)
  })

  it('막기: 가장 먼저 쏠 드론 쪽으로 방패를 들고, 그 드론이 쏘고 나면 다음 드론 쪽으로 옮긴다', () => {
    const reflex = new EvasionReflex()
    reflex.update(withThreats([{ from: 'ahead', secondsToFire: 1.2 }], 0), 'guard')
    const both = reflex.update(withThreats([{ from: 'ahead', secondsToFire: 0.4 }, { from: 'left', secondsToFire: 1.2 }], 0.8), 'guard')
    const after = reflex.update(withThreats([{ from: 'left', secondsToFire: 0.6 }], 1.4), 'guard')

    expect(both?.guardUnit).toBe('ahead')
    expect(both?.velocity).toBeUndefined()
    expect(after?.guardUnit).toBe('left')
  })

  it('정한 시간이 지나면 끝난다', () => {
    const reflex = new EvasionReflex()
    reflex.update(withThreats([{ from: 'left', secondsToFire: 1.2 }], 0), 'both')

    expect(reflex.update(withThreats([], 1.4), 'both')).not.toBeNull()
    expect(reflex.update(withThreats([], 1.6), 'both')).toBeNull()
  })

  it('반응 안 함이면 아무것도 하지 않는다', () => {
    expect(new EvasionReflex().update(withThreats([{ from: 'left', secondsToFire: 1.2 }], 0), 'none')).toBeNull()
  })
})
