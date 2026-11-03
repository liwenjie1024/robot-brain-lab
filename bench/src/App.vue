<script setup lang="ts">
import { dateKoKR, koKR, NAlert, NButton, NConfigProvider, NMessageProvider, NTag, NTooltip } from 'naive-ui'
import { computed } from 'vue'
import CommandLog from '@/components/CommandLog.vue'
import ControlPanel from '@/components/ControlPanel.vue'
import RobotView from '@/components/RobotView.vue'
import StatusPanel from '@/components/StatusPanel.vue'
import type { Velocity } from '@/control/drive'
import { SimClient } from '@/sim/simClient'
import { useSim } from '@/sim/useSim'
import { PHASE_LABELS } from '@/utils/labels'

const SIM_BASE_URL = '/sim'

const client = new SimClient({ baseUrl: SIM_BASE_URL })
const sim = useSim(client)
const { phase, phaseDetail, scene, state, log } = sim

const phaseLabel = computed(() => PHASE_LABELS[phase.value])
const disabledReason = computed(() =>
  phase.value === 'open' ? null : '몸(시뮬레이터)과 연결되어야 명령을 보낼 수 있습니다.',
)

function drive(label: string, velocity: Velocity) {
  void sim.send(label, { type: 'velocity', ...velocity })
}

function push(label: string, force: [number, number, number], durationMs: number) {
  void sim.send(label, { type: 'push', force, durationMs })
}

function reset() {
  void sim.send('처음 자세로', { type: 'reset' })
}
</script>

<template>
  <n-config-provider :locale="koKR" :date-locale="dateKoKR">
    <n-message-provider>
      <div class="page">
        <header class="header">
          <div>
            <h1>로봇 두뇌 시험장</h1>
            <p class="subtitle">1단계: 몸(물리 시뮬레이션)과 운동 제어(System 0) — 사람이 걷기 명령을 직접 보냅니다</p>
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
            <status-panel :state="state" :stale="phase !== 'open'" />
            <control-panel :limits="scene.limits" :yaw="state?.robot.yaw ?? 0" :disabled-reason="disabledReason"
                           :fallen="state?.robot.posture === 'fallen'" @drive="drive" @push="push" @reset="reset" />
            <command-log :entries="log" />
          </aside>
        </main>
        <p v-else-if="phase === 'loading-scene'" class="loading">몸(시뮬레이터)에서 모양을 받는 중입니다…</p>
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
  max-width: 1600px;
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
  grid-template-columns: minmax(0, 1fr) 380px;
  gap: 12px;
}
.view {
  height: calc(100vh - 120px);
  min-height: 420px;
}
.side {
  display: flex;
  flex-direction: column;
  gap: 12px;
}
.loading {
  color: #475569;
}
@media (max-width: 900px) {
  .layout {
    grid-template-columns: 1fr;
  }
  .view {
    height: 60vh;
  }
}
</style>
