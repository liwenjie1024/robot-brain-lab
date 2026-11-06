import type { Metrics } from '@shared/brain/generated/status'

/** 판단 시간·명령 수는 최근 이만큼 동안을 본다 */
const WINDOW_MS = 5000
const MILLIS_PER_SECOND = 1000
const MICROS_PER_MILLI = 1000

/** 두뇌가 얼마나 빨리, 얼마나 잘 하는지 잰다 (화면에 보이고 시험 점수가 된다). */
export class BrainMetrics {
  private ticks: { at: number; micros: number }[] = []
  private commands: number[] = []
  private lastReactionMs: number | null = null
  private reactions: number[] = []
  private shots = 0
  private hits = 0
  private kills = 0
  private damageTaken = 0

  constructor(private readonly now: () => number = () => performance.now()) {}

  reset(): void {
    this.ticks = []
    this.commands = []
    this.lastReactionMs = null
    this.reactions = []
    this.shots = 0
    this.hits = 0
    this.kills = 0
    this.damageTaken = 0
  }

  /** 판단 한 번 (startedAt은 now()로 잰 시작 시각) */
  tick(startedAt: number): void {
    const at = this.now()
    this.ticks.push({ at, micros: (at - startedAt) * MICROS_PER_MILLI })
  }

  commandSent(): void {
    this.commands.push(this.now())
  }

  reaction(milliseconds: number): void {
    this.lastReactionMs = milliseconds
    this.reactions.push(milliseconds)
  }

  /** 처음으로 되돌린 뒤의 반응 시간 평균 (시험 한 판의 값) */
  averageReactionMs(): number | null {
    return this.reactions.length ? Math.round(this.reactions.reduce((sum, value) => sum + value, 0) / this.reactions.length) : null
  }

  shot(): void {
    this.shots++
  }

  hit(): void {
    this.hits++
  }

  kill(): void {
    this.kills++
  }

  damaged(amount: number): void {
    this.damageTaken += amount
  }

  snapshot(): Metrics {
    const since = this.now() - WINDOW_MS
    this.ticks = this.ticks.filter((tick) => tick.at >= since)
    this.commands = this.commands.filter((at) => at >= since)
    const micros = this.ticks.map((tick) => tick.micros)
    const average = micros.length ? micros.reduce((sum, value) => sum + value, 0) / micros.length : 0
    return {
      tickMicrosAvg: Math.round(average),
      tickMicrosMax: Math.round(micros.length ? Math.max(...micros) : 0),
      commandsPerSecond: Math.round((this.commands.length / WINDOW_MS) * MILLIS_PER_SECOND * 10) / 10,
      lastReactionMs: this.lastReactionMs === null ? null : Math.round(this.lastReactionMs),
      shots: this.shots,
      hits: this.hits,
      kills: this.kills,
      damageTaken: this.damageTaken,
    }
  }
}
