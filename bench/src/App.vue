<script setup lang="ts">
import { dateKoKR, koKR, NAlert, NButton, NConfigProvider, NMessageProvider, NTag, NTooltip } from 'naive-ui'
import { computed } from 'vue'
import { BrainClient, brainSocketUrl } from '@/brain/brainClient'
import { useBrain } from '@/brain/useBrain'
import BrainPanel from '@/components/BrainPanel.vue'
import CombatLog from '@/components/CombatLog.vue'
import CommandLog from '@/components/CommandLog.vue'
import FlightPanel from '@/components/FlightPanel.vue'
import MechaPanel from '@/components/MechaPanel.vue'
import OrderPanel from '@/components/OrderPanel.vue'
import RobotView from '@/components/RobotView.vue'
import ScenarioPanel from '@/components/ScenarioPanel.vue'
import TrialPanel from '@/components/TrialPanel.vue'
import UnitsPanel from '@/components/UnitsPanel.vue'
import type { FlightVelocity } from '@/control/drive'
import type { ScenarioName } from '@shared/sim/generated/command'
import { SimClient } from '@shared/sim/simClient'
import { useSim } from '@/sim/useSim'
import { PHASE_LABELS } from '@/utils/labels'

const SIM_BASE_URL = '/sim'
const BRAIN_PATH = '/brain'

const client = new SimClient({ baseUrl: SIM_BASE_URL })
const sim = useSim(client)
// 기록 목록은 컴포넌트 이름(CombatLog·CommandLog)과 겹치지 않게 부른다 (템플릿이 같은 이름의 값을 먼저 쓴다).
const { phase, phaseDetail, scene, state, log: commandEntries, combatLog: combatEntries } = sim

const brain = useBrain(new BrainClient({ url: brainSocketUrl(BRAIN_PATH) }))

const phaseLabel = computed(() => PHASE_LABELS[phase.value])
const TRIAL_RUNNING_REASON = '시험 중입니다. 아래 시험과 점수 칸에서 시험을 멈춘 뒤 쓸 수 있습니다.'
const disabledReason = computed(() => {
  if (phase.value !== 'open') {
    return '몸(시뮬레이터)과 연결되어야 명령을 보낼 수 있습니다.'
  }
  return brain.trialsRunning.value ? TRIAL_RUNNING_REASON : null
})
/** 사람이 직접 조종할 수 없는 까닭 (몸과 끊김, 또는 두뇌가 조종 중) */
const manualDisabledReason = computed(() =>
  disabledReason.value ??
  (brain.driving.value ? '두뇌가 조종하고 있습니다. 직접 조종하려면 두뇌 칸의 "두뇌에게 조종 맡기기"를 끄세요.' : null),
)
const names = computed(() => new Map((scene.value?.units ?? []).map((unit) => [unit.id, unit.name])))
const nameOf = (id: string) => names.value.get(id) ?? id

function fly(label: string, velocity: FlightVelocity) {
  void sim.send(label, { type: 'velocity', ...velocity })
}

function push(label: string, force: [number, number, number], durationMs: number) {
  void sim.send(label, { type: 'push', force, durationMs })
}

function reset(scenario: string) {
  void sim.send('처음으로', { type: 'reset', scenario: scenario as ScenarioName })
}

const fire = () => void sim.send('쏘기', { type: 'fire' })
const aim = (unit: string) => void sim.send(`${nameOf(unit)} 겨누기`, { type: 'aim', unit })
const guard = (unit: string) => void sim.send(`${nameOf(unit)} 쪽 방패`, { type: 'guard', raised: true, unit })
const lowerAim = () => void sim.send('소총 내리기', { type: 'lowerAim' })
const lowerGuard = () => void sim.send('방패 내리기', { type: 'guard', raised: false })
</script>

<template>
  <n-config-provider :locale="koKR" :date-locale="dateKoKR">
    <n-message-provider>
      <div class="page">
        <header class="header">
          <div>
            <h1>로봇 두뇌 시험장</h1>
            <p class="subtitle">
              날고 무장한 시험 기체 {{ scene?.robot.name ?? '' }}와 두뇌 — 말로 명령하면 느린 뇌(System 2)가 계획을 짜고, 빠른 뇌(System 1)가 날고 쏘고 피합니다. 시험과 점수로 여러 판을 돌려 견줍니다
            </p>
          </div>
          <n-tooltip>
            <template #trigger>
              <n-tag :type="phaseLabel.type" data-test="phase" round>{{ phaseLabel.text }}</n-tag>
            </template>
            {{ phaseLabel.help }}
          </n-tooltip>
        </header>

        <n-alert v-if="phase === 'failed'" type="error" title="몸(시뮬레이터)에 연결하지 못했습니다" class="banner">
          <p>{{ phaseDetail }}</p>
          <p class="muted">저장소 맨 위에서 <code>docker compose up -d sim</code> 으로 띄울 수 있습니다.</p>
          <n-button type="primary" data-test="retry" @click="sim.retry">다시 시도</n-button>
        </n-alert>
        <n-alert v-else-if="phase === 'reconnecting'" type="warning" class="banner">{{ phaseDetail }}</n-alert>

        <main v-if="scene" class="layout">
          <section class="view" aria-label="3D 화면">
            <robot-view :client="client" :scene="scene" />
          </section>
          <aside class="side">
            <mecha-panel :state="state" :names="names" :stale="phase !== 'open'" />
            <order-panel :phase="brain.phase.value" :status="brain.status.value" :error="brain.orderError.value" :names="names"
                         @order="brain.order" @cancel-plan="brain.cancelPlan" />
            <brain-panel :phase="brain.phase.value" :status="brain.status.value" :decisions="brain.decisions.value"
                         :last-error="brain.lastError.value" :units="state?.units ?? []" @set-autonomy="brain.setAutonomy"
                         @set-skill="brain.setSkill" @retry="brain.retry" />
            <units-panel :state="state" :disabled-reason="manualDisabledReason" @aim="aim" @guard="guard" @fire="fire"
                         @lower-aim="lowerAim" @lower-guard="lowerGuard" />
            <scenario-panel :scenarios="scene.scenarios" :current="state?.scenario ?? null"
                            :disabled-reason="disabledReason" @reset="reset" />
            <flight-panel :limits="scene.limits" :heading="state?.mecha.heading ?? 0" :disabled-reason="manualDisabledReason"
                          :destroyed="state?.mecha.mode === 'destroyed'" @fly="fly" @push="push" @fire="fire" />
            <combat-log :entries="combatEntries" :names="names" />
            <command-log :entries="commandEntries" />
          </aside>
        </main>
        <p v-else-if="phase === 'loading-scene'" class="loading">몸(시뮬레이터)에서 시험장 모양을 받는 중입니다…</p>
        <section v-if="scene" class="trials" aria-label="시험과 점수">
          <trial-panel :phase="brain.phase.value" :status="brain.status.value" :scenarios="scene.scenarios"
                       :error="brain.trialError.value" @start="brain.startTrials" @stop="brain.stopTrials" />
        </section>
      </div>
    </n-message-provider>
  </n-config-provider>
</template>

<style>
body {
  margin: 0;
  font-family: system-ui, -apple-system, 'Segoe UI', 'Malgun Gothic', sans-serif;
  background: #f1f5f9;
  color: #0f172a;
}
</style>

<style scoped>
.page {
  max-width: 1700px;
  margin: 0 auto;
  padding: 16px;
}
.header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
  margin-bottom: 12px;
}
h1 {
  margin: 0;
  font-size: 22px;
}
.subtitle {
  margin: 4px 0 0;
  color: #475569;
  font-size: 13px;
}
.banner {
  margin-bottom: 12px;
}
.muted {
  color: #64748b;
  font-size: 12px;
}
.layout {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 400px;
  gap: 12px;
  align-items: start;
}
.view {
  position: sticky;
  top: 12px;
  height: calc(100vh - 120px);
  min-height: 420px;
}
.side {
  display: flex;
  flex-direction: column;
  gap: 12px;
}
.trials {
  margin-top: 12px;
}
.loading {
  color: #475569;
}
@media (max-width: 900px) {
  .layout {
    grid-template-columns: 1fr;
  }
  .view {
    position: static;
    height: 60vh;
  }
}
</style>
