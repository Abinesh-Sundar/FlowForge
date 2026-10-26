import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// Point the dev proxy at whichever port the backend runs on:
//   VITE_API_TARGET=http://127.0.0.1:8081 npm run dev
const apiTarget = process.env.VITE_API_TARGET || 'http://127.0.0.1:8000'

export default defineConfig({
  plugins: [react()],
  server: {
    // 5173 by default, but take the next free port instead of failing if it is already in use.
    port: 5173,
    strictPort: false,
    proxy: { '/api': { target: apiTarget, changeOrigin: true } },
  },
})
