import { describe, expect, it } from 'vitest'
import { runResult } from '@shared/test/fixtures'
import { stat, summarize } from './trialStats'

describe('stat', () => {
  it('가운데 값·가장 작은 값·가장 큰 값·평균을 소수 한 자리로 낸다 (판이 홀수 개)', () => {
    expect(stat([35.2, 21.04, 51.2])).toEqual({ median: 35.2, min: 21, max: 51.2, mean: 35.8 })
  })

  it('판이 짝수 개면 가운데 두 값의 평균이 가운데 값이다', () => {
    expect(stat([40, 10, 30, 20])?.median).toBe(25)
  })

  it('경계값: 한 판이면 모든 값이 같고, 값이 없으면 null', () => {
    expect(stat([7])).toEqual({ median: 7, min: 7, max: 7, mean: 7 })
    expect(stat([])).toBeNull()
  })
})

describe('summarize', () => {
  it('다 격파한 판만 격파 시간에 넣고, 명중률은 모든 판의 맞힘 ÷ 쏨으로 낸다', () => {
    const summary = summarize([
      runResult({ clearTimeS: 20, score: 90, shots: 6, hits: 6 }),
      runResult({ run: 2, outcome: 'timeout', clearTimeS: null, kills: 2, score: 50, shots: 5, hits: 3 }),
      runResult({ run: 3, clearTimeS: 40, score: 80, shots: 7, hits: 6, reactionMs: null }),
    ])

    expect(summary).toMatchObject({ runs: 3, cleared: 2, accuracy: 0.833 })
    expect(summary.clearTimeS).toEqual({ median: 30, min: 20, max: 40, mean: 30 })
    expect(summary.score.median).toBe(80)
    expect(summary.reactionMs?.median).toBe(18)
    expect(summary.planFirstStepMs).toBeNull()
  })

  it('경계값: 한 번도 다 격파하지 못하고 쏘지도 않았으면 격파 시간·명중률은 null', () => {
    const summary = summarize([runResult({ outcome: 'destroyed', clearTimeS: null, kills: 0, shots: 0, hits: 0 })])

    expect(summary).toMatchObject({ runs: 1, cleared: 0, clearTimeS: null, accuracy: null })
  })
})
