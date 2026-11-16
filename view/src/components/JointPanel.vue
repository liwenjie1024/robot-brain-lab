<script setup lang="ts">
// 关节的力矩：每个关节的驱动器现在出多大的力，是它最多能出的百分之几。按身体的部分分组。
import { computed } from 'vue'
import { NCard, NEmpty } from 'naive-ui'
import HelpTip from '@/components/HelpTip.vue'
import { effortOf, hardestJoint, jointRows, rowsByRegion } from '@/sim/derive'
import type { Sim } from '@/sim/useSim'
import { asPercent, fixed } from '@/text/format'
import { EFFORT_LABELS } from '@/text/labels'

const props = defineProps<{ sim: Sim }>()

// 一开始打开腿这一组：站着的时候最费力的关节在腿上。
const OPEN_AT_FIRST = '腿'
const FULL = 100

const rows = computed(() => {
  const scene = props.sim.scene.value
  const state = props.sim.shown.value
  return scene && state ? jointRows(scene, state) : []
})
const regions = computed(() => rowsByRegion(rows.value))
const hardest = computed(() => hardestJoint(rows.value))

const effort = (share: number) => EFFORT_LABELS[effortOf(share)]
const barWidth = (share: number) => `${Math.min(share, 1) * FULL}%`
</script>

<template>
  <n-card size="small">
    <template #header>
      关节的力矩
      <help-tip
        text="力矩是驱动器拧关节的劲。条越长，离这个驱动器最多能出的力矩（峰值）越近。站着不动的时候应该都很短：站着不费力。"
      />
    </template>
    <n-empty v-if="rows.length === 0" description="还没有收到状态" size="small" />
    <template v-else>
      <p v-if="hardest" class="summary">
        现在最费力的是 <strong>{{ hardest.label }}</strong
        >：{{ fixed(Math.abs(hardest.torqueNm), 1) }} N·m，是峰值的 {{ asPercent(hardest.share) }}（{{
          effort(hardest.share).label
        }}）
      </p>
      <!-- 用浏览器自带的折叠（details）：组件库的折叠面板不会跟着状态更新里面的数。 -->
      <details v-for="group in regions" :key="group.region" class="group" :open="group.region === OPEN_AT_FIRST">
        <summary>
          {{ group.region }}（{{ group.rows.length }} 个）
          <span class="group-note">最费力：{{ group.hardest.label }} {{ asPercent(group.hardest.share) }}</span>
        </summary>
        <table class="joints">
          <thead>
            <tr>
              <th scope="col">关节</th>
              <th scope="col">出的力矩</th>
              <th scope="col" class="number">N·m</th>
              <th scope="col" class="number">是峰值的</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="row in group.rows" :key="row.name">
              <th scope="row">{{ row.label }}</th>
              <td>
                <div class="bar" role="img" :aria-label="`${effort(row.share).label}，峰值的 ${asPercent(row.share)}`">
                  <div class="bar-fill" :style="{ width: barWidth(row.share), background: effort(row.share).color }"></div>
                </div>
              </td>
              <td class="number">{{ fixed(row.torqueNm, 1) }}</td>
              <td class="number" :style="{ color: effort(row.share).color }">
                {{ asPercent(row.share) }} {{ effort(row.share).label }}
              </td>
            </tr>
          </tbody>
        </table>
      </details>
    </template>
  </n-card>
</template>

<style scoped>
.summary {
  margin: 0 0 8px;
  font-size: 13px;
}
.group {
  border-top: 1px solid #e9ebef;
  padding: 6px 0;
}
.group summary {
  cursor: pointer;
  font-size: 14px;
  user-select: none;
}
.group summary:focus-visible {
  outline: 2px solid #1f6fd1;
  outline-offset: 2px;
}
.group[open] summary {
  margin-bottom: 6px;
}
.group-note {
  margin-left: 10px;
  color: #5c6370;
  font-size: 12px;
}
.joints {
  width: 100%;
  border-collapse: collapse;
  font-size: 13px;
  font-variant-numeric: tabular-nums;
}
.joints th {
  font-weight: 400;
  text-align: left;
  white-space: nowrap;
}
.joints thead th {
  color: #8a8f98;
  font-size: 12px;
}
.joints td,
.joints th {
  padding: 2px 6px 2px 0;
}
.number {
  text-align: right !important;
  white-space: nowrap;
}
.bar {
  width: 100%;
  min-width: 70px;
  height: 8px;
  background: #e9ebef;
  border-radius: 4px;
  overflow: hidden;
}
.bar-fill {
  height: 100%;
  min-width: 2px;
  border-radius: 4px;
}
</style>
