import { describe, expect, it } from 'vitest'
import { asDuration, asKilograms, asPercent, asVector, fixed, magnitude, toDegrees } from '@/text/format'

describe('把数写成人看的字', () => {
  it('力写成相当于多少公斤', () => {
    expect(asKilograms(766.94)).toBe('78.2 kg')
    expect(asKilograms(0)).toBe('0.0 kg')
  })

  it('留几位小数；很小的负数不写成 -0.0', () => {
    expect(fixed(23.651, 1)).toBe('23.7')
    expect(fixed(-25.14, 1)).toBe('-25.1')
    expect(fixed(-0.04, 1)).toBe('0.0')
    expect(fixed(-0.0004, 2)).toBe('0.00')
    expect(fixed(0.889, 2)).toBe('0.89')
    expect(fixed(7)).toBe('7.0')
  })

  it('比例写成百分数', () => {
    expect(asPercent(0.0847)).toBe('8%')
    expect(asPercent(0.5)).toBe('50%')
    expect(asPercent(1.2)).toBe('120%')
    expect(asPercent(0)).toBe('0%')
  })

  it('弧度换成度', () => {
    expect(toDegrees(Math.PI)).toBeCloseTo(180)
    expect(toDegrees(0)).toBe(0)
  })

  it('三个方向的数写成一行，说清楚哪个是哪个', () => {
    expect(asVector([0.004, -0.2, 9.81], 2)).toBe('前 0.00　左 -0.20　上 9.81')
    expect(asVector([2, 1, 11], 0)).toBe('前 2　左 1　上 11')
    expect(asVector([])).toBe('前 0.0　左 0.0　上 0.0')
  })

  it('三个方向合起来有多大', () => {
    expect(magnitude([3, 4, 0])).toBe(5)
    expect(magnitude([])).toBe(0)
  })

  it('时间：一分钟以内写秒，过了写几分几秒', () => {
    expect(asDuration(0)).toBe('0.0 秒')
    expect(asDuration(12.34)).toBe('12.3 秒')
    expect(asDuration(59.94)).toBe('59.9 秒')
    expect(asDuration(60)).toBe('1 分 00 秒')
    expect(asDuration(125.9)).toBe('2 分 05 秒')
  })
})
