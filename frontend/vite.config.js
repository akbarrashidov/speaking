import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// Bundle kichik bo'lishi shart (§8) — og'ir UI kutubxonalar yo'q.
export default defineConfig({
  plugins: [react()],
  build: {
    target: 'es2019',
    chunkSizeWarningLimit: 300,
  },
  server: {
    port: 5173,
    proxy: {
      // Docker'da backend porti tashqariga chiqarilmagan, shuning uchun
      // nginx orqali (HTTP_PORT) yuriladi. Alohida backend ishlatilsa —
      // `VITE_PROXY_TARGET` bilan almashtiriladi.
      '/api': {
        target: process.env.VITE_PROXY_TARGET || 'http://localhost:9100',
        changeOrigin: true,
      },
      '/ws': {
        target: (process.env.VITE_PROXY_TARGET || 'http://localhost:9100').replace(
          'http',
          'ws'
        ),
        ws: true,
      },
    },
  },
})
