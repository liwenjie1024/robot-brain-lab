import planSchema from '../../../contracts/brain/plan.schema.json'
import type { Perception } from '../perception'
import type { ChatMessage } from './model'

/**
 * 언어 모델에게 주는 글: 할 일과 규칙(시스템), 지금 장면과 명령(사용자).
 * 시스템 글은 늘 같게 둔다 (Ollama가 앞부분 계산을 다시 쓰므로 명령마다 빨라진다).
 */

export const SYSTEM_PROMPT = [
  '너는 사람형 전투 기체 BL-01의 작전 담당이다. 사람의 명령과 지금 장면을 보고, 기체가 차례로 할 단계를 JSON 하나로만 답한다.',
  '',
  '기술(skill):',
  '- engage: 드론과 교전한다 (다가가 겨누고 맞을 때만 쏜다). target에 드론 id를 쓰면 그 드론부터, null이면 기체가 고른다.',
  '- hold: 지금 자리에 떠서 지킨다.',
  '- retreat: 드론들 반대쪽으로 오르며 물러난다.',
  '- idle: 멈춘다.',
  '조준 경고를 받으면(evasion): dodge 옆으로 피하기(받는 피해가 가장 적다), guard 방패로 막기, both 둘 다.',
  '다음 단계로 넘어갈 때(until)와 value:',
  '- targetDestroyed: 이 단계의 target을 격파하면. target을 정한 engage에만 쓴다. value 0',
  '- allDestroyed: 모든 드론을 격파하면. engage에만 쓴다 (쏘는 기술은 engage뿐이다). value 0',
  '- seconds: value초가 지나면 (1~120)',
  '- hpBelow: 기체 체력 비율이 value 아래가 되면 (0과 1 사이, 예: 0.5). engage·hold에만 쓴다',
  '- never: 넘어가지 않는다. 마지막 단계에만 쓴다. value 0',
  'retreatBelowHp: 체력 비율이 이 값 아래면 계획을 멈추고 물러난다 (0~0.9). "위험하면 물러나"는 0.3, 말이 없으면 0.',
  '',
  '규칙:',
  '- target은 장면에 있는 드론의 id(예: "drone-1")나 null만 쓴다. 이름이 아니라 id를 쓴다.',
  '- engage가 아닌 단계의 target은 늘 null이다.',
  '- 드론을 정해 잡으라면 그 드론을 target으로 두고 targetDestroyed. "~부터"면 이어서 나머지를 잡는 단계를 둔다.',
  '- "체력이 적은·가까운·무장한 드론부터"는 장면의 hp·distance·armed를 보고 드론 id를 그 차례로 쓴다.',
  '- evasion은 명령에 말이 없으면 dodge. "막아·방패"는 guard, "피하며 막아"는 both.',
  '- seconds는 명령에 시간이 있을 때만 쓴다.',
  '- "위험하면 물러나", "체력이 절반이면 물러나"는 단계가 아니라 retreatBelowHp로 쓴다 (절반이면 0.5).',
  '- 드론을 다 잡은 뒤 할 말이 없으면 마지막에 hold never를 둔다.',
  '- 단계는 1~5개. say는 무엇을 하겠다는 한국어 한 문장이다 (명령을 그대로 되풀이하지 않는다).',
  '',
  '예) 명령: 드론 2부터 잡고 나머지도 정리해. 방패로 막아',
  '{"say":"표적 드론 2를 먼저 잡고 나머지도 격파하겠습니다.","retreatBelowHp":0,"steps":[' +
    '{"skill":"engage","target":"drone-2","evasion":"guard","until":"targetDestroyed","value":0},' +
    '{"skill":"engage","target":null,"evasion":"guard","until":"allDestroyed","value":0},' +
    '{"skill":"hold","target":null,"evasion":"guard","until":"never","value":0}]}',
  '예) 장면의 드론 hp: drone-1 60, drone-2 20, drone-3 40. 명령: 약한 드론부터 차례로 잡아. 위험하면 물러나',
  '{"say":"체력이 적은 드론 2, 3, 1 차례로 잡고, 위험하면 물러나겠습니다.","retreatBelowHp":0.3,"steps":[' +
    '{"skill":"engage","target":"drone-2","evasion":"dodge","until":"targetDestroyed","value":0},' +
    '{"skill":"engage","target":"drone-3","evasion":"dodge","until":"targetDestroyed","value":0},' +
    '{"skill":"engage","target":"drone-1","evasion":"dodge","until":"targetDestroyed","value":0},' +
    '{"skill":"hold","target":null,"evasion":"dodge","until":"never","value":0}]}',
].join('\n')

/**
 * 언어 모델이 피하기를 고를 수 있는 값. none은 주지 않는다: 7B 모델이 명령에 말이 없을 때 none을 골라
 * 조준 경고를 받고도 맞기만 하는 계획을 냈다 (규칙으로 말해도 따르지 않음). none은 사람이 직접 고를 때만 쓴다.
 */
export const MODEL_EVASIONS = ['dodge', 'guard', 'both'] as const

const STEP_FORMAT = {
  ...planSchema.$defs.PlanStep,
  properties: { ...planSchema.$defs.PlanStep.properties, evasion: { enum: MODEL_EVASIONS } },
}

/** 계획 스키마에서 $ref를 풀어 넣은 것 (Ollama의 format은 스키마 안의 참조를 따라가지 않는다) */
export const PLAN_FORMAT: object = {
  type: planSchema.type,
  properties: { ...planSchema.properties, steps: { ...planSchema.properties.steps, items: STEP_FORMAT } },
  required: planSchema.required,
  additionalProperties: false,
}

/** 다시 물을 때: 지난 답과 무엇이 틀렸는지 */
export interface RetryNote {
  answer: string
  problem: string
}

export function planMessages(order: string, perception: Perception, retry?: RetryNote): ChatMessage[] {
  const messages: ChatMessage[] = [
    { role: 'system', content: SYSTEM_PROMPT },
    { role: 'user', content: `장면: ${JSON.stringify(sceneSummary(perception))}\n명령: ${order}` },
  ]
  if (retry) {
    messages.push(
      { role: 'assistant', content: retry.answer || '(빈 답)' },
      { role: 'user', content: `이 계획은 쓸 수 없다: ${retry.problem}\n규칙을 지켜 계획 전체를 다시 답하라.` },
    )
  }
  return messages
}

/** 언어 모델이 읽을 만큼만 (거리는 m, 체력은 남은 값과 최대값) */
export function sceneSummary(perception: Perception): object {
  const { self, targets, threats } = perception
  const aiming = new Set(threats.map((threat) => threat.from))
  return {
    self: { hp: self.hp, maxHp: self.maxHp, energy: Math.round(self.energy), altitude: Math.round(self.position[2]), mode: self.mode },
    drones: targets.map((target) => ({
      id: target.id,
      name: target.name,
      distance: Math.round(target.distance),
      armed: target.armed,
      hp: target.hp,
      maxHp: target.maxHp,
      aimingAtMe: aiming.has(target.id),
    })),
  }
}
