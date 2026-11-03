import { describe, expect, it } from 'vitest'
import { drone, mechaStatus, perceptionOf } from './testing'

describe('perceive', () => {
  it('살아 있는 드론만 가까운 순으로, 거리와 기수에서 돌아간 각을 붙여 본다', () => {
    const perception = perceptionOf({
      mecha: mechaStatus({ position: [0, 0, 30], heading: 0 }),
      units: [
        drone({ id: 'far', position: [300, 0, 30] }),
        drone({ id: 'left', position: [0, 100, 30] }),
        drone({ id: 'dead', position: [10, 0, 30], alive: false }),
      ],
    })

    expect(perception.targets.map((target) => target.id)).toEqual(['left', 'far'])
    expect(perception.targets[0]?.distance).toBeCloseTo(100)
    expect(perception.targets[0]?.bearing).toBeCloseTo(Math.PI / 2)
    expect(perception.targets[1]?.bearing).toBeCloseTo(0)
  })

  it('기수가 돌아가 있으면 각도 기수 기준이다 (북쪽을 볼 때 동쪽 드론은 오른쪽 -90°)', () => {
    const perception = perceptionOf({
      mecha: mechaStatus({ position: [0, 0, 30], heading: Math.PI / 2 }),
      units: [drone({ position: [100, 0, 30] })],
    })

    expect(perception.targets[0]?.bearing).toBeCloseTo(-Math.PI / 2)
  })

  it('위협은 쏘기까지 짧은 순이고, 쏘려는 드론이 있는 쪽을 붙인다 (모르는 유닛이면 null)', () => {
    const perception = perceptionOf({
      mecha: mechaStatus({ position: [0, 0, 30], heading: 0 }),
      units: [drone({ id: 'drone-1', position: [0, -100, 30] })],
      threats: [
        { from: 'ghost', secondsToFire: 1.1 },
        { from: 'drone-1', secondsToFire: 0.4 },
      ],
    })

    expect(perception.threats.map((threat) => threat.from)).toEqual(['drone-1', 'ghost'])
    expect(perception.threats[0]?.bearing).toBeCloseTo(-Math.PI / 2)
    expect(perception.threats[1]?.bearing).toBeNull()
  })
})
