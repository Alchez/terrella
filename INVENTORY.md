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
~43 GB of superseded generations sat unnoticed. **Re-measured 2026-07-17** after the fill-sun pass
(`run_pass.sh --tiles`, exit 0, 67:44); the whole derived chain is FRESH and `is_stale` reports False
for every raster below. *This table was ~a day stale before that: it still called the live pyramid
"PRE-Caspian, PRE-GLOBathy" and `planet_rgb.tif` "not yet tiled", both untrue since the 07-17 morning
cut. A storage map that lags is how the 43 GB hid — re-measure it when the chain moves, not later.*

| File | Size | What it is | Reclaim? |
|---|---|---|---|
| `height_3857.tif` + `.done` | 31 GB | planet heightfield on the WMQ 3857 grid (131072 × 93009 Float32) | Keep — **fresh**; it is now the composite's direct colour input (the ramps are applied from elevation) |
| `planet_rgb_v1.tif` + `.done` | **17 GB** | the 2026-07-14 sea-rework composite. **Superseded TWICE** (Caspian+GLOBathy on 07-16, fill sun on 07-17) and last written 07-14 20:32. It is **no longer the source of the live tiles and no longer the rollback** — `tiles_old` is. | **Reclaimable — the largest single win in this dir, and the row most likely to be wrong again.** Rolling back to it means the pre-Caspian, pre-GLOBathy, pre-fill look, which was deliberately superseded. Rohan's call: `data/` is gitignored, so deletion is permanent |
| `tiles_old/` | 14 GB | **rolled forward 2026-07-18 13:17:** now the **256 gamma8** pyramid (the pre-#5 look), 62,177 tiles — the `--tiles` re-cut renamed the previous live `tiles` over it. **This is the rollback for the 128 landing** — `mv tiles tiles_bad && mv tiles_old tiles` restores the 256 look | Keep until the 128 look is judged on `/globe` |
| `tiles/` | 14 GB | **live** z0–8 512px pyramid, 62,177 tiles — served via `TILES_STORE`. Cut 2026-07-18 13:17 from the **128/N4 threaded composite** (opt #5) | Keep (live) until re-cut |
| `planet_rgb.tif` + `.done` | 11 GB | **the 128/N4 THREADED composite (2026-07-18 13:02, opt #5)** — the source of the live `tiles/`. Same look knobs (`fill_strength=0.15`, `hi=1.12`, `snow_curve=gamma8`) but `composite_window_rows=128`: sub-perceptually different from the 256 gamma8 (worst 20 DN on mountain snow, invisible at true scale). The 256 version is preserved as `planet_rgb_gamma8_baseline.tif` | Keep — `--tiles` reads it |
| `planet_rgb_gamma8_baseline.tif` | 11 GB | the **256 gamma8** composite (2026-07-18 07:43) — the byte-identical rollback + A/B reference for the 128 landing. `data/` is gitignored, so this file IS the 256 archive | Keep while the 128 look is live |
| `hs_3857.tif` + `.done` | 7.4 GB | per-row-z hillshade (EXAG=15) **+ the 0.15 fill sun, baked** — despite the name this is *combined light*, not a bare hillshade (2026-07-17). Still on the `flat = 255*sin(alt)` contract, which is why `composite` needed no change; max DN 226, not 255 | Keep — **fresh** |
| `lakedepth_3857.tif` + `.done` | 310 MB | GLOBathy lake depth on the 3857 grid (built 2026-07-15, `1:01:38`) — deflates small because it is ~98% zero | Keep — its `.done` is what stops a pass paying that hour again; only dep is `lakedepth.vrt` |
| `snow_persistence_3857.tif` + `.done` | 7.0 GiB | **New 2026-07-18** (opt #4). NSIDC-0791 persistence warped ONCE to the 3857 grid, storing the **raw PACKED Float32** (0–10000 + 65535 fill), unpacked per-window in float64. Warped in **256-row latitude bands** (== the composite window height) because a single whole-grid warp of this ~1.1 km source **decimates** it, smoothing snow off mountains; banding makes each band == the per-window warp → byte-identical. Composite reads window slices. | Keep — **fresh**; dep is `snow/*.nc` (`SP_NC`). Regenerable |
| `glacier_3857.tif` + `.done` | 23 MB | **New 2026-07-18** (opt #4). RGI 7.0 glacier mask (Byte 0/1) rasterized ONCE to the 3857 grid; composite `np.maximum`'s it into the snow alpha. Rasterize is an exact vector burn, so whole-grid == per-window (no banding needed). | Keep — **fresh**; dep is `rgi7_g_3857.gpkg` (`RGI_GPKG`). Regenerable |
| `water_3857.tif` / `ocean_3857.tif` + `.done` | 69 MB | 3857 masks | Keep — **fresh**; `water_3857` now correctly reads **class 1** at the Caspian |
| `hs_params.json`, `composite_params.json` | ~2 KB | materialised palette/knob params — **the freshness guard's dependency records**. `composite_params` gained LAND_STOPS/SEA_STOPS/LUT_STEP_M on 2026-07-16 when `ramp_{land,sea}.txt` were deleted with color-relief | Keep (regenerated; **mtime is load-bearing**) |
| `index.html` | 2.6 KB | **tile SMOKE TEST, not the product globe** — proves the raw pyramid renders using only `python -m http.server`, so broken tiles and a broken frontend can be told apart. No starfield/borders/atmosphere; the product (`globe.astro`, `/globe`) has all three. Labelled in-page + in `<title>` after it was mistaken for the product on 2026-07-17 | Keep — it is a *different tool*, not a superseded one, and being gitignored means deleting is permanent (git is not its archive) |

**Gone 2026-07-16** (deleted with the `gdaldem color-relief` stage — `composite()` applies the ramps
from elevation via a 17.6 KB LUT): `land_3857.tif`, `sea_3857.tif`, `ramp_land.txt`, `ramp_sea.txt`.

**Profiling output** (`data/work/`, gitignored; the *code* is tracked at `pipeline/profile/`):

| Dir | Size | What it is | Reclaim? |
|---|---|---|---|
| `_profile_tiles/` | 6.0 MB | the latest `run_pass.sh --tiles` run — `pass.log` (stage timings) + `samples.jsonl` (0.5 s RSS/CPU/disk per process). **`run_pass.sh` truncates `pass.log` on every run**, so this is only ever the most recent pass | Keep — it is the source of PROCESS.md's numbers |
| `_profile_tiles_prefill_baseline/` | 2.8 MB | a hand copy of the 07-17 *morning* (pre-fill) profile, taken because the harness would have overwritten it and it was the only baseline for the fill's cost | **Reclaimable** — its numbers are now in PROCESS.md and HISTORY. Keep only if a fill-vs-no-fill CPU comparison is still wanted |

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
