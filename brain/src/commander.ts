import type { FlightVelocity } from '@shared/sim/generated/message'
import type { Limits } from '@shared/sim/generated/scene'
import type { CommandResult, OutgoingCommand } from '@shared/sim/simClient'
import { clamp } from './geometry'
import type { GuardIntent, Intent } from './intent'

/** 속도를 이 단위로 맞춰, 아주 작은 변화로 명령을 쏟아내지 않는다. */
const SPEED_STEP = 0.5
const TURN_STEP = 0.05
/** 단위로 맞춘 값의 실수 오차를 지우는 자릿수 (1.2/0.05 = 23.999…처럼 되지 않게) */
const DECIMALS = 6

export interface CommandSender {
  send(command: OutgoingCommand): Promise<CommandResult>
}

export interface SentCommands {
  velocity?: Promise<CommandResult>
  aim?: Promise<CommandResult>
  guard?: Promise<CommandResult>
  fire?: Promise<CommandResult>
}

export interface CommanderEvents {
  /** 몸이 명령을 거절했다 (두뇌의 실수를 기록으로 남긴다) */
  rejected(command: OutgoingCommand, reason: string): void
  /** 명령 하나를 보냈다 (초당 명령 수를 센다) */
  sent(): void
}

/**
 * 의도 → 몸에 보낼 명령. 지난번에 보낸 것과 달라진 것만 보낸다 (몸은 다음 명령까지 그대로 따른다).
 * 속도는 몸이 알린 범위 안으로 자르고 단위로 맞춘다. 사격은 앞 사격의 답이 오기 전에는 다시 보내지 않는다.
 */
export class Commander {
  private velocity: FlightVelocity | null = null
  private aim: string | null | undefined = undefined
  private guard: string | undefined = undefined
  private firing = false

  constructor(
    private readonly sender: CommandSender,
    private readonly events: CommanderEvents,
    private limits: Limits | null = null,
  ) {}

  setLimits(limits: Limits): void {
    this.limits = limits
  }

  /** 몸이 처음으로 되돌아갔다: 지난번에 보낸 것을 잊고 다음 판단에서 모두 다시 보낸다. */
  forget(): void {
    this.velocity = null
    this.aim = undefined
    this.guard = undefined
  }

  apply(intent: Intent): SentCommands {
    const sent: SentCommands = {}
    const velocity = this.fit(intent.velocity)
    if (!this.velocity || !sameVelocity(this.velocity, velocity)) {
      this.velocity = velocity
      sent.velocity = this.send({ type: 'velocity', ...velocity }, () => (this.velocity = null))
    }
    if (intent.aim !== this.aim) {
      this.aim = intent.aim
      sent.aim = this.send(intent.aim ? { type: 'aim', unit: intent.aim } : { type: 'lowerAim' }, () => (this.aim = undefined))
    }
    const guardKey = guardKeyOf(intent.guard)
    if (guardKey !== this.guard) {
      this.guard = guardKey
      sent.guard = this.send(guardCommand(intent.guard), () => (this.guard = undefined))
    }
    if (intent.fire && !this.firing) {
      this.firing = true
      sent.fire = this.send({ type: 'fire' }, () => undefined).finally(() => (this.firing = false))
    }
    return sent
  }

  private send(command: OutgoingCommand, onRejected: () => void): Promise<CommandResult> {
    this.events.sent()
    return this.sender.send(command).then((result) => {
      if (!result.accepted) {
        // 거절된 명령은 보냈다고 기억하지 않는다 (다음 판단에서 다시 정한다).
        onRejected()
        this.events.rejected(command, result.reason ?? '까닭을 알 수 없음')
      }
      return result
    })
  }

  private fit(velocity: FlightVelocity): FlightVelocity {
    const limits = this.limits
    const fit = (value: number, step: number, range?: { min: number; max: number }) => {
      const inRange = (v: number) => (range ? clamp(v, range.min, range.max) : v)
      // 범위로 자르고, 단위로 맞추고, 단위가 범위 끝을 넘겼으면 다시 자른다 (몸이 범위 밖이라고 거절하지 않게).
      return inRange(roundTo(inRange(value), step))
    }
    return {
      forward: fit(velocity.forward, SPEED_STEP, limits?.forward),
      sideways: fit(velocity.sideways, SPEED_STEP, limits?.sideways),
      up: fit(velocity.up, SPEED_STEP, limits?.up),
      turn: fit(velocity.turn, TURN_STEP, limits?.turn),
    }
  }
}

function roundTo(value: number, step: number): number {
  return Number((Math.round(value / step) * step).toFixed(DECIMALS)) || 0
}

function sameVelocity(a: FlightVelocity, b: FlightVelocity): boolean {
  return a.forward === b.forward && a.sideways === b.sideways && a.up === b.up && a.turn === b.turn
}

function guardKeyOf(guard: GuardIntent): string {
  return guard.raised ? `up:${guard.unit ?? ''}` : 'down'
}

function guardCommand(guard: GuardIntent): OutgoingCommand {
  if (!guard.raised) {
    return { type: 'guard', raised: false }
  }
  return guard.unit ? { type: 'guard', raised: true, unit: guard.unit } : { type: 'guard', raised: true }
}
