# `deploy/` — a local production simulator

**Nothing here is deployed anywhere, and this is not a deployment you are expected to use.**
The live site runs on Cloudflare (`web/DEPLOY.md`). This directory exists for two reasons:

1. **To run the built site locally the way a real server would** — production's cache classes and
   compression, offline, with no Cloudflare account.
2. **To be a worked example of what Terrella's static output needs from an HTTP server**, for anyone
   serving it somewhere else. Serve it however you like; this is a reference, not a prescription.

```sh
cd deploy
./make-local-cert.sh                        # once — self-signed cert for :443
docker compose --env-file ../web/.env up -d
```

Store paths come from `web/.env`, the same single source of truth the Astro dev middleware uses.
Then `http://localhost:8080` (plain HTTP) or `https://localhost:8443` (TLS + HTTP/2).

## What the site needs from a server

Most of this is visible in `nginx/terrella-locations.conf`, which is commented with the reasoning.
The two worth stating separately are the ones that **fail silently** — the site looks fine and is
quietly wrong:

- **Compress the GeoJSON.** `countries.geojson` is **8.96 MB → 2.50 MB** gzipped (3.6×) and the globe
  `fetch`es it on every visit. Miss this and nothing breaks; the globe is just slow forever. Scope
  compression to text-like types only — the WebP tiles, hero images and the PMTiles archive are
  already compressed, so recompressing them costs CPU for roughly zero bytes.
- **Send `Timing-Allow-Origin` if assets are on a different origin than the page.** Without it,
  cross-origin Resource Timing reports every size and duration as `0` — the same value a genuinely
  free resource reports. The site's own instrumentation then reads its largest payloads as costless.

The rest fails loudly enough to find:

- **Three cache classes.** `/_astro/` is content-hashed, so `immutable` for a year. The asset stores
  and `/caps/` change rarely — a week plus ETag revalidation. **HTML must be `no-cache`** (meaning
  "store, but revalidate", not "don't store"), because a stale HTML page references build-asset URLs
  that no longer exist, which presents as a site that loads and then does nothing.
- **`.geojson` needs a content type.** It is absent from the standard mime map.
- **CORS**, if the assets are on a different origin: the globe `fetch`es the GeoJSON, and a `fetch`
  needs CORS where an `<img>` hero does not. Getting this wrong breaks only the borders.

## What this sim deliberately cannot do

**Relief tiles.** The site asks for one tile per request at `/tiles/{z}/{x}/{y}.webp`, ranged out of
the PMTiles archive by a tile server — the Astro dev middleware locally, a Worker over R2 in
production. nginx can be neither, so `/tiles/` returns a `501` that says so rather than letting the
globe render an unexplained blank sphere. Everything else here is a faithful twin.
