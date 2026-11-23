import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  build: {
    target: 'es2020',
  },
  server: {
    port: 5175,
    strictPort: true,
    proxy: {
      '/studio': 'http://127.0.0.1:8010',
      '/content': 'http://127.0.0.1:8010',
      '/publish': 'http://127.0.0.1:8010',
      '/topics': 'http://127.0.0.1:8010',
      '/accounts': 'http://127.0.0.1:8010',
      '/themes': 'http://127.0.0.1:8010',
      '/metrics': 'http://127.0.0.1:8010',
      '/settings': 'http://127.0.0.1:8010',
      '/health': 'http://127.0.0.1:8010',
    },
  },
})
