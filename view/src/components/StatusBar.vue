<script setup lang="ts">
// 最上面的一条：连没连上、测试台上是哪个身体、现在是什么情况、仿真走到哪了。
import { computed } from 'vue'
import { NButton, NSelect, NTag, useMessage } from 'naive-ui'
import HelpTip from '@/components/HelpTip.vue'
import { speedText, standingOf } from '@/sim/derive'
import type { Sim } from '@/sim/useSim'
import { asDuration } from '@/text/format'
import { LINK_LABELS, STANDING_LABELS } from '@/text/labels'

const props = defineProps<{ sim: Sim }>()
const message = useMessage()

const link = computed(() => LINK_LABELS[props.sim.link.value])
const state = computed(() => props.sim.shown.value)
const standing = computed(() => (state.value ? STANDING_LABELS[standingOf(state.value)] : null))
const bodyOptions = computed(() =>
  (props.sim.scene.value?.choices ?? []).map((choice) => ({
    label: choice.available ? choice.name : `${choice.name}（现在用不了）`,
    value: choice.body,
    disabled: !choice.available,
  })),
)
const unavailable = computed(() =>
  (props.sim.scene.value?.choices ?? [])
    .filter((choice) => !choice.available)
    .map((choice) => `${choice.name}：${choice.reason}`)
    .join('\n'),
)

async function choose(body: string): Promise<void> {
  if (body === props.sim.scene.value?.body) return
  try {
    await props.sim.selectBody(body)
  } catch (error) {
    message.error(error instanceof Error ? error.message : String(error))
  }
}
</script>

<template>
  <header class="bar">
    <h1 class="bar-title">Nova：看得见</h1>

    <div class="bar-item">
      <n-tag :type="link.type" :bordered="false" :title="link.hint">{{ link.label }}</n-tag>
      <n-button v-if="sim.link.value === 'closed'" size="small" @click="sim.retryLink()">再连一次</n-button>
    </div>

    <div class="bar-item">
      <span class="bar-label">身体</span>
      <n-select
        class="bar-body"
        size="small"
        :value="sim.scene.value?.body ?? null"
        :options="bodyOptions"
        :disabled="sim.stale.value || !sim.scene.value"
        placeholder="还没拿到"
        aria-label="放上测试台的身体"
        @update:value="choose"
      />
      <help-tip v-if="unavailable" :text="unavailable" />
    </div>

    <div v-if="state && standing" class="bar-item" :class="{ 'bar-old': sim.stale.value }">
      <n-tag :type="standing.type" :bordered="false" :title="standing.hint">{{ standing.label }}</n-tag>
      <span>第 {{ state.episode + 1 }} 回 · {{ asDuration(state.time_s) }}</span>
      <span class="bar-label">{{ speedText(state) }}</span>
      <help-tip
        text="仿真里的时间和墙上的钟一样快，才是实时。电脑算不过来的时候仿真会比钟慢，但不会算错。没有网页看着的时候，仿真停着不走。"
      />
    </div>
  </header>
</template>

<style scoped>
.bar {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px 20px;
  padding: 10px 16px;
  background: #ffffff;
  border-bottom: 1px solid #e3e5ea;
}
.bar-title {
  margin: 0;
  font-size: 18px;
  font-weight: 600;
}
.bar-item {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 14px;
}
.bar-label {
  color: #5c6370;
}
.bar-body {
  width: 190px;
}
.bar-old {
  opacity: 0.55;
}
</style>
