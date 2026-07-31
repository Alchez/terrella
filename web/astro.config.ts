import { defineConfig, fontProviders } from 'astro/config';
import { loadEnv } from 'vite';
import type { Plugin } from 'vite';
import type { ServerResponse } from 'node:http';
import fs from 'node:fs';
import path from 'node:path';
import { EtagMismatch, PMTiles, type RangeResponse, type Source, tileTypeExt } from 'pmtiles';
import {
  TILE_CONTENT_TYPE,
  assertZoomRange,
  describeTileTypeMismatch,
  parseTilePath,
} from './src/lib/reliefTiles';
import {
  TERRAIN_CONTENT_TYPE,
  assertTerrainZoomRange,
  describeTerrainTileTypeMismatch,
  parseTerrainTilePath,
} from './src/lib/terrainSource';

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
// A fourth store rather than a second file inside PMTILES_STORE: the two archives are products
// of two different pipeline outputs (data/work/planet_tiles and data/work/planet_terrain), and
// pointing one var at both would mean the packer had to write terrain.pmtiles somewhere other
// than beside the pyramid it packed. In production they are two keys in one bucket, which is a
// property of the deploy and not of this disk.
const TERRAIN_PMTILES_STORE = env.TERRAIN_PMTILES_STORE;

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

// The packaged pyramids, as the pipeline names them inside their stores.
const ARCHIVE_NAME = 'planet.pmtiles';
const TERRAIN_ARCHIVE_NAME = 'terrain.pmtiles';

// One open archive per path per dev-server process. Opening means an fs handle plus a header
// read, and PMTiles caches the directory pages it decodes, so re-opening per request would throw
// that cache away and re-read the root directory on every tile. An entry is dropped on failure so
// a fixed .env or a re-packaged archive recovers without a restart. Read positions are explicit,
// so concurrent tile requests share the handle safely.
//
// A MAP rather than the single slot this was until terrain shipped: with two archives alternating
// — every terrain tile arrives interleaved with colour ones — a one-entry memo evicts on every
// request, which is worse than no memo at all (an fs open plus a header read per tile) and would
// have looked like nothing but slowness.
const openedArchives = new Map<string, Promise<PMTiles>>();

/** `validateHeader` is per archive rather than baked in, because the two contracts are the thing
 *  that must NOT be shared — each pyramid has its own zoom range and its own encoding rule, and a
 *  check that accepted either would accept the wrong archive under the wrong route. */
function openArchive(
  archivePath: string,
  validateHeader: (header: { minZoom: number; maxZoom: number; tileType: number }) => void,
): Promise<PMTiles> {
  const already = openedArchives.get(archivePath);
  if (already) return already;
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
    // The globe states the zoom range and the tile encoding as constants so it can request tile
    // z0 without first learning them over the network. This is the check that keeps both copies
    // honest. A dev server should refuse to start on drift.
    validateHeader(await opened.getHeader());
    return opened;
  })().catch((error: unknown) => {
    openedArchives.delete(archivePath);
    throw error;
  });
  openedArchives.set(archivePath, archive);
  return archive;
}

/** Header check for the relief pyramid. */
function validateReliefHeader(header: { minZoom: number; maxZoom: number; tileType: number }) {
  assertZoomRange(header.minZoom, header.maxZoom);
  const mismatch = describeTileTypeMismatch(tileTypeExt(header.tileType));
  if (mismatch) throw new Error(mismatch);
}

/** Header check for the elevation pyramid. */
function validateTerrainHeader(header: { minZoom: number; maxZoom: number; tileType: number }) {
  assertTerrainZoomRange(header.minZoom, header.maxZoom);
  const mismatch = describeTerrainTileTypeMismatch(tileTypeExt(header.tileType));
  if (mismatch) throw new Error(mismatch);
}

/** What one parsed request resolved to: which archive, and where in it. */
interface ResolvedTileRoute {
  tile: { z: number; x: number; y: number };
  storeName: string;
  store: string | undefined;
  archiveName: string;
  contentType: string;
  validateHeader: (header: { minZoom: number; maxZoom: number; tileType: number }) => void;
}

// Dev-only: answer /tiles/{z}/{x}/{y}.webp and /tiles/terrain/{z}/{x}/{y}.webp out of the two
// packaged PMTiles archives. This is the local twin of the production tile Worker, and it exists
// for the same reason the Worker does — the archives are GB-scale, so the browser must never
// address one directly and must never send a Range header (
// to R2). The ranging happens here against a local file; in production it happens inside a
// Worker against an R2 object.
//
// ONE middleware over both, dispatching exactly the way the Worker does, because the two servers
// answering the same contract differently is the failure this arrangement exists to prevent. It
// falls out of the base URLs rather than being arranged: TERRAIN_URL_TEMPLATE is TILE_BASE plus
// the `terrain/` prefix, so in dev (`TILE_BASE = /tiles/`) the mount strips `/tiles` and this
// sees precisely the path the Worker sees at the root of its own hostname.
//
// Order matters and is safe in both directions: `parseTilePath` requires the FIRST segment to be
// a zoom, so it can never match a `/terrain/...` path, and `parseTerrainTilePath` requires the
// literal prefix, so it can never match a bare one. Neither is a prefix of the other.
function tilesDevServer(): Plugin {
  return {
    name: 'tiles-dev-server',
    configureServer(server) {
      server.middlewares.use('/tiles', (req, res, next) => {
        const requested = decodeURIComponent((req.url || '').split('?')[0]);
        const relief = parseTilePath(requested);
        const terrain = relief ? null : parseTerrainTilePath(requested);
        if (!relief && !terrain) return next();
        const route: ResolvedTileRoute = relief
          ? {
              tile: relief,
              storeName: 'PMTILES_STORE',
              store: PMTILES_STORE,
              archiveName: ARCHIVE_NAME,
              contentType: TILE_CONTENT_TYPE,
              validateHeader: validateReliefHeader,
            }
          : {
              tile: terrain!,
              storeName: 'TERRAIN_PMTILES_STORE',
              store: TERRAIN_PMTILES_STORE,
              archiveName: TERRAIN_ARCHIVE_NAME,
              contentType: TERRAIN_CONTENT_TYPE,
              validateHeader: validateTerrainHeader,
            };
        const store = resolveStore(route.storeName, route.store, res);
        if (!store) return;
        const { tile } = route;
        void (async () => {
          try {
            const archive = await openArchive(
              path.resolve(store, route.archiveName),
              route.validateHeader,
            );
            const entry = await archive.getZxy(tile.z, tile.x, tile.y);
            if (!entry) {
              // Both pyramids are COMPLETE (87,381 tiles each = every address from z0 to z8), so
              // a miss is a bug in the packaging, not an empty region. Say so rather than
              // rendering a silent hole.
              res.statusCode = 404;
              res.setHeader('Content-Type', 'text/plain; charset=utf-8');
              res.end(`No tile ${tile.z}/${tile.x}/${tile.y} in ${route.archiveName}`);
              return;
            }
            res.setHeader('Content-Type', route.contentType);
            res.setHeader('Cache-Control', 'no-cache');
            res.end(Buffer.from(entry.data));
          } catch (error) {
            res.statusCode = 500;
            res.setHeader('Content-Type', 'text/plain; charset=utf-8');
            res.end(
              `Tile ${tile.z}/${tile.x}/${tile.y} from ${route.archiveName} failed: ` +
                `${(error as Error).message}`,
            );
          }
        })();
      });
    },
  };
}

// Where `?perf` snapshot exports land, relative to web/. Gitignored.
const PERF_SNAPSHOT_DIR = '.perf';

// A snapshot is a few KB of JSON. The cap is three orders of magnitude above that, and exists
// because an unbounded read from a socket into memory is an unbounded read from a socket into
// memory regardless of who is meant to be on the other end.
const PERF_BODY_LIMIT_BYTES = 1024 * 1024;

// Dev-only: accept a POSTed `?perf` snapshot and write it to web/.perf/<timestamp>.json.
//
// WHAT THIS REPLACES
// ------------------
// Reading performance numbers off a photograph of a phone screen, and re-typing them. That loop
// lost real fidelity — a phone's panel is truncated, and the numbers that got transcribed were the
// ones that happened to be legible rather than the ones that mattered. The phone can now POST the
// whole structured report to the LAN dev server it is already loading the site from, and it can be
// read straight off disk.
//
// THE CONSTRAINTS, AND WHY EACH ONE IS HERE
// -----------------------------------------
// This is an unauthenticated write endpoint on a server bound to 0.0.0.0 for phone testing, so:
//   - POST only; anything else falls through to Astro rather than being handled.
//   - The filename is generated HERE from the clock. Nothing from the request body or URL reaches
//     the path — the request cannot name, traverse to, or overwrite a file.
//   - One fixed directory, resolved once from this config's own location.
//   - The body is capped and must parse as JSON, so a malformed or oversized POST is rejected
//     rather than stored as an unreadable file.
//
// DELIBERATE DEVIATION FROM THE ASSET-STORE RULE
// ----------------------------------------------
// The stores above take an env var with NO fallback, because a store pointing at the wrong place
// serves wrong data silently. This defaults instead, and the difference is the consequence of being
// wrong: a snapshot directory in an unexpected place costs one `ls`. Requiring configuration for a
// diagnostic would mean the diagnostic is unavailable exactly when someone is in a hurry to use it.
function perfSnapshotServer(): Plugin {
  return {
    name: 'perf-snapshot-server',
    configureServer(server) {
      server.middlewares.use('/__perf', (req, res, next) => {
        if (req.method !== 'POST') return next();
        const chunks: Buffer[] = [];
        let received = 0;
        req.on('data', (chunk: Buffer) => {
          received += chunk.length;
          if (received > PERF_BODY_LIMIT_BYTES) {
            res.statusCode = 413;
            res.end('perf snapshot too large');
            req.destroy();
            return;
          }
          chunks.push(chunk);
        });
        req.on('end', () => {
          void (async () => {
            const body = Buffer.concat(chunks).toString('utf8');
            try {
              JSON.parse(body);
            } catch {
              res.statusCode = 400;
              res.end('perf snapshot is not JSON');
              return;
            }
            // Colons are legal on ext4 but make the file annoying to pass to anything shell-shaped.
            const stamp = new Date().toISOString().replace(/[:.]/g, '-');
            const directory = path.resolve(process.cwd(), PERF_SNAPSHOT_DIR);
            const file = path.join(directory, `${stamp}.json`);
            try {
              await fs.promises.mkdir(directory, { recursive: true });
              await fs.promises.writeFile(file, body, 'utf8');
              console.info(`[perf] snapshot written to ${path.relative(process.cwd(), file)}`);
              res.statusCode = 200;
              res.setHeader('Content-Type', 'application/json');
              res.end(JSON.stringify({ written: path.relative(process.cwd(), file) }));
            } catch (error) {
              res.statusCode = 500;
              res.end(`perf snapshot write failed: ${(error as Error).message}`);
            }
          })();
        });
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
      perfSnapshotServer(),
    ],
  },
});
