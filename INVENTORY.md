# Storage inventory

Point-in-time snapshot of on-disk data stores (**2026-07-16**, after the GLOBathy/Caspian pass).
Everything lives under `data/` (gitignored) — no assets or DEM data are in git. Free space at
snapshot: **487 GB** of a 1.8 TB ext4 root. Sizes approximate.

## Raw sources — `data/raw/` (~677 GB)

| Store | Size | What it is | Used by | Reclaim? |
|---|---|---|---|---|
| `glo30/` | 551 GB | Copernicus GLO-30 land DEM tiles (downloaded per-country, on demand) | fusion (heroes + planet) | Keep — any re-fuse needs it; largest store |
| `worldcover/` | 114 GB | ESA WorldCover 2021 (class-70 permanent snow/ice) | **hero snow only** (`render/snow_mask.py`) — NOT the tile pipeline | Reclaimable — see note |
| `globathy/` | 16 GB | GLOBathy zips as downloaded (`Bathymetry_Rasters.zip` 16.7 GB + `GLOBathy_basic_parameters.zip` 116 MB), figshare v1 pinned by size+md5, **CC0** | `acquire/extract_globathy.py` → `work/globathy/` | **Reclaimable once extracted** — re-downloadable, and the download script verifies against the pinned md5 |
| `gebco/` | 7.3 GB | GEBCO 2026 bathymetry / ice-surface | fusion (heroes + planet); Caspian bathymetry since 2026-07-15 | Keep |
| `rgi/` | 2.6 GB | RGI 7.0 glaciers (merged `rgi7_g_3857.gpkg` + source shp) | tile snow (`render/snow.py`) | Keep |
| `snow/` | 1.6 GB | NSIDC-0791 snow-persistence climatology | tile snow (`render/snow.py`) | Keep |
| `cop30_void/` | 1.2 GB | Cop30 void-fill DEM | fusion void-fill | Keep |
| `naturalearth/` | 38 MB | NE vectors (borders, framing polygons, coastline oracle) | framing, borders | Keep (tiny) |

## Work / intermediates — `data/work/` (~267 GB)

| Store | Size | What it is | Reclaim? |
|---|---|---|---|
| `planet_tiles/` | 73 GB | Tile-pyramid build — see breakdown below | Mixed |
| `globathy/` | 16 GB | GLOBathy extracted: `rasters/` = **83,357** per-lake 1″ TIFFs ≥10 KB (15 GB) + `lakedepth.vrt` (83,356 sources; the Caspian is excluded — it is watermask class 1 and takes GEBCO) | Keep — the VRT is the lake-depth warp's only dependency. `rasters/` is 83 k inodes; regenerable from the raw zip |
| `planet/` | 12 GB | Fused planet heightfield + masks, 540 cells of 10° (36 lon × 15 lat; Antarctica excluded by design, not a gap) | Keep — input to the tiler |
| `tiles/caspian_check/` | 852 MB | Item-6 Caspian regression render (2026-07-15) + its before/after PNG | Reclaimable — verdict + numbers recorded in HISTORY.md |
| `_profile/` | 81 MB | 2026-07-16 instrumented-pass **output**: `pass.perf.data` (349k samples), `samples.jsonl`, `pass.log`, `lutpass.log` | **Fully reclaimable** — every conclusion is in HISTORY.md. The *harness* that produced it lives in **`pipeline/profile/`** (tracked); it sat here until 2026-07-16, when `data/` being gitignored meant those scripts were never in git at all. **Code in `pipeline/`, output in `data/`** |
| per-country dirs (`russia/` 21 GB, `canada/` 13 GB, `china/` 11 GB, … 208 dirs) | ~182 GB | **Hero render intermediates** (DEM mosaics, warps, masks per country) | Reclaimable — heroes are rendered |

### `planet_tiles/` breakdown

Itemised because a previous snapshot summarised this dir in one line, which is precisely how
~43 GB of superseded generations sat unnoticed. **As of 2026-07-16 the whole derived chain is
FRESH** — the batched Caspian + GLOBathy pass rebuilt it and `is_stale` reports False for every
raster below.

| File | Size | What it is | Reclaim? |
|---|---|---|---|
| `height_3857.tif` + `.done` | 33 GB | planet heightfield on the WMQ 3857 grid (131072 × 93009 Float32) | Keep — **fresh**; it is now the composite's direct colour input (the ramps are applied from elevation) |
| `planet_rgb_v1.tif` + `.done` | 18 GB | the **source of the LIVE `tiles/`** (sea rework, locked 2026-07-14) | Keep until the new pyramid is cut & judged — **it is the rollback** |
| `tiles/` | 16 GB | **live** z0–8 512px pyramid, 62,177 tiles — served via `TILES_STORE`. **PRE-Caspian, PRE-GLOBathy** | Keep (live) until re-cut |
| `planet_rgb.tif` + `.done` | 12 GB | **the new composite (2026-07-16)** — GLOBathy lake depth + Caspian bathymetry + `WATER_RGB`. Verified against oracles; **not yet tiled** | Keep — `--tiles` reads it |
| `hs_3857.tif` + `.done` | 8.4 GB | per-row-z hillshade (EXAG=15) | Keep — **fresh** |
| `lakedepth_3857.tif` + `.done` | 310 MB | GLOBathy lake depth on the 3857 grid (built 2026-07-15, `1:01:38`) — deflates small because it is ~98% zero | Keep — its `.done` is what stops a pass paying that hour again; only dep is `lakedepth.vrt` |
| `water_3857.tif` / `ocean_3857.tif` + `.done` | 69 MB | 3857 masks | Keep — **fresh**; `water_3857` now correctly reads **class 1** at the Caspian |
| `hs_params.json`, `composite_params.json` | ~2 KB | materialised palette/knob params — **the freshness guard's dependency records**. `composite_params` gained LAND_STOPS/SEA_STOPS/LUT_STEP_M on 2026-07-16 when `ramp_{land,sea}.txt` were deleted with color-relief | Keep (regenerated; **mtime is load-bearing**) |
| `index.html` | 2.6 KB | **tile SMOKE TEST, not the product globe** — proves the raw pyramid renders using only `python -m http.server`, so broken tiles and a broken frontend can be told apart. No starfield/borders/atmosphere; the product (`globe.astro`, `/globe`) has all three. Labelled in-page + in `<title>` after it was mistaken for the product on 2026-07-17 | Keep — it is a *different tool*, not a superseded one, and being gitignored means deleting is permanent (git is not its archive) |

**Gone 2026-07-16** (deleted with the `gdaldem color-relief` stage — `composite()` applies the ramps
from elevation via a 17.6 KB LUT): `land_3857.tif`, `sea_3857.tif`, `ramp_land.txt`, `ramp_sea.txt`.

## The freshness guard (why no manual `rm` list is ever needed)

`shade_planet.py` used to guard each stage on `if not out.exists()`, which cannot tell *built* from
*still correct* — a re-run would have skipped everything and re-cut tiles from pre-Caspian rasters.
Since 2026-07-15 it is freshness-based (`is_stale`): a stage re-runs if its output is missing, was
never stamped `.done`, or is older than any input — including the chunk **directory** (a VRT's mtime
does not move when its chunks are re-fused) and the materialised param files. It fired correctly on
the real re-fuse (2026-07-16) and rebuilt exactly the stale chain. **It is blind to CODE changes by
design** (params, not source, are the dependency — so a `git checkout` cannot force a 33 GB rebuild);
any *behavioural* change to a shading kernel must therefore be verified against an oracle by hand,
as the hillshade float32 and color-relief LUT changes both were. → [HISTORY.md](HISTORY.md)

## Reclaim notes

- **Biggest safe reclaim ≈ the per-country `work/` intermediates (~182 GB).** Pure regenerable
  intermediates from finished hero renders. `python -m pipeline.batch --clean` reclaims them
  per-country as it runs; any country whose hero PNG exists can be `rm`'d and rebuilt on demand.
- **WorldCover (114 GB)** is the hero snow-mask source (`snow_mask.py`, class 70) and is **not**
  read by the tile pipeline (which uses NSIDC-0791 + RGI). It is reclaimable, but a future hero
  re-render would re-download the per-frame tiles it needs (automatic, from the ESA S3 bucket).
  It becomes *fully* retired only if the heroes also migrate to the tile snow source.
- **`glo30/` (551 GB)** is the largest store and the one to leave alone while Phase 2 is active —
  any new country, corrected region, or z9/z10 re-fuse reads from it.
- **Re-shading is all-or-nothing** (the Caspian was ~0.15% of the raster and still cost a full-planet
  rebuild; windowed patching was considered and rejected). **That pass has now been paid — 2026-07-16,
  98 min, batched as designed** (Caspian + GLOBathy + `WATER_RGB` in one), so the argument is settled
  and the chain is fresh. The cost is worth remembering for the NEXT such change: budget a full pass,
  and batch everything pending into it rather than paying it repeatedly. → [PLAN.md](PLAN.md).

## Reclaimed 2026-07-15 (~41 GB: 487 → 529 GB free)

| Removed | Size | Why it was dead |
|---|---|---|
| `planet_tiles/blocks/` + `planet_rgb.vrt` | 8.2 GB | output of the retired 194-strip `tile_planet.py`, superseded by `shade_planet.py`; unreferenced |
| `planet_tiles/tiles_old/` | 13 GB | pre-sea-rework pyramid; rollback for a rework locked & live. The next `--tiles` run re-creates a fresh rollback automatically |
| `planet_tiles/planet_rgb.tif` + `.done` | 14 GB | pre-sea-rework composite (predates `ramp_sea.txt`); superseded by `_v1` **and** an active skip-if-present trap |
| `work/redsea_proto/` | 4.8 GB | sea-rework A/B variants (baseline/v1/v2/tones); winner locked |
| `work/caspian_{water,bathy,north}/` | 2.4 GB | Caspian scratch — conclusions recorded in HISTORY.md; `.log` files kept |
| `planet_tiles/_bench_{sp,rgi}.tif` | 482 MB | `experiments/composite_bench.py` temps; regenerable |
| `raw/glo90/` | 74 MB | GLO-90 prototype tiles; experiments only |
| `planet_tiles/planet_rgb_v2.done` | 0 | orphaned marker (its `.tif` was reclaimed 2026-07-14) |
