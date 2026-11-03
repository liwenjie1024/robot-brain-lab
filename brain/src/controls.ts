import Ajv2020 from 'ajv/dist/2020'
import controlSchema from '../../contracts/brain/control.schema.json'
import type { BrainControl } from '@shared/brain/generated/control'
import type { ControlResult } from '@shared/brain/generated/status'
import type { System1 } from './system1'

const validateControl = new Ajv2020({ allErrors: false }).compile<BrainControl>(controlSchema)

/**
 * 화면(나중에는 느린 뇌)이 보낸 지시를 경계에서 확인하고 적용한다. 받을 수 없으면 까닭을 붙여 거절한다.
 * knownTargets는 지금 장면의 드론 (모르면 비어 있고, 그때는 표적을 확인하지 않는다).
 */
export function applyControl(text: string, system1: System1, knownTargets: ReadonlySet<string>): ControlResult {
  let message: unknown
  try {
    message = JSON.parse(text)
  } catch {
    return { type: 'controlResult', accepted: false, reason: 'JSON이 아닙니다' }
  }
  const id = typeof message === 'object' && message && 'id' in message && typeof message.id === 'string' ? message.id : undefined
  const result = (accepted: boolean, reason?: string): ControlResult => ({
    type: 'controlResult',
    accepted,
    ...(id ? { id } : {}),
    ...(reason ? { reason } : {}),
  })
  if (!validateControl(message)) {
    return result(false, `지시 모양이 맞지 않습니다: ${validateControl.errors?.[0]?.message ?? ''}`)
  }
  switch (message.type) {
    case 'setSkill':
      if (message.target && knownTargets.size > 0 && !knownTargets.has(message.target)) {
        return result(false, `그런 표적이 없습니다: ${message.target}`)
      }
      system1.setSkill(message.skill, message.target ?? null, message.evasion)
      return result(true)
    case 'setAutonomy':
      system1.setAutonomy(message.enabled)
      return result(true)
  }
}
