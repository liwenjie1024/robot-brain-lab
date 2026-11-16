<script setup lang="ts">
// 整个画面：上面一条状态，左边是 3D 的身体，右边是操作和每种读数。
import { NAlert, NButton } from 'naive-ui'
import BalancePanel from '@/components/BalancePanel.vue'
import ControlPanel from '@/components/ControlPanel.vue'
import JointPanel from '@/components/JointPanel.vue'
import SensePanel from '@/components/SensePanel.vue'
import StageView from '@/components/StageView.vue'
import StatusBar from '@/components/StatusBar.vue'
import { useSim } from '@/sim/useSim'

const sim = useSim()
</script>

<template>
  <div class="page">
    <status-bar :sim="sim" />

    <div class="notices" aria-live="polite">
      <n-alert v-if="sim.link.value === 'closed'" type="error" title="和仿真的连接断了" :show-icon="false">
        下面的数是断开之前的，不是现在的。过一会儿会自己再连。仿真没开的话，先在仓库里运行
        <code>docker compose up -d sim</code>。
        <n-button size="tiny" class="notice-button" @click="sim.retryLink()">再连一次</n-button>
      </n-alert>
      <n-alert v-if="sim.problem.value" type="error" title="收到了读不懂的消息" :show-icon="false">
        {{ sim.problem.value }}。网页和仿真可能不是同一个版本：重新启动仿真（<code>docker compose restart sim</code>），再刷新这一页。
      </n-alert>
      <n-alert v-if="sim.shown.value?.problem" type="error" title="仿真出了问题" :show-icon="false">
        {{ sim.shown.value.problem }}
      </n-alert>
    </div>

    <main class="main">
      <section class="stage-area" aria-label="3D 的身体"><stage-view :sim="sim" /></section>
      <section class="panels" :class="{ old: sim.stale.value }" aria-label="操作和读数">
        <control-panel :sim="sim" />
        <balance-panel :sim="sim" />
        <joint-panel :sim="sim" />
        <sense-panel :sim="sim" />
      </section>
    </main>
  </div>
</template>

<style scoped>
.page {
  display: flex;
  flex-direction: column;
  height: 100vh;
  background: #eceef2;
  color: #2b2f36;
}
.notices {
  display: flex;
  flex-direction: column;
  gap: 6px;
  padding: 0 12px;
}
.notices > :first-child {
  margin-top: 8px;
}
.notice-button {
  margin-left: 8px;
}
.main {
  flex: 1;
  display: grid;
  grid-template-columns: minmax(0, 1fr) 460px;
  gap: 12px;
  min-height: 0;
  padding: 12px;
}
.stage-area {
  min-width: 0;
  min-height: 0;
}
.panels {
  display: flex;
  flex-direction: column;
  gap: 10px;
  min-height: 0;
  overflow-y: auto;
  padding-right: 2px;
}
/* 连接断着的时候，读数是旧的：调淡一点，和上面的提示一起说明"这不是现在的"。 */
.panels.old {
  opacity: 0.6;
}
code {
  padding: 1px 4px;
  background: rgba(0, 0, 0, 0.06);
  border-radius: 3px;
}
/* 窄的屏幕（平板、手机）：3D 在上，读数在下，一起往下滚。 */
@media (max-width: 1000px) {
  .page {
    height: auto;
    min-height: 100vh;
  }
  .main {
    grid-template-columns: minmax(0, 1fr);
  }
  .stage-area {
    height: 60vh;
  }
  .panels {
    overflow-y: visible;
  }
}
</style>
