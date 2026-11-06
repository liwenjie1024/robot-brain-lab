import Ajv2020 from 'ajv/dist/2020'
import controlSchema from '../../contracts/brain/control.schema.json'
import type { BrainControl } from '@shared/brain/generated/control'
import type { ControlResult } from '@shared/brain/generated/status'
import type { Brain } from './brain'

const validateControl = new Ajv2020({ allErrors: false }).compile<BrainControl>(controlSchema)

/**
 * 화면이 보낸 지시를 경계에서 확인하고 적용한다. 받을 수 없으면 까닭을 붙여 거절한다.
 * knownTargets는 지금 장면의 드론 (모르면 비어 있고, 그때는 표적을 확인하지 않는다).
 * 말로 한 명령(order)은 받았다고 바로 답하고, 계획을 짜는 과정은 두뇌의 상태와 판단 기록으로 알린다.
 * 시험 중에는 시험 멈추기만 받는다.
 */
export function applyControl(text: string, brain: Brain, knownTargets: ReadonlySet<string>): ControlResult {
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
  if (brain.trialsRunning && message.type !== 'stopTrials') {
    return result(false, '시험 중에는 할 수 없습니다. 시험을 멈춘 뒤 해 주세요')
  }
  switch (message.type) {
    case 'setSkill':
      if (message.target && knownTargets.size > 0 && !knownTargets.has(message.target)) {
        return result(false, `그런 표적이 없습니다: ${message.target}`)
      }
      brain.chooseSkill(message.skill, message.target ?? null, message.evasion)
      return result(true)
    case 'setAutonomy':
      brain.setAutonomy(message.enabled)
      return result(true)
    case 'order':
      if (!message.text.trim()) {
        return result(false, '명령이 비어 있습니다')
      }
      void brain.order(message.text)
      return result(true)
    case 'cancelPlan':
      return brain.cancelPlan() ? result(true) : result(false, '그만둘 계획이 없습니다')
    case 'startTrials': {
      const reason = brain.startTrials(message)
      return reason ? result(false, reason) : result(true)
    }
    case 'stopTrials':
      return brain.stopTrials() ? result(true) : result(false, '돌고 있는 시험이 없습니다')
  }
}
