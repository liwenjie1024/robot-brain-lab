import type { RunResult, SetupSummary, Stat } from '@shared/brain/generated/status'

const DECIMALS = 10
const ACCURACY_DECIMALS = 1000
const NO_RUNS: Stat = { median: 0, min: 0, max: 0, mean: 0 }

/** 여러 판의 값 (값이 없으면 null). 판마다 크게 흩어지므로 평균보다 가운데 값을 먼저 본다. */
export function stat(values: readonly number[]): Stat | null {
  if (values.length === 0) {
    return null
  }
  const sorted = [...values].sort((a, b) => a - b)
  const middle = Math.floor(sorted.length / 2)
  const median = sorted.length % 2 === 1 ? sorted[middle]! : (sorted[middle - 1]! + sorted[middle]!) / 2
  const mean = sorted.reduce((sum, value) => sum + value, 0) / sorted.length
  return { median: round(median), min: round(sorted[0]!), max: round(sorted.at(-1)!), mean: round(mean) }
}

export function summarize(results: readonly RunResult[]): SetupSummary {
  const shots = results.reduce((sum, result) => sum + result.shots, 0)
  const hits = results.reduce((sum, result) => sum + result.hits, 0)
  const cleared = results.filter((result) => result.clearTimeS !== null)
  return {
    runs: results.length,
    cleared: cleared.length,
    score: stat(results.map((result) => result.score)) ?? NO_RUNS,
    clearTimeS: stat(cleared.map((result) => result.clearTimeS!)),
    damageTaken: stat(results.map((result) => result.damageTaken)) ?? NO_RUNS,
    accuracy: shots > 0 ? Math.round((hits / shots) * ACCURACY_DECIMALS) / ACCURACY_DECIMALS : null,
    reactionMs: stat(present(results.map((result) => result.reactionMs))),
    planFirstStepMs: stat(present(results.map((result) => result.planFirstStepMs))),
  }
}

function present(values: (number | null)[]): number[] {
  return values.filter((value): value is number => value !== null)
}

function round(value: number): number {
  return Math.round(value * DECIMALS) / DECIMALS
}
