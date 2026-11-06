import type { Plan, PlanStep } from '@shared/brain/generated/plan'
import type { PlannerStatus, PlanStatus } from '@shared/brain/generated/status'
import type { SceneDescription } from '@shared/sim/generated/scene'
import type { DecisionLog } from '../decisions'
import type { Perception } from '../perception'
import type { ChatMessage, LanguageModel } from './model'
import { PlanCache, type Situation } from './planCache'
import { checkPlan, checkRetreatBelowHp, checkStep } from './planCheck'
import { PlanRun, type PlanSource, type SkillControl } from './planRun'
import { parseJson, PlanStreamReader, type StreamPiece } from './planStream'
import { PLAN_FORMAT, planMessages, type RetryNote } from './prompt'
import { QUICK_ORDER_EXAMPLES, quickPlan } from './quickOrders'

/** 잘못된 계획이면 까닭을 붙여 한 번 더 묻는다 (재 보니 대개 두 번째에 맞게 고친다) */
const MAX_ATTEMPTS = 2
/** 모델이 GPU에 없으면 올리는 데 몇 초 걸린다 (따뜻할 때 계획 전체는 약 3초) */
export const ANSWER_TIMEOUT_MS = 30_000
const MS_PER_SECOND = 1000

const SOURCE_NOTES: Record<PlanSource, string> = {
  quick: '짧은 명령으로 바로 알아들음',
  cache: '전에 짠 계획을 다시 씀',
  llm: '언어 모델이 계획을 짬',
}

export interface System2Deps {
  skills: SkillControl
  log: DecisionLog
  model: LanguageModel
  now: () => number
  answerTimeoutMs?: number
}

type Answer = { plan: Plan } | { problem: string; answer: string; final: boolean }

/**
 * 느린 뇌(System 2): 말로 한 명령을 계획(기술 단계)으로 바꿔 빠른 뇌에게 차례로 시킨다.
 * 짧은 명령은 규칙으로 바로, 전에 짠 명령은 기억에서, 나머지는 언어 모델에 묻는다 (흘러 오는 첫 단계부터 시작한다).
 * 빠른 뇌는 계획을 기다리지 않고 50Hz로 계속 판단한다. 계획이 바뀌는 것은 기술뿐이다.
 */
export class System2 {
  private run: PlanRun | null = null
  private perception: Perception | null = null
  private available = false
  private checked = false
  private names = new Map<string, string>()
  private readonly cache = new PlanCache()
  private request: AbortController | null = null
  /** 명령·그만두기마다 늘린다. 앞 명령의 늦게 온 답을 버리려고 */
  private generation = 0

  constructor(private readonly deps: System2Deps) {}

  setScene(scene: SceneDescription): void {
    this.names = new Map(scene.units.map((unit) => [unit.id, unit.name]))
  }

  update(perception: Perception): void {
    if (this.perception && perception.simTime < this.perception.simTime) {
      this.cancel('몸이 처음으로 되돌아감')
    }
    this.perception = perception
    this.run?.update(perception)
  }

  /** 언어 모델을 쓸 수 있는지 다시 본다. 쓸 수 있게 되면 GPU에 미리 올린다. */
  async refreshPlanner(): Promise<boolean> {
    const available = await this.deps.model.isAvailable()
    if (available !== this.available || !this.checked) {
      const name = this.deps.model.name
      this.note(
        available
          ? `느린 뇌의 언어 모델(${name})을 쓸 수 있음`
          : `언어 모델(${name})을 쓸 수 없음 — 짧은 명령(${QUICK_ORDER_EXAMPLES.join('·')})만 알아들음`,
      )
      if (available) {
        void this.deps.model.warmUp().catch(() => undefined)
      }
    }
    this.available = available
    this.checked = true
    return available
  }

  /** 말로 한 명령. 받으면 두뇌가 조종을 맡는다. 계획을 다 짜면(또는 실패하면) 끝나는 Promise */
  async order(text: string): Promise<void> {
    const order = text.trim()
    this.cancel('새 명령을 받음')
    const generation = this.generation
    const startedAt = this.deps.now()
    this.note(`명령 받음: "${order}"`)
    this.deps.skills.setAutonomy(true)

    const quick = quickPlan(order)
    if (quick) {
      this.follow(this.newRun(order, 'quick', startedAt), quick)
      return
    }
    const perception = this.perception
    if (!perception) {
      this.newRun(order, 'llm', startedAt).fail('몸의 상태를 아직 받지 못해 계획을 짤 수 없습니다')
      return
    }
    const situation = situationOf(perception)
    const cached = this.cache.get(order, situation)
    if (cached && checkPlan(cached, situation.targets).ok) {
      this.follow(this.newRun(order, 'cache', startedAt), cached)
      return
    }
    const run = this.newRun(order, 'llm', startedAt)
    if (!this.available && !(await this.refreshPlanner())) {
      if (generation === this.generation) {
        run.fail(`언어 모델(${this.deps.model.name})을 쓸 수 없어 짧은 명령만 알아듣습니다 (예: ${QUICK_ORDER_EXAMPLES.join(', ')})`)
      }
      return
    }
    if (generation === this.generation) {
      await this.think(run, perception, situation, generation)
    }
  }

  /** 짜거나 따르는 계획을 그만둔다 (기체는 지금 기술을 그대로 한다). 그만둘 것이 없으면 false */
  cancel(reason: string): boolean {
    this.generation++
    this.request?.abort()
    this.request = null
    return this.run?.cancel(reason) ?? false
  }

  /** 기억한 계획을 잊는다 (시험에서 판마다 언어 모델에 새로 묻게) */
  forgetPlans(): void {
    this.cache.clear()
  }

  planStatus(): PlanStatus | null {
    return this.run?.view() ?? null
  }

  plannerStatus(): PlannerStatus {
    return { model: this.deps.model.name, available: this.available }
  }

  private newRun(order: string, source: PlanSource, startedAt: number): PlanRun {
    this.run = new PlanRun(order, source, {
      skills: this.deps.skills,
      note: (text) => this.note(text),
      nameOf: (id) => this.names.get(id) ?? id,
      elapsedMs: () => Math.round(this.deps.now() - startedAt),
    })
    return this.run
  }

  private follow(run: PlanRun, plan: Plan): void {
    this.note(`${SOURCE_NOTES[run.source]}: ${plan.say}`)
    run.setSay(plan.say)
    run.setRetreatBelowHp(plan.retreatBelowHp)
    plan.steps.forEach((step) => run.addStep(step))
    run.complete()
  }

  private async think(run: PlanRun, perception: Perception, situation: Situation, generation: number): Promise<void> {
    let retry: RetryNote | undefined
    for (let attempt = 1; attempt <= MAX_ATTEMPTS; attempt++) {
      const answer = await this.ask(run, planMessages(run.order, perception, retry), situation.targets, generation)
      if (generation !== this.generation) {
        return
      }
      if ('plan' in answer) {
        run.setSay(answer.plan.say)
        run.complete()
        this.cache.put(run.order, situation, answer.plan)
        const seconds = ((run.view().timing.totalMs ?? 0) / MS_PER_SECOND).toFixed(1)
        this.note(`${SOURCE_NOTES.llm}: ${answer.plan.say} (${answer.plan.steps.length}단계, ${seconds}초, ${attempt}번 물음)`)
        return
      }
      if (answer.final) {
        run.fail(answer.problem)
        return
      }
      retry = answer
      if (attempt < MAX_ATTEMPTS) {
        this.note(`언어 모델의 계획이 맞지 않음 (${answer.problem}) → 까닭을 알려 주고 다시 물음`)
      }
    }
    run.fail(`언어 모델이 ${MAX_ATTEMPTS}번 모두 맞지 않는 계획을 냄: ${retry?.problem ?? ''}`)
  }

  /** 한 번 묻는다. 단계는 받는 대로 확인해 바로 시작하고, 틀린 것이 보이면 끝까지 기다리지 않고 끊는다. */
  private async ask(run: PlanRun, messages: ChatMessage[], targets: ReadonlySet<string>, generation: number): Promise<Answer> {
    run.startAttempt()
    const reader = new PlanStreamReader()
    const controller = new AbortController()
    const timeout = AbortSignal.timeout(this.deps.answerTimeoutMs ?? ANSWER_TIMEOUT_MS)
    this.request = controller
    const steps: PlanStep[] = []
    let answer = ''
    let problem: string | null = null
    const onText = (text: string) => {
      if (problem !== null || generation !== this.generation) {
        return
      }
      run.heardFirstToken()
      answer += text
      for (const piece of reader.push(text)) {
        problem = this.take(run, piece, steps, targets)
        if (problem !== null) {
          controller.abort()
          return
        }
      }
    }
    try {
      await this.deps.model.chat({ messages, format: PLAN_FORMAT, signal: AbortSignal.any([controller.signal, timeout]) }, onText)
    } catch (error) {
      if (generation !== this.generation) {
        return { problem: '그만둠', answer, final: true }
      }
      if (problem === null) {
        return this.failedAsk(error, timeout, answer)
      }
    } finally {
      if (this.request === controller) {
        this.request = null
      }
    }
    if (problem !== null) {
      return { problem, answer, final: false }
    }
    const checked = checkPlan(parseJson(answer), targets)
    if (!checked.ok) {
      return { problem: checked.problem, answer, final: false }
    }
    // 흘러 올 때 읽은 것과 다 읽은 것은 같아야 하지만, 혹시 놓친 값이 있어도 다 읽은 계획을 따른다.
    checked.value.steps.slice(steps.length).forEach((step) => run.addStep(step))
    run.setRetreatBelowHp(checked.value.retreatBelowHp)
    return { plan: checked.value }
  }

  private failedAsk(error: unknown, timeout: AbortSignal, answer: string): Answer {
    if (timeout.aborted) {
      return { problem: `언어 모델이 ${(this.deps.answerTimeoutMs ?? ANSWER_TIMEOUT_MS) / MS_PER_SECOND}초 안에 답하지 않음`, answer, final: true }
    }
    void this.refreshPlanner()
    return { problem: `언어 모델에 묻지 못함: ${error instanceof Error ? error.message : String(error)}`, answer, final: true }
  }

  /** 흘러 온 값 하나를 받는다. 틀렸으면 까닭 */
  private take(run: PlanRun, piece: StreamPiece, steps: PlanStep[], targets: ReadonlySet<string>): string | null {
    if (piece.kind === 'step') {
      const checked = checkStep(piece.value, steps.length, steps.at(-1), targets)
      if (!checked.ok) {
        return checked.problem
      }
      steps.push(checked.value)
      run.addStep(checked.value)
      return null
    }
    if (piece.key === 'say' && typeof piece.value === 'string') {
      run.setSay(piece.value)
    } else if (piece.key === 'retreatBelowHp') {
      const checked = checkRetreatBelowHp(piece.value)
      if (!checked.ok) {
        return checked.problem
      }
      run.setRetreatBelowHp(checked.value)
    }
    return null
  }

  private note(text: string): void {
    this.deps.log.add('plan', text, this.perception?.simTime ?? null)
  }
}

function situationOf(perception: Perception): Situation {
  return { scenario: perception.scenario, targets: new Set(perception.targets.map((target) => target.id)) }
}
