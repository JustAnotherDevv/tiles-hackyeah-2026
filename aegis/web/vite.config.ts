import { fileURLToPath, URL } from 'node:url';
import tailwindcss from '@tailwindcss/vite';
import react from '@vitejs/plugin-react';
import { defineConfig } from 'vite';

// Aegis dashboard build (CONTRACTS sections 6.6 / 7.6). Served by the gateway at /ui/.
const GATEWAY = process.env.AEGIS_GATEWAY_URL ?? 'http://127.0.0.1:8787';
const PROXIED = ['/api', '/v1', '/mcp', '/healthz', '/metrics', '/openai', '/ollama', '/egress'];

export default defineConfig({
  base: '/ui/',
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: { '@': fileURLToPath(new URL('./src', import.meta.url)) },
  },
  server: {
    port: 5173,
    proxy: Object.fromEntries(PROXIED.map((p) => [p, { target: GATEWAY, changeOrigin: false }])),
  },
  preview: { port: 4173 },
  build: {
    outDir: 'dist',
    emptyOutDir: true,
    chunkSizeWarningLimit: 4096,
    rollupOptions: {
      output: {
        manualChunks(id) {
          if (!id.includes('node_modules')) return undefined;
          if (id.includes('monaco-editor') || id.includes('monaco-yaml')) return 'monaco';
          if (id.includes('recharts') || id.includes('d3-')) return 'charts';
          if (id.includes('react-dom') || id.includes('react-router') || id.includes('/react/')) return 'react';
          return undefined;
        },
      },
    },
  },
});
