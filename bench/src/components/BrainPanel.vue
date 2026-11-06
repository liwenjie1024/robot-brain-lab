<script setup lang="ts">
import { NAlert, NButton, NCard, NEmpty, NRadioButton, NRadioGroup, NSelect, NSpace, NSwitch, NTag, NTooltip } from 'naive-ui'
import { computed, ref, watch } from 'vue'
import type { Evasion, SkillName } from '@shared/brain/generated/control'
import type { BrainStatus, Decision, DecisionKind } from '@shared/brain/generated/status'
import { EVASION_LABELS, SKILL_LABELS } from '@shared/brain/labels'
import type { UnitStatus } from '@shared/sim/generated/message'
import type { BrainPhase } from '@/brain/brainClient'
import type { TagType } from '@/utils/labels'

/**
 * 빠른 뇌(System 1)를 다루는 칸: 조종 맡기기, 기술·표적·조준 경고 반응 고르기, 지금 하는 일과 판단 기록·지표.
 * 기술은 사람이 여기서 직접 고르거나, 말로 명령하면 느린 뇌(System 2)가 계획에 따라 고른다 (명령 칸).
 */
const props = defineProps<{
  phase: BrainPhase
  status: BrainStatus | null
  decisions: readonly Decision[]
  lastError: string | null
  /** 이 장면의 드론 (표적 고르기) */
  units: readonly UnitStatus[]
}>()

const emit = defineEmits<{
  setAutonomy: [enabled: boolean]
  setSkill: [skill: SkillName, target: string | null, evasion: Evasion]
  retry: []
}>()

const AUTO_TARGET = '__auto__'
const PERCENT = 100

const SKILLS: { name: SkillName; label: string; help: string }[] = [
  { name: 'idle', label: SKILL_LABELS.idle, help: '그 자리에 멈춰 지시를 기다립니다.' },
  { name: 'hold', label: SKILL_LABELS.hold, help: '지금 자리를 붙잡고, 밀려나면 돌아옵니다.' },
  { name: 'engage', label: SKILL_LABELS.engage, help: '드론을 골라 거리를 맞추고, 조준이 맞을 때만 쏩니다.' },
  { name: 'retreat', label: SKILL_LABELS.retreat, help: '드론 반대쪽으로 오르며 물러나고 방패를 듭니다.' },
]
const EVASIONS: { value: Evasion; label: string }[] = (['dodge', 'guard', 'both', 'none'] as const).map((value) => ({
  value,
  label: EVASION_LABELS[value],
}))
const KIND_LABELS: Record<DecisionKind, { text: string; type: TagType }> = {
  skill: { text: '기술', type: 'info' },
  target: { text: '표적', type: 'default' },
  fire: { text: '사격', type: 'warning' },
  reflex: { text: '반사', type: 'error' },
  result: { text: '결과', type: 'success' },
  command: { text: '거절됨', type: 'error' },
  plan: { text: '계획', type: 'info' },
}

const target = ref<string>(AUTO_TARGET)
const evasion = ref<Evasion>('dodge')
watch(
  () => props.status?.skill,
  (skill) => {
    if (skill) {
      target.value = skill.target ?? AUTO_TARGET
      evasion.value = skill.evasion
    }
  },
)

const connected = computed(() => props.phase === 'open')
const targetOptions = computed(() => [
  { label: '두뇌가 고름', value: AUTO_TARGET },
  ...props.units.filter((unit) => unit.alive).map((unit) => ({ label: unit.name, value: unit.id })),
])
const metrics = computed(() => props.status?.metrics)
const accuracy = computed(() => (metrics.value?.shots ? Math.round((metrics.value.hits / metrics.value.shots) * PERCENT) : null))

function choose(skill: SkillName) {
  emit('setSkill', skill, target.value === AUTO_TARGET ? null : target.value, evasion.value)
}
</script>

<template>
  <n-card title="두뇌 (빠른 뇌 System 1)" size="small">
    <template #header-extra>
      <n-tag :type="connected ? 'success' : phase === 'connecting' ? 'info' : 'default'" round data-test="brain-phase">
        {{ connected ? '두뇌 연결됨' : phase === 'connecting' ? '두뇌에 연결하는 중' : '두뇌 꺼짐' }}
      </n-tag>
    </template>

    <div v-if="!connected" data-test="brain-offline">
      <p class="hint">
        두뇌는 따로 띄우는 프로그램입니다. 저장소 맨 위에서 <code>npm run brain</code> 으로 띄우면 여기에 붙습니다.
        두뇌가 없어도 아래 "직접 날려 보기"로 기체를 움직일 수 있습니다.
      </p>
      <n-button size="small" data-test="brain-retry" @click="emit('retry')">다시 연결</n-button>
    </div>

    <template v-else-if="status">
      <div class="autonomy">
        <n-switch :value="status.autonomy" data-test="autonomy" @update:value="(value: boolean) => emit('setAutonomy', value)" />
        <span>두뇌에게 조종 맡기기</span>
        <n-tag v-if="status.autonomy" type="warning" size="small">두뇌가 조종 중</n-tag>
      </div>
      <p class="hint">켜면 두뇌가 비행·사격·방패 명령을 보내고, 직접 조종 칸은 잠깁니다. 끄면 두뇌는 보기만 합니다.</p>

      <n-alert v-if="!status.simConnected" type="warning" :show-icon="false" class="notice">
        두뇌가 몸(시뮬레이터)에 연결되지 않았습니다.
      </n-alert>
      <n-alert v-if="lastError" type="error" :show-icon="false" class="notice" data-test="brain-error">{{ lastError }}</n-alert>

      <label class="label" for="brain-target">표적</label>
      <n-select id="brain-target" v-model:value="target" :options="targetOptions" size="small" />
      <label class="label">조준 경고를 받으면</label>
      <n-radio-group v-model:value="evasion" size="small">
        <n-radio-button v-for="option in EVASIONS" :key="option.value" :value="option.value" :data-test="`evasion-${option.value}`">
          {{ option.label }}
        </n-radio-button>
      </n-radio-group>

      <label class="label">기술 (누르면 위의 표적·반응과 함께 바로 바뀝니다. 따르던 계획은 그만둡니다)</label>
      <n-space size="small">
        <n-tooltip v-for="skill in SKILLS" :key="skill.name">
          <template #trigger>
            <n-button size="small" :type="status.skill.name === skill.name ? 'primary' : 'default'"
                      :data-test="`skill-${skill.name}`" @click="choose(skill.name)">
              {{ skill.label }}
            </n-button>
          </template>
          {{ skill.help }}
        </n-tooltip>
      </n-space>

      <p class="activity" data-test="activity">{{ status.activity }}</p>

      <table v-if="metrics" class="metrics" data-test="metrics">
        <tbody>
          <tr>
            <th scope="row">판단 시간</th>
            <td>평균 {{ metrics.tickMicrosAvg }}µs · 가장 길게 {{ metrics.tickMicrosMax }}µs</td>
          </tr>
          <tr>
            <th scope="row">반응 시간</th>
            <td>
              {{ metrics.lastReactionMs === null ? '아직 없음' : `${metrics.lastReactionMs}ms` }}
              <span class="muted">(조준 경고를 본 뒤 몸이 반사 명령을 받기까지)</span>
            </td>
          </tr>
          <tr>
            <th scope="row">사격</th>
            <td>{{ metrics.shots }}번 · 맞힘 {{ metrics.hits }}<template v-if="accuracy !== null"> ({{ accuracy }}%)</template> · 격파 {{ metrics.kills }}</td>
          </tr>
          <tr>
            <th scope="row">받은 피해</th>
            <td>{{ metrics.damageTaken }}</td>
          </tr>
        </tbody>
      </table>

      <h3>판단 기록</h3>
      <n-empty v-if="decisions.length === 0" description="아직 판단 기록이 없습니다" size="small" />
      <ol v-else class="decisions" data-test="decisions">
        <li v-for="decision in decisions" :key="decision.seq">
          <span class="time">{{ decision.simTime === null ? '' : `${decision.simTime.toFixed(1)}초` }}</span>
          <n-tag size="small" :type="KIND_LABELS[decision.kind].type">{{ KIND_LABELS[decision.kind].text }}</n-tag>
          <span>{{ decision.text }}</span>
        </li>
      </ol>
    </template>
    <p v-else class="hint">두뇌의 상태를 기다리는 중입니다…</p>
  </n-card>
</template>

<style scoped>
.hint {
  margin: 6px 0 10px;
  color: #64748b;
  font-size: 12px;
}
.autonomy {
  display: flex;
  align-items: center;
  gap: 8px;
  font-weight: 600;
}
.notice {
  margin-bottom: 8px;
}
.label {
  display: block;
  font-size: 13px;
  margin: 10px 0 4px;
}
.activity {
  margin: 12px 0 8px;
  padding: 8px;
  border-radius: 6px;
  background: #f1f5f9;
  font-size: 13px;
}
.metrics {
  width: 100%;
  border-collapse: collapse;
  font-size: 12px;
  font-variant-numeric: tabular-nums;
}
.metrics th {
  text-align: left;
  font-weight: normal;
  color: #475569;
  width: 5.5em;
  padding: 2px 0;
  vertical-align: top;
}
.muted {
  color: #94a3b8;
}
h3 {
  margin: 12px 0 6px;
  font-size: 13px;
}
.decisions {
  max-height: 260px;
  overflow-y: auto;
  margin: 0;
  padding: 0;
  list-style: none;
  font-size: 12px;
}
.decisions li {
  display: flex;
  align-items: baseline;
  gap: 6px;
  padding: 3px 0;
  border-bottom: 1px solid #e2e8f0;
}
.time {
  min-width: 3.5em;
  color: #64748b;
  font-variant-numeric: tabular-nums;
}
</style>
