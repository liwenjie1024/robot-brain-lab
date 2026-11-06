<script setup lang="ts">
import { NButton, NCard, NEmpty, NProgress, NTag } from 'naive-ui'
import { computed } from 'vue'
import type { StateMessage } from '@shared/sim/generated/message'
import { distance, formatMeters, formatSeconds } from '@/utils/labels'
import HelpTip from './HelpTip.vue'

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
const AIM_HELP = '사격은 총열이 실제로 가리키는 쪽으로 나갑니다. 겨눈 뒤 기체 상태의 "어긋남"이 1° 안쪽일 때 쏘면 잘 맞습니다.'

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
  <n-card size="small" class="units">
    <template #header>
      드론과 무장
      <help-tip :text="AIM_HELP" />
    </template>
    <div class="weapons">
      <n-button type="primary" size="small" data-test="fire" :disabled="blocked" @click="emit('fire')">쏘기 (X)</n-button>
      <n-button size="small" data-test="lower-aim" :disabled="blocked || !mecha?.weapon.aimTarget" @click="emit('lowerAim')">
        소총 내리기
      </n-button>
      <n-button size="small" data-test="lower-guard" :disabled="blocked || !mecha?.guard.raised" @click="emit('lowerGuard')">
        방패 내리기
      </n-button>
    </div>

    <n-empty v-if="drones.length === 0" description="이 시험 장면에는 드론이 없습니다" size="small" />
    <ul v-else class="drones" data-test="drones">
      <li v-for="drone in drones" :key="drone.id" :class="{ down: !drone.alive }">
        <div class="info">
          <strong class="name">{{ drone.name }}</strong>
          <template v-if="drone.alive">
            <span class="hp">
              <n-progress type="line" :percentage="drone.hpPercent" :show-indicator="false" :height="6" status="error"
                          :aria-label="`${drone.name} 체력 ${drone.hp}`" />
            </span>
            <span class="hp-text">체력 {{ drone.hp }}</span>
          </template>
          <n-tag v-else size="small">파괴됨</n-tag>
          <n-tag v-if="drone.armed && drone.alive" size="small" type="warning">반격함</n-tag>
          <n-tag v-if="drone.secondsToFire !== undefined" size="small" type="error" data-test="drone-threat">
            조준 중 · {{ formatSeconds(drone.secondsToFire) }}
          </n-tag>
        </div>
        <div class="actions">
          <span class="range">{{ formatMeters(drone.range) }}</span>
          <n-button size="tiny" :type="drone.aimed ? 'primary' : 'default'" :data-test="`aim-${drone.id}`"
                    :disabled="blocked || !drone.alive" @click="emit('aim', drone.id)">
            {{ drone.aimed ? '겨누는 중' : '겨누기' }}
          </n-button>
          <n-button size="tiny" :type="drone.guarded ? 'info' : 'default'" :data-test="`guard-${drone.id}`"
                    :aria-label="`${drone.name} 쪽으로 방패 들기`" :disabled="blocked || !drone.alive" @click="emit('guard', drone.id)">
            {{ drone.guarded ? '막는 중' : '막기' }}
          </n-button>
        </div>
      </li>
    </ul>
  </n-card>
</template>

<style scoped>
.weapons {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 4px;
  margin-bottom: 4px;
}
.drones {
  margin: 0;
  padding: 0;
  list-style: none;
}
/* 정보(이름·체력·표시)와 할 일(거리·버튼)을 나눠, 칸이 좁으면 할 일 묶음째 다음 줄로 */
.drones li {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: 2px 8px;
  padding: 4px 0;
  border-bottom: 1px solid #e2e8f0;
  font-size: 12px;
}
.info,
.actions {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 4px 6px;
}
.actions {
  margin-left: auto;
}
.drones li:last-child {
  border-bottom: none;
}
.drones li.down {
  opacity: 0.6;
}
.name {
  font-size: 13px;
}
.hp {
  display: inline-block;
  width: 48px;
  flex: none;
}
.hp-text {
  color: #64748b;
  font-variant-numeric: tabular-nums;
}
.range {
  color: #64748b;
  font-size: 12px;
  font-variant-numeric: tabular-nums;
}
</style>
