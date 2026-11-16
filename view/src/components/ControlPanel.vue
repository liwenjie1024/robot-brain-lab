<script setup lang="ts">
// 操作：重新开始、暂停和继续、让驱动器顶住或者松开、推一下。
import { computed, ref } from 'vue'
import { NButton, NCard, NRadioButton, NRadioGroup, NSwitch, useMessage } from 'naive-ui'
import HelpTip from '@/components/HelpTip.vue'
import type { Sim } from '@/sim/useSim'
import { asPercent, GRAVITY_M_S2 } from '@/text/format'
import { PUSH_LABELS, PUSH_STRENGTHS } from '@/text/labels'
import type { PushDirection } from '@/text/labels'

const props = defineProps<{ sim: Sim }>()
const message = useMessage()

const DEFAULT_STRENGTH = 0.04
const share = ref(DEFAULT_STRENGTH)
const busy = ref(false)

const state = computed(() => props.sim.shown.value)
/** 连着仿真、也拿到了状态，才能操作。 */
const ready = computed(() => !props.sim.stale.value && state.value !== null)
const pushing = computed(() => state.value?.push != null)
const canPush = computed(() => ready.value && !busy.value && !pushing.value && state.value?.running === true)
const pushForceN = computed(() => share.value * (props.sim.scene.value?.mass_kg ?? 0) * GRAVITY_M_S2)
const whyNoPush = computed(() => {
  if (!ready.value) return '还没连上仿真'
  if (pushing.value) return '正在推……'
  if (state.value?.running === false) return '暂停着的时候推不了，先点"继续"'
  return ''
})

/** 发一条命令。没照做的话，把原因告诉人。 */
async function run(command: () => Promise<void>): Promise<void> {
  busy.value = true
  try {
    await command()
  } catch (error) {
    message.error(error instanceof Error ? error.message : String(error))
  } finally {
    busy.value = false
  }
}

const reset = () => run(() => props.sim.reset())
const toggleRunning = () => run(() => (state.value?.running ? props.sim.pause() : props.sim.resume()))
const setControl = (on: boolean) => run(() => props.sim.setControl(on))
const push = (direction: PushDirection) => run(() => props.sim.pushBody(direction, share.value))
</script>

<template>
  <n-card title="操作" size="small">
    <div class="row">
      <n-button type="primary" :disabled="!ready || busy" @click="reset">重新开始</n-button>
      <n-button :disabled="!ready || busy" @click="toggleRunning">{{ state?.running === false ? '继续' : '暂停' }}</n-button>
      <help-tip text="重新开始：回到站姿，驱动器出力，时间从 0 开始。暂停：仿真停在这一刻，点继续再走。" />
    </div>

    <div class="row">
      <span class="name">驱动器</span>
      <n-switch
        :value="state?.controlled ?? true"
        :disabled="!ready || busy"
        aria-label="驱动器顶住还是松开"
        @update:value="setControl"
      >
        <template #checked>顶住</template>
        <template #unchecked>松开</template>
      </n-switch>
      <help-tip
        text="顶住：每个关节的驱动器把关节顶在站姿的角度上。松开：驱动器不出力，身体马上就倒。这说明是驱动器让它站住的。"
      />
    </div>

    <div class="row">
      <span class="name">推一下</span>
      <n-radio-group v-model:value="share" size="small" :disabled="!ready" aria-label="推多重">
        <n-radio-button v-for="strength in PUSH_STRENGTHS" :key="strength.share" :value="strength.share">
          {{ strength.label }}
        </n-radio-button>
      </n-radio-group>
      <help-tip text="在胸上推 0.5 秒。力按体重的比例算，这样轻的身体和重的身体受的是同样分量的一推。" />
    </div>
    <div class="note">力是体重的 {{ asPercent(share) }}，约 {{ pushForceN.toFixed(0) }} N</div>

    <div class="cross" role="group" aria-label="往哪边推">
      <n-button class="cross-forward" size="small" :disabled="!canPush" @click="push('forward')">
        ↑ {{ PUSH_LABELS.forward }}
      </n-button>
      <n-button class="cross-left" size="small" :disabled="!canPush" @click="push('left')">← {{ PUSH_LABELS.left }}</n-button>
      <n-button class="cross-right" size="small" :disabled="!canPush" @click="push('right')">
        {{ PUSH_LABELS.right }} →
      </n-button>
      <n-button class="cross-backward" size="small" :disabled="!canPush" @click="push('backward')">
        ↓ {{ PUSH_LABELS.backward }}
      </n-button>
    </div>
    <div v-if="whyNoPush" class="note" role="status">{{ whyNoPush }}</div>
  </n-card>
</template>

<style scoped>
.row {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
  margin-bottom: 12px;
}
.name {
  width: 56px;
  color: #5c6370;
}
.note {
  margin: -6px 0 10px 64px;
  color: #5c6370;
  font-size: 12px;
}
.cross {
  display: grid;
  grid-template-columns: repeat(3, 84px);
  grid-template-rows: repeat(3, auto);
  gap: 6px;
  margin: 0 0 10px 64px;
}
.cross-forward {
  grid-area: 1 / 2;
}
.cross-left {
  grid-area: 2 / 1;
}
.cross-right {
  grid-area: 2 / 3;
}
.cross-backward {
  grid-area: 3 / 2;
}
</style>
