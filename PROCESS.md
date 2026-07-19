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
| 4 | `render/hillshade.py` — per-row z-factor **+ fill sun** | **11:48** (1.17 cores, 44.9 MB/s r) | ~0 s | `hs_3857.tif` 7.9 GB | `is_stale` |
| 5 | `global_occlusion` — sky-view factor | **2:44** (0.78 cores, **193 MB/s r** — I/O-bound) | ~0 s | in-memory only | **lazy** (2026-07-17) |
| 6 | `composite_planet` — ramps × hillshade × SVF + snow + lake depth | **10:45 threaded 128/N4** (peak **10.55 GiB**); was **49:40** serial 256 | ~0 s | `planet_rgb.tif` 11 GB | `is_stale` |
| 7 | `build_tiles` — `gdal raster tile` z0–8 | **3:32** (12.0 of 16 cores, 502 MB/s read) | **3:32 — no guard** | `tiles/` 14 GB, 62,177 tiles | none |

Stages 4–7 re-measured **2026-07-17** on the fill-sun pass (`run_pass.sh --tiles`, exit 0, **67:44 total**),
which is also the first run to record **cores and disk rate per stage** — PROCESS.md previously had wall
times only, which is why "is the hillshade compute- or I/O-bound?" was unanswerable this morning. Now:

- **hillshade 11:48** — was 8:28; the fill adds a second `hillshade_array` per window (same block, no
  extra I/O) for **+3:20**. Projected +4:30 from a synthetic benchmark, so the projection was ~35% high
  on the delta: pure compute is 1.41 s/window but only ~half the stage is arithmetic (1.17 cores).
- **composite 49:40** — was 53.8 min. The **−4.1 min is optimisation #3** (`num_threads="ALL_CPUS"` on the
  writers, landed 2026-07-16) cashing in for the first time; PLAN predicted "~6 min, upper bound".
- **0.78 of 16 cores** was the composite's headline number when serial: neither I/O-bound (7.4 MB/s) nor
  parallel, it was **single-threaded and DRAM-bandwidth-bound** — full-width windows make every 3-channel
  array 402 MB against ~32 MB of L3, so all ~30 numpy ops are DRAM round-trips. That is *why* threading
  caps at ~3× and why bigger windows do not help.
- **composite 10:45, threaded 128/N4 (optimisation #5 LANDED 2026-07-18).** ~3.5× the serial rate, peak
  **10.55 GiB** (up from the bench's 8.5 on 24 windows — full-pass fragmentation, still under the 12 G cap;
  N=6 would OOM a full pass). The 128-row window is NOT for speed (128 ties 256 serial per row) but to fit
  4 workers under the cap — 256/N3 OOMs. It shifts the look sub-perceptibly (worst 20 DN on mountain snow,
  invisible at true scale). → HISTORY § 2026-07-18 — the composite is threaded.

**End-to-end, measured:**

| Scenario | Wall | Notes |
|---|---|---|
| **A hillshade-stage re-tune** (`fill_strength` → live tiles) | **67:44** | measured 2026-07-17 (fill sun). Warps all skip; hillshade + SVF + composite + tile cut all run. |
| **A composite-stage re-tune** (`snow_curve` → live tiles) | **~17 min** (was 55:48) | 2026-07-17 gamma8 was SVF 167 s + composite **49:33** + tiles 3:28 = 55:48. With #5 landed (128/N4) the composite is **10:45**, so a composite-knob iteration is now **≈ 167 s SVF + 10:45 + ~3:30 tiles ≈ 17 min** — the ~3× that motivated Phase B, and it matters most for Antarctica's many ice-look iterations. |
| Everything cold, shade only | **~72 min** | 2026-07-16, after color-relief was deleted (was ~98 min) |
| `--tiles`, everything fresh | **~3:45** | was 6:17 before the SVF guard — 41% of it was discarded work |
| No `--tiles`, everything fresh | **0.29 s** | every stage skips; this is the guard working |
| Lake-depth warp (stage 3) | **1:01:38** | one-time; its `.done` is what stops a pass paying that hour again |
| **A pole-look preview** (cap / sea-ice iteration, browser-free) | **~1–3 min** | `disc_preview.py`: composite only the polar band uncapped, reusing the cached SVF (`occ.npy`), then reproject to EPSG:3995 → a disc PNG. No full recompose, no tile cut, no browser. This is the right loop for the pole — the full composite + re-cut (2026-07-18 pale-C: 10:48 + 3:28) was overkill to preview one flat colour. → HISTORY § the polar cap: flat fails |

**What a knob actually restages** (measured, not inferred — `fill_strength` + `hi`, 2026-07-17): all four
warps skip, including the 1:01:38 lake warp. A **hillshade-stage** knob (`fill_strength`, tracked in
`hs_params.json`) restages hillshade → composite → tiles. A **composite-stage** knob (`hi`, `ambient`,
ramp colours, tracked in `composite_params.json`) restages composite → tiles, ~53 min. The composite is
**~71% of any art iteration** — see PLAN § Pipeline optimisation #5 (~3× is available and unclaimed).

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
