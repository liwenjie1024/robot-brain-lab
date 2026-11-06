import { describe, expect, it } from 'vitest'
import { trialSeries } from '@shared/test/fixtures'
import { bestOf, longestMinutes, toTrialSetups, TRIAL_COLUMNS } from './trials'

describe('bestOf', () => {
  it('높을수록 좋으면 가장 큰 값, 낮을수록 좋으면 가장 작은 값의 번호를 고른다', () => {
    expect(bestOf([80, 90, 70], 'high')).toEqual(new Set([1]))
    expect(bestOf([80, 90, 70], 'low')).toEqual(new Set([2]))
  })

  it('같은 값이면 모두 고르고, 값이 없는(null) 것은 견주지 않는다', () => {
    expect(bestOf([30, null, 30], 'low')).toEqual(new Set([0, 2]))
  })

  it('경계값: 값이 하나뿐이면 견줄 것이 없어 고르지 않는다', () => {
    expect(bestOf([30, null], 'low')).toEqual(new Set())
    expect(bestOf([], 'high')).toEqual(new Set())
  })
})

describe('toTrialSetups', () => {
  const SETUP = { kind: 'skill', skill: 'engage', evasion: 'dodge' } as const

  it('경계값: 1~6가지만 시험 지시에 넣고, 없거나 7가지면 null', () => {
    expect(toTrialSetups([SETUP])).toEqual([SETUP])
    expect(toTrialSetups(Array.from({ length: 6 }, () => SETUP))).toHaveLength(6)
    expect(toTrialSetups([])).toBeNull()
    expect(toTrialSetups(Array.from({ length: 7 }, () => SETUP))).toBeNull()
  })
})

describe('longestMinutes', () => {
  it('모든 판이 제한 시간까지 가고 판마다 되돌리는 시간을 더한 분을 올림으로 낸다', () => {
    expect(longestMinutes(4, 3, 60)).toBe(13)
    expect(longestMinutes(1, 1, 10)).toBe(1)
  })
})

describe('TRIAL_COLUMNS', () => {
  it('요약을 사람이 읽는 글로 쓴다 (다 격파하지 못한 판만 있으면 격파 시간은 없음)', () => {
    const summary = trialSeries().setups[1]!.summary!
    const cells = Object.fromEntries(TRIAL_COLUMNS.map((column) => [column.key, column.format(summary)]))

    expect(cells).toEqual({
      score: '70.4 (53.3~87.4)',
      cleared: '1 / 2판',
      clearTime: '20.6초 (모두 20.6초)',
      damage: '180 (160~200)',
      accuracy: '91%',
      reaction: '18ms',
      plan: '-',
    })
    expect(TRIAL_COLUMNS.find((column) => column.key === 'clearTime')?.format({ ...summary, clearTimeS: null })).toBe('없음')
  })
})
