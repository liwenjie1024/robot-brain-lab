import { describe, expect, it } from 'vitest'
import type { Evasion, SkillName } from '@shared/brain/generated/control'
import type { Plan } from '@shared/brain/generated/plan'
import { DecisionLog } from '../decisions'
import { drone, perceptionOf, ScriptedModel, settle, StepGate } from '../testing'
import type { SkillControl } from './planRun'
import { System2 } from './system2'

class RecordingSkills implements SkillControl {
  readonly skills: [SkillName, string | null, Evasion][] = []
  autonomy = false

  setSkill(name: SkillName, target: string | null, evasion: Evasion): void {
    this.skills.push([name, target, evasion])
  }

  setAutonomy(enabled: boolean): void {
    this.autonomy = enabled
  }
}

const PLAN: Plan = {
  say: '표적 드론 2를 먼저 잡고 나머지도 격파하겠습니다.',
  retreatBelowHp: 0.3,
  steps: [
    { skill: 'engage', target: 'drone-2', evasion: 'guard', until: 'targetDestroyed', value: 0 },
    { skill: 'engage', target: null, evasion: 'guard', until: 'allDestroyed', value: 0 },
    { skill: 'hold', target: null, evasion: 'guard', until: 'never', value: 0 },
  ],
}
const ORDER = '드론 2부터 잡고 나머지도 정리해'
const WRONG_PLAN = JSON.stringify({ ...PLAN, steps: [{ ...PLAN.steps[0], skill: 'hold' }] })
const SCENE = perceptionOf({ simTime: 3, scenario: 'skirmish', units: [drone({ id: 'drone-1' }), drone({ id: 'drone-2', name: '표적 드론 2' })] })

async function setup(options: { available?: boolean; answerTimeoutMs?: number } = {}) {
  const model = new ScriptedModel()
  model.available = options.available ?? true
  const skills = new RecordingSkills()
  const log = new DecisionLog()
  let clock = 0
  const system2 = new System2({ skills, log, model, now: () => clock, answerTimeoutMs: options.answerTimeoutMs })
  await system2.refreshPlanner()
  system2.update(SCENE)
  return { model, skills, log, system2, advance: (ms: number) => (clock += ms), notes: () => log.recent().map((decision) => decision.text) }
}

describe('System2', () => {
  it('짧은 명령은 언어 모델에 묻지 않고 바로 따르고, 조종을 맡는다', async () => {
    const { model, skills, system2 } = await setup()

    await system2.order('물러나!')

    expect(model.requests).toEqual([])
    expect(skills.autonomy).toBe(true)
    expect(skills.skills).toEqual([['retreat', null, 'both']])
    expect(system2.planStatus()).toMatchObject({ source: 'quick', state: 'running', attempts: 0, timing: { firstStepMs: 0, totalMs: 0 } })
  })

  it('언어 모델이 쓴 계획을 따르고, 첫 글자·첫 단계·전체 시간을 잰다', async () => {
    const { model, skills, system2, advance, notes } = await setup()
    const gate = new StepGate()
    model.pause = async (signal) => {
      await gate.wait(signal)
      advance(10)
    }
    model.reply(JSON.stringify(PLAN))

    const done = system2.order(ORDER)
    await gate.releaseUntil(() => skills.skills.length > 0)

    expect(system2.planStatus()).toMatchObject({ state: 'running', current: 0, retreatBelowHp: 0.3, say: PLAN.say, timing: { firstTokenMs: 10, totalMs: null } })
    expect(skills.skills).toEqual([['engage', 'drone-2', 'guard']])

    await gate.releaseUntil(() => gate.pending === 0 && system2.planStatus()?.timing.totalMs !== null)
    await done
    const status = system2.planStatus()
    expect(status).toMatchObject({ source: 'llm', state: 'running', attempts: 1, steps: [{ state: 'running' }, { state: 'waiting' }, { state: 'waiting' }] })
    expect(status?.timing.firstStepMs).toBeLessThan(status?.timing.totalMs ?? 0)
    expect(notes().at(-1)).toMatch(/^언어 모델이 계획을 짬: .* \(3단계, \d+\.\d초, 1번 물음\)$/)
    expect(model.requests[0]?.messages[1]?.content).toContain('"id":"drone-2"')
    expect(model.requests[0]?.messages[1]?.content).toContain(`명령: ${ORDER}`)
  })

  it('잘못된 단계가 흘러 오면 끝까지 기다리지 않고 끊고, 까닭을 붙여 다시 물어 고친 계획을 따른다', async () => {
    const { model, skills, system2, notes } = await setup()
    model.reply(WRONG_PLAN, JSON.stringify(PLAN))

    await system2.order(ORDER)

    expect(model.requests).toHaveLength(2)
    const retry = model.requests[1]?.messages ?? []
    expect(retry.map((message) => message.role)).toEqual(['system', 'user', 'assistant', 'user'])
    expect(retry[3]?.content).toContain('단계 1: hold의 target은 null이어야 합니다')
    expect(notes()).toContainEqual(expect.stringContaining('→ 까닭을 알려 주고 다시 물음'))
    expect(system2.planStatus()).toMatchObject({ state: 'running', attempts: 2, steps: [{ skill: 'engage', target: 'drone-2' }, {}, {}] })
    expect(skills.skills).toEqual([['engage', 'drone-2', 'guard']])
  })

  it('실패: 두 번 모두 잘못된 계획이면 실패로 알리고, 기술은 바꾸지 않는다', async () => {
    const { model, skills, system2 } = await setup()
    model.reply(WRONG_PLAN, '{"say":"멈춥니다","retreatBelowHp":2,"steps":[]}')

    await system2.order(ORDER)

    expect(system2.planStatus()).toMatchObject({ state: 'failed', attempts: 2, error: expect.stringContaining('2번 모두 맞지 않는 계획') })
    expect(system2.planStatus()?.error).toContain('retreatBelowHp는 0~0.9')
    expect(skills.skills).toEqual([])
  })

  it('실패: 다 받은 답이 JSON이 아니면 다시 묻는다', async () => {
    const { model, system2 } = await setup()
    model.reply('{"say":"교전', JSON.stringify(PLAN))

    await system2.order(ORDER)

    expect(model.requests).toHaveLength(2)
    expect(model.requests[1]?.messages[3]?.content).toContain('전체')
    expect(system2.planStatus()?.state).toBe('running')
  })

  it('같은 명령을 같은 상황에서 다시 하면 기억한 계획을 쓴다 (언어 모델에 묻지 않음)', async () => {
    const { model, system2 } = await setup()
    model.reply(JSON.stringify(PLAN))
    await system2.order(ORDER)

    await system2.order(`${ORDER}!`)

    expect(model.requests).toHaveLength(1)
    expect(system2.planStatus()).toMatchObject({ source: 'cache', state: 'running', attempts: 0 })
  })

  it('기억한 계획의 표적이 이미 격파됐으면 다시 묻는다', async () => {
    const { model, system2 } = await setup()
    model.reply(JSON.stringify(PLAN), JSON.stringify({ ...PLAN, steps: [PLAN.steps[1]] }))
    await system2.order(ORDER)
    system2.update(perceptionOf({ simTime: 4, scenario: 'skirmish', units: [drone({ id: 'drone-1' })] }))

    await system2.order(ORDER)

    expect(model.requests).toHaveLength(2)
    expect(system2.planStatus()?.source).toBe('llm')
  })

  it('순서: 짜는 중에 새 명령이 오면 앞 답을 끊고 버린다 (늦게 온 앞 답이 기술을 바꾸지 않는다)', async () => {
    const { model, skills, system2, notes } = await setup()
    const gate = new StepGate()
    model.pause = gate.wait
    model.reply(JSON.stringify(PLAN))
    const first = system2.order(ORDER)
    await gate.release()

    model.pause = null
    await system2.order('자리 지켜')
    await first

    expect(skills.skills).toEqual([['hold', null, 'dodge']])
    expect(system2.planStatus()).toMatchObject({ order: '자리 지켜', source: 'quick' })
    expect(notes()).toContain('계획을 그만둠: 새 명령을 받음')
  })

  it('짜는 중에 그만두면 언어 모델 요청을 끊고 그만둔 것으로 알린다', async () => {
    const { model, system2 } = await setup()
    const gate = new StepGate()
    model.pause = gate.wait
    model.reply(JSON.stringify(PLAN))
    const thinking = system2.order(ORDER)
    await gate.release()

    expect(system2.cancel('사람이 그만두게 함')).toBe(true)
    await thinking

    expect(model.requests[0]?.signal.aborted).toBe(true)
    expect(system2.planStatus()).toMatchObject({ state: 'cancelled' })
    expect(system2.cancel('또')).toBe(false)
  })

  it('실패: 언어 모델이 정한 시간 안에 답하지 않으면 다시 묻지 않고 실패한다', async () => {
    const { model, system2 } = await setup({ answerTimeoutMs: 30 })
    model.pause = new StepGate().wait
    model.reply(JSON.stringify(PLAN))

    await system2.order(ORDER)

    expect(model.requests).toHaveLength(1)
    expect(system2.planStatus()).toMatchObject({ state: 'failed', error: '언어 모델이 0.03초 안에 답하지 않음' })
  })

  it('실패: 언어 모델에 묻지 못하면 실패로 알리고, 쓸 수 있는지 다시 본다', async () => {
    const { model, system2 } = await setup()
    model.reply(new Error('fetch failed'))
    model.available = false

    await system2.order(ORDER)
    await settle()

    expect(system2.planStatus()).toMatchObject({ state: 'failed', error: '언어 모델에 묻지 못함: fetch failed' })
    expect(system2.plannerStatus()).toEqual({ model: 'test-model', available: false })
  })

  it('언어 모델이 없으면 짧은 명령만 따르고, 다른 명령은 까닭을 붙여 실패한다', async () => {
    const { model, system2, notes } = await setup({ available: false })

    await system2.order(ORDER)
    expect(system2.planStatus()).toMatchObject({ state: 'failed', error: expect.stringContaining('짧은 명령만 알아듣습니다 (예: 멈춰, 물러나, 지켜, 공격)') })
    await system2.order('공격')

    expect(model.requests).toEqual([])
    expect(system2.planStatus()).toMatchObject({ source: 'quick', state: 'running' })
    expect(notes()).toContainEqual(expect.stringContaining('언어 모델(test-model)을 쓸 수 없음'))
  })

  it('언어 모델을 다시 쓸 수 있게 되면 알리고 GPU에 미리 올린다 (바뀔 때만)', async () => {
    const { model, system2, notes } = await setup({ available: false })
    model.available = true

    await system2.refreshPlanner()
    await system2.refreshPlanner()

    expect(model.warmUps).toBe(1)
    expect(notes().filter((text) => text.includes('쓸 수 있음'))).toHaveLength(1)
  })

  it('실패: 몸의 상태를 받기 전에는 언어 모델로 계획을 짤 수 없다', async () => {
    const model = new ScriptedModel()
    const system2 = new System2({ skills: new RecordingSkills(), log: new DecisionLog(), model, now: () => 0 })

    await system2.order(ORDER)

    expect(system2.planStatus()).toMatchObject({ state: 'failed', error: '몸의 상태를 아직 받지 못해 계획을 짤 수 없습니다' })
  })

  it('순서: 몸이 처음으로 되돌아가면(시각이 줄면) 계획을 그만둔다', async () => {
    const { system2, notes } = await setup()
    await system2.order('공격')

    system2.update(perceptionOf({ simTime: 0.02 }))

    expect(system2.planStatus()?.state).toBe('cancelled')
    expect(notes().at(-1)).toBe('계획을 그만둠: 몸이 처음으로 되돌아감')
  })

  it('몸의 상태가 오면 계획의 단계를 넘긴다', async () => {
    const { skills, system2 } = await setup()
    await system2.order('공격')

    system2.update(perceptionOf({ simTime: 4, units: [] }))

    expect(skills.skills.map(([name]) => name)).toEqual(['engage', 'hold'])
  })
})
