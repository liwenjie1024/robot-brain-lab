// contracts/brain/plan.schema.json에서 만든 파일이다. 직접 고치지 말고 npm run contracts 로 다시 만든다.

/**
 * 느린 뇌(System 2)가 말로 한 명령을 보고 짜는 작전 계획. 언어 모델에 이 형식으로만 답하게 하고(Ollama format), 받은 뒤 같은 스키마로 다시 확인한다. 언어 모델이 잘 따르게 모든 필드를 늘 채우고 oneOf를 쓰지 않는다.
 */
export interface Plan {
  /**
   * 사람에게 하는 한국어 한 문장 (무엇을 하겠다는지)
   */
  say: string
  /**
   * 체력이 이 비율(0~0.9) 아래로 떨어지면 계획을 멈추고 물러난다. 0이면 쓰지 않는다. 단계보다 먼저 쓰게 해 첫 단계를 시작할 때 이미 알고 있다.
   */
  retreatBelowHp: number
  /**
   * 차례로 할 기술 (앞 단계의 until이 맞으면 다음 단계로)
   *
   * @minItems 1
   * @maxItems 5
   */
  steps:
    | [PlanStep]
    | [PlanStep, PlanStep]
    | [PlanStep, PlanStep, PlanStep]
    | [PlanStep, PlanStep, PlanStep, PlanStep]
    | [PlanStep, PlanStep, PlanStep, PlanStep, PlanStep]
}
/**
 * skill: idle 멈춤·hold 자리 지키기·engage 교전·retreat 물러나기. target: engage일 때 노릴 드론 id(없으면 null, 다른 기술은 늘 null). evasion: 조준 경고에 dodge 피하기·guard 막기·both 둘 다·none. until: 다음 단계로 넘어갈 때 — targetDestroyed(이 단계 표적 격파), allDestroyed(모든 드론 격파), seconds(value초 지남), hpBelow(체력 비율이 value 아래), never(넘어가지 않음). value: seconds면 1~120초, hpBelow면 0~1 비율, 그 밖에는 0
 *
 * This interface was referenced by `Plan`'s JSON-Schema
 * via the `definition` "PlanStep".
 */
export interface PlanStep {
  skill: 'idle' | 'hold' | 'engage' | 'retreat'
  target: string | null
  evasion: 'dodge' | 'guard' | 'both' | 'none'
  until: 'targetDestroyed' | 'allDestroyed' | 'seconds' | 'hpBelow' | 'never'
  value: number
}
