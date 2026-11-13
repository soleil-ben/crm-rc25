import { fileURLToPath, URL } from 'node:url';
import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

// Approved public-update wording lives in the backend package so it ships with the API
// that validates against it. The staff picker and the public tracking page import that
// same file rather than keeping a second copy, because two copies of customer-facing
// wording drift and nobody notices until a customer reads the stale one (DEC-0084).
const templateCatalogue = fileURLToPath(
  new URL('../backend/app/content/public_update_templates.json', import.meta.url),
);

// The document and everything Vite serves with it are never cached (UAT-AD-01). The
// staff portal is one HTML document whose screens render customer data; a browser that
// kept a copy of it could show that copy after a sign-out, from the Back button or the
// back-forward cache. `no-store` on the document is the browser-side half of the fix
// (the API has answered `no-store` since Phase 1); the SPA's own cache handling is the
// other half (`src/app/SessionContext.jsx`). The same header must be set on `index.html`
// by whatever serves the production build -- `docs/DEPLOYMENT.md` section 3 says so.
const NO_STORE_HEADERS = {
  'Cache-Control': 'no-store, no-cache, must-revalidate, private',
  Pragma: 'no-cache',
};

// The React app never talks to SQLite. Every read and write goes through the FastAPI
// REST API (Design.md section 18). In development the API is proxied so the session
// cookie is same-origin.
export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: { '@templates': templateCatalogue },
  },
  server: {
    // The catalogue sits outside the Vite root, so dev-server file serving has to be told
    // the repository root is allowed. Production builds bundle it and never serve it.
    fs: { allow: ['..'] },
    port: 5173,
    headers: NO_STORE_HEADERS,
    proxy: {
      '/api': {
        target: process.env.VITE_API_TARGET || 'http://127.0.0.1:8000',
        changeOrigin: false,
      },
    },
  },
  preview: {
    headers: NO_STORE_HEADERS,
  },
  build: {
    outDir: 'dist',
    sourcemap: false,
  },
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: ['./tests/setup.js'],
    include: ['tests/**/*.test.jsx', 'tests/**/*.test.js'],
    css: false,
  },
});
