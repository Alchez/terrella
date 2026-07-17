# Terrella — processes and how long they take

Every number here is **measured on this box** (RTX 4070 Super, 16 cores, 29 GB RAM, ext4 NVMe), not
estimated. Where a figure is an estimate it says so. Dates say when it was last measured — re-measure
rather than trust an old row, and see `HISTORY.md` for why each number is what it is.

## How "re-run" works

Every pipeline stage is guarded by `is_stale(output, *inputs)`: it rebuilds only if its output is
missing, never completed (`.done` marker), or older than any input. So a re-run costs **~0 s per stage**
until something upstream actually changes. Tunables that never reach a file of their own
(`KNOBS`, palette colours) are materialised into `composite_params.json` / `hs_params.json`, whose mtime
moves **only when a value really changes** — that is what makes the guard trustworthy against a
`git checkout`.

Two stages are the exceptions, and they are the whole story of a re-run:

- **`build_tiles` has no guard** — it always re-cuts. `--resume` skips tiles that already exist, but the
  staging dir is renamed away on success, so the next `--tiles` starts empty and pays full price.
- **`global_occlusion` (sky-view) has no file to stamp**, so it is guarded by *laziness* instead: it is
  passed to the composite unevaluated and only runs if the composite is stale (added 2026-07-17).

## The planet tile pipeline

`python -m pipeline.tile.shade_planet [--tiles]` — or instrumented:
`bash pipeline/profile/run_pass.sh [--tiles]`

| # | Stage | First run | Re-run (fresh) | Output | Guard |
|---|---|---|---|---|---|
| 0 | `fuse/fuse_planet.py` — 540 cells @ 10″, 12 workers *(separate command)* | **~15 min** (43 s/dense cell) | skip | `work/planet/chunks/` (540 cells) + 3 VRTs, 12 GB | per-cell exists() |
| 1 | warp height → 3857 | **5 min** (486% CPU, 17 threads) | ~0 s | `height_3857.tif` 33 GB | `is_stale` |
| 2 | warp ocean + water masks → 3857 | **< 1 min** | ~0 s | 69 MB | `is_stale` |
| 3 | warp GLOBathy lake depth → 3857 | **1:01:38** (nodata-masker-bound, 102% CPU) | ~0 s | `lakedepth_3857.tif` 310 MB | `is_stale` |
| 4 | `render/hillshade.py` — per-row z-factor | **8:28** (float32 @ 256 rows) | ~0 s | `hs_3857.tif` 8.4 GB | `is_stale` |
| 5 | `global_occlusion` — sky-view factor | **2:33** (single-threaded, reads all 31 GB) | ~0 s | in-memory only | **lazy** (2026-07-17) |
| 6 | `composite_planet` — ramps × hillshade × SVF + snow + lake depth | **53.8 min** (1 core; peak 6.24 GiB) | ~0 s | `planet_rgb.tif` 12 GB | `is_stale` |
| 7 | `build_tiles` — `gdal raster tile` z0–8 | **3:44** (12.0 of 16 cores, 502 MB/s read) | **3:44 — no guard** | `tiles/` 16 GB, 62,177 tiles | none |

**End-to-end, measured:**

| Scenario | Wall | Notes |
|---|---|---|
| Everything cold, shade only | **~72 min** | 2026-07-16, after color-relief was deleted (was ~98 min) |
| `--tiles`, everything fresh | **~3:45** | was 6:17 before the SVF guard — 41% of it was discarded work |
| No `--tiles`, everything fresh | **0.29 s** | every stage skips; this is the guard working |
| Lake-depth warp (stage 3) | **1:01:38** | one-time; its `.done` is what stops a pass paying that hour again |

Peak RSS is **6.24 GiB** (the composite) — run under `MemoryMax=12G` (~1.9× measured). Tiling peaks at
only 2.02 GiB across 18 processes. **`memory.current` is not RSS**: during tiling the cgroup sits at
~16 GiB, but that is reclaimable page cache (`anon` 0.58 GiB) — watch **anon**, not the total.

## Hero renders (separate pipeline — Blender, not the tiler)

| Stage | First run | Re-run | Output |
|---|---|---|---|
| `render/render_prep.py --frame` → `frame.json` | ~seconds | `is_stale` | per-country frame + warps |
| `render/scene_build.py --render` — headless Cycles, OptiX | **3:36 @ 8K** | n/a | one hero PNG |
| Full batch — **204 heroes** | **overnight** (estimate; GPU-bound, occupies the desktop) | per-country resume | `blender/renders/` |

8K frames denoise on **CPU**, not GPU: GPU render + GPU OIDN contend for the 12 GB VRAM → Xid 31 MMU fault.

## Acquire (one-time, network-bound)

Run once; all are resumable and verify against a pinned size/md5, so a re-run is a no-op.

| Source | Size | Notes |
|---|---|---|
| Copernicus GLO-30 | **551 GB** | per-country, on demand — never bootstrapped globally (Russia alone ≈ 4,900 tiles) |
| ESA WorldCover | 114 GB | **hero snow only**, not the tile pipeline |
| GLOBathy | 16.7 GB zip | → 83,357 per-lake rasters; **reclaimable once extracted** |
| GEBCO 2026 | 7.3 GB | bathymetry + ice surface |
| RGI 7.0 glaciers | 2.6 GB | tile snow |
| NSIDC-0791 snow persistence | 1.6 GB | tile snow |
| Cop30 void-fill | 1.2 GB | fusion void-fill |
| Natural Earth | 38 MB | borders, framing, coastline oracle |

## Frontend and serving

| Process | Command | Time | Notes |
|---|---|---|---|
| Astro dev server — **the product globe** | `pnpm dev` in `maps-frontend/web` | ~2 s | `/globe` on Astro's default port 4321 (not pinned in config); serves `/tiles` from `TILES_STORE` (dev-only middleware, `no-cache`) |
| Static build | `pnpm build` | ~seconds | emits HTML/CSS/JS only — assets stay external |
| Tile smoke test — **not the product** | `python3 -m http.server` in `work/planet_tiles` | instant | proves the pyramid renders with zero deps; no starfield/borders/atmosphere by design |
| PMTiles packaging | `pmtiles` CLI | **not yet run** | Phase 4; packs `tiles/` into one file for range-request serving |

## If you only remember one thing

The pipeline is **fast to re-run and slow to build**: cold is ~72 min plus a one-time hour for the lake
warp; warm is seconds. The only stage that always costs is the tile cut (**3:44**) — and that is the
step that makes work visible on the globe.
