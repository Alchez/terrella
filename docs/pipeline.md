# The pipeline: raw data to a served globe

Every stage between a published DEM and what the site hands a browser, for both bodies, in the order you would run it: set up a machine, fetch the global data, render heroes, cut the tile pyramid, build the site.

Its two siblings answer the questions this file does not: [`pipeline-layout.md`](pipeline-layout.md) for where a module goes, [`adding-a-body.md`](adding-a-body.md) for what a new planet has to bring. The *why* behind the framing numbers is [`framing-math.md`](framing-math.md); measured stage runtimes are `PROCESS.md`; the high-level picture is the [`README`](../README.md).

## Environment setup (fresh machine)

Ubuntu, natively. Nothing in the pipeline is specific to one machine.

1. **Blender 5.1.2**, official tarball. `paths.BLENDER` finds it, `MAPS_BLENDER` overrides.
2. **Python venv**: `uv sync`, then `source .venv/bin/activate` before every command. Blender's own interpreter cannot import it, which is why numbers reach the scene through `frame.json`.
3. **`pmtiles`**: `bash pipeline/acquire/install_geotools.sh`. Globe only, skip it for heroes. **Not the PyPI `pmtiles`**, a different project with no `edit`, the only writer of a vector cut's `attribution`.

Run every stage from the repo root as `python -m pipeline.<sub>.<module>`. Keep project data on ext4; never read or write large rasters from NTFS.

## Data bootstrap (once per machine)

Two global datasets are fetched once and reused by every country. The batch runner does this on first run; by hand:

```bash
bash pipeline/acquire/download_naturalearth.sh   # borders, framing polygons, coastline oracle (pinned release)
python -m pipeline.acquire.download_gebco        # global bathymetry
```

**Copernicus GLO-30 land tiles are not bootstrapped**, being hundreds of GB for a planet. They are fetched per country, only for the tiles a frame needs: Russia alone pulls ~4900.

## Regenerating a hero

`batch.py` is the normal way in. It runs each country's stages as isolated subprocesses and survives an overnight sweep: crash-safe resume per stage, a memory floor that defers heavy stages under load, and failures logged to `blender/renders/batch_failures.jsonl`.

```bash
python -m pipeline.batch --through render --only nepal            # one country, prep + render
python -m pipeline.batch --through render --only nepal --dry-run  # print the plan, run nothing
python -m pipeline.batch --through render --clean                 # every in-scope country, reclaiming as it goes
```

`--through prep` stops before the render and is the default; `--force` redoes countries already marked done; `--limit N` caps the count; `--mem-floor-gib` tunes the defer threshold.

**For one country's actual filled-in commands, ask the resolver `batch.py` itself uses:**

```bash
python -m pipeline.frame.country_config --country nepal
```

It prints that country's frame, its derived render numbers, its data preflights and the exact stage commands, so it stays right when this page does not.

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

**Every stage above writes into that country's own work directory**, `data/work/<slug>/render/`, which `country_config.country_render_dir` owns. `frame.json` lands there beside the projected rasters, and it is what stage 7 reads across the interpreter boundary.

The graph is drawn in [`pipeline-overview.mmd`](pipeline-overview.mmd) and [`pipeline-detail.mmd`](pipeline-detail.mmd).

## The tile pyramid (the zoomable globe)

The second production lane: fuse the whole planet once, raytrace it block by block, cut tiles, pack them into one servable archive. **It runs the same Cycles rig the heroes do**, so the globe and the gallery are one look rather than two kept in agreement. What differs is the unit of work, a block rather than a country.

**Run a pass through the harness, never by hand:**

```bash
pipeline/profile/run_pass.sh --body earth            # shade only
pipeline/profile/run_pass.sh --body earth --tiles    # shade (skipped when fresh), then cut tiles
```

- **It caps memory in a systemd scope**, sized per body by `pipeline/profile/pass_memory.py` so an overrun kills the job and not the box, and sets `GDAL_CACHEMAX=512`.
- **One heavy job at a time.** The cap is sized for a single pass, and the planet pass ends by invoking `cap_render` inside the same cgroup.

**The four planet-raster stages take a required `--body`**: `planet_pass`, `cap_pass`, `terrain_rgb` and `pack_pmtiles`. None of them defaults to Earth.

- **A default is the tempting fix**, and the wrong one produces plausible output against another body's master. `pipeline/bodies.py` is what the flag resolves against.
- **The acquire stages and the surface-layer producers take no `--body`**, each being about one body's own dataset already, and the two vector cuts are one stage per body rather than one stage taking a body.
- **Intermediates nest per body**, `data/work/<body>/<stage>/`, and **Earth's prefix is empty**: its cut lands in `data/work/planet_tiles/`, Mars's in `data/work/mars/planet_tiles/`.
- **That is what makes each recipe sidecar body-specific for free.** A body field in the recipe is the tempting alternative, and it invalidates Earth's whole correct output the day a second body exists.

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
| `pipeline.tile.cap_pass` | both polar caps (AEQD) → `web/public/caps/` for Earth, whose URLs are a frontend contract, with a second body nesting one level in. `cap_render` is everything a disc is built from and `cap_raytrace` is the only producer, so a disc matches the tiles it feathers into by construction. Runs at the planet pass's tail with the same `--body`. The assets are gitignored, so a clone regenerates them here; `--elev-only` rebuilds just the per-pole terrain-RGB textures, which have their own freshness gate |
| `pipeline.tile.terrain_rgb` | the terrain-RGB elevation pyramid for the globe's Tier-3 displacement, read off `height_3857.tif` rather than the colour raster, which makes it a separate lane and not a stage of the planet pass. `--out` stays required: the variant directory is operator-named, and checked to be under that body's tree rather than derived |
| `pipeline.compose.countries_geojson` → `pipeline.compose.countries_pmtiles` | Earth's vector pyramid: Natural Earth admin-0 polygons simplified to one WGS84 GeoJSON, then cut to `vector.pmtiles`. Three layers (fill, outline, and a fat invisible hit target), because a 176-atoll nation is otherwise unclickable |
| `pipeline.compose.features_geojson` → `pipeline.compose.features_pmtiles` | Mars's vector pyramid: the IAU gazetteer folded to GeoJSON, then cut to its own `vector.pmtiles`. Four layers, including the IAU's label anchors. Both cuts are driven by `pipeline.compose.vector_cut`, which owns the freshness gate, the staging loop and the conversion; the two stages above only declare what is in them |
| `pipeline.tile.pack_pmtiles` + `tools/pmtiles convert` | `planet.pmtiles` and `terrain.pmtiles`: the range-request-servable raster archives. The packer reads the tile encoding off the directory, so one command packs either, and `--layer` decides the credit it writes into the archive. The vector pyramids are cut straight to PMTiles by the two stages above and never pass through here |

Snow here is **not** the hero's WorldCover class-70 mask: it is observed snow persistence as a soft alpha, ramped by latitude, with RGI glaciers crisp on top. `CLAUDE.md` § *Data sources* owns why the two surfaces differ, and the pipeline diagrams show the full graph.

## From heroes to the website

Two compose steps and a manifest regeneration turn finished heroes into what the site serves. Both compose steps take `--only <slug,slug>` and `--force`.

```bash
python -m pipeline.compose.hero_variants --jobs 8   # 6 srcset rungs per hero (downscale-only, idempotent)
python -m pipeline.compose.gen_spotlight            # transparent Focus layer: dims everything outside the country
python web/scripts/gen_manifest.py --out web/src/data/countries.json
pnpm --dir web build
```

- **Both share one rung ladder**, 640/960/1280/1920/3840/native: the gallery stacks their outputs under one `sizes`, so a rung in one and not the other fetches mismatched files. `tests/test_hero_variants.py` guards it.
- **Parallelism is a memory question, per script.** `--jobs 8` suits `hero_variants`; `gen_spotlight` is serial because its **native** rung peaks near 8 GB. Time one slug first; `PROCESS.md` has the pass costs.
- **`hero_variants_recipe.json` records rung to WebP quality**, since existence cannot tell a q95 file from the q85 it replaced. Changing `quality_for()` restages that rung and only that rung.
- **Borders are baked, not toggled.** `compose/overlay_borders.py` draws them over the finished render; the spotlight is a hero's only toggle asset.
- **The manifest reads variant dimensions off disk**, so the gallery and detail pages fill in as renders complete.
