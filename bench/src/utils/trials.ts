import type { StartTrials, TrialSetup } from '@shared/brain/generated/control'
import type { SetupSummary, Stat } from '@shared/brain/generated/status'

/** 한 시험에서 견줄 수 있는 것의 수 (contracts/brain/control.schema.json의 StartTrials.setups) */
export const MAX_TRIAL_SETUPS = 6

/** 판마다 장면을 되돌리고 두뇌가 맡기까지 드는 시간 (재 보니 1초 안팎, 넉넉히) */
const RESET_OVERHEAD_S = 3
const SECONDS_PER_MINUTE = 60
const PERCENT = 100

/** 길어야 걸리는 분 (모든 판이 제한 시간까지 가면) */
export function longestMinutes(setups: number, runs: number, timeLimitS: number): number {
  return Math.ceil((setups * runs * (timeLimitS + RESET_OVERHEAD_S)) / SECONDS_PER_MINUTE)
}

/** 견줄 것이 1~6가지일 때만 시험 지시에 넣을 수 있는 모양으로 준다 (아니면 null) */
export function toTrialSetups(setups: readonly TrialSetup[]): StartTrials['setups'] | null {
  return setups.length >= 1 && setups.length <= MAX_TRIAL_SETUPS ? (setups as StartTrials['setups']) : null
}

export type Better = 'high' | 'low'

/** 견준 것 가운데 가장 좋은 것들의 번호 (같으면 모두). 값이 둘 이상 있을 때만 고른다 (하나뿐이면 견줄 것이 없다). */
export function bestOf(values: readonly (number | null)[], better: Better): Set<number> {
  const present = values.filter((value): value is number => value !== null)
  if (present.length < 2) {
    return new Set()
  }
  const best = better === 'high' ? Math.max(...present) : Math.min(...present)
  return new Set(values.flatMap((value, index) => (value === best ? [index] : [])))
}

/** 시험 결과 표의 칸 하나: 무엇을 보고, 높은 것과 낮은 것 중 무엇이 좋은지, 어떻게 쓰는지 */
export interface TrialColumn {
  key: string
  title: string
  help: string
  better: Better
  value: (summary: SetupSummary) => number | null
  format: (summary: SetupSummary) => string
}

export const TRIAL_COLUMNS: TrialColumn[] = [
  {
    key: 'score',
    title: '점수',
    help: '판마다 점수(100점)의 가운데 값. 괄호는 가장 낮은~높은 판.',
    better: 'high',
    value: (summary) => summary.score.median,
    format: (summary) => `${summary.score.median} (${range(summary.score)})`,
  },
  {
    key: 'cleared',
    title: '다 격파',
    help: '드론을 모두 격파한 판 수 ÷ 돌린 판 수',
    better: 'high',
    value: (summary) => summary.cleared / summary.runs,
    format: (summary) => `${summary.cleared} / ${summary.runs}판`,
  },
  {
    key: 'clearTime',
    title: '격파 시간',
    help: '다 격파한 판만, 판을 시작한 때부터 마지막 드론을 격파한 때까지 (가운데 값, 괄호는 가장 빠른~느린 판)',
    better: 'low',
    value: (summary) => summary.clearTimeS?.median ?? null,
    format: (summary) => (summary.clearTimeS ? `${summary.clearTimeS.median}초 (${range(summary.clearTimeS, '초')})` : '없음'),
  },
  {
    key: 'damage',
    title: '받은 피해',
    help: '한 판에 준 체력의 가운데 값 (최대 체력 1000)',
    better: 'low',
    value: (summary) => summary.damageTaken.median,
    format: (summary) => `${summary.damageTaken.median} (${range(summary.damageTaken)})`,
  },
  {
    key: 'accuracy',
    title: '명중률',
    help: '모든 판에서 맞힌 수 ÷ 쏜 수',
    better: 'high',
    value: (summary) => summary.accuracy,
    format: (summary) => (summary.accuracy === null ? '쏘지 않음' : `${Math.round(summary.accuracy * PERCENT)}%`),
  },
  {
    key: 'reaction',
    title: '반응 시간',
    help: '조준 경고를 본 뒤 반사 명령을 몸이 받기까지 (판마다 평균의 가운데 값)',
    better: 'low',
    value: (summary) => summary.reactionMs?.median ?? null,
    format: (summary) => (summary.reactionMs ? `${summary.reactionMs.median}ms` : '없음'),
  },
  {
    key: 'plan',
    title: '계획 첫 단계',
    help: '말로 한 명령을 받은 뒤 첫 단계를 시작하기까지 (말로 한 명령만)',
    better: 'low',
    value: (summary) => summary.planFirstStepMs?.median ?? null,
    format: (summary) => (summary.planFirstStepMs ? `${(summary.planFirstStepMs.median / 1000).toFixed(1)}초` : '-'),
  },
]

function range(stat: Stat, unit = ''): string {
  return stat.min === stat.max ? `모두 ${stat.min}${unit}` : `${stat.min}~${stat.max}${unit}`
}
