import { fileURLToPath, URL } from 'node:url'
import vue from '@vitejs/plugin-vue'
import { defineConfig } from 'vitest/config'

// 仿真在 Docker 里跑（compose.yaml 的 sim）。网页把请求发到 /sim，由开发服务器转过去：
// 这样网页和仿真是同一个地址，浏览器不会因为"来源不同"把请求拦掉。
const simTarget = process.env.VITE_SIM_TARGET ?? 'http://127.0.0.1:8870'

export default defineConfig({
  plugins: [vue()],
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url)),
    },
  },
  server: {
    // 只在这台电脑自己上开，别的电脑连不进来。
    host: '127.0.0.1',
    port: 5280,
    strictPort: true,
    proxy: {
      '/sim': {
        target: simTarget,
        ws: true,
        rewrite: (path) => path.replace(/^\/sim/, ''),
      },
    },
  },
  build: {
    // 3D 的那一块（three.js，约 560 kB）到要画的时候才单独去拿。比它还大的一块出现了要知道。
    chunkSizeWarningLimit: 650,
  },
  test: {
    environment: 'jsdom',
    include: ['src/**/*.spec.ts'],
  },
})
