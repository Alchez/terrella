import { defineConfig, fontProviders } from 'astro/config';
import { loadEnv } from 'vite';
import type { Plugin } from 'vite';
import type { ServerResponse } from 'node:http';
import fs from 'node:fs';
import { createRequire } from 'node:module';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { EtagMismatch, PMTiles, type RangeResponse, type Source, tileTypeExt } from 'pmtiles';
import {
  archiveFileName,
  archivePath,
  describeMissingArchive,
  describeRetiredStoreVars,
  resolveDataRoot,
} from './src/lib/devStores';
import {
  describeArchiveHeaderMismatch,
  LAYERS,
  resolveTileRequest,
  type LayerId,
} from './src/lib/tileAddress';
import type { BodySlug } from './src/lib/bodies';
import { describeTileTypeMismatch } from './src/lib/reliefTiles';
import { describeTerrainTileTypeMismatch } from './src/lib/terrainSource';
import { describeVectorTileTypeMismatch } from './src/lib/vectorTiles';
import { perfCaptureName } from './src/lib/perfCaptureName';

// Asset store locations. DEV-ONLY: the dev server serves /heroes, /borders and /tiles
// out of these external directories (R2 does it in production; the
// static build never reads them). `loadEnv` is required because .env files are not in
// process.env by the time this config runs.
//
// TWO KINDS OF STORE, AND ONLY ONE OF THEM IS CONFIGURED. Heroes and borders are named
// explicitly, machine-specific, with deliberately NO fallback — an unset var fails loudly (see
// resolveStore) rather than silently pointing somewhere wrong. The three tile ARCHIVES are not
// named at all any more: they are derived from the pipeline's own work tree, because one variable
// per archive per body does not survive a second planet. See src/lib/devStores.ts for the
// convention and for where the fail-loud property went.
const env = loadEnv(process.env.NODE_ENV || 'development', process.cwd(), '');
const HERO_STORE = env.HERO_STORE;
const BORDERS_STORE = env.BORDERS_STORE;

// The checkout, taken from this file's own location rather than from cwd — `pipeline/paths.py`
// derives its ROOT the same way and for the same reason: a root that moved with the working
// directory would resolve differently depending on where the server was started.
const REPO_ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const DATA_ROOT = resolveDataRoot(env, REPO_ROOT);

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
  archivePathname: string,
  validateHeader: (header: { minZoom: number; maxZoom: number; tileType: number }) => void,
): Promise<PMTiles> {
  const already = openedArchives.get(archivePathname);
  if (already) return already;
  const archive = (async () => {
    const handle = await fs.promises.open(archivePathname, 'r');
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
      getKey: () => archivePathname,
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
    openedArchives.delete(archivePathname);
    throw error;
  });
  openedArchives.set(archivePathname, archive);
  return archive;
}

/** Per-layer tile-ENCODING checks. Which encoding an archive stores is a property of the layer's
 *  contract, not of the planet: every body's relief is WebP and every body's vectors are MVT. */
const VALIDATE_TILE_TYPE: Record<LayerId, (extension: string) => string | null> = {
  relief: describeTileTypeMismatch,
  terrain: describeTerrainTileTypeMismatch,
  vector: describeVectorTileTypeMismatch,
};

/** Header checks for one body's cut of one layer, THROWING where the Worker logs and 404s.
 *
 *  The asymmetry is deliberate and long-standing: a dev server should refuse to start on drift, a
 *  live one should serve what it has and make the drift visible rather than 500 the world. Both
 *  descriptions come from `lib/`, so the checks stay testable — a config is imported by nothing. */
function headerCheckFor(body: BodySlug, layer: LayerId) {
  return (header: { minZoom: number; maxZoom: number; tileType: number }): void => {
    const zoomMismatch = describeArchiveHeaderMismatch(body, layer, header);
    if (zoomMismatch) throw new Error(zoomMismatch);
    const typeMismatch = VALIDATE_TILE_TYPE[layer](tileTypeExt(header.tileType));
    if (typeMismatch) throw new Error(typeMismatch);
  };
}

// Dev-only: answer /tiles/{z}/{x}/{y}.webp, /tiles/terrain/{z}/{x}/{y}.webp and
// /tiles/countries/{z}/{x}/{y}.mvt out of the three packaged PMTiles archives, each found under
// the pipeline's own work tree (src/lib/devStores.ts). This is the local twin of the production
// tile Worker, and it exists for the same reason the Worker does — the archives are GB-scale, so
// the browser must never address one directly and must never send a Range header. The ranging
// happens here against a local file; in production it happens inside a Worker against an R2 object.
//
// ONE middleware over all three, dispatching through the SAME function the Worker calls —
// `resolveTileRequest` — because the two servers answering one contract differently is the failure
// this arrangement exists to prevent. Sharing the parsers was never quite enough: the two routers
// still chose between them separately, which is how dev came to 404 the `/v<N>/` prefix that
// production has always accepted. One resolver cannot diverge.
//
// It sees exactly what the Worker sees, and that falls out of the base URL rather than being
// arranged: the templates are TILE_BASE plus a path, so in dev (`TILE_BASE = /tiles/`) the mount
// strips `/tiles` and this reads precisely the path the Worker reads at the root of its hostname.
function tilesDevServer(): Plugin {
  return {
    name: 'tiles-dev-server',
    configureServer(server) {
      // Said once, at startup, rather than per request: a variable that used to steer this server
      // and now does nothing is state someone edits, restarts, and then disbelieves the result of.
      const retired = describeRetiredStoreVars(env);
      if (retired) console.warn(`[tiles] ${retired}`);
      server.middlewares.use('/tiles', (req, res, next) => {
        const requested = decodeURIComponent((req.url || '').split('?')[0]);
        const tile = resolveTileRequest(requested);
        if (!tile) return next();
        const layer = LAYERS[tile.layer];
        const archivePathname = archivePath(DATA_ROOT, tile.body, tile.layer);
        const archiveName = archiveFileName(tile.layer);
        // Checked per request, not once at startup, for the reason resolveStore is: `astro build`
        // creates a Vite server and runs configureServer, but never asks for a tile, so a missing
        // archive must not be able to fail a build that does not need it.
        if (!fs.existsSync(archivePathname)) {
          res.statusCode = 500;
          res.setHeader('Content-Type', 'text/plain; charset=utf-8');
          res.end(describeMissingArchive(tile.body, tile.layer, archivePathname, DATA_ROOT));
          return;
        }
        void (async () => {
          try {
            const archive = await openArchive(
              archivePathname,
              headerCheckFor(tile.body, tile.layer),
            );
            const entry = await archive.getZxy(tile.z, tile.x, tile.y);
            if (!entry) {
              // What a miss MEANS is a property of the archive, so the status comes off the
              // route. The two RASTER pyramids are COMPLETE (87,381 tiles each = every address
              // from z0 to z8), so a miss there is a packaging bug and gets a 404 that says so
              // rather than a silent hole. The COUNTRY pyramid is sparse — most of the planet is
              // ocean — so a miss there is ordinary and gets an empty 204, which MapLibre reads
              // as a tile with no features.
              res.statusCode = layer.missingTileStatus;
              if (layer.missingTileStatus === 404) {
                res.setHeader('Content-Type', 'text/plain; charset=utf-8');
                res.end(`No tile ${tile.z}/${tile.x}/${tile.y} in ${archiveName}`);
              } else {
                res.end();
              }
              return;
            }
            res.setHeader('Content-Type', layer.contentType);
            res.setHeader('Cache-Control', 'no-cache');
            res.end(Buffer.from(entry.data));
          } catch (error) {
            res.statusCode = 500;
            res.setHeader('Content-Type', 'text/plain; charset=utf-8');
            res.end(
              `Tile ${tile.z}/${tile.x}/${tile.y} from ${archiveName} failed: ` +
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
            // Mounted middleware sees the path AFTER the mount point, so the query is read off
            // whatever remains rather than off a URL that still says `/__perf`. The label is
            // untrusted — `perfCaptureName` owns making it safe, and owns it in one place.
            const arm = new URL(req.url ?? '/', 'http://localhost').searchParams.get('arm');
            const file = path.join(directory, perfCaptureName(stamp, arm));
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

// Dev-only: unlock the JS Self-Profiling API, which Chrome gates behind a document policy —
// `new Profiler(...)` throws `NotAllowedError: JS profiling is disabled by Document Policy` until
// this header is present, and no page-side code can grant it.
//
// DEV ONLY BY CONSTRUCTION, and it must stay that way: `configureServer` never runs for the static
// build, so this cannot reach production by being forgotten. It is a diagnostic that lets the page
// sample its own stacks, which is exactly what a visitor's page must not be able to do.
//
// The header goes on EVERY response rather than on documents alone. Discriminating would mean
// re-deriving "is this a document" from the URL here, and this middleware runs ahead of the asset
// servers below precisely so it cannot be skipped — a policy that arrives for some documents and
// not others is worse than one that is uniformly too broad on a dev server.
function jsProfilingPolicy(): Plugin {
  return {
    name: 'js-profiling-policy',
    configureServer(server) {
      server.middlewares.use((_req, res, next) => {
        res.setHeader('Document-Policy', 'js-profiling');
        next();
      });
    },
  };
}

// GPU MEMORY ACCOUNTING, DEV ONLY — and dev-only is what makes it affordable at all.
//
// The instrument this project ships is a SNAPSHOT, and the defects that have cost the most are
// TRAJECTORIES: an unbounded pool, a tile set that inflates under one kind of camera movement. The
// terms of that model are readable from MapLibre itself and the timeline samples them; what no
// page-side counter can see is how many bytes the GPU is actually holding, because WebGL exposes no
// memory query. `webgl-memory` (MIT) answers that by wrapping the context, and it also records a
// creation stack per resource — which turns "9 GB of textures exist" into "this code made them".
//
// WHY IT CANNOT BE AN IMPORT. It must patch `getContext` BEFORE `new maplibregl.Map` builds one, and
// a dynamic import cannot promise that against synchronous boot code — the same constraint that put
// `resourceTimingBuffer.ts` outside `lib/perf/`. A static import would instead ship 50 KB to every
// visitor and break the rule `lib/perf/lazyBoundary.test.ts` exists to enforce, which has already
// been violated once for exactly this reason. A classic <script> sidesteps both: the platform runs
// it before the deferred module scripts, so ordering is guaranteed rather than arranged.
//
// DEV ONLY BY CONSTRUCTION, like `jsProfilingPolicy` above: `configureServer` and `apply: 'serve'`
// never run for the static build, so this cannot reach production by being forgotten. It is served
// out of node_modules rather than copied into `public/`, so nothing enters the deployed bundle and
// no committed file can drift from the installed version.
//
// This plugin only SERVES the file; the tag that loads it is in `layouts/Base.astro`, behind an
// `import.meta.env.DEV` guard the build evaluates away. Injecting it from here via Vite's
// `transformIndexHtml` was tried and is silently inert — Astro renders page HTML itself and never
// runs that hook, so the route answered 200 while no tag ever appeared.
function webglMemoryDevTool(): Plugin {
  const scriptUrl = '/__webgl-memory.js';
  return {
    name: 'webgl-memory-dev-tool',
    apply: 'serve',
    configureServer(server) {
      // Resolved HERE rather than at module scope, so a production install without devDependencies
      // cannot fail the build on a missing dev tool. `apply: 'serve'` already prevents the plugin
      // running at build; this makes the file lookup follow the same rule rather than trust it.
      const scriptPath = createRequire(import.meta.url).resolve('webgl-memory');
      server.middlewares.use(scriptUrl, (_req, res: ServerResponse) => {
        res.setHeader('Content-Type', 'application/javascript; charset=utf-8');
        // Never cached: a version bump must take effect on reload, not on a cleared cache.
        res.setHeader('Cache-Control', 'no-store');
        res.end(fs.readFileSync(scriptPath, 'utf8'));
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
  build: {
    // Inline every page stylesheet into its document instead of linking it.
    //
    // The default is 'auto', which inlines only below Vite's 4 KB assetsInlineLimit — and the
    // globe's own sheet is 12 KB, so it sat just outside and cost a full round trip before anything
    // could paint. Measured on a devtools-throttled mobile profile: FCP **1,264 → 629 ms**, because
    // the document already has to arrive and a stylesheet that arrives with it is free of latency.
    //
    // This is deliberately NOT paired with inlining MapLibre's 70 KB, which is linked non-blocking
    // from earth.astro instead. Inlining both was measured too and came out SLOWER (689 ms): past
    // roughly the document's own size, the bytes you add to every page cost more than the round trip
    // you remove. The rule is "inline what blocks paint, link what does not".
    //
    // The cost is real and accepted: page CSS is no longer separately cacheable across navigations.
    // It is 12 KB on the globe and 5 KB on the gallery, against a 265 KB script that dwarfs both.
    inlineStylesheets: 'always',
  },
  vite: {
    plugins: [
      jsProfilingPolicy(),
      webglMemoryDevTool(),
      heroDevServer(),
      bordersDevServer(),
      tilesDevServer(),
      perfSnapshotServer(),
    ],
  },
});
