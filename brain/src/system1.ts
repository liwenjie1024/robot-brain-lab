import type { Evasion, SkillName } from '@shared/brain/generated/control'
import type { BrainStatus } from '@shared/brain/generated/status'
import type { StateMessage } from '@shared/sim/generated/message'
import type { SceneDescription } from '@shared/sim/generated/scene'
import type { CombatEvent, OutgoingCommand } from '@shared/sim/simClient'
import { type CommandSender, Commander } from './commander'
import { DecisionLog } from './decisions'
import type { Intent } from './intent'
import { BrainMetrics } from './metrics'
import { type Perception, perceive } from './perception'
import { EvasionReflex, type ReflexAction } from './reflexes'
import { EngageSkill } from './skills/engage'
import { HoldSkill } from './skills/hold'
import { IdleSkill } from './skills/idle'
import { RetreatSkill } from './skills/retreat'
import type { Skill } from './skills/skill'

const MECHA_ID = 'mecha'
export const DEFAULT_EVASION: Evasion = 'dodge'

export const SKILL_LABELS: Record<SkillName, string> = {
  idle: '대기',
  hold: '자리 지키기',
  engage: '교전',
  retreat: '물러나기',
}

const EVASION_LABELS: Record<Evasion, string> = {
  dodge: '피하기',
  guard: '방패로 막기',
  both: '피하며 막기',
  none: '반응 안 함',
}

export function createSkill(name: SkillName, target: string | null): Skill {
  switch (name) {
    case 'hold':
      return new HoldSkill()
    case 'engage':
      return new EngageSkill(target)
    case 'retreat':
      return new RetreatSkill()
    case 'idle':
      return new IdleSkill()
  }
}

/**
 * 빠른 뇌(System 1): 몸의 상태가 올 때마다(50Hz) 지금 보이는 것으로 의도를 정하고, 맡았으면 몸에 명령한다.
 * 기술(사람·느린 뇌가 고름) 위에 반사(조준 경고에 피하기·막기)를 얹는다. 언어 모델을 쓰지 않는다.
 */
export class System1 {
  readonly log = new DecisionLog()
  readonly metrics: BrainMetrics
  private readonly commander: Commander
  private readonly reflex = new EvasionReflex()
  private skill: Skill = new IdleSkill()
  private skillTarget: string | null = null
  private evasion: Evasion = DEFAULT_EVASION
  private autonomy = false
  private simConnected = false
  private names = new Map<string, string>()
  private lastSimTime: number | null = null
  private lastIntent: Intent | null = null
  private lastReflex: ReflexAction | null = null

  constructor(
    sender: CommandSender,
    private readonly now: () => number = () => performance.now(),
  ) {
    this.metrics = new BrainMetrics(now)
    this.commander = new Commander(sender, {
      sent: () => this.metrics.commandSent(),
      rejected: (command, reason) => this.log.add('command', `몸이 ${describeCommand(command)} 명령을 거절함: ${reason}`, this.lastSimTime),
    })
  }

  setScene(scene: SceneDescription): void {
    this.names = new Map(scene.units.map((unit) => [unit.id, unit.name]))
    this.commander.setLimits(scene.limits)
  }

  setSimConnected(connected: boolean): void {
    this.simConnected = connected
    if (!connected) {
      this.commander.forget()
    }
  }

  setSkill(name: SkillName, target: string | null = null, evasion: Evasion = this.evasion): void {
    this.skill = createSkill(name, target)
    this.skillTarget = target
    this.evasion = evasion
    const aim = target ? ` (표적: ${this.nameOf(target)})` : ''
    this.log.add('skill', `기술: ${SKILL_LABELS[name]}${aim} · 조준 경고에는 ${EVASION_LABELS[evasion]}`, this.lastSimTime)
  }

  setAutonomy(enabled: boolean): void {
    if (enabled === this.autonomy) {
      return
    }
    this.autonomy = enabled
    // 맡을 때는 지난번에 보낸 명령을 잊고 모두 다시 보낸다 (그 사이 사람이 다른 명령을 보냈을 수 있다).
    this.commander.forget()
    this.log.add('skill', enabled ? '두뇌가 조종을 맡음' : '두뇌가 조종을 내려놓음 (보기만 함)', this.lastSimTime)
  }

  onState(state: StateMessage): void {
    const receivedAt = this.now()
    if (this.lastSimTime !== null && state.simTime < this.lastSimTime) {
      this.restart()
    }
    this.lastSimTime = state.simTime
    const perception = perceive(state)
    const reflex = this.reflex.update(perception, this.skill.name === 'idle' ? 'none' : this.evasion)
    const intent = withReflex(this.skill.decide(perception), reflex)
    this.metrics.tick(receivedAt)
    this.noteChanges(perception, intent, reflex)
    if (this.autonomy && perception.self.mode !== 'destroyed') {
      this.command(intent, reflex, receivedAt, perception)
    }
    this.lastIntent = intent
    this.lastReflex = reflex
  }

  onCombat(event: CombatEvent): void {
    const simTime = event.simTime
    if (event.type === 'destroyed') {
      if (event.unit === MECHA_ID) {
        this.log.add('result', '기체가 파괴됨', simTime)
      } else {
        this.metrics.kill()
        this.log.add('result', `${this.nameOf(event.unit)} 격파`, simTime)
      }
      return
    }
    const hit = event.hit
    if (event.shooter === MECHA_ID) {
      this.metrics.shot()
      if (hit && !hit.blocked) {
        this.metrics.hit()
      }
      this.log.add('result', hit ? `맞힘: ${this.nameOf(hit.unit)} (체력 -${hit.damage})` : '빗나감', simTime)
      return
    }
    const shooter = this.nameOf(event.shooter)
    if (!hit) {
      this.log.add('result', `${shooter}의 사격이 빗나감`, simTime)
    } else if (hit.blocked) {
      this.log.add('result', `${shooter}의 사격을 방패로 막음`, simTime)
    } else {
      this.metrics.damaged(hit.damage)
      this.log.add('result', `${shooter}에게 맞음 (체력 -${hit.damage})`, simTime)
    }
  }

  status(): BrainStatus {
    const intent = this.lastIntent
    const reflex = this.lastReflex
    return {
      type: 'brainStatus',
      simConnected: this.simConnected,
      autonomy: this.autonomy,
      simTime: this.lastSimTime,
      skill: { name: this.skill.name, target: this.skillTarget, evasion: this.evasion },
      activity: this.activityText(intent),
      target: intent?.target ?? null,
      reflex: reflex ? { kind: reflex.kind, threat: reflex.threat, until: reflex.until } : null,
      metrics: this.metrics.snapshot(),
    }
  }

  private restart(): void {
    this.reflex.reset()
    this.commander.forget()
    this.skill = createSkill(this.skill.name, this.skillTarget)
    this.metrics.reset()
    this.lastIntent = null
    this.log.add('skill', '몸이 처음으로 되돌아가 판단을 새로 시작함', null)
  }

  private command(intent: Intent, reflex: ReflexAction | null, receivedAt: number, perception: Perception): void {
    const sent = this.commander.apply(intent)
    if (sent.fire) {
      const error = perception.self.weapon.aimError
      this.log.add('fire', `사격: ${this.nameOf(intent.target)} (어긋남 ${error?.toFixed(2) ?? '?'}°)`, perception.simTime)
    }
    const reaction = reflex?.started ? (sent.velocity ?? sent.guard) : undefined
    void reaction?.then((result) => {
      if (result.accepted) {
        this.metrics.reaction(this.now() - receivedAt)
      }
    })
  }

  private noteChanges(perception: Perception, intent: Intent, reflex: ReflexAction | null): void {
    if (intent.target !== (this.lastIntent?.target ?? null) && intent.target) {
      this.log.add('target', `표적: ${this.nameOf(intent.target)} (${describeTarget(perception, intent.target)})`, perception.simTime)
    }
    if (reflex?.started) {
      const threat = perception.threats.find((item) => item.from === reflex.threat)
      const seconds = threat ? `${threat.secondsToFire.toFixed(1)}초 뒤 사격` : ''
      this.log.add('reflex', `${this.nameOf(reflex.threat)}이(가) 조준함 (${seconds}) → ${EVASION_LABELS[reflex.kind]}`, perception.simTime)
    }
  }

  private activityText(intent: Intent | null): string {
    if (!this.simConnected) {
      return '몸(시뮬레이터)에 연결되지 않음'
    }
    if (!intent) {
      return '몸의 상태를 기다리는 중'
    }
    const reflex = this.lastReflex
    const prefix = reflex ? `⚠ ${EVASION_LABELS[reflex.kind]} 중 · ` : ''
    const text = `${prefix}${intent.activity}`
    return this.autonomy ? text : `사람이 조종 중 (두뇌라면: ${text})`
  }

  private nameOf(id: string | null): string {
    return id ? (this.names.get(id) ?? id) : '없음'
  }
}

function withReflex(intent: Intent, reflex: ReflexAction | null): Intent {
  if (!reflex) {
    return intent
  }
  return {
    ...intent,
    velocity: reflex.velocity ?? intent.velocity,
    guard: reflex.guardUnit ? { raised: true, unit: reflex.guardUnit } : intent.guard,
  }
}

function describeTarget(perception: Perception, id: string): string {
  const target = perception.targets.find((item) => item.id === id)
  if (!target) {
    return '보이지 않음'
  }
  return `${Math.round(target.distance)} m${target.armed ? ', 무장' : ''}`
}

function describeCommand(command: OutgoingCommand): string {
  return command.type
}
