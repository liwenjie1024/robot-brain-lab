<script setup lang="ts">
import { NCard, NDescriptions, NDescriptionsItem, NEmpty, NTag, NTooltip } from 'naive-ui'
import { computed } from 'vue'
import type { StateMessage } from '@/sim/generated/message'
import { formatDegrees, formatSeconds, formatSpeed, POSTURE_LABELS } from '@/utils/labels'

/** 몸의 지금 상태: 서 있는지, 어디서 어느 쪽을 보는지, 명령한 속도와 실제 속도 */
const props = defineProps<{
  state: StateMessage | null
  /** 연결이 끊겨 마지막으로 받은 상태를 보여 주는 중 */
  stale: boolean
}>()

const posture = computed(() => (props.state ? POSTURE_LABELS[props.state.robot.posture] : null))
const robot = computed(() => props.state?.robot)
</script>

<template>
  <n-card title="몸 상태" size="small">
    <template #header-extra>
      <n-tooltip v-if="posture">
        <template #trigger>
          <n-tag :type="posture.type" data-test="posture" round>{{ posture.text }}</n-tag>
        </template>
        {{ posture.help }}
      </n-tooltip>
    </template>
    <n-empty v-if="!state || !robot" description="아직 상태를 받지 못했습니다" />
    <template v-else>
      <p v-if="stale" class="stale" data-test="stale">
        연결이 끊겨 마지막으로 받은 상태입니다. 지금 몸의 상태와 다를 수 있습니다.
      </p>
      <n-descriptions :column="1" label-placement="left" size="small">
        <n-descriptions-item label="지난 시간">
          {{ formatSeconds(state.simTime) }}
          <span class="muted">(시뮬레이션 기준)</span>
        </n-descriptions-item>
        <n-descriptions-item label="위치">
          앞 {{ robot.position[0].toFixed(2) }} m, 왼쪽 {{ robot.position[1].toFixed(2) }} m,
          골반 높이 {{ robot.position[2].toFixed(2) }} m
        </n-descriptions-item>
        <n-descriptions-item label="바라보는 방향">{{ formatDegrees(robot.yaw) }}</n-descriptions-item>
      </n-descriptions>
      <table class="speeds" data-test="speeds">
        <caption>속도 (명령한 값 → 실제 값)</caption>
        <tbody>
          <tr>
            <th scope="row">앞뒤</th>
            <td>{{ formatSpeed(robot.command.forward, 'm/s') }}</td>
            <td>{{ formatSpeed(robot.velocity.forward, 'm/s') }}</td>
          </tr>
          <tr>
            <th scope="row">옆</th>
            <td>{{ formatSpeed(robot.command.sideways, 'm/s') }}</td>
            <td>{{ formatSpeed(robot.velocity.sideways, 'm/s') }}</td>
          </tr>
          <tr>
            <th scope="row">돌기</th>
            <td>{{ formatSpeed(robot.command.turn, 'rad/s') }}</td>
            <td>{{ formatSpeed(robot.velocity.turn, 'rad/s') }}</td>
          </tr>
        </tbody>
      </table>
      <p v-if="robot.pushing" class="pushing" data-test="pushing">⚠ 지금 밀고 있습니다</p>
    </template>
  </n-card>
</template>

<style scoped>
.muted {
  color: #64748b;
  font-size: 12px;
}
.stale {
  margin: 0 0 8px;
  padding: 6px 8px;
  border-radius: 4px;
  background: #fef3c7;
  color: #92400e;
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
  width: 3em;
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
