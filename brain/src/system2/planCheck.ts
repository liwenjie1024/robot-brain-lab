import Ajv2020, { type ErrorObject } from 'ajv/dist/2020'
import planSchema from '../../../contracts/brain/plan.schema.json'
import type { Plan, PlanStep } from '@shared/brain/generated/plan'

/**
 * 언어 모델이 낸 계획을 경계에서 확인한다: 모양은 규약 스키마로, 뜻은 아래 규칙으로.
 * 틀리면 고쳐 쓰지 않고 까닭을 돌려준다 (언어 모델에게 그 까닭을 붙여 다시 묻는다).
 */

export type Checked<T> = { ok: true; value: T } | { ok: false; problem: string }

const ajv = new Ajv2020({ allErrors: false })
const validatePlanShape = ajv.compile<Plan>(planSchema)
const validateStepShape = ajv.compile<PlanStep>({ $ref: `${planSchema.$id}#/$defs/PlanStep` })
const validateRetreatShape = ajv.compile<number>({ $ref: `${planSchema.$id}#/properties/retreatBelowHp` })

export const MAX_STEPS = planSchema.properties.steps.maxItems
const MIN_SECONDS = 1
const MAX_SECONDS = planSchema.$defs.PlanStep.properties.value.maximum
/** 맞으며 버티다 체력이 줄면 넘어가는 것이 뜻이 있는 기술 */
const HP_WAITING_SKILLS: ReadonlySet<PlanStep['skill']> = new Set(['engage', 'hold'])

/** targets: 지금 살아 있는 드론 id */
export function checkPlan(value: unknown, targets: ReadonlySet<string>): Checked<Plan> {
  if (!validatePlanShape(value)) {
    return { ok: false, problem: shapeProblem(validatePlanShape.errors) }
  }
  for (const [index, step] of value.steps.entries()) {
    const problem = meaningProblem(step, value.steps[index - 1], targets)
    if (problem) {
      return { ok: false, problem: `단계 ${index + 1}: ${problem}` }
    }
  }
  return { ok: true, value }
}

/** 흘러 들어온 단계 하나를 앞 단계와 함께 본다 (계획을 다 받기 전에 시작하려고) */
export function checkStep(value: unknown, index: number, previous: PlanStep | undefined, targets: ReadonlySet<string>): Checked<PlanStep> {
  if (index >= MAX_STEPS) {
    return { ok: false, problem: `단계는 ${MAX_STEPS}개까지입니다` }
  }
  if (!validateStepShape(value)) {
    return { ok: false, problem: `단계 ${index + 1}: ${shapeProblem(validateStepShape.errors)}` }
  }
  const problem = meaningProblem(value, previous, targets)
  return problem ? { ok: false, problem: `단계 ${index + 1}: ${problem}` } : { ok: true, value }
}

export function checkRetreatBelowHp(value: unknown): Checked<number> {
  return validateRetreatShape(value)
    ? { ok: true, value }
    : { ok: false, problem: `retreatBelowHp는 0~${planSchema.properties.retreatBelowHp.maximum} 사이의 체력 비율입니다` }
}

function meaningProblem(step: PlanStep, previous: PlanStep | undefined, targets: ReadonlySet<string>): string | null {
  if (previous?.until === 'never') {
    return '앞 단계의 until이 never라 이 단계까지 가지 않습니다 (never는 마지막 단계에만 씁니다)'
  }
  if (step.target !== null && step.skill !== 'engage') {
    return `${step.skill}의 target은 null이어야 합니다 (target은 engage에만 씁니다)`
  }
  if (step.target !== null && !targets.has(step.target)) {
    return `장면에 없는 드론입니다: ${step.target} (있는 드론: ${[...targets].join(', ') || '없음'})`
  }
  if (step.until === 'targetDestroyed' && step.target === null) {
    return 'targetDestroyed는 target을 정한 engage에만 씁니다'
  }
  if ((step.until === 'allDestroyed' || step.until === 'targetDestroyed') && step.skill !== 'engage') {
    return `${step.until}는 engage에만 씁니다 (쏘는 기술은 engage뿐이라 ${step.skill}로는 이 단계가 끝나지 않습니다)`
  }
  if (step.until === 'hpBelow' && !HP_WAITING_SKILLS.has(step.skill)) {
    return `hpBelow는 engage·hold에만 씁니다 (${step.skill} 중에 체력이 줄기를 기다리는 단계가 됩니다). 물러날 체력은 retreatBelowHp로 씁니다`
  }
  return valueProblem(step)
}

function valueProblem(step: PlanStep): string | null {
  switch (step.until) {
    case 'seconds':
      return step.value >= MIN_SECONDS && step.value <= MAX_SECONDS ? null : `seconds면 value는 ${MIN_SECONDS}~${MAX_SECONDS}초입니다`
    case 'hpBelow':
      return step.value > 0 && step.value < 1 ? null : 'hpBelow면 value는 0과 1 사이의 체력 비율입니다 (예: 0.5)'
    default:
      return step.value === 0 ? null : `until이 ${step.until}이면 value는 0입니다`
  }
}

function shapeProblem(errors: ErrorObject[] | null | undefined): string {
  const error = errors?.[0]
  if (!error) {
    return '모양이 맞지 않습니다'
  }
  const extra = typeof error.params.additionalProperty === 'string' ? ` (${error.params.additionalProperty})` : ''
  const allowed = Array.isArray(error.params.allowedValues) ? ` (${error.params.allowedValues.join(', ')})` : ''
  return `${error.instancePath || '전체'} ${error.message ?? ''}${extra}${allowed}`.trim()
}
