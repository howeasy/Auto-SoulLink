import { defineConfig } from 'vite';
import { svelte } from '@sveltejs/vite-plugin-svelte';

// base './' so the built bundle works from /static/mockups/b/ without knowing its path.
// /static/* is proxied in dev so the real slink.css + themes load off the manager.
export default defineConfig({
  base: './',
  plugins: [svelte()],
  build: { outDir: '../../server/static/mockups/b', emptyOutDir: true },
  server: { proxy: { '/static': 'http://localhost:8090' } },
});
