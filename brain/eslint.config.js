import { defineConfigWithVueTs, vueTsConfigs } from '@vue/eslint-config-typescript'

// 화면(bench)과 같은 TypeScript 규칙을 쓴다 (두뇌에는 Vue 파일이 없다).
export default defineConfigWithVueTs({ ignores: ['dist/**', 'coverage/**'] }, vueTsConfigs.recommended)
