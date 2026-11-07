import type { BrainStatus, PlanStatus, RunResult, TrialSeries } from '../brain/generated/status'
import type { MechaStatus, StateMessage, UnitStatus } from '../sim/generated/message'
import type { Limits, ScenarioInfo, SceneDescription } from '../sim/generated/scene'

/** 시험에서 함께 쓰는 값. 몸이 실제로 알리는 값과 같게 둔다 (sim/robot_sim/limits.py). */
export const LIMITS: Limits = {
  forward: { min: -15, max: 40 },
  sideways: { min: -20, max: 20 },
  up: { min: -15, max: 20 },
  turn: { min: -1.2, max: 1.2 },
  pushForce: { min: 0, max: 3_000_000 },
  pushDurationMs: { min: 10, max: 1000 },
}

/** 몸이 /scene으로 알리는 시험 장면 (sim/robot_sim/scenarios.py와 같은 수) */
export const SCENARIOS: ScenarioInfo[] = [
  { name: 'empty', label: '빈 시험장', description: '드론 없이 날기·자세만 시험합니다.', drones: 0, armedDrones: 0 },
  { name: 'targets', label: '표적 사격', description: '멈춰 떠 있는 드론 3대를 맞힙니다.', drones: 3, armedDrones: 0 },
  { name: 'skirmish', label: '반격하는 드론', description: '원을 그리며 나는 드론 3대가 조준 경고 1.2초 뒤에 쏩니다.', drones: 3, armedDrones: 3 },
]

export function sceneDescription(overrides: Partial<SceneDescription> = {}): SceneDescription {
  return {
    robot: { name: 'BL-01', description: '시험 기체', height: 16 },
    movingBodies: [],
    geoms: [],
    meshes: [],
    units: [
      { id: 'mecha', kind: 'mecha', name: 'BL-01', body: 1 },
      { id: 'drone-1', kind: 'drone', name: '표적 드론 1', body: 6 },
      { id: 'drone-2', kind: 'drone', name: '표적 드론 2', body: 7 },
    ],
    scenarios: SCENARIOS,
    limits: LIMITS,
    rates: { physicsHz: 500, controlHz: 50, stateHz: 50 },
    ...overrides,
  }
}

export const NAMES = new Map([
  ['drone-1', '표적 드론 1'],
  ['drone-2', '표적 드론 2'],
])

export function mechaStatus(overrides: Partial<MechaStatus> = {}): MechaStatus {
  return {
    position: [10, 0, 30.5],
    heading: Math.PI / 2,
    altitude: 20,
    velocity: { forward: 19.6, sideways: 0.1, up: 0, turn: 0 },
    command: { forward: 20, sideways: 0, up: 0, turn: 0 },
    mode: 'flying',
    hp: 1000,
    maxHp: 1000,
    energy: 100,
    weapon: { ready: true, cooldown: 0, aimTarget: null },
    guard: { raised: false, unit: null },
    pushing: false,
    ...overrides,
  }
}

export function drone(overrides: Partial<UnitStatus> = {}): UnitStatus {
  return {
    id: 'drone-1',
    kind: 'drone',
    name: '표적 드론 1',
    position: [160, 0, 30.5],
    velocity: [0, 0, 0],
    hp: 60,
    maxHp: 60,
    alive: true,
    armed: false,
    ...overrides,
  }
}

export function stateMessage(overrides: Partial<StateMessage> = {}): StateMessage {
  return {
    type: 'state',
    seq: 1,
    episode: 0,
    simTime: 12.34,
    scenario: 'targets',
    bodies: [0, 0, 10.5, 1, 0, 0, 0],
    mecha: mechaStatus(),
    units: [drone()],
    threats: [],
    ...overrides,
  }
}

export function brainStatus(overrides: Partial<BrainStatus> = {}): BrainStatus {
  return {
    type: 'brainStatus',
    simConnected: true,
    autonomy: false,
    simTime: 12.3,
    skill: { name: 'engage', target: null, evasion: 'dodge' },
    activity: '표적 드론 1 겨누는 중 (170 m, 어긋남 0.8°)',
    target: 'drone-1',
    reflex: null,
    metrics: { tickMicrosAvg: 15, tickMicrosMax: 80, commandsPerSecond: 3, lastReactionMs: 17, shots: 4, hits: 3, kills: 1, damageTaken: 40 },
    plan: null,
    planner: { model: 'qwen2.5:7b', available: true },
    trials: null,
    ...overrides,
  }
}

/** 언어 모델이 짠 두 단계 계획의 첫 단계를 하는 중 */
export function planStatus(overrides: Partial<PlanStatus> = {}): PlanStatus {
  return {
    order: '드론 2부터 잡고 나머지도 정리해',
    source: 'llm',
    state: 'running',
    say: '표적 드론 2를 먼저 잡고 나머지도 격파하겠습니다.',
    steps: [
      { skill: 'engage', target: 'drone-2', evasion: 'dodge', until: 'targetDestroyed', value: 0, state: 'running' },
      { skill: 'engage', target: null, evasion: 'dodge', until: 'allDestroyed', value: 0, state: 'waiting' },
    ],
    current: 0,
    retreatBelowHp: 0.3,
    attempts: 1,
    timing: { firstTokenMs: 120, firstStepMs: 1480, totalMs: 3020 },
    error: null,
    ...overrides,
  }
}

export function runResult(overrides: Partial<RunResult> = {}): RunResult {
  return {
    run: 1,
    outcome: 'cleared',
    startDelayS: 0,
    durationS: 25.7,
    clearTimeS: 25.7,
    drones: 3,
    kills: 3,
    damageTaken: 40,
    shots: 6,
    hits: 6,
    reactionMs: 18,
    planFirstStepMs: null,
    planTotalMs: null,
    planAttempts: null,
    score: 84.3,
    ...overrides,
  }
}

/** 반격하는 드론 장면에서 피하기·막기를 2판씩 견준 시험 (다 돌림) */
export function trialSeries(overrides: Partial<TrialSeries> = {}): TrialSeries {
  const stat = (median: number, min = median, max = median) => ({ median, min, max, mean: (min + max) / 2 })
  return {
    state: 'done',
    scenario: 'skirmish',
    runs: 2,
    timeLimitS: 60,
    startSpreadS: 4,
    startedAt: '2026-11-06T12:00:00.000Z',
    finishedAt: '2026-11-06T12:02:10.000Z',
    setups: [
      {
        setup: { kind: 'skill', skill: 'engage', evasion: 'dodge' },
        label: '교전 · 피하기',
        results: [runResult(), runResult({ run: 2, clearTimeS: 35.2, durationS: 35.2, damageTaken: 80, score: 77.3 })],
        summary: { runs: 2, cleared: 2, score: stat(80.8, 77.3, 84.3), clearTimeS: stat(30.5, 25.7, 35.2), damageTaken: stat(60, 40, 80), accuracy: 1, reactionMs: stat(18), planFirstStepMs: null },
      },
      {
        setup: { kind: 'skill', skill: 'engage', evasion: 'guard' },
        label: '교전 · 방패로 막기',
        results: [
          runResult({ clearTimeS: 20.6, durationS: 20.6, damageTaken: 160, score: 87.4 }),
          runResult({ run: 2, outcome: 'timeout', clearTimeS: null, durationS: 60, kills: 2, damageTaken: 200, shots: 5, hits: 4, score: 53.3 }),
        ],
        summary: { runs: 2, cleared: 1, score: stat(70.4, 53.3, 87.4), clearTimeS: stat(20.6), damageTaken: stat(180, 160, 200), accuracy: 10 / 11, reactionMs: stat(18), planFirstStepMs: null },
      },
    ],
    current: null,
    error: null,
    savedTo: 'results/trials/2026-11-06T12-00-00-skirmish.json',
    ...overrides,
  }
}
