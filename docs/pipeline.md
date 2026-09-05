# Running the pipeline

How to set up a fresh machine and regenerate any Terrella hero from source. This is the operational runbook; the *why* behind the numbers is in [`framing-math.md`](framing-math.md), and the high-level picture is in the top-level [`README`](../README.md).

## Reproducible from source

No rendered asset or DEM tile is in git: only code, config, and the per-country frame pins. The single source of truth for "what commands rebuild country X" is the resolver itself:

```bash
python -m pipeline.frame.country_config --country nepal
```

That prints Nepal's frame, its derived render numbers, its data preflights, and **the exact stage commands**, the same commands the batch runner executes. When in doubt about how a country is built, ask `country_config`; this doc explains the workflow around it, not a frozen command list that would drift.

## How `pipeline/` is laid out

Four kinds of thing live in the package, and which one a module is decides where it sits.

- **A sub-package holds stages that run.** Most are named for the step they perform, in roughly the order the data moves: `acquire` fetches published data, `fuse` welds land and sea into one heightfield, `frame` resolves a country into render parameters, `tile` cuts the raster pyramids, `compose` assembles the delivered vectors and image variants. `render` is the hero rig, one country into one Cycles image. Two are named for what they hold instead of for a step, `look` and `profile`.
- **A law or a seam at the top level of `pipeline/` is something more than one stage reads**, and it is there because the copies had drifted. `mercator.py` exists because two shading modules each carried their own Earth radius and their own inverse projection; `raster_io.py` because one windowed-read fix landed at a single call site and was missed at its siblings. So reaching for a new one is a claim that a second reader exists, and the test is: change one copy, what goes red? Nothing red means it does not belong at the top level yet.
- **An entry point also sits at the top level, and the reader test above does not apply to it**, because it is run rather than imported and its reader count is zero by construction. `batch.py` is the runner and the documented way in; `ot_oracle.py` is a dev-time fusion oracle that no production sweep invokes. What places these is that they stand outside the stage order rather than inside it.
- **A helper at the top level is reached for by a test or a hand-run probe, and by no stage.** `verify.py` is the one, a raster comparison built so that a check cannot quietly pass. It is not `profile/`, which measures what a run cost; this measures whether the output is what it should be.

**`look/` and `render/` are the pair most easily confused.** `look/` is what a surface is painted with and how it is lit, the surface layers and the shared shading law, read by both rigs. `render/` is the hero rig alone. The dependency runs one way, `render` onto `look`, and a cycle between them means a module sits on the wrong side. `profile/` is instrumentation and produces nothing the site serves.

**Nothing here is grouped by planet**, which is the question the tree invites and the one a directory listing answers wrongly. Bodies are data and stages are code: a stage never branches on which body it holds, it reads a field. So what a planet is, has, and requires is declared rather than filed, in `bodies.Body` (its geometry and its exaggeration), `Body.surface_layers` against the `layers.Layer` vocabulary (which surfaces it has), and `look/layer_producers.py` with `look/perennial_ice.py` (who builds each of those for it). No field carries a default, so every one of those is a hard error until a new body answers for it. A per-body directory would state the same thing where nothing can check it, and a body that had not answered would look like a body with fewer files.

The root `__init__.py` carries this rule beside the code, and each sub-package's own `__init__.py` states what that package holds, so both are readable from inside the package as well as from here.

## Environment setup (fresh machine)

The project runs natively on Ubuntu (dev box and the rohome host share the distro family; the pipeline is designed to run unchanged on both).

1. **Blender 5.1.2**, a tarball install, *not* on PATH. This project expects it at `~/software/blender-5.1.2-linux-x64/blender`. Render headless with `blender -b`; the GUI needs far more RAM and is not used for production.
2. **Python venv**, uv-managed. `uv sync` rebuilds `.venv` exactly from `pyproject.toml` + `uv.lock`. Activate it for every pipeline command: `source .venv/bin/activate`. (Blender's bundled Python 3.13 is a *separate* interpreter, so `bpy` scripts cannot import the venv's packages, which is why geographic numbers are computed outside Blender and handed over in `frame.json`.)
3. **Vendored geotools**: `bash pipeline/acquire/install_geotools.sh` installs the pinned `pmtiles` binary into gitignored `tools/`. Only needed for the Phase 2 tile pyramid, not for hero renders.
4. **`.env`** *(optional)*, holding `OPENTOPOGRAPHY_API_KEY`, used only by `pipeline.ot_oracle` (a dev-time fusion validation oracle). Gitignored; not required to render.

`pipeline/` is a Python package, so run every stage from the repo root as `python -m pipeline.<sub>.<module>`. Keep all project data on the ext4 filesystem; never read or write large rasters from NTFS.

## Data bootstrap (once per machine)

Two global datasets are fetched once and reused by every country. The batch runner does this automatically on first run, but you can run them by hand:

```bash
bash pipeline/acquire/download_naturalearth.sh   # borders, framing polygons, coastline oracle (pinned release)
python -m pipeline.acquire.download_gebco        # global bathymetry
```

Copernicus GLO-30 land tiles are **not** bootstrapped globally. They are downloaded per country, on demand, only for the tiles a frame needs (a full planet's worth is hundreds of GB). Russia alone pulls ~4900 tiles.

## Regenerating a hero

The batch runner drives the whole chain and is the normal way in. It reuses `country_config`'s resolver, runs each country's stages as isolated subprocesses, and is built to survive an overnight sweep: crash-safe resume (a file at its final path means "done"; a partial country resumes stage-by-stage), a memory floor that defers heavy stages under load, and per-country failure logging to `blender/renders/batch_failures.jsonl`.

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
| 6 | Lake depth mask | `pipeline.render.lake_mask` | `lakedepth.tif` (GLOBathy depth → ramp position; lakes shade by depth, rivers stay flat) |
| 7 | Render | `render/scene_build.py` via `blender -b` | The hero PNG |

Python stages run as `python -m <module>` (e.g. `python -m pipeline.render.render_prep …`), shell stages as `bash pipeline/<sub>/<script>.sh`, and the Blender scene as `blender -b --python pipeline/render/scene_build.py`. Ask `country_config --country <slug>` for the exact, filled-in commands.

The geometry behind stages 1–7 (how a lon/lat box becomes projected pixels, displacement scale, and camera framing) is explained in plain English in [`framing-math.md`](framing-math.md). The pipeline diagrams are [`pipeline-overview.mmd`](pipeline-overview.mmd) and [`pipeline-detail.mmd`](pipeline-detail.mmd) (Mermaid).

Borders are **never** rendered inside the Blender scene. They are composited in post as a standalone transparent layer, so the website can toggle them over the hero.

### The tile pyramid (the zoomable globe)

A separate, raster-only path that does **not** use Blender: fuse the whole planet once, shade it to imitate the hero look, cut tiles, and pack them into one servable archive.

**The four planet-raster stages take a required `--body`**: `planet_pass`, `cap_pass`, `terrain_rgb` and `pack_pmtiles`. None of them defaults to Earth, deliberately: a default is exactly the silent Earth assumption the second body exists to remove, and the wrong one would produce plausible output against the wrong master. The body decides the vertical exaggeration, the zoom ceiling, the colour ramp and the projection radii together, from the registry in `pipeline/bodies.py`. The acquire stages and the surface-layer producers below take no `--body`, because each is already about one body's own dataset, and the two vector cuts are one stage per body rather than one stage taking a body.

Each body's intermediates live under its own work directory, `data/work/<body>/<stage>/`. **Earth's prefix is empty**, which keeps it on its historical layout: Earth's cut lands in `data/work/planet_tiles/` and Mars's in `data/work/mars/planet_tiles/`. That is what makes every recipe sidecar body-specific for free, without a body field in the recipe itself, which would have invalidated Earth's entire correct output the moment a second body existed.

**Run a full pass through the harness, not by hand:**

```bash
pipeline/profile/run_pass.sh --body earth            # shade only
pipeline/profile/run_pass.sh --body earth --tiles    # shade (skipped when fresh), then cut tiles
```

It runs the pass inside a systemd scope with a memory cap derived per body by `pipeline/profile/pass_memory.py`, so an overrun kills the job rather than the box, and it sets `GDAL_CACHEMAX=512`. Run **one heavy job at a time**: the cap is sized for a single pass, and the planet pass ends by invoking `cap_render` as a subprocess inside the same cgroup.

| Module | Produces |
|---|---|
| `pipeline.fuse.fuse_planet` | Earth's planet heightfield, pole to pole (10×10° cells at 10″, `data/work/planet/*.vrt`). **Earth only**: Mars arrives pre-fused, so it has no fusion tier at all |
| `pipeline.acquire.download_mars_dem` | the USGS MOLA/HRSC blended DEM at 200 m, which *is* Mars's heightfield rather than an input to one |
| `pipeline.acquire.download_sim3292` | SIM 3292, the geologic map that says where Mars's permanent polar ice is |
| `pipeline.acquire.download_viking_mosaic` | the Viking colour mosaic: the ice's brightness, and the hue Mars's land ramp is measured against |
| `pipeline.acquire.download_nomenclature` | the IAU gazetteer, the source of Mars's named features |
| NSIDC-0791 snow persistence | the snow-persistence NetCDF, obtained from NSIDC via Earthdata (earthaccess/CMR) and placed at `data/raw/snow/`. **No committed acquire script** (unlike RGI / sea ice) |
| `pipeline.acquire.download_rgi` | RGI 7.0 glacier shapefiles merged to `data/raw/rgi/rgi7_g_3857.gpkg` |
| `pipeline.acquire.download_seaice` | OSI SAF monthly sea-ice concentration → the annual ice-frequency climatology |
| `pipeline.look.snow` | tile snow: persistence → latitude-ramped soft alpha, unioned with RGI glaciers |
| `pipeline.look.seaice` | sea-ice alpha over the ocean (translucent white, seafloor glows through) |
| `pipeline.look.lake_depth` | GLOBathy lake depth on the tile grid (depth-keyed lake tint) |
| `pipeline.tile.planet_pass` | the production planet pass: warp everything to one Web-Mercator grid, then raytrace it block by block → `planet_rgb.tif`, then `gdal raster tile` → the z0–8 pyramid, then the polar caps. Four stages in order, sequenced from outside whichever one fills the raster |
| `pipeline.planet_warp` | the first planet stage: warp the 4326 height and masks onto the WMQ-aligned 3857 grid every block's context is cut from |
| `pipeline.tile.cut_tiles` | the last planet stage: cut 512px tiles out of the finished raster, to this body's own ceiling. What fills the raster between the two is `pipeline.tile.block_render` |
| `pipeline.tile.block_render` | the pass's RAYTRACE producer: the same raster rendered block by block through Cycles, resumable per block |
| `pipeline.tile.cap_pass` | both polar caps (AEQD) → `web/public/caps/` for Earth, whose URLs are a frontend contract, with a second body nesting one level in. Every disc is raytraced, so it matches the tiles it feathers into by construction: `pipeline.tile.cap_render` is everything a disc is built from and `pipeline.tile.cap_raytrace` is the only producer. The arm was picked off a per-body field until that field and the composited arm were deleted. Takes the same required `--body` the planet pass does, and is invoked with it automatically at that pass's tail. The cap assets are gitignored, so a fresh clone regenerates them here; `--elev-only` rebuilds just the per-pole terrain-RGB textures, which have their own freshness gate and do not require the ~14 GB colour render |
| `pipeline.tile.terrain_rgb` | the terrain-RGB elevation pyramid for the globe's Tier-3 displacement, read straight off `height_3857.tif`, never the colour raster, so it is a separate lane rather than a stage of the planet pass. Takes the same required `--body` the shade and cap passes do, which picks the master, the ceiling and the descent's factor together; `--out` stays required, because the variant directory under the stage is operator-named and is checked to be under that body's tree rather than derived |
| `pipeline.compose.countries_geojson` → `pipeline.compose.countries_pmtiles` | Earth's vector pyramid: Natural Earth admin-0 polygons simplified to one WGS84 GeoJSON, then cut to `vector.pmtiles`. Three layers (fill, outline, and a fat invisible hit target), because a 176-atoll nation is otherwise unclickable |
| `pipeline.compose.features_geojson` → `pipeline.compose.features_pmtiles` | Mars's vector pyramid: the IAU gazetteer folded to GeoJSON, then cut to its own `vector.pmtiles`. Four layers, including the IAU's label anchors. Both cuts are driven by `pipeline.compose.vector_cut`, which owns the freshness gate, the staging loop and the conversion; the two stages above only declare what is in them |
| `pipeline.tile.pack_pmtiles` + `tools/pmtiles convert` | `planet.pmtiles`, `terrain.pmtiles` and `vector.pmtiles`: the range-request-servable archives, one per pyramid. The packer reads the tile encoding off the directory, so the same command packs any of them |

Snow here is **not** the hero's WorldCover class-70 mask (permanent ice only, which left mid/high-latitude ranges bare). It is observed MODIS snow *persistence* as a soft alpha, ramped by latitude, with RGI glaciers crisp on top. The decisions behind every piece are recorded in the project's decision archive, which is kept outside this repository (`CLAUDE.md` says what its citations mean); the pipeline diagrams show the full graph.

## From heroes to the website

Once heroes exist, two compose steps and a manifest regeneration turn them into what the site serves:

```bash
python -m pipeline.compose.hero_variants --jobs 8   # 6 srcset rungs per hero (downscale-only, idempotent)
python -m pipeline.compose.gen_spotlight    # transparent Focus layer: dims everything outside the country
```

Both take `--only <slug,slug>` to process a subset, and both take `--force`. They share one rung
ladder, **640/960/1280/1920/3840/native**, because the gallery stacks their outputs under a single
`sizes`; a rung in one ladder and not another makes the browser fetch mismatched files
(`tests/test_hero_variants.py` guards this against what the pages declare).

Each hero's borders are composited in by `overlay_borders` during the render, not toggled: there is
no separate border layer.

Parallelism is per-script and is a MEMORY question, not a core one. `hero_variants` peaks at ~525 MB
per encode, so `--jobs 8` is comfortable and takes the 203-hero pass from ~49 min to ~6 min.
`gen_spotlight` defaults to serial because its **native** rung peaks near 8 GB, but a small-rung
pass (640/960/1280 only) measures ~0.5 GB per job, so that constraint does not apply to it; time one
slug before choosing.

`hero_variants` also records `hero_variants_recipe.json` (rung → the WebP quality it was written at).
Existence alone cannot tell a q95 file from the q85 one it replaced, so **changing `quality_for()` is
what restages a rung**, and only that rung. Then the frontend (the Astro site in `web/`) regenerates its manifest and builds:

```bash
python web/scripts/gen_manifest.py --out web/src/data/countries.json
pnpm --dir web build
```

The manifest reads the actual variant dimensions off disk, so the gallery and detail pages fill in automatically as renders complete.
