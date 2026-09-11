# Deploying Terrella

Two Workers, one R2 bucket, and three settings that live only in the Cloudflare dashboard.
Everything here is about `web/`; the pipeline that *produces* the assets is `docs/pipeline.md`.

## Where the site lives

Only the shell is small enough to ship inside the build, so production is four origins. The three that are not the site are exactly the `PUBLIC_*_BASE` variables `build:deploy` sets, which is what makes the count checkable:

| What                          | Where                                                       |
| :---------------------------- | :---------------------------------------------------------- |
| Shell: HTML, JS, CSS, caps    | site Worker (`wrangler.jsonc`), `du -sh dist` for its size  |
| Hero renders, border GeoJSON  | R2 bucket `terrella-assets`, at `assets.terrella.alchez.dev` |
| Relief tiles, terrain-RGB DEM | tile Worker (`worker/`) over an R2 binding                   |
| Whole archives, as downloads  | `archives.terrella.alchez.dev`, the tile bucket direct       |

The last two are the same bucket reached two ways, and the difference is what the free tier charges for: a tile is a Worker invocation, a download is not. See § *What is public* in `.claude/rules/tile-worker-and-delivery.md`.

The tile Worker serves **six** archives out of one bucket, told apart by the address:
`{body}/{layer}/{token}/{z}/{x}/{y}.{ext}`, where the layer segment is `relief`, `terrain` or
`vector`. **The segment is the layer's ROLE, never the object's product name**: Earth's vector cut is
keyed `earth/countries-v3.pmtiles` and is still addressed `earth/vector/...`, so a URL built from the
key 404s. That segment also carries the whole distinction between a body's two raster pyramids, which
share a grid and a zoom span, so serving the wrong one would displace the globe rather than fail.

Which archive each `{body}/{layer}` resolves to is the registry in `src/lib/tileAddress.ts`, which
the Worker and the client both compile. Uploading a new archive is `aws --profile r2 --endpoint-url
<r2> s3 cp <file> s3://terrella-tiles/<key>`, then point that layer's registry entry at the new
key and regenerate its token with `pnpm check:tile-tokens --write`; a re-cut always ships under a
**new key**, never an overwrite.

**Deleting the superseded object is irreversible, so it comes last.** R2 implements no object
versioning and no undelete — `ListObjectVersions` answers `NotImplemented` — so a removed archive
is gone from the bucket for good. Delete only once the new key is verified live, because until then
the old object is what makes a rollback a revert-and-redeploy rather than a rebuild.

**The copies on the render box are not a substitute.** The raster cutters keep exactly one
generation at `tiles_old` and the next run of that stage removes it, so a pyramid is restorable from
disk only until it is next cut — a rollback for the run you just did, not an archive. The vector
archives keep no previous generation at all and their source GeoJSON is overwritten in place by the
derivation, so rebuilding one means reverting the geometry rule out of git and re-cutting.

**Ship the tile Worker BEFORE the site.** The token in a tile URL comes from the site bundle, and
the Worker is what routes it — so a site deployed first advertises addresses the live Worker may
not answer, and the globe comes up blank. The reverse is harmless: a Worker that understands an
address nobody is asking for yet costs nothing.

**There are TWO deploys.** `pnpm run deploy` ships the shell only; the tile Worker has its own
config and its own command. Neither touches the other.

### What the free tier actually buys

The Workers account is on the free plan, which only the dashboard shows: the API does not answer it. Cloudflare's [Workers](https://developers.cloudflare.com/workers/platform/pricing/) and [R2](https://developers.cloudflare.com/r2/pricing/) pricing pages own every limit and rate, so none is copied here; this section owns how Terrella spends them. Two limits bind, and they fail differently, so neither is simply the tighter one.

- **Requests stop the site.** The free plan's daily request limit is account-wide, and past it comes Error 1027 or fail-open. The site shell is static assets, which do not count, so the tile Worker spends it alone: **74 tile requests per view at z6** on the `full` tier, which makes the limit divided by 74 the number of cold visits a day the site serves.
  - **A cache hit is billed as a request.** Caching improves latency, never the request count, so no cache-tuning lever moves this number.
  - **Terrain roughly doubles the count by declaration, not by law**: relief declares `tileSize: 256` and terrain declares `tileSize: 128`, and it is the smaller one that makes terrain draw twice as many.
  - **A download is not a Worker request** and spends none of the limit: `archives.terrella.alchez.dev` serves the bucket direct, one Class B operation per file and no egress charge. So the answer to anyone who wants the data is take an archive, not hit the tile endpoint.
- **Storage costs money.** The two buckets together are past R2's free storage allowance, and overage is billed per GB-month, rounded up to the next whole one. At R2's rate that makes a new pyramid a disk-and-time decision rather than a cost one.
  - **Measure it rather than believing a figure written here**: `aws --profile r2 --endpoint-url "$R2_ENDPOINT" s3 ls --recursive --summarize s3://terrella-tiles`, then the same for `terrella-assets`.
- **Workers Paid is what buys past the request limit**: a flat monthly fee including an allowance of requests and CPU time, then a rate per million of each. A month at `full` is cold visits a day × 74 × 30 requests against that allowance, and the CPU time the tile Worker spends per request, which only the dashboard reports, prices the rest.

## 1. The tile Worker

```sh
cd worker && npx wrangler deploy
```

**Required whenever `worker/` or anything it imports changes** — which is `src/lib/tileAddress.ts`
and everything it reaches, the registry and `tileTokens.json` among them. Named as the entry point
rather than as a list of modules, because a list goes stale in silence: a reader who checks it,
finds their file absent and skips this deploy ships a site advertising addresses the live Worker
cannot resolve.

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

## 2. The site shell

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

**The preflight can refuse.** `scripts/check_deploy_sync.ts` runs before the upload and blocks on
three things: an object the manifest promises that R2 does not have, a globe that would request
terrain no Worker routes, and **any archive the registry publishes** that is not in
`terrella-tiles`. All three are silent in production — a 404ing tile does not stop the globe
rendering, it just renders wrong, flat, or blank with nothing in any log. The refusal message names
the file to change.

The third enumerates rather than naming keys, and that is what closed a real hole: it used to read
two named variables out of the Worker's config, so the country pyramid was never checked at all and
a deploy missing it reported clean. A fourth archive is now checked the day it is published, by a
script nobody edited.

It is also the one to expect after a re-cut: packing and uploading an archive are separate steps
from deploying, so bumping the registry entry before the upload finishes is the easy mistake. The
preflight turns that into a refusal instead of an outage.

## Verifying a deploy

A caching layer replaying stored bytes is the most reliable way to misread a good deploy as a
broken one. Both checks below exist to get around one.

### The shell — use a cache-buster, not the plain URL

For about a minute after `pnpm run deploy`, `https://terrella.alchez.dev/earth/` can still serve the
**previous** HTML — `cf-cache-status: HIT`, referencing the old `_astro` chunk hash — while the new
chunk is already uploaded and reachable. It reads exactly like a silent failure. It is not; the edge
copy clears itself. Bypass the cached key instead:

```sh
curl -s "https://terrella.alchez.dev/earth/?cachebust=$RANDOM" | grep -o '/_astro/earth[^"]*\.js'
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
