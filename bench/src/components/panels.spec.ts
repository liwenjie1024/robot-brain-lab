import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import type { StateMessage } from '@/sim/generated/message'
import type { Limits } from '@/sim/generated/scene'
import CommandLog from './CommandLog.vue'
import ControlPanel from './ControlPanel.vue'
import StatusPanel from './StatusPanel.vue'

const LIMITS: Limits = {
  forward: { min: -0.5, max: 1.0 },
  sideways: { min: -0.5, max: 0.5 },
  turn: { min: -1.0, max: 1.0 },
  pushForce: { min: 0, max: 400 },
  pushDurationMs: { min: 10, max: 1000 },
}

function stateWith(posture: 'standing' | 'fallen', pushing = false): StateMessage {
  return {
    type: 'state',
    seq: 1,
    simTime: 12.34,
    bodies: [],
    robot: {
      position: [1.25, -0.5, posture === 'fallen' ? 0.19 : 0.78],
      yaw: Math.PI / 2,
      velocity: { forward: 0.48, sideways: 0.01, turn: 0 },
      command: { forward: 0.5, sideways: 0, turn: 0 },
      posture,
      pushing,
    },
  }
}

function controlPanel(props: Partial<{ disabledReason: string | null; fallen: boolean }> = {}) {
  return mount(ControlPanel, {
    props: { limits: LIMITS, yaw: 0, disabledReason: null, fallen: false, ...props },
    attachTo: document.body,
  })
}

describe('StatusPanel', () => {
  it('서 있으면 "서 있음"을 글자로 보여 주고 명령한 속도와 실제 속도를 나란히 보여 준다', () => {
    const wrapper = mount(StatusPanel, { props: { state: stateWith('standing'), stale: false } })

    expect(wrapper.get('[data-test="posture"]').text()).toBe('서 있음')
    expect(wrapper.get('[data-test="speeds"]').text()).toContain('0.50 m/s')
    expect(wrapper.get('[data-test="speeds"]').text()).toContain('0.48 m/s')
    expect(wrapper.text()).toContain('90°')
  })

  it('넘어지면 "넘어짐"으로 바뀐다', () => {
    const wrapper = mount(StatusPanel, { props: { state: stateWith('fallen'), stale: false } })

    expect(wrapper.get('[data-test="posture"]').text()).toBe('넘어짐')
    expect(wrapper.text()).toContain('골반 높이 0.19 m')
  })

  it('밀고 있으면 알린다', () => {
    const wrapper = mount(StatusPanel, { props: { state: stateWith('standing', true), stale: false } })

    expect(wrapper.find('[data-test="pushing"]').exists()).toBe(true)
  })

  it('연결이 끊긴 동안에는 마지막으로 받은 상태라고 알린다', () => {
    const wrapper = mount(StatusPanel, { props: { state: stateWith('standing'), stale: true } })

    expect(wrapper.get('[data-test="stale"]').text()).toContain('마지막으로 받은 상태')
  })

  it('빈 상태: 아직 상태를 받지 못했으면 그렇게 알린다', () => {
    const wrapper = mount(StatusPanel, { props: { state: null, stale: false } })

    expect(wrapper.text()).toContain('아직 상태를 받지 못했습니다')
  })
})

describe('ControlPanel', () => {
  it('앞으로를 누르면 걷기 빠르기로 앞으로 가는 명령을 낸다', async () => {
    const wrapper = controlPanel()

    await wrapper.get('[data-test="drive-forward"]').trigger('click')

    expect(wrapper.emitted('drive')).toEqual([['앞으로', { forward: 0.5, sideways: 0, turn: 0 }]])
    wrapper.unmount()
  })

  it('키보드 W로도 앞으로 간다', async () => {
    const wrapper = controlPanel()

    window.dispatchEvent(new KeyboardEvent('keydown', { code: 'KeyW' }))

    expect(wrapper.emitted('drive')?.[0]?.[0]).toBe('앞으로')
    wrapper.unmount()
  })

  it('실패: 연결이 없으면 까닭을 보여 주고 버튼·키보드로 명령을 내지 않는다', async () => {
    const wrapper = controlPanel({ disabledReason: '몸과 연결되어야 합니다' })

    await wrapper.get('[data-test="drive-forward"]').trigger('click')
    window.dispatchEvent(new KeyboardEvent('keydown', { code: 'KeyW' }))

    expect(wrapper.text()).toContain('몸과 연결되어야 합니다')
    expect(wrapper.emitted('drive')).toBeUndefined()
    wrapper.unmount()
  })

  it('넘어졌으면 다시 세우는 방법을 알린다', () => {
    const wrapper = controlPanel({ fallen: true })

    expect(wrapper.get('[data-test="fallen-notice"]').text()).toContain('처음 자세로')
    wrapper.unmount()
  })

  it('밀기는 로봇 기준 방향의 힘과 시간을 낸다', async () => {
    const wrapper = controlPanel()

    await wrapper.get('[data-test="push-left"]').trigger('click')

    expect(wrapper.emitted('push')).toEqual([['왼쪽에서 밀기 150N', [0, -150, 0], 100]])
    wrapper.unmount()
  })

  it('처음 자세로를 누르면 되돌리기를 낸다', async () => {
    const wrapper = controlPanel()

    await wrapper.get('[data-test="reset"]').trigger('click')

    expect(wrapper.emitted('reset')).toHaveLength(1)
    wrapper.unmount()
  })
})

describe('CommandLog', () => {
  it('빈 상태: 보낸 명령이 없으면 그렇게 알린다', () => {
    expect(mount(CommandLog, { props: { entries: [] } }).text()).toContain('아직 보낸 명령이 없습니다')
  })

  it('받은 명령은 걸린 시간을, 거절된 명령은 까닭을 보여 준다', () => {
    const wrapper = mount(CommandLog, {
      props: {
        entries: [
          { label: '앞으로', at: new Date(), result: { id: 'a', accepted: true, roundTripMs: 23.4 } },
          { label: '밀기', at: new Date(), result: { id: 'b', accepted: false, reason: '미는 힘이 범위를 벗어났습니다', roundTripMs: 9 } },
        ],
      },
    })

    const text = wrapper.get('[data-test="command-log"]').text()
    expect(text).toContain('받음 · 23ms')
    expect(text).toContain('거절')
    expect(text).toContain('미는 힘이 범위를 벗어났습니다')
  })
})
