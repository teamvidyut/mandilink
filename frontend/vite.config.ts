import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

// In dev, /api (HTTP + the demo-mode WebSocket) is proxied to FastAPI on :8000.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: { '/api': { target: 'http://127.0.0.1:8000', changeOrigin: true, ws: true } },
  },
  build: { outDir: 'dist', sourcemap: false, chunkSizeWarningLimit: 1500 },
});
