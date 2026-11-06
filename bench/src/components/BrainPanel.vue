<script setup lang="ts">
import { NAlert, NButton, NCard, NRadioButton, NRadioGroup, NSelect, NSwitch, NTag, NTooltip } from 'naive-ui'
import { computed, ref, watch } from 'vue'
import type { Evasion, SkillName } from '@shared/brain/generated/control'
import type { BrainStatus } from '@shared/brain/generated/status'
import { EVASION_LABELS, SKILL_LABELS } from '@shared/brain/labels'
import type { UnitStatus } from '@shared/sim/generated/message'
import type { BrainPhase } from '@/brain/brainClient'
import HelpTip from './HelpTip.vue'

/**
 * 빠른 뇌(System 1)를 다루는 칸: 조종 맡기기, 기술·표적·조준 경고 반응 고르기, 지금 하는 일과 지표 (판단 기록은 기록 칸).
 * 기술은 사람이 여기서 직접 고르거나, 말로 명령하면 느린 뇌(System 2)가 계획에 따라 고른다 (명령 칸).
 */
const props = defineProps<{
  phase: BrainPhase
  status: BrainStatus | null
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
const SYSTEM1_HELP =
  '빠른 뇌(System 1)는 몸의 상태가 올 때마다(1초에 50번) 언어 모델 없이 판단합니다. 기술은 여기서 직접 고르거나, 말로 명령하면 느린 뇌가 계획에 따라 고릅니다. 판단 기록은 "기록" 칸에 있습니다.'
const AUTONOMY_HELP = '켜면 두뇌가 비행·사격·방패 명령을 보내고, 직접 조종 칸은 잠깁니다. 끄면 두뇌는 보기만 합니다 (두뇌라면 무엇을 할지만 보입니다).'
const SKILL_HELP = '누르면 고른 표적·반응과 함께 바로 바뀝니다. 말로 한 명령의 계획을 따르던 중이면 계획은 그만둡니다.'
const REACTION_HELP = '조준 경고를 본 뒤 몸이 반사 명령을 받기까지 걸린 시간'
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
  <n-card size="small" class="brain">
    <template #header>
      두뇌 (빠른 뇌)
      <help-tip :text="SYSTEM1_HELP" />
    </template>
    <template #header-extra>
      <n-tag :type="connected ? 'success' : phase === 'connecting' ? 'info' : 'default'" round size="small" data-test="brain-phase">
        {{ connected ? '두뇌 연결됨' : phase === 'connecting' ? '두뇌에 연결하는 중' : '두뇌 꺼짐' }}
      </n-tag>
    </template>

    <div v-if="!connected" data-test="brain-offline">
      <p class="hint">
        두뇌는 따로 띄우는 프로그램입니다. 저장소 맨 위에서 <code>npm run brain</code> 으로 띄우면 여기에 붙습니다.
        두뇌가 없어도 "직접 날려 보기"로 기체를 움직일 수 있습니다.
      </p>
      <n-button size="small" data-test="brain-retry" @click="emit('retry')">다시 연결</n-button>
    </div>

    <template v-else-if="status">
      <div class="autonomy">
        <n-switch :value="status.autonomy" size="small" data-test="autonomy" @update:value="(value: boolean) => emit('setAutonomy', value)" />
        <span>두뇌에게 조종 맡기기</span>
        <help-tip :text="AUTONOMY_HELP" />
        <n-tag v-if="status.autonomy" type="warning" size="small">두뇌가 조종 중</n-tag>
      </div>

      <n-alert v-if="!status.simConnected" type="warning" :show-icon="false" class="notice">두뇌가 몸(시뮬레이터)에 연결되지 않았습니다.</n-alert>
      <n-alert v-if="lastError" type="error" :show-icon="false" class="notice" data-test="brain-error">{{ lastError }}</n-alert>

      <div class="target">
        <label for="brain-target">표적</label>
        <n-select id="brain-target" v-model:value="target" :options="targetOptions" size="small" />
      </div>
      <span id="brain-evasion" class="label">조준 경고를 받으면</span>
      <n-radio-group v-model:value="evasion" size="small" class="evasions" aria-labelledby="brain-evasion">
        <n-radio-button v-for="option in EVASIONS" :key="option.value" :value="option.value" :data-test="`evasion-${option.value}`">
          {{ option.label }}
        </n-radio-button>
      </n-radio-group>
      <span class="label">기술 <help-tip :text="SKILL_HELP" /></span>
      <div class="skills">
        <n-tooltip v-for="skill in SKILLS" :key="skill.name">
          <template #trigger>
            <n-button size="small" :type="status.skill.name === skill.name ? 'primary' : 'default'"
                      :data-test="`skill-${skill.name}`" @click="choose(skill.name)">
              {{ skill.label }}
            </n-button>
          </template>
          {{ skill.help }}
        </n-tooltip>
      </div>

      <p class="activity" data-test="activity">{{ status.activity }}</p>

      <dl v-if="metrics" class="metrics" data-test="metrics">
        <dt>판단 시간</dt>
        <dd>평균 {{ metrics.tickMicrosAvg }}µs · 가장 길게 {{ metrics.tickMicrosMax }}µs</dd>
        <dt>반응 시간 <help-tip :text="REACTION_HELP" /></dt>
        <dd>{{ metrics.lastReactionMs === null ? '아직 없음' : `${metrics.lastReactionMs}ms` }}</dd>
        <dt>사격</dt>
        <dd>{{ metrics.shots }}번 · 맞힘 {{ metrics.hits }}<template v-if="accuracy !== null"> ({{ accuracy }}%)</template> · 격파 {{ metrics.kills }}</dd>
        <dt>받은 피해</dt>
        <dd>{{ metrics.damageTaken }}</dd>
      </dl>
    </template>
    <p v-else class="hint">두뇌의 상태를 기다리는 중입니다…</p>
  </n-card>
</template>

<style scoped>
.hint {
  margin: 0 0 8px;
  color: #64748b;
  font-size: 12px;
}
.autonomy {
  display: flex;
  align-items: center;
  gap: 6px;
  font-weight: 600;
  font-size: 13px;
  margin-bottom: 6px;
}
.notice {
  margin-bottom: 6px;
  font-size: 12px;
}
.target {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 12px;
}
.target label {
  flex: none;
  white-space: nowrap;
}
.label {
  display: block;
  margin: 6px 0 2px;
  font-size: 12px;
  color: #475569;
}
/* 네 버튼을 칸 너비에 맞춰 고르게 나눈다 (좁은 칸에서도 넘치지 않게). 버튼 사이의 구분선도 들어 있어 grid가 아니라 flex로 */
.evasions {
  display: flex;
  width: 100%;
}
.evasions :deep(.n-radio-button) {
  flex: 1;
  padding: 0 2px;
  text-align: center;
  white-space: nowrap;
}
.skills {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 4px;
}
.skills :deep(.n-button) {
  padding: 0 4px;
}
.activity {
  margin: 6px 0;
  padding: 6px 8px;
  border-radius: 6px;
  background: #f1f5f9;
  font-size: 12px;
}
.metrics {
  display: grid;
  grid-template-columns: auto 1fr;
  gap: 1px 8px;
  margin: 0;
  font-size: 12px;
  font-variant-numeric: tabular-nums;
}
.metrics dt {
  color: #64748b;
}
.metrics dd {
  margin: 0;
}
</style>
