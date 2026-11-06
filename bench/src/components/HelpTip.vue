<script setup lang="ts">
import { NTooltip } from 'naive-ui'

/**
 * 도움말 "?" 표시: 칸을 줄이려고 긴 설명은 마우스를 올리면 보이게 둔다.
 * 화면 읽기 프로그램은 aria-label로 같은 설명을 읽는다.
 */
defineProps<{ text: string }>()
</script>

<template>
  <n-tooltip :style="{ maxWidth: '320px' }">
    <template #trigger>
      <span class="help" tabindex="0" role="img" :aria-label="`도움말: ${text}`">?</span>
    </template>
    {{ text }}
  </n-tooltip>
</template>

<style scoped>
.help {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 16px;
  height: 16px;
  margin-left: 4px;
  border-radius: 50%;
  background: #e2e8f0;
  color: #475569;
  font-size: 11px;
  font-weight: 700;
  cursor: help;
  vertical-align: middle;
  flex: none;
}
.help:focus-visible {
  outline: 2px solid #2563eb;
  outline-offset: 1px;
}
</style>
