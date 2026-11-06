import { describe, expect, it } from 'vitest'
import { PlanStreamReader, type StreamPiece } from './planStream'

const STEP_1 = { skill: 'engage', target: 'drone-2', evasion: 'guard', until: 'targetDestroyed', value: 0 }
const STEP_2 = { skill: 'hold', target: null, evasion: 'dodge', until: 'never', value: 0 }
const PLAN = { say: '드론 2부터 {잡고}, "나머지"도 \\ 정리합니다.', retreatBelowHp: 0.3, steps: [STEP_1, STEP_2] }
const EXPECTED: StreamPiece[] = [
  { kind: 'field', key: 'say', value: PLAN.say },
  { kind: 'field', key: 'retreatBelowHp', value: 0.3 },
  { kind: 'step', value: STEP_1 },
  { kind: 'step', value: STEP_2 },
]

function readAll(text: string, chunkSize: number): StreamPiece[] {
  const reader = new PlanStreamReader()
  const pieces: StreamPiece[] = []
  for (let index = 0; index < text.length; index += chunkSize) {
    pieces.push(...reader.push(text.slice(index, index + chunkSize)))
  }
  return pieces
}

describe('PlanStreamReader', () => {
  it.each([1, 2, 3, 7, 1000])('조각이 %s글자씩 와도 say·retreatBelowHp·단계를 차례로 꺼낸다', (chunkSize) => {
    expect(readAll(JSON.stringify(PLAN), chunkSize)).toEqual(EXPECTED)
  })

  it('줄을 바꿔 보기 좋게 쓴 JSON도 읽는다', () => {
    expect(readAll(JSON.stringify(PLAN, null, 2), 5)).toEqual(EXPECTED)
  })

  it('단계는 그 단계의 닫는 괄호가 오자마자 꺼낸다 (계획을 다 받기 전에)', () => {
    const text = JSON.stringify(PLAN)
    const firstStep = JSON.stringify(STEP_1)
    const firstStepEnd = text.indexOf(firstStep) + firstStep.length
    const reader = new PlanStreamReader()

    const before = reader.push(text.slice(0, firstStepEnd - 1))
    const atEnd = reader.push(text.slice(firstStepEnd - 1, firstStepEnd))

    expect(before.filter((piece) => piece.kind === 'step')).toEqual([])
    expect(atEnd).toEqual([{ kind: 'step', value: STEP_1 }])
  })

  it('순서가 뒤바뀌어도(단계가 먼저) 맨 위 값과 단계를 모두 꺼낸다', () => {
    const text = JSON.stringify({ steps: [STEP_1], say: '교전합니다.', retreatBelowHp: 0 })

    expect(readAll(text, 4)).toEqual([
      { kind: 'step', value: STEP_1 },
      { kind: 'field', key: 'say', value: '교전합니다.' },
      { kind: 'field', key: 'retreatBelowHp', value: 0 },
    ])
  })

  it('실패: 읽을 수 없는 값은 undefined로 꺼낸다 (확인하는 쪽이 거절한다)', () => {
    const pieces = readAll('{"say": 오류, "steps": [{"skill": engage}]}', 3)

    expect(pieces).toEqual([
      { kind: 'field', key: 'say', value: undefined },
      { kind: 'step', value: undefined },
    ])
  })

  it('끝나지 않은 단계는 꺼내지 않는다', () => {
    expect(readAll('{"say":"a","retreatBelowHp":0,"steps":[{"skill":"engage"', 4)).toEqual([
      { kind: 'field', key: 'say', value: 'a' },
      { kind: 'field', key: 'retreatBelowHp', value: 0 },
    ])
  })
})
