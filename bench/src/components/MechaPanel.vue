<script setup lang="ts">
import { NCard, NEmpty, NProgress, NTag, NTooltip } from 'naive-ui'
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

const SPEED_COLUMNS = [
  { key: 'forward', label: '앞뒤', unit: 'm/s' },
  { key: 'sideways', label: '옆', unit: 'm/s' },
  { key: 'up', label: '위아래', unit: 'm/s' },
  { key: 'turn', label: '돌기', unit: 'rad/s' },
] as const
</script>

<template>
  <n-card title="기체 상태" size="small" class="mecha">
    <template #header-extra>
      <n-tooltip v-if="mode">
        <template #trigger>
          <n-tag :type="mode.type" data-test="mode" round size="small">{{ mode.text }}</n-tag>
        </template>
        {{ mode.help }}
      </n-tooltip>
    </template>
    <n-empty v-if="!state || !mecha" description="아직 상태를 받지 못했습니다" size="small" />
    <template v-else>
      <p v-if="stale" class="stale" data-test="stale">연결이 끊겨 마지막으로 받은 상태입니다. 지금 기체의 상태와 다를 수 있습니다.</p>
      <p v-for="threat in state.threats" :key="threat.from" class="threat" role="alert" data-test="threat">
        ⚠ {{ nameOf(threat.from) }}이(가) 조준 중 — {{ formatSeconds(threat.secondsToFire) }} 뒤 사격
      </p>

      <div class="bars">
        <div>
          <span class="bar-label">체력 {{ Math.round(mecha.hp) }} / {{ mecha.maxHp }}</span>
          <n-progress type="line" :percentage="hpPercent" :show-indicator="false" :height="8"
                      :status="hpPercent > 50 ? 'success' : hpPercent > 25 ? 'warning' : 'error'" />
        </div>
        <div>
          <span class="bar-label">소총 에너지 {{ Math.round(mecha.energy) }} / 100 (한 번에 {{ ENERGY_PER_SHOT }})</span>
          <n-progress type="line" :percentage="mecha.energy" :show-indicator="false" :height="8" status="info" />
        </div>
      </div>

      <dl class="facts">
        <dt>소총</dt>
        <dd>
          <n-tag size="small" :type="mecha.weapon.ready ? 'success' : 'warning'" data-test="weapon">{{ weaponText }}</n-tag>
          <span v-if="mecha.weapon.aimTarget" class="muted">
            {{ nameOf(mecha.weapon.aimTarget) }} 겨눔<template v-if="mecha.weapon.aimError !== undefined">,
              어긋남 {{ mecha.weapon.aimError.toFixed(1) }}°</template>
          </span>
        </dd>
        <dt>방패</dt>
        <dd data-test="guard">{{ mecha.guard.raised ? `올림 (${mecha.guard.unit ? nameOf(mecha.guard.unit) + ' 쪽' : '앞'})` : '내림' }}</dd>
        <dt>높이·기수</dt>
        <dd>{{ formatMeters(mecha.altitude) }} (발바닥) · {{ formatDegrees(mecha.heading) }}</dd>
        <dt>지난 시간</dt>
        <dd>{{ formatSeconds(state.simTime) }}<span v-if="mecha.pushing" class="pushing" data-test="pushing"> · ⚠ 미는 중</span></dd>
      </dl>

      <table class="speeds" data-test="speeds">
        <caption>속도: 명령한 값과 실제 값</caption>
        <thead>
          <tr>
            <th scope="col"><span class="sr-only">구분</span></th>
            <th v-for="column in SPEED_COLUMNS" :key="column.key" scope="col">{{ column.label }}</th>
          </tr>
        </thead>
        <tbody>
          <tr>
            <th scope="row">명령</th>
            <td v-for="column in SPEED_COLUMNS" :key="column.key">{{ formatSpeed(mecha.command[column.key], column.unit) }}</td>
          </tr>
          <tr>
            <th scope="row">실제</th>
            <td v-for="column in SPEED_COLUMNS" :key="column.key">{{ formatSpeed(mecha.velocity[column.key], column.unit) }}</td>
          </tr>
        </tbody>
      </table>
    </template>
  </n-card>
</template>

<style scoped>
/* 칸 너비에 맞춰 줄을 바꾼다 (조종 보기에서는 넓고, 시험 보기에서는 좁다) */
.mecha {
  container-type: inline-size;
}
.stale {
  margin: 0 0 6px;
  padding: 4px 8px;
  border-radius: 4px;
  background: #fef3c7;
  color: #92400e;
  font-size: 12px;
}
.threat {
  margin: 0 0 4px;
  padding: 4px 8px;
  border-radius: 4px;
  background: #fee2e2;
  color: #b91c1c;
  font-size: 13px;
  font-weight: 600;
}
.bars {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 4px 12px;
  margin-bottom: 6px;
}
.bar-label {
  font-size: 12px;
}
.facts {
  display: grid;
  grid-template-columns: auto 1fr auto 1fr;
  gap: 2px 8px;
  margin: 0 0 6px;
  font-size: 12px;
  align-items: center;
}
.facts dt {
  color: #64748b;
}
.facts dd {
  margin: 0;
}
.muted {
  margin-left: 4px;
  color: #64748b;
}
.pushing {
  color: #b45309;
}
.speeds {
  width: 100%;
  border-collapse: collapse;
  font-size: 12px;
  font-variant-numeric: tabular-nums;
}
.speeds caption {
  text-align: left;
  color: #64748b;
  padding-bottom: 2px;
}
.speeds th {
  font-weight: normal;
  color: #64748b;
  text-align: right;
}
.speeds tbody th {
  text-align: left;
  width: 3em;
}
.speeds td {
  text-align: right;
}
.sr-only {
  position: absolute;
  width: 1px;
  height: 1px;
  overflow: hidden;
  clip: rect(0 0 0 0);
}
/* 좁은 칸: 위의 기본 규칙보다 뒤에 두어야 이긴다 */
@container (max-width: 380px) {
  .bars {
    grid-template-columns: 1fr;
  }
  .facts {
    grid-template-columns: auto 1fr;
  }
}
</style>
