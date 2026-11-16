<script setup lang="ts">
// 3D 的身体：照仿真给的样子搭出来，跟着状态动。可以自己转着看，也可以从身体的相机看出去。
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { NAlert, NButton, NCheckbox, NProgress, NSelect, NSpin } from 'naive-ui'
import HelpTip from '@/components/HelpTip.vue'
import type { Stage } from '@/stage/stage'
import type { Sim } from '@/sim/useSim'

const props = defineProps<{ sim: Sim }>()

/** 自己转着看。别的选项是身体上第几台相机。 */
const FREE_VIEW = -1

const holder = ref<HTMLDivElement | null>(null)
const canvas = ref<HTMLCanvasElement | null>(null)
const view = ref(FREE_VIEW)
const markers = ref(true)
const drawProblem = ref<string | null>(null)
let stage: Stage | null = null
let frame = 0
let gone = false
let observer: ResizeObserver | null = null

const viewOptions = computed(() => [
  { label: '自己转着看', value: FREE_VIEW },
  ...(props.sim.scene.value?.cameras ?? []).map((camera, index) => ({ label: `从${camera.label}看`, value: index })),
])
const loadingPercent = computed(() => {
  const loading = props.sim.loading.value
  return loading ? Math.round((100 * loading.done) / loading.total) : 0
})
const fromBody = computed(() => view.value !== FREE_VIEW)

function fit(): void {
  if (holder.value && stage) stage.resize(holder.value.clientWidth, holder.value.clientHeight)
}

function draw(): void {
  frame = requestAnimationFrame(draw)
  if (!stage) return
  const state = props.sim.latest()
  if (state) stage.update(state)
  stage.render()
}

function showBody(): void {
  const scene = props.sim.scene.value
  if (!stage || !scene) return
  try {
    stage.setFigure(scene, props.sim.meshes.value)
    view.value = FREE_VIEW
    drawProblem.value = null
  } catch (error) {
    drawProblem.value = error instanceof Error ? error.message : String(error)
  }
}

onMounted(async () => {
  // 3D 的那一大块程序（three.js）到要画的时候才去拿，这样网页别的部分先出来。
  const loaded = await import('@/stage/stage').catch(() => null)
  if (gone || !canvas.value || !holder.value) return
  if (!loaded) {
    drawProblem.value = '3D 的那一部分没有加载出来。刷新这一页再试。'
    return
  }
  try {
    stage = new loaded.Stage(canvas.value)
  } catch {
    drawProblem.value = '这个浏览器画不了 3D（没有 WebGL）。换一个浏览器，或者打开显卡加速再试。'
    return
  }
  observer = new ResizeObserver(fit)
  observer.observe(holder.value)
  fit()
  showBody()
  draw()
})

onBeforeUnmount(() => {
  gone = true
  cancelAnimationFrame(frame)
  observer?.disconnect()
  stage?.dispose()
  stage = null
})

watch(() => props.sim.scene.value, showBody)
watch(view, (chosen) => stage?.setView(chosen === FREE_VIEW ? null : chosen))
watch(markers, (wanted) => stage?.showMarkers(wanted))
</script>

<template>
  <div ref="holder" class="stage">
    <canvas ref="canvas" class="stage-canvas" aria-label="身体的 3D 图"></canvas>

    <div v-if="sim.scene.value && !drawProblem" class="stage-tools">
      <n-select v-model:value="view" :options="viewOptions" size="small" class="stage-view" aria-label="从哪里看" />
      <n-checkbox v-model:checked="markers" :disabled="fromBody">
        重心和压力中心
        <help-tip
          text="红色的球是重心，下面的红线是它落在地面上的位置。蓝色的圈是压力中心：地面托着身体的力合起来作用的那一点。压力中心在重心的正下面，身体就不会歪。"
        />
      </n-checkbox>
    </div>
    <div v-if="fromBody" class="stage-note">这是网页照相机的位置画出来的，不是相机拍到的画面。</div>

    <div v-if="drawProblem" class="stage-cover">
      <n-alert type="error" title="3D 画不出来">{{ drawProblem }}</n-alert>
    </div>
    <div v-else-if="sim.sceneError.value" class="stage-cover">
      <n-alert type="error" title="没拿到身体的样子">
        {{ sim.sceneError.value }}
        <div class="stage-retry"><n-button size="small" type="primary" @click="sim.retryScene()">再试一次</n-button></div>
      </n-alert>
    </div>
    <div v-else-if="sim.loading.value" class="stage-cover">
      <div class="stage-loading">
        <n-spin size="small" />
        <span>正在拿身体的样子（{{ sim.loading.value.done }} / {{ sim.loading.value.total }}）</span>
        <n-progress type="line" :percentage="loadingPercent" :show-indicator="false" />
      </div>
    </div>
    <div v-else-if="!sim.scene.value" class="stage-cover">
      <div class="stage-loading"><n-spin size="small" /><span>正在等仿真……</span></div>
    </div>
  </div>
</template>

<style scoped>
.stage {
  position: relative;
  width: 100%;
  height: 100%;
  min-height: 320px;
  background: #f4f5f7;
  border-radius: 8px;
  overflow: hidden;
}
.stage-canvas {
  display: block;
  width: 100%;
  height: 100%;
}
.stage-tools {
  position: absolute;
  top: 12px;
  left: 12px;
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 6px 10px;
  background: rgba(255, 255, 255, 0.9);
  border-radius: 6px;
}
.stage-view {
  width: 190px;
}
.stage-note {
  position: absolute;
  left: 12px;
  bottom: 12px;
  padding: 4px 10px;
  background: rgba(255, 255, 255, 0.9);
  border-radius: 6px;
  color: #5c6370;
  font-size: 12px;
}
.stage-cover {
  position: absolute;
  inset: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 24px;
  background: rgba(244, 245, 247, 0.92);
}
.stage-loading {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 10px;
  width: 280px;
  color: #5c6370;
}
.stage-retry {
  margin-top: 10px;
}
</style>
