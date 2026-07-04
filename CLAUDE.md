# Relief Globe — project memory

A static website presenting ray-traced relief maps of every country, navigable as an
interactive globe. Design target: the Frank Ramspott "3D Render Topographic Map — Neutral"
aesthetic (soft raytraced shadows, heavy vertical exaggeration, warm sand/rose land +
desaturated teal sea with bathymetry, white vector borders, minimal typography).

## Purpose — learning first (overrides efficiency)

This project is a vehicle for learning: the process matters more than the output. Rohan
wants to understand every piece (DEM data, GDAL, Blender/Cycles, tiling, MapLibre, serving)
— not just have it built.

- Act as a **guide, not a workhorse**: explain the why and the how, surface the concepts
  behind each step, and involve Rohan in the doing rather than silently completing work.
- **Don't make assumptions** — where a choice or concept has depth, be more verbose;
  present it rather than shortcutting past it.
- **Claude writes the code**; the teaching lives in the explanation around it, not in
  delegated typing. Function docstrings are welcome; inline comments only when
  necessary — explain in chat instead.
- Prefer the path that teaches over the path that merely ships. Slower is fine.
- Expect the plan to change significantly as understanding grows; treat PLAN.md as
  genuinely living, and don't resist rework driven by new understanding.

## Architecture (decided — do not re-litigate without explicit discussion)

Three tiers of one site, sharing one asset store, selected by a client-side capability probe:

- **Tier 1 — gallery:** static HTML + responsive hero images (2K/4K/8K variants via srcset).
  Renders instantly for everyone; this is the pessimistic default while the probe runs.
- **Tier 2 — globe:** MapLibre GL JS v5+ globe projection draping pre-shaded raster tiles.
  Requires WebGL2 (feature-detect via `canvas.getContext('webgl2')`).
- **Tier 3 — full:** Tier 2 + terrain-RGB 3D displacement layer + idle animations +
  lazy-loaded 8K hero renders on country click. Gated on GPU tier + network strength.

Principles: default pessimistic / upgrade optimistically; user-overridable quality toggle
(Lite / Globe / Full, persisted); runtime degradation if frame rate tanks; honor
`Save-Data`, `prefers-reduced-motion`, `prefers-reduced-data`.

## Data sources

- **Land elevation:** Copernicus DEM GLO-30 (via AWS Open Data / OpenTopography).
- **Bathymetry:** GEBCO, fused with land DEM into one seamless heightfield.
  Bathymetry is part of the signature look (shelf seas) — not optional.
- **Boundaries / coastlines:** Natural Earth vectors (country polygons, maritime
  boundaries rendered as dashed lines, borders as crisp white vector overlay — never
  baked into raster).

## Rendering decisions

- **Hero renders:** headless Blender Cycles (bpy scripting), GPU = RTX 4070 Super with
  OptiX denoising. One scene rig reused for all countries: DEM as displacement, sun lamp
  at low altitude, two-ramp material (elevation-keyed land, depth-keyed sea),
  orthographic camera framed per-country from Natural Earth bounding boxes.
  Vertical exaggeration ~5–15x, tuned once, applied globally for consistency.
- **Tile pyramid:** raster approximation of the Cycles look — multidirectional hillshade
  + sky-view factor / ambient occlusion (WhiteboxTools) + the same two color ramps,
  composited with GDAL. Zoom 0–8 initially; extend to z10 max (matches 30m source limit).
- **Tiles are 512px (@2x)** — the aesthetic lives in fine shading detail; 256px tiles
  look soft on high-DPI screens.
- Baked NW-ish lighting globally (cartographic convention); no per-region sun position.

## Serving & deployment

- Package tiles as **PMTiles** (single file, HTTP range requests, no tile server).
- Hosting: static, on rohome behind the existing Pangolin reverse proxy
  (`*.alchez.dev` via Scaleway VPS), plain nginx container. Aggressive cache headers.
- Everything pre-rendered; no server-side compute at request time.

## Environment

- Dev/render machine: dual-boot desktop PC (RTX 4070 Super, 12GB VRAM). **All project
  work happens in the Ubuntu boot** — native NVIDIA driver + CUDA/OptiX, Blender on
  Linux. The Windows boot is not used for this project; never suggest Windows paths,
  WSL, PowerShell, or Windows-specific tooling.
- Keep all project data on the ext4 filesystem. Do not read/write large rasters from
  NTFS partitions.
- Host: rohome — Ubuntu 26.04 LTS, Docker Compose stack, Watchtower auto-updates.
  Same distro family as the dev machine: containerized pipeline must run unchanged on
  both (dev iterations on desktop, full production passes + serving on rohome).
- Expect ~8–10 GB of DEM tiles per large country; full pyramid tens of GB — plan disk
  accordingly and keep intermediates out of backups.

## Working conventions

- Pipeline stages must be **idempotent and resumable** — a crash at tile N must not
  restart the world. Cache intermediates; validate outputs per stage.
- Python for pipeline code (GDAL, rasterio, bpy). Prefer boring, debuggable scripts
  over frameworks.
- PLAN.md is the living plan: update checkboxes and record decisions there after each
  work session. Before any multi-file or architectural task, plan first (Plan Mode).
- Do not commit rendered assets or DEM data to git — code and config only.
  Assets live in a data directory referenced by config.

## Reference reading

- Daniel Huffman, "Creating Shaded Relief in Blender" (the canonical technique).
- MapLibre GL globe projection docs; PMTiles spec (Protomaps).
- Prior art for land/sea fusion: ETOPO 2022 (NOAA, finished 15" product + reference
  oracle), Tozer et al. 2019 (SRTM15+ paper, describes grdblend assembly), GMT grdblend
  docs (feathered grid blending), Tom Patterson's shadedrelief.com + Blue Earth
  Bathymetry (the aesthetic school we follow, with processed data).
