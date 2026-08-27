---
paths:
  - "web/worker/**"
  - "deploy/**"
  - "web/wrangler*"
  # The archive keys live here, and changing one is what the deploy-order section below is about.
  - "web/src/lib/tileAddress.ts"
  - "web/src/lib/tileTokens.json"
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

## Shipping a re-cut archive

**A re-cut takes a NEW object key and is never an overwrite.** The reason is in `tileAddress.ts`,
beside Mars's relief entry; read it there rather than trusting a summary of it here.

**TWO Workers ship a key change, not one.** `worker/index.ts` imports the registry, so `objectKey`
is compiled into the tile Worker rather than read at request time. Deploying only the site leaves
the tile Worker fetching the previous archive, and nothing anywhere reports the disagreement.

**Deploy the TILE Worker first, then the site.** `parseTileAddress` checks that a token is
well-formed and never that it matches the registry, so during the window between the two deploys
whichever Worker is behind decides what the other serves:

- Tiles first: old-token requests briefly return new bytes, which cache under a token the updated
  HTML will never ask for again. Harmless, and it self-clears.
- Site first: new-token URLs return the OLD archive, and tiles are cached `immutable` for a year.
  Nothing short of another token change can clear them, so this is the order that does real damage.

**Regenerating a token re-anchors a sabotage needle.** `scripts/sabotage.py` pins one case to a
literal token value in `tileTokens.json`, the one generated file the table names, so a re-cut turns
the gate red with nothing else wrong. Update the needle in the same change as the token, or the
failure lands on CI after the deploy has already shipped.

**`No targets deployed for terrella-tiles` is normal output, not a failure.** It means the deploy
created no new route bindings; the custom domain persists across versions. The check that actually
settles it is fetching a tile from production and comparing it against the local archive
(`tools/pmtiles tile <archive> z x y`), at a deep zoom as well as a shallow one, since a truncated
upload shows up in the leaves rather than at the root.
