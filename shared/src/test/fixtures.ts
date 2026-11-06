import type { BrainStatus, PlanStatus } from '../brain/generated/status'
import type { MechaStatus, StateMessage, UnitStatus } from '../sim/generated/message'
import type { Limits } from '../sim/generated/scene'

/** 시험에서 함께 쓰는 값. 몸이 실제로 알리는 값과 같게 둔다 (sim/robot_sim/limits.py). */
export const LIMITS: Limits = {
  forward: { min: -15, max: 40 },
  sideways: { min: -20, max: 20 },
  up: { min: -15, max: 20 },
  turn: { min: -1.2, max: 1.2 },
  pushForce: { min: 0, max: 3_000_000 },
  pushDurationMs: { min: 10, max: 1000 },
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
