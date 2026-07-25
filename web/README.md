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

## 🚀 Project Structure

Inside of your Astro project, you'll see the following folders and files:

```text
/
├── public/
├── src/
│   └── pages/
│       └── index.astro
└── package.json
```

Astro looks for `.astro` or `.md` files in the `src/pages/` directory. Each page is exposed as a route based on its file name.

There's nothing special about `src/components/`, but that's where we like to put any Astro/React/Vue/Svelte/Preact components.

Any static assets, like images, can be placed in the `public/` directory.

## 🧞 Commands

All commands are run from the root of the project, from a terminal:

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

## Deploying

The site is served from three origins, because only the shell is small enough to ship
inside the build:

| What                          | Where                                    |
| :---------------------------- | :--------------------------------------- |
| Shell — HTML, JS, CSS, caps   | this Worker (`wrangler.jsonc`), ~13 MB   |
| Hero renders, border GeoJSON  | R2 bucket `terrella-assets`              |
| Relief tiles                  | the tile Worker in `worker/`             |

`pnpm build` addresses all three **same-origin**, which is what `astro dev` and the nginx
prod-sim serve. That build is correct locally and broken in production, where nothing but
the shell lives on the site's own origin. **`pnpm run deploy` is therefore the only correct
way to ship** — it sets the three `PUBLIC_*_BASE` variables first. They live in
`build:deploy` in `package.json` rather than a `.env.production`, which is gitignored to
keep API keys out of the repo; a test asserts that every base the code reads is supplied
there as an absolute URL, so adding a fourth cannot silently ship as same-origin.

Note `pnpm run deploy`, not `pnpm deploy` — the latter is a pnpm builtin.

Deploying from a fresh clone does not work, by design: the build reads
`src/data/countries.json` and `public/caps/`, both generated from the render store and both
gitignored. Regenerate them before deploying (see `docs/pipeline.md`).

### Zone configuration (Cloudflare dashboard)

Three settings live in the dashboard rather than in this repo, because neither wrangler's
OAuth nor an object-scoped S3 token can write them. `pnpm run deploy` does **not** apply
them, and each fails silently — a fresh setup needs all three.

| Setting                  | Where                                        | Value                                                                                  |
| :----------------------- | :------------------------------------------- | :------------------------------------------------------------------------------------- |
| Cache Rule               | Caching → Cache Rules                        | `http.host eq "assets.terrella.alchez.dev"` → Eligible for cache, Edge TTL 1 month, **Ignore cache-control** |
| CORS policy              | R2 → `terrella-assets` → Settings            | allow the site origin, `GET` + `HEAD`                                                  |
| Response header rule     | Rules → Transform Rules → Modify Response Header | same host match → set `Timing-Allow-Origin: *`                                      |

Why each is needed, since none is obvious from a failure:

- **Cache Rule** — `.geojson` and `.json` are not default-cached extensions (`.webp` and
  `.png` are), so without it every visit pulls the border GeoJSON from origin. R2 sends no
  `Cache-Control` at all, which is why the TTL must *ignore* the header rather than honour it.
  `cf-cache-status: DYNAMIC` is the signature of a missing rule; `MISS` then `HIT` is success.
- **CORS** — the globe `fetch`es both GeoJSON files, and a `fetch` needs CORS where an
  `<img>` hero does not. Getting this wrong breaks only the borders, not the heroes.
- **`Timing-Allow-Origin`** — without it, cross-origin Resource Timing reports `transferSize`
  and `decodedBodySize` as `0` rather than as unknown, so the site's own instrumentation reads
  its largest payload as free. It also degrades LCP attribution for the gallery's hero images.
  The tile Worker sets this header itself (`worker/index.ts`) and needs no rule.

## 👀 Want to learn more?

Feel free to check [our documentation](https://docs.astro.build) or jump into our [Discord server](https://astro.build/chat).
