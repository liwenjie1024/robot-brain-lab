import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import type { BrainStatus, PlanStatus } from '@shared/brain/generated/status'
import { brainStatus, NAMES, planStatus } from '@shared/test/fixtures'
import OrderPanel from './OrderPanel.vue'

function panel(props: Partial<{ phase: 'connecting' | 'open' | 'offline'; status: BrainStatus | null; error: string | null }> = {}) {
  return mount(OrderPanel, { props: { phase: 'open', status: brainStatus(), error: null, names: NAMES, ...props } })
}

const withPlan = (overrides: Partial<PlanStatus> = {}) => brainStatus({ plan: planStatus(overrides) })

describe('OrderPanel', () => {
  it('두뇌가 꺼져 있으면 명령 칸 대신 까닭을 알린다', () => {
    const wrapper = panel({ phase: 'offline', status: null })

    expect(wrapper.find('[data-test="order-offline"]').exists()).toBe(true)
    expect(wrapper.find('[data-test="order-input"]').exists()).toBe(false)
  })

  it('두뇌의 상태를 받기 전에는 기다린다고 알린다', () => {
    expect(panel({ status: null }).text()).toContain('두뇌의 상태를 기다리는 중입니다')
  })

  it('계획이 없으면 빈 상태를 알린다', () => {
    expect(panel().get('[data-test="plan-empty"]').text()).toContain('아직 명령이 없습니다')
  })

  it('쓴 명령을 앞뒤 띄어쓰기를 떼어 내고, 칸을 비운다', async () => {
    const wrapper = panel()
    const input = wrapper.get('[data-test="order-input"] input')

    await input.setValue('  드론 2부터 잡아  ')
    await wrapper.get('form').trigger('submit')

    expect(wrapper.emitted('order')).toEqual([['드론 2부터 잡아']])
    expect((input.element as HTMLInputElement).value).toBe('')
  })

  it('경계값: 빈 명령이나 띄어쓰기뿐인 명령은 보내지 않는다', async () => {
    const wrapper = panel()

    await wrapper.get('[data-test="order-input"] input').setValue('   ')
    await wrapper.get('form').trigger('submit')

    expect(wrapper.emitted('order')).toBeUndefined()
    expect(wrapper.get('[data-test="order-send"]').attributes('disabled')).toBeDefined()
  })

  it('경계값: 명령 칸은 규약의 200자까지만 받는다', () => {
    expect(panel().get('[data-test="order-input"] input').attributes('maxlength')).toBe('200')
  })

  it('"바로 하기" 짧은 명령은 누르면 바로 보낸다', async () => {
    const wrapper = panel()

    await wrapper.get('[data-test="quick-물러나"]').trigger('click')

    expect(wrapper.emitted('order')).toEqual([['물러나']])
  })

  it('계획의 상태·출처·말·단계별 진행·물러날 체력·걸린 시간을 보여 준다', () => {
    const wrapper = panel({ status: withPlan() })

    expect(wrapper.get('[data-test="plan-state"]').text()).toBe('따르는 중')
    expect(wrapper.get('[data-test="plan-source"]').text()).toBe('언어 모델')
    expect(wrapper.get('[data-test="plan-say"]').text()).toContain('표적 드론 2를 먼저 잡고')
    const steps = wrapper.findAll('[data-test="plan-steps"] li').map((item) => item.text())
    expect(steps[0]).toContain('▶ 하는 중')
    expect(steps[0]).toContain('1. 교전 (표적 드론 2) · 표적 드론 2을(를) 격파할 때까지')
    expect(steps[0]).toContain('경고에 피하기')
    expect(steps[1]).toContain('· 기다림')
    expect(wrapper.get('[data-test="plan-retreat"]').text()).toContain('30% 아래')
    expect(wrapper.get('[data-test="plan-timing"]').text()).toBe('첫 글자 0.1초 · 첫 단계 시작 1.5초 · 계획 전체 3.0초 · 언어 모델에 1번 물음')
  })

  it('짜는 중에는 아직 받지 못한 시간을 "받는 중"으로 알리고, 그만두기를 누를 수 있다', async () => {
    const wrapper = panel({
      status: withPlan({ state: 'thinking', say: '명령을 생각하는 중…', steps: [], current: null, timing: { firstTokenMs: null, firstStepMs: null, totalMs: null } }),
    })

    expect(wrapper.get('[data-test="plan-state"]').text()).toBe('짜는 중')
    expect(wrapper.get('[data-test="plan-timing"]').text()).toBe('계획을 받는 중 · 언어 모델에 1번 물음')
    await wrapper.get('[data-test="plan-cancel"]').trigger('click')
    expect(wrapper.emitted('cancelPlan')).toHaveLength(1)
  })

  it('짧은 명령·기억한 계획은 언어 모델에 묻지 않았다고 알린다', () => {
    const wrapper = panel({ status: withPlan({ source: 'cache', attempts: 0 }) })

    expect(wrapper.get('[data-test="plan-source"]').text()).toBe('기억한 계획')
    expect(wrapper.get('[data-test="plan-timing"]').text()).toBe('언어 모델에 묻지 않고 바로 따릅니다')
  })

  it.each([
    ['done', '마침'],
    ['cancelled', '그만둠'],
    ['retreating', '물러나는 중'],
  ] as const)('끝난 계획(%s)은 상태를 글로 알리고 그만두기 버튼을 감춘다', (state, label) => {
    const wrapper = panel({ status: withPlan({ state }) })

    expect(wrapper.get('[data-test="plan-state"]').text()).toBe(label)
    expect(wrapper.find('[data-test="plan-cancel"]').exists()).toBe(false)
  })

  it('실패: 계획이 실패하면 까닭과 "같은 명령 다시 하기"를 보여 준다', async () => {
    const wrapper = panel({ status: withPlan({ state: 'failed', error: '언어 모델이 30초 안에 답하지 않음' }) })

    expect(wrapper.get('[data-test="plan-error"]').text()).toContain('30초 안에 답하지 않음')
    await wrapper.get('[data-test="plan-retry"]').trigger('click')

    expect(wrapper.emitted('order')).toEqual([['드론 2부터 잡고 나머지도 정리해']])
  })

  it('실패: 두뇌가 명령을 받지 않으면 까닭을 보여 준다', () => {
    expect(panel({ error: '명령이 비어 있습니다' }).get('[data-test="order-error"]').text()).toBe('명령이 비어 있습니다')
  })

  it('언어 모델을 쓸 수 없으면 짧은 명령만 알아듣는다고 글과 색으로 알린다', () => {
    const wrapper = panel({ status: brainStatus({ planner: { model: 'qwen2.5:7b', available: false } }) })

    expect(wrapper.get('[data-test="planner"]').text()).toBe('짧은 명령만')
    expect(wrapper.get('[data-test="planner-off"]').text()).toContain('언어 모델(qwen2.5:7b)을 쓸 수 없어')
  })
})
