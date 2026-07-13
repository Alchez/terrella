# Terrella

Ray-traced relief maps of every country, served as a static website that upgrades from a plain image gallery to an interactive globe as the visitor's hardware allows. The heroes are rendered in Blender Cycles from real elevation data (Copernicus GLO-30 land + GEBCO bathymetry, fused into one seamless heightfield), shaded to the Frank Ramspott "3D Render Topographic Map" look and composited with Natural Earth borders.

This README is the operational entry point: how to set up a fresh machine and regenerate any hero from source. The *why* behind the numbers lives elsewhere — see [Where to read next](#where-to-read-next).

## The one thing to know

**Every hero is reproducible from committed source.** No rendered asset or DEM tile is in git — only code, config, and the per-country frame pins. The single source of truth for "what commands rebuild country X" is the resolver itself:

```bash
python -m pipeline.frame.country_config --country nepal
```

That prints Nepal's frame, its derived render numbers, its data preflights, and **the exact stage commands** — the same commands the batch runner executes. When in doubt about how a country is built, ask `country_config`; this doc explains the workflow around it, not a frozen command list that would drift.

## Repository map

| Path | What lives here |
|---|---|
| `pipeline/` | Every pipeline stage, a Python package grouped by phase: `acquire/` (downloads), `fuse/` (mosaics + heightfield), `frame/` (framing + the `country_config` resolver), `render/` (prep, snow, Blender scene, sky-view), `compose/` (borders, variants) — with `batch.py` (orchestrator) and `ot_oracle.py` at the root. Stages run as modules: `python -m pipeline.<sub>.<module>`. Boring, debuggable, idempotent. |
| `config/countries.toml` | The scope (~204 heroes) and per-country overrides: frames, curated includes, exclusions, antimeridian markers. The editable source of truth. |
| `config/frames/*.json` | Committed frame pins for countries whose framing was hand-tuned (e.g. India). |
| `data/` | DEM/bathymetry rasters and work intermediates. **Gitignored** — regenerated, never committed. |
| `blender/renders/heroes/` | Final hero PNGs (`<slug>.png`). Gitignored. |
| `blender/renders/variants/` | Responsive WebP variants + transparent border layers the website serves. Gitignored. |
| `docs/` | Deeper explainers: the framing math and the pipeline diagrams. |
| `PLAN.md` | The living plan and full decision log — every non-obvious choice and its rationale. |
| `ART.md` | The locked aesthetic constants (sun angle, ramps, exaggeration) frozen at Phase 0 exit. |
| `ATTRIBUTIONS.md` | Data-source licenses and the made-with-AI posture. |

## Environment setup (fresh machine)

The project runs natively on Ubuntu (dev box and the rohome host share the distro family; the pipeline is designed to run unchanged on both).

1. **Blender 5.1.2** — a tarball install, *not* on PATH. This project expects it at `~/software/blender-5.1.2-linux-x64/blender`. Render headless with `blender -b`; the GUI needs far more RAM and is not used for production.
2. **Python venv** — uv-managed. `uv sync` rebuilds `.venv` exactly from `pyproject.toml` + `uv.lock`. Activate it for every pipeline command: `source .venv/bin/activate`. (Blender's bundled Python 3.13 is a *separate* interpreter — `bpy` scripts cannot import the venv's packages, which is why geographic numbers are computed outside Blender and handed over in `frame.json`.)
3. **Vendored geotools** — `bash pipeline/acquire/install_geotools.sh` installs the pinned `pmtiles` binary into gitignored `tools/`. Only needed for the Phase 2 tile pyramid, not for hero renders.
4. **`.env`** *(optional)* — holds `OPENTOPOGRAPHY_API_KEY`, used only by `pipeline/ot_oracle.py` (a dev-time fusion validation oracle). Gitignored; not required to render.

Keep all project data on the ext4 filesystem — never read or write large rasters from NTFS.

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

`pipeline/` is a Python package: **Python stages run as `python -m <module>`** (e.g. `python -m pipeline.render.render_prep …`), shell stages as `bash pipeline/<sub>/<script>.sh`, and the Blender scene as `blender -b --python pipeline/render/scene_build.py`. Ask `country_config --country <slug>` for the exact, filled-in commands.

The geometry behind stages 1–6 — how a lon/lat box becomes projected pixels, displacement scale, and camera framing — is explained in plain English in [`docs/framing-math.md`](docs/framing-math.md). The pipeline diagrams are [`docs/pipeline-overview.mmd`](docs/pipeline-overview.mmd) and [`docs/pipeline-detail.mmd`](docs/pipeline-detail.mmd) (Mermaid).

Borders are **never** rendered inside the Blender scene — they are composited in post as a standalone transparent layer, so the website can toggle them over the hero.

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

## Where to read next

- **[`PLAN.md`](PLAN.md)** — the living plan and decision log. Start here for the current phase and the rationale behind any choice.
- **[`docs/framing-math.md`](docs/framing-math.md)** — how a country name becomes a framed, projected render.
- **[`ART.md`](ART.md)** — the locked aesthetic constants (changing them means re-rendering every hero).
- **[`ATTRIBUTIONS.md`](ATTRIBUTIONS.md)** — data licenses and attribution.
- **[`CLAUDE.md`](CLAUDE.md)** — project conventions and environment specifics.
