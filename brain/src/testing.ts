import type { StateMessage, UnitStatus } from '@shared/sim/generated/message'
import type { CommandResult, OutgoingCommand } from '@shared/sim/simClient'
import { drone, mechaStatus, stateMessage } from '@shared/test/fixtures'
import type { CommandSender } from './commander'
import { type Perception, perceive } from './perception'
import type { ChatRequest, LanguageModel } from './system2/model'

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

/**
 * 가짜 언어 모델: 준비한 답을 chunkSize 글자씩 흘린다. 물은 내용을 기록한다.
 * pause를 주면 조각마다 그것을 기다린다 (StepGate로 조각을 하나씩 내보내 "흘러 오는 중"을 시험한다).
 */
export class ScriptedModel implements LanguageModel {
  readonly name = 'test-model'
  available = true
  warmUps = 0
  chunkSize = 8
  pause: ((signal: AbortSignal) => Promise<void>) | null = null
  readonly requests: ChatRequest[] = []
  private readonly answers: (string | Error)[] = []

  reply(...answers: (string | Error)[]): this {
    this.answers.push(...answers)
    return this
  }

  async chat(request: ChatRequest, onText: (text: string) => void): Promise<void> {
    this.requests.push(request)
    const answer = this.answers.shift()
    if (answer === undefined) {
      throw new Error('시험: 준비한 답이 없음')
    }
    if (answer instanceof Error) {
      throw answer
    }
    for (let index = 0; index < answer.length; index += this.chunkSize) {
      await this.pause?.(request.signal)
      request.signal.throwIfAborted()
      onText(answer.slice(index, index + this.chunkSize))
    }
  }

  async isAvailable(): Promise<boolean> {
    return this.available
  }

  async warmUp(): Promise<void> {
    this.warmUps++
  }
}

/** 조각을 하나씩 내보내는 문. 끊으면(abort) 기다리던 조각은 그 까닭으로 실패한다. */
export class StepGate {
  private waiting: (() => void)[] = []

  readonly wait = (signal: AbortSignal): Promise<void> =>
    new Promise((resolve, reject) => {
      this.waiting.push(resolve)
      signal.addEventListener('abort', () => reject(signal.reason), { once: true })
    })

  /** 조각 하나를 내보내고 그 처리가 끝나기를 기다린다 */
  async release(): Promise<void> {
    this.waiting.shift()?.()
    await settle()
  }

  /** 조건이 맞을 때까지 조각을 내보낸다 */
  async releaseUntil(condition: () => boolean, limit = 1000): Promise<void> {
    for (let count = 0; count < limit && !condition(); count++) {
      await this.release()
    }
  }

  get pending(): number {
    return this.waiting.length
  }
}
