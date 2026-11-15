import { defineConfig, bindings } from 'cf/config';
// Deliberately no account/resource IDs, route or secrets. Deployment needs an
// authenticated project account and scoped resource setup. Paid changes require approval.
export default defineConfig({
  worker: {
    name: 'kokiri-catalog', entrypoint: './src/worker.ts', compatibilityDate: '2026-11-15',
    env: { DB: bindings.d1({ name: 'kokiri-catalog' }) },
    observability: { enabled: false },
  },
});
