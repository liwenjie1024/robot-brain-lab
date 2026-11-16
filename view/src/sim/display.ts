// 画面上的数多久换一次。仿真每秒发 30 次状态，数字跟着跳的话看不清，所以隔 0.1 秒换一次；
// 但是重要的变化（倒了、暂停了、松开了、换了一回……）马上换，不等。
import type { State } from '@/generated/message'

export const SHOW_EVERY_MS = 100

/** 新来的状态里有没有要马上让人看到的变化。 */
export function changedUrgently(shown: State | null, next: State): boolean {
  return (
    shown === null ||
    shown.body !== next.body ||
    shown.episode !== next.episode ||
    shown.running !== next.running ||
    shown.controlled !== next.controlled ||
    shown.fallen !== next.fallen ||
    shown.problem !== next.problem ||
    (shown.push === null) !== (next.push === null)
  )
}

/** 这个新来的状态现在要不要换到画面上。shownAtMs 是画面上那个是什么时候换上的。 */
export function shouldShow(shown: State | null, next: State, shownAtMs: number, nowMs: number): boolean {
  return changedUrgently(shown, next) || nowMs - shownAtMs >= SHOW_EVERY_MS
}
