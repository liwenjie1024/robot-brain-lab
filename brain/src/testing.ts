import type { StateMessage, UnitStatus } from '@shared/sim/generated/message'
import type { CommandResult, OutgoingCommand } from '@shared/sim/simClient'
import { drone, mechaStatus, stateMessage } from '@shared/test/fixtures'
import type { CommandSender } from './commander'
import { type Perception, perceive } from './perception'

/** 두뇌 시험에서 쓰는 도우미: 상태 만들기와, 보낸 명령을 기록하는 가짜 몸. */

export { drone, mechaStatus, stateMessage }

export function perceptionOf(overrides: Partial<StateMessage> = {}): Perception {
  return perceive(stateMessage(overrides))
}

/** 기체가 (0, 0, z)에서 기수 0(+x)을 보고 있고, 드론들이 주어진 자리에 있다. */
export function scene(units: UnitStatus[], overrides: Partial<StateMessage> = {}): Perception {
  return perceptionOf({ mecha: mechaStatus({ position: [0, 0, 30], heading: 0 }), units, ...overrides })
}

export class RecordingSender implements CommandSender {
  readonly sent: OutgoingCommand[] = []
  /** 정한 명령 종류는 거절한다 */
  rejectTypes = new Set<string>()
  private pending: ((result: CommandResult) => void)[] = []
  /** true면 답을 바로 주지 않고 flush()까지 기다린다 */
  holdReplies = false

  send(command: OutgoingCommand): Promise<CommandResult> {
    this.sent.push(command)
    const result: CommandResult = this.rejectTypes.has(command.type)
      ? { id: `${this.sent.length}`, accepted: false, reason: '시험용 거절', roundTripMs: 1 }
      : { id: `${this.sent.length}`, accepted: true, roundTripMs: 1 }
    if (this.holdReplies) {
      return new Promise((resolve) => this.pending.push(() => resolve(result)))
    }
    return Promise.resolve(result)
  }

  flush(): void {
    const pending = this.pending
    this.pending = []
    pending.forEach((resolve) => resolve({ id: '', accepted: true, roundTripMs: 1 }))
  }

  types(): string[] {
    return this.sent.map((command) => command.type)
  }

  clear(): void {
    this.sent.length = 0
  }
}

/** Promise의 then이 돌게 한 번 넘긴다 */
export function settle(): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, 0))
}
