import { defineConfig, loadEnv } from 'vite';
import react from '@vitejs/plugin-react';
import tailwindcss from '@tailwindcss/vite';

export default defineConfig(({ command, mode }) => {
  const env = loadEnv(mode, '..', '');
  const target = env.VITE_API_PROXY_TARGET || `http://127.0.0.1:${env.BACKEND_PORT || '8001'}`;
  const proxy = { '/api': { target, changeOrigin: true, rewrite: (path: string) => path.replace(/^\/api/, '') } };
  return {
    envDir: '..',
    // A local dev convenience key must never become a credential in a published bundle.
    define: { 'import.meta.env.VITE_API_KEY': JSON.stringify(command === 'serve' && mode === 'development' ? env.VITE_API_KEY || '' : '') },
    plugins: [react(), tailwindcss()],
    server: { port: 5173, proxy },
    preview: { port: 4173, proxy },
  };
});
