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
| 6 | Render | `render/scene_build.py` via `blender -b` | The hero PNG |

Python stages run as `python -m <module>` (e.g. `python -m pipeline.render.render_prep …`), shell stages as `bash pipeline/<sub>/<script>.sh`, and the Blender scene as `blender -b --python pipeline/render/scene_build.py`. Ask `country_config --country <slug>` for the exact, filled-in commands.

The geometry behind stages 1–6 — how a lon/lat box becomes projected pixels, displacement scale, and camera framing — is explained in plain English in [`framing-math.md`](framing-math.md). The pipeline diagrams are [`pipeline-overview.mmd`](pipeline-overview.mmd) and [`pipeline-detail.mmd`](pipeline-detail.mmd) (Mermaid).

Borders are **never** rendered inside the Blender scene — they are composited in post as a standalone transparent layer, so the website can toggle them over the hero.

### Phase 2 — the tile pyramid (in progress)

The zoomable globe is a separate, raster-only path that does **not** use Blender: fuse the whole planet once, shade it to imitate the hero look, and cut tiles.

| Module | Produces |
|---|---|
| `pipeline.fuse.fuse_planet` | the planet heightfield (10×10° cells at 10″, `data/work/planet/*.vrt`) |
| `pipeline.acquire.download_snow` | NSIDC-0791 snow-persistence granule (Earthdata token in `.env`) |
| `pipeline.acquire.download_rgi` | RGI 7.0 glacier shapefiles merged to `data/raw/rgi/rgi7_g_3857.gpkg` |
| `pipeline.render.snow` | tile snow: persistence → latitude-ramped soft alpha, unioned with RGI glaciers |
| `pipeline.tile.shade` | reproject cells to Web-Mercator, mosaic, shade once (color-relief × single-NW hillshade × sky-view + snow) → `region_rgb.tif` |

Snow here is **not** the hero's WorldCover class-70 mask (permanent ice only, which left mid/high-latitude ranges bare) — it is observed MODIS snow *persistence* as a soft alpha, ramped by latitude, with RGI glaciers crisp on top. See the [decision log](../PLAN.md) and the pipeline diagrams. Tiling → PMTiles and the seamless full-planet shade (latitude-banded z-factor / windowed composite) are the remaining pieces.

## From heroes to the website

Once heroes exist, three steps turn them into what the site serves:

```bash
python -m pipeline.compose.hero_variants    # 2K/4K/native WebP variants per hero (downscale-only, idempotent)
python -m pipeline.compose.gen_borders      # transparent white border layer per country
```

Both take `--only <slug,slug>` to process a subset and `--force` to redo existing outputs. Then the frontend (a separate Astro site in the `../maps-frontend` git worktree) regenerates its manifest and builds:

```bash
python ../maps-frontend/web/scripts/gen_manifest.py --out ../maps-frontend/web/src/data/countries.json
pnpm --dir ../maps-frontend/web build
```

The manifest reads the actual variant dimensions off disk, so the gallery and detail pages fill in automatically as renders complete.
