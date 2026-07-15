import { defineConfig, fontProviders } from 'astro/config';
import { loadEnv } from 'vite';
import type { Plugin } from 'vite';
import type { ServerResponse } from 'node:http';
import fs from 'node:fs';
import path from 'node:path';

// Asset store locations. DEV-ONLY: the dev server serves /heroes, /tiles and /borders
// straight off these external directories (nginx does the same in prod; the static build
// never reads them). The paths are machine-specific and MUST come from .env — copy
// .env.example to .env and set them. `loadEnv` is required because .env files are not in
// process.env by the time this config runs. There is deliberately NO fallback: the on-disk
// layout differs per checkout (and this frontend worktree will eventually fold into the
// main repo), so an unset var fails loudly (see resolveStore) rather than silently
// pointing somewhere wrong.
const env = loadEnv(process.env.NODE_ENV || 'development', process.cwd(), '');
const HERO_STORE = env.HERO_STORE;
const TILES_STORE = env.TILES_STORE;
const BORDERS_STORE = env.BORDERS_STORE;

// Resolve a required asset-store path, or 500 the request with actionable guidance.
// Checked PER-REQUEST (not when the middleware is registered) so a missing var only
// affects the dev asset routes when they're actually hit. `astro build` creates a Vite
// server — running configureServer — but never requests these routes, so it stays green.
function resolveStore(name: string, value: string | undefined, res: ServerResponse): string | null {
  if (!value) {
    res.statusCode = 500;
    res.setHeader('Content-Type', 'text/plain; charset=utf-8');
    res.end(`${name} is not set — copy web/.env.example to web/.env and set ${name} to your local asset store.`);
    return null;
  }
  return value;
}

// Dev-only: serve /heroes/* straight from the external render store, so we never
// copy tens of GB of hero variants into public/ or the build. In production,
// nginx serves /heroes/ from the same store (see deploy notes). The build itself
// only emits HTML/CSS/JS that *references* /heroes/… — the images are external.
function heroDevServer(): Plugin {
  return {
    name: 'hero-dev-server',
    configureServer(server) {
      server.middlewares.use('/heroes', (req, res, next) => {
        const store = resolveStore('HERO_STORE', HERO_STORE, res);
        if (!store) return;
        const rel = decodeURIComponent((req.url || '').split('?')[0]).replace(/^\/+/, '');
        const file = path.resolve(store, rel);
        if (!file.startsWith(path.resolve(store)) || !fs.existsSync(file) || fs.statSync(file).isDirectory()) {
          return next();
        }
        const type = file.endsWith('.webp') ? 'image/webp'
          : file.endsWith('.png') ? 'image/png'
          : 'application/octet-stream';
        res.setHeader('Content-Type', type);
        res.setHeader('Cache-Control', 'no-cache');
        fs.createReadStream(file).pipe(res);
      });
    },
  };
}

// Dev-only: serve {urlPrefix}/{z}/{x}/{y}.png straight from a tile pyramid on disk,
// same origin as the dev server so MapLibre's tile fetches need no CORS. Mirrors
// heroDevServer(); prod nginx serves /tiles/ from the same store.
function tilesDevServer(urlPrefix: string, envName: string, store: string | undefined): Plugin {
  return {
    name: `tiles-dev-server:${urlPrefix}`,
    configureServer(server) {
      server.middlewares.use(urlPrefix, (req, res, next) => {
        const resolvedStore = resolveStore(envName, store, res);
        if (!resolvedStore) return;
        const rel = decodeURIComponent((req.url || '').split('?')[0]).replace(/^\/+/, '');
        const file = path.resolve(resolvedStore, rel);
        if (!file.startsWith(path.resolve(resolvedStore)) || !fs.existsSync(file) || fs.statSync(file).isDirectory()) {
          return next();
        }
        res.setHeader('Content-Type', file.endsWith('.png') ? 'image/png' : 'application/octet-stream');
        res.setHeader('Cache-Control', 'no-cache');
        fs.createReadStream(file).pipe(res);
      });
    },
  };
}

// Dev-only: serve /borders/*.geojson straight from the border store, same origin
// as the dev server. Mirrors tilesDevServer(); prod nginx serves /borders/ too.
function bordersDevServer(): Plugin {
  return {
    name: 'borders-dev-server',
    configureServer(server) {
      server.middlewares.use('/borders', (req, res, next) => {
        const store = resolveStore('BORDERS_STORE', BORDERS_STORE, res);
        if (!store) return;
        const rel = decodeURIComponent((req.url || '').split('?')[0]).replace(/^\/+/, '');
        const file = path.resolve(store, rel);
        if (!file.startsWith(path.resolve(store)) || !fs.existsSync(file) || fs.statSync(file).isDirectory()) {
          return next();
        }
        res.setHeader('Content-Type', file.endsWith('.geojson') ? 'application/geo+json' : 'application/octet-stream');
        res.setHeader('Cache-Control', 'no-cache');
        fs.createReadStream(file).pipe(res);
      });
    },
  };
}

// https://astro.build/config
export default defineConfig({
  // Self-hosted display serif (Astro 7 Fonts API) — Fraunces, an optical
  // old-style serif. Downloaded at build, served from _astro/fonts; no runtime
  // external requests. Exposed as --font-serif, wired into --serif in global.css.
  fonts: [
    {
      provider: fontProviders.fontsource(),
      name: 'Fraunces',
      cssVariable: '--font-serif',
      weights: [400, 600],
      fallbacks: ['Georgia', 'Times New Roman', 'serif'],
    },
  ],
  vite: {
    plugins: [
      heroDevServer(),
      tilesDevServer('/tiles', 'TILES_STORE', TILES_STORE),
      bordersDevServer(),
    ],
  },
});
