import type { Evasion, SkillName, TrialSetup } from './generated/control'
import type { PlanStep } from './generated/plan'

/** 두뇌의 판단 기록과 화면이 같은 말을 쓰게 한곳에 둔다 */

export const SKILL_LABELS: Record<SkillName, string> = {
  idle: '대기',
  hold: '자리 지키기',
  engage: '교전',
  retreat: '물러나기',
}

export const EVASION_LABELS: Record<Evasion, string> = {
  dodge: '피하기',
  guard: '방패로 막기',
  both: '피하며 막기',
  none: '반응 안 함',
}

const PERCENT = 100

export function percent(ratio: number): number {
  return Math.round(ratio * PERCENT)
}

/** 시험에서 비교할 것: "교전 · 피하기" 또는 말로 한 명령 "“드론 2부터 잡아”" */
export function trialSetupLabel(setup: TrialSetup): string {
  return setup.kind === 'skill' ? `${SKILL_LABELS[setup.skill]} · ${EVASION_LABELS[setup.evasion]}` : `“${setup.text}”`
}

/** 계획의 한 단계를 한 줄로: "교전 (표적 드론 2) · 표적 드론 2을(를) 격파할 때까지" */
export function describeStep(step: PlanStep, nameOf: (id: string) => string): string {
  const target = step.target ? ` (${nameOf(step.target)})` : ''
  return `${SKILL_LABELS[step.skill]}${target} · ${describeUntil(step, nameOf)}`
}

export function describeUntil(step: PlanStep, nameOf: (id: string) => string): string {
  switch (step.until) {
    case 'targetDestroyed':
      return `${step.target ? nameOf(step.target) : '표적'}을(를) 격파할 때까지`
    case 'allDestroyed':
      return '모든 드론을 격파할 때까지'
    case 'seconds':
      return `${step.value}초 동안`
    case 'hpBelow':
      return `체력이 ${percent(step.value)}% 아래가 될 때까지`
    case 'never':
      return '다음 명령까지 계속'
  }
}
