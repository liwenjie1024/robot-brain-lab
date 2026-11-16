import { flushPromises } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import StageView from '@/components/StageView.vue'
import { button, fakeSim, show } from '@/test/fakeSim'
import { g1Scene, novaScene, novaState } from '@/test/samples'

// 测试的环境里没有显卡，所以把"舞台"换成一个只记下被叫了什么的假舞台。
const stage = vi.hoisted(() => ({
  setFigure: vi.fn(),
  update: vi.fn(),
  setView: vi.fn(),
  showMarkers: vi.fn(),
  resize: vi.fn(),
  render: vi.fn(),
  dispose: vi.fn(),
}))
vi.mock('@/stage/stage', () => ({
  Stage: vi.fn(function Stage() {
    return stage
  }),
}))

beforeEach(() => {
  Object.values(stage).forEach((call) => call.mockReset())
  vi.stubGlobal(
    'ResizeObserver',
    class {
      observe(): void {}
      disconnect(): void {}
    },
  )
  // 不让画面真的一帧一帧地画下去；每个测试自己决定画几帧。
  vi.stubGlobal('requestAnimationFrame', () => 1)
  vi.stubGlobal('cancelAnimationFrame', () => undefined)
})

afterEach(() => {
  vi.unstubAllGlobals()
  document.body.innerHTML = ''
})

describe('3D 的身体', () => {
  it('拿到样子就把身体放上舞台，画的时候用最新的状态', async () => {
    const sim = fakeSim(novaScene(), novaState())
    show(StageView, sim)
    await vi.dynamicImportSettled()
    await flushPromises()
    expect(stage.setFigure).toHaveBeenCalledTimes(1)
    expect(stage.setFigure.mock.calls[0]![0].body).toBe('nova')
    expect(stage.update).toHaveBeenCalledWith(sim.shown.value)
    expect(stage.render).toHaveBeenCalledTimes(1)
  })

  it('换了身体：把新的放上舞台', async () => {
    const sim = fakeSim(novaScene(), novaState())
    show(StageView, sim)
    await vi.dynamicImportSettled()
    await flushPromises()
    sim.scene.value = g1Scene()
    await vi.dynamicImportSettled()
    await flushPromises()
    expect(stage.setFigure).toHaveBeenCalledTimes(2)
    expect(stage.setFigure.mock.calls[1]![0].body).toBe('g1')
  })

  it('能选从哪里看：自己转着看，或者从身体的每台相机看', async () => {
    const wrapper = show(StageView, fakeSim(novaScene(), novaState()))
    await vi.dynamicImportSettled()
    await flushPromises()
    expect(wrapper.find('.stage-tools').exists()).toBe(true)
    expect(wrapper.text()).toContain('自己转着看')
    expect(wrapper.text()).toContain('重心和压力中心')
    expect(wrapper.text()).not.toContain('不是相机拍到的画面')
  })

  it('还没有样子：写着正在等仿真', async () => {
    const wrapper = show(StageView, fakeSim(null, null))
    await vi.dynamicImportSettled()
    await flushPromises()
    expect(wrapper.text()).toContain('正在等仿真……')
    expect(wrapper.find('.stage-tools').exists()).toBe(false)
    expect(stage.setFigure).not.toHaveBeenCalled()
  })

  it('正在拿样子和网格：写着拿了几样、一共几样', async () => {
    const sim = fakeSim(null, null)
    sim.loading.value = { done: 12, total: 36 }
    const wrapper = show(StageView, sim)
    await vi.dynamicImportSettled()
    await flushPromises()
    expect(wrapper.text()).toContain('正在拿身体的样子（12 / 36）')
  })

  it('样子没拿到：说为什么，有"再试一次"', async () => {
    const sim = fakeSim(null, null)
    sim.sceneError.value = '仿真没有给出身体的样子（500）'
    const wrapper = show(StageView, sim)
    await vi.dynamicImportSettled()
    await flushPromises()
    expect(wrapper.text()).toContain('没拿到身体的样子')
    expect(wrapper.text()).toContain('仿真没有给出身体的样子（500）')
    await button(wrapper, '再试一次').trigger('click')
    expect(sim.retryScene).toHaveBeenCalledTimes(1)
  })

  it('身体搭不出来（比如少了网格）：说出来，不是一片空白', async () => {
    stage.setFigure.mockImplementation(() => {
      throw new Error('第 3 个网格还没有拿到')
    })
    const wrapper = show(StageView, fakeSim(novaScene(), novaState()))
    await vi.dynamicImportSettled()
    await flushPromises()
    expect(wrapper.text()).toContain('3D 画不出来')
    expect(wrapper.text()).toContain('第 3 个网格还没有拿到')
  })

  it('画面关掉的时候，把舞台占的地方还回去', async () => {
    const wrapper = show(StageView, fakeSim(novaScene(), novaState()))
    await vi.dynamicImportSettled()
    await flushPromises()
    wrapper.unmount()
    expect(stage.dispose).toHaveBeenCalledTimes(1)
  })
})
