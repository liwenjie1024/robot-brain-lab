import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import type { BrainStatus, Decision } from '@shared/brain/generated/status'
import { brainStatus, drone } from '@shared/test/fixtures'
import BrainPanel from './BrainPanel.vue'

function panel(props: Partial<{ phase: 'connecting' | 'open' | 'offline'; status: BrainStatus | null; decisions: Decision[]; lastError: string | null }> = {}) {
  return mount(BrainPanel, {
    props: { phase: 'open', status: brainStatus(), decisions: [], lastError: null, units: [drone(), drone({ id: 'drone-2', name: '표적 드론 2' })], ...props },
  })
}

describe('BrainPanel', () => {
  it('두뇌가 꺼져 있으면 띄우는 방법과 다시 연결 버튼을 보여 준다', async () => {
    const wrapper = panel({ phase: 'offline', status: null })

    expect(wrapper.get('[data-test="brain-phase"]').text()).toBe('두뇌 꺼짐')
    expect(wrapper.get('[data-test="brain-offline"]').text()).toContain('npm run brain')
    await wrapper.get('[data-test="brain-retry"]').trigger('click')
    expect(wrapper.emitted('retry')).toHaveLength(1)
  })

  it('지금 하는 일과 지표(판단 시간·반응 시간·명중률)를 보여 준다', () => {
    const wrapper = panel()

    expect(wrapper.get('[data-test="activity"]').text()).toContain('표적 드론 1 겨누는 중')
    const metrics = wrapper.get('[data-test="metrics"]').text()
    expect(metrics).toContain('평균 15µs')
    expect(metrics).toContain('17ms')
    expect(metrics).toContain('4번 · 맞힘 3 (75%) · 격파 1')
  })

  it('기술 버튼은 고른 표적·반응과 함께 낸다 (표적을 고르지 않으면 두뇌가 고름)', async () => {
    const wrapper = panel()

    await wrapper.get('[data-test="evasion-guard"] input').setValue(true)
    await wrapper.get('[data-test="skill-engage"]').trigger('click')

    expect(wrapper.emitted('setSkill')).toEqual([['engage', null, 'guard']])
  })

  it('조종 맡기기 스위치를 켜고 끈다', async () => {
    const wrapper = panel()

    await wrapper.get('[data-test="autonomy"]').trigger('click')

    expect(wrapper.emitted('setAutonomy')).toEqual([[true]])
  })

  it('실패: 두뇌가 지시를 거절하면 까닭을 보여 준다', () => {
    expect(panel({ lastError: '그런 표적이 없습니다: drone-9' }).get('[data-test="brain-error"]').text()).toContain('drone-9')
  })

  it('판단 기록을 종류와 함께 보여 주고, 없으면 빈 상태를 알린다', () => {
    const decisions: Decision[] = [{ type: 'decision', seq: 2, simTime: 4.2, kind: 'reflex', text: '표적 드론 2이(가) 조준함 → 피하기' }]

    expect(panel({ decisions }).get('[data-test="decisions"]').text()).toContain('반사')
    expect(panel().text()).toContain('아직 판단 기록이 없습니다')
  })
})
