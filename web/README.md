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
> does not — so changing the tile contract (`src/lib/reliefTiles.ts`) leaves a running dev server
> answering the *old* request shape while the freshly-compiled globe asks for the new one, and every
> tile 404s. **Restart the dev server after touching either.**

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
`tileConcurrency`, `perfOverlay`, `rungs`, `manifest`, `palette`.

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
| `pnpm run build:deploy` | Build addressing the production asset hosts      |
| `pnpm run deploy`      | `build:deploy`, then upload to Cloudflare        |

### Running a Lighthouse pass

```sh
npx lighthouse https://terrella.alchez.dev/globe/ \
  --output=json --output-path=/tmp/lh.json --only-categories=performance --quiet \
  --chrome-flags="--headless=new --no-sandbox --enable-unsafe-swiftshader --use-gl=angle --use-angle=swiftshader"
```

Three things will otherwise waste a run:

- **Headless Chrome needs the SwiftShader flags** or the globe never gets a WebGL2 context, and the
  page silently measures as the gallery instead.
- **`/` client-side steers to `/globe/`** (the `Base.astro` tier guard). Always check
  `finalDisplayedUrl` against `requestedUrl` in the JSON — otherwise you measure the globe twice and
  believe one run was the gallery.
- **Lighthouse cannot seed `localStorage`**, so the tier guard always decides for itself. Forcing
  Tier 1 needs `rg:quality = "lite"` in a pre-seeded Chrome profile; for a quick check, set it in a
  real browser instead and read Resource Timing. `rg:quality` persists — restore it afterwards.

The default (mobile) preset **is** the weak-Android test: Moto G Power, 4× CPU throttle, slow 4G.
Use `--preset=desktop` for the unthrottled number; the two differ by roughly 30 points here.

## Deploying

**→ [`DEPLOY.md`](DEPLOY.md)** — two Workers, the R2 bucket, the three dashboard-only zone
settings, and how to verify a deploy without a cache lying to you.

Short version: `pnpm run deploy` ships the shell (not `pnpm deploy`, which is a pnpm builtin), and
`cd worker && npx wrangler deploy` ships the tile Worker. They are separate; neither implies the
other.
