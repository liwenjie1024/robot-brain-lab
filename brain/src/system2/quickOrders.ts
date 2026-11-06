import type { Plan, PlanStep } from '@shared/brain/generated/plan'

/**
 * 짧은 명령은 언어 모델에 묻지 않고 규칙으로 바로 알아듣는다 (급한 말에 3초를 기다리지 않게, 언어 모델이 없어도 쓰게).
 * 말 전체가 아래 낱말 하나일 때만 쓴다. "드론 1부터 공격해"처럼 더 붙은 말은 언어 모델이 본다.
 */

const SPACES_AND_MARKS = /[\s.,!?~…'"]+/g
/** 말 끝의 명령·높임 꼴은 떼고 본다 ("후퇴해라" → "후퇴") */
const ENDINGS = /(해주세요|해줘|하세요|세요|해라|하라|해요|해|라|요)$/

const step = (skill: PlanStep['skill'], evasion: PlanStep['evasion'], until: PlanStep['until']): PlanStep => ({
  skill,
  target: null,
  evasion,
  until,
  value: 0,
})

const QUICK_ORDERS: readonly { words: readonly string[]; plan: Plan }[] = [
  {
    words: ['멈춰', '멈춤', '정지', '그만', '스톱', 'stop'],
    plan: { say: '멈추고 다음 명령을 기다리겠습니다.', retreatBelowHp: 0, steps: [step('idle', 'none', 'never')] },
  },
  {
    words: ['물러나', '후퇴', '퇴각', '도망', '도망쳐', '빠져', 'retreat'],
    plan: { say: '드론 반대쪽으로 물러나며 피하고 막겠습니다.', retreatBelowHp: 0, steps: [step('retreat', 'both', 'never')] },
  },
  {
    words: ['지켜', '자리지켜', '버텨', '대기', 'hold'],
    plan: { say: '이 자리를 지키며 조준 경고는 피하겠습니다.', retreatBelowHp: 0, steps: [step('hold', 'dodge', 'never')] },
  },
  {
    words: ['공격', '교전', '싸워', '쏴', '격파', '다잡아', '모두잡아', '전부잡아', 'attack'],
    plan: {
      say: '드론을 모두 격파할 때까지 교전하고, 조준 경고는 피하겠습니다.',
      retreatBelowHp: 0,
      steps: [step('engage', 'dodge', 'allDestroyed'), step('hold', 'dodge', 'never')],
    },
  },
]

/** 비교하기 좋게: 작은 글자로, 띄어쓰기·문장 부호를 뺀다 */
export function normalizeOrder(text: string): string {
  return text.toLowerCase().replace(SPACES_AND_MARKS, '')
}

/** 알아들으면 계획 (매번 새 복사본), 아니면 null */
export function quickPlan(order: string): Plan | null {
  const word = normalizeOrder(order).replace(ENDINGS, '')
  const known = QUICK_ORDERS.find((entry) => entry.words.includes(word))
  return known ? structuredClone(known.plan) : null
}

/** 화면 도움말에 보일 예 */
export const QUICK_ORDER_EXAMPLES = QUICK_ORDERS.map((entry) => entry.words[0])
