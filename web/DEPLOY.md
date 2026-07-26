# Deploying Terrella

Two Workers, one R2 bucket, and three settings that live only in the Cloudflare dashboard.
Everything here is about `web/`; the pipeline that *produces* the assets is `docs/pipeline.md`.

## Where the site lives

Only the shell is small enough to ship inside the build, so production is three origins:

| What                         | Where                                   |
| :--------------------------- | :-------------------------------------- |
| Shell — HTML, JS, CSS, caps  | site Worker (`wrangler.jsonc`), ~13 MB  |
| Hero renders, border GeoJSON | R2 bucket `terrella-assets`             |
| Relief tiles                 | tile Worker (`worker/`) over an R2 binding |

**There are TWO deploys.** `pnpm run deploy` ships the shell only; the tile Worker has its own
config and its own command. Neither touches the other.

## 1. The site shell

```sh
pnpm run deploy          # NOT `pnpm deploy` — that is a pnpm builtin
```

`pnpm build` addresses all three origins **same-origin**, which is what `astro dev` and the nginx
prod-sim serve. That build is correct locally and broken in production, where nothing but the shell
is on the site's own origin — so `pnpm run deploy` is the only correct way to ship. It sets the
three `PUBLIC_*_BASE` variables first.

Those variables live in `build:deploy` in `package.json` rather than a `.env.production`, which is
gitignored to keep API keys out of the repo. A test asserts every base the code reads is supplied
there as an absolute URL, so adding a fourth cannot silently ship as same-origin.

**A fresh clone cannot deploy, by design.** The build reads `src/data/countries.json` and
`public/caps/`, both generated from the render store and both gitignored. Regenerate them first —
see `docs/pipeline.md`.

## 2. The tile Worker

```sh
cd worker && npx wrangler deploy
```

Required whenever `worker/` or anything it imports (`src/lib/reliefTiles.ts`) changes.

Two things about this deploy are confusing enough to waste a session:

- **`No targets deployed for terrella-tiles` is not an error.** The site Worker declares
  `routes: [{ pattern: "terrella.alchez.dev", custom_domain: true }]`; the tile Worker declares
  **no routes**, because `tiles.terrella.alchez.dev` is attached to it **in the dashboard only**.
  Wrangler is reporting that the config named no targets, not that the version failed. It does go
  live — confirm from outside rather than from the message.
- **A fresh setup must attach that custom domain by hand**, or the Worker deploys successfully and
  is unreachable at every hostname: `workers_dev` and `preview_urls` are both off by design.
  Declaring the route in `worker/wrangler.jsonc` would fix both points. It has not been done
  because the domain is already attached and re-declaring it touches live routing.

## Verifying a deploy

A caching layer replaying stored bytes is the most reliable way to misread a good deploy as a
broken one. Both checks below exist to get around one.

### The shell — use a cache-buster, not the plain URL

For about a minute after `pnpm run deploy`, `https://terrella.alchez.dev/globe/` can still serve the
**previous** HTML — `cf-cache-status: HIT`, referencing the old `_astro` chunk hash — while the new
chunk is already uploaded and reachable. It reads exactly like a silent failure. It is not; the edge
copy clears itself. Bypass the cached key instead:

```sh
curl -s "https://terrella.alchez.dev/globe/?cachebust=$RANDOM" | grep -o '/_astro/globe[^"]*\.js'
```

Compare that against the chunk name wrangler just listed as uploaded.

### The tile Worker — ask a tile, read two headers

```sh
curl -sD- -o /dev/null -H "Origin: https://terrella.alchez.dev" \
  https://tiles.terrella.alchez.dev/8/155/99.webp | grep -iE "cf-cache-status|server-timing"
# cf-cache-status: MISS
# server-timing: cache;dur=6, r2;dur=281;desc="1 read, 148540 B", worker;dur=287
```

- **`Cf-Cache-Status` present at all** means Workers Caching is live. Absent means the `cache` block
  in `worker/wrangler.jsonc` did not take.
- **`MISS` right after a deploy is expected.** The Worker version is part of the cache key
  (`cross_version_cache` is off), so every deploy starts cold — that is also the invalidation
  mechanism, and why there is nothing to purge.
- **`Server-Timing` is only true on a `MISS`.** On a `HIT` the Worker never runs, so the stored
  header is replayed verbatim, reporting whichever request filled the cache. The tell is arithmetic:
  a total well below the replayed `worker;dur` is a stale header, not a fast Worker. Read the read
  count (`1 read` = index prefetch working) only on a `MISS`.
- **Send the `Origin` header.** Responses carry `Vary: Origin`, so a bare `curl` populates and reads
  a variant no browser ever touches — and a cross-origin request is the only way to exercise the
  CORS path the globe actually uses.
- **`caches.default` is consulted inside the Worker and is *not* version-keyed.** A tile can be
  `Cf-Cache-Status: MISS` (new Worker version) while `X-Terrella-Cache: hit` serves a body from
  before the deploy. For a genuinely cold measurement require **both** to say miss, and pick an
  address never fetched before.

## Zone configuration (Cloudflare dashboard)

Three settings live in the dashboard rather than this repo, because neither wrangler's OAuth nor an
object-scoped S3 token can write them. `pnpm run deploy` does **not** apply them and each fails
silently, so a fresh setup needs all three.

| Setting              | Where                                            | Value                                                                                                       |
| :------------------- | :----------------------------------------------- | :---------------------------------------------------------------------------------------------------------- |
| Cache Rule           | Caching → Cache Rules                            | `http.host eq "assets.terrella.alchez.dev"` → Eligible for cache, Edge TTL 1 month, **Ignore cache-control** |
| CORS policy          | R2 → `terrella-assets` → Settings                | allow the site origin, `GET` + `HEAD`                                                                       |
| Response header rule | Rules → Transform Rules → Modify Response Header | same host match → set `Timing-Allow-Origin: *`                                                              |

Why each is needed, since none is obvious from its failure:

- **Cache Rule** — `.geojson` and `.json` are not default-cached extensions (`.webp` and `.png`
  are), so without it every visit pulls the border GeoJSON from origin. R2 sends no `Cache-Control`
  at all, which is why the TTL must *ignore* the header rather than honour it.
  `cf-cache-status: DYNAMIC` is the signature of a missing rule; `MISS` then `HIT` is success.
- **CORS** — the globe `fetch`es both GeoJSON files, and a `fetch` needs CORS where an `<img>` hero
  does not. Getting this wrong breaks only the borders, not the heroes.
- **`Timing-Allow-Origin`** — without it, cross-origin Resource Timing reports `transferSize` and
  `decodedBodySize` as `0` rather than as unknown, so the site's own instrumentation reads its
  largest payload as free. It also degrades LCP attribution for the gallery's hero images. The tile
  Worker sets this header itself (`worker/index.ts`) and needs no rule.
