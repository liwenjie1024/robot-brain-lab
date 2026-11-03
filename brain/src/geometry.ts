/** 두뇌가 쓰는 작은 벡터 계산. 좌표는 몸과 같다: x 앞(세계), y 왼쪽, z 위, 각은 rad. */

export type Vec3 = readonly [number, number, number]

export interface Planar {
  /** 기수 방향 기준 앞 */
  forward: number
  /** 기수 방향 기준 왼쪽 */
  sideways: number
}

export function subtract(a: Vec3, b: Vec3): Vec3 {
  return [a[0] - b[0], a[1] - b[1], a[2] - b[2]]
}

export function length(v: Vec3): number {
  return Math.hypot(v[0], v[1], v[2])
}

/** -π ~ π로 */
export function wrapAngle(angle: number): number {
  return Math.atan2(Math.sin(angle), Math.cos(angle))
}

/** from에서 to를 볼 때 기수에서 돌아간 각 (왼쪽 +) */
export function bearing(from: Vec3, heading: number, to: Vec3): number {
  return wrapAngle(Math.atan2(to[1] - from[1], to[0] - from[0]) - heading)
}

/** 세계 바닥 방향(x, y)을 기수 기준 앞·옆으로 */
export function toHeadingFrame(worldX: number, worldY: number, heading: number): Planar {
  const cos = Math.cos(heading)
  const sin = Math.sin(heading)
  return { forward: cos * worldX + sin * worldY, sideways: -sin * worldX + cos * worldY }
}

export function clamp(value: number, low: number, high: number): number {
  return Math.min(high, Math.max(low, value))
}
