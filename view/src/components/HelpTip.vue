<script setup lang="ts">
// 一个小问号：鼠标移上去（或者用键盘走到它）就显示一段解释。给术语用。
import { NTooltip } from 'naive-ui'

defineProps<{ text: string }>()
</script>

<template>
  <n-tooltip trigger="hover" :style="{ maxWidth: '280px' }">
    <template #trigger>
      <span class="help-tip" role="img" tabindex="0" :aria-label="`说明：${text}`">?</span>
    </template>
    {{ text }}
  </n-tooltip>
</template>

<style scoped>
.help-tip {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 16px;
  height: 16px;
  margin-left: 4px;
  border: 1px solid #9aa0aa;
  border-radius: 50%;
  color: #5c6370;
  font-size: 11px;
  line-height: 1;
  cursor: help;
  user-select: none;
}
.help-tip:focus-visible {
  outline: 2px solid #1f6fd1;
  outline-offset: 1px;
}
</style>
