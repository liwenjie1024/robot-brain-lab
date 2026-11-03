<script setup lang="ts">
import { NButton, NCheckbox, NResult, NSpin } from 'naive-ui'
import { onBeforeUnmount, onMounted, ref, watch } from 'vue'
import type { RobotSceneHandle } from '@/scene/robotScene'
import { parseMesh } from '@/sim/meshes'
import type { SceneDescription } from '@/sim/generated/scene'
import type { SimClient } from '@/sim/simClient'
import { supportsWebGl } from '@/utils/webgl'

/** 몸의 3D 모습. 상태는 화면 표시 간격과 상관없이 받는 대로 바로 옮긴다. */
const props = defineProps<{ client: SimClient; scene: SceneDescription }>()

type ViewPhase = 'loading' | 'ready' | 'failed' | 'no-webgl'

const canvas = ref<HTMLCanvasElement | null>(null)
const phase = ref<ViewPhase>('loading')
const failure = ref('')
const follow = ref(true)
let handle: RobotSceneHandle | null = null
let stopState: (() => void) | null = null
let stopCombat: (() => void) | null = null

async function loadMesh(meshId: number) {
  const response = await fetch(props.client.meshUrl(meshId))
  if (!response.ok) {
    throw new Error(`메시 ${meshId}을(를) 받지 못했습니다 (응답 ${response.status})`)
  }
  return parseMesh(await response.arrayBuffer())
}

async function build() {
  teardown()
  if (!supportsWebGl()) {
    phase.value = 'no-webgl'
    return
  }
  phase.value = 'loading'
  try {
    // 3D 라이브러리는 이 화면에서만 쓰므로 필요할 때 불러온다.
    const { createRobotScene } = await import('@/scene/robotScene')
    const reducedMotion = window.matchMedia?.('(prefers-reduced-motion: reduce)').matches ?? false
    handle = await createRobotScene(canvas.value!, props.scene, { loadMesh, reducedMotion })
    handle.setFollow(follow.value)
    stopState = props.client.on('state', (state) => handle?.update(state))
    stopCombat = props.client.on('combat', (event) => {
      if (event.type === 'shot') {
        handle?.showShot(event)
      }
    })
    phase.value = 'ready'
  } catch (error) {
    teardown()
    failure.value = error instanceof Error ? error.message : String(error)
    phase.value = 'failed'
  }
}

function teardown() {
  stopState?.()
  stopState = null
  stopCombat?.()
  stopCombat = null
  handle?.dispose()
  handle = null
}

onMounted(build)
watch(() => props.scene, build, { flush: 'post' })
watch(follow, (value) => handle?.setFollow(value))
onBeforeUnmount(teardown)
</script>

<template>
  <div class="robot-view">
    <canvas ref="canvas" data-test="robot-canvas" :class="{ hidden: phase !== 'ready' }"
            aria-label="시험장 3D 화면. 마우스로 끌면 돌려 보고, 휠로 가까이·멀리 봅니다." />
    <div v-if="phase === 'loading'" class="overlay">
      <n-spin size="large" />
      <p>시험장 모양을 불러오는 중입니다…</p>
    </div>
    <n-result v-else-if="phase === 'failed'" class="overlay" status="error" title="3D 화면을 만들지 못했습니다"
              :description="failure">
      <template #footer>
        <n-button type="primary" @click="build">다시 시도</n-button>
      </template>
    </n-result>
    <n-result v-else-if="phase === 'no-webgl'" class="overlay" status="warning" title="이 브라우저는 3D를 그릴 수 없습니다"
              description="WebGL을 쓸 수 없어 3D 모습은 보이지 않습니다. 오른쪽의 상태와 명령은 그대로 쓸 수 있습니다." />
    <div v-if="phase === 'ready'" class="view-tools">
      <n-checkbox v-model:checked="follow">기체 따라가기</n-checkbox>
      <span class="hint">끌어서 돌려 보기 · 휠로 확대</span>
    </div>
  </div>
</template>

<style scoped>
.robot-view {
  position: relative;
  min-height: 360px;
  height: 100%;
  border-radius: 8px;
  overflow: hidden;
  background: #0f172a;
}
canvas {
  display: block;
  width: 100%;
  height: 100%;
}
canvas.hidden {
  visibility: hidden;
}
.overlay {
  position: absolute;
  inset: 0;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 12px;
  color: #e2e8f0;
  background: #0f172a;
}
.view-tools {
  position: absolute;
  left: 12px;
  bottom: 12px;
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 6px 10px;
  border-radius: 6px;
  background: rgb(15 23 42 / 75%);
  --n-text-color: #e2e8f0;
}
.view-tools :deep(.n-checkbox__label) {
  color: #e2e8f0;
}
.hint {
  color: #94a3b8;
  font-size: 12px;
}
</style>
