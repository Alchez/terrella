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

## Moving or deleting an object in R2

**`aws s3 cp` cannot copy inside R2 at all.** It calls `GetObjectTagging`, which R2 answers
`NotImplemented`, and every copy fails on that before touching a byte. Use the low-level
`aws s3api copy-object --bucket B --key NEW --copy-source B/OLD`, which does not ask for tags.

**A server-side copy of a multi-GB object blocks for about two minutes and the CLI gives up first.**
Measured on this bucket: 98 to 128 s per 2.3 to 3.1 GB object, against a default read timeout of 60 s,
so every large copy times out and is abandoned while a 10 MB one finishes in 3 s. Pass
`--cli-read-timeout 0`. The failure looks like a network fault and is not one.

**Deleting is allowed; it is UNDELETE that R2 does not have.** `DeleteObject` and `DeleteObjects`
both work. What is missing is versioning, so `ListObjectVersions` answers `NotImplemented` and a
removed object is gone. Read "no undelete" as "one-way", never as "not permitted".

**Renaming an archive key needs the TILE WORKER deploy and nothing else.** A tile token is a SHA-256
over the archive's CONTENT (`gen_tile_tokens.ts` streams the file), so identical bytes under a new
key keep every tile URL identical, and the site shell builds URLs from body, layer and token without
ever reading a key. `worker/index.ts` is the only runtime reader of `objectKey`. That also removes
the usual ordering hazard: with no token change there is no window in which the site advertises an
address the Worker cannot answer.

**Copy, deploy, verify, then delete, and verify on a cache-cold address at each step.** A tile served
from the edge proves nothing about which object backs it, so the check needs `cf-cache-status: MISS`
on an address never fetched before. The deletion is itself the strongest proof: once the old keys are
gone, a served tile can only have come from the new ones.

## Writing metadata into an archive

**`pmtiles convert` filters what it carries.** `pack_pmtiles.py` writes six MBTiles metadata rows
and a production archive shows five: `bounds` is hoisted into the binary header and dropped from the
JSON. Arbitrary keys DO survive, `attribution` verbatim among them, but assume nothing without
probing the key you need on a two-tile fixture first.

**The GDAL PMTiles driver cannot write `attribution` at all.** Its creation options are `NAME`,
`DESCRIPTION`, `TYPE`, `MINZOOM`, `MAXZOOM`, `CONF`, `SIMPLIFICATION`, `SIMPLIFICATION_MAX_ZOOM`,
`EXTENT`, `BUFFER`, `MAX_SIZE`, `MAX_FEATURES`, and no more. `DESCRIPTION` is not a substitute:
`attribution` is the key a renderer displays. The vector cut therefore rewrites the blob afterwards
with `tools/pmtiles edit --metadata`, which replaces the metadata ENTIRELY, so read it back with
`pmtiles show --metadata` and merge rather than composing a fresh object. Measured: one key added,
none lost, tile bytes identical, file 106 bytes smaller because the JSON re-serialises tighter.

**`tools/` is gitignored, so `tools/pmtiles` is a download and not part of a checkout.** Both archive
chains need it now. A stage that cannot find it must exit rather than skip, or it ships an
uncredited archive with the run reporting success.

**A superseded archive can be rewritten freely; a published one cannot.** `worker/index.ts` imports
`PUBLISHED` alone, `ARCHIVED` has no runtime reader, and `gen_tile_tokens.ts` computes tokens only
for published archives. So editing a superseded object's metadata moves no tile, no URL and no
token. Doing the same to a published one changes its content SHA, hence its token, hence every tile
URL, and that is a re-cut's worth of deploy rather than a metadata edit.

## What is public, which is not what the bucket setting says

**The bucket is private and the tiles are not.** `terrella-tiles` has no custom domain and its
`r2.dev` URL is disabled, so no whole archive is reachable. But `ALLOWED_ORIGIN` only decides whether
the Worker emits `Access-Control-Allow-Origin`: it is not an access gate, and a request with no
`Origin` header is answered in full. Verified against production on every published pyramid.

So CORS stops a browser on another site from reading a tile into JavaScript, and stops nothing else.
Any non-browser client already has every tile. Treat "the tiles are private" as false whenever it
comes up.
