import type { Posture } from '@/sim/generated/message'
import type { ConnectionPhase } from '@/sim/simClient'

/** 상태는 색과 글자를 함께 보여 준다 (색만으로 나누지 않는다). */
export type TagType = 'success' | 'warning' | 'error' | 'info' | 'default'

export interface StatusLabel {
  text: string
  type: TagType
  help: string
}

export const POSTURE_LABELS: Record<Posture, StatusLabel> = {
  standing: { text: '서 있음', type: 'success', help: '골반이 충분히 높고 똑바로 서 있습니다.' },
  fallen: {
    text: '넘어짐',
    type: 'error',
    help: '골반이 낮아졌거나 60도 넘게 기울었습니다. "처음 자세로"를 눌러 다시 세우세요.',
  },
}

export const PHASE_LABELS: Record<ConnectionPhase, StatusLabel> = {
  'loading-scene': { text: '몸 모양을 받는 중', type: 'info', help: '시뮬레이터에서 로봇의 모양을 받고 있습니다.' },
  connecting: { text: '연결하는 중', type: 'info', help: '시뮬레이터에 연결하고 있습니다.' },
  open: { text: '연결됨', type: 'success', help: '시뮬레이터에서 상태를 받고 있습니다.' },
  reconnecting: { text: '다시 연결하는 중', type: 'warning', help: '연결이 끊겨 다시 붙고 있습니다.' },
  failed: { text: '연결 못 함', type: 'error', help: '시뮬레이터가 떠 있는지 확인한 뒤 다시 시도해 주세요.' },
}

export function formatSpeed(value: number, unit: 'm/s' | 'rad/s'): string {
  return `${value.toFixed(2)} ${unit}`
}

export function formatDegrees(radians: number): string {
  return `${Math.round((radians * 180) / Math.PI)}°`
}

export function formatSeconds(seconds: number): string {
  return `${seconds.toFixed(1)}초`
}
