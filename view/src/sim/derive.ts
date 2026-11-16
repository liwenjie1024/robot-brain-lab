// 从"样子"和"状态"里算出画面要用的东西：每个关节费不费力、站得怎么样、脚底的图、哪里碰到了东西。
// 这里只是算，不碰画面，也不认身体是哪一个。
import { magnitude, toDegrees } from '@/text/format'
import type { State } from '@/generated/message'
import type { Joint, Scene } from '@/generated/scene'

export type Region = Joint['region']
/** 身体的各部分在画面上排的顺序。 */
export const REGIONS: readonly Region[] = ['腿', '腰', '颈', '手臂', '手']

export interface JointRow {
  name: string
  label: string
  region: Region
  torqueNm: number
  /** 出的力矩是峰值的多少（0~1）。 */
  share: number
  angleDeg: number
}

export interface RegionRows {
  region: Region
  rows: JointRow[]
  /** 这一部分里最费力的关节。 */
  hardest: JointRow
}

/** 每个关节现在的读数，顺序和模型里一样。 */
export function jointRows(scene: Scene, state: State): JointRow[] {
  return scene.joints.map((joint, index) => {
    const torqueNm = state.joints.torques_nm[index] ?? 0
    return {
      name: joint.name,
      label: joint.label,
      region: joint.region,
      torqueNm,
      share: Math.abs(torqueNm) / joint.peak_torque_nm,
      angleDeg: toDegrees(state.joints.angles_rad[index] ?? 0),
    }
  })
}

/** 最费力的那个关节。一个关节都没有就是 null。 */
export function hardestJoint(rows: readonly JointRow[]): JointRow | null {
  return rows.reduce<JointRow | null>((hardest, row) => (hardest === null || row.share > hardest.share ? row : hardest), null)
}

/** 把关节按身体的部分分开，只留这个身体有的部分。 */
export function rowsByRegion(rows: readonly JointRow[]): RegionRows[] {
  return REGIONS.flatMap((region) => {
    const inRegion = rows.filter((row) => row.region === region)
    const hardest = hardestJoint(inRegion)
    return hardest ? [{ region, rows: inRegion, hardest }] : []
  })
}

export type Effort = 'easy' | 'working' | 'near-limit'
const WORKING_FROM = 0.5
const NEAR_LIMIT_FROM = 0.8

/** 一个关节费不费力：不到峰值的一半算轻松，到八成算快到顶了。 */
export function effortOf(share: number): Effort {
  if (share >= NEAR_LIMIT_FROM) return 'near-limit'
  return share >= WORKING_FROM ? 'working' : 'easy'
}

export type Standing = 'problem' | 'fallen' | 'paused' | 'limp' | 'standing'

/** 现在是什么情况。几样同时有的时候，说最要紧的那一样。 */
export function standingOf(state: State): Standing {
  if (state.problem !== null) return 'problem'
  if (state.fallen) return 'fallen'
  if (!state.running) return 'paused'
  return state.controlled ? 'standing' : 'limp'
}

const AS_FAST_AS_THE_CLOCK = 0.95

/** 仿真走得多快，用一句话说。 */
export function speedText(state: State): string {
  if (!state.running) return '停着'
  if (state.speed >= AS_FAST_AS_THE_CLOCK) return '和钟一样快'
  return `比钟慢（${state.speed.toFixed(2)} 倍）`
}

type Point = [number, number]

export interface FootMark {
  label: string
  /** 脚底正中间在地面上的位置（米）：往前、往左，从两只脚的正中间量。 */
  center: Point
  /** 脚尖朝哪边：0 是朝前，正的是往左转。 */
  headingRad: number
  lengthM: number
  widthM: number
  supportN: number
  /** 这只脚托着的占全部的多少（0~1）。地面没托着任何东西时是 0。 */
  share: number
  pressureCenter: Point | null
}

export interface Footprint {
  feet: FootMark[]
  pressureCenter: Point | null
  centerOfMass: Point
}

const NUMBERS_PER_POSITION = 3
const NUMBERS_PER_ORIENTATION = 4

/** 用姿态（w、x、y、z）转一个方向。 */
export function rotate(orientation: readonly number[], vector: readonly number[]): [number, number, number] {
  const [w = 1, x = 0, y = 0, z = 0] = orientation
  const [vx = 0, vy = 0, vz = 0] = vector
  // v + 2w(u × v) + 2u × (u × v)，u 是 (x, y, z)。
  const cx = y * vz - z * vy
  const cy = z * vx - x * vz
  const cz = x * vy - y * vx
  return [
    vx + 2 * (w * cx + y * cz - z * cy),
    vy + 2 * (w * cy + z * cx - x * cz),
    vz + 2 * (w * cz + x * cy - y * cx),
  ]
}

/** 从上面往下看脚底：两只脚在哪、各托着多少、压力中心和重心落在哪。都从两只脚的正中间量。 */
export function footprint(scene: Scene, state: State): Footprint {
  const soles = scene.feet.map((foot) => {
    const position = state.link_positions.slice(foot.link * NUMBERS_PER_POSITION, (foot.link + 1) * NUMBERS_PER_POSITION)
    const orientation = state.link_orientations.slice(
      foot.link * NUMBERS_PER_ORIENTATION,
      (foot.link + 1) * NUMBERS_PER_ORIENTATION,
    )
    const offset = rotate(orientation, foot.sole)
    const forward = rotate(orientation, [1, 0, 0])
    return {
      x: (position[0] ?? 0) + offset[0],
      y: (position[1] ?? 0) + offset[1],
      headingRad: Math.atan2(forward[1], forward[0]),
    }
  })
  const middle: Point = [
    soles.reduce((sum, sole) => sum + sole.x, 0) / soles.length,
    soles.reduce((sum, sole) => sum + sole.y, 0) / soles.length,
  ]
  const fromMiddle = (point: readonly number[]): Point => [(point[0] ?? 0) - middle[0], (point[1] ?? 0) - middle[1]]
  return {
    feet: scene.feet.map((foot, index) => {
      const sole = soles[index] ?? { x: 0, y: 0, headingRad: 0 }
      const support = state.feet[index]
      return {
        label: foot.label,
        center: fromMiddle([sole.x, sole.y]),
        headingRad: sole.headingRad,
        lengthM: foot.length_m,
        widthM: foot.width_m,
        supportN: support?.support_n ?? 0,
        share: state.support_n > 0 ? (support?.support_n ?? 0) / state.support_n : 0,
        pressureCenter: support?.pressure_center ? fromMiddle(support.pressure_center) : null,
      }
    }),
    pressureCenter: state.pressure_center ? fromMiddle(state.pressure_center) : null,
    centerOfMass: fromMiddle(state.center_of_mass),
  }
}

export interface Touch {
  label: string
  forceN: number
}

/** 力比这个小的不算碰到（仿真里会有一点点算出来的零头）。 */
export const TOUCH_THRESHOLD_N = 0.5

/** 现在哪些地方碰到了东西，碰得多重。 */
export function touched(scene: Scene, state: State): Touch[] {
  return scene.touch_sensors.flatMap((sensor, index) => {
    const forceN = magnitude(state.touches[index] ?? [])
    return forceN >= TOUCH_THRESHOLD_N ? [{ label: sensor.label, forceN }] : []
  })
}
