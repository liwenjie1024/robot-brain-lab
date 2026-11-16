import { describe, expect, it } from 'vitest'
import { changedUrgently, shouldShow, SHOW_EVERY_MS } from '@/sim/display'
import { novaState } from '@/test/samples'
import type { State } from '@/generated/message'

const pushing = { force_n: [30, 0, 0] as [number, number, number], remaining_s: 0.3 }

describe('画面上的数多久换一次', () => {
  it('第一条状态马上显示', () => {
    expect(changedUrgently(null, novaState())).toBe(true)
    expect(shouldShow(null, novaState(), 0, 0)).toBe(true)
  })

  it('只是数变了：不急，等 0.1 秒', () => {
    const shown = novaState()
    const next = { ...novaState(), time_s: shown.time_s + 0.03, tilt_deg: 0.2 }
    expect(changedUrgently(shown, next)).toBe(false)
    expect(shouldShow(shown, next, 1000, 1000 + SHOW_EVERY_MS - 1)).toBe(false)
    expect(shouldShow(shown, next, 1000, 1000 + SHOW_EVERY_MS)).toBe(true)
  })

  it.each<[string, Partial<State>]>([
    ['倒了', { fallen: true }],
    ['暂停了', { running: false }],
    ['松开了', { controlled: false }],
    ['出了问题', { problem: '仿真里的数坏了' }],
    ['重新开始了（新的一回）', { episode: 99 }],
    ['换了身体', { body: 'g1' }],
    ['开始推了', { push: pushing }],
  ])('%s：马上显示，不等', (_name, change) => {
    const shown = novaState()
    const next = { ...novaState(), ...change }
    expect(changedUrgently(shown, next)).toBe(true)
    expect(shouldShow(shown, next, 1000, 1001)).toBe(true)
  })

  it('推完了也马上显示；还在推的时候只是剩下的时间变了，不急', () => {
    const during = { ...novaState(), push: pushing }
    expect(changedUrgently(during, novaState())).toBe(true)
    expect(changedUrgently(during, { ...during, push: { ...pushing, remaining_s: 0.1 } })).toBe(false)
  })
})
