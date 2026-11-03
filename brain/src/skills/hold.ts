import { clamp, toHeadingFrame, type Vec3 } from '../geometry'
import { GUARD_DOWN, type Intent } from '../intent'
import type { Perception } from '../perception'
import type { Skill } from './skill'

/** 처음 자리(기술을 고른 때의 위치)로 돌아오는 빠르기 = 벗어난 거리 × 이 값 */
const RETURN_GAIN = 0.6
const MAX_RETURN_SPEED = 12
/** 이만큼 안이면 제자리로 본다 (명령을 흔들지 않게) */
const SETTLED_M = 1.5

/**
 * 자리 지키기: 기술을 고른 때의 위치를 붙잡는다. 맞거나 피하느라 밀려나도 되먹임으로 돌아온다
 * (멈춤 명령만 보내 놓으면 밀린 자리에 그대로 있다).
 */
export class HoldSkill implements Skill {
  readonly name = 'hold' as const
  private anchor: Vec3 | null = null

  decide(perception: Perception): Intent {
    const { position, heading } = perception.self
    const anchor = (this.anchor ??= position)
    const offset = [anchor[0] - position[0], anchor[1] - position[1], anchor[2] - position[2]] as const
    const away = Math.hypot(...offset)
    const planar = toHeadingFrame(offset[0], offset[1], heading)
    const scale = away < SETTLED_M ? 0 : RETURN_GAIN
    // 0을 곱한 음수는 -0이 되어 기록에 섞이므로 0으로 둔다.
    const limit = (value: number) => clamp(value * scale, -MAX_RETURN_SPEED, MAX_RETURN_SPEED) || 0
    return {
      velocity: { forward: limit(planar.forward), sideways: limit(planar.sideways), up: limit(offset[2]), turn: 0 },
      aim: null,
      guard: GUARD_DOWN,
      fire: false,
      activity: away < SETTLED_M ? '자리 지키는 중' : `처음 자리로 돌아가는 중 (${Math.round(away)} m 벗어남)`,
      target: null,
    }
  }
}
