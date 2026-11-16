// 把数写成人看的字。
export const GRAVITY_M_S2 = 9.81
const DEGREES_PER_RADIAN = 180 / Math.PI

/** 一个力相当于多少公斤的重量，比如 "39.1 kg"。 */
export function asKilograms(newtons: number): string {
  return `${(newtons / GRAVITY_M_S2).toFixed(1)} kg`
}

/** 一个数留几位小数。-0.0 写成 0.0。 */
export function fixed(value: number, digits = 1): string {
  const text = value.toFixed(digits)
  return Number(text) === 0 ? (0).toFixed(digits) : text
}

/** 0.085 写成 "9%"。 */
export function asPercent(share: number): string {
  return `${Math.round(share * 100)}%`
}

/** 弧度换成度。 */
export function toDegrees(radians: number): number {
  return radians * DEGREES_PER_RADIAN
}

/** 三个方向的数写成一行："前 0.1　左 0.0　上 9.8"。 */
export function asVector(values: readonly number[], digits = 1): string {
  const [forward = 0, left = 0, up = 0] = values
  return `前 ${fixed(forward, digits)}　左 ${fixed(left, digits)}　上 ${fixed(up, digits)}`
}

/** 三个方向的数合起来有多大。 */
export function magnitude(values: readonly number[]): number {
  return Math.hypot(...values)
}

/** 仿真过了多久："12.3 秒"；超过一分钟写成 "2 分 05 秒"。 */
export function asDuration(seconds: number): string {
  if (seconds < 60) return `${seconds.toFixed(1)} 秒`
  const minutes = Math.floor(seconds / 60)
  const rest = Math.floor(seconds - minutes * 60)
  return `${minutes} 分 ${String(rest).padStart(2, '0')} 秒`
}
