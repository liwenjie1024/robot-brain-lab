import { fileURLToPath, URL } from 'node:url'
import vue from '@vitejs/plugin-vue'
import { defineConfig } from 'vitest/config'

// 몸(시뮬레이터)은 Docker에서 돈다 (compose.yaml). 화면은 /sim으로 보내고 개발 서버가 넘겨 준다
// (주소를 하나로 두어 브라우저의 다른 출처 막기(CORS)를 피한다).
const simTarget = process.env.VITE_SIM_TARGET ?? 'http://localhost:8765'

export default defineConfig({
  plugins: [vue()],
  resolve: {
    alias: { '@': fileURLToPath(new URL('./src', import.meta.url)) },
  },
  server: {
    port: 5180,
    proxy: {
      '/sim': {
        target: simTarget,
        ws: true,
        rewrite: (path) => path.replace(/^\/sim/, ''),
      },
    },
  },
  build: {
    // 3D 화면 덩어리(three.js, 약 560kB)는 이미 3D를 그릴 때만 따로 불러온다. 그보다 큰 덩어리가 생기면 알린다.
    chunkSizeWarningLimit: 600,
  },
  test: {
    environment: 'jsdom',
    include: ['src/**/*.spec.ts'],
  },
})
