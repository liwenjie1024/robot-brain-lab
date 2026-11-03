<script setup lang="ts">
import { NButton, NCard, NEmpty, NProgress, NSpace, NTag } from 'naive-ui'
import { computed } from 'vue'
import type { StateMessage } from '@shared/sim/generated/message'
import { distance, formatMeters, formatSeconds } from '@/utils/labels'

/** 이 장면의 드론과 무장: 겨누기, 방패로 막기, 쏘기 */
const props = defineProps<{
  state: StateMessage | null
  /** 명령을 보낼 수 없으면 그 까닭 */
  disabledReason: string | null
}>()

const emit = defineEmits<{
  aim: [unit: string]
  guard: [unit: string]
  fire: []
  lowerAim: []
  lowerGuard: []
}>()

const PERCENT = 100

const drones = computed(() => {
  const state = props.state
  if (!state) {
    return []
  }
  const threats = new Map(state.threats.map((threat) => [threat.from, threat.secondsToFire]))
  return state.units.map((unit) => ({
    ...unit,
    hpPercent: (unit.hp / unit.maxHp) * PERCENT,
    range: distance(unit.position, state.mecha.position),
    secondsToFire: threats.get(unit.id),
    aimed: state.mecha.weapon.aimTarget === unit.id,
    guarded: state.mecha.guard.raised && state.mecha.guard.unit === unit.id,
  }))
})
const mecha = computed(() => props.state?.mecha)
const blocked = computed(() => !!props.disabledReason || mecha.value?.mode === 'destroyed')
</script>

<template>
  <n-card title="드론과 무장" size="small">
    <n-space class="weapons">
      <n-button type="primary" data-test="fire" :disabled="blocked" @click="emit('fire')">쏘기 (X)</n-button>
      <n-button data-test="lower-aim" :disabled="blocked || !mecha?.weapon.aimTarget" @click="emit('lowerAim')">
        소총 내리기
      </n-button>
      <n-button data-test="lower-guard" :disabled="blocked || !mecha?.guard.raised" @click="emit('lowerGuard')">
        방패 내리기
      </n-button>
    </n-space>
    <p class="hint">사격은 총열이 실제로 가리키는 쪽으로 나갑니다. 겨눈 뒤 "어긋남"이 1° 안쪽일 때 쏘면 잘 맞습니다.</p>

    <n-empty v-if="drones.length === 0" description="이 시험 장면에는 드론이 없습니다" />
    <ul v-else class="drones" data-test="drones">
      <li v-for="drone in drones" :key="drone.id" :class="{ down: !drone.alive }">
        <div class="row">
          <strong>{{ drone.name }}</strong>
          <n-tag size="small" :type="drone.alive ? 'success' : 'default'">{{ drone.alive ? '살아 있음' : '파괴됨' }}</n-tag>
          <n-tag v-if="drone.armed && drone.alive" size="small" type="warning">반격함</n-tag>
          <n-tag v-if="drone.secondsToFire !== undefined" size="small" type="error" data-test="drone-threat">
            조준 중 · {{ formatSeconds(drone.secondsToFire) }}
          </n-tag>
          <span class="range">{{ formatMeters(drone.range) }}</span>
        </div>
        <n-progress type="line" :percentage="drone.hpPercent" :show-indicator="false"
                    :status="drone.alive ? 'error' : 'default'" :aria-label="`${drone.name} 체력 ${drone.hp}`" />
        <n-space size="small" class="actions">
          <n-button size="small" :type="drone.aimed ? 'primary' : 'default'" :data-test="`aim-${drone.id}`"
                    :disabled="blocked || !drone.alive" @click="emit('aim', drone.id)">
            {{ drone.aimed ? '겨누는 중' : '겨누기' }}
          </n-button>
          <n-button size="small" :type="drone.guarded ? 'info' : 'default'" :data-test="`guard-${drone.id}`"
                    :disabled="blocked || !drone.alive" @click="emit('guard', drone.id)">
            {{ drone.guarded ? '방패로 막는 중' : '방패로 막기' }}
          </n-button>
        </n-space>
      </li>
    </ul>
  </n-card>
</template>

<style scoped>
.weapons {
  margin-bottom: 4px;
}
.hint {
  margin: 4px 0 10px;
  color: #64748b;
  font-size: 12px;
}
.drones {
  margin: 0;
  padding: 0;
  list-style: none;
}
.drones li {
  padding: 8px 0;
  border-bottom: 1px solid #e2e8f0;
}
.drones li.down {
  opacity: 0.6;
}
.row {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 6px;
  margin-bottom: 4px;
}
.range {
  margin-left: auto;
  color: #64748b;
  font-size: 12px;
  font-variant-numeric: tabular-nums;
}
.actions {
  margin-top: 6px;
}
</style>
