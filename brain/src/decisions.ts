import type { Decision, DecisionKind } from '@shared/brain/generated/status'

const KEEP = 60

/** 판단 기록: 무엇을 보고 무엇을 정했는지 한 줄씩. 화면에 바로 보내고, 최근 것을 새로 붙은 화면에 준다. */
export class DecisionLog {
  private entries: Decision[] = []
  private seq = 0
  private listeners = new Set<(decision: Decision) => void>()

  add(kind: DecisionKind, text: string, simTime: number | null): void {
    const decision: Decision = { type: 'decision', seq: ++this.seq, simTime, kind, text }
    this.entries = [...this.entries.slice(-(KEEP - 1)), decision]
    for (const listener of this.listeners) {
      listener(decision)
    }
  }

  recent(): Decision[] {
    return [...this.entries]
  }

  onDecision(listener: (decision: Decision) => void): () => void {
    this.listeners.add(listener)
    return () => this.listeners.delete(listener)
  }
}
