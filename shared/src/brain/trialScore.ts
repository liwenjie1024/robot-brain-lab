/**
 * 시험 한 판의 점수 (0~100). 두뇌가 셈하고, 화면은 같은 값으로 셈법을 설명한다.
 * - 격파: 격파한 드론 비율 × 50
 * - 빠르기: 다 격파했을 때만, 남은 제한 시간 비율 × 25 (같은 제한 시간끼리만 견줄 수 있다)
 * - 버티기: 남은 체력 비율(받은 피해 ÷ 최대 체력을 뺀 것) × 25
 * 격파가 가장 크고, 빠르기와 버티기는 서로 맞바꿀 수 있게 같은 무게로 둔다 (피하기는 늦지만 덜 맞는다).
 */
export const SCORE_POINTS = { kills: 50, speed: 25, survival: 25 } as const

const DECIMALS = 10

export interface RunFacts {
  drones: number
  kills: number
  /** 다 격파한 때 (못 했으면 null) */
  clearTimeS: number | null
  timeLimitS: number
  damageTaken: number
  maxHp: number
}

export function scoreRun(facts: RunFacts): number {
  const killed = facts.drones > 0 ? facts.kills / facts.drones : 0
  const speed = facts.clearTimeS === null ? 0 : clamp01(1 - facts.clearTimeS / facts.timeLimitS)
  const survived = facts.maxHp > 0 ? clamp01(1 - facts.damageTaken / facts.maxHp) : 0
  const score = SCORE_POINTS.kills * killed + SCORE_POINTS.speed * speed + SCORE_POINTS.survival * survived
  return Math.round(score * DECIMALS) / DECIMALS
}

function clamp01(value: number): number {
  return Math.min(1, Math.max(0, value))
}
