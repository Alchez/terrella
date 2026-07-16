# Terrella — living plan

Status legend: [ ] todo · [~] in progress · [x] done · [!] blocked
Update this file at the end of every work session (checkboxes + open questions + Active learnings).
Record dated decisions and their rationale in [`HISTORY.md`](HISTORY.md) — the chronological archive,
kept out of here so this plan stays lean across context compactions.

## Phase 0 — Proof of concept (one country, end to end)

Goal: a single Ramspott-style render of **India** that looks right, before building anything global.

- [x] Download Copernicus GLO-30 tiles covering India + margin (979 tiles, 60–100°E / 0–40°N, DEM + WBM, 34 GB — `pipeline/download_glo30.py`)
- [x] Download GEBCO bathymetry for the same extent (GEBCO_2026 GeoTIFF subset + TID, via download.gebco.net)
- [x] Fuse land + bathymetry into one seamless GeoTIFF heightfield — done at 3″ for the 66–99°E/4–38°N frame (pipeline/fuse_heightfield.py + ocean mask COG; recipe and oracles in HISTORY.md). 1″ runs deferred until small-country heroes / z9+ tiles.
- [x] Manual Blender scene: displacement plane, sun lamp, two-ramp material, ortho camera (blender/india_hero.blend — working recipe and debug lessons in HISTORY.md)
- [x] Iterate lighting/palette/exaggeration until it matches the reference aesthetic (2026-07-05 tuning session — rationale in HISTORY.md, constants in the locked section below; final judgment at 8K)
- [x] Add Natural Earth border overlay (white, ~like reference) + dashed maritime lines (2026-07-06 — pipeline/overlay_borders.py, oracle-verified alignment, cased poster-weight styling approved)
- [x] Render 8K still; review on both desktop and phone (2026-07-06, approved; 1 px dicing, 6.8 GB peak, CPU denoise)
- [x] **Checkpoint: lock the scene rig parameters (light azimuth/altitude, ramps, exaggeration) — these become global constants** (2026-07-06 — see "Locked global constants" below. Phase 0 complete.)

## Phase 1 — Batch hero renders (all countries)

- [x] Script the Phase 0 scene in bpy: load heightfield + the three masks (ocean/lake/river), frame ortho camera from a country bounding box (Natural Earth), render headless (blender -b — proven 2026-07-07: 3:36 @ 8K, 12.3 GB host). Complete 2026-07-08: frame_country.py → render_prep --frame → frame.json → scene_build --render, proven end-to-end on Nepal + Sri Lanka, India pinned (HISTORY.md; formulas in docs/framing-math.md).
- [x] Per-country config: bbox padding, camera framing overrides for awkward shapes (Chile, Indonesia, Russia, island nations). Complete 2026-07-09: config/countries.toml (scope 208 strict − 9 excluded + 5 curated includes = **204 heroes**; five mainland frame overrides; antimeridian markers) + pipeline/country_config.py resolver (frames, long-edge hero res, auto 1″/3″ fusion, GLO-30/GEBCO preflights, --emit-pin, --all audit) + India pin committed at config/frames/india.json (HISTORY.md; docs/framing-math.md + ART.md updated)
- [x] Per-country displacement Scale: the locked 15× is *physical*, and the plane is always 2 units wide, so Scale = 15 ÷ (frame width ÷ 2 in m) — the 8.0e-6 constant is India-frame-specific; computed per frame by render_prep.scene_numbers into frame.json since 2026-07-08 (Nepal 3.33e-5, Sri Lanka 1.00e-4 — docs/framing-math.md)
- [x] QA small rugged countries (Switzerland-class) for "bumpy" over-detail (2026-07-08 three-arm A/B: no bumpiness when warp width ≈ render width — 1″ fusion adopted as the small-country standard, resolution bumping rejected for heroes; see HISTORY.md)
- [x] Snow/ice as a data mask + shadow legibility (2026-07-08: WorldCover class 70 via pipeline/snow_mask.py after render_prep, snow E8F1F6, fill sun + 12° sun, land ramp top de-whitened — full A/B evidence and dataset evaluation in HISTORY.md; Switzerland v2 + India v4 heroes re-rendered as confirmation)
- [x] Handle antimeridian-crossing countries (Fiji, Russia, NZ) explicitly. Complete 2026-07-09: a geometry premise-check killed the wrap-math — 4 of 5 (Russia/US/NZ/Fiji) have their land on one side of 180 → non-crossing mainland frame overrides (France mechanism); Kiribati deferred as a special-case (genuinely split). Code = a ±180 clamp in `pad_frame` (also fixes Tuvalu) + a 1-line `resolve()` guard. See HISTORY.md.
- [x] Batch runner: queue all ~195 countries, resumable, logs failures — canonical outputs blender/renders/heroes/&lt;workdir-slug&gt;.png (current look, no version suffix; history lives in renders/archive/ + HISTORY.md). Complete 2026-07-09: `pipeline/batch.py` (reuses `country_config`, subprocess-isolated, sequential, prep/render split default-prep, crash-safe filesystem resume, dynamic OOM defense, JSONL failure log — see HISTORY.md). Chose a Python runner over GNU `parallel` (needed the crash-safety + OOM logic; rendering is serial anyway).
- [x] Document hero regeneration + pipeline CLI usage (README or docs/), end of Phase 1 — the committed source (scene_build.py + country_config.py + countries.toml + frame.json pins) is the canonical, reproducible form; .blend scenes are regenerated from it, never versioned (HISTORY.md 2026-07-09). This is what a fresh clone or a contributor runs to reproduce any hero. Complete 2026-07-13: `README.md` — the operational entry point (env setup, once-per-machine data bootstrap, `batch.py` regeneration path, the stage table, and the hero→variants→borders→manifest→build asset chain). Anchored on `country_config.py --country <slug>` as the self-documenting command list rather than a frozen one; complements `docs/framing-math.md` (the geometry *why*).
- [x] Overnight render run on 4070 Super; QA pass over outputs. Command: `python -m pipeline.batch --through render --clean` (bootstrap runs first; ~500 GB of GLO-30 downloads on top of 285 GB used, `--clean` reclaims per-country intermediates; Russia alone is 4919 tiles). Pre-sweep readiness verified 2026-07-09: held countries are config-consistent, **no re-prep/wipe needed** — india & switzerland skip-done (approved heroes), srilanka re-rendered at 1s, bhutan/nepal consistent (nepal gains its Himalayan snow on the sweep render); khambhat is out-of-scope dev cruft the sweep ignores. Recommend one `--only <slug> --through render` proof render before the full sweep (already done for srilanka). **Complete 2026-07-13:** the v3 sweep finished — all ~203 in-scope heroes rendered (Kiribati deferred), every post-sweep bug closed (see the 2026-07-11 entry), and variants/borders/manifest current. This closes Phase 1.
- [x] Generate responsive variants (2K/4K/8K WebP) per country. Complete 2026-07-09: `pipeline/hero_variants.py` — GDAL WebP driver (no new dep), Lanczos-downscales each 8K hero PNG to long-edge 1920/3840/native WebP (q85) in `blender/renders/variants/<slug>-<longedge>.webp`, idempotent, downscale-only. Heroes are fully opaque (borders composite separately) so alpha is dropped → RGB. Full-res WebP ≈16× smaller than the PNG (srilanka 3.1 MB vs 51 MB), 2K sub-MB, no visible artifacts. Naming is by long-edge size-class (consistent tier across portrait/landscape); the Phase-3 frontend reads actual dims for the `srcset` width descriptor.

## Phase 2 — Global tile pyramid

**Scoped 2026-07-10 (toolchain + decisions):** ceiling **locked at z8** (~300 m/px; z9/z10 are additive
over the same mosaic+shading, so deferred until deep zoom is proven necessary). Toolchain audit found the
stack is almost entirely **GDAL, already installed** (`gdal raster tile` with WebMercatorQuad + min/max
zoom supersedes gdal2tiles; gdaldem hillshade/color-relief; gdalwarp/buildvrt; native MBTiles r/w). **GDAL
pinned to 3.13.1** (latest, 2026-06-05) for the production run via the official OSGeo GDAL container; apt on
Ubuntu 26.04 tops out at 3.12.2 and 3.13 adds nothing our recipe needs (its tiling headline just default-remaps
gdal2tiles→`gdal raster tile`, a path we already call directly), so the step-B prototype runs on the box's
3.12.2 — the prep sweep is unaffected either way (venv rasterio bundles its own GDAL, not the system one).
**Only one mandatory new dependency: the `pmtiles` CLI** (GDAL writes MBTiles but not PMTiles → convert as the
last step). **SVF/openness step — decided 2026-07-10:** our own `sky_view.py` horizon code (already the
production openness pass burned into every hero → palette-consistent by construction, no dep, learning-first).
WhiteboxTools was dropped (legacy); RVT (`rvt-py`, the community SVF specialist, but Python <3.12 so its own
env) is kept only as an optional one-off numeric oracle. color-relief ramp file to be generated from the hero `SEA_STOPS`/land arrays
(single source of truth). Tile storage mount on rohome is a **Phase 4 deploy concern** (build on the dev box,
ship the finished `.pmtiles`), not a Phase 2 blocker. Tuning loop + the raster-vs-Blender-tile fork
(open-Q below) both gated on a **frozen hero look**.

- [x] Toolchain locked (2026-07-10): `pmtiles` 1.31.0 = sole vendored tool (`pipeline/install_geotools.sh`); SVF via our own `sky_view.py`; **GDAL pinned 3.13.1** (OSGeo container for prod; prototype on apt 3.12.2). WhiteboxTools dropped as legacy.
- [x] Build planet-wide fused heightfield (chunked; will not fit in RAM). Complete 2026-07-13:
  `pipeline/fuse/fuse_planet.py` fuses the globe as 10x10-degree cells at 10" EPSG:4326 (matches
  z8 1:1 at every latitude), 12-wide subprocess runner. Antarctica deferred (`--skip-south -60`).
  Output: 540 chunks -> `data/work/planet/planet_{heightfield,oceanmask,watermask}.vrt` (12 GB,
  129600 x 54000, lat -60..90). Swept in ~15 min, 0 failures. See HISTORY.md.
- [x] Raster shading pipeline — single-NW hillshade + global SVF (`sky_view.py`) + shared land/sea ramps (`palette.py`), shaded natively in Web Mercator to match the hero family. Superseded the per-strip pass with one global streaming pass (`shade_planet.py`, 2026-07-14); see HISTORY.md.
- [x] Compare tiles vs the Cycles render — Nepal chunk + whole-planet mosaic confirm the raster composite reproduces the hero family (single-NW; multidirectional rejected). See HISTORY.md.
- [x] Global snow layer for tiles — NSIDC-0791 persistence (soft alpha, latitude-ramped 0.40@45°→0.60@63°) + RGI 7.0 glacier union (open IHP-WINS mirror), integrated into `shade.py` (`snow.py`) and shipped planet-wide. See HISTORY.md.
- [x] Cut 512px tiles, z0–8 — full planet pyramid built & serving on the globe (`shade_planet.py`: per-row `z=15/cos(lat)` hillshade → seamless + correct per-latitude exaggeration, global SVF; 62,177 tiles, 2026-07-14). The seamless refinements the first per-strip pass deferred all landed in this rebuild. (z10 later = a full re-fuse at ~2.5″, not a tiling flag.)
- [ ] On-globe tile judgment (now viewable at `/globe`) — confirm the refined look holds; restrain only enough to keep borders/labels legible and tame native-30 m noise at z8. Known deferred gaps to accept-or-fill: **Antarctica** (flat cap below −60°S) and **Greenland interior** (flat white where snow-persistence = 1 over smooth ice).
- [ ] **Caspian bathymetry — route it through GEBCO + the sea ramp.** The fusion consults GEBCO only where `ocean` (`fuse_heightfield.py:211`), and the Caspian is WBM class 2 with a −28 m surface, so `coastal_water` (`|land| ≤ 1`) never fires → the heightfield takes GLO-30's **flat lake surface**. Probed 2026-07-15: fused = −28.0 m at *both* the deep basin and the north shelf, while GEBCO holds **−464 m / −1026 m** there — the measured bathymetry exists and is thrown away, so the Caspian renders as a flat bright slab beside a bathymetric Black Sea. Fix = one rule absorbing it into `ocean`: `(wbm == 2) & (land < -5) & in_caspian_bbox(46.5,36.5→55.5,47.5)`. Everything downstream then flows with **no shading change** (oceanmask→sea ramp + `sea_lift`/`sea_shade`/`sea_svf`; `classify_water` reclassifies 2→1 so the flat-water branch stops catching it). Each clause earns its place: `wbm==2` gives the precise DEM shoreline (GEBCO's coarse 15″ coast never defines the edge; `min(geb,-1)` keeps shallow margins continuous); `land < -5` excludes the Mingevir Reservoir (+83 m); the **bbox is load-bearing, not laziness** — without it the rule catches the Dead Sea (−430 m, WBM lake, *no* GEBCO bathymetry) which would collapse to `min(geb,-1) = -1` and render as a flat bright slab (a regression). Uniquely cheap because the Caspian is below sea level *throughout*, so absolute elevation maps onto the existing sea ramp with no new ramp and no per-lake datum. Cost: re-fuse 4 cells (`e040_n30 e040_n40 e050_n30 e050_n40`, ~1.5 GB/worker, idempotent) → rebuild the 3 VRTs → re-shade → re-cut. **Re-fuse done 2026-07-15; the re-shade + re-cut are the remaining step** (deferred for free resources; run cgroup-capped — `systemd-run --user --scope -p MemoryMax=12G -p MemorySwapMax=0`; **12 G, not the 8 G used on 2026-07-15** — measured peak is 6.93 GiB *with* lake depth and 6.45 GiB without, so 8 G left only 19% headroom even before the lake layer; 12 G is 1.7× measured and still half the 24 GB free, so it kills the job not the box). No manual `rm` list is needed first: `shade_planet.py`'s freshness guard (2026-07-15) now sees the re-fused chunks and rebuilds the whole derived chain itself. It is a **full-planet pass, not a 4-cell one** (~0.15% of the raster changed; windowed patching was considered and rejected — → HISTORY.md), so batch it with `WATER_RGB` and ideally GLOBathy rather than paying for it twice. **Expected result is structure, not darkness** — median Caspian depth is only ~48 m, so it stays legitimately bright (lum 180 → 168 shelf / 152 mid / 146 deep vs Black Sea 129); the win is a flat slab becoming a shaded basin.
- [ ] Package as PMTiles (Phase 4 deploy step; gated on the look being final)
- [ ] (Stretch) terrain-RGB elevation tiles for Tier 3 displacement
- [ ] **General lake depth → GLOBathy (ACTIVE 2026-07-15).** Every lake *except* the Caspian and the Great Lakes is a flat slab — GEBCO carries real bathymetry for those two only. This is the *structural* half of the inland-water clash: the sea spans lum 126→191 by depth, so **no flat fill can ever close the gap** (`WATER_RGB`→`8EC6C4` moved it 184→180, imperceptible). **Architecture reversed 2026-07-15: a render layer, NOT a fusion channel** — depth is tint-only (`HISTORY.md` 2026-07-07: at 15× a carved Namtso is a 1.5 km crater and the shadow-catching plate dies), so it lives beside **snow**, warped at composite time, never in the master. Consequences: **no re-fuse**, **no HydroLAKES join** (it existed only to place basins vertically; nothing is placed) → **stays CC0**, and a future z10 re-fuse would not redo it. Rationale + the GLOBathy/3D-LAKES/GLDB evaluation → [HISTORY.md](HISTORY.md).
  - **Done:** acquired (`acquire/download_globathy.py`, figshare v1 pinned by size+md5, both CC0); extracted 83,357 rasters ≥10 KB → `work/globathy/lakedepth.vrt` (`acquire/extract_globathy.py`; Caspian excluded — it is watermask class 1 via GEBCO); lake ramp in `palette.py` (`LAKE_STOPS[0]` **derived from** `WATER_RGB` so it cannot drift); `render/lake_depth.py`; `shade.py` region path + `composite(depth=)` + `--knob lake_curve` (`off|linear|sqrt|log1p`). **Validated on Tibet + Baikal 2026-07-15 and approved:** log1p is the only usable curve (region p10–p90 spread 0.38 vs sqrt's 0.14 — sqrt is a no-op); today Baikal and Namtso are *the same pixel colour* despite 13× depth, now (75,131,145) vs (97,152,162).
  - **Pre-flight before the full pass — ordered, do not skip:**
    1. ~~**Wire `shade_planet.py`**~~ **DONE 2026-07-15** — one-shot `lakedepth_3857.tif` warp in `warp_inputs` (bilinear/Float32, deliberately outside the mask loop whose `-r near -ot Byte` is right for class codes and wrong for depth; warped once, not per window, because an 83k-source VRT re-reads every source on each touch), `depth=` threaded through `composite_planet`, masked to class 2 via `lake_depth.lakes_only`.
    2. ~~**Close the freshness guard**~~ **DONE 2026-07-15** — `LAKE_STOPS`/`LAKE_MAX_M` into `composite_params()`, `lakedepth_3857.tif` into the (now named + tested) `composite_deps()`. `lake_curve` needed nothing: it rides in KNOBS. **Rerun economics pinned by test:** an unchanged rerun skips everything; a ramp re-tune re-composites but does **not** redo the 31 GB height warp or the GLOBathy warp.
    3. ~~**Tests**~~ **DONE 2026-07-15** — `tests/test_lake_depth.py` (120 pass total): `LAKE_STOPS[0] == WATER_RGB` pinned (the drift class that started this thread), LUT endpoints + monotonic darkening, all three curves' range/monotonicity/endpoints, the measured log1p-beats-sqrt claim, `lakes_only`'s per-class masking incl. **the Caspian at unit level**, and `lake_curve=off` reproducing today's flat fill exactly. Each guard is shown to FAIL on a known-bad input (the 2026-07-06 blind-oracle lesson). Caught a real bug: **log1p did not clamp** to `LAKE_MAX_M` (harmless today only because `composite` clips, but one shallower-cap re-tune from indexing off the ramp).
    4. ~~**Measure composite RAM**~~ **DONE 2026-07-15** — real pipeline peak **6.93 GiB with depth / 6.45 GiB without** (`experiments/composite_ram.py` + a timed region render). Depth costs **+0.48 GiB**, not the ~1 GB predicted by summing temporaries. **The finding was that the 8 G cap was already too tight before this change** → raised to **12 G** everywhere it is cited as a recipe.
    5. ~~**Time the one-shot warp**~~ **DONE 2026-07-15 — RAN TO COMPLETION: `1:01:38`, peak RSS 2.18 GB, 310 MB, exit 0.** `lakedepth_3857.tif` is built and `.done`-stamped (grid byte-identical to `warp_inputs`', so it will **not** re-warp on the pass). Profiled with `perf`: the cost is **`GDALWarpNoDataMasker` 51%**, not the sources (`VRTComplexSource::RasterIO` **2.4%**) — the many-source VRT is a non-issue and re-tiling the 83 k striped sources would buy nothing. Rate is spatially non-uniform (polar band empty → fast; the 50–70°N lake belt → ~7× slower), so do not extrapolate from the first 20%. Full rationale + the `-multi`/`-wo NUM_THREADS`/`-wm` doc corrections → [HISTORY.md](HISTORY.md).
    - **Calibration verified on the warped planet raster** (the check the 2026-07-07 prototype lacked): Baikal 1638.3/1642, Tanganyika 1464.7/1470, Ladoga 229.7/230, Titicaca 279.1/281, Superior 405.5/406, Namtso 123.9/125 — **all within 1%**. The cone is calibrated where surveys exist *and* the warp preserved it.
    - **Follow-up, NOT blocking the pass, and deliberately NOT applied to it.** `-wo NUM_THREADS=ALL_CPUS` + `-wm` is what threads warp *computation* (`-co NUM_THREADS` only threads GTiff's DEFLATE; `-multi` explicitly does not thread computation). **Do not put these on the height warp in the coming pass**, for three reasons, in order of weight:
      1. **No baseline exists.** The 31 GB height warp has never been timed. Change its flags now and the result is uninterpretable forever — the pass is the one free chance to measure it, since it re-warps anyway.
      2. **The lake warp's profile does not transfer** (checked, not assumed): `GDALWarpNoDataMasker` was 51% *because* of `-srcnodata` on a 98%-nodata source, but `planet_heightfield.vrt` declares **zero** `NoDataValue` and the height warp passes no `-srcnodata` → that half cannot occur. And "17 threads, 16 idle" was a DEFLATE pool with only 310 MB to compress; height writes **31 GB**, so the already-set `-co NUM_THREADS=ALL_CPUS` may already be earning out. Its bottleneck is **unknown**.
      3. **The payoff is contingent on z10.** This warp only re-runs on a re-fuse. If z8 holds, there may never be another one and the work is worth ~0; if z10 lands it is 16× the pixels and worth a lot. Decide the ceiling first.
      → **Run the pass instrumented instead** (`/usr/bin/time -v` + a `perf` sample on the height warp): baseline *and* profile for free, then optimise with evidence. Also still untested: sources carrying **0** as fill rather than −9999 would need no masking at all (bilinear→0 at a shore is physically correct) — that one is real but is a GLOBathy source rewrite, and only pays on a re-extract. **Measure, don't predict** — five predictions were wrong on 2026-07-15, and a sixth ("the prize is the height warp") was corrected the same day.
    6. ~~**Caspian regression render**~~ **DONE 2026-07-15 — PASSES on all three counts** (`shade.py --cells e040_n30 e050_n30 --per-row-z`, 7281×4456). Measured over the **2,372,061 class-1 Caspian px**, selected by watermask (never by bbox — see the oracle note below):
       - **Routing:** every Caspian water px is class 1 → sea ramp. 1,794 px remain class 2 in the bbox (genuine small lakes, not the Caspian).
       - **Structure — the headline:** luminance p10/p50/p90 was **182.9 / 182.9 / 182.9** before (spread **0.0** across 2.37 M px: a *literal* flat slab) and is now **137.0 / 158.8 / 167.8** (spread **30.8**). The `before` is the same geographic pixels in `planet_rgb_v1.tif`, proven pixel-comparable (exact integer lattice offset; land correlates **0.9972**, mean |Δ| 2.7 lum = regional-vs-global SVF, not geometry).
       - **Tint:** **0 px** of lake depth reach `composite()`. Two independent guards: `lakes_only` zeroes depth wherever `watercode != 2`, *and* `composite` gates lake colour behind `water=(code==2)|(code==3)`, so a class-1 px cannot take lake colour even if handed depth.
       - Artifact: `data/work/tiles/caspian_check/caspian_before_after.png` (approved on phone).
       - **The region path is what made this runnable before the pass:** `reproject_cell` warps each cell straight from `CHUNKS/<name>/` with `-overwrite`, so it always reads the **re-fused** chunks. The **planet** path would have tested the old bug — `planet_tiles/water_3857.tif` is the pre-re-fuse mask (2026-07-14) and still reads **class 2** at the deep basin. The guard covers it (`height`/`ocean`/`water` all `stale=True` → re-warped by the pass), so no manual `rm` — but **do not read a planet-path result as a Caspian verdict until the masks have rebuilt.**
       - **RAM, learned the hard way:** the region path is **not windowed** — it composites the whole region at once, so cells are a direct RAM multiplier. Four cells (7281×9625 = **70 Mpx**, 2.1× the planet's 33.6 Mpx window) hit **~14.5 GiB** and were **OOM-killed by the 12 G cap** exactly as the morning's 6.93 GiB measurement predicts. Two cells = 32.4 Mpx ≈ the planet window and fit fine. The cap did its job: `constraint=CONSTRAINT_MEMCG` killed the job, not the box.
       - **Oracle note (cost two false alarms today):** a **bbox max is not a lake oracle** — it caught Iranian/lower-Volga lakes and reported a 92 m Caspian "leak" whose argmax was on land near Baku. And `lakedepth_merc.tif`/`lakedepth_3857.tif` on disk are the **raw, unmasked** warps; `lakes_only` is applied in memory (`shade.py:163`), so testing the *file* reports leaks that cannot reach a pixel. Select by watermask; test the contract, not the intermediate.
    - **Latent, NOT blocking (bites at z10 only):** `ocean`/`water`/`lakedepth` take their grid from `height_3857.tif` but none depends on it for freshness. A z10 re-fuse would re-warp height to a new grid while `lakedepth` stayed falsely "fresh" at the old dimensions. Fix is a dimension/bounds comparison, **not** an mtime dep (which would force a needless 62-min re-warp whenever height rebuilds to the same grid). → [HISTORY.md](HISTORY.md)
  - ~~**Then** batch the pass with the Caspian re-shade + `WATER_RGB`~~ **DONE 2026-07-16 — the batched
    pass ran (98 min, instrumented) and the mosaic is VERIFIED.** `planet_rgb.tif` (12 GB) carries
    GLOBathy lake depth + Caspian bathymetry + `WATER_RGB`, and is `.done`-stamped and fresh.
    Measured against a pre-registered known-bad (all lakes identical at `(141,197,195)` if depth never
    reached the pixels): **Baikal `(81,137,149)` vs Namtso `(100,155,164)` — 18.0 lum apart** where they
    used to be the same pixel; Tanganyika lands on Baikal (absolute, not per-lake, calibration);
    Caspian spread **0.0 → 30.8** over 2.37 M class-1 px. The planet and region paths agree to a
    decimal, an unplanned cross-check. → [HISTORY.md](HISTORY.md)
  - **[!] THE ONLY REMAINING STEP: cut the tiles.** `python -m pipeline.tile.shade_planet --tiles`
    (gdaladdo + `gdal raster tile` z0-8, ~62 k tiles; swaps `tiles/` and keeps `tiles_old/` as
    rollback). **The live globe still serves the PRE-Caspian, PRE-GLOBathy pyramid** built from
    `planet_rgb_v1.tif` — none of this work is visible until this runs. Deliberately gated on Rohan
    judging the mosaic first; everything upstream is fresh, so it is tiling only.
  - **Coverage is fine, measured:** GLOBathy reaches 71% of WBM lake px in Tibet / 99% at Baikal. Of the shortfall, ~31% is whole ponds with a **median size of 2 px** (no gradient possible at any threshold — lowering `MIN_BYTES` buys nothing) and ~69% is rim inside graded lakes (the HydroLAKES↔WBM mismatch), which is **invisible because the ramp starts at `WATER_RGB`** and reads as a shelf. 528 bodies carry 91% of lake pixels.
  - **Epistemics (measured, and load-bearing for the About page):** the *shape* is an invented cone for **all** 1.43 M lakes — on the Caspian, the one lake with both a survey and trustworthy GEBCO, it correlates just **0.53** and claims 155 m where the truth is <20 m. The *scale* is a real survey for only **647 of our 83,357** lakes (0.78%) — though **14 of the 15 deepest**. Restricting to surveyed lakes was tested and **rejected**: 84.7% of them are in the USA, so it would render survey funding as geology, with the discontinuity landing on the US/Canada border. Uniform modelled treatment is the deliberate choice; GEBCO is *not* a usable oracle for lakes (it claims Erie is 225 m; it is 64).

## Pipeline optimisation — ranked, measured 2026-07-16 (NOT started; nothing here is urgent)

From the instrumented pass (98 min wall, 114 min CPU, **1.16 of 16 cores averaged** — the pipeline is
~93% idle silicon). Full evidence → [HISTORY.md](HISTORY.md). **Every one of these is measured; the
three flag-level fixes that "obviously" should have worked all died on contact with a profiler**
(`-multi`, `-wm`/`-wo NUM_THREADS`, `-co NUM_THREADS`), so nothing below is proposed from analogy.

Ordered by (measured win) ÷ (risk × effort):

1. ~~**Hillshade → float32 + `window_rows=256`**~~ **DONE 2026-07-16. 932 s → 508 s (1.84×), 11.6 GB →
   2.03 GB (5.7×), and 99.9374% of 12.19 G pixels bit-identical vs the old output (0 px beyond 1 DN).**
   The speed-up was a free by-product of halving memory traffic; the stage is still 97% on one core.
   `tests/test_hillshade.py` added (suite 120 → 129) pinning dtype/equivalence/window-invariance —
   incl. the NEP-50 trap where a float64 `zfactor` silently upcasts the whole computation back.
   Full detail + the sun-altitude mistake that the oracle caught → [HISTORY.md](HISTORY.md).
   - **Cap consequence:** the RAM-critical stage is once again `composite()` at **6.93 GiB**, so the
     **12 G cap is back to ~1.7× the true peak** and the PLAN recipe is sound again. Before this fix it
     was 1.03× — sized off the composite while the hillshade quietly peaked higher.
2. ~~**Delete the color-relief stage**~~ **DONE 2026-07-16.** `composite()` takes elevation and applies
   the ramps via `palette.relief_lut` (17.6 KB). **color-relief 28.3 min → 0**; composite 44.3 → 53.8
   (+9.5, it now reads the 31 GB height rather than 1.6 GB of RGB) → **net −18.8 min**, and composite's
   peak RSS *fell* 6.93 → **6.24 GiB**. With the hillshade fix the pass is **~98 → ~72 min (−26%)**.
   Verified twice against independent pre-existing oracles: LUT vs gdaldem's own rasters (6/6 bands,
   zero px beyond 1 DN) and LUT-fed vs gdaldem-fed `planet_rgb` (3/3 bands, zero px beyond a
   **pre-registered** 2 DN). `ramp_{land,sea}.txt` are gone; LAND_STOPS/SEA_STOPS/LUT_STEP_M moved into
   `composite_params()` with three guard tests, or a ramp re-tune would have left planet_rgb falsely
   fresh. → [HISTORY.md](HISTORY.md)
3. **Warp snow + glaciers ONCE to the planet grid, not per window.** The composite forks **728
   subprocesses** (`gdalwarp` + `gdal_rasterize` per window × 364) costing **534 CPU-s (7.8%)**, and
   `gdal_rasterize` re-reads the whole RGI glacier vector every window (peak 1 GB RSS, ×363). The
   glaciers and the persistence grid are **static** — this is exactly the "warp once, read windows"
   treatment `lakedepth_3857.tif` already gets, and for the same recorded reason. Cheap; also deletes
   the `_sp_win.tif`/`_rgi_win.tif` update-mode footgun.
4. **Parallelise the composite across windows.** 44:20 and the windows are independent by construction.
   Gated on #1 and #3 landing (RAM per worker is the constraint, and #3 removes the fork storm). Only
   worth it after the cheap wins — do not start here.
5. **The `-srcnodata` → 0-fill lead on GLOBathy** (still the only *warp* optimisation with money in it):
   `GDALWarpNoDataMasker` is **51%** of the 62-min lake warp; sources carrying 0 as fill would need no
   masking (bilinear→0 at a shore is physically correct). Pays only on a re-extract. Not blocking.

### Experiments audit (2026-07-16)

Retired: **`sea_ab.py`** (subject locked at V1, its winning knobs *are* `shade.py`'s KNOBS, and both
stages it drove were deleted with color-relief) and **`ab_crops.py`** (India water Route A/B — shipped;
zero refs; did module-level I/O on a render that no longer exists, so it could not even import).
The bar both met: **broken + subject concluded + conclusion already in production + zero references.**

**Everything else stays, deliberately.** The other twelve all import cleanly, and this is a
learning-first project — a *working* experiment is the record of a decision (`resolution_bump`,
`snow_proto`, `tile_chunk`/`tile_recipe`, `lake_depth_prototype`, the khambhat pair). Retiring them
would trade a documented history for a tidier directory. Revisit only if one *breaks*.

- **`composite_ram.py`'s 6.93 GiB is STALE** — `composite()` takes elevation since the color-relief
  deletion. **The real pass now measures 6.24 GiB** (`/usr/bin/time -v`, 2026-07-16), so the 12 G cap is
  ~1.9x and remains sound — but the fixture should be re-run so it stops disagreeing with reality.
- **`pipeline/profile/`** (new): `sample_tree.py` / `watchdog.py` / `stamp.py` / `run_pass.sh` — the
  instrumentation harness. **Moved here from `data/work/_profile/` on 2026-07-16 because `data/` is
  gitignored**: the harness INVENTORY told the reader to "keep" was never tracked and would have been
  lost. Code in `pipeline/`, output in `data/`. Worth remembering as a rule, not an incident.
- **Four implementations of "side-by-side before/after crop"** existed at once (`ab_crops.py`,
  `lake_ab.py`, plus two written ad hoc during the Caspian and Tibet checks) — because it is the most
  repeated need in the project and nobody looked first. `lake_ab.py` is the survivor and the natural
  home: generalise it to `--left/--right` over any two rasters with a lon/lat bbox. **Same bug as the
  three below, in the tooling layer.**

**Should we commonify? Yes — and the evidence is that the SAME fix has now been applied at one call site
and missed at its siblings three separate times:**

| the fix | has it | missing it |
|---|---|---|
| float32 + small streaming window | `shade.composite()` | **`hillshade.per_row_zfactor_hillshade()`** (11.6 GB) |
| warp once to the planet grid, read windows | `lakedepth_3857.tif` | **`snow.warp_persistence` / `rasterize_glaciers`** (728 forks) |
| `-co NUM_THREADS=ALL_CPUS` | height warp, lakedepth warp | ocean/water warps, both color-reliefs |

These are not three bugs; they are one bug — **a per-call-site copy of a decision that should exist
once**. Proposed shape, smallest first (each is independently useful; do NOT do them as one change):
- **`pipeline/render/gdal_opts.py`** (or a constant in an existing module): one `GTIFF_CREATE` list.
  Trivial, removes the drift, and makes row 3 a one-line change forever. *Note the honest caveat: the
  profile says this flag is worth ~18% of color-relief and ~0 on the lake warp — commonify it for
  consistency, not for speed.*
- **A `stream_windows(src, rows, dtype)` helper** owning the window/halo/dtype policy that `composite`
  and `per_row_zfactor_hillshade` currently each hand-roll. This is the one with real money in it: it is
  what would have carried the float32 fix to the hillshade automatically in 2026-07-14.
- **A `warp_once(vrt, grid, out, resampling, dtype)` helper** behind `is_stale`, which `lake_depth`
  effectively already is and `snow` should be. Would collapse row 2 and kill the fork storm.

## Phase 3 — Frontend

Baked-vs-live rule (2026-07-07): too expensive to compute live → baked, always; depends on view state/interaction → live, always; otherwise context-dependent or variant-multiplying → live but pinned to authored constants; invariant and physics-coupled → baked. Live raster grading (dark mode) OK — it commutes with the look; runtime terrain exaggeration only in a narrow range — baked shadows don't move. User-exposed settings only where the user's context genuinely varies (quality tier, border toggle, motion).

**Phase 3 started 2026-07-10 — Tier 1 shipped (branch `feat/frontend`, git worktree `../maps-frontend`; merge to `main` later; all committed).** An Astro 7 static site under `web/`: a responsive gallery of country heroes, per-country detail pages, and an About page — all data-driven so they fill in as renders complete. Decisions:
- **Astro 7 + pnpm.** Self-hosted **Fraunces** display serif via the stable Fonts API (`_astro/fonts`, no runtime external requests); system sans + mono utility face. Component hierarchy: `Base` (shell + fonts + the floating, persistent border toggle) → `Masthead` (eyebrow + heading + optional back link + the elevation legend, per-page via props/slots) → `Legend` (the hypsometric ramp — the signature). Design tokens in `src/styles/global.css` (moved out of a component `<style is:global>` for reliable CSS HMR).
- **Assets are external, never bundled.** Hero WebP + border PNGs live in the render store: a dev-only Vite middleware in `astro.config.mjs` maps `/heroes/*` → `blender/renders/variants/`; in prod nginx serves the same path. The build only emits HTML/CSS/JS that references `/heroes/…` (tens of GB never copied into `dist`).
- **Manifest bridge:** `web/scripts/gen_manifest.py` reads `country_config` + scans the variant store → `src/data/countries.json` (name, continent, aspect, variant sizes, `hasBorder`). Re-run after each asset pass.
- **Borders:** `pipeline/gen_borders.py` (on `main`) draws the standalone transparent border layer + gallery-sized variants from prep outputs only (reuses `overlay_borders`' AEA→pixel mapping), independent of the render.
- **Responsive:** two width tiers — browse grid `min(2200px, 94vw)` with column-*width*-driven masonry (~6 cols at 2K → 1 on mobile); content pages `min(1500px, 92vw)`; prose kept to a readable measure; search capped 720px. Scoped component selectors must not collide with the shared `.legend`/`.card` (Astro `figure[data-astro-cid]` outspecifies a global `.legend` — scope to `.card figure`/`.stage figure`).

**POST-RENDER ASSET WORKFLOW** (run after tonight's `--through render --force` fills all 203 heroes): `python pipeline/hero_variants.py` → `python pipeline/gen_borders.py` → `python web/scripts/gen_manifest.py --repo <repo> --out web/src/data/countries.json` → `pnpm --dir web build`. Gallery + detail + border toggle then populate for every country (only india/srilanka/switzerland are live today).

No longer Phase-2-blocked — the pyramid exists. **Tier 2 globe + vector borders shipped 2026-07-14** (`feat/frontend`, `/globe` route; build notes → [HISTORY.md](HISTORY.md)). **Capability probe + auto-steer tier routing + Lite/Globe/Full toggle + FPS degradation landed 2026-07-14** — the three-tier selection is now wired end-to-end (gallery ⇄ globe); Tier 3's 3D displacement stays deferred (needs a terrain-RGB pyramid we haven't built — "Full" is currently globe + idle animation). Remaining Phase-3 tail: Tier 1 no-JS fallback + the deferred hero sea-sync. **Deploy is Phase 4.**

- [x] MapLibre GL globe over the raster pyramid (PMTiles source deferred to Phase 4)
- [x] Natural Earth borders as vector line overlay, with show/hide toggle (land-only; maritime deferred)
- [x] Border legibility over pale highlands/snow — strengthened casing into a soft dark halo (2026-07-14)
- [x] Country click → fly-to → in-globe hero panel (2026-07-14 — invisible NE country-polygon hit layer, authored-frame `fitBounds`, lazy hero panel honouring the border toggle; build notes → [HISTORY.md](HISTORY.md))
- [x] Globe experience polish — detail-page render zoom, starfield, elevation stat dropped; **sea rework (#3): V1 locked & LIVE 2026-07-14** (deeper tone + un-flattened seafloor; knobs baked into `shade.py`, `tests/test_palette.py` re-frozen to 85B9B7/3A6E7D @ 0/−6000, palette/ART updated). Winner **z0-8** re-cut from the already-baked `planet_rgb_v1.tif` into the live `tiles/` (62,177 tiles; pre-rework set kept as `tiles_old` for rollback — reclaimed 2026-07-15). A/B toggle retired; comparison artifacts reclaimed (~39 GB, remainder 2026-07-15). Mobile polish 2026-07-14: control-collision fixed (bottom-right `.fab-stack`), border tiling de-jagged (`tolerance` 1.2→0.375 + `buffer` 256), attribution compact-collapsed + re-parented to float above controls on small screens. **2026-07-15:** capability probe + auto-steer routing + Lite/Globe/Full + **Spin** toggle shipped & committed (`feat/frontend` `a595ef9`, `c7eda66`). Spin = interaction-retires + toggle-restart; **resume-on-zoom-out is deferred** — a persistent-auto-rotate attempt broke MapLibre's render loop (re-entrant easeTo), reverted; redo via the official spin pattern only. **Spin option A shipped 2026-07-15:** above z3 the toggle is disabled + greyed ("Zoom out to spin"), re-enabled on zoom-out — fixes the dead-toggle confusion; auto-resume still deferred. All → [HISTORY.md](HISTORY.md)
- [ ] **Sync heroes to the reworked sea ramp** — the globe/tile sea look diverged from the Cycles heroes on 2026-07-14 (tiles = deepened, −6,000 m ramp in `palette.py`; heroes still the old 8FC7C5/−3,000 ramp in `scene_build.py`). **Do this once the tile pyramid is finalised** (i.e. after any z10 re-fuse / PMTiles decisions land — no point re-rendering ~204 heroes against a sea ramp that may still move). Port the tile `SEA_STOPS` + `SEA_MIN_M` into `scene_build.py`, re-render all heroes, regenerate variants/borders/manifest. Touches the frozen "Locked global constants" sea ramp → treat as a deliberate re-freeze.
- [x] Tier 1 no-JS fallback (2026-07-15) — the gallery already SSGs all 203 cards, so browsing needs no JS; the gaps were the dead search box + no find-by-name. Removed the search; added an atlas **gazetteer** (every country a link with its bbox-centroid coordinates, Fraunces letter-markers, A–Z rail) that **opens as a full-screen overlay** from the header "Index" link — pure CSS (`:target` opens, `:has(:target)` holds it open through letter-jumps), so it works with zero JS and Cmd/Ctrl+F searches it once open. Plus a `no-js`→`js` `<html>` class flip that hides the JS-only toggles (`.fab-stack`) without JS. Grid untouched. See HISTORY.md.
- [x] Capability probe + auto-steer tier routing (2026-07-14, `feat/frontend`) — `src/lib/capability.ts`: pure `decideTier(signals, quality)` (WebGL2 hard floor + software-GPU via `WEBGL_debug_renderer_info` / Save-Data / slow-network / low-memory / reduced-motion signals), TDD with 15 vitest cases. A pre-paint inline `<head>` guard steers capable visitors `/` → `/globe/` (and bounces incapable/Lite deep-links back) with no flash; probe-aware "Globe" link on the gallery. Build notes → [HISTORY.md](HISTORY.md)
- [x] Quality toggle (Lite / Globe / Full), persisted in `localStorage` (`rg:quality`) — a bottom-right control that overrides the probe and navigates to the chosen tier.
- [x] Runtime degradation hook on sustained low FPS — `globe.astro` watchdog samples frames while the map is moving and retires the idle spin below ~30 fps.
- [x] Respect Save-Data / prefers-reduced-motion / prefers-reduced-data — folded into `probeSignals()`: data pessimism → gallery; reduced-motion → globe (no idle spin); low memory → globe (skip full).

## Phase 4 — Deploy & polish

- [ ] nginx container on rohome, cache headers, PMTiles range-request config
- [ ] Pangolin route: maps.alchez.dev (or chosen subdomain)
- [ ] Lighthouse pass on all three tiers; test on a weak Android device
- [ ] About page: data credits (Copernicus, GEBCO, Natural Earth, ESA WorldCover — exact CC-BY string in the locked-constants Snow entry), technique notes
- [ ] (Optional flourish) landing-page "poster mode" beauty shot — Balazh-style sphere + water shell + atmosphere volume + perspective camera; a weekend experiment on existing data, decomposed in chat 2026-07-07
- [ ] Ship. Post it somewhere.

## Locked global constants (Phase 0 exit checkpoint, 2026-07-06; amended 2026-07-08 — snow / fill sun / sun angle / ramp top, see HISTORY.md)

Global for all ~195 countries. Changing any of these after Phase 1 starts means re-rendering every hero — treat as frozen; re-litigate only with explicit discussion.

- **Terrain:** vertical exaggeration 15× — Midlevel 0; Scale is per-frame unit conversion, `15 ÷ (extent_w/2 in m)`, computed by render_prep.py into frame.json (India's pinned 8.0e-6 is the hand-rounded instance — docs/framing-math.md).
- **Light:** Sun rotation (44°, 0°, −45°) → altitude 46°, azimuth NW; Angle 12°; Strength 3. Fill sun rotation (30°, 0°, 135°) → SE, shadowless (`use_shadow` off); Angle 10°; Strength 0.45 (15% of main). World fill `F2E7D5` @ strength 0.3.
- **Color:** View transform **Standard** (never AgX). Land ramp: heights 0→6,000 m on positions 0→1, stops E9D9C0@0 / D7AC8E@0.083 / CE9880@0.25 / C9AD97@0.5 / DCC9B2@0.75 / E9DCC8@1.0 — the top stays in the warm sand register; white/blue belongs to the snow mask alone. Sea ramp (**smooth-C, updated 2026-07-10** — re-litigated, see HISTORY.md; old was C6E4E2@0 / 98C5C8@0.15 / 649BA4@0.4 / 487D8A@1.0 which read as ice): depths 0→−3,000 m, 6 stops 8FC7C5@0 / 7CB8B8@0.10 / 68A6AC@0.22 / 56939E@0.38 / 47808F@0.62 / 3A6E7D@1.0 — shallow water a real teal. **This is the HERO ramp (`scene_build.py`) and is unchanged.** The TILE sea ramp (`palette.py`) diverged 2026-07-14 in the globe sea rework (V1 chosen): surface deepened ~15% and depth extended to −6,000 m so abyssal seas vary tonally — stops 85B9B7@0 / 73ABAB@0.033 / 68A6AC@0.133 / 56939E@0.333 / 47808F@0.633 / 3A6E7D@1.0 (see HISTORY.md). Heroes are NOT re-rendered to match yet — an open item. Snow `E8F1F6`, Mix between land ramp and Lake (water always wins). Masks 0/255 PNG, image nodes Non-Color, mask interpolation Closest, no reversed Map Ranges.
- **Snow data:** ESA WorldCover 2021 v200 class 70, warped nearest per frame by pipeline/snow_mask.py (permanent snow/ice only — the annual composite excludes seasonal snowpack by construction). CC-BY 4.0; About page must credit "© ESA WorldCover project 2021 / Contains modified Copernicus Sentinel data (2021) processed by ESA WorldCover consortium". No coverage of Antarctica (special-case hero regardless).
- **Camera:** orthographic, straight down; ortho scale = plane's larger dimension × 1.0006 (India: 2.06 over a 2 × 2.0588 plane); render resolution: 7680 px on the raster's *longer* axis, short axis from aspect (2026-07-09; `hero_long_edge` in config/countries.toml, per-country overridable — India pinned at its fixed-width-era 7680×7906; 2048-wide tests).
- **Render:** Cycles, OptiX backend, OIDN denoiser (GPU off for 8K frames — VRAM contention), adaptive subdivision dicing 1 px (≈6.8 GB peak at 8K).
- **Post-render shading (added 2026-07-10):** `pipeline/sky_view.py` — burn-only horizon sky-view-factor from `heightfield_aea`, darkens land valleys (strength ~0.38) for topographic depth so low-relief countries read; composited onto the hero by `batch.py` before the atomic promote; open ground and sea unchanged. Chosen over adaptive exaggeration + Cycles AO (HISTORY.md).
- **Borders (overlay, not scene):** land white 95% @ 10 px + casing #3D2B1F 35% @ 14 px; disputed/LoC dash [30, 20]; maritime white 80% @ 7 px + casing 25% @ 10.5 px, dash [40, 25]. Widths are 8K-canvas pixels; scale linearly with render width. NE default worldview.

## Open questions

Resolved questions move to HISTORY.md — one home per fact. Each question names the point where it gets decided.

- Tile shading: is pure raster compositing good enough, or render z0–z6 tiles in Blender for true shadows and switch to raster at higher zooms? **Decided at:** Phase 2's side-by-side step — judge one region's raster composite against its Cycles reference; the Blender-tile arm only gets costed if that comparison fails. (Prior-art audit 2026-07-09: the closest neighbour, LuisSevillano/relievo, colors its relief in gdaldem/Pillow *outside* Blender — exactly the raster-composite arm we plan for tiles — reinforcing that the hero=in-Blender / tile=GDAL-post split is the standard division, not an idiosyncrasy.) **First side-by-side 2026-07-13 (Nepal chunk `e080_n20`, shaded in Mercator): the raster composite reproduces the hero family cleanly → strongly leans raster; the Blender-tile arm is not needed pending the on-globe view with borders.**
- **Hero presentation — geography-conditional, not finalised** (explored 2026-07-09 spike; full findings + reusable machinery in HISTORY.md). The country-shape cutout was tried and generalised: cutout-cream suits continental/landlocked, real generous ocean suits genuinely water-surrounded (island) countries, but no single universal design holds (the trilemma: consistent / coherent / neighbour-free can't all hold at once). Two problems stay open: (a) most countries are *both* coastal and bordered (France, USA, India…) and need a tier-classification rule; (b) every treatment reads **flat at the country margin** (wants its own edge-depth pass). cutout-cream and everyone-island are post-processes of the tight renders (free); only the island real-ocean tier needs bigger-frame renders (cost path C). **Decided at:** Phase 3 gallery/globe design, once rectangular heroes exist to judge against; not a look change to the heroes, so it does not touch the locked constants.
- Storage location for the tile pyramid on rohome (which mount, backup exclusion). **Decided by:** the start of Phase 2 production runs on rohome, before the planet heightfield and pyramid (tens of GB) start landing on disk.
- **z8 vs z10 tile ceiling.** Locked at z8 (10″ master, 306 m/px). Going to z10 is **not a tiling flag — it's a re-fuse**: tiling the 10″ master deeper just upsamples (16× tiles, zero new detail); real z10 detail needs re-fusing the planet at **~2.5″ (76 m)** → 16× pixels → **~4 h fusion, ~190 GB master, ~16× the PMTiles (~2.5 → ~30–40 GB)**. (Native 1″/z11 = ~100× / ~1.2 TB, infeasible on current disk.) **Runtime on Tier 2/3 is unaffected** — MapLibre fetches only viewport tiles at the current zoom and PMTiles serves by HTTP range request, so a deeper pyramid is *crisper on zoom-in, not heavier to render*; the cost is build-time + hosting storage, paid once, and is **additive/deferrable** (add later by re-fusing finer, no frontend change). Mitigation if pursued: z10 **over land only** (per-region max-zoom; ocean has no detail to reveal) cuts ~16× toward ~5×. **Decided at:** after the z8 globe is viewable live — "z8 feels coarse" can't be judged until seen on the sphere (a full 10° cell shrunk to a 900 px panel reads coarser than z8 will on-screen). Resolution facts (our 512 px @2x): res(z)=78271.5/2^z m/px → z8=306, z9=153, z10=76, z11≈38 ≈ native 30 m (so GLO-30 native ≈ z11 here, z12 in the standard 256 px zoom numbering).

- **Prep-ahead producer/consumer runner (Phase 1.5 — timing, not correctness).** `batch.py` today
  serializes prep (stages 0–4: download/mosaic/fuse/warp/snow — network/CPU/disk, GPU-idle) with the
  render (stage 5 — GPU) per country, so the GPU idles during downloads. Measured on the 2026-07-09
  overnight sweep: **~9% GPU duty cycle** (≈15 min of rendering in ~2h49m; Canada's 6376-tile download
  alone idled the GPU ~40 min; renders themselves are only ~1–4 min each). The render is VRAM-locked
  to one-at-a-time (8K peaks ~11–12 GB of 12 GB) so *render must stay serial*; the win is **overlapping
  prep with render** (disjoint hardware). Design: **one render worker = the sole GPU lease**, draining
  a queue; **1–few prep workers** (network/CPU) staying N countries ahead. The "ready queue" is
  *implicit* — countries whose `render/`+snowmask exist but hero doesn't, discoverable by filesystem
  scan, so **resume stays filesystem-only (no durable queue state)**. Safety invariants that must NOT
  regress (crash-safety + the 2026-07-09 two-runner collision): (1) **single-instance `flock`** — refuse
  to start if another orchestrator holds it (the collision was exactly this missing guard); (2) **per-country
  claim** (atomic `mkdir data/work/<slug>/.claim`) so no two workers share a work dir (prevents the
  `--clean`-vs-fuse race that produced the `heightfield.tmp: No such file` errors); (3) **`--clean` stays
  post-render, done by the render worker only**; (4) atomic stage finalization unchanged; (5) **RAM-aware
  gating** — with prep+render concurrent, cap concurrent memory-heavy ops (≤1 fuse) and keep the render's
  MemAvailable pre-gate + cgroup cap, since a big fuse (GB) + a render (~12 GB host) can blow past 30 GB.
  Scheduling: **prep smallest-first** (by GLO-30 tile count) to fill the queue fast and never starve the
  renderer behind a giant download. Disk budget: queue depth N holds N un-pruned work dirs (up to ~4.5 GB
  each) → bound N by free space. Expected win: wall-clock → ~`max(total_prep, total_render)` instead of the
  sum (~2–4× on download-heavy runs). **Decided at:** after Phase 1 hero renders complete — do NOT build
  mid-sweep. Zero-complexity 90% alternative: the existing phase split (`--through prep` to completion,
  *then* `--through render` = pure GPU), which suffices if prep is allowed to finish first.


## Active learnings (tile pipeline — load-bearing gotchas)

Timeless notes that affect current/next work; full chronological rationale and superseded
approaches → HISTORY.md.

- **Planet tile shading is ONE global streaming pass** — `pipeline/tile/shade_planet.py`, not
  per-strip. Warp the 4326 planet heightfield → a single 3857 grid once, then global color-relief, a
  **custom per-row-z hillshade** (`render/hillshade.py`: z = 15/cos(lat) per row → the hero's
  physical 15× at every latitude, computed full-width with a 1-row halo so it is seamless; matches
  `gdaldem` to ≤1 DN), globally-normalised SVF, per-window composite. Supersedes the 194-strip
  `tile_planet.py`, whose single global z=20 blew out the tropics / flattened high latitudes and
  whose per-strip `--compute_edges` seamed the deep ocean.
- **The shade KNOBS were tuned on mountainous Nepal** and blow out flat *bright* terrain. `exposure`
  1.30 multiplied flat sunlit ground 1.15× and clipped pale-sand lowlands (Sri Lanka) to white →
  lowered to **1.05** (flat land renders ~1.0×, its true colour; mountains keep their punch because
  the shadow/highlight limits are `ambient`/`hi`, unchanged). Rule: validate any knob change on a
  *different terrain type* (bright lowland, flat ice sheet, high latitude), not just mountains.
- **Snow = observed persistence, not permanent-ice.** NSIDC-0791 persistence → latitude-ramped soft
  alpha + RGI 7.0 glacier union (`render/snow.py`), replacing WorldCover class-70 (left mid/high-lat
  ranges bare). Snow shadows must be **blue-white** (`palette.SNOW_SHADOW_RGB`), not a neutral
  `SNOW_RGB × light` — the latter turns rugged snow (Himalaya) into a grey smear while flat ice
  (Greenland) stays clean white.
- **`gdal raster tile` needs `--tile-size 512`** (its 256 default halves the 306 m/px master);
  tiling a many-source VRT re-reads every source per low-zoom tile and is far too slow → materialise
  to a tiled GTiff + overviews first, then tile that.
- **Mercator polar hole**: the raster stops at ±85.05°; MapLibre's globe smears the non-uniform edge
  row into a pole starburst → cap the edge bands flat deep-sea (>84°N, <−59.5°S). Antarctica (south
  of −60°) is still deferred; the south cap is a clean-disc placeholder.
- **WebMercatorQuad grid alignment**: warp the 3857 grid with `-tap -tr 305.7483` so pixels snap to
  the z8 tile grid — `20037508.34 = 65536 × 305.7483`; an unaligned grid seams the tiles or forces a
  resample. The planet grid is **131072 × 93009**, top 85.05°N, bottom −60°S.
- **GEBCO_2026 is ice-*surface* elevation, not sub-ice bathymetry** — the fusion "no-tile → ocean"
  rule would clamp Antarctica/Greenland ice to −1 m, so a proper Antarctica needs its own GLO-30 ice
  tiles as a special-case pass, **never a bathymetry clamp**.
- **The region path is NOT windowed — cell count is a direct RAM multiplier.** `shade.py --cells`
  composites the whole region in one shot, unlike `shade_planet.py`'s 256-row windows. The planet's
  window is 131072 × 256 = **33.6 Mpx ≈ 6.9 GiB**, so that is the unit: **~2 cells ≈ one planet window**
  (2 × 10° cells at mid-latitude = 7281 × 4456 = 32.4 Mpx). Four cells = 70 Mpx ≈ 14.5 GiB and gets
  **OOM-killed at the 12 G cap** (proven 2026-07-15). Scale cells by the cap, not by the map you want.
- **The two shade paths have opposite staleness exposure.** `shade.py` (region) re-warps from
  `CHUNKS/<name>/` with `-overwrite` every run → **always current**, which is why its missing
  skip-if-present costs nothing in correctness and why it is the right tool to validate a fresh re-fuse
  *before* a planet pass. `shade_planet.py` caches into `planet_tiles/` → **exposed by design**, which is
  what `is_stale` covers. A region render is therefore a valid early check; a planet render is only valid
  for whatever its cached inputs are actually fresh for.
- **Verification discipline — the one recurring bug is testing a PROXY instead of the thing.** It hit
  five times on 2026-07-15 and **every single one was in the checking, never in the pipeline**. The
  proxy is always the thing that is easier to reach and usually correlated, so it passes unnoticed:
  `pgrep -f` → the `/usr/bin/time` wrapper, not gdalwarp; a **bbox max** → any lake in the rectangle,
  not the Caspian; the **raw depth file** → the unmasked warp, not what `composite()` is handed;
  **`memory.current`** → page cache, not `anon`; and the **calibration oracle** → lakes where GLOBathy
  copies the published depth verbatim, so it could only ever agree.
  - **Hardened into code 2026-07-16: `pipeline/verify.py::compare_rasters`.** A written rule was not
    holding — instance #7 landed one message after the rule was written down. So the tool now makes the
    failure structural rather than remembered: every comparison returns the FULL histogram (shape is the
    diagnostic — precision noise centres on 0, a systematic offset does not), a WITNESS in lon/lat, a
    self-compare CONTROL proving 0 is reachable, and COVERAGE that labels a partial scan
    `!! PARTIAL SCAN -- this is a sample, not a proof`. **It cannot return a bare aggregate.**
    `tolerance` is passed IN, before the run, so the bar cannot be relaxed to fit the answer. It found
    both 2026-07-16 verdicts (hillshade, color-relief LUT). Use it for any raster A/B.
  - **The question that catches all five, asked BEFORE running the check:** *"what would this read if
    the thing I fear were NOT happening?"* If the answer is "the same", the check is worthless. Caspian
    clean → bbox max still says 92 m. Masking works → the file still holds nonzero. Job healthy →
    `memory.current` still parks at the cap. All three die on that question in one sentence.
  - **Call the production boundary.** The unit tests never had this bug and the scratch scripts always
    did — because tests call `lake_depth.lakes_only(...)`, the same function the pipeline calls, while a
    scratch script re-reads an intermediate file and eyeballs it. Verify by importing the real code path.
  - **Every aggregate must name its witness.** A max without an argmax is unfalsifiable: "92 m leak"
    survived exactly until the argmax placed it *on land near Baku*. max→argmax in lon/lat, count→an
    example, mean→the population it was drawn from.
  - **Why this is worth the ceremony, given the day's three false alarms were harmless:** they were false
    *positives*, which are cheap and self-correcting — you go look and find nothing. The identical
    mechanism with the sign flipped is a false *negative*, and one of the five already was one ("the
    calibration oracle passes", said twice, proving nothing). The 2026-07-06 blind-oracle bug was the same
    disease: a structural diff whose filter deleted the very lines the bug was in, so it passed on a
    broken scene. **A check that cannot fail is indistinguishable from a check that passed.**
- **Testing lake/water behaviour: select by watermask, and assert on the contract, not the file.** Two
  false alarms on 2026-07-15 came from proxies. (1) A **bbox max is not a lake oracle** — a rectangle
  around the Caspian catches Iranian and lower-Volga lakes and "finds" a 92 m leak whose argmax is on
  land near Baku. (2) **`lakedepth_*.tif` on disk is the RAW, unmasked warp** — `lakes_only(watercode)`
  is applied in memory (`shade.py:163`), so shore-lake bleed under bilinear looks like a leak in the file
  and is zeroed before any pixel sees it. Class-1 water is double-guarded: `lakes_only` zeroes the depth,
  **and** `composite` gates lake colour behind `water=(code==2)|(code==3)`.
- **The float32 + small-window fix was applied to `composite()` and NEVER propagated to the
  hillshade — which is the actual RAM-critical stage.** Measured 2026-07-15 in the instrumented pass:
  `per_row_zfactor_hillshade` still runs `window_rows=1024` and `.astype(np.float64)` →
  1024 × 131072 = **134 Mpx × 8 B = 1.07 GB per array**, and the gradient/slope/aspect temporaries
  stack on it → **anon sawtooths to ~11.6 GB against the 12 G cap** (95%), with the cgroup logging
  **122,501 reclaim events**. `composite()` by contrast is float32 @ 256 rows = 33.6 Mpx → 6.93 GiB.
  The hillshade uses **4× the rows and 2× the dtype width = 8× the bytes per array** — to produce a
  **uint8** output, so the float64 buys nothing. **The 12 G cap was sized from the composite's
  6.93 GiB (PLAN called it "1.7× measured"); against the hillshade's real 11.6 GB peak it is
  1.03×.** The cap was never wrong about the composite; it was measuring the wrong stage.
  → Fix = float32 + `window_rows` ~256; expect it to be *faster* too, since the reclaim thrash goes
  away. **This is the strongest argument for commonifying the streaming-window helpers**: one
  identical bug, fixed once in 2026-07-14's OOM postmortem, left live in the sibling function.
- **The planet composite is full-width, so window *height* is a hard RAM lever.** At 384 rows × 131072
  wide the float64 composite peaked ~18 GB (numpy compound-expression temporaries stack on the
  persistent arrays) and was **OOM-killed** on the 29 GB box under browser load (2026-07-14). Fix
  shipped: `composite()` computes in **float32** (halves every array) + `WINDOW_ROWS=256` (~6 GB);
  launch with `GDAL_CACHEMAX=512`.
