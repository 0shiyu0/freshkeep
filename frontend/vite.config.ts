import { fileURLToPath, URL } from 'node:url'
import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

// 产物目录 dist/ 同时被两处消费：
//   1) 后端 StaticFiles 托管（Web）
//   2) Capacitor 的 webDir（原生 App）
export default defineConfig({
  plugins: [vue()],
  resolve: {
    alias: { '@': fileURLToPath(new URL('./src', import.meta.url)) },
  },
  server: {
    port: 5173,
    // 开发期把 /api 代理到本机后端，避免跨域
    proxy: { '/api': { target: 'http://127.0.0.1:8080', changeOrigin: true } },
  },
  build: {
    outDir: 'dist',
    sourcemap: false,
    chunkSizeWarningLimit: 900,
    rollupOptions: {
      output: {
        // ECharts 体积大，单独切块，避免首屏 JS 过大。
        // Vite 8 的类型只接受函数形式（对象形式已废弃）。
        manualChunks(id: string) {
          if (id.includes('node_modules/echarts') || id.includes('node_modules/zrender')) return 'echarts'
          if (id.includes('node_modules')) return 'vendor'
          return undefined
        },
      },
    },
  },
})
