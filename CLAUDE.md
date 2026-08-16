# Terrella — project memory

A static site of ray-traced relief maps, navigable as an interactive globe — every country on Earth,
and Mars as a second body.
Look target: Frank Ramspott's "3D Render Topographic Map — Neutral" — soft raytraced shadows,
heavy vertical exaggeration, warm sand land, desaturated teal sea with bathymetry, white vector
borders, minimal typography. The aesthetic decisions live in ART.md.

This file is the standing brief for anyone working on the repo, human or agent. It states current
truth only; it is not a changelog.

## Purpose — learning first (overrides efficiency)

This project is a vehicle for learning: the point is to understand every piece — DEM data, GDAL,
Blender/Cycles, tiling, MapLibre, serving — not to be handed a finished site.

- Be a **guide, not a workhorse**: explain the why, and involve the maintainer in the doing.
- Where a choice has depth, present it rather than shortcutting past it.
- **Claude writes the code**; the teaching lives in chat. Docstrings welcome, inline comments only where necessary.
- Prefer the path that teaches over the path that merely ships. Slower is fine.
- Expect the plan to change as understanding grows; don't resist rework.

## Architecture (decided — do not re-litigate without explicit discussion)

Three tiers of one site, one asset store, chosen by a client-side capability probe.

- **Tier 1 gallery** — static HTML + responsive hero images; the pessimistic default while the probe runs.
- **Tier 2 globe** — MapLibre globe projection over pre-shaded raster tiles; needs WebGL2. Pinned to an exact version in `web/package.json`, with one vendored patch (`patches/`, guarded by `vendoredPatches.test.ts`).
- **Tier 3 full** — Tier 2 + terrain-RGB displacement + the idle spin + the in-globe hero panel, gated on GPU tier and network. The panel loads the srcset rung that fits the card, never the 8K master.

Default pessimistic and upgrade optimistically; the Lite/Globe/Full toggle persists and beats the
probe; degrade at runtime if frame rate tanks; honour `Save-Data`, `prefers-reduced-motion`,
`prefers-reduced-data`.

## Data sources

Every line below is **Earth's** until the Mars one, which is the whole of Mars's list — stated here
rather than pointed at, because MARS.md is slated to leave version control and nothing tracked may
depend on it.

- **Land:** Copernicus DEM GLO-30. The AWS *Public DGED 2021* edition withholds tiles over some regions and a missing tile fuses **silently as ocean** — fill gaps from OpenTopography `2023_1` (keyless S3, `--no-sign-request`).
- **Bathymetry:** GEBCO, fused with the land DEM into one seamless heightfield. Part of the signature look, not optional.
- **Only those two are fused.** Everything below is warped onto the render grid at composite time and never enters the fusion master, which is also why a finer re-fuse would not have to redo any of it.
- **Lake beds:** GLOBathy (CC0), a **tint-only** input — a carved bed at 15× makes a crater of every lake and kills the flat plate that catches the surrounding shadows. Modelling every lake alike is deliberate: restricting to surveyed ones renders survey funding as geology, the discontinuity falling on the US/Canada border.
- **Snow / glaciers: the two surfaces differ, and that is a decision rather than drift.** Tiles take NSIDC-0791 persistence + RGI 7.0 with a latitude-ramped soft alpha, and **Antarctica is painted white outright** (persistence is NH-only, RGI region 19 skipped). Heroes take ESA WorldCover class 70, which the tiles **replaced** because permanent-ice-only left mid- and high-latitude ranges bare. **Access gotcha:** an Earthdata bearer token authenticates CMR granule downloads but *not* the NSIDC file pool, and RGI 7.0 is not granule-searchable at all → take it from the UNESCO IHP-WINS CKAN mirror.
- **Sea ice:** OSI SAF OSI-450-a v3.0 reduced to a 1991–2020 ice-frequency climatology (`render/seaice.py`), chosen over the NSIDC CDR purely on access — anonymous over met.no THREDDS, no token churn.
- **Boundaries:** Natural Earth. Borders are a white vector overlay, **never baked into raster tiles**; hero borders are composited in post, never rendered in the Blender scene. Worldview is NE default (de-facto) site-wide, disputed segments dashed, noted on the About page.
- **Mars, in full, is three:** the USGS **MOLA/HRSC blended DEM** at 200 m (elevation), **SIM 3292** (where the permanent polar ice is), and the **Viking colour mosaic** (the ice's brightness, and the hue the land ramp is measured from). No sea, no borders, no snow dataset — and the share-alike half of the blend's licence is why the whole site's output is CC BY-SA 4.0.

## Rendering decisions

- **Heroes:** headless Blender Cycles (bpy), RTX 4070 Super, OptiX backend + OpenImageDenoise — but **CPU denoise for 8K**, or render and denoise contend for the 12 GB VRAM and the driver throws an Xid 31 MMU fault.
- One scene rig for every country: DEM displacement, low sun, two-ramp material (elevation-keyed land, depth-keyed sea), ortho camera framed from Natural Earth bounds.
- **Vertical exaggeration belongs to the body** — 15× on Earth. The hero imports `palette.EXAGGERATION`, the tiles and caps read `Body.exaggeration`, and a test pins Earth's field equal to the constant; unpinned, the tiles drift away from the heroes they must match.
- **Tiles approximate the Cycles look:** single-NW hillshade (multidirectional rejected) + the hero's own fill sun ported across (`hillshade.combine_fill`) + sky-view factor from our own `sky_view.py` (WhiteboxTools dropped; the heroes burn it in post too) + the same ramps, composited with GDAL.
- **Cast shadows are the one light term the tiles do not have, and re-adding one is a REJECTED idea, not an open one.** `cast_shadow.py` is written, wired and shipped at `shadow_strength` 0.0 — turned down twice on the look and the second time on the *mechanism*: attenuating the main sun scales light amplitude, and fine detail amplitude falls with it, so any such shadow erases the modelling it carries. Reopening needs a different mechanism, not a different number.
- **Tile depth belongs to the body too** — `Body.tile_max_zoom`, z8 on Earth and z7 on Mars. **Earth's z8 is LOCKED**: z9/z10 are parked in FUTURE and blocked on disk — a planet re-fuse at ~2.5″, never a tiling flag.
- **Tiles are 512px**, declared to MapLibre as `tileSize: 256`, which centres the scheme on DPR 2. → FUTURE § raster tile resolution vs device pixel ratio
- **Delivery encoding is a policy, not one constant** — masters stay lossless, delivery does not. → ART § Delivery encoding · § The srcset ladder
- **Every writer records its recipe beside its output**, because existence cannot see a settings change.
- **A producer declares what it emitted; no consumer infers it from what is on disk.** A missing raster cannot distinguish "this body has none" from "the producer crashed", and an absent path scores nothing in an mtime comparison — so switching an input off leaves the output that used it looking fresh. `pipeline/planet_seam.py`.
- Baked NW-ish lighting globally (cartographic convention); no per-region sun position.

## Serving & deployment

- Tiles ship as **PMTiles**, ranged *server-side* into whole `z/x/y` tiles — the browser never opens the archive.
- **Cloudflare:** a site Worker over `web/dist`, R2 for archive/heroes/borders, and a separate tile Worker.
- **The tile Worker is mandatory, not stylistic** — Cloudflare caps a cacheable object at 512 MB, so a multi-GB archive can never be an edge object; the Worker turns range reads into ~40 KB tiles, which *are* cacheable.
- **Never let the browser send `Range` at a Worker** — Workers Caching strips the header and asks for the *full body*, i.e. the whole archive per tile. Request whole tiles by `z/x/y` and do the arithmetic inside, against an R2 binding.
- Everything is pre-rendered; no server-side compute at request time.

## Environment

- Blender 5.1.2, tarball at `~/software/blender-5.1.2-linux-x64/blender`, **not on PATH**. Render headless (`blender -b`) — the GUI OOMs at 8K.
- Pipeline Python is the uv-managed venv (`source .venv/bin/activate`); `uv sync` rebuilds it exactly, upgrades only via `uv lock --upgrade`. Blender's bundled Python is a **separate interpreter** — bpy scripts cannot import the venv's packages.
- Dev/render box: dual-boot desktop, RTX 4070 Super, 12 GB VRAM. **All work happens in the Ubuntu boot** — never suggest Windows paths, WSL, or PowerShell.
- **OptiX crash recipe:** `OPTIX_ERROR_UNKNOWN` at context creation → check `journalctl -k` for NVRM **Xid** lines; if the Xid's pid is Blender the driver is fine, just restart Blender to clear the dead CUDA context.
- **One heavy job at a time under a 16 G cgroup cap, no exemptions** — not for third-party tools, and not for an ad-hoc measurement either; the category that matters is "touches a full-planet raster", not "is a pipeline stage". `run_pass.sh` sizes the cap per body from `pipeline/profile/pass_cap.py`. 12 G is the value that failed: the shade pass invokes `cap_render` in its own cgroup, so a 12 G pass completed every tile stage and died at the last one. Keep project data and temp on ext4 — never tmpfs `/tmp`, never large rasters on NTFS.
- A separate home server runs the pipeline; it is not the site's origin. The site is served entirely from the CDN.
- **Keep intermediates out of backups.** INVENTORY.md is the storage map — current sizes, what each store feeds, and which are reclaimable.

## Working conventions

- Pipeline stages are **idempotent and resumable** — a crash at tile N must not restart the world. Cache intermediates, validate per stage.
- Python for pipeline code; boring debuggable scripts over frameworks. (Upheld on measurement, not taste: numpy releases the GIL, so threads reach the same ceiling xarray/dask would.)
- **Every gate stays at zero and there is no "pre-existing error" allowance.** From the root: `uv run pytest`, `uv run pyright`, `uv run ruff check` — pyright asks whether the types line up, ruff whether the code says what it means, and neither substitutes for the other. From `web/`: `pnpm test`, `pnpm lint`, `pnpm check` (which is `astro check` plus the worker's own tsconfig, since a second tsconfig is a second program the project check cannot see) and `pnpm check:test-collection`. rasterio call sites take a targeted `# pyright: ignore[reportCallIssue]`; GDAL creation-option dicts are `dict[str, Any]`.
- **Docs in this repo state current truth, not history** — if a row and reality disagree, the row is the bug. Dated decisions live in a decision archive kept outside the repo.
- **A learning goes where it will be met:** a fact about one function into that function's docstring, a general work heuristic into the agent's memory.
- **A second reader with no owner is the defect, and the KIND of thing is incidental** — a path, a procedure, a constant, a header, an explanation in a comment. With no home to import from, the second module copies, and *every copy is correct where it sits*: Natural Earth reached eight spellings of one path, all resolving identically on this machine, before `pipeline/naturalearth.py`; `download_one` reached two, and the copy drifted a timeout and a 404 branch, each exercised only by its own callers. **The trigger is "change one copy — what goes red?"** Nothing red means it needs an owner; where one owner is impossible — a latitude that must exist in Python and in TypeScript — make one copy executable so the drift fails loudly instead.
- **For an EXPLANATION that trigger is inert — nothing ever goes red — so ask "if this concept changed, how many places would I edit?"** `bodies.py` re-established *why there are three radii* at each radius field and again in its module docstring, and every copy passed the comment rule below on its own: a per-comment test cannot see a cross-comment property, which is why the bloat was invisible from inside and obvious to a reader. A concept gets one block; the sites that need it get one line pointing at it. Measure with `scripts/prose_report.py` rather than by eye — but as an instrument you run, never a gate, since a dense constants file is legitimately dense.
- **A comment explains its own subject and makes no claim that can rot behind its back.** The test: *could this sentence go false without anyone touching this function?* Counts, measurements taken elsewhere and system-wide properties all answer yes — they keep reading as specification long after they stop being true, which is how `composite_deps`' "eight look constants" and a test docstring's "53.8 min composite" each sent a decision the wrong way. Those belong in a test, in PROCESS.md, or nowhere; what stays is the concept, the context needed to read the code, and the anti-redo guard.
- **A superseded path is deleted the same day**, or moved out of the production package — prose calling it "retired" does not disarm a runnable entry point. Exception: under gitignored `data/`, where deletion is permanent.
- Never commit rendered assets or DEM data — code and config only.
- Plan first (Plan Mode) before any multi-file or architectural task.
- The other docs, so facts are looked up rather than re-guessed: **PROCESS.md** measured runtimes (the authority — read it before estimating), **INVENTORY.md** the storage map, **ART.md** the aesthetic decisions, **FUTURE.md** the v2 parking lot (check it before designing a "new" feature), **MARS.md** the standing brief for the second body (read it before touching a body seam), **docs/*.mmd** the pipeline diagrams.

## Skills context

- Assume no prior Blender experience in GUI sessions: give exact click paths, introduce UI vocabulary as it is used, and verify state with screenshots rather than assuming it.
- Local Blender is 5.1.2 and Claude's UI knowledge is 4.x-era — give 5.1.2 paths, and when uncertain say so and point at node search rather than guessing.
- Shader gotchas proven in 5.1.2, all of which produce plausible-looking wrong output rather than an error: 8-bit images are divided by 255 on load (export masks as 0/255); Map Range with reversed ranges is undefined (use Math Multiply + Clamp); ColorRamp stops re-sort by position, so never address one by index. The bpy edition is documented where it bites, in `scene_build.make_ramp`.

## Reference reading

Daniel Huffman, "Creating Shaded Relief in Blender" (the canonical technique) · MapLibre globe
projection docs · the PMTiles spec (Protomaps) · prior art for land/sea fusion: ETOPO 2022 (NOAA),
Tozer et al. 2019 (SRTM15+), GMT grdblend docs, Tom Patterson's shadedrelief.com.
