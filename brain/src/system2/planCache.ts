import type { Plan } from '@shared/brain/generated/plan'
import { normalizeOrder } from './quickOrders'

const CAPACITY = 32

/** 계획을 다시 써도 되는 상황: 같은 시험 장면, 같은 드론이 살아 있음 */
export interface Situation {
  scenario: string
  targets: ReadonlySet<string>
}

/**
 * 언어 모델이 짠 계획을 기억해 같은 명령·같은 상황에 다시 쓴다 (같은 말을 또 하면 언어 모델을 기다리지 않는다).
 * 드론의 거리·체력은 늘 조금씩 바뀌어 키에 넣지 않는다. 그래서 꺼낸 계획도 쓰기 전에 다시 확인한다.
 * 가장 오래 안 쓴 것부터 잊는다.
 */
export class PlanCache {
  private readonly entries = new Map<string, Plan>()

  constructor(private readonly capacity = CAPACITY) {}

  get(order: string, situation: Situation): Plan | undefined {
    const key = cacheKey(order, situation)
    const plan = this.entries.get(key)
    if (!plan) {
      return undefined
    }
    this.entries.delete(key)
    this.entries.set(key, plan)
    return structuredClone(plan)
  }

  put(order: string, situation: Situation, plan: Plan): void {
    const key = cacheKey(order, situation)
    this.entries.delete(key)
    this.entries.set(key, structuredClone(plan))
    for (const oldest of this.entries.keys()) {
      if (this.entries.size <= this.capacity) {
        break
      }
      this.entries.delete(oldest)
    }
  }
}

function cacheKey(order: string, situation: Situation): string {
  return [normalizeOrder(order), situation.scenario, [...situation.targets].sort().join(',')].join('|')
}
