<script setup lang="ts">
import { NAlert, NCard, NDescriptions, NDescriptionsItem, NEmpty, NProgress, NTag, NTooltip } from 'naive-ui'
import { computed } from 'vue'
import type { StateMessage } from '@shared/sim/generated/message'
import { formatDegrees, formatMeters, formatSeconds, formatSpeed, MODE_LABELS } from '@/utils/labels'

/** 기체 상태: 비행 모드, 체력·에너지, 소총·방패, 위협 경고, 명령한 속도와 실제 속도 */
const props = defineProps<{
  state: StateMessage | null
  /** 유닛 번호 → 이름 */
  names: ReadonlyMap<string, string>
  /** 연결이 끊겨 마지막으로 받은 상태를 보여 주는 중 */
  stale: boolean
}>()

const ENERGY_PER_SHOT = 20
const PERCENT = 100

const mecha = computed(() => props.state?.mecha)
const mode = computed(() => (mecha.value ? MODE_LABELS[mecha.value.mode] : null))
const hpPercent = computed(() => (mecha.value ? (mecha.value.hp / mecha.value.maxHp) * PERCENT : 0))
const nameOf = (id: string | null | undefined) => (id ? (props.names.get(id) ?? id) : '')

const weaponText = computed(() => {
  const weapon = mecha.value?.weapon
  if (!weapon || !mecha.value) {
    return ''
  }
  if (weapon.ready) {
    return '쏠 수 있음'
  }
  if (weapon.cooldown > 0) {
    return `식는 중 (${formatSeconds(weapon.cooldown)})`
  }
  return mecha.value.energy < ENERGY_PER_SHOT ? '에너지 모자람' : '쏠 수 없음'
})

const rows = computed(() => {
  const value = mecha.value
  if (!value) {
    return []
  }
  return [
    { label: '앞뒤', command: formatSpeed(value.command.forward, 'm/s'), actual: formatSpeed(value.velocity.forward, 'm/s') },
    { label: '옆', command: formatSpeed(value.command.sideways, 'm/s'), actual: formatSpeed(value.velocity.sideways, 'm/s') },
    { label: '위아래', command: formatSpeed(value.command.up, 'm/s'), actual: formatSpeed(value.velocity.up, 'm/s') },
    { label: '돌기', command: formatSpeed(value.command.turn, 'rad/s'), actual: formatSpeed(value.velocity.turn, 'rad/s') },
  ]
})
</script>

<template>
  <n-card title="기체 상태" size="small">
    <template #header-extra>
      <n-tooltip v-if="mode">
        <template #trigger>
          <n-tag :type="mode.type" data-test="mode" round>{{ mode.text }}</n-tag>
        </template>
        {{ mode.help }}
      </n-tooltip>
    </template>
    <n-empty v-if="!state || !mecha" description="아직 상태를 받지 못했습니다" />
    <template v-else>
      <p v-if="stale" class="stale" data-test="stale">
        연결이 끊겨 마지막으로 받은 상태입니다. 지금 기체의 상태와 다를 수 있습니다.
      </p>
      <n-alert v-for="threat in state.threats" :key="threat.from" type="error" class="threat" :show-icon="false"
               data-test="threat">
        ⚠ {{ nameOf(threat.from) }}이(가) 조준 중 — {{ formatSeconds(threat.secondsToFire) }} 뒤 사격
      </n-alert>

      <div class="bar">
        <span>체력 {{ Math.round(mecha.hp) }} / {{ mecha.maxHp }}</span>
        <n-progress type="line" :percentage="hpPercent" :show-indicator="false"
                    :status="hpPercent > 50 ? 'success' : hpPercent > 25 ? 'warning' : 'error'" />
      </div>
      <div class="bar">
        <span>소총 에너지 {{ Math.round(mecha.energy) }} / 100 (한 번 쏘는 데 {{ ENERGY_PER_SHOT }})</span>
        <n-progress type="line" :percentage="mecha.energy" :show-indicator="false" status="info" />
      </div>

      <n-descriptions :column="1" label-placement="left" size="small" class="facts">
        <n-descriptions-item label="소총">
          <n-tag size="small" :type="mecha.weapon.ready ? 'success' : 'warning'" data-test="weapon">{{ weaponText }}</n-tag>
          <span v-if="mecha.weapon.aimTarget" class="muted">
            {{ nameOf(mecha.weapon.aimTarget) }} 겨눔<template v-if="mecha.weapon.aimError !== undefined">,
              어긋남 {{ mecha.weapon.aimError.toFixed(1) }}°</template>
          </span>
        </n-descriptions-item>
        <n-descriptions-item label="방패">
          <span data-test="guard">{{ mecha.guard.raised ? `올림 (${mecha.guard.unit ? nameOf(mecha.guard.unit) + ' 쪽' : '앞'})` : '내림' }}</span>
        </n-descriptions-item>
        <n-descriptions-item label="높이">{{ formatMeters(mecha.altitude) }} (발바닥 기준)</n-descriptions-item>
        <n-descriptions-item label="기수 방향">{{ formatDegrees(mecha.heading) }}</n-descriptions-item>
        <n-descriptions-item label="지난 시간">{{ formatSeconds(state.simTime) }}</n-descriptions-item>
      </n-descriptions>

      <table class="speeds" data-test="speeds">
        <caption>속도 (명령한 값 → 실제 값)</caption>
        <tbody>
          <tr v-for="row in rows" :key="row.label">
            <th scope="row">{{ row.label }}</th>
            <td>{{ row.command }}</td>
            <td>{{ row.actual }}</td>
          </tr>
        </tbody>
      </table>
      <p v-if="mecha.pushing" class="pushing" data-test="pushing">⚠ 지금 밀고 있습니다</p>
    </template>
  </n-card>
</template>

<style scoped>
.stale {
  margin: 0 0 8px;
  padding: 6px 8px;
  border-radius: 4px;
  background: #fef3c7;
  color: #92400e;
  font-size: 12px;
}
.threat {
  margin-bottom: 6px;
  font-weight: 600;
}
.bar {
  margin-bottom: 8px;
  font-size: 13px;
}
.facts {
  margin-top: 4px;
}
.muted {
  margin-left: 6px;
  color: #64748b;
  font-size: 12px;
}
.speeds {
  width: 100%;
  margin-top: 8px;
  border-collapse: collapse;
  font-variant-numeric: tabular-nums;
}
.speeds caption {
  text-align: left;
  color: #64748b;
  font-size: 12px;
  padding-bottom: 4px;
}
.speeds th {
  text-align: left;
  font-weight: normal;
  width: 4em;
}
.speeds td {
  text-align: right;
  padding: 2px 0;
}
.pushing {
  margin: 8px 0 0;
  color: #b45309;
}
</style>
