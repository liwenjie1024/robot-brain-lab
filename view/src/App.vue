<script setup lang="ts">
// 最外面一层：画面上的组件用中文，弹出来的提示有地方放。
import { dateZhCN, NConfigProvider, NMessageProvider, zhCN } from 'naive-ui'
import MainView from '@/components/MainView.vue'
</script>

<template>
  <n-config-provider :locale="zhCN" :date-locale="dateZhCN">
    <n-message-provider>
      <main-view />
    </n-message-provider>
  </n-config-provider>
</template>

<style>
html,
body,
#app {
  height: 100%;
  margin: 0;
}
body {
  font-family: 'Microsoft YaHei', 'PingFang SC', 'Noto Sans CJK SC', system-ui, sans-serif;
}
</style>
