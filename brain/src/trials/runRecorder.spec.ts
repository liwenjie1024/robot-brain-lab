import { describe, expect, it } from 'vitest'
import { drone, mechaStatus, planStatus, stateMessage } from '@shared/test/fixtures'
import { RunRecorder } from './runRecorder'

const DRONES = [drone({ id: 'drone-1' }), drone({ id: 'drone-2' }), drone({ id: 'drone-3' })]
const START = stateMessage({ simTime: 0.02, units: DRONES, mecha: mechaStatus({ hp: 1000 }) })

const at = (simTime: number, overrides: { hp?: number; dead?: number; destroyed?: boolean } = {}) =>
  stateMessage({
    simTime,
    units: DRONES.map((unit, index) => ({ ...unit, alive: index >= (overrides.dead ?? 0) })),
    mecha: mechaStatus({ hp: overrides.hp ?? 1000, mode: overrides.destroyed ? 'destroyed' : 'flying' }),
  })

const NO_EXTRAS = { startDelayS: 0, reactionMs: 18, plan: null }

describe('RunRecorder', () => {
  it('드론을 다 격파하면 그때까지의 시간·받은 피해·쏜 수·맞힌 수로 결과와 점수를 낸다', () => {
    const recorder = new RunRecorder(START, 60)
    recorder.onCombat({ type: 'shot', simTime: 3, shooter: 'mecha', from: [0, 0, 0], to: [1, 0, 0], hit: { unit: 'drone-1', damage: 30, blocked: false } })
    recorder.onCombat({ type: 'shot', simTime: 4, shooter: 'mecha', from: [0, 0, 0], to: [1, 0, 0] })
    recorder.onCombat({ type: 'shot', simTime: 5, shooter: 'drone-2', from: [0, 0, 0], to: [1, 0, 0], hit: { unit: 'mecha', damage: 40, blocked: false } })

    expect(recorder.update(at(10, { dead: 2, hp: 960 }))).toBeNull()
    expect(recorder.update(at(30.02, { dead: 3, hp: 960 }))).toBe('cleared')

    expect(recorder.result(1, 'cleared', NO_EXTRAS)).toEqual({
      run: 1,
      outcome: 'cleared',
      startDelayS: 0,
      durationS: 30,
      clearTimeS: 30,
      drones: 3,
      kills: 3,
      damageTaken: 40,
      shots: 2,
      hits: 1,
      reactionMs: 18,
      planFirstStepMs: null,
      planTotalMs: null,
      planAttempts: null,
      score: 50 + 12.5 + 24,
    })
  })

  it('기체가 파괴되면 그 판은 파괴로 끝나고, 격파한 수만큼만 점수를 받는다', () => {
    const recorder = new RunRecorder(START, 60)

    expect(recorder.update(at(20, { dead: 1, hp: 0, destroyed: true }))).toBe('destroyed')
    expect(recorder.result(1, 'destroyed', NO_EXTRAS)).toMatchObject({ clearTimeS: null, kills: 1, damageTaken: 1000, score: 16.7 })
  })

  it('경계값: 제한 시간이 되는 상태에서 끝나고, 바로 앞 상태에서는 끝나지 않는다', () => {
    const recorder = new RunRecorder(START, 60)

    expect(recorder.update(at(60))).toBeNull()
    expect(recorder.update(at(60.02))).toBe('timeout')
  })

  it('같은 상태에서 다 격파와 파괴가 함께 일어나면 다 격파로 본다', () => {
    expect(new RunRecorder(START, 60).update(at(15, { dead: 3, hp: 0, destroyed: true }))).toBe('cleared')
  })

  it('말로 한 명령의 판은 계획의 첫 단계·전체 시간과 물은 횟수를 남긴다', () => {
    const recorder = new RunRecorder(START, 60)
    recorder.update(at(25, { dead: 3 }))

    expect(recorder.result(2, 'cleared', { startDelayS: 1.6, reactionMs: null, plan: planStatus() })).toMatchObject({
      run: 2,
      startDelayS: 1.6,
      planFirstStepMs: 1480,
      planTotalMs: 3020,
      planAttempts: 1,
    })
  })

  it('체력이 오히려 늘어도 받은 피해는 0 아래로 내려가지 않는다', () => {
    const recorder = new RunRecorder(stateMessage({ simTime: 0.02, units: DRONES, mecha: mechaStatus({ hp: 900 }) }), 60)
    recorder.update(at(5, { hp: 1000 }))

    expect(recorder.result(1, 'timeout', NO_EXTRAS).damageTaken).toBe(0)
  })
})
