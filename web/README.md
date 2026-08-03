# Terrella — frontend (`web/`)

The Astro site: Tier-1 gallery, country detail pages, About, and the `/globe` route (a MapLibre
globe over the raster tile pyramid), with a capability probe that auto-steers between tiers.

## First-run setup (fresh checkout / worktree)

`web/` depends on three things that are **not** in git — they are generated or machine-specific,
so a fresh clone or worktree has none of them and **every route 500s (`FailedToLoadModuleSSR`)
until all three exist**. In order:

1. **`.env`** — store paths for the dev middleware, which serves `/heroes`, `/borders` and
   `/tiles` straight off disk (the static build never reads them; a deploy points the site at
   object storage instead, via the `PUBLIC_*_BASE` vars the same template documents).
   Copy the template and set each var to an absolute local path — there is no fallback, an unset
   var fails the dev server with a clear message:
   ```sh
   cp .env.example .env
   # edit HERO_STORE / BORDERS_STORE / PMTILES_STORE, e.g. PMTILES_STORE=/path/to/maps/data/work/planet_tiles
   ```
   `.env` is gitignored (machine-specific), which is why it does not travel with the checkout.

2. **Dependencies**:
   ```sh
   pnpm install
   ```

3. **The gallery manifest** `src/data/countries.json` — generated from the hero-variant store,
   and imported by all three pages (index, `[slug]`, globe), so its absence 500s the whole site.
   Also gitignored. Regenerate it whenever heroes are re-rendered:
   ```sh
   ../.venv/bin/python scripts/gen_manifest.py --out src/data/countries.json
   ```
   Requires the hero WebP variants and the Natural Earth admin-0 shapefile to already exist.

Then start the server (add `--host` to reach it from another device on your LAN, e.g. a phone):
```sh
pnpm dev --host
```

> If you rebuilt the tile pyramid while the server was running, the browser may hold stale tiles
> and a failed SSR import can stay cached — a server restart plus a hard reload clears both.

> **Vite does not hot-reload `astro.config.ts`.** Page and lib code reloads, the `/tiles` middleware
> does not — so changing a tile contract (any of the `src/lib/` modules the config imports) leaves a
> running dev server answering the *old* request shape while the freshly-compiled globe asks for the
> new one, and every tile 404s. **Restart the dev server after touching the config, or any module it
> imports.**

### Baked or live — the rule for where a value gets computed

Applied to every visual constant on the site, and worth knowing before adding a knob:

- Too expensive to compute live → **baked** into the asset.
- Depends on view state (camera, zoom, pitch) → **live**.
- Invariant *and* physics-coupled (sun geometry, exaggeration) → **baked**, so the heroes and the
  tiles cannot disagree.
- Otherwise → **live, but pinned to authored constants** rather than computed from the data.
- A **user-exposed setting** only where visitor context genuinely varies — device capability, motion
  and data preferences. Not for things we simply have an opinion about.

### The tile request contract

`{z}/{x}/{y}.webp`, z0–8, one tile per request. `src/lib/reliefTiles.ts` is the single source of
truth for all of it — extension, content type, path parser and zoom range — and both servers import
it: the `/tiles` middleware in `astro.config.ts` for dev, `worker/index.ts` for production. They
differ only in where the bytes come from (a local file vs an R2 binding); the browser never opens
the archive itself.

The extension follows the archive's declared tile type, which is set by the pipeline
(`TILE_CUT` in `pipeline/tile/shade_planet.py`) and carried through by `pack_pmtiles`. A PMTiles
archive stores **one** encoding for every tile, so this is a single global fact, not a per-tile one.
Changing it is also the cache-bust: every tile URL changes, so a re-cut needs **no zone purge**.

## Project structure

```text
web/
├── astro.config.ts        # build config + the dev-only /heroes, /borders, /tiles middleware
├── wrangler.jsonc         # the site Worker — serves dist/ as static assets
├── public/
│   └── caps/              # polar cap WebP rungs + caps.json (generated; gitignored)
├── scripts/
│   ├── gen_manifest.py    # reads the variant store → src/data/countries.json
│   └── check_deploy_sync.ts   # deploy preflight: R2 objects vs the manifest
├── src/
│   ├── pages/             # index (gallery) · [slug] (country) · globe · about
│   ├── layouts/ components/ styles/
│   ├── lib/               # the tested logic — see below
│   └── data/              # countries.json (generated; gitignored)
└── worker/                # the tile Worker: one z/x/y out of the PMTiles archive in R2
```

`src/lib/` is where anything worth testing lives, each module paired with a `.test.ts`:
`reliefTiles` (the tile request contract, imported by *both* servers), `assetBase` (dev vs
production origins), `capability` + `fpsDegradation` (the tier probe and runtime downgrade),
`hoverTracking` (hover resolution, including re-resolving when the globe moves under a parked
pointer), `countryHighlight`, `polarCaps` (rung choice by projected on-screen size),
`terrainSource`, `tileCacheBudget`, `glDiagnostics`, `skyAtmosphere`, `tileConcurrency`, `rungs`,
`manifest`, `palette`.

`src/lib/perf/` holds the `?perf` instrument alone — `perfOverlay`, `perfSnapshot`, `perfNetwork`.
It is a **lazy boundary**: no page may statically value-import from it, so a visitor without the flag
never downloads it. `lazyBoundary.test.ts` enforces that for the whole directory, because guarding it
per-file let a regression ship 268 lines of instrument to every visitor. The one exemption is
`lib/resourceTimingBuffer.ts`, which has to run before the map is constructed and says so in its
header.

## Diagnostic flags

Query flags on `/globe`, for isolating one variable during a measurement. They are **URLs rather than
UI controls on purpose**: several are `Map` *constructor* options that cannot be changed on a live map
(`skirt` is baked into the cached terrain mesh, `maxreq` is set before any request goes out,
`demcache` sizes a cache at construction), and more importantly an experiment arm should be a
*reproducible address*. A toggle that flips state in place invites comparing two arms within one page
load, which has already produced one 47% effect that did not exist.

A malformed value is **refused loudly** (a console warning naming the accepted set) and the default
applies — never silently, because a run that believes it swept one value while running another is
worse than no run.

| Flag | Values | What it does |
| --- | --- | --- |
| `?perf` | — | The performance panel: timings, long tasks, frame rate, GL state, tile bytes, fill time, and an export button. Also sets `window.terrellaMap` for scripted camera routes. |
| `?bare` | — | Tiles only: no caps, no borders, no country interaction. The floor of the loading window. |
| `?nocaps` | — | Drops the polar caps. They are the largest VRAM term we allocate ourselves. |
| `?terrain=` | `N` \| `off` | Forces 3D displacement on at any tier with exaggeration `N`, or `off` as a flat control **without demoting the tier**. Zero is refused — indistinguishable from off. |
| `?maxreq=` | 1–`MAX_PARALLEL_IMAGE_REQUESTS_CEILING` | MapLibre's parallel image cap, which every tile, sprite and icon shares as one FIFO queue. The site raises MapLibre's own 16 to `RAISED_MAX_PARALLEL_IMAGE_REQUESTS` for an unconstrained visitor, and leaves it at 16 under `Save-Data`, a slow link, or a phone — see `src/lib/tileConcurrency.ts`. The sweep found no saturation below the ceiling, so a higher arm needs that constant raised first. |
| `?demcache=` | `off` \| slots | The DEM tile cache bound — `off`, an explicit slot count, or absent for the canvas-derived cap. |
| `?demsize=` | `256` \| `512` | The DEM tile size declaration. 512 is the most expensive arm by far: render tiles are per-frame framebuffer binds plus a full replay of the layer stack. |
| `?skirt=` | `auto` \| `none` | Terrain skirt length (ships `none`). A **constructor** option — the skirt is baked into the cached mesh, so it needs one page load per arm. |
| `?sky=` | `off` \| `0`–`1` | The atmosphere blend floor. `0` is accepted and meaningful here (no atmosphere past the overview), unlike `?terrain=0`. |
| `?ramp=` | `off` \| number | The terrain exaggeration ramp's floor — the value it decays to at z8. Non-integers are fine; it is a continuous look knob. |

## Commands

Run from `web/`:

| Command                   | Action                                           |
| :------------------------ | :----------------------------------------------- |
| `pnpm install`             | Installs dependencies                            |
| `pnpm dev`             | Starts local dev server at `localhost:4321`      |
| `pnpm build`           | Build your production site to `./dist/`          |
| `pnpm preview`         | Preview your build locally, before deploying     |
| `pnpm astro ...`       | Run CLI commands like `astro add`, `astro check` |
| `pnpm astro -- --help` | Get help using the Astro CLI                     |
| `pnpm check`           | Type-check (`astro check`) — must report 0 errors |
| `pnpm test`            | Unit tests (vitest)                              |
| `pnpm run check:test-collection` | Asserts every `*.test.ts` is collected by a vitest project |
| `pnpm run build:deploy` | Build addressing the production asset hosts      |
| `pnpm run deploy`      | `build:deploy`, then upload to Cloudflare        |

### Proving a guard is not vacuous

`pnpm test` going green says every guard passed. It does not say any guard would have *failed*, and
several here would not have: a regex anchored `^import` never matched Astro's indented imports, and a
duplicate assertion in `capability.test.ts` was vacuous its whole life. Both passed happily.

**`uv run scripts/sabotage.py`** (from the repo root) settles it. Each case breaks one string in one
source file, runs the suite, and restores the file — and it names the test that must catch it, so "the
suite went red" is not accepted as proof. A full pass runs the whole suite once per case, so budget
roughly that: `--list` prints the current table and runs nothing.

Most cases drive `pnpm test`. The rest drive `pytest`, and they are the ones worth knowing about: they
sabotage the guards that keep the *documentation and the table itself* honest — an unclosed code fence,
a clipped table row, a case whose needle a refactor has moved. The gate that keeps this table honest is
a guard like any other, so it gets the same treatment.

```sh
uv run scripts/sabotage.py                  # every case
uv run scripts/sabotage.py --filter cap     # cases whose label or path matches
uv run scripts/sabotage.py --suite web      # one suite only
uv run scripts/sabotage.py --list           # the table, run nothing
uv run scripts/sabotage.py --restore        # put the tree back after a killed run
```

Add a case whenever you add a guard, with the guard's test name. `tests/test_sabotage_cases.py` checks
the table against the tree on every `pytest` run — so a needle a refactor moved fails in a tenth of a
second, rather than as a shrug minutes into a run nobody is watching.

### Running a Lighthouse pass

**The GL flag chooses which tier you measure**, so it is the experiment rather than boilerplate.
`Base.astro`'s pre-paint guard bounces `/earth/` back to `/` whenever the renderer string names a
software rasterizer — which makes SwiftShader the Tier-1 recipe and hardware ANGLE the Tier-3 one.

```sh
# The globe. Hardware ANGLE, or the guard sends you to the gallery.
npx lighthouse https://terrella.alchez.dev/earth/ \
  --output=json --output-path=/tmp/lh-globe.json --only-categories=performance --quiet \
  --chrome-flags="--headless=new --no-sandbox --use-gl=angle --use-angle=gl"

# The gallery. SwiftShader fails that same guard, on purpose.
npx lighthouse https://terrella.alchez.dev/ \
  --output=json --output-path=/tmp/lh-gallery.json --only-categories=performance --quiet \
  --chrome-flags="--headless=new --no-sandbox --enable-unsafe-swiftshader --use-gl=angle --use-angle=swiftshader"
```

These will otherwise waste a run:

- **Always check `finalDisplayedUrl` against `requestedUrl`.** The guard steers both ways — `/` to
  `/earth/` for a capable visitor, `/earth/` to `/` for everyone else — and a steered run is a
  clean, green, entirely valid report about the wrong document. It is the only check that catches a
  recipe the site has outgrown, which is how the SwiftShader flags above stopped measuring the globe.
- **Headless Chrome reaches for SwiftShader on its own.** Dropping the GL flags entirely does not
  give you the GPU, it gives you the gallery. Read `UNMASKED_RENDERER_WEBGL` before believing a
  surprising number.
- **Read the tier off the final screenshot.** The view bar's highlighted pill says which tier the
  run actually got; `full` and `globe` differ by the idle spin and the in-globe hero panel, and
  nothing else in the report distinguishes them.
- **One run is not evidence.** Take three, quote the median and the spread. TBT has swung by most of
  its own magnitude between consecutive runs of an identical command, which is larger than most
  effects worth chasing.
- **Lighthouse cannot seed `localStorage`.** Tier 1 no longer needs a pre-seeded profile because the
  SwiftShader recipe reaches it; pinning Tier 2 on a capable machine still does (`rg:quality =
  "globe"`, which persists — restore it afterwards).

The default preset **is** the weak-Android test: Moto G Power, 4× CPU throttle, slow 4G.
`--preset=desktop` is the unthrottled number. Both keep the host's real GPU, so neither is a phone —
and a score measured under a software rasterizer is not comparable to one measured on a GPU.

**The preset is DPR 1.75, which is lower than any current phone** (2.6–3.0). That matters for
anything `srcset` selects, because rung choice is a step function of device pixels: a payload can be
fine at 1.75 and three times larger at 3.0. Override with
`--screenEmulation.mobile --screenEmulation.width=390 --screenEmulation.height=844
--screenEmulation.deviceScaleFactor=3` and read `audits['network-requests']` to see which rung the
browser actually took.

### A two-arm A/B against a local build

Build both arms, then serve them **sequentially on the same port** so origin, port and protocol are
held constant and only the markup varies. Heroes come from R2 in both arms, so image bytes are real.

- **Serve through something that compresses.** `python3 -m http.server` sends identity encoding, so
  an arm that adds markup is billed for its full uncompressed size — 201 `<noscript>` twins cost
  +164 KiB raw against +2.6 KiB gzipped, which ate about a second and understated a fix by a third.
  The tell is `transferSize == resourceSize` on the document; assert `transferSize < resourceSize`
  before quoting anything.
- **Then validate the harness against production itself** before believing the delta. One run
  against the live site should land near the *before* arm — 3% on LCP and identical CLS is what
  a faithful harness looks like. Absolutes do not transfer between origins; deltas do.
- Gate every run on `finalDisplayedUrl`, on a non-zero hero request count, and on CLS, which a
  layout-collapsing arm is otherwise the obvious way to fake.

### Chasing a layout shift

Lighthouse gives a CLS number and a list of shifted elements; neither is enough to fix one, because
**the element that moves is rarely the element that caused the move**. Drive a browser directly and
read `layout-shift` entries with their `sources` — each carries the node plus its `previousRect` and
`currentRect`, so the direction and distance are readable rather than inferred.

- **Record the state of the document at the instant of each shift** — how much of it had parsed,
  which resources had landed, `readyState`. That is what separates "an image arrived" from "a font
  swapped" from "a script mutated the DOM", and it is not recoverable afterwards.
- **The score is driven by the furthest distance anything travelled, not by the height change.**
  A header growing 38 px scored 0.19 because the nav inside it also moved 190 px sideways. Reasoning
  about the vertical shift alone will not reproduce the number.
- **Measure cold and warm as separate arms.** A webfont applies at first paint on a repeat visit and
  after it on a first one, which are different experiments — one CLS fix measured 0.001 cold and
  0.193 warm. Warm requires the harness to send `Cache-Control: immutable` on `/_astro/*`; without
  it the browser revalidates, the font misses its window, and the warm arm silently degrades into a
  second cold one. Prove it with `transferSize === 0`.
  - **That arm is currently a hypothesis, not production.** Measured on the live site: every
    content-hashed asset — fonts, chunks, CSS — comes back `public, max-age=0, must-revalidate`
    with an ETag, and `If-None-Match` confirms a `304`. So a repeat visitor revalidates before the
    font can be used, and the true warm behaviour sits between the two arms rather than at the
    immutable one. `worker/index.ts` does send `immutable`, but it serves *tiles* on another
    origin; the site's own assets are Workers Static Assets defaults, and there is no `_headers`
    file. The local nginx twin **does** send `immutable` (`deploy/nginx/terrella-locations.conf`),
    which makes it kinder than the CDN — the same shape as the identity-encoding trap above.
- **Never intercept the document to simulate a change.** Rewriting the response body (Playwright's
  `route.fulfill`, or any equivalent) serves it from memory instead of streaming it over the
  throttled link, which moves every resource's arrival relative to paint. The control is decisive:
  the *unchanged* page measured 0.328 served normally and 0.001 intercepted. Build the arm.

## Deploying

**→ [`DEPLOY.md`](DEPLOY.md)** — two Workers, the R2 bucket, the three dashboard-only zone
settings, and how to verify a deploy without a cache lying to you.

Short version: `pnpm run deploy` ships the shell (not `pnpm deploy`, which is a pnpm builtin), and
`cd worker && npx wrangler deploy` ships the tile Worker. They are separate; neither implies the
other.
