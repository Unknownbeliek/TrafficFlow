import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import tailwindcss from '@tailwindcss/vite';

// The client is prebuilt by `npm run build` into client/ so the Node bridge can
// serve it as static files; this config exists for hot-reload development.
export default defineConfig({
  plugins: [react(), tailwindcss()],
  root: 'client',
  build: { outDir: '../dist', emptyOutDir: true },
  server: { host: '0.0.0.0', port: 5174 },
});
