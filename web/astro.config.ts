import { defineConfig, fontProviders } from 'astro/config';
import { loadEnv } from 'vite';
import type { Plugin } from 'vite';
import type { ServerResponse } from 'node:http';
import fs from 'node:fs';
import path from 'node:path';
import { parseByteRange } from './src/lib/httpRange';

// Asset store locations. DEV-ONLY: the dev server serves /heroes, /borders and /pmtiles
// straight off these external directories (nginx does the same in prod; the
// static build never reads them). The paths are machine-specific and MUST come from .env — copy
// .env.example to .env and set them. `loadEnv` is required because .env files are not in
// process.env by the time this config runs. There is deliberately NO fallback: the on-disk
// layout differs per checkout (and this frontend worktree will eventually fold into the
// main repo), so an unset var fails loudly (see resolveStore) rather than silently
// pointing somewhere wrong.
const env = loadEnv(process.env.NODE_ENV || 'development', process.cwd(), '');
const HERO_STORE = env.HERO_STORE;
const BORDERS_STORE = env.BORDERS_STORE;
const PMTILES_STORE = env.PMTILES_STORE;

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

// Dev-only: serve /borders/*.geojson straight from the border store, same origin
// as the dev server. Mirrors heroDevServer(); prod nginx serves /borders/ too.
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

// Dev-only: serve /pmtiles/*.pmtiles from the archive store WITH byte-range support —
// the one route where Range matters. The pmtiles client reads the 15 GB archive as byte
// slices (16 KB header first, then per-tile spans); without 206 responses a client would
// fall back to downloading the whole file. nginx serves the same file in prod with
// native Range handling, so this middleware is dev parity, not production code.
function pmtilesDevServer(): Plugin {
  return {
    name: 'pmtiles-dev-server',
    configureServer(server) {
      server.middlewares.use('/pmtiles', (req, res, next) => {
        const store = resolveStore('PMTILES_STORE', PMTILES_STORE, res);
        if (!store) return;
        const rel = decodeURIComponent((req.url || '').split('?')[0]).replace(/^\/+/, '');
        const file = path.resolve(store, rel);
        if (
          !file.startsWith(path.resolve(store)) ||
          !file.endsWith('.pmtiles') ||
          !fs.existsSync(file) ||
          fs.statSync(file).isDirectory()
        ) {
          return next();
        }
        const totalSize = fs.statSync(file).size;
        res.setHeader('Accept-Ranges', 'bytes');
        res.setHeader('Content-Type', 'application/octet-stream');
        res.setHeader('Cache-Control', 'no-cache');
        const range = parseByteRange(req.headers.range, totalSize);
        if (range === 'unsatisfiable') {
          res.statusCode = 416;
          res.setHeader('Content-Range', `bytes */${totalSize}`);
          res.end();
          return;
        }
        if (range === null) {
          res.setHeader('Content-Length', totalSize);
          fs.createReadStream(file).pipe(res);
          return;
        }
        res.statusCode = 206;
        res.setHeader('Content-Range', `bytes ${range.start}-${range.end}/${totalSize}`);
        res.setHeader('Content-Length', range.end - range.start + 1);
        fs.createReadStream(file, { start: range.start, end: range.end }).pipe(res);
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
      bordersDevServer(),
      pmtilesDevServer(),
    ],
  },
});
