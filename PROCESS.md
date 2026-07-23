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

One stage is still the exception, and it is the interesting one:

- **`global_occlusion` (sky-view) has no file to stamp**, so it is guarded by *laziness* instead: it is
  passed to the composite unevaluated and only runs if the composite is stale (added 2026-07-17).

`build_tiles` was the other exception until 2026-07-20 — it always re-cut, because the staging dir is
renamed away on success so `--resume` started empty and the pyramid had no completion stamp. It now
carries a `tiles.done` sentinel + a `tiles_are_fresh` guard, so a fully-fresh `--tiles` re-run skips the
cut, and it dropped `--resume` (cutting clean each time, so a truncated png can't survive). → HISTORY §
2026-07-20 pipeline hardening.

## The planet tile pipeline

`python -m pipeline.tile.shade_planet [--tiles]` — or instrumented:
`bash pipeline/profile/run_pass.sh [--tiles]`

| # | Stage | First run | Re-run (fresh) | Output | Guard |
|---|---|---|---|---|---|
| 0 | `fuse/fuse_planet.py` — 648 cells @ 10″, 12 workers *(separate command; run `build_mosaics.sh` first after any tile download — a stale mosaic fuses new land as ocean, 2026-07-22)* | **~15 min** (43 s/dense cell; the 108 polar cells ~2 min total — GLO-30 thins toward the pole) | skip | `work/planet/chunks/` (648 cells) + 3 VRTs, 14 GB | per-cell exists() |
| 1 | warp height → 3857 | **6:49** (2026-07-22, 131072-row grid; was 5 min at 93009) | ~0 s | `height_3857.tif` 44 GB | `is_stale` |
| 2 | warp ocean + water masks → 3857 | **~3:30** (1:45 + 1:47; was < 1 min at the old grid) | ~0 s | 69 MB | `warp_needs_rebuild` |
| 3 | warp GLOBathy lake depth → 3857 | **1:01:44** (nodata-masker-bound, 102% CPU) — **UNCHANGED by the Antarctic rows**: no lakes south of −60, the cost lives in the 50–70°N belt | ~0 s | `lakedepth_3857.tif` 310 MB | `warp_needs_rebuild` |
| 3b | warp snow persistence (banded) + rasterize glaciers + warp sea ice (banded) → 3857 (opt #4 / sea ice) | **snow 15:16, glaciers 0:19, sea-ice 14:42** (2026-07-22 grid; sea-ice was ~9:17) | ~0 s | `snow_persistence_3857.tif`, `glacier_3857.tif`, `seaice_3857.tif` | `warp_needs_rebuild` |
| 4 | `render/hillshade.py` — per-row z-factor **+ fill sun** | **16:20** (2026-07-22 grid; was 11:48) | ~0 s | `hs_3857.tif` | `is_stale` |
| 5 | `global_occlusion` — sky-view factor | **3:23** (2026-07-22 grid; was 2:44 — I/O-bound) | ~0 s | in-memory only | **lazy** (2026-07-17) |
| 6 | `composite_planet` — ramps × hillshade × SVF + snow + sea ice + lake depth | **21:37 threaded 128/N4, 1024 windows** (2026-07-22 grid; was 13:28 at 727 windows with sea ice — per-window +14%, the Antarctic windows are all snow+ice work) | ~0 s | `planet_rgb.tif` 12 GB | `is_stale` |
| 7 | `build_tiles` — `gdal raster tile` z0–8 | **4:19** (2026-07-22 grid; was 3:32) | **skip** (guarded 2026-07-20) | `tiles/` 16 GB, z8 rows now reach y=255 | `tiles.done` |

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

**The 2026-07-22 Antarctica pass re-measured every stage at the permanent 131072-row grid** (the fill:
93009 → 131072 rows, 1.41×; `run_pass.sh --tiles`, exit 0, **2:28:01 total** — dominated by the one-time
grid-guarded re-warps, chiefly the 1:01:44 lake warp). Stage numbers above are the ones to quote now; the
old-grid values stay in parens. Guard column: `warp_needs_rebuild` = mtime **or** off-grid (the 2026-07-22
grid-freshness fix) — those stages restaged on this pass *because* the grid grew, and will again only if
it grows again (z10).

**End-to-end, measured:**

| Scenario | Wall | Notes |
|---|---|---|
| **A hillshade-stage re-tune** (`fill_strength` → live tiles) | **~46 min** at the 2026-07-22 grid (was ~29) | hillshade 16:20 + SVF 3:23 + composite 21:37 + tile cut 4:19 ≈ 46 min. Warps all skip. |
| **A composite-stage re-tune** (`snow_curve` → live tiles) | **~17 min** (was 55:48) | 2026-07-17 gamma8 was SVF 2:44 + composite **49:33** + tiles 3:28 = 55:48. With #5 landed (128/N4) the composite is **10:45**, so a composite-knob iteration is now **≈ 2:44 SVF + 10:45 + 3:32 tiles ≈ 17 min** — the ~3× that motivated Phase B, and it matters most for Antarctica's many ice-look iterations. |
| **A sea-ice recomposite** (`ICE_LO` → live tiles) | **~19.6 min** | 2026-07-20. Warps skip (`seaice_3857` fresh); SVF 2:44 + composite **13:28** (727 win, threaded 128/N4) + tile cut 3:27 ≈ 19.6 min. The composite is **+2:43 over the 10:45 no-ice pass** — the per-window sea-ice slice read + ocean-gated blend. The FIRST sea-ice pass also paid the one-time **banded `seaice_3857` warp ~9:17** (coarse 25 km source → banded like snow). **Re-confirmed 2026-07-21 at 19:32** on the `ambient_knee` pass (SVF 2:36 + composite 13:28 + cut 3:28). **2026-07-22 grid: a composite-knob iteration is now ≈ 3:23 SVF + 21:37 composite + 4:19 cut ≈ ~29 min** — the number to quote (Antarctica grew the grid 1.41× and its windows are all snow+ice work). |
| Everything cold, shade only | **~72 min** (pre-#5) → **~35 min** now | the 2026-07-16 ~72 min embedded the serial composite (~49 min); with #5 threaded (composite 10:45) a cold shade is ~35 min. Both exclude the one-time lake warp + fuse. |
| `--tiles`, everything fresh | **~0.4 s** | `build_tiles` guarded 2026-07-20 — was ~3:45 (the 3:32 cut always re-ran, other stages skipped) before the `tiles.done` sentinel |
| No `--tiles`, everything fresh | **0.29 s** | every stage skips; this is the guard working |
| Lake-depth warp (stage 3) | **1:01:38** | one-time; its `.done` is what stops a pass paying that hour again |
| **Cast shadows** (`shadow_strength` > 0) | **+0.625 s/Mpx** measured; est. **+2.1 h** on the planet hillshade at `shadow_reach=300` | 2026-07-21, Iran region A/B (`e040_n30 e050_n30`, 32.4 Mpx): 16.73 s control → 37.01 s with shadows, **+121%**, peak RSS unchanged at 6.3 GB (the wide halo costs time, not memory). The march is `reach_px` full-raster passes, so cost is **linear in `shadow_reach`**: 300 px → ~2.6 h full pass, 150 px → ~1.6 h, 100 px → ~1.2 h. 300 px covers 6,115 m of relief; 150 px covers 3,057 m. `shadow_strength` is hillshade-stage, so any change restages hillshade → composite → tiles. |
| **Polar cap render** (`pipeline/tile/cap_render.py`) | **~1:35** both caps at the production 8192² (56 + 44 s; 4096² was ~43 s), peak ~4 GiB | 2026-07-20; productionized 2026-07-23. AEQD warps of source rasters (height/ocean/water/snow/sea-ice) + the shared `shade.composite` + baked coastline → `web/public/caps/cap_{north,south}.webp` (**3.2 + 2.1 MB**, WebP q85 — was 11.1 + 4.8 MB PNG at 4096²) + `caps.json` (the web contract). The fast browser-free pole-look loop — the old `disc_preview.py` scratch tool is superseded. The south cap sources the fused planet VRTs (GEBCO-direct retired 2026-07-22). **Freshness-guarded since 2026-07-22** (recipe sidecar on `composite_params` + source mtimes + the WebP quality; `shade_planet`'s pass tail invokes it, so the caps restage whenever the look does — a fresh check is ~2 s). → HISTORY § the polar cap: flat fails · § polar caps PRODUCTIONIZED |

**What a knob actually restages** (measured, not inferred — `fill_strength` + `hi`, 2026-07-17): all
warps skip, including the 1:01:38 lake warp. A **hillshade-stage** knob (`fill_strength`, tracked in
`hs_params.json`) restages hillshade → composite → tiles (~29 min). A **composite-stage** knob (`hi`,
`ambient`, ramp colours, tracked in `composite_params.json`) restages composite → tiles, **~17 min**
(SVF 2:44 + composite 10:45 threaded + tile cut 3:32). The composite is the bulk of any art iteration —
optimisation #5 (composite threading, **landed 2026-07-18**) is what took it from ~53 min serial to this.

Peak RSS is **10.55 GiB** — the threaded composite (128/N4) under `MemoryMax=12G` (~1.14× headroom; N=6
would OOM; the serial composite was 6.24 GiB). Tiling runs under a **separate 16 G cap** (`run_pass.sh`,
sized off the per-worker `GDAL_CACHEMAX` math) and peaks ~2 GiB anon across 18 processes. **`memory.current`
is not RSS**: during tiling the cgroup sits at ~16 GiB, but that is reclaimable page cache (`anon` 0.58 GiB)
— watch **anon**, not the total.

## Hero renders (separate pipeline — Blender, not the tiler)

| Stage | First run | Re-run | Output |
|---|---|---|---|
| `render/render_prep.py --frame` → `frame.json` | ~seconds | `is_stale` | per-country frame + warps |
| `render/lake_mask.py` (new 2026-07-23, stage 5.5) | **0:11 finland (lake-densest) / 0:03 estonia** — the feared 83k-source-VRT warp cost is seconds, not minutes | skip-if-exists | `lakedepth_aea.tif` (log1p ramp position) |
| `render/scene_build.py --render` — headless Cycles, OptiX | **3:36 @ 8K** (finland 1:29 at 4142×7680) | n/a | one hero PNG |
| Full batch — **204 heroes** | **overnight** (estimate; GPU-bound, occupies the desktop) | per-country resume | `blender/renders/` |
| `batch --through prep`, all outputs cached (the 2026-07-23 sea-sync pre-pass) | **~2 h for 204** (≈35 s/country of pure walk overhead — a 20-40 min projection missed 3× by counting only the lake warp) | same | prep-complete markers |

8K frames denoise on **CPU**, not GPU: GPU render + GPU OIDN contend for the 12 GB VRAM → Xid 31 MMU fault.

**The 35 s/country prep-walk overhead, decomposed (2026-07-23, log-measured):** ~17 s = `build_mosaics.sh`
rebuilding the two 26,475-source VRTs identically per country (371 bars at 8–9 s in one pre-pass ≈ **53 min
of redundant rebuilds**); ~3–6 s = `download_glo30`'s per-country stat loop + 3 ETag HEADs (550+ identical
round-trips per pre-pass); ~4–8 s = six subprocess starts × GDAL/rasterio import (deliberate — OOM
isolation); rest = skip-checks + the real lake warp.

**FIXED same day (TDD, 12 tests, → HISTORY § 2026-07-23 prep-walk redundancy cut):** `build_mosaics.sh`
freshness skip (`.sources` sidecar equality + newer-than-VRT check; **17.6 → 0.63 s**, rebuild proven
byte-identical) and a 24 h `preflight_ok.json` stamp in `download_glo30` (**one 1.6 s ETag check per day,
then ~0.07 s**). A warm six-stage walk measured **1.25 s/country** (was ~35 s) — a full 204-country walk
drops ~1 h; only the deliberate subprocess import tax remains.

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
| OSI SAF sea ice (OSI-450-a) | 640 MB | tile sea ice; **anonymous** THREDDS, **serial** (OSI SAF forbids parallel); 720 monthly files → the 1991–2020 frequency climatology |
| Cop30 void-fill | 1.2 GB | fusion void-fill |
| Natural Earth | 38 MB | borders, framing, coastline oracle |

## Frontend and serving

| Process | Command | Time | Notes |
|---|---|---|---|
| Astro dev server — **the product globe** | `pnpm dev` in `web` (in-repo since the frontend merged to main) | ~2 s | `/globe` on Astro's default port 4321 (not pinned in config); serves `/tiles` from `TILES_STORE` (dev-only middleware, `no-cache`) |
| Static build | `pnpm build` | ~seconds | emits HTML/CSS/JS only — assets stay external |
| Tile smoke test — **not the product** | `python3 -m http.server` in `work/planet_tiles` | instant | proves the pyramid renders with zero deps; no starfield/borders/atmosphere by design |
| PMTiles packaging | `pack_pmtiles.py` → `pmtiles convert` | dir→MBTiles **33 s** (87,381 tiles, 16.15 GB); convert **1m11s** capped + `--tmpdir` on ext4 → 15 GB `planet.pmtiles`, 4,635 tiles (5.3%) deduped | 2026-07-23: first attempt ran uncapped and staged ~12 GB in tmpfs `/tmp` (= RAM on Ubuntu 26.04) → swap 100%, session OOM (→ HISTORY § the uncapped pmtiles convert OOM'd the box). Capped retry verified: `pmtiles verify` clean, 5 tiles byte-identical incl. z8 y=255 |

## If you only remember one thing

The pipeline is **fast to re-run and slow to build**: a cold shade is ~35 min (post-#5) plus a one-time
hour for the lake warp; warm is seconds. Since 2026-07-20 even the tile cut is guarded, so a fully-fresh
`--tiles` re-run is seconds too — the ~3:32 cut runs only when `planet_rgb` actually changed.
