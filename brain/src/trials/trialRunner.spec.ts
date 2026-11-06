import { describe, expect, it } from 'vitest'
import type { Evasion, SkillName, StartTrials } from '@shared/brain/generated/control'
import type { PlanStatus, TrialSeries } from '@shared/brain/generated/status'
import type { StateMessage } from '@shared/sim/generated/message'
import { drone, mechaStatus, planStatus, SCENARIOS, stateMessage } from '@shared/test/fixtures'
import { RecordingSender, settle } from '../testing'
import { RESET_TIMEOUT_MS, startDelay, TrialRunner, type TrialSubject } from './trialRunner'
import type { TrialStore } from './trialStore'

class RecordingSubject implements TrialSubject {
  readonly calls: string[] = []
  autonomy = false
  planNow: PlanStatus | null = null

  setSkill(name: SkillName, _target: string | null, evasion: Evasion): void {
    this.calls.push(`setSkill ${name} ${evasion}`)
  }

  setAutonomy(enabled: boolean): void {
    this.autonomy = enabled
  }

  async order(text: string): Promise<void> {
    this.calls.push(`order ${text}`)
    this.autonomy = true
  }

  reactionMs(): number | null {
    return 18
  }

  plan(): PlanStatus | null {
    return this.planNow
  }
}

class MemoryStore implements TrialStore {
  readonly saved: TrialSeries[] = []
  fail = false

  async save(series: TrialSeries): Promise<string> {
    if (this.fail) {
      throw new Error('디스크가 가득 참')
    }
    this.saved.push(series)
    return `results/trials/${this.saved.length}.json`
  }
}

const SKIRMISH: StartTrials = {
  type: 'startTrials',
  scenario: 'skirmish',
  setups: [
    { kind: 'skill', skill: 'engage', evasion: 'dodge' },
    { kind: 'skill', skill: 'engage', evasion: 'guard' },
  ],
  runs: 2,
  timeLimitS: 60,
  startSpreadS: 0,
}

const DRONES = [drone({ id: 'drone-1' }), drone({ id: 'drone-2' }), drone({ id: 'drone-3' })]

function state(simTime: number, overrides: { dead?: number; hp?: number; scenario?: string } = {}): StateMessage {
  return stateMessage({
    simTime,
    scenario: overrides.scenario ?? 'skirmish',
    units: DRONES.map((unit, index) => ({ ...unit, alive: index >= (overrides.dead ?? 0) })),
    mecha: mechaStatus({ hp: overrides.hp ?? 1000 }),
  })
}

function setup() {
  const sender = new RecordingSender()
  const subject = new RecordingSubject()
  const store = new MemoryStore()
  const notes: string[] = []
  let clock = 0
  const runner = new TrialRunner({
    sender,
    subject,
    store,
    note: (text) => notes.push(text),
    now: () => clock,
    clock: () => new Date('2026-11-06T12:00:00.000Z'),
  })
  runner.setScenarios(SCENARIOS)
  runner.setSimConnected(true)
  return { runner, sender, subject, store, notes, advance: (ms: number) => (clock += ms) }
}

/** 되돌리기의 답을 받고 첫 상태로 판을 시작한 뒤, clearAt초에 드론을 다 격파한다 */
async function playRun(runner: TrialRunner, clearAt: number, hp = 1000): Promise<void> {
  await settle()
  runner.onState(state(0.02))
  runner.onState(state(clearAt / 2, { dead: 1, hp }))
  runner.onState(state(clearAt + 0.02, { dead: 3, hp }))
}

describe('TrialRunner', () => {
  it('비교할 것을 번갈아 돌려(1판째를 모두 돌리고 2판째로) 판마다 결과·점수를, 모아서 가운데 값을 내고 남긴다', async () => {
    const { runner, sender, subject, store } = setup()

    expect(runner.start(SKIRMISH)).toBeNull()
    await playRun(runner, 20)
    await playRun(runner, 30, 840)
    await playRun(runner, 40)
    await playRun(runner, 50, 840)
    await settle()

    expect(sender.sent.filter((command) => command.type === 'reset')).toHaveLength(4)
    expect(subject.calls).toEqual(['setSkill engage dodge', 'setSkill engage guard', 'setSkill engage dodge', 'setSkill engage guard'])
    const series = runner.status()!
    expect(series).toMatchObject({ state: 'done', current: null, finishedAt: '2026-11-06T12:00:00.000Z', savedTo: 'results/trials/1.json' })
    expect(series.setups.map((entry) => entry.label)).toEqual(['교전 · 피하기', '교전 · 방패로 막기'])
    expect(series.setups[0]!.results.map((result) => result.clearTimeS)).toEqual([20, 40])
    expect(series.setups[1]!.summary).toMatchObject({ runs: 2, cleared: 2, clearTimeS: { median: 40 }, damageTaken: { median: 160 } })
    expect(store.saved).toHaveLength(1)
    expect(subject.autonomy).toBe(false)
  })

  it('판을 시작할 때 두뇌에게 맡기고, 판이 끝나 장면을 되돌리는 동안에는 조종을 내려놓게 한다', async () => {
    const { runner, subject } = setup()
    runner.start(SKIRMISH)
    await settle()

    expect(subject.autonomy).toBe(false)
    runner.onState(state(0.02))
    expect(subject.autonomy).toBe(true)
    expect(runner.status()?.current).toEqual({ setup: 0, run: 1, phase: 'running', startDelayS: 0, elapsedS: 0 })
    runner.onState(state(30, { dead: 3 }))

    expect(subject.autonomy).toBe(false)
    expect(runner.status()?.current).toMatchObject({ setup: 1, run: 1, phase: 'resetting' })
  })

  it('말로 한 명령은 판마다 다시 명령하고, 계획의 시간을 결과에 남긴다', async () => {
    const { runner, subject } = setup()
    subject.planNow = planStatus()
    runner.start({ ...SKIRMISH, setups: [{ kind: 'order', text: '공격' }], runs: 1 })

    await playRun(runner, 25)

    expect(subject.calls).toEqual(['order 공격'])
    expect(runner.status()?.setups[0]?.results[0]).toMatchObject({ planFirstStepMs: 1480, planAttempts: 1 })
  })

  it('경계값: 제한 시간이 지나면 그 판을 끝내고 다음 판으로 간다', async () => {
    const { runner } = setup()
    runner.start({ ...SKIRMISH, runs: 1, timeLimitS: 10 })
    await settle()
    runner.onState(state(0.02))

    runner.onState(state(9.98, { dead: 1 }))
    expect(runner.status()?.current?.run).toBe(1)
    expect(runner.status()?.current?.setup).toBe(0)
    runner.onState(state(10.02, { dead: 1 }))

    expect(runner.status()?.setups[0]?.results[0]).toMatchObject({ outcome: 'timeout', clearTimeS: null, kills: 1, durationS: 10 })
    expect(runner.status()?.current).toMatchObject({ setup: 1, phase: 'resetting' })
  })

  it('순서: 되돌리기의 답을 받기 전에 온 상태(되돌리기 전의 상태)로는 판을 시작하지 않는다', async () => {
    const { runner, sender, subject } = setup()
    sender.holdReplies = true
    runner.start(SKIRMISH)

    runner.onState(state(42, { dead: 1 }))
    expect(subject.calls).toEqual([])
    sender.flush()
    await settle()
    runner.onState(state(0.02))

    expect(subject.calls).toEqual(['setSkill engage dodge'])
  })

  it.each([
    ['이미 시험 중', (runner: TrialRunner) => runner.start(SKIRMISH), SKIRMISH, '이미 시험 중입니다'],
    ['몸과 끊김', (runner: TrialRunner) => runner.setSimConnected(false), SKIRMISH, '몸(시뮬레이터)에 연결되어야'],
    ['없는 장면', () => undefined, { ...SKIRMISH, scenario: 'volcano' }, '그런 시험 장면이 없습니다: volcano'],
    ['드론이 없는 장면', () => undefined, { ...SKIRMISH, scenario: 'empty' }, '빈 시험장에는 드론이 없어'],
  ] as const)('실패: %s이면 시작하지 않고 까닭을 돌려준다', (_, before, spec, reason) => {
    const { runner } = setup()
    before(runner)

    expect(runner.start(spec)).toContain(reason)
  })

  it('실패: 몸이 장면 되돌리기를 거절하면 시험을 멈추고 까닭을 남긴다', async () => {
    const { runner, sender } = setup()
    sender.rejectTypes.add('reset')

    runner.start(SKIRMISH)
    await settle()

    expect(runner.status()).toMatchObject({ state: 'failed', error: expect.stringContaining('몸이 장면 되돌리기를 거절함') })
  })

  it('실패: 되돌리기에 정한 시간 안에 답이 없으면 시험을 멈춘다', () => {
    const { runner, sender, advance } = setup()
    sender.holdReplies = true
    runner.start(SKIRMISH)

    advance(RESET_TIMEOUT_MS)
    runner.onState(state(42))
    expect(runner.running).toBe(true)
    advance(1)
    runner.onState(state(42.02))

    expect(runner.status()).toMatchObject({ state: 'failed', error: expect.stringContaining('몸이 답하지 않음') })
  })

  it('실패: 판 중간에 몸과 끊기면 시험이 실패하고, 끝난 판의 결과는 남긴다', async () => {
    const { runner, store } = setup()
    runner.start(SKIRMISH)
    await playRun(runner, 20)
    await settle()
    runner.onState(state(0.02))

    runner.setSimConnected(false)
    await settle()

    expect(runner.status()).toMatchObject({ state: 'failed', error: '몸(시뮬레이터)과 연결이 끊겼습니다' })
    expect(store.saved[0]?.setups[0]?.results).toHaveLength(1)
  })

  it('순서: 판 중간에 다른 곳에서 장면을 되돌리면(시각이 줄면) 시험이 실패한다', async () => {
    const { runner } = setup()
    runner.start(SKIRMISH)
    await settle()
    runner.onState(state(0.02))
    runner.onState(state(12))

    runner.onState(state(0.02))

    expect(runner.status()).toMatchObject({ state: 'failed', error: expect.stringContaining('다른 곳에서 장면을 처음으로 되돌렸습니다') })
  })

  it('실패: 되돌린 장면이 시험할 장면과 다르면 멈춘다', async () => {
    const { runner } = setup()
    runner.start(SKIRMISH)
    await settle()

    runner.onState(state(0.02, { scenario: 'targets' }))

    expect(runner.status()).toMatchObject({ state: 'failed', error: '되돌린 장면이 다릅니다: targets' })
  })

  it('사람이 멈추면 끝난 판까지 남기고, 중복으로 멈추면 false', async () => {
    const { runner, store, notes } = setup()
    runner.start(SKIRMISH)
    await playRun(runner, 20)

    expect(runner.stop()).toBe(true)
    expect(runner.stop()).toBe(false)
    await settle()

    expect(runner.status()).toMatchObject({ state: 'stopped', error: null, current: null })
    expect(store.saved).toHaveLength(1)
    expect(notes.at(-1)).toBe('시험 끝 (사람이 멈춤, 1판)')
  })

  it('경계값: 한 판도 끝나지 않았으면 남기지 않는다', async () => {
    const { runner, store } = setup()
    runner.start(SKIRMISH)

    runner.stop()
    await settle()

    expect(store.saved).toEqual([])
    expect(runner.status()?.savedTo).toBeNull()
  })

  it('실패: 결과를 남기지 못하면 판단 기록에 알리고 경로는 비워 둔다', async () => {
    const { runner, store, notes } = setup()
    store.fail = true
    runner.start({ ...SKIRMISH, runs: 1, setups: [SKIRMISH.setups[0]!] })

    await playRun(runner, 20)
    await settle()

    expect(runner.status()).toMatchObject({ state: 'done', savedTo: null })
    expect(notes.at(-1)).toBe('시험 결과를 남기지 못함: 디스크가 가득 참')
  })

  it('끝난 시험 뒤에 다시 시작할 수 있다', async () => {
    const { runner } = setup()
    runner.start({ ...SKIRMISH, runs: 1, setups: [SKIRMISH.setups[0]!] })
    await playRun(runner, 20)

    expect(runner.start(SKIRMISH)).toBeNull()
    expect(runner.status()).toMatchObject({ state: 'running', setups: [{ results: [] }, { results: [] }] })
  })

  it('상태를 고쳐도 시험에는 영향이 없다 (복사본을 준다)', () => {
    const { runner } = setup()
    runner.start(SKIRMISH)

    runner.status()!.setups.pop()

    expect(runner.status()?.setups).toHaveLength(2)
  })

  it('맡는 때를 늦추면 그동안 기다렸다가 맡기고, 시간·피해는 맡은 때부터 잰다 (기다리는 동안 맞은 것은 빼고)', async () => {
    const { runner, subject } = setup()
    runner.start({ ...SKIRMISH, setups: [SKIRMISH.setups[0]!], runs: 2, startSpreadS: 4 })
    await playRun(runner, 20)
    await settle()

    runner.onState(state(0.02))
    expect(runner.status()?.current).toMatchObject({ run: 2, phase: 'waiting', startDelayS: 2 })
    runner.onState(state(1.5, { hp: 960 }))
    expect(subject.calls).toHaveLength(1)
    runner.onState(state(2.02, { hp: 920 }))
    expect(subject.calls).toEqual(['setSkill engage dodge', 'setSkill engage dodge'])
    expect(runner.status()?.current).toMatchObject({ run: 2, phase: 'running' })
    runner.onState(state(12.02, { dead: 3, hp: 880 }))

    expect(runner.status()?.setups[0]?.results.map((result) => [result.startDelayS, result.clearTimeS, result.damageTaken])).toEqual([
      [0, 20, 0],
      [2, 10, 40],
    ])
  })

  it('순서: 기다리는 동안 다른 곳에서 장면을 되돌리면 시험이 실패한다', async () => {
    const { runner } = setup()
    runner.start({ ...SKIRMISH, startSpreadS: 4 })
    await playRun(runner, 20)
    await settle()
    runner.onState(state(0.02))
    runner.onState(state(1))

    runner.onState(state(0.02))

    expect(runner.status()).toMatchObject({ state: 'failed', error: expect.stringContaining('다른 곳에서 장면을') })
  })
})

describe('startDelay', () => {
  it('n판이면 0부터 늦출 폭 ÷ n씩 고르게 늦춘다 (마지막 판도 폭을 넘지 않는다)', () => {
    expect([1, 2, 3, 4, 5].map((run) => startDelay(run, 5, 4))).toEqual([0, 0.8, 1.6, 2.4, 3.2])
  })

  it('경계값: 늦출 폭이 0이거나 한 판뿐이면 늦추지 않는다', () => {
    expect(startDelay(3, 5, 0)).toBe(0)
    expect(startDelay(1, 1, 10)).toBe(0)
  })
})
