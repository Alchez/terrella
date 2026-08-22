# Storage inventory

- The **current** map of on-disk data stores: what each is, who reads it, whether it is
  reclaimable. This file is maintained, not a snapshot: **re-measure when the chain moves; if a
  row and the disk disagree, the row is the bug.** Past states live in git history; reclaim
  passes and their lessons live in HISTORY (§ the reclaim log moves out of INVENTORY).
- Two gitignored stores hold everything: `data/` (sources + intermediates) and
  `blender/renders/` (the hero products); no assets or DEM data are in git. Free space:
  **~389 GB** of a 1.8 TB ext4 root. Sizes approximate.

## Raw sources: `data/raw/` (~688 GB)

| Store | Size | What it is | Used by | Reclaim? |
|---|---|---|---|---|
| `glo30/` | 551 GB | Copernicus GLO-30 land DEM tiles (downloaded per-country, on demand) | fusion (heroes + planet) | Keep: any re-fuse, new country, or z9/z10 extension reads it; largest store |
| `worldcover/` | 114 GB | ESA WorldCover 2021 (class-70 permanent snow/ice) | **hero snow only** (`render/snow_mask.py`), NOT the tile pipeline | Reclaimable: see reclaim picture |
| `gebco/` | 7.3 GB | GEBCO 2026 bathymetry / ice-surface | fusion (heroes + planet); Caspian bathymetry | Keep |
| `rgi/` | 2.6 GB | RGI 7.0 glaciers (merged `rgi7_g_3857.gpkg` + source shp) | tile snow (`look/snow.py`) | Keep |
| `snow/` | 1.6 GB | NSIDC-0791 snow-persistence climatology | tile snow (`look/snow.py`) | Keep |
| `seaice/` | 640 MB | OSI SAF OSI-450-a monthly EASE2 files + the derived 1991–2020 ice-frequency climatology (`seaice_frequency_1991-2020_4326.tif`) + native `freq_{nh,sh}_ease2.tif` | tile sea ice (`look/seaice.py`) + both caps | Keep (climatology is tiny); `monthly/` regenerable from anonymous THREDDS |
| `cop30_void/` | 1.2 GB | Cop30 void-fill DEM | fusion void-fill | Keep |
| `addrock/` | 410 MB | SCAR ADD rock outcrop, the LANDSAT auto-extraction (zip + unzipped shp + the reprojected `add_rock_3857.gpkg`) | Antarctic ice subtraction (`look/snow.py`), tiles + block + south cap | Keep the gpkg; the unzipped shp is regenerable from the zip, and the zip from `acquire/download_add_rock.py` |
| `naturalearth/` | 38 MB | NE vectors (borders, framing polygons, coastline oracle) | framing, borders, countries/boundary GeoJSON | Keep (tiny) |
| `mars/` | 12 GB | Two whole-planet downloads, no per-tile machinery. The MOLA/HRSC blended DEM (`Mars_HRSC_MOLA_BlendDEM_Global_200mp_v2.tif`, 11,384,463,908 B, 106694 × 53347 int16) is the heightfield. `Mars_Viking_ClrMosaic_global_925m.tif` (797,888,177 B, 23059 × 11530 RGB, SimpleCylindrical metres) is **an acquired input**: it is the field Mars's polar ice alpha is graded from, and `mars_ice.ALPHA_LEVELS` was measured over these exact bytes; it is also what the land ramp's hue was measured against | the DEM feeds Mars's planet seam (`fuse/relabel_mars.py`); the mosaic is acquired by `acquire/download_viking_mosaic.py` and read so far only by the ice-level scripts, no render stage yet | Keep the DEM: re-downloadable, but a ~23 min single-stream fetch with its edition pinned by size and Last-Modified. The mosaic is **re-fetchable exactly**, its acquirer pinning the publisher's own md5, so a deleted copy returns byte-identical in ~90 s, but it is no longer spare, and deleting it now costs a re-fetch rather than nothing |

## Work / intermediates: `data/work/` (~330 GB)

| Store | Size | What it is | Reclaim? |
|---|---|---|---|
| `planet_tiles/` | **97 GB** | Tile-pyramid build: itemised below | Mixed: see breakdown |
| per-country dirs (`russia/` 21 GB, `canada/` 13 GB, `china/` 11 GB, … 208 dirs) | ~190 GB | **Hero render intermediates** (DEM mosaics, warps, masks per country) | Reclaimable: heroes are rendered; kept while the hero sweep queue reads them |
| `globathy/` | 16 GB | GLOBathy extracted: `rasters/` = **83,357** per-lake 1″ TIFFs (~15 GB, 83 k inodes) + `lakedepth.vrt` (the Caspian is excluded; watermask class 1, takes GEBCO) | Keep: the VRT is the lake-depth warp's only dependency, and the raw zips it came from are gone, so this IS the store now (re-downloadable via `acquire.download_globathy`, pinned md5) |
| `planet/` | 14 GB | Fused planet heightfield + masks, 648 cells of 10° (36 lon × 18 lat, pole to pole) | Keep: input to the tiler |
| `planet_terrain/` | **7.6 GB** | Terrain-RGB (Tier 3 displacement), built by `tile/terrain_rgb.py` from `height_3857.tif`. Shipping pyramid is `bathy_s8_webp/` (**2.63 GB, 87,381 tiles, z0–8**), stamped `tiles.done` + `terrain_params.json` so it will not restage, packed to **`terrain.pmtiles` (2.63 GB)** via **`terrain.mbtiles` (2.69 GB)**. **Both the 60 GB `elev/` chain and the spike A/B builds are gone**: this store is now only the shipping pyramid, its archive, and the bridge | Mixed: `terrain.mbtiles` (2.69 GB) is the bridge format and is dead now that the archive is live in production; it rebuilds from `tiles/` in 12 s, the same standing exception `planet.mbtiles` takes. Keep `bathy_s8_webp/` (the pack source) and `terrain.pmtiles` (the deployment artifact). A rebuild re-derives the chain from `height_3857.tif` and no longer copies the master, so it costs ~13 GB transiently, not 60 |
| `planet_vector/` | **10.2 MB** | Earth's VECTOR tiles (MVT), cut by `compose/countries_pmtiles.py` from `borders/countries.geojson` plus the two layers it derives. One archive, three source-layers (`country_fill`, `country_outline`, `country_hit`), z0–8, stamped `countries_tiles_params.json`: the sidecar keeps its producer's name, the archive takes the layer's. **Three orders of magnitude smaller than the raster pyramids**: it is geometry, not pixels | Keep. Re-cuts from `countries.geojson` in **17 s**, so the archive is cheap to regenerate; the recipe sidecar is what makes a settings change visible, since the filename cannot carry one |
| `cap/` | 1.3 GB | Both caps' render intermediates (`tile/cap_render.py`): AEQD warps + `cap_{north,south}.tif` + **the freshness sidecars `cap_{north,south}_params.json`** + the A/B rung archives (decision records, ~10 MB). Served outputs live at `web/public/caps/` (two WebP rungs per pole + `caps.json`) | Reclaimable: regenerated by a cap render (deleting the sidecars merely forces one), but budget **≥16 G**: the render peaks ~14 GB and OOMs under the standard 12 G cap (PROCESS § Polar cap render) |
| `borders/` | <1 GB | `countries.geojson` + `boundary_lines.geojson` (NE → GeoJSON emitters), served at `/borders/` | Keep (tiny); regenerable from `naturalearth/` |
| `mars/` | 4.2 GB | **The second body's whole work tree**, nested under its own prefix where Earth's stages sit un-prefixed at the root. `planet/` is 12 KB: a CRS-relabelled VRT over the raw blend plus its seam declaration, no copy of the 11 GB. `planet_tiles/` holds the two products of the z7 cut, `tiles/` 1.4 GB (21,845 tiles, z0–7) and **`planet.pmtiles` 1.40 GB** (the deployment artifact, 20,950 unique tile bodies), plus the four recipe sidecars and the burnt ice GeoJSONs. **Its intermediates are deliberately absent**: `height_3857.tif` (11 GB at 65536²), `planet_rgb.tif` 4.1 GB, `hs_3857.tif` 3.2 GB, the six ice rasters and the alpha, and `planet.mbtiles` were all reclaimed once the cut was accepted, because no remaining phase reads them: vectors are a web overlay and heroes render from the raw DEM | Mixed: the archive and `tiles/` are the products and `tiles/` stays until R2 holds a second copy of the archive. Everything reclaimed rebuilds from raw in ~16:10; the `.done` markers left vouching for absent outputs are safe, since every guard returns "rebuild" for a missing file |
| `mars/ice/` | 205 MB | **Live.** `viking_luma_4326.tif`: the Viking mosaic collapsed to one Float32 brightness band on a 4326 grid covering the whole sphere, which is the field BOTH ice tiers grade against, beside the two VRTs that reach it and `viking_luma_params.json`. Whole-planet on purpose though only the poles are read: a polar crop would save ~160 MB and cost a crop latitude whose failure is ice quietly missing at the band edge | Keep: a 45 s rebuild from the raw mosaic, and the sidecar makes a re-run a skip. `mars_ice.ALPHA_LEVELS` is four percentiles OF THIS FILE, so rebuilding it on a different grid means re-measuring them |
| `mars/cap/` | 1.3 GB | **Live.** The cap stage's intermediates for both poles: the AEQD height warps and the full-size colour renders, beside the `*_params.json` sidecars that decide whether a re-run restages them. `MARS.renders_polar_caps` is `True`, so the shade pass refreshes these on every run | Keep: deleting them costs a ~1:15 re-render, and the sidecars are what make it a skip |
| `_profile_tiles/` | 6 MB | The latest `run_pass.sh --tiles` run: `pass.log` (stage timings) + `samples.jsonl`. **Truncated on every run**: only ever the most recent pass | Keep: the source of PROCESS.md's numbers |
| `_profile_mars_tiles/` | 540 KB | The same two files for the FIRST Mars pass, under its own name because that one predates the harness knowing about bodies and was run by hand. Mars runs through `run_pass.sh` now and lands in `_profile_tiles/` beside Earth: the 16 G cap that forced the detour is derived from `renders_polar_caps` and answers 12 G for a capless body | Keep: the source of PROCESS.md's first Mars row, which no later run reproduces |
| `_profile_pass/` | 17 MB | The same two files for the most recent `run_pass.sh` with NO `--tiles`, kept separate from `_profile_tiles/` so a composite-only look iteration does not overwrite the timings of the last full cut. **Truncated on every run** | Keep: the source of PROCESS.md's warm-loop row |
| `_*/` experiment scratch | 0 now | A/B and investigation output, by convention leading-underscore (`_ab_shadow`, `_pinecone_exp`, …) | **Reclaim as soon as the decision lands in HISTORY**: the finding is the product, the pixels are not |

### `planet_tiles/` breakdown

- **Itemised deliberately**: summarising this directory in one line is how ~43 GB of dead
  generations once hid; and a *deferred* measurement of a growing directory is the same failure
  as a stale one. Re-measure when the chain moves.
- Steady state is **one live pyramid + one rollback**: `tiles/` plus the `tiles_old/` that
  `build_tiles` auto-rotates on each cut. `tiles_old/` is currently absent: the WebP pyramid it
  guarded is live and served, so the rollback window closed and its 16 GB was reclaimed.
- `pack_pmtiles.py` emits an intermediate `planet.mbtiles` (3.19 GB) that `pmtiles convert` reads: 
  **transient by design**, and currently absent: it is deleted once the archive verifies and rebuilds
  from `tiles/` in ~10 s.

| File | Size | What it is | Reclaim? |
|---|---|---|---|
| `height_3857.tif` + `.done` | 46 GB | planet heightfield on the WMQ 3857 grid (131072², Float32, full Mercator extent incl. Antarctica) | Keep: the composite's direct colour input (ramps apply from elevation) |
| `seaice_3857.tif` + `.done` | 18 GB | OSI SAF ice-frequency climatology warped ONCE to the 3857 grid, raw packed Float32, in latitude bands (a coarse 25 km source decimates under a single whole-grid warp); composite reads window slices, ocean-gated | Keep: fresh; dep is `seaice_frequency_1991-2020_4326.tif`. Regenerable |
| `tiles/` | **3.1 GB** | **LIVE and APPROVED**: the ratified look (z0–8, 512 px WebP q95, rows to y=255) | Keep (live) |
| `planet.pmtiles` | **3.1 GB** | the serving archive (`pmtiles convert`, capped, `--tmpdir` on ext4): spec v3, clustered, z0–8, ~5% duplicate tiles collapsed; verified via `pmtiles verify` + 5-tile byte-compare | Keep: the deployment artifact; ~34 s + ~1m11s to rebuild from `tiles/` |
| `planet_rgb.tif` + `.done` | 11 GB | the composite at the full 131072² grid: the approved look the tiles are cut from | Keep: `--tiles` reads it |
| `snow_persistence_3857.tif` + `.done` | 10 GB | NSIDC-0791 persistence warped ONCE to the 3857 grid, raw packed Float32, in 256-row latitude bands (whole-grid warp decimates the ~1.1 km source; banding == the per-window warp, byte-identical); composite reads window slices | Keep: fresh; dep is `snow/*.nc`. Regenerable |
| `hs_3857.tif` + `.done` | 10 GB | per-row-z hillshade **+ the fill sun, baked**: *combined light*, not a bare hillshade, still on the `flat = 255·sin(alt)` contract; max DN 226 | Keep: fresh |
| `glacier_3857.tif` + `.done` | 30 MB | RGI 7.0 glacier mask (Byte 0/1) rasterized ONCE to the 3857 grid; exact vector burn, so no banding needed | Keep: fresh; dep is `rgi7_g_3857.gpkg`. Regenerable |
| `lakedepth_3857.tif` + `.done` | 318 MB | GLOBathy lake depth on the 3857 grid (~98% zero, deflates small). Its `.done` is what stops a pass paying that ~1 h warp again; only dep is `lakedepth.vrt` | Keep |
| `water_3857.tif` / `ocean_3857.tif` + `.done` | 81 MB | 3857 masks; `water_3857` reads class 1 at the Caspian | Keep: fresh |
| `hs_params.json`, `composite_params.json` | ~2 KB | materialised palette/knob params: **the freshness guard's dependency records** | Keep (regenerated; **mtime is load-bearing**) |
| `index.html` | 2.6 KB | **tile SMOKE TEST, not the product globe**: proves the raw pyramid renders with only `python -m http.server`, so broken tiles and a broken frontend can be told apart (labelled in-page after being mistaken for the product once) | Keep: a *different tool*, and gitignored means deleting is permanent |
| `tmp/` | ~0 | `pmtiles convert --tmpdir` home (ext4, not tmpfs): self-cleans on normal exit | Keep the dir |

## Hero products: `blender/renders/` (~27 GB)

- The only heavy store outside `data/`, gitignored the same way. Listed here because an
  unlisted store is an unaudited one: a 26 GB dead rollback archive lived here unnoticed
.

| Store | Size | What it is | Reclaim? |
|---|---|---|---|
| `heroes/raw/` | 13 GB | the un-post-processed Cycles frames, one 8K PNG per country | Keep: `sky_view` re-shades finals from these with **no GPU re-render** (the AO retune took 203 countries off them in minutes) |
| `heroes/` | 12 GB | the shaded finals (raw + `sky_view`), one per country | Keep: the source `hero_variants` encodes from |
| `variants/` | **3.5 GB** | **the served store**: 1,243 hero WebP (6 rungs, q85 to 1920 / q95 above, **+ a per-country portrait fill rung on 25 of them**) + 1,243 spotlight overlays + 1,010 border PNGs (5 rungs) | Keep: this is what the browser fetches |
| `borders/` | 158 MB | per-country transparent border PNGs | Keep: the globe click-panel overlay builds from them |
| `archive/` | 595 MB | one-off look experiments (india/nepal/swiss look v1–v3): the visual record behind ART's decisions | Keep (small); **not** a place for rollback trees |
| `*.log`, `batch_failures*.jsonl` | <10 MB | sweep logs + the failure roster batch retries from | Keep (tiny) |

- **Rollback archives are the trap here.** A pre-sweep `cp -al` hardlink tree costs ~0 bytes
  *until* the sweep re-renders, then every hardlink breaks into real bytes and the archive
  silently becomes a full second copy. Prune it the day the sweep ratifies.

## What the browser loads (dev vs prod)

- The wire view, which stores actually reach a visitor, and how dev differs from the deploy
  target. Dev serves stores through three routes in `web/astro.config.ts`: two pointed by
  `web/.env` (`HERO_STORE` → `blender/renders/variants`, `BORDERS_STORE` → `work/borders`) and
  `/tiles`, whose three archives are derived from the work tree itself
  (`work/<body>/planet_tiles/planet.pmtiles` and siblings, rooted at `MAPS_DATA`); the deploy
  target is Cloudflare: a **site Worker** serving
  `web/dist` as static assets (`web/wrangler.jsonc`, *not* Pages), R2 for the hero and border
  stores, and a **separate tile Worker** for tiles. The site addresses all three through
  `web/src/lib/assetBase.ts`, whose defaults are the same-origin dev paths.
- The build (`web/dist/`, **14 MB**, 206 pages) contains **only markup + code**: every heavy asset
  stays in its store and is fetched at runtime, so `pnpm build` never copies gigabytes.

| Asset | Wire size (prod, gz) | Dev | Prod | Store |
|---|---|---|---|---|
| globe JS chunk (MapLibre + the **bundled** `countries.json` manifest: an import, never a fetch) | 280 KB (1.08 MB raw) | vite, unminified, larger | edge gzip/brotli | `web/dist/_astro/` |
| page CSS | **inlined into every document** (`build.inlineStylesheets: 'always'`), so it costs document bytes and no request: 12 KB on the globe, 5 KB on the gallery, uncompressed | dev injects it as `<style>` via Vite instead, which is a different cascade order | same | in the HTML |
| MapLibre's stylesheet | 70 KB raw, a **non-blocking** `<link media="print">` promoted on load: it styles widgets that cannot exist until the globe chunk has run | same link; dev *also* injects it as `<style>`, so it loads twice | same | `web/dist/_astro/maplibre-gl.*.css` |
| small chunks (polarCaps, capability probe) | ~3 KB total | same | same | `web/dist/_astro/` |
| relief tiles | **~36 KB avg/tile** (3.1 GB ÷ 87,381), viewport-driven | `/tiles/earth/relief/{token}/{z}/{x}/{y}.webp`, ranged out of the archive by the dev middleware | same URL shape, ranged by the Worker out of R2: measured: first paint ≈ 40 requests | `planet_tiles/planet.pmtiles` |
| polar caps | **desktop 3.2 + 2.1 MB** (8192 rung) · **mobile 1.0 + 0.8 MB** (4096 rung) + `caps.json` (fetched eagerly at globe load, revalidated not cached; decode off-thread) | identical | identical: WebP ships pre-compressed | `web/public/caps/` |
| `boundary_lines.geojson` | 0.55 MB gz (1.95 MB raw): **opt-in only**: fetched on the first Borders toggle-on, never by default | uncompressed | edge gzip/brotli | `work/borders/` |
| country vector tiles | **4 tiles, 175 KB brotli** in the cold window at the default camera (z1 covers the globe; 22–65 KB each, largest 122 KB raw), viewport-driven like the relief tiles | `/tiles/earth/vector/{token}/{z}/{x}/{y}.mvt`, ranged by the dev middleware, identity bytes | same URL shape, ranged by the Worker out of R2; edge-compressed as text | `planet_vector/vector.pmtiles` |
| `countries.geojson` | 2.5 MB gz (9.4 MB raw at the 0.002° guard-tested tolerance): **no longer delivered**: superseded by the vector tiles above, and now only the cut's input | n/a | n/a | `work/borders/` |
| hero variants (gallery srcset + globe click panel) | mean per rung **60 KB / 130 / 222 / 466 / 2,838 / 8,624** (640/960/1280/1920/3840/native WebP) + the portrait fill rung (**2048/2560/3072, 19.0 MB over 25 countries**) + border overlays 0.14–1.1 MB PNG | staged behind an IntersectionObserver past the first two cards; srcset picks the rung, and for a portrait country the rung's WIDTH is `rung × aspect` | same | `blender/renders/variants/` |

Dev–prod differences that matter:

- **Compression**: dev sends identity bytes (`boundary_lines.geojson` alone is 1.95 MB on the wire
  vs 0.55 MB gz); the CDN compresses text assets. WebP/PNG are pre-compressed either way. **MVT is
  not**: the archive stores it gzipped but both tile servers read through that, so the Worker emits
  plain protobuf and the edge compresses it like text (measured: 122 KB → 65 KB brotli).
- **Validators**: the dev store routes send no ETag/Last-Modified, so every dev reload
  re-downloads everything (recorded on the PLAN Lighthouse item); prod sends validators plus
  aggressive cache headers.
- **Tile source**: one archive per layer either way, and the browser never opens any of them: it
  asks for `{body}/{layer}/{token}/{z}/{x}/{y}.{ext}` and a tile server does the ranging (dev
  middleware locally, a Worker over R2 in production). Six segments, always: a planet, a layer or
  a re-cut adds a word to one of the first three and never changes the shape. The token is the
  archive's own content hash, which is what a re-cut changes: tiles ship `immutable` for a year and
  a zone purge cannot reach a browser cache, so the URL *is* the version. `web/src/lib/tileAddress.ts`
  is the one grammar, imported by both servers and by the client that builds the URLs. The XYZ
  directory the archive was packed from is not deployed at all.
- `countries.geojson` fetches on every globe load (it drives interactivity); `boundary_lines`
  loads only after the user opts into borders (the source is added lazily on first toggle-on,
  and the stored preference re-adds it on later visits): async, first paint never waits.

## The freshness guard (why no manual `rm` list is ever needed)

- Every stage is guarded on **freshness** (`pipeline/freshness.py`), not existence: a stage
  re-runs if its output is missing, was never stamped `.done`, or is older than any input: 
  including the chunk **directory** (a VRT's mtime does not move when its chunks are re-fused)
  and the materialised param files. An exists()-only guard cannot tell *built* from *still
  correct*.
- **It is blind to CODE changes by design** (params, not source, are the dependency: a
  `git checkout` cannot force a 33 GB rebuild); any *behavioural* change to a shading kernel must
  be verified against an oracle by hand.

## Reclaim protocol

- **The standing rule:** remove only what is required for nothing at all; keep anything that is
  still an interim product for an eventual re-run.
- **Before reclaiming any `work/` directory:** `ls` it for `.py`/`.sh` and check `git ls-files`: 
  scripts have twice been found living only in gitignored `data/`, once rescued mid-`rm`
.
- **Re-measure this file after any reclaim or build**: that is its maintenance contract.
- **Re-shading is all-or-nothing** (windowed patching was considered and rejected): budget a full
  pass, and batch every pending look change into it rather than paying it repeatedly.
- **The current reclaim picture:**
  - **`terrain.mbtiles` (2.69 GB) is the one dead thing**: the bridge `pmtiles convert` read, and
    the archive it produced is live and verified against production. Same shape as the
    `planet.mbtiles` exception: deleted once the archive verifies, rebuilt from `tiles/` in 12 s.
  - The two most recent passes were both terrain: the **60 GB `elev/` chain** (
    gets the guard every other stage already had) and the **3.4 GB spike A/B builds**: `bathy`,
    `bathy_s2/_s4/_s8`, `clamp`, `bathy_s8_webp_z6`, dead because the flags that selected them
    (`?dem`/`?quant`/`?demfmt`/`?demdepth`) retired with the archive, so no address reached a build
    directory any more. **This bullet lagged the first of those by a whole pass**: the row was
    updated and the picture was not, which is the failure mode the re-measure contract exists to
    stop. Earlier passes reclaimed ~41, ~46+17 and ~35 GB.
  - per-country hero intermediates (~190 GB) + `raw/worldcover/` (114 GB): **still not dead
    even though the sweep ratified**: they are the input to any future re-render (a new country,
    a look change, the next `render_prep` fix), and worldcover only retires if the heroes also
    migrate to the tile snow source. The standing rule keeps interim products for an eventual
    re-run; these are the largest test of it.
  - `tiles_old/` returns at the next cut and auto-reclaims at the one after; its keep-gate is
    the rollback window, so it is only dead once the new pyramid is live and served.
  - `raw/glo30/` (551 GB): leave alone: any new country, corrected region, or finer re-fuse
    reads it.
