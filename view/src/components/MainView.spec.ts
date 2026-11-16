import { flushPromises, mount } from '@vue/test-utils'
import { NMessageProvider } from 'naive-ui'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { defineComponent, h } from 'vue'
import MainView from '@/components/MainView.vue'
import { button, fakeSim } from '@/test/fakeSim'
import type { FakeSim } from '@/test/fakeSim'
import { novaScene, novaState } from '@/test/samples'

// 整个画面用的仿真换成假的；3D 的那一块这里不测（它有自己的测试）。
const current = vi.hoisted(() => ({ sim: null as unknown }))
vi.mock('@/sim/useSim', () => ({ useSim: () => current.sim }))
vi.mock('@/components/StageView.vue', () => ({ default: { render: () => null } }))

function showPage(sim: FakeSim) {
  current.sim = sim
  const host = defineComponent({ render: () => h(NMessageProvider, null, { default: () => h(MainView) }) })
  return mount(host, { attachTo: document.body })
}

beforeEach(() => {
  current.sim = null
})

afterEach(() => {
  document.body.innerHTML = ''
})

describe('整个画面', () => {
  it('一切正常：有操作、站得怎么样、关节的力矩、感觉四块，没有红色的提示', () => {
    const wrapper = showPage(fakeSim(novaScene(), novaState()))
    const titles = wrapper.findAll('.n-card-header__main').map((title) => title.text())
    expect(titles.map((title) => title.replace(/\s*\?$/, ''))).toEqual(['操作', '站得怎么样', '关节的力矩', '感觉'])
    expect(wrapper.findAll('.n-alert').length).toBe(0)
    expect(wrapper.find('.panels.old').exists()).toBe(false)
  })

  it('连接断了：说下面的数是旧的、怎么把仿真开起来；读数调淡；能点"再连一次"', async () => {
    const sim = fakeSim(novaScene(), novaState())
    sim.link.value = 'closed'
    const wrapper = showPage(sim)
    const notice = wrapper.find('.notices').text()
    expect(notice).toContain('和仿真的连接断了')
    expect(notice).toContain('下面的数是断开之前的，不是现在的')
    expect(notice).toContain('docker compose up -d sim')
    expect(wrapper.find('.panels.old').exists()).toBe(true)
    await button(wrapper.find('.notices') as never, '再连一次').trigger('click')
    expect(sim.retryLink).toHaveBeenCalledTimes(1)
  })

  it('正在连的时候读数也是旧的（调淡），但不说"断了"', () => {
    const sim = fakeSim(novaScene(), novaState())
    sim.link.value = 'connecting'
    const wrapper = showPage(sim)
    expect(wrapper.find('.panels.old').exists()).toBe(true)
    expect(wrapper.find('.notices').text()).not.toContain('和仿真的连接断了')
  })

  it('收到了读不懂的消息：说出来，告诉人怎么办', () => {
    const sim = fakeSim(novaScene(), novaState())
    sim.problem.value = '仿真发来的消息读不懂（/time_s：must be number）'
    const notice = showPage(sim).find('.notices').text()
    expect(notice).toContain('收到了读不懂的消息')
    expect(notice).toContain('/time_s：must be number')
    expect(notice).toContain('docker compose restart sim')
  })

  it('仿真自己出了问题：把它说的原样告诉人', async () => {
    const sim = fakeSim(novaScene(), { ...novaState(), running: false, problem: '仿真里的数坏了，已经停下。请重新开始' })
    const wrapper = showPage(sim)
    await flushPromises()
    expect(wrapper.find('.notices').text()).toContain('仿真出了问题')
    expect(wrapper.find('.notices').text()).toContain('仿真里的数坏了，已经停下。请重新开始')
  })
})
