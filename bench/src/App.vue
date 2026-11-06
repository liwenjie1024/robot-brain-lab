<script setup lang="ts">
import { dateKoKR, koKR, NAlert, NButton, NConfigProvider, NMessageProvider, NRadioButton, NRadioGroup, NTag, NTooltip } from 'naive-ui'
import { computed, ref } from 'vue'
import { BrainClient, brainSocketUrl } from '@/brain/brainClient'
import { useBrain } from '@/brain/useBrain'
import BrainPanel from '@/components/BrainPanel.vue'
import FlightPanel from '@/components/FlightPanel.vue'
import HelpTip from '@/components/HelpTip.vue'
import LogPanel from '@/components/LogPanel.vue'
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

/** 조종은 한 화면에 다 보이게(넘기지 않게) 3D·기체 상태 | 두뇌 | 직접 조종 | 기록으로 나누고, 시험과 점수는 따로 본다 */
type View = 'control' | 'trials'
const view = ref<View>('control')
const ABOUT =
  '날고 무장한 시험 기체와 두뇌를 시험합니다. 말로 명령하면 느린 뇌(System 2)가 계획을 짜고, 빠른 뇌(System 1)가 날고 쏘고 피합니다. "시험과 점수"에서 여러 판을 돌려 견줍니다.'
const TRIAL_RUNNING_REASON = '시험 중입니다. 위의 "시험과 점수"에서 시험을 멈춘 뒤 쓸 수 있습니다.'

const phaseLabel = computed(() => PHASE_LABELS[phase.value])
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
      <div class="app">
        <header class="header">
          <h1>로봇 두뇌 시험장</h1>
          <span class="robot">{{ scene?.robot.name ?? '' }}</span>
          <help-tip :text="ABOUT" />
          <n-radio-group v-model:value="view" size="small" class="views" aria-label="보기" data-test="view">
            <n-radio-button value="control" data-test="view-control">조종</n-radio-button>
            <n-radio-button value="trials" data-test="view-trials">
              시험과 점수<template v-if="brain.trialsRunning.value"> · 시험 중</template>
            </n-radio-button>
          </n-radio-group>
          <n-tooltip>
            <template #trigger>
              <n-tag :type="phaseLabel.type" data-test="phase" round size="small">몸: {{ phaseLabel.text }}</n-tag>
            </template>
            {{ phaseLabel.help }}
          </n-tooltip>
        </header>

        <n-alert v-if="phase === 'failed'" type="error" title="몸(시뮬레이터)에 연결하지 못했습니다" class="banner">
          {{ phaseDetail }} 저장소 맨 위에서 <code>docker compose up -d sim</code> 으로 띄울 수 있습니다.
          <n-button type="primary" size="small" data-test="retry" @click="sim.retry">다시 시도</n-button>
        </n-alert>
        <n-alert v-else-if="phase === 'reconnecting'" type="warning" class="banner">{{ phaseDetail }}</n-alert>

        <main v-if="scene" class="workspace" :class="view" data-test="workspace">
          <section class="view-col" aria-label="3D 화면과 기체 상태">
            <div class="view">
              <robot-view :client="client" :scene="scene" />
            </div>
            <mecha-panel :state="state" :names="names" :stale="phase !== 'open'" />
          </section>

          <section v-show="view === 'control'" class="col brain-col" aria-label="두뇌">
            <order-panel :phase="brain.phase.value" :status="brain.status.value" :error="brain.orderError.value" :names="names"
                         @order="brain.order" @cancel-plan="brain.cancelPlan" />
            <brain-panel :phase="brain.phase.value" :status="brain.status.value" :last-error="brain.lastError.value"
                         :units="state?.units ?? []" @set-autonomy="brain.setAutonomy" @set-skill="brain.setSkill" @retry="brain.retry" />
          </section>
          <section v-show="view === 'control'" class="col manual-col" aria-label="직접 조종">
            <scenario-panel :scenarios="scene.scenarios" :current="state?.scenario ?? null"
                            :disabled-reason="disabledReason" @reset="reset" />
            <flight-panel :limits="scene.limits" :heading="state?.mecha.heading ?? 0" :disabled-reason="manualDisabledReason"
                          :destroyed="state?.mecha.mode === 'destroyed'" :keyboard="view === 'control'" @fly="fly" @push="push"
                          @fire="fire" />
            <units-panel :state="state" :disabled-reason="manualDisabledReason" @aim="aim" @guard="guard" @fire="fire"
                         @lower-aim="lowerAim" @lower-guard="lowerGuard" />
          </section>
          <section v-show="view === 'control'" class="logs-col" aria-label="기록">
            <log-panel :decisions="brain.decisions.value" :combat="combatEntries" :commands="commandEntries" :names="names" />
          </section>

          <section v-show="view === 'trials'" class="trials-col" aria-label="시험과 점수">
            <trial-panel :phase="brain.phase.value" :status="brain.status.value" :scenarios="scene.scenarios"
                         :error="brain.trialError.value" @start="brain.startTrials" @stop="brain.stopTrials" />
          </section>
        </main>
        <p v-else-if="phase === 'loading-scene'" class="loading">몸(시뮬레이터)에서 시험장 모양을 받는 중입니다…</p>
      </div>
    </n-message-provider>
  </n-config-provider>
</template>

<style>
html,
body {
  margin: 0;
  font-family: system-ui, -apple-system, 'Segoe UI', 'Malgun Gothic', sans-serif;
  background: #f1f5f9;
  color: #0f172a;
}
</style>

<style scoped>
/* 한 화면에 다 보이게: 페이지는 넘기지 않고, 칸이 모자라면 그 칸 안에서만 넘긴다 */
.app {
  box-sizing: border-box;
  height: 100vh;
  display: flex;
  flex-direction: column;
  gap: 8px;
  padding: 8px 12px;
  overflow: hidden;
}
.header {
  flex: none;
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
}
h1 {
  margin: 0;
  font-size: 18px;
  white-space: nowrap;
}
.robot {
  color: #475569;
  font-size: 13px;
}
.views {
  margin-left: auto;
}
.banner {
  flex: none;
}
.workspace {
  flex: 1;
  min-height: 0;
  display: grid;
  gap: 8px;
  grid-template-rows: minmax(0, 1fr);
}
.workspace.control {
  grid-template-columns: minmax(320px, 1.1fr) minmax(360px, 1.15fr) minmax(330px, 1fr) minmax(260px, 0.8fr);
  grid-template-areas: 'view brain manual logs';
}
.workspace.trials {
  grid-template-columns: minmax(300px, 0.75fr) minmax(0, 2.5fr);
  grid-template-areas: 'view trials';
}
.view-col {
  grid-area: view;
  min-height: 0;
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.view {
  flex: 1;
  min-height: 200px;
}
.col {
  min-height: 0;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.brain-col {
  grid-area: brain;
}
.manual-col {
  grid-area: manual;
}
.logs-col {
  grid-area: logs;
  min-height: 0;
}
.trials-col {
  grid-area: trials;
  min-height: 0;
}
.loading {
  color: #475569;
}
/* 네 칸의 가장 작은 너비(약 1320px)가 들어가지 않으면 기록을 3D 아래로 내린다 */
@media (max-width: 1319px) {
  .workspace.control {
    grid-template-columns: minmax(340px, 1.15fr) minmax(320px, 1fr) minmax(320px, 1fr);
    grid-template-rows: minmax(0, 1fr) 160px;
    grid-template-areas:
      'view brain manual'
      'logs brain manual';
  }
}
/* 태블릿·휴대폰: 한 줄로 쌓고 페이지를 넘긴다 */
@media (max-width: 1099px) {
  .app {
    height: auto;
    overflow: visible;
  }
  .workspace.control,
  .workspace.trials {
    grid-template-columns: 1fr;
    grid-template-rows: none;
    grid-template-areas: 'view' 'brain' 'manual' 'logs' 'trials';
  }
  .view {
    height: 50vh;
    flex: none;
  }
  .col {
    overflow: visible;
  }
  .logs-col {
    height: 50vh;
  }
}
</style>
