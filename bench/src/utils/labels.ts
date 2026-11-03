import type { MechaMode } from '@/sim/generated/message'
import type { ConnectionPhase } from '@/sim/simClient'

/** 상태는 색과 글자를 함께 보여 준다 (색만으로 나누지 않는다). */
export type TagType = 'success' | 'warning' | 'error' | 'info' | 'default'

export interface StatusLabel {
  text: string
  type: TagType
  help: string
}

export const MODE_LABELS: Record<MechaMode, StatusLabel> = {
  landed: { text: '착지', type: 'default', help: '땅에 서 있고 추진기를 끈 상태입니다.' },
  flying: { text: '비행 중', type: 'success', help: '추진기로 떠 있거나 날고 있습니다.' },
  destroyed: {
    text: '파괴됨',
    type: 'error',
    help: '체력이 다해 추진기가 꺼졌습니다. "처음으로"를 눌러 다시 시작하세요.',
  },
}

export const PHASE_LABELS: Record<ConnectionPhase, StatusLabel> = {
  'loading-scene': { text: '시험장 모양을 받는 중', type: 'info', help: '시뮬레이터에서 시험장의 모양을 받고 있습니다.' },
  connecting: { text: '연결하는 중', type: 'info', help: '시뮬레이터에 연결하고 있습니다.' },
  open: { text: '연결됨', type: 'success', help: '시뮬레이터에서 상태를 받고 있습니다.' },
  reconnecting: { text: '다시 연결하는 중', type: 'warning', help: '연결이 끊겨 다시 붙고 있습니다.' },
  failed: { text: '연결 못 함', type: 'error', help: '시뮬레이터가 떠 있는지 확인한 뒤 다시 시도해 주세요.' },
}

export function formatSpeed(value: number, unit: 'm/s' | 'rad/s'): string {
  return `${value.toFixed(unit === 'm/s' ? 1 : 2)} ${unit}`
}

export function formatDegrees(radians: number): string {
  return `${Math.round((radians * 180) / Math.PI)}°`
}

export function formatSeconds(seconds: number): string {
  return `${seconds.toFixed(1)}초`
}

export function formatMeters(meters: number): string {
  return `${Math.round(meters)} m`
}

export function distance(a: readonly number[], b: readonly number[]): number {
  return Math.hypot((a[0] ?? 0) - (b[0] ?? 0), (a[1] ?? 0) - (b[1] ?? 0), (a[2] ?? 0) - (b[2] ?? 0))
}
