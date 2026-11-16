<script setup lang="ts">
// 感觉：这个身体自己的传感器读到的。有什么就列什么：平衡感（IMU）、六轴力、接触。
import { computed } from 'vue'
import { NCard, NEmpty, NTag } from 'naive-ui'
import HelpTip from '@/components/HelpTip.vue'
import { touched } from '@/sim/derive'
import type { Sim } from '@/sim/useSim'
import { asVector, fixed, magnitude } from '@/text/format'

const props = defineProps<{ sim: Sim }>()

const scene = computed(() => props.sim.scene.value)
const state = computed(() => props.sim.shown.value)
const imus = computed(() =>
  (scene.value?.imus ?? []).map((imu, index) => ({ label: imu.label, reading: state.value?.imus[index] })),
)
const forces = computed(() =>
  (scene.value?.force_sensors ?? []).map((sensor, index) => ({ label: sensor.label, reading: state.value?.forces[index] })),
)
const touches = computed(() => (scene.value && state.value ? touched(scene.value, state.value) : []))
const touchPlaces = computed(() => scene.value?.touch_sensors.length ?? 0)
</script>

<template>
  <n-card title="感觉" size="small">
    <n-empty v-if="!scene || !state" description="还没有收到状态" size="small" />
    <template v-else>
      <h3 class="kind">
        平衡感（IMU）
        <help-tip
          text="IMU 量加速度和转得多快。站着不动的时候，它量到的加速度是朝上的 9.81（重力），角速度是 0。身体一歪、一晃，这两个数就变。"
        />
      </h3>
      <table v-if="imus.length" class="readings">
        <thead>
          <tr>
            <th scope="col">装在</th>
            <th scope="col">加速度（m/s²）</th>
            <th scope="col">角速度（rad/s）</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="imu in imus" :key="imu.label">
            <th scope="row">{{ imu.label }}</th>
            <td>{{ imu.reading ? asVector(imu.reading.acceleration, 2) : '-' }}</td>
            <td>{{ imu.reading ? asVector(imu.reading.angular_velocity, 2) : '-' }}</td>
          </tr>
        </tbody>
      </table>
      <p v-else class="none">这个身体没有 IMU。</p>

      <h3 class="kind">
        六轴力
        <help-tip
          text="装在踝和腕上，量这一处传过去的力和力矩。踝的读数是腿压在脚上的力；腕的读数是手和手里的东西的重量。读数是传感器自己的坐标。"
        />
      </h3>
      <table v-if="forces.length" class="readings">
        <thead>
          <tr>
            <th scope="col">装在</th>
            <th scope="col" class="number">力（N）</th>
            <th scope="col">三个方向</th>
            <th scope="col" class="number">力矩（N·m）</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="sensor in forces" :key="sensor.label">
            <th scope="row">{{ sensor.label }}</th>
            <td class="number">{{ sensor.reading ? fixed(magnitude(sensor.reading.force), 1) : '-' }}</td>
            <td>{{ sensor.reading ? asVector(sensor.reading.force, 0) : '-' }}</td>
            <td class="number">{{ sensor.reading ? fixed(magnitude(sensor.reading.moment), 1) : '-' }}</td>
          </tr>
        </tbody>
      </table>
      <p v-else class="none">这个身体没有六轴力传感器。</p>

      <h3 class="kind">
        碰到了哪里
        <help-tip text="身体的每一段、每个指尖受到的接触力。站着的时候应该只有两只脚碰着地面。" />
      </h3>
      <p v-if="touchPlaces === 0" class="none">这个身体没有量接触的传感器。</p>
      <p v-else-if="touches.length === 0" class="none">{{ touchPlaces }} 处都没有碰到东西。</p>
      <div v-else class="touches">
        <n-tag v-for="touch in touches" :key="touch.label" type="info" size="small" :bordered="false">
          {{ touch.label }} {{ fixed(touch.forceN, 0) }} N
        </n-tag>
      </div>
    </template>
  </n-card>
</template>

<style scoped>
.kind {
  margin: 10px 0 4px;
  font-size: 13px;
  font-weight: 600;
}
.kind:first-child {
  margin-top: 0;
}
.readings {
  width: 100%;
  border-collapse: collapse;
  font-size: 13px;
  font-variant-numeric: tabular-nums;
}
.readings th {
  font-weight: 400;
  text-align: left;
  white-space: nowrap;
}
.readings thead th {
  color: #8a8f98;
  font-size: 12px;
}
.readings td,
.readings th {
  padding: 2px 8px 2px 0;
}
.number {
  text-align: right !important;
}
.none {
  margin: 0;
  color: #5c6370;
  font-size: 13px;
}
.touches {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}
</style>
