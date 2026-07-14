// @ts-check
import { defineConfig, fontProviders } from 'astro/config';
import fs from 'node:fs';
import path from 'node:path';

// Where the rendered hero WebP variants live (the pipeline's asset store).
// Overridable via HERO_STORE for a different checkout / machine.
const HERO_STORE =
  process.env.HERO_STORE ||
  '/home/rohan/projects/maps/blender/renders/variants';

// Where the built tile pyramid lives (z0-8 512px PNGs, XYZ). Overridable via
// TILES_STORE. Same story as HERO_STORE: served straight off disk in dev, by
// nginx (or a PMTiles range endpoint) in prod — never copied into the build.
const TILES_STORE =
  process.env.TILES_STORE ||
  '/home/rohan/projects/maps/data/work/planet_tiles/tiles';

// Where the vector border GeoJSON lives (pipeline/compose/borders_geojson.py
// output). Overridable via BORDERS_STORE. Served straight off disk in dev, by
// nginx in prod — same "assets are external" story as tiles and heroes.
const BORDERS_STORE =
  process.env.BORDERS_STORE ||
  '/home/rohan/projects/maps/data/work/borders';

// Dev-only: serve /heroes/* straight from the external render store, so we never
// copy tens of GB of hero variants into public/ or the build. In production,
// nginx serves /heroes/ from the same store (see deploy notes). The build itself
// only emits HTML/CSS/JS that *references* /heroes/… — the images are external.
function heroDevServer() {
  return {
    name: 'hero-dev-server',
    /** @param {import('vite').ViteDevServer} server */
    configureServer(server) {
      server.middlewares.use('/heroes', (req, res, next) => {
        const rel = decodeURIComponent((req.url || '').split('?')[0]).replace(/^\/+/, '');
        const file = path.resolve(HERO_STORE, rel);
        if (!file.startsWith(path.resolve(HERO_STORE)) || !fs.existsSync(file) || fs.statSync(file).isDirectory()) {
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
function tilesDevServer(urlPrefix, store) {
  return {
    name: `tiles-dev-server:${urlPrefix}`,
    /** @param {import('vite').ViteDevServer} server */
    configureServer(server) {
      server.middlewares.use(urlPrefix, (req, res, next) => {
        const rel = decodeURIComponent((req.url || '').split('?')[0]).replace(/^\/+/, '');
        const file = path.resolve(store, rel);
        if (!file.startsWith(path.resolve(store)) || !fs.existsSync(file) || fs.statSync(file).isDirectory()) {
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
function bordersDevServer() {
  return {
    name: 'borders-dev-server',
    /** @param {import('vite').ViteDevServer} server */
    configureServer(server) {
      server.middlewares.use('/borders', (req, res, next) => {
        const rel = decodeURIComponent((req.url || '').split('?')[0]).replace(/^\/+/, '');
        const file = path.resolve(BORDERS_STORE, rel);
        if (!file.startsWith(path.resolve(BORDERS_STORE)) || !fs.existsSync(file) || fs.statSync(file).isDirectory()) {
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
      tilesDevServer('/tiles', TILES_STORE),
      bordersDevServer(),
    ],
  },
});
