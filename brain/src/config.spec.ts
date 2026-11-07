import { describe, expect, it } from 'vitest'
import { bodyLinkKind } from './config'

describe('몸에 붙는 길 고르기 (BODY_LINK)', () => {
  it('정하지 않으면 몸의 WebSocket에 바로 붙는다', () => {
    expect(bodyLinkKind(undefined)).toBe('ws')
  })

  it.each(['ws', 'ros'] as const)('%s는 그대로 쓴다', (kind) => {
    expect(bodyLinkKind(kind)).toBe(kind)
  })

  it.each(['', 'ROS', 'rosbridge'])('실패: 모르는 값 "%s"은 띄울 때 멈춘다 (다른 길로 잰 줄 모르게)', (value) => {
    expect(() => bodyLinkKind(value)).toThrow('BODY_LINK는 ws 또는 ros만 쓸 수 있습니다')
  })
})
