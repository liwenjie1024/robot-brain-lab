// 画面上的各种状态叫什么、用什么颜色。状态都是"颜色 + 字"一起用，不只靠颜色。
import type { Effort, Standing } from '@/sim/derive'
import type { LinkStatus } from '@/sim/link'

type TagType = 'success' | 'warning' | 'error' | 'info'

export interface StatusLabel {
  label: string
  type: TagType
  /** 这是什么情况、接下来能做什么。 */
  hint: string
}

export const LINK_LABELS: Record<LinkStatus, StatusLabel> = {
  connecting: { label: '正在连接', type: 'warning', hint: '正在连仿真' },
  open: { label: '已连接', type: 'success', hint: '连着仿真，数是现在的' },
  closed: { label: '连接断了', type: 'error', hint: '连不上仿真。过一会儿会自己再连，也可以现在就再连一次' },
}

export const STANDING_LABELS: Record<Standing, StatusLabel> = {
  standing: { label: '站着', type: 'success', hint: '驱动器顶着站姿' },
  limp: { label: '松开了', type: 'warning', hint: '驱动器不出力，身体会倒。再点"顶住"就恢复出力' },
  paused: { label: '暂停着', type: 'info', hint: '仿真停着。点"继续"接着走' },
  fallen: { label: '倒了', type: 'error', hint: '点"重新开始"回到站姿' },
  problem: { label: '出了问题', type: 'error', hint: '点"重新开始"' },
}

export interface EffortLabel {
  label: string
  color: string
}

export const EFFORT_LABELS: Record<Effort, EffortLabel> = {
  easy: { label: '轻松', color: '#2f9e58' },
  working: { label: '用力', color: '#d98a00' },
  'near-limit': { label: '快到顶了', color: '#d12d2d' },
}

export type PushDirection = 'forward' | 'backward' | 'left' | 'right'

export const PUSH_LABELS: Record<PushDirection, string> = {
  forward: '往前',
  backward: '往后',
  left: '往左',
  right: '往右',
}

/** 推的力度：是体重的多少。 */
export const PUSH_STRENGTHS: readonly { share: number; label: string }[] = [
  { share: 0.02, label: '很轻' },
  { share: 0.04, label: '轻' },
  { share: 0.08, label: '中' },
  { share: 0.15, label: '重' },
  { share: 0.3, label: '很重' },
]
