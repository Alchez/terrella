import { defineConfig, fontProviders } from 'astro/config';
import { loadEnv } from 'vite';
import type { Plugin } from 'vite';
import type { ServerResponse } from 'node:http';
import fs from 'node:fs';
import path from 'node:path';
import { EtagMismatch, PMTiles, type RangeResponse, type Source } from 'pmtiles';
import { TILE_CONTENT_TYPE, assertZoomRange, parseTilePath } from './src/lib/reliefTiles';

// Asset store locations. DEV-ONLY: the dev server serves /heroes, /borders and /tiles
// out of these external directories (R2 does it in production; the
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
// copy tens of GB of hero variants into public/ or the build. In production the same
// files are R2 objects and the base URL moves (see src/lib/assetBase.ts). The build
// itself only emits HTML/CSS/JS that *references* the hero base — images are external.
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
// as the dev server. Mirrors heroDevServer(); in production these are R2 objects too.
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

// The packaged pyramid, as the pipeline names it inside PMTILES_STORE.
const ARCHIVE_NAME = 'planet.pmtiles';

// One open archive per dev-server process. Opening means an fs handle plus a header read,
// and PMTiles caches the directory pages it decodes, so re-opening per request would throw
// that cache away and re-read the root directory on every tile. Memoised by path, and the
// memo is dropped on failure so a fixed .env or a re-packaged archive recovers without a
// restart. Read positions are explicit, so concurrent tile requests share the handle safely.
let openedArchive: { archivePath: string; archive: Promise<PMTiles> } | null = null;

function openArchive(archivePath: string): Promise<PMTiles> {
  if (openedArchive?.archivePath === archivePath) return openedArchive.archive;
  const archive = (async () => {
    const handle = await fs.promises.open(archivePath, 'r');
    // Stand-in for an HTTP ETag: mtime+size changes whenever the archive is re-packed. PMTiles
    // caches directory entries, and a directory entry is a byte OFFSET — offsets into a
    // different archive are meaningless, so re-packing while the dev server holds warm
    // directories would read real bytes from the wrong place and serve a corrupt tile with a
    // 200. Reporting a mismatch makes getZxy drop its cache and retry instead. The production
    // Worker gets this from R2's real ETag via `onlyIf`; the failure mode is identical, and
    // re-cutting the pyramid is a routine event here.
    const archiveVersion = async () => {
      const stats = await handle.stat();
      return `${stats.mtimeMs}-${stats.size}`;
    };
    const source: Source = {
      getKey: () => archivePath,
      async getBytes(offset, length, _signal, etag): Promise<RangeResponse> {
        const current = await archiveVersion();
        if (etag !== undefined && etag !== current) throw new EtagMismatch();
        const buffer = Buffer.alloc(length);
        await handle.read(buffer, 0, length, offset);
        return {
          data: buffer.buffer.slice(buffer.byteOffset, buffer.byteOffset + buffer.byteLength),
          etag: current,
        };
      },
    };
    const opened = new PMTiles(source);
    const header = await opened.getHeader();
    // The globe states the zoom range as a constant so it can request tile z0 without first
    // learning the range over the network. This is the check that keeps that copy honest.
    assertZoomRange(header.minZoom, header.maxZoom);
    return opened;
  })().catch((error: unknown) => {
    openedArchive = null;
    throw error;
  });
  openedArchive = { archivePath, archive };
  return archive;
}

// Dev-only: answer /tiles/{z}/{x}/{y}.webp out of the packaged PMTiles archive. This is the
// local twin of the production tile Worker, and it exists for the same reason the Worker
// does — the archive is multi-GB, so the browser must never address it directly and must never
// send a Range header (→ HISTORY § the deploy target moves to R2). The ranging happens here,
// against a local file; in production it happens inside a Worker, against an R2 object.
function tilesDevServer(): Plugin {
  return {
    name: 'tiles-dev-server',
    configureServer(server) {
      server.middlewares.use('/tiles', (req, res, next) => {
        const store = resolveStore('PMTILES_STORE', PMTILES_STORE, res);
        if (!store) return;
        const tile = parseTilePath(decodeURIComponent((req.url || '').split('?')[0]));
        if (!tile) return next();
        void (async () => {
          try {
            const archive = await openArchive(path.resolve(store, ARCHIVE_NAME));
            const entry = await archive.getZxy(tile.z, tile.x, tile.y);
            if (!entry) {
              // The pyramid is complete (87,381 tiles = every address from z0 to z8), so a
              // miss is a bug in the packaging, not an empty region. Say so rather than
              // rendering a silent hole.
              res.statusCode = 404;
              res.setHeader('Content-Type', 'text/plain; charset=utf-8');
              res.end(`No tile ${tile.z}/${tile.x}/${tile.y} in ${ARCHIVE_NAME}`);
              return;
            }
            res.setHeader('Content-Type', TILE_CONTENT_TYPE);
            res.setHeader('Cache-Control', 'no-cache');
            res.end(Buffer.from(entry.data));
          } catch (error) {
            res.statusCode = 500;
            res.setHeader('Content-Type', 'text/plain; charset=utf-8');
            res.end(`Tile ${tile.z}/${tile.x}/${tile.y} failed: ${(error as Error).message}`);
          }
        })();
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
      tilesDevServer(),
    ],
  },
});
