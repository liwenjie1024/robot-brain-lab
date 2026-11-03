import type { CombatEvent } from '@shared/sim/simClient'
import type { TagType } from './labels'

/** 사격·격파 사건을 사람이 읽는 한 줄로 바꾼다. names는 유닛 번호 → 이름 (모르면 번호 그대로). */
export interface CombatLine {
  text: string
  type: TagType
}

const MECHA_ID = 'mecha'

export function describeCombatEvent(event: CombatEvent, names: ReadonlyMap<string, string>): CombatLine {
  const name = (id: string) => names.get(id) ?? id
  if (event.type === 'destroyed') {
    return event.unit === MECHA_ID
      ? { text: '기체가 파괴되었습니다', type: 'error' }
      : { text: `${name(event.unit)} 파괴`, type: 'success' }
  }
  const shooter = event.shooter === MECHA_ID ? '기체가 쏨' : `${name(event.shooter)}이(가) 쏨`
  const hit = event.hit
  if (!hit) {
    return { text: `${shooter} → 빗나감`, type: 'default' }
  }
  if (hit.blocked) {
    return { text: `${shooter} → 방패로 막음`, type: 'info' }
  }
  if (hit.unit === MECHA_ID) {
    return { text: `${shooter} → 기체가 맞음 (체력 -${hit.damage})`, type: 'error' }
  }
  return { text: `${shooter} → ${name(hit.unit)} 맞힘 (체력 -${hit.damage})`, type: 'success' }
}
