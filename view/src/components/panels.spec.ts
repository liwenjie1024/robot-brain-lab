import { flushPromises } from '@vue/test-utils'
import { afterEach, describe, expect, it, vi } from 'vitest'
import BalancePanel from '@/components/BalancePanel.vue'
import ControlPanel from '@/components/ControlPanel.vue'
import JointPanel from '@/components/JointPanel.vue'
import SensePanel from '@/components/SensePanel.vue'
import StageView from '@/components/StageView.vue'
import StatusBar from '@/components/StatusBar.vue'
import { button, fakeSim, show } from '@/test/fakeSim'
import { g1Scene, g1State, novaScene, novaState } from '@/test/samples'

afterEach(() => {
  document.body.innerHTML = ''
})

const pushing = { force_n: [30, 0, 0] as [number, number, number], remaining_s: 0.3 }

describe('最上面的一条', () => {
  it('连着、站着：写着已连接、身体的名字、站着、第几回、过了多久', () => {
    const wrapper = show(StatusBar, fakeSim(novaScene(), { ...novaState(), episode: 2, time_s: 12.34 }))
    const text = wrapper.text()
    expect(text).toContain('已连接')
    expect(text).toContain('Nova（核心版）')
    expect(text).toContain('站着')
    expect(text).toContain('第 3 回 · 12.3 秒')
    expect(text).toContain('和钟一样快')
    expect(text).not.toContain('再连一次')
  })

  it.each([
    ['正在连', 'connecting', '正在连接', false],
    ['断了', 'closed', '连接断了', true],
  ] as const)('%s：写出来；断了才有"再连一次"', (_name, status, label, canRetry) => {
    const sim = fakeSim(novaScene(), novaState())
    sim.link.value = status
    const wrapper = show(StatusBar, sim)
    expect(wrapper.text()).toContain(label)
    expect(wrapper.text().includes('再连一次')).toBe(canRetry)
  })

  it('点"再连一次"就去连', async () => {
    const sim = fakeSim(novaScene(), novaState())
    sim.link.value = 'closed'
    await button(show(StatusBar, sim), '再连一次').trigger('click')
    expect(sim.retryLink).toHaveBeenCalledTimes(1)
  })

  it.each([
    ['倒了', { fallen: true }, '倒了'],
    ['暂停着', { running: false }, '暂停着'],
    ['松开了', { controlled: false }, '松开了'],
    ['出了问题', { problem: '数坏了' }, '出了问题'],
  ])('%s：状态用字写出来（不只是颜色）', (_name, change, label) => {
    const wrapper = show(StatusBar, fakeSim(novaScene(), { ...novaState(), ...change }))
    expect(wrapper.find('.n-tag + span').exists() || wrapper.text().includes(label)).toBe(true)
    expect(wrapper.text()).toContain(label)
  })

  it('连接断着的时候，时间那一块调淡（是旧的）', () => {
    const sim = fakeSim(novaScene(), novaState())
    sim.link.value = 'closed'
    expect(show(StatusBar, sim).find('.bar-old').exists()).toBe(true)
  })

  it('有的身体现在用不了：问号里写着为什么', () => {
    const scene = novaScene()
    scene.choices[1] = { ...scene.choices[1]!, available: false, reason: '先运行下载的命令' }
    const wrapper = show(StatusBar, fakeSim(scene, novaState()))
    expect(wrapper.find('[aria-label*="先运行下载的命令"]').exists()).toBe(true)
  })

  it('还没拿到样子和状态：只有连接的状态，身体那里写着还没拿到', () => {
    const wrapper = show(StatusBar, fakeSim(null, null))
    expect(wrapper.text()).toContain('已连接')
    expect(wrapper.text()).toContain('还没拿到')
    expect(wrapper.text()).not.toContain('第 ')
  })
})

describe('操作', () => {
  it('点"重新开始"发重新开始；仿真在走时另一个按钮是"暂停"', async () => {
    const sim = fakeSim(novaScene(), novaState())
    const wrapper = show(ControlPanel, sim)
    await button(wrapper, '重新开始').trigger('click')
    expect(sim.reset).toHaveBeenCalledTimes(1)
    await button(wrapper, '暂停').trigger('click')
    expect(sim.pause).toHaveBeenCalledTimes(1)
    expect(sim.resume).not.toHaveBeenCalled()
  })

  it('暂停着的时候按钮是"继续"；这时候推不了，写着为什么', async () => {
    const sim = fakeSim(novaScene(), { ...novaState(), running: false })
    const wrapper = show(ControlPanel, sim)
    await button(wrapper, '继续').trigger('click')
    expect(sim.resume).toHaveBeenCalledTimes(1)
    expect(button(wrapper, '往前').attributes('disabled')).toBeDefined()
    expect(wrapper.text()).toContain('暂停着的时候推不了')
  })

  it('推一下：默认是"轻"（体重的 4%），写着是多少牛；点方向就往那边推', async () => {
    const sim = fakeSim(novaScene(), novaState())
    const wrapper = show(ControlPanel, sim)
    expect(wrapper.text()).toContain('力是体重的 4%，约 29 N')
    await button(wrapper, '往左').trigger('click')
    expect(sim.pushBody).toHaveBeenCalledWith('left', 0.04)
    await flushPromises()
    await button(wrapper, '往后').trigger('click')
    expect(sim.pushBody).toHaveBeenLastCalledWith('backward', 0.04)
  })

  it('轻的身体同样是 4%，牛顿数小', () => {
    expect(show(ControlPanel, fakeSim(g1Scene(), g1State())).text()).toContain('力是体重的 4%，约 13 N')
  })

  it('正在推的时候不能再推，写着"正在推"', () => {
    const wrapper = show(ControlPanel, fakeSim(novaScene(), { ...novaState(), push: pushing }))
    expect(wrapper.text()).toContain('正在推……')
    for (const direction of ['往前', '往后', '往左', '往右']) {
      expect(button(wrapper, direction).attributes('disabled')).toBeDefined()
    }
  })

  it('连接断着、或者还没有状态：都不能操作，写着为什么', () => {
    const offline = fakeSim(novaScene(), novaState())
    offline.link.value = 'closed'
    for (const sim of [offline, fakeSim(novaScene(), null)]) {
      const wrapper = show(ControlPanel, sim)
      expect(button(wrapper, '重新开始').attributes('disabled')).toBeDefined()
      expect(button(wrapper, '往前').attributes('disabled')).toBeDefined()
      expect(wrapper.text()).toContain('还没连上仿真')
    }
  })

  it('仿真没有照做：把原因弹出来给人看', async () => {
    const sim = fakeSim(novaScene(), novaState())
    sim.pushBody.mockRejectedValueOnce(new Error('上一下还没推完'))
    await button(show(ControlPanel, sim), '往前').trigger('click')
    await flushPromises()
    expect(document.body.textContent).toContain('上一下还没推完')
  })

  it('驱动器的开关：现在是顶住的；关掉就发"松开"', async () => {
    const sim = fakeSim(novaScene(), novaState())
    const wrapper = show(ControlPanel, sim)
    const toggle = wrapper.find('[role="switch"]')
    expect(toggle.attributes('aria-checked')).toBe('true')
    await toggle.trigger('click')
    expect(sim.setControl).toHaveBeenCalledWith(false)
  })
})

describe('站得怎么样', () => {
  it('写着歪了多少、骨盆多高、地面托着多少公斤、两只脚各托多少', () => {
    const text = show(BalancePanel, fakeSim(novaScene(), novaState())).text()
    expect(text).toContain('0.0°')
    expect(text).toContain('0.89 m')
    expect(text).toContain('74.2 kg（体重 74.2 kg）')
    expect(text).toContain('左脚：37.1 kg（50%）')
    expect(text).toContain('右脚：37.1 kg（50%）')
    expect(text).not.toContain('脚没有踩在地上')
  })

  it('图上画着两只脚、每只脚的压力中心、合起来的压力中心和重心', () => {
    const wrapper = show(BalancePanel, fakeSim(novaScene(), novaState()))
    expect(wrapper.findAll('rect.foot').length).toBe(2)
    expect(wrapper.findAll('circle.foot-center').length).toBe(2)
    expect(wrapper.find('circle.pressure').exists()).toBe(true)
    expect(wrapper.find('g.mass').exists()).toBe(true)
    expect(wrapper.find('svg').attributes('aria-label')).toBe('从上面往下看的脚底')
  })

  it('脚没有踩在地上：说出来，不画压力中心', () => {
    const state = novaState()
    state.support_n = 0
    state.pressure_center = null
    state.feet = [
      { support_n: 0, pressure_center: null },
      { support_n: 0, pressure_center: null },
    ]
    const wrapper = show(BalancePanel, fakeSim(novaScene(), state))
    expect(wrapper.text()).toContain('脚没有踩在地上')
    expect(wrapper.find('circle.pressure').exists()).toBe(false)
    expect(wrapper.text()).toContain('左脚：0.0 kg（0%）')
  })

  it('还没有状态：写着还没有收到', () => {
    expect(show(BalancePanel, fakeSim(novaScene(), null)).text()).toContain('还没有收到状态')
  })
})

describe('关节的力矩', () => {
  it('说出现在最费力的关节；按身体的部分分组，腿那一组一开始是打开的', () => {
    const wrapper = show(JointPanel, fakeSim(novaScene(), novaState()))
    expect(wrapper.find('.summary').text().replace(/\s+/g, ' ')).toMatch(
      /^现在最费力的是 左 踝 前后：22\.\d N·m，是峰值的 9%（轻松）$/,
    )
    const groups = wrapper.findAll('details')
    expect(groups.map((group) => group.find('summary').text().replace(/\s+/g, ' '))).toEqual([
      '腿（12 个） 最费力：左 踝 前后 9%',
      '腰（3 个） 最费力：腰 前后 1%',
      '颈（2 个） 最费力：颈 点头 3%',
      '手臂（14 个） 最费力：左 肘 3%',
      '手（36 个） 最费力：左 拇指 腕掌 弯 2%',
    ])
    expect(groups.map((group) => group.attributes('open') !== undefined)).toEqual([true, false, false, false, false])
    expect(wrapper.findAll('tbody tr').length).toBe(67)
  })

  it('每一行写着力矩、是峰值的百分之几、费不费力（字和颜色一起）', () => {
    const wrapper = show(JointPanel, fakeSim(novaScene(), novaState()))
    const ankle = wrapper.findAll('tbody tr').find((row) => row.text().includes('左 踝 前后'))!
    const [bar, torque, share] = ankle.findAll('td')
    expect(torque!.text()).toMatch(/^-22\.\d$/)
    expect(share!.text()).toBe('9% 轻松')
    expect(bar!.find('.bar').attributes('aria-label')).toBe('轻松，峰值的 9%')
  })

  it('状态变了，表里的数跟着变（不停在刚打开时的数上）', async () => {
    const sim = fakeSim(novaScene(), novaState())
    const wrapper = show(JointPanel, sim)
    const changed = novaState()
    const ankle = novaScene().joints.findIndex((joint) => joint.name === 'left_ankle_pitch')
    changed.joints.torques_nm[ankle] = -220
    sim.shown.value = changed
    await flushPromises()
    const row = wrapper.findAll('tbody tr').find((candidate) => candidate.text().includes('左 踝 前后'))!
    expect(row.findAll('td').map((cell) => cell.text())).toEqual(['', '-220.0', '90% 快到顶了'])
    expect(wrapper.find('.summary').text()).toContain('快到顶了')
  })

  it('基线只有腿、腰、手臂三组', () => {
    const wrapper = show(JointPanel, fakeSim(g1Scene(), g1State()))
    expect(wrapper.findAll('details').length).toBe(3)
    expect(wrapper.findAll('tbody tr').length).toBe(29)
  })

  it('还没有状态：写着还没有收到', () => {
    expect(show(JointPanel, fakeSim(novaScene(), null)).text()).toContain('还没有收到状态')
  })
})

describe('感觉', () => {
  it('Nova：两个 IMU、四个六轴力、碰着地面的两只脚', () => {
    const wrapper = show(SensePanel, fakeSim(novaScene(), novaState()))
    const text = wrapper.text()
    expect(text).toContain('前 0.00　左 0.00　上 9.81')
    expect(wrapper.findAll('table').length).toBe(2)
    expect(wrapper.findAll('table')[0]!.findAll('tbody tr').length).toBe(2)
    expect(wrapper.findAll('table')[1]!.findAll('tbody tr').length).toBe(4)
    expect(text).toContain('左踝')
    expect(text).toContain('左 脚 364 N')
    expect(text).toContain('右 脚 364 N')
  })

  it('基线：有 IMU；没有的传感器写着"这个身体没有"', () => {
    const text = show(SensePanel, fakeSim(g1Scene(), g1State())).text()
    expect(text).toContain('躯干')
    expect(text).toContain('这个身体没有六轴力传感器。')
    expect(text).toContain('这个身体没有量接触的传感器。')
  })

  it('有量接触的传感器，但是哪里都没碰到：写出来', () => {
    const state = novaState()
    state.touches = state.touches.map(() => [0, 0, 0])
    expect(show(SensePanel, fakeSim(novaScene(), state)).text()).toContain('25 处都没有碰到东西。')
  })

  it('还没有状态：写着还没有收到', () => {
    expect(show(SensePanel, fakeSim(null, null)).text()).toContain('还没有收到状态')
  })
})

describe('3D 的身体（测试的环境里没有显卡）', () => {
  it('浏览器画不了 3D：说出来，告诉人怎么办', async () => {
    // three.js 画不了的时候会往控制台写一行错；这里就是要它画不了，不让这一行混进测试的输出。
    const complaints = vi.spyOn(console, 'error').mockImplementation(() => undefined)
    const noContext = vi.spyOn(HTMLCanvasElement.prototype, 'getContext').mockReturnValue(null)
    const wrapper = show(StageView, fakeSim(novaScene(), novaState()))
    await vi.dynamicImportSettled()
    await flushPromises()
    complaints.mockRestore()
    noContext.mockRestore()
    expect(wrapper.text()).toContain('3D 画不出来')
    expect(wrapper.text()).toContain('这个浏览器画不了 3D（没有 WebGL）')
  })
})
