# Terrella — project memory

A static site of ray-traced relief maps, navigable as an interactive globe, covering every country
on Earth plus Mars as a second body.
The look sits in the tradition of Frank Ramspott's topographic renders: soft raytraced shadows,
heavy vertical exaggeration, warm sand land, desaturated teal sea with bathymetry, white vector
borders, minimal typography. The aesthetic decisions live in ART.md.

This file is the standing brief for anyone working on the repo, human or agent. It states current
truth only; it is not a changelog.

## Purpose — learning first (overrides efficiency)

This project is a vehicle for learning: the point is to understand every piece — DEM data, GDAL,
Blender/Cycles, tiling, MapLibre, serving — not to be handed a finished site.

- Where a choice has depth, present it rather than shortcutting past it.
- Docstrings welcome, inline comments only where necessary.
- Prefer the path that teaches over the path that merely ships. Slower is fine.
- Expect the plan to change as understanding grows; don't resist rework.

In the maintainer's own sessions with an AI assistant: be a **guide, not a workhorse**, explaining the why and involving the maintainer in the doing, and **Claude writes the code** while the teaching lives in chat. Neither says anything about outside contributions, which CONTRIBUTING.md covers and which are wanted.

## Check a claim before it ships

Six checks, each one earned by a wrong answer this project actually shipped into a conversation.
Run them on any measurement before it is reported, and on any value or plan before it is recommended.

- **Provenance.** Did I measure this, or read it somewhere? A cited fact is only about its own subject: "0.000% land above 84" was true, was about land, and was used to rule out shadows on the seabed.
- **Population.** Does one number cover a mixed population? A median over a sample that was 90% flat pack ice read -0.7 DN and hid a 19.2 DN swing on the ridges, which was the thing being asked about.
- **Instrument.** What else shapes this signal? An image gradient reports the terrain's grain, not the light's direction. Name the confound first, and give the instrument a control that must fail when the instrument is broken.
- **Range.** Am I outside where I measured? Scaling a 90 degree difference down to 15 degrees linearly predicted 3.7 DN; measured, it was 2.55.
- **Arbitrary.** Can I name the evidence for this exact value? "12 passes" had none and was offered as a recommendation anyway. Where there is no evidence, the sentence has to say so.
- **Set.** Does this claim quantify over a set: every consumer, the only producer, nothing else reads this, all the remaining work? Enumerate the set from code before the sentence ships. "Gating at the producer covers every consumer" was written after finding one of two, and "the cap raytrace needs this regardless" was written without walking the work list it claimed to depend on it.

## Architecture (decided — do not re-litigate without explicit discussion)

Three tiers of one site, one asset store, chosen by a client-side capability probe.

- **Tier 1 gallery** — static HTML + responsive hero images; the pessimistic default while the probe runs.
- **Tier 2 globe** — MapLibre globe projection over pre-shaded raster tiles; needs WebGL2. Pinned to an exact version in `web/package.json`, with one vendored patch (`patches/`, guarded by `vendoredPatches.test.ts`).
- **Tier 3 full** — Tier 2 + terrain-RGB displacement + the idle spin + the in-globe hero panel, gated on GPU tier and network. The panel loads the srcset rung that fits the card, never the 8K master.

Default pessimistic and upgrade optimistically; the Lite/Globe/Full toggle persists and beats the
probe; degrade at runtime if frame rate tanks; honour `Save-Data`, `prefers-reduced-motion`,
`prefers-reduced-data`.

## Data sources

`ATTRIBUTIONS.md` is the list: every dataset, what it does in the pipeline, and its licence, for both
bodies. This section carries only what shapes the architecture, and the acquisition gotchas are their
own skill (`.claude/skills/acquire-data/`).

- **Two rasters are fused and no others:** Copernicus DEM GLO-30 for land and GEBCO for bathymetry, into one seamless heightfield. The bathymetry is part of the signature look rather than an option. Everything else is warped onto the render grid at composite time and never enters the fusion master, which is why a finer re-fuse would not have to redo any of it.
- Lake beds are tint-only. A carved bed at 15x makes a crater of every lake and kills the flat plate that catches the surrounding shadows. Modelling every lake alike is deliberate: restricting to surveyed ones renders survey funding as geology, the discontinuity falling on the US/Canada border.
- Snow and glaciers differ between the two surfaces by decision rather than drift. Tiles take NSIDC-0791 persistence plus all nineteen RGI 7.0 regions with a latitude-ramped soft alpha, and Antarctica is painted white outright (persistence saturates there but leaves 9 to 14% of the land as clustered fill, which RGI's peripheral region 19 does not reach; it whitens the sub-Antarctic islands instead, where persistence has no observation at all). Heroes take ESA WorldCover class 70, which the tiles replaced because permanent-ice-only left mid- and high-latitude ranges bare.
- Borders are never baked into raster tiles. They are a white vector overlay, and hero borders are composited in post rather than rendered in the Blender scene. Worldview is Natural Earth default (de-facto) site-wide, disputed segments dashed, noted on the About page.
- Mars has no sea, no borders and no snow dataset, and the share-alike half of its blended DEM's licence is why the whole site's output is CC BY-SA 4.0.

## Rendering decisions

- **Heroes:** headless Blender Cycles (bpy), RTX 4070 Super, OptiX backend + OpenImageDenoise — but **CPU denoise for 8K**, or render and denoise contend for the 12 GB VRAM and the driver throws an Xid 31 MMU fault.
- One scene rig for every country: DEM displacement, low sun, two-ramp material (elevation-keyed land, depth-keyed sea), ortho camera framed from Natural Earth bounds.
- Vertical exaggeration belongs to the body, 15x on Earth. Every path that draws more than one body reads `Body.exaggeration`, the render seam included since it is the block prep's as well as the hero's; `palette.EXAGGERATION` is the authored constant the region preview still reads and a test pins Earth's field equal to it. Unpinned, the tiles drift away from the heroes they must match.
- **A body's tile look belongs to its producer, and `Body.planet_producer` is the seam.** Earth raytraces every tile block in Cycles, off the rig the heroes use. Mars composites, approximating that look with a single-NW hillshade (multidirectional rejected) plus the hero's own fill sun ported across (`hillshade.combine_fill`) plus sky-view factor from our own `sky_view.py` (WhiteboxTools dropped; the heroes burn it in post too) plus the same ramps, assembled with GDAL. `cap_pass.CAP_PRODUCERS` keys the polar disc's arm on that same field, so a body's caps and its tiles are never built by two different renderers.
- **Cast shadows are the one light term the COMPOSITE does not have, and re-adding one there is a REJECTED idea, not an open one.** Earth's raytraced tiles carry real ones; this is about the path Mars is still on. `cast_shadow.py` is written, wired and shipped at `shadow_strength` 0.0, turned down twice on the look and the second time on the *mechanism*: attenuating the main sun scales light amplitude, and fine detail amplitude falls with it, so any such shadow erases the modelling it carries. Reopening needs a different mechanism, not a different number.
- Tile depth belongs to the body too: `Body.tile_max_zoom`, z8 on Earth and z7 on Mars. **Earth's z8 is LOCKED**, since z9/z10 are parked in FUTURE and blocked on disk, needing a planet re-fuse at ~2.5″ rather than a tiling flag.
- Tiles are 512px, declared to MapLibre as `tileSize: 256`, which centres the scheme on DPR 2. → FUTURE § raster tile resolution vs device pixel ratio
- Delivery encoding is a policy rather than one constant: masters stay lossless, delivery does not. → ART § Delivery encoding · § The srcset ladder
- Every writer records its recipe beside its output, because existence cannot see a settings change.
- **A producer declares what it emitted; no consumer infers it from what is on disk.** A missing raster cannot distinguish "this body has none" from "the producer crashed", and an absent path scores nothing in an mtime comparison — so switching an input off leaves the output that used it looking fresh. Two tiers own this: `pipeline/planet_seam.py` for a body's planet rasters, and `pipeline/render/render_seam.py` for what fills one render directory. The second records **one entry per stage** because a country is filled by three that do not know each other's output, which is what lets an empty list say "I ran here and produced nothing" — the fact a missing file cannot carry. It is stdlib-only, since Blender's interpreter reads it.
- Baked NW-ish lighting globally (cartographic convention); no per-region sun position.

## Serving & deployment

- Everything is pre-rendered, tiles ship as PMTiles, and the site is served entirely from Cloudflare rather than from the box that runs the pipeline.
- The tile Worker, the R2 layout and the `Range`-at-a-Worker landmine are in `.claude/rules/tile-worker-and-delivery.md`, which loads whenever Worker or deploy code is opened.

## Environment

- Pipeline Python is the uv-managed venv (`source .venv/bin/activate`); `uv sync` rebuilds it exactly, upgrades only via `uv lock --upgrade`.
- Dev/render box: dual-boot desktop, RTX 4070 Super, 12 GB VRAM. **All work happens in the Ubuntu boot** — never suggest Windows paths, WSL, or PowerShell.
- Blender's own version, path, interpreter boundary and crash recipe are in `.claude/skills/blender-rig/`, which loads when a session touches the rig.
- **One heavy job at a time under a 16 G cgroup cap, no exemptions.** The category that matters is "touches a full-planet raster" rather than "is a pipeline stage", so third-party tools and ad-hoc measurements are in scope too. `run_pass.sh` sizes the cap per body from `pipeline/profile/pass_cap.py`, and a hook refuses an unwrapped heavy command.
- Keep project data and temp on ext4, never tmpfs `/tmp` and never large rasters on NTFS.
- A separate home server runs the pipeline and is not the site's origin.
- Keep intermediates out of backups. INVENTORY.md is the storage map: current sizes, what each store feeds, and which are reclaimable.

## Working conventions

- Pipeline stages are **idempotent and resumable** — a crash at tile N must not restart the world. Cache intermediates, validate per stage.
- Python for pipeline code; boring debuggable scripts over frameworks. (Upheld on measurement, not taste: numpy releases the GIL, so threads reach the same ceiling xarray/dask would.)
- **Every gate stays at zero and there is no "pre-existing error" allowance.** `./scripts/check.sh` from the repo root is the single place the list lives, and its header carries the order and the tool-by-tool reasoning. rasterio call sites take a targeted `# pyright: ignore[reportCallIssue]`; GDAL creation-option dicts are `dict[str, Any]`.
- Docs in this repo state current truth, not history: if a row and reality disagree, the row is the bug. Dated decisions live in a decision archive kept outside the repo.
- A learning goes where it will be met: a fact about one function into that function's docstring, a general work heuristic into the agent's memory.
- **Anything with two readers needs one owner**, and the kind of thing is incidental: a path, a procedure, a constant, a header, an explanation. Trigger: change one copy, what goes red? Nothing red means it needs an owner. Where one owner is impossible, such as a latitude that must live in both Python and TypeScript, make one copy executable so drift fails loudly.
- **For an explanation nothing ever goes red**, so ask instead how many places you would edit if the concept changed. One block owns a concept; every site that needs it gets one line pointing there. `scripts/prose_report.py` measures it, as an instrument you run rather than a gate.
- **A comment explains its own subject and claims nothing that can rot behind its back.** Trigger: could this sentence go false without anyone touching this function? Counts, measurements taken elsewhere and system-wide properties all can, and belong in a test, in PROCESS.md, or nowhere. Keep the concept, the context needed to read the code, and the anti-redo guard.
- A superseded path is deleted the same day, or moved out of the production package: prose calling it "retired" does not disarm a runnable entry point. Exception: under gitignored `data/`, where deletion is permanent.
- Never commit rendered assets or DEM data, code and config only.
- Plan first (Plan Mode) before any multi-file or architectural task.
- CONTRIBUTING.md is the entry point for anyone working here, human or agent: what runs without the render store, the one gate command, and the AI-assistance policy.
- Knowledge needed only sometimes lives in `.claude/skills/` when a TASK calls for it, or `.claude/rules/` when a matching FILE is opened. Neither belongs here, and content moves between them rather than being copied.
- The other docs, so facts are looked up rather than re-guessed: **PROCESS.md** measured runtimes (the authority, read it before estimating), **INVENTORY.md** the storage map, **ART.md** the aesthetic decisions, **FUTURE.md** the v2 parking lot (check it before designing a "new" feature), **docs/*.mmd** the pipeline diagrams. A body seam is read from `pipeline/bodies.py` and its web twin, which own every per-body fact between them.

Working in Blender, the 5.1.2 shader gotchas and the OptiX crash recipe are their own skill
(`.claude/skills/blender-rig/`), loaded when a session actually touches the rig.
