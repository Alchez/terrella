# Running the pipeline

How to set up a fresh machine and regenerate any Terrella hero from source. This is the operational runbook; the *why* behind the numbers is in [`framing-math.md`](framing-math.md), and the high-level picture is in the top-level [`README`](../README.md).

## Reproducible from source

No rendered asset or DEM tile is in git — only code, config, and the per-country frame pins. The single source of truth for "what commands rebuild country X" is the resolver itself:

```bash
python -m pipeline.frame.country_config --country nepal
```

That prints Nepal's frame, its derived render numbers, its data preflights, and **the exact stage commands** — the same commands the batch runner executes. When in doubt about how a country is built, ask `country_config`; this doc explains the workflow around it, not a frozen command list that would drift.

## Environment setup (fresh machine)

The project runs natively on Ubuntu (dev box and the rohome host share the distro family; the pipeline is designed to run unchanged on both).

1. **Blender 5.1.2** — a tarball install, *not* on PATH. This project expects it at `~/software/blender-5.1.2-linux-x64/blender`. Render headless with `blender -b`; the GUI needs far more RAM and is not used for production.
2. **Python venv** — uv-managed. `uv sync` rebuilds `.venv` exactly from `pyproject.toml` + `uv.lock`. Activate it for every pipeline command: `source .venv/bin/activate`. (Blender's bundled Python 3.13 is a *separate* interpreter — `bpy` scripts cannot import the venv's packages, which is why geographic numbers are computed outside Blender and handed over in `frame.json`.)
3. **Vendored geotools** — `bash pipeline/acquire/install_geotools.sh` installs the pinned `pmtiles` binary into gitignored `tools/`. Only needed for the Phase 2 tile pyramid, not for hero renders.
4. **`.env`** *(optional)* — holds `OPENTOPOGRAPHY_API_KEY`, used only by `pipeline.ot_oracle` (a dev-time fusion validation oracle). Gitignored; not required to render.

`pipeline/` is a Python package — run every stage from the repo root as `python -m pipeline.<sub>.<module>`. Keep all project data on the ext4 filesystem — never read or write large rasters from NTFS.

## Data bootstrap (once per machine)

Two global datasets are fetched once and reused by every country. The batch runner does this automatically on first run, but you can run them by hand:

```bash
bash pipeline/acquire/download_naturalearth.sh   # borders, framing polygons, coastline oracle (pinned release)
python -m pipeline.acquire.download_gebco        # global bathymetry
```

Copernicus GLO-30 land tiles are **not** bootstrapped globally — they are downloaded per country, on demand, only for the tiles a frame needs (a full planet's worth is hundreds of GB). Russia alone pulls ~4900 tiles.

## Regenerating a hero

The batch runner drives the whole chain and is the normal way in. It reuses `country_config`'s resolver, runs each country's stages as isolated subprocesses, and is built to survive an overnight sweep — crash-safe resume (a file at its final path means "done"; a partial country resumes stage-by-stage), a memory floor that defers heavy stages under load, and per-country failure logging to `blender/renders/batch_failures.jsonl`.

**One country, end to end** (prep + render):

```bash
python -m pipeline.batch --through render --only nepal
```

**Preview the plan without running anything:**

```bash
python -m pipeline.batch --through render --only nepal --dry-run
```

**The full sweep** (all in-scope countries; `--clean` reclaims per-country intermediates as it goes):

```bash
python -m pipeline.batch --through render --clean
```

Useful flags: `--through prep` stops before the render stage (the default, for a prep-ahead pass); `--force` redoes countries already marked done; `--limit N` caps the count; `--mem-floor-gib` tunes the defer-under-load threshold.

### What the stages do

The chain `country_config` prints per country, in order. Each stage finalizes its output atomically, so re-running skips completed work.

| # | Stage | Module / script | Produces |
|---|---|---|---|
| 0 | Bootstrap *(once)* | `acquire/download_naturalearth.sh`, `pipeline.acquire.download_gebco` | Global vectors + bathymetry |
| 1 | Download land DEM | `pipeline.acquire.download_glo30` | GLO-30 tiles for the frame |
| 2 | Build mosaics | `fuse/build_mosaics.sh` | VRT mosaics of DEM + water-body mask |
| 3 | Fuse heightfield | `pipeline.fuse.fuse_heightfield` | Seamless land+sea heightfield + ocean/lake/river masks |
| 4 | Render prep | `pipeline.render.render_prep` | Projected rasters + `frame.json` (every derived number) |
| 5 | Snow mask | `pipeline.render.snow_mask` | Snow/ice mask (ESA WorldCover class 70) |
| 6 | Lake depth mask | `pipeline.render.lake_mask` | `lakedepth_aea.tif` (GLOBathy depth → ramp position; lakes shade by depth, rivers stay flat) |
| 7 | Render | `render/scene_build.py` via `blender -b` | The hero PNG |

Python stages run as `python -m <module>` (e.g. `python -m pipeline.render.render_prep …`), shell stages as `bash pipeline/<sub>/<script>.sh`, and the Blender scene as `blender -b --python pipeline/render/scene_build.py`. Ask `country_config --country <slug>` for the exact, filled-in commands.

The geometry behind stages 1–7 — how a lon/lat box becomes projected pixels, displacement scale, and camera framing — is explained in plain English in [`framing-math.md`](framing-math.md). The pipeline diagrams are [`pipeline-overview.mmd`](pipeline-overview.mmd) and [`pipeline-detail.mmd`](pipeline-detail.mmd) (Mermaid).

Borders are **never** rendered inside the Blender scene — they are composited in post as a standalone transparent layer, so the website can toggle them over the hero.

### The tile pyramid (the zoomable globe)

A separate, raster-only path that does **not** use Blender: fuse the whole planet once, shade it to imitate the hero look, cut tiles, and pack them into one servable archive.

| Module | Produces |
|---|---|
| `pipeline.fuse.fuse_planet` | the planet heightfield, pole to pole (10×10° cells at 10″, `data/work/planet/*.vrt`) |
| NSIDC-0791 snow persistence | the snow-persistence NetCDF, obtained from NSIDC via Earthdata (earthaccess/CMR) and placed at `data/raw/snow/` — **no committed acquire script** (unlike RGI / sea ice) |
| `pipeline.acquire.download_rgi` | RGI 7.0 glacier shapefiles merged to `data/raw/rgi/rgi7_g_3857.gpkg` |
| `pipeline.acquire.download_seaice` | OSI SAF monthly sea-ice concentration → the annual ice-frequency climatology |
| `pipeline.render.snow` | tile snow: persistence → latitude-ramped soft alpha, unioned with RGI glaciers |
| `pipeline.render.seaice` | sea-ice alpha over the ocean (translucent white, seafloor glows through) |
| `pipeline.render.lake_depth` | GLOBathy lake depth on the tile grid (depth-keyed lake tint) |
| `pipeline.tile.shade_planet` | the production planet pass: warp everything to one Web-Mercator grid, hillshade + fill sun, sky-view, windowed composite → `planet_rgb.tif`, then `gdal raster tile` → the z0–8 pyramid (`pipeline.tile.shade` is the region-sized A/B path) |
| `pipeline.tile.cap_render` | both polar caps (AEQD, the same composite) → `web/public/caps/` |
| `pipeline.tile.pack_pmtiles` + `tools/pmtiles convert` | `planet.pmtiles` — the single range-request-servable archive |

Snow here is **not** the hero's WorldCover class-70 mask (permanent ice only, which left mid/high-latitude ranges bare) — it is observed MODIS snow *persistence* as a soft alpha, ramped by latitude, with RGI glaciers crisp on top. The decisions behind every piece are in [`HISTORY.md`](../HISTORY.md); the pipeline diagrams show the full graph.

## From heroes to the website

Once heroes exist, four steps turn them into what the site serves:

```bash
python -m pipeline.compose.hero_variants    # 2K/4K/native WebP variants per hero (downscale-only, idempotent)
python -m pipeline.compose.gen_borders      # transparent white border layer per country
python -m pipeline.compose.gen_spotlight    # transparent Focus layer: dims everything outside the country
```

All three take `--only <slug,slug>` to process a subset; `gen_borders` and `gen_spotlight` also take
`--force` to redo existing outputs. `gen_spotlight` runs serially by default — the largest countries
peak near 8 GB each, so `--jobs>1` needs real headroom above the 12 G cap. Then the frontend (the in-repo Astro site in `web/`, merged to main) regenerates its manifest and builds:

```bash
python web/scripts/gen_manifest.py --out web/src/data/countries.json
pnpm --dir web build
```

The manifest reads the actual variant dimensions off disk, so the gallery and detail pages fill in automatically as renders complete.
