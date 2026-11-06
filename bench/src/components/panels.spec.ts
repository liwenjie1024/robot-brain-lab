import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import { drone, LIMITS, mechaStatus, NAMES, stateMessage } from '@shared/test/fixtures'
import CombatLog from './CombatLog.vue'
import CommandLog from './CommandLog.vue'
import FlightPanel from './FlightPanel.vue'
import MechaPanel from './MechaPanel.vue'
import ScenarioPanel from './ScenarioPanel.vue'
import UnitsPanel from './UnitsPanel.vue'

function flightPanel(props: Partial<{ disabledReason: string | null; destroyed: boolean }> = {}) {
  return mount(FlightPanel, {
    props: { limits: LIMITS, heading: 0, disabledReason: null, destroyed: false, ...props },
    attachTo: document.body,
  })
}

describe('MechaPanel', () => {
  it('비행 모드를 글자로, 체력·에너지·소총·방패와 명령한/실제 속도를 보여 준다', () => {
    const wrapper = mount(MechaPanel, { props: { state: stateMessage(), names: NAMES, stale: false } })

    expect(wrapper.get('[data-test="mode"]').text()).toBe('비행 중')
    expect(wrapper.text()).toContain('체력 1000 / 1000')
    expect(wrapper.get('[data-test="weapon"]').text()).toBe('쏠 수 있음')
    expect(wrapper.get('[data-test="guard"]').text()).toBe('내림')
    expect(wrapper.get('[data-test="speeds"]').text()).toContain('20.0 m/s')
    expect(wrapper.get('[data-test="speeds"]').text()).toContain('19.6 m/s')
  })

  it('조준당하면 누가 몇 초 뒤 쏘는지 경고한다', () => {
    const state = stateMessage({ threats: [{ from: 'drone-2', secondsToFire: 0.6 }] })

    const wrapper = mount(MechaPanel, { props: { state, names: NAMES, stale: false } })

    expect(wrapper.get('[data-test="threat"]').text()).toContain('표적 드론 2이(가) 조준 중 — 0.6초 뒤 사격')
  })

  it.each([
    [{ ready: false, cooldown: 0.3, aimTarget: null }, 100, '식는 중 (0.3초)'],
    [{ ready: false, cooldown: 0, aimTarget: null }, 10, '에너지 모자람'],
  ])('쏠 수 없으면 까닭을 보여 준다 (%#)', (weapon, energy, text) => {
    const state = stateMessage({ mecha: mechaStatus({ weapon, energy }) })

    expect(mount(MechaPanel, { props: { state, names: NAMES, stale: false } }).get('[data-test="weapon"]').text()).toBe(text)
  })

  it('겨누는 표적과 어긋난 각, 방패로 막는 쪽을 이름으로 보여 준다', () => {
    const mecha = mechaStatus({
      weapon: { ready: true, cooldown: 0, aimTarget: 'drone-1', aimError: 0.42 },
      guard: { raised: true, unit: 'drone-2' },
    })

    const wrapper = mount(MechaPanel, { props: { state: stateMessage({ mecha }), names: NAMES, stale: false } })

    expect(wrapper.text()).toContain('표적 드론 1 겨눔, 어긋남 0.4°')
    expect(wrapper.get('[data-test="guard"]').text()).toBe('올림 (표적 드론 2 쪽)')
  })

  it('파괴되면 "파괴됨"으로 바뀐다', () => {
    const state = stateMessage({ mecha: mechaStatus({ mode: 'destroyed', hp: 0 }) })

    expect(mount(MechaPanel, { props: { state, names: NAMES, stale: false } }).get('[data-test="mode"]').text()).toBe('파괴됨')
  })

  it('연결이 끊긴 동안에는 마지막으로 받은 상태라고 알린다', () => {
    const wrapper = mount(MechaPanel, { props: { state: stateMessage(), names: NAMES, stale: true } })

    expect(wrapper.get('[data-test="stale"]').text()).toContain('마지막으로 받은 상태')
  })

  it('빈 상태: 아직 상태를 받지 못했으면 그렇게 알린다', () => {
    expect(mount(MechaPanel, { props: { state: null, names: NAMES, stale: false } }).text()).toContain('아직 상태를 받지 못했습니다')
  })
})

describe('FlightPanel', () => {
  it('앞으로를 누르면 앞뒤 빠르기로 나는 명령을 낸다', async () => {
    const wrapper = flightPanel()

    await wrapper.get('[data-test="fly-forward"]').trigger('click')

    expect(wrapper.emitted('fly')).toEqual([['앞으로', { forward: 20, sideways: 0, up: 0, turn: 0 }]])
    wrapper.unmount()
  })

  it('옆으로는 앞뒤 빠르기의 절반으로 난다', async () => {
    const wrapper = flightPanel()

    await wrapper.get('[data-test="fly-strafeLeft"]').trigger('click')

    expect(wrapper.emitted('fly')?.[0]?.[1]).toEqual({ forward: 0, sideways: 10, up: 0, turn: 0 })
    wrapper.unmount()
  })

  it('키보드 R로 오르고 X로 쏜다', () => {
    const wrapper = flightPanel()

    window.dispatchEvent(new KeyboardEvent('keydown', { code: 'KeyR' }))
    window.dispatchEvent(new KeyboardEvent('keydown', { code: 'KeyX' }))

    expect(wrapper.emitted('fly')?.[0]?.[0]).toBe('위로')
    expect(wrapper.emitted('fire')).toHaveLength(1)
    wrapper.unmount()
  })

  it('실패: 연결이 없으면 까닭을 보여 주고 버튼·키보드로 명령을 내지 않는다', async () => {
    const wrapper = flightPanel({ disabledReason: '몸과 연결되어야 합니다' })

    await wrapper.get('[data-test="fly-forward"]').trigger('click')
    window.dispatchEvent(new KeyboardEvent('keydown', { code: 'KeyX' }))

    expect(wrapper.text()).toContain('몸과 연결되어야 합니다')
    expect(wrapper.emitted('fly')).toBeUndefined()
    expect(wrapper.emitted('fire')).toBeUndefined()
    wrapper.unmount()
  })

  it('이 칸이 보이지 않을 때(keyboard=false)는 키보드로 조종하지 않는다', () => {
    const wrapper = mount(FlightPanel, { props: { limits: LIMITS, heading: 0, disabledReason: null, destroyed: false, keyboard: false } })

    window.dispatchEvent(new KeyboardEvent('keydown', { code: 'KeyW' }))

    expect(wrapper.emitted('fly')).toBeUndefined()
    wrapper.unmount()
  })

  it('밀기는 기체 기준 방향의 힘(N)과 시간을 낸다', async () => {
    const wrapper = flightPanel()

    await wrapper.get('[data-test="push-left"]').trigger('click')

    expect(wrapper.emitted('push')).toEqual([['왼쪽에서 밀기 1000kN', [0, -1_000_000, 0], 200]])
    wrapper.unmount()
  })
})

describe('UnitsPanel', () => {
  it('드론마다 상태·체력·거리를 보여 주고, 겨누기·방패로 막기를 낸다', async () => {
    const wrapper = mount(UnitsPanel, { props: { state: stateMessage(), disabledReason: null } })

    expect(wrapper.get('[data-test="drones"]').text()).toContain('표적 드론 1')
    expect(wrapper.get('[data-test="drones"]').text()).toContain('체력 60')
    expect(wrapper.get('[data-test="drones"]').text()).toContain('150 m')
    expect(wrapper.get('[data-test="guard-drone-1"]').attributes('aria-label')).toBe('표적 드론 1 쪽으로 방패 들기')
    await wrapper.get('[data-test="aim-drone-1"]').trigger('click')
    await wrapper.get('[data-test="guard-drone-1"]').trigger('click')
    await wrapper.get('[data-test="fire"]').trigger('click')

    expect(wrapper.emitted('aim')).toEqual([['drone-1']])
    expect(wrapper.emitted('guard')).toEqual([['drone-1']])
    expect(wrapper.emitted('fire')).toHaveLength(1)
  })

  it('조준 중인 드론에 남은 시간을 붙이고, 파괴된 드론은 겨눌 수 없다', () => {
    const state = stateMessage({
      units: [drone({ armed: true }), drone({ id: 'drone-2', name: '표적 드론 2', alive: false, hp: 0 })],
      threats: [{ from: 'drone-1', secondsToFire: 0.8 }],
    })

    const wrapper = mount(UnitsPanel, { props: { state, disabledReason: null } })

    expect(wrapper.get('[data-test="drone-threat"]').text()).toContain('조준 중 · 0.8초')
    expect(wrapper.get('[data-test="aim-drone-2"]').attributes('disabled')).toBeDefined()
    expect(wrapper.findAll('[data-test="drones"] li')[1]?.text()).toContain('파괴됨')
  })

  it('실패: 기체가 파괴되면 쏘기·겨누기를 막는다', () => {
    const state = stateMessage({ mecha: mechaStatus({ mode: 'destroyed', hp: 0 }) })

    const wrapper = mount(UnitsPanel, { props: { state, disabledReason: null } })

    expect(wrapper.get('[data-test="fire"]').attributes('disabled')).toBeDefined()
    expect(wrapper.get('[data-test="aim-drone-1"]').attributes('disabled')).toBeDefined()
  })

  it('빈 상태: 드론이 없는 장면이면 그렇게 알린다', () => {
    const wrapper = mount(UnitsPanel, { props: { state: stateMessage({ units: [] }), disabledReason: null } })

    expect(wrapper.text()).toContain('이 시험 장면에는 드론이 없습니다')
  })
})

describe('ScenarioPanel', () => {
  const scenarios = [
    { name: 'targets', label: '표적 사격', description: '멈춰 떠 있는 드론 3대', drones: 3, armedDrones: 0 },
    { name: 'skirmish', label: '반격하는 드론', description: '조준 경고 뒤에 쏩니다', drones: 3, armedDrones: 3 },
  ]

  it('지금 장면을 고른 채로 보여 주고, 처음으로를 누르면 그 장면으로 되돌린다', async () => {
    const wrapper = mount(ScenarioPanel, { props: { scenarios, current: 'skirmish', disabledReason: null } })

    expect(wrapper.text()).toContain('조준 경고 뒤에 쏩니다')
    await wrapper.get('[data-test="reset"]').trigger('click')

    expect(wrapper.get('[data-test="reset"]').text()).toBe('처음으로')
    expect(wrapper.emitted('reset')).toEqual([['skirmish']])
  })
})

describe('CombatLog', () => {
  it('빈 상태: 사격이 없으면 그렇게 알린다', () => {
    expect(mount(CombatLog, { props: { entries: [], names: NAMES } }).text()).toContain('아직 사격이 없습니다')
  })

  it('사격·격파를 사람이 읽는 글로 보여 준다', () => {
    const entries = [
      { key: 2, at: new Date(), event: { type: 'destroyed' as const, simTime: 3, unit: 'drone-1' } },
      {
        key: 1,
        at: new Date(),
        event: {
          type: 'shot' as const,
          simTime: 3,
          shooter: 'mecha',
          from: [0, 0, 30] as [number, number, number],
          to: [150, 0, 25] as [number, number, number],
          hit: { unit: 'drone-1', damage: 30, blocked: false },
        },
      },
    ]

    const text = mount(CombatLog, { props: { entries, names: NAMES } }).get('[data-test="combat-log"]').text()

    expect(text).toContain('표적 드론 1 파괴')
    expect(text).toContain('기체가 쏨 → 표적 드론 1 맞힘 (체력 -30)')
  })
})

describe('CommandLog', () => {
  it('받은 명령은 걸린 시간을, 거절된 명령은 까닭을 보여 준다', () => {
    const wrapper = mount(CommandLog, {
      props: {
        entries: [
          { label: '앞으로', at: new Date(), result: { id: 'a', accepted: true, roundTripMs: 23.4 } },
          { label: '쏘기', at: new Date(), result: { id: 'b', accepted: false, reason: '소총이 아직 식는 중입니다', roundTripMs: 9 } },
        ],
      },
    })

    const text = wrapper.get('[data-test="command-log"]').text()
    expect(text).toContain('받음 · 23ms')
    expect(text).toContain('소총이 아직 식는 중입니다')
  })
})
