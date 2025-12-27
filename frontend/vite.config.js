import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

export default defineConfig({
  plugins: [vue()],
  server: {
    port: 3000,
    proxy: {
      '/api': {
        target: 'http://localhost:8202',
        changeOrigin: true
      }
    }
  },
  resolve: {
    // Force development mode for lightweight-charts
    conditions: ['development', 'module', 'import', 'default']
  }
})

