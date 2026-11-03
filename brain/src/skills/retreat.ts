import { clamp, toHeadingFrame } from '../geometry'
import { GUARD_DOWN, type Intent, STILL } from '../intent'
import type { Perception } from '../perception'
import type { Skill } from './skill'

const RETREAT_SPEED = 30
/** 이 높이까지 오르며 물러난다 (드론보다 위로) */
const SAFE_ALTITUDE_M = 80
const CLIMB_SPEED = 6
/** 가장 가까운 드론이 이보다 멀면 물러나기를 멈추고 떠 있는다 */
const SAFE_DISTANCE_M = 700

/** 물러나기: 드론들의 반대쪽으로 날며 오르고, 가장 가까운 무장 드론 쪽으로 방패를 든다. */
export class RetreatSkill implements Skill {
  readonly name = 'retreat' as const

  decide(perception: Perception): Intent {
    const { self, targets } = perception
    const nearest = targets[0]
    const armed = targets.find((target) => target.armed)
    const guard = armed ? { raised: true as const, unit: armed.id } : GUARD_DOWN
    const climb = self.position[2] < SAFE_ALTITUDE_M ? CLIMB_SPEED : 0
    if (!nearest || nearest.distance > SAFE_DISTANCE_M) {
      return { velocity: { ...STILL, up: climb }, aim: null, guard, fire: false, activity: '드론에게서 충분히 멀어짐', target: null }
    }
    // 드론들의 무게 중심에서 멀어지는 쪽 (바닥 방향만)
    const centerX = targets.reduce((sum, target) => sum + target.position[0], 0) / targets.length
    const centerY = targets.reduce((sum, target) => sum + target.position[1], 0) / targets.length
    const awayX = self.position[0] - centerX
    const awayY = self.position[1] - centerY
    const norm = Math.hypot(awayX, awayY) || 1
    const planar = toHeadingFrame((awayX / norm) * RETREAT_SPEED, (awayY / norm) * RETREAT_SPEED, self.heading)
    return {
      velocity: { forward: clamp(planar.forward, -RETREAT_SPEED, RETREAT_SPEED), sideways: planar.sideways, up: climb, turn: 0 },
      aim: null,
      guard,
      fire: false,
      activity: `물러나는 중 (가장 가까운 드론 ${Math.round(nearest.distance)} m)`,
      target: null,
    }
  }
}
