import { describe, expect, it } from 'vitest'
import { validateSimMessage } from '../sim/simClient'
import type { OutgoingCommand } from '../sim/simClient'
import { drone, mechaStatus, stateMessage } from '../test/fixtures'
import { rosDestroyed, rosShot, rosState, shotMessage } from '../test/rosFixtures'
import { combatFromRos, serviceCall, stateFromRos } from './bl01'

describe('BL-01 ROS 메시지 → 규약', () => {
  it('상태: 드라이버가 바꾼 메시지를 되돌리면 처음 상태와 같고 규약 스키마를 지난다', () => {
    const state = stateMessage({
      episode: 3,
      bodies: [0, 0, 20, 1, 0, 0, 0],
      units: [drone(), drone({ id: 'drone-2', name: '표적 드론 2', alive: false, hp: 0 })],
      threats: [{ from: 'drone-1', secondsToFire: 0.8 }],
    })

    const converted = stateFromRos(rosState(state))

    expect(converted).toEqual(state)
    expect(validateSimMessage(converted)).toBe(true)
  })

  it('상태: 빈 글은 없음(null)으로, has_*가 꺼진 값은 빠진 필드로 바꾼다', () => {
    const state = stateMessage({ mecha: mechaStatus({ weapon: { ready: false, cooldown: 0.4, aimTarget: null } }) })
    const ros = rosState(state)
    ros.mecha.weapon.aim_error = 12
    ros.mecha.weapon.aim_point = [9, 9, 9]

    const weapon = stateFromRos(ros).mecha.weapon

    expect(weapon).toEqual({ ready: false, cooldown: 0.4, aimTarget: null })
    expect(stateFromRos(ros).mecha.guard.unit).toBeNull()
  })

  it('상태: 겨누는 중이면 표적·어긋난 각·겨눈 점을 그대로 옮긴다', () => {
    const weaponStatus = { ready: true, cooldown: 0, aimTarget: 'drone-1', aimError: 1.5, aimPoint: [40, 0, 20] as [number, number, number] }
    const state = stateMessage({ mecha: mechaStatus({ weapon: weaponStatus, guard: { raised: true, unit: 'drone-2' } }) })

    const mecha = stateFromRos(rosState(state)).mecha

    expect(mecha.weapon).toEqual(weaponStatus)
    expect(mecha.guard).toEqual({ raised: true, unit: 'drone-2' })
  })

  it('실패: 필드가 빠진 메시지는 바꾸다 예외를 낸다 (쓰는 쪽이 버리고 알린다)', () => {
    const ros: Partial<ReturnType<typeof rosState>> = rosState(stateMessage())
    delete ros.mecha

    expect(() => stateFromRos(ros)).toThrow()
  })

  it('실패: 모양은 바꿀 수 있어도 값이 규약과 다르면 규약 스키마가 막는다', () => {
    const ros = rosState(stateMessage())
    ros.mecha.mode = 'swimming' as never

    expect(validateSimMessage(stateFromRos(ros))).toBe(false)
  })

  it.each([
    { name: '맞힌 사격', shot: shotMessage() },
    { name: '빗나간 사격', shot: shotMessage({ hit: undefined }) },
    { name: '방패에 막힌 사격', shot: shotMessage({ shooter: 'drone-1', hit: { unit: 'mecha', damage: 0, blocked: true } }) },
  ])('사건: $name을 되돌리면 처음 사건과 같다', ({ shot }) => {
    const expected = { ...shot }
    if (!expected.hit) {
      delete expected.hit
    }

    const converted = combatFromRos(rosShot(shot))

    expect(converted).toEqual(expected)
    expect(validateSimMessage(converted)).toBe(true)
  })

  it('사건: 격파는 파괴된 유닛만 옮긴다', () => {
    expect(combatFromRos(rosDestroyed('drone-1', 7.25))).toEqual({ type: 'destroyed', simTime: 7.25, unit: 'drone-1' })
  })
})

describe('명령 → BL-01 서비스 부르기', () => {
  const cases: { command: OutgoingCommand; service: string; type: string; args: object }[] = [
    {
      command: { type: 'velocity', forward: 20, sideways: -3, up: 1.5, turn: 0.2 },
      service: '/bl01/set_velocity',
      type: 'bl01_msgs/srv/SetVelocity',
      args: { velocity: { linear: { x: 20, y: -3, z: 1.5 }, angular: { x: 0, y: 0, z: 0.2 } } },
    },
    { command: { type: 'stop' }, service: '/bl01/stop', type: 'bl01_msgs/srv/Stop', args: {} },
    { command: { type: 'aim', unit: 'drone-2' }, service: '/bl01/aim', type: 'bl01_msgs/srv/Aim', args: { unit: 'drone-2' } },
    { command: { type: 'aimPoint', point: [1, 2, 3] }, service: '/bl01/aim_point', type: 'bl01_msgs/srv/AimPoint', args: { point: [1, 2, 3] } },
    { command: { type: 'lowerAim' }, service: '/bl01/lower_aim', type: 'bl01_msgs/srv/LowerAim', args: {} },
    { command: { type: 'guard', raised: true, unit: 'drone-1' }, service: '/bl01/guard', type: 'bl01_msgs/srv/Guard', args: { raised: true, unit: 'drone-1' } },
    { command: { type: 'guard', raised: false }, service: '/bl01/guard', type: 'bl01_msgs/srv/Guard', args: { raised: false, unit: '' } },
    { command: { type: 'fire' }, service: '/bl01/fire', type: 'bl01_msgs/srv/Fire', args: {} },
    {
      command: { type: 'push', force: [0, 5000, 0], durationMs: 200 },
      service: '/bl01/push',
      type: 'bl01_msgs/srv/Push',
      args: { force: [0, 5000, 0], duration_ms: 200 },
    },
    { command: { type: 'reset', scenario: 'skirmish' }, service: '/bl01/reset', type: 'bl01_msgs/srv/Reset', args: { scenario: 'skirmish' } },
    { command: { type: 'reset' }, service: '/bl01/reset', type: 'bl01_msgs/srv/Reset', args: { scenario: '' } },
  ]

  it.each(cases.map((item) => ({ ...item, name: JSON.stringify(item.command) })))('명령 $name → 서비스와 인자', ({ command, service, type, args }) => {
    expect(serviceCall(command)).toEqual({ service, type, args })
  })
})
