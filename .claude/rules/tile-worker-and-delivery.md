---
paths:
  - "web/worker/**"
  - "deploy/**"
  - "web/wrangler*"
---

# Serving Terrella: the tile Worker and what it may not do

Everything is pre-rendered. There is no server-side compute at request time, and the site is served
entirely from the CDN rather than from the box that runs the pipeline.

- Tiles ship as **PMTiles**, ranged *server-side* into whole `z/x/y` tiles. The browser never opens the archive.
- **Cloudflare:** a site Worker over `web/dist`, R2 for archive, heroes and borders, and a separate tile Worker.
- The tile Worker is mandatory rather than stylistic. Cloudflare caps a cacheable object at 512 MB, so a multi-GB archive can never be an edge object; the Worker turns range reads into ~40 KB tiles, which *are* cacheable.

## The landmine

**Never let the browser send `Range` at a Worker.** Workers Caching strips the header and asks the
origin for the *full body*, which means the whole archive is fetched per tile. Request whole tiles
by `z/x/y` and do the byte arithmetic inside the Worker, against an R2 binding.

This fails as a bill and a latency cliff rather than as an error, which is why it is written down
where Worker code is opened rather than left to be rediscovered.
