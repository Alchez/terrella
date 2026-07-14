# Storage inventory

Point-in-time snapshot of on-disk data stores (**2026-07-14**). Everything lives under `data/`
(gitignored) — no assets or DEM data are in git. Free space at snapshot: **548 GB** of a 1.8 TB
ext4 root. Sizes approximate; `data/work/planet_tiles/` grows while the tile rebuild runs.

## Raw sources — `data/raw/` (~677 GB)

| Store | Size | What it is | Used by | Reclaim? |
|---|---|---|---|---|
| `glo30/` | 551 GB | Copernicus GLO-30 land DEM tiles (downloaded per-country, on demand) | fusion (heroes + planet) | Keep — any re-fuse needs it; largest store |
| `worldcover/` | 114 GB | ESA WorldCover 2021 (class-70 permanent snow/ice) | **hero snow only** (`render/snow_mask.py`) — NOT the tile pipeline | Reclaimable — see note |
| `gebco/` | 7.3 GB | GEBCO 2026 bathymetry / ice-surface | fusion (heroes + planet) | Keep |
| `rgi/` | 2.6 GB | RGI 7.0 glaciers (merged `rgi7_g_3857.gpkg` + source shp) | tile snow (`render/snow.py`) | Keep |
| `snow/` | 1.6 GB | NSIDC-0791 snow-persistence climatology | tile snow (`render/snow.py`) | Keep |
| `cop30_void/` | 1.2 GB | Cop30 void-fill DEM | fusion void-fill | Keep |
| `glo90/` | 74 MB | GLO-90 prototype tiles | experiments only | Reclaimable |
| `naturalearth/` | 38 MB | NE vectors (borders, framing polygons, coastline oracle) | framing, borders | Keep (tiny) |

## Work / intermediates — `data/work/` (~256 GB)

| Store | Size | What it is | Reclaim? |
|---|---|---|---|
| `planet_tiles/` | 61 GB | Tile-pyramid build — 3857 height/color/hillshade + `planet_rgb.tif` + `tiles/` | Active (current rebuild) |
| `planet/` | 12 GB | Fused planet heightfield, 10° cells | Keep — input to the tiler |
| per-country dirs (`russia/` 21 GB, `canada/` 13 GB, `china/` 11 GB, … ~180 dirs) | ~180 GB | **Hero render intermediates** (DEM mosaics, warps, masks per country) | Reclaimable — heroes are rendered |

## Reclaim notes (nothing deleted — reference only)

- **Biggest safe reclaim ≈ the per-country `work/` intermediates (~180 GB).** Pure regenerable
  intermediates from finished hero renders. `python -m pipeline.batch --clean` reclaims them
  per-country as it runs; any country whose hero PNG exists can be `rm`'d and rebuilt on demand.
- **WorldCover (114 GB)** is the hero snow-mask source (`snow_mask.py`, class 70) and is **not**
  read by the tile pipeline (which uses NSIDC-0791 + RGI). It is reclaimable, but a future hero
  re-render would re-download the per-frame tiles it needs (automatic, from the ESA S3 bucket).
  It becomes *fully* retired only if the heroes also migrate to the tile snow source.
- **`glo30/` (551 GB)** is the largest store and the one to leave alone while Phase 2 is active —
  any new country, corrected region, or z9/z10 re-fuse reads from it.
