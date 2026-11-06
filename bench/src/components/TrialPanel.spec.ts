import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import type { BrainStatus, TrialSeries } from '@shared/brain/generated/status'
import { brainStatus, runResult, SCENARIOS, trialSeries } from '@shared/test/fixtures'
import TrialPanel from './TrialPanel.vue'

function panel(props: Partial<{ phase: 'connecting' | 'open' | 'offline'; status: BrainStatus | null; error: string | null }> = {}) {
  return mount(TrialPanel, { props: { phase: 'open', status: brainStatus(), scenarios: SCENARIOS, error: null, ...props } })
}

const withTrials = (overrides: Partial<TrialSeries> = {}) => brainStatus({ trials: trialSeries(overrides) })

describe('TrialPanel', () => {
  it('두뇌가 꺼져 있으면 시험 대신 까닭을 알린다', () => {
    const wrapper = panel({ phase: 'offline', status: null })

    expect(wrapper.find('[data-test="trial-offline"]').exists()).toBe(true)
    expect(wrapper.find('[data-test="trial-form"]').exists()).toBe(false)
  })

  it('빈 상태: 시험한 적이 없으면 그렇게 알린다', () => {
    expect(panel().get('[data-test="trial-empty"]').text()).toContain('아직 시험 결과가 없습니다')
  })

  it('드론이 있는 장면만 고를 수 있고, 반격하는 장면을 먼저 고른다', () => {
    const wrapper = panel()

    expect(wrapper.get('[data-test="trial-scenario"]').text()).toContain('반격하는 드론 (드론 3대, 모두 반격)')
    expect(wrapper.text()).not.toContain('빈 시험장')
  })

  it('처음에는 조준 경고 반응 네 가지를 3판씩 견주고, 얼마나 걸릴지 알린다', () => {
    expect(panel().get('[data-test="trial-estimate"]').text()).toBe('모두 12판, 길어야 약 14분 걸립니다.')
  })

  it('시작은 무슨 일이 일어나는지 확인한 뒤에만 보내고, 그만두면 보내지 않는다', async () => {
    const wrapper = panel()

    await wrapper.get('[data-test="trial-start"]').trigger('click')
    expect(wrapper.get('[data-test="trial-confirm"]').text()).toContain('장면을 12번 처음으로 되돌리고')
    expect(wrapper.emitted('start')).toBeUndefined()
    await wrapper.get('[data-test="trial-confirm-cancel"]').trigger('click')
    expect(wrapper.find('[data-test="trial-confirm"]').exists()).toBe(false)
    await wrapper.get('[data-test="trial-start"]').trigger('click')
    await wrapper.get('[data-test="trial-confirm-start"]').trigger('click')

    expect(wrapper.emitted('start')).toEqual([
      [
        {
          scenario: 'skirmish',
          setups: ['none', 'dodge', 'guard', 'both'].map((evasion) => ({ kind: 'skill', skill: 'engage', evasion })),
          runs: 3,
          timeLimitS: 60,
          startSpreadS: 4,
        },
      ],
    ])
  })

  it('말로 한 명령을 넣어 함께 견주고, 같은 명령은 두 번 넣지 않는다', async () => {
    const wrapper = panel()
    const input = wrapper.get('[data-test="trial-order-input"] input')

    for (const text of ['공격', ' 공격 ']) {
      await input.setValue(text)
      await wrapper.get('[data-test="trial-order-add"]').trigger('submit')
    }
    await wrapper.get('[data-test="trial-start"]').trigger('click')
    await wrapper.get('[data-test="trial-confirm-start"]').trigger('click')

    const spec = wrapper.emitted('start')?.[0]?.[0] as { setups: unknown[] }
    expect(spec.setups).toHaveLength(5)
    expect(spec.setups.at(-1)).toEqual({ kind: 'order', text: '공격' })
  })

  it('경계값: 견줄 것을 하나도 고르지 않거나 6가지를 넘으면 시작할 수 없고 까닭을 보인다', async () => {
    const wrapper = panel()
    for (const evasion of ['none', 'dodge', 'guard', 'both']) {
      await wrapper.get(`[data-test="trial-evasion-${evasion}"]`).trigger('click')
    }
    expect(wrapper.get('[data-test="trial-problem"]').text()).toBe('비교할 것을 하나 넘게 고르세요')
    expect(wrapper.get('[data-test="trial-start"]').attributes('disabled')).toBeDefined()

    for (const evasion of ['none', 'dodge', 'guard', 'both']) {
      await wrapper.get(`[data-test="trial-evasion-${evasion}"]`).trigger('click')
    }
    const input = wrapper.get('[data-test="trial-order-input"] input')
    for (const text of ['공격', '물러나', '자리 지켜']) {
      await input.setValue(text)
      await wrapper.get('[data-test="trial-order-add"]').trigger('submit')
    }

    expect(wrapper.get('[data-test="trial-problem"]').text()).toBe('비교할 것은 6가지까지입니다 (지금 7가지)')
    expect(wrapper.get('[data-test="trial-start"]').attributes('disabled')).toBeDefined()
  })

  it('시험 중에는 고르는 칸 대신 진행과 멈추기 버튼을 보인다', async () => {
    const wrapper = panel({ status: withTrials({ state: 'running', current: { setup: 1, run: 2, phase: 'running', startDelayS: 2, elapsedS: 12.34 }, finishedAt: null }) })

    expect(wrapper.find('[data-test="trial-form"]').exists()).toBe(false)
    expect(wrapper.get('[data-test="trial-progress"]').text()).toContain('4판 가운데 5판째 · 교전 · 방패로 막기 (2판째) · 12.3초 지남')
    expect(wrapper.get('[data-test="trial-state"]').text()).toBe('시험 중')
    await wrapper.get('[data-test="trial-stop"]').trigger('click')

    expect(wrapper.emitted('stop')).toHaveLength(1)
  })

  it('두뇌가 맡기를 기다리는 동안에는 몇 초 늦추는지 알린다', () => {
    const wrapper = panel({ status: withTrials({ state: 'running', current: { setup: 0, run: 2, phase: 'waiting', startDelayS: 2, elapsedS: 0 } }) })

    expect(wrapper.get('[data-test="trial-progress"]').text()).toContain('두뇌가 맡기를 기다리는 중 (2초 늦춤)')
  })

  it('장면을 되돌리는 동안에는 그렇다고 알린다', () => {
    const wrapper = panel({ status: withTrials({ state: 'running', current: { setup: 0, run: 1, phase: 'resetting', startDelayS: 0, elapsedS: 0 }, setups: [] }) })

    expect(wrapper.get('[data-test="trial-progress"]').text()).toContain('장면을 처음으로 되돌리는 중')
  })

  it('결과 표에 견준 것마다 가운데 값을 보이고, 칸마다 가장 좋은 것을 글로 표시한다', () => {
    const wrapper = panel({ status: withTrials() })
    const rows = wrapper.findAll('[data-test="trial-results"] tbody tr').map((row) => row.findAll('td').map((cell) => cell.text()))

    expect(rows[0]?.[0]).toBe('80.8 (77.3~84.3) ★ 가장 좋음')
    expect(rows[1]?.[0]).toBe('70.4 (53.3~87.4)')
    expect(rows[1]?.[2]).toBe('20.6초 (모두 20.6초) ★ 가장 좋음')
    expect(rows[0]?.[5]).toBe('18ms ★ 가장 좋음')
    expect(wrapper.get('[data-test="trial-runs-list"]').text()).toContain('시간 끝 · 2판: 2/3 격파 · 피해 200 · 53.3점')
    expect(panel({ status: withTrials({ setups: [{ ...trialSeries().setups[0]!, results: [runResult({ run: 2, startDelayS: 2 })] }] }) }).text()).toContain('2판 (2초 늦춤): 25.7초')
    expect(wrapper.get('[data-test="trial-saved"]').text()).toContain('results/trials/2026-11-06T12-00-00-skirmish.json')
  })

  it('실패: 시험이 실패하면 까닭과 "같은 시험 다시 시작"을 보이고, 누르면 같은 설정으로 다시 시작한다', async () => {
    const wrapper = panel({ status: withTrials({ state: 'failed', error: '몸(시뮬레이터)과 연결이 끊겼습니다' }) })

    expect(wrapper.get('[data-test="trial-failed"]').text()).toContain('몸(시뮬레이터)과 연결이 끊겼습니다')
    await wrapper.get('[data-test="trial-retry"]').trigger('click')

    expect(wrapper.emitted('start')).toEqual([
      [
        {
          scenario: 'skirmish',
          setups: [
            { kind: 'skill', skill: 'engage', evasion: 'dodge' },
            { kind: 'skill', skill: 'engage', evasion: 'guard' },
          ],
          runs: 2,
          timeLimitS: 60,
          startSpreadS: 4,
        },
      ],
    ])
  })

  it('실패: 두뇌가 시험 지시를 받지 않으면 까닭을 보인다', () => {
    expect(panel({ error: '시험 중에는 할 수 없습니다' }).get('[data-test="trial-error"]').text()).toBe('시험 중에는 할 수 없습니다')
  })
})
