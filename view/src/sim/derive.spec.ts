import { describe, expect, it } from 'vitest'
import {
  effortOf,
  footprint,
  hardestJoint,
  jointRows,
  REGIONS,
  rotate,
  rowsByRegion,
  speedText,
  standingOf,
  touched,
  TOUCH_THRESHOLD_N,
} from '@/sim/derive'
import { g1Scene, g1State, novaScene, novaState } from '@/test/samples'

const HALF_TURN = Math.SQRT1_2

describe('关节费不费力', () => {
  it('每个关节一行，顺序和模型里一样；出的力矩是峰值的多少', () => {
    const scene = novaScene()
    const rows = jointRows(scene, novaState())
    expect(rows.map((row) => row.name)).toEqual(scene.joints.map((joint) => joint.name))
    const ankle = rows.find((row) => row.name === 'left_ankle_pitch')!
    expect(ankle.label).toBe('左 踝 前后')
    expect(ankle.region).toBe('腿')
    expect(ankle.torqueNm).toBeCloseTo(-22.42, 1)
    expect(ankle.share).toBeCloseTo(0.091, 2)
    const knee = rows.find((row) => row.name === 'left_knee')!
    expect(knee.angleDeg).toBeCloseTo(15, 1)
  })

  it('站着的时候最费力的是踝（两个身体都是）', () => {
    expect(hardestJoint(jointRows(novaScene(), novaState()))!.label).toContain('踝 前后')
    expect(hardestJoint(jointRows(g1Scene(), g1State()))!.label).toContain('踝 前后')
    expect(hardestJoint([])).toBeNull()
  })

  it('按身体的部分分组，只留这个身体有的部分，顺序固定', () => {
    const nova = rowsByRegion(jointRows(novaScene(), novaState()))
    expect(nova.map((group) => [group.region, group.rows.length])).toEqual([
      ['腿', 12],
      ['腰', 3],
      ['颈', 2],
      ['手臂', 14],
      ['手', 36],
    ])
    expect(nova.map((group) => group.region)).toEqual([...REGIONS])
    const g1 = rowsByRegion(jointRows(g1Scene(), g1State()))
    expect(g1.map((group) => [group.region, group.rows.length])).toEqual([
      ['腿', 12],
      ['腰', 3],
      ['手臂', 14],
    ])
    expect(nova[0]!.hardest.label).toContain('踝 前后')
  })

  it.each([
    [0, 'easy'],
    [0.499, 'easy'],
    [0.5, 'working'],
    [0.799, 'working'],
    [0.8, 'near-limit'],
    [1.5, 'near-limit'],
  ] as const)('出了峰值的 %s：%s', (share, effort) => {
    expect(effortOf(share)).toBe(effort)
  })
})

describe('现在是什么情况', () => {
  it('站着、松开了、暂停着、倒了、出了问题', () => {
    const state = novaState()
    expect(standingOf(state)).toBe('standing')
    expect(standingOf({ ...state, controlled: false })).toBe('limp')
    expect(standingOf({ ...state, running: false })).toBe('paused')
    expect(standingOf({ ...state, fallen: true })).toBe('fallen')
    expect(standingOf({ ...state, problem: '数坏了' })).toBe('problem')
  })

  it('几样同时有：说最要紧的那一样', () => {
    const state = novaState()
    expect(standingOf({ ...state, fallen: true, running: false, controlled: false })).toBe('fallen')
    expect(standingOf({ ...state, problem: 'x', fallen: true, running: false })).toBe('problem')
    expect(standingOf({ ...state, running: false, controlled: false })).toBe('paused')
  })

  it('仿真走得多快，用一句话说', () => {
    const state = novaState()
    expect(speedText({ ...state, speed: 1 })).toBe('和钟一样快')
    expect(speedText({ ...state, speed: 0.95 })).toBe('和钟一样快')
    expect(speedText({ ...state, speed: 0.949 })).toBe('比钟慢（0.95 倍）')
    expect(speedText({ ...state, speed: 0.6 })).toBe('比钟慢（0.60 倍）')
    expect(speedText({ ...state, running: false, speed: 0 })).toBe('停着')
  })
})

describe('用姿态转一个方向', () => {
  it('没有转的姿态：方向不变', () => {
    expect(rotate([1, 0, 0, 0], [1, 2, 3])).toEqual([1, 2, 3])
  })

  it('绕朝上的轴转 90°：朝前的变成朝左的', () => {
    const [x, y, z] = rotate([HALF_TURN, 0, 0, HALF_TURN], [1, 0, 0])
    expect(x).toBeCloseTo(0)
    expect(y).toBeCloseTo(1)
    expect(z).toBeCloseTo(0)
  })

  it('绕朝左的轴转 90°：朝前的变成朝下的', () => {
    const [x, y, z] = rotate([HALF_TURN, 0, HALF_TURN, 0], [1, 0, 0])
    expect(x).toBeCloseTo(0)
    expect(y).toBeCloseTo(0)
    expect(z).toBeCloseTo(-1)
  })
})

describe('从上面往下看脚底', () => {
  it('两只脚一左一右，各托一半；压力中心和重心在两只脚的正中间', () => {
    const scene = novaScene()
    const print = footprint(scene, novaState())
    const [left, right] = print.feet
    expect([left!.label, right!.label]).toEqual(['左脚', '右脚'])
    expect(left!.center[1]).toBeCloseTo(0.085, 3)
    expect(right!.center[1]).toBeCloseTo(-0.085, 3)
    expect(left!.center[0]).toBeCloseTo(0, 3)
    expect(left!.headingRad).toBeCloseTo(0, 3)
    expect(left!.share).toBeCloseTo(0.5, 2)
    expect(left!.share + right!.share).toBeCloseTo(1, 6)
    expect([left!.lengthM, left!.widthM]).toEqual([scene.feet[0]!.length_m, scene.feet[0]!.width_m])
    expect(left!.pressureCenter![1]).toBeGreaterThan(0)
    expect(right!.pressureCenter![1]).toBeLessThan(0)
    expect(print.pressureCenter![0]).toBeCloseTo(0, 2)
    expect(print.pressureCenter![1]).toBeCloseTo(0, 3)
    expect(print.centerOfMass[0]).toBeCloseTo(print.pressureCenter![0], 2)
  })

  it('基线的脚也照样算出来', () => {
    const print = footprint(g1Scene(), g1State())
    expect(print.feet[0]!.center[1]).toBeCloseTo(0.1185, 3)
    expect(print.feet[0]!.lengthM).toBeCloseTo(0.18)
    expect(print.feet[0]!.share).toBeCloseTo(0.5, 2)
  })

  it('脚没有踩在地上：没有压力中心，各托 0', () => {
    const state = {
      ...novaState(),
      support_n: 0,
      pressure_center: null,
      feet: [
        { support_n: 0, pressure_center: null },
        { support_n: 0, pressure_center: null },
      ] as ReturnType<typeof novaState>['feet'],
    }
    const print = footprint(novaScene(), state)
    expect(print.pressureCenter).toBeNull()
    expect(print.feet.map((foot) => [foot.share, foot.pressureCenter])).toEqual([
      [0, null],
      [0, null],
    ])
  })

  it('身体转了 90°（面朝左）：脚尖也朝左，两只脚一前一后', () => {
    const state = novaState()
    const turned = { ...state, link_positions: [...state.link_positions], link_orientations: [...state.link_orientations] }
    const links = turned.link_positions.length / 3
    for (let link = 0; link < links; link++) {
      const position = state.link_positions.slice(3 * link, 3 * link + 3)
      const [x, y, z] = rotate([HALF_TURN, 0, 0, HALF_TURN], position)
      turned.link_positions.splice(3 * link, 3, x, y, z)
      // 这个样本里每一段的脚都没有转（站着），所以整个转 90° 以后脚的姿态就是这个。
      turned.link_orientations.splice(4 * link, 4, HALF_TURN, 0, 0, HALF_TURN)
    }
    const print = footprint(novaScene(), turned)
    expect(print.feet[0]!.headingRad).toBeCloseTo(Math.PI / 2, 3)
    expect(print.feet[0]!.center[0]).toBeCloseTo(-0.085, 3)
    expect(print.feet[1]!.center[0]).toBeCloseTo(0.085, 3)
  })
})

describe('哪里碰到了东西', () => {
  it('站着的时候只有两只脚碰着地面', () => {
    const places = touched(novaScene(), novaState())
    expect(places.map((place) => place.label)).toEqual(['左 脚', '右 脚'])
    expect(places[0]!.forceN).toBeCloseTo(366.5, 0)
  })

  it('力不到 0.5 N 的不算碰到；正好 0.5 N 的算', () => {
    const scene = novaScene()
    const state = novaState()
    state.touches = state.touches.map(() => [0, 0, 0])
    state.touches[0] = [0, 0, TOUCH_THRESHOLD_N - 0.01]
    state.touches[1] = [TOUCH_THRESHOLD_N, 0, 0]
    expect(touched(scene, state).map((place) => place.label)).toEqual([scene.touch_sensors[1]!.label])
  })

  it('没有量接触的传感器的身体：什么也没有', () => {
    expect(touched(g1Scene(), g1State())).toEqual([])
  })
})
