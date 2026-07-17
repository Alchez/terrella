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

**COMPLETE 2026-07-13** — all ~203 in-scope heroes rendered (Kiribati deferred), variants/borders/manifest
current. Detail for every line below → HISTORY.md; the reproducible entry point is `README.md`.

- [x] bpy scene script — `render_prep --frame` → `frame.json` → `scene_build --render`, headless (3:36 @ 8K)
- [x] Per-country config — `config/countries.toml`, **204 heroes** (208 strict − 9 + 5 curated), `country_config.py` resolver
- [x] Per-country displacement Scale — the locked 15× is *physical*; computed per frame into `frame.json` (`docs/framing-math.md`)
- [x] QA small rugged countries — no bumpiness when warp width ≈ render width; **1″ fusion is the small-country standard**
- [x] Snow/ice as a data mask + shadow legibility — WorldCover class 70, fill sun + 12° sun, land-ramp top de-whitened
- [x] Antimeridian countries — a geometry premise-check killed the wrap-math: 4 of 5 have land on one side of 180 → frame overrides
- [x] Batch runner — `pipeline/batch.py`, resumable, subprocess-isolated, OOM defense, JSONL failure log
- [x] Document hero regeneration — `README.md`, anchored on `country_config.py --country <slug>` as a self-documenting command list
- [x] Overnight sweep + QA — the v3 sweep; every post-sweep bug closed. **This closed Phase 1.**
- [x] Responsive variants (2K/4K/8K WebP) — `pipeline/hero_variants.py`, ≈16× smaller than PNG, no visible artifacts

## Phase 2 — Global tile pyramid

**Scoped 2026-07-10:** ceiling **locked at z8** (~300 m/px; z9/z10 are additive over the same
mosaic+shading → deferred, see Open questions). Stack is almost entirely GDAL, already installed;
**GDAL pinned 3.13.1** for the production run (OSGeo container; apt tops out at 3.12.2, which is fine for
prototyping since venv rasterio bundles its own). **One new dependency: the `pmtiles` CLI** (GDAL writes
MBTiles, not PMTiles). SVF via our own `sky_view.py` — already burned into every hero, so palette-consistent
by construction. WhiteboxTools dropped as legacy. → HISTORY.md § 2026-07-10

- [x] Toolchain locked (2026-07-10) — `pmtiles` 1.31.0 vendored via `pipeline/install_geotools.sh`
- [x] Planet-wide fused heightfield — `fuse/fuse_planet.py`, 540 cells of 10° at 10″ EPSG:4326, 12-wide runner, 0 failures. Antarctica deferred (`--skip-south -60`)
- [x] Raster shading pipeline — one global streaming pass (`shade_planet.py`, 2026-07-14), superseding the 194-strip pass
- [x] Compare tiles vs the Cycles render — the raster composite reproduces the hero family (single-NW; multidirectional rejected)
- [x] Global snow layer — NSIDC-0791 persistence (latitude-ramped 0.40@45°→0.60@63°) + RGI 7.0 glacier union
- [x] Cut 512px tiles z0–8 — 62,177 tiles, 2026-07-14 (z10 later = a full re-fuse at ~2.5″, not a tiling flag)
- [x] **Caspian bathymetry via GEBCO + the sea ramp** — DONE: re-fused 2026-07-15 (`fuse_heightfield.is_caspian`), re-shaded in the 2026-07-16 batched pass. Flat slab → shaded basin, luminance spread **0.0 → 30.8** over 2.37 M px. → HISTORY § 2026-07-15 — Inland water
- [x] **General lake depth → GLOBathy** — DONE: a **render layer, not a fusion channel** (tint-only, so no re-fuse, no HydroLAKES join, stays CC0, and a future z10 would not redo it). Shipped in the 2026-07-16 pass; Baikal and Namtso were the same pixel colour, now 18.0 lum apart. → HISTORY § 2026-07-15 — GLOBathy lake depth
- [x] **CUT THE TILES — DONE 2026-07-17**, instrumented (`pipeline/profile/run_pass.sh --tiles`). 62,177 tiles live, `tiles_old` = rollback, exit 0. **Total 6:17** — the "30–60 min" this blocker carried was a guess and was wrong by ~10×. Verified at the pixel with a control (Caspian tile 100% >2 DN; Sahara 0.0%, max exactly 2 = the LUT noise floor). Rebuild: `bash pipeline/profile/run_pass.sh --tiles`. → HISTORY § THE TILE CUT LANDED
- [x] **`global_occlusion` guarded — DONE 2026-07-17.** SVF has no file to stamp, so it is gated by *laziness*: `composite_planet` takes a `Callable` and invokes it only past the freshness check. **A fully-fresh pass: 153.5 s → 0.29 s**; `--tiles` re-run 6:17 → ~3:45. Every stage in the pass is now guarded. → HISTORY § THE TILE CUT LANDED
- [ ] **`build_tiles` is now the only unguarded stage** — always re-cuts (3:44), since the staging dir is renamed away on success so `--resume` starts empty. Correct-but-costly; a guard would need to compare the pyramid against `planet_rgb`'s `.done`. → PROCESS.md
- [ ] **`--resume` does not verify** — a tile truncated by a kill is skipped, not repaired (docs-derived, unmeasured). The 07-15 cut *was* OOM-interrupted and resumed; verify before trusting a resumed pyramid. → HISTORY § the gdaladdo step DELETED
- [ ] On-globe tile judgment (`/globe`) — confirm the refined look holds. Known deferred gaps to accept-or-fill: **Antarctica** (flat cap below −60°S) and **Greenland interior** (flat white where persistence = 1 over smooth ice).
- [ ] **About page must carry the GLOBathy epistemics** — the depth *shape* is an invented cone for all 1.43 M lakes (correlates just **0.53** on the Caspian); the *scale* is a real survey for **647 of 83,357** (0.78%), though 14 of the 15 deepest. Uniform modelled treatment is the deliberate choice — restricting to surveyed lakes was tested and rejected (84.7% are in the USA → survey funding rendered as geology). → HISTORY § 2026-07-15 — GLOBathy lake depth
- [ ] Package as PMTiles (Phase 4 deploy step; gated on the look being final)
- [ ] (Stretch) terrain-RGB elevation tiles for Tier 3 displacement

## Pipeline optimisation — ranked, measured 2026-07-16 (NOT started; nothing here is urgent)

Baseline: 98 min wall, 114 min CPU, **1.16 of 16 cores averaged**. Everything here is measured — the
three "obvious flag" fixes (`-multi`, `-wm`/`-wo NUM_THREADS`, `-co NUM_THREADS`) all died on a
profiler, so nothing is proposed from analogy. → HISTORY.md § 2026-07-16 — the instrumented planet pass

**None of this speeds up the tile cut** (`build_tiles` shares no code with the composite). It pays on the
NEXT full shade pass, whose size depends on the deferred z9/z10 call — so the sizing input does not exist
yet. That, not effort, is why it is unstarted.

1. ~~Hillshade → float32 + `window_rows=256`~~ **DONE** — 932→508 s, 11.6→2.03 GB. → HISTORY § optimisation #1 landed
2. ~~Delete the color-relief stage~~ **DONE** — pass 98→72 min; ramps are now a 17.6 KB LUT. → HISTORY § optimisation #2 landed
3. ~~`num_threads="ALL_CPUS"` on the rasterio writers~~ **DONE** — **10.0× on the writer** (8.79→0.88 s), byte-identical output, no rebuild forced; ~6 min of the composite's 53.8 (upper bound), on the next pass. Three writers, not PLAN's two — `shade.py`'s region writer is the sibling. → HISTORY § optimisation #3 landed
4. **Warp snow + glaciers ONCE to the planet grid** — 728 forks, 7.8% CPU; also deletes the fixed-path `_sp_win.tif`/`_rgi_win.tif` temps, which are a hard blocker for #5.
5. **Parallelise the composite with `ThreadPoolExecutor`, ~4 threads** — *not* processes. Measured 2026-07-16 on real windows through `shade.composite`: numpy releases the GIL, so threads scale **1.80× @2 / 2.83× @4 / 3.57× @8**, using 3.54 cores at 4. Efficiency falls 90%→45% as memory bandwidth saturates, so **~3× is the ceiling and 4 threads is the knee** (54→~19 min). Threads need no IPC, no pickling and no per-worker GDAL handles — a `ProcessPoolExecutor` design was drafted and killed by this measurement. Gated on #4 (the fixed-path snow temps are not concurrency-safe). Read/write stay on the main thread; rasterio datasets are not thread-safe.
6. **`-srcnodata`→0-fill on GLOBathy** — `GDALWarpNoDataMasker` is 51% of the 62-min lake warp. Pays only on a re-extract.

**Commonify: yes.** The same fix has landed at one call site and been missed at its siblings **four**
times — float32+window (composite had it, hillshade didn't), warp-once (lakedepth had it, snow didn't),
`NUM_THREADS` (warps had it, writers didn't), and `# pyright: ignore` for rasterio's untyped
`Window` (fuse/render_prep had it, four new sites didn't). Plus four copies of A/B-crop tooling.
`GTIFF_CREATE` now has live evidence *and* a constraint: the 2026-07-16 `NUM_THREADS` fix took the **three**
tile writers and left three more unflagged — and **fusion's two must stay that way**, since `fuse_planet.py`
sets `GDAL_NUM_THREADS=1` on purpose (parallelism is across cells) and an explicit creation option would
override it. So the constant carries the **format** options only; **threading is per-call-site policy**, or
it silently oversubscribes fusion. → HISTORY § optimisation #3 landed
Smallest first, independently useful: a shared `GTIFF_CREATE` constant · `stream_windows(src, rows,
dtype)` (the one with real money — it is what would have carried float32 to the hillshade) ·
`warp_once(...)` behind `is_stale` · generalise `lake_ab.py` to `--left/--right`.

- **Experiments audit (2026-07-16):** retired `sea_ab.py` and `ab_crops.py` (bar: broken + subject concluded + conclusion already in production + zero refs). The other twelve stay — a *working* experiment is the record of a decision. → HISTORY § 2026-07-16
- **`composite_ram.py` measures `composite()` alone — a lower bound, not the pass** (re-measured 2026-07-16: 3.88 GiB no-depth / **4.50 with**, vs the pass's **6.24**; the ~1.7 GiB gap is readers/writers/GDAL cache and will never close). 12 G cap = 1.9× the real peak, sound. The old "6.93 is stale" line conflated two scopes. → HISTORY § composite_ram.py was never the number
- **Code in `pipeline/`, output in `data/`** — `data/` is gitignored, so the profiling harness that lived in `data/work/_profile/` was never tracked. Now `pipeline/profile/`. A rule, not an incident.

## Phase 3 — Frontend

**Tiers 1 + 2 shipped** on `feat/frontend` (git worktree `../maps-frontend`; merge to `main` later).
Astro 7 static site: gallery + detail pages + About + the `/globe` route, with a capability probe
auto-steering between them. **Tier 3's 3D displacement stays deferred** — it needs a terrain-RGB pyramid
we have not built, so "Full" is currently globe + idle animation. Architecture, the Astro/asset decisions
and the CSS gotchas → HISTORY § 2026-07-10 — Phase 3 begins. Asset commands → `docs/pipeline.md`.
**Deploy is Phase 4.**

**Baked-vs-live rule (2026-07-07, locked):** too expensive to compute live → baked, always; depends on
view state → live, always; invariant and physics-coupled → baked; otherwise live but pinned to authored
constants. User-exposed settings only where the visitor's context genuinely varies (quality tier, border
toggle, motion). → HISTORY

- [x] MapLibre GL globe over the raster pyramid (PMTiles source deferred to Phase 4)
- [x] Natural Earth vector borders + toggle (land-only; maritime deferred) — casing strengthened to a soft dark halo for legibility over pale highlands/snow
- [x] Country click → fly-to → in-globe hero panel (NE polygon hit layer, authored-frame `fitBounds`, lazy panel)
- [x] Globe polish — starfield, detail-page render zoom, mobile control-collision + border de-jag; **sea rework V1 locked & LIVE 2026-07-14**; **Spin** toggle (option A: disabled above z3, auto-resume deferred)
- [x] Capability probe + auto-steer tier routing + Lite/Globe/Full toggle + FPS degradation (2026-07-14/15) — `decideTier()` with a WebGL2 hard floor, TDD'd; pre-paint `<head>` guard steers with no flash
- [x] Tier 1 no-JS fallback (2026-07-15) — the gallery already SSGs all 203 cards; added a pure-CSS gazetteer overlay (`:target` / `:has(:target)`), removed the dead search
- [ ] **Sync heroes to the reworked sea ramp** — tiles and heroes diverged 2026-07-14 (tiles: deepened, −6,000 m ramp in `palette.py`; heroes: the old `8FC7C5`/−3,000 ramp in `scene_build.py`). Port the tile `SEA_STOPS`/`SEA_MIN_M` into `scene_build.py`, re-render ~204 heroes, regenerate variants/borders/manifest. **Gated on the tile pyramid being final** (z10/PMTiles) — no point re-rendering against a ramp that may still move. Touches the locked constants → a deliberate re-freeze. **Three more divergences ride on this same re-render, so fix them together:** (a) the hero/tile sun-altitude split (46° vs 45°); (b) **`WATER_RGBA` = `98C5C8` has drifted** — it is the *pre*-2026-07-10 sea ramp's 0.15 stop and matches no current stop, the identical bug fixed in the tile palette on 2026-07-15 (`WATER_RGB` → `8EC6C4`) but never checked on the heroes (found 2026-07-16); re-derive it from `SEA_STOPS[0]` and pin it **relationally**, or it drifts a third time; (c) hero lake depth — GLOBathy met the reopening bar the 2026-07-07 prototype was parked on, and the tiles took it while the heroes stayed flat (a parallel module, as `snow_mask.py` parallels `snow.py`). → ART.md § Inland water

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

- **z8 vs z10 tile ceiling — the big one; it gates the hero sea-sync, PMTiles, and every pipeline optimisation.** Locked at z8 (10″ master, 306 m/px). z10 is **not a tiling flag — it's a re-fuse**: tiling the 10″ master deeper only upsamples. Real z10 detail needs re-fusing at ~2.5″/76 m → **16× pixels, ~4 h fusion, ~190 GB master, PMTiles ~2.5 → ~30–40 GB** (native 1″/z11 ≈ 100× / ~1.2 TB — infeasible on current disk). **Runtime is unaffected** — MapLibre fetches only viewport tiles and PMTiles serves by range request, so a deeper pyramid is *crisper on zoom-in, not heavier to render*; the cost is build-time + storage, paid once, and is **additive/deferrable**. Mitigation if pursued: z10 **over land only** cuts ~16× toward ~5×. Resolution: res(z) = 78271.5/2^z m/px at our 512 px @2x → z8=306, z9=153, z10=76, z11≈38 ≈ GLO-30 native. **Decided at:** after the z8 globe is viewable live — "z8 feels coarse" cannot be judged until seen on the sphere.
  - **Latent bug this would trip (harmless at z8, bites the moment z10 lands):** `ocean`/`water`/`lakedepth_3857` take their grid from `height_3857.tif` but **none depends on it for freshness**, so a z10 re-fuse would re-warp height to a new grid while `lakedepth` sat falsely "fresh" at the old dimensions. Fix is a **dimension/bounds comparison, not an mtime dep** (which would force a needless 62-min re-warp whenever height rebuilds to the same grid). Fix before any re-fuse, not after.
- **Hero presentation — geography-conditional, not finalised.** The country-shape cutout was tried and generalised: cutout-cream suits continental/landlocked, real generous ocean suits island countries, but no single universal design holds (the trilemma: consistent / coherent / neighbour-free cannot all hold at once). Two problems stay open: most countries are *both* coastal and bordered (France, USA, India) and need a tier-classification rule; and every treatment reads **flat at the country margin** (wants its own edge-depth pass). Only the island real-ocean tier needs bigger-frame renders; the rest are free post-processes. **Decided at:** Phase 3 gallery/globe design, once rectangular heroes exist to judge against. Not a look change → does not touch the locked constants. → HISTORY § 2026-07-09 — Hero presentation explored
- **Storage location for the tile pyramid on rohome** (which mount, backup exclusion). **Decided by:** the start of Phase 4 deploy, before tens of GB land on disk.
- **Prep-ahead producer/consumer runner — designed, deferred, probably moot.** Would overlap GPU-idle prep with render (measured ~9% GPU duty cycle on the 2026-07-09 sweep). Its gate ("after Phase 1 completes") passed on 2026-07-13 with the sweep already done, and the phase split (`--through prep`, then `--through render`) is the zero-complexity 90% alternative. Design + the five safety invariants it must not regress → HISTORY § 2026-07-09 — Batch runner. **Decided at:** only if a full re-render sweep is ever needed again.

## Active learnings (tile pipeline — load-bearing gotchas)

One line each. Anything needing a paragraph belongs in HISTORY.md, not here — this section exists to be
scanned before touching the pipeline, not to archive evidence.

- **Planet tile shading is ONE global streaming pass** (`tile/shade_planet.py`): warp → per-row-z hillshade (z = 15/cos(lat), full-width, 1-row halo → seamless) → globally-normalised SVF → per-window composite. Supersedes the 194-strip `tile_planet.py`, whose global z=20 blew out the tropics and whose per-strip `--compute_edges` seamed the ocean.
- **The shade KNOBS were tuned on mountainous Nepal** and blow out flat *bright* terrain. Validate any knob change on a different terrain type (bright lowland, ice sheet, high latitude) — never only on mountains.
- **Snow = observed persistence, not permanent-ice** (NSIDC-0791 latitude-ramped soft alpha + RGI 7.0 union). Snow shadows must be blue-white (`palette.SNOW_SHADOW_RGB`); a neutral `SNOW_RGB × light` greys rugged snow into a smear.
- **`gdal raster tile` needs `--tile-size 512`** (its 256 default halves the 306 m/px master), and never tile a many-source VRT — it re-reads every source per low-zoom tile. Materialise a tiled GTiff + overviews first.
- **Mercator polar hole**: cap the edge bands flat deep-sea (>84°N, <−59.5°S) or MapLibre's globe smears the non-uniform edge row into a starburst. Antarctica below −60°S is still a deferred placeholder disc.
- **WebMercatorQuad alignment**: warp with `-tap -tr 305.7483` (`20037508.34 = 65536 × 305.7483`) or the tiles seam. Planet grid is **131072 × 93009**, top 85.05°N, bottom −60°S.
- **GEBCO_2026 is ice-*surface* elevation, not sub-ice bathymetry** — the "no-tile → ocean" rule would clamp Antarctica/Greenland ice to −1 m. They need their own GLO-30 special-case pass, never a bathymetry clamp.
- **The region path is NOT windowed — cell count is a direct RAM multiplier.** ~2 cells ≈ one planet window (33.6 Mpx); 4 cells = 70 Mpx ≈ 14.5 GiB and gets OOM-killed at the 12 G cap. Scale cells by the cap, not by the map you want.
- **The two shade paths have opposite staleness exposure** — `shade.py` (region) re-warps with `-overwrite` every run, so it is *always* current and is the right pre-flight check for a fresh re-fuse; `shade_planet.py` caches, so it is exposed by design and is what `is_stale` covers.
- **The freshness guard is blind to CODE by design** (params, not source, are the dependency — so `git checkout` cannot force a 33 GB rebuild). Any *behavioural* change to a shading kernel must therefore be verified against an oracle by hand.
- **`composite_params()` serialises KNOBS wholesale**, so anything changing its JSON marks `planet_rgb` stale and costs a ~54-min rebuild before `--tiles` cuts anything. Keep new tunables *inside* KNOBS (this is why `lake_curve` rides there, and why `shade.Knobs` is a TypedDict rather than a split-out constant).
- **The one recurring bug is testing a PROXY instead of the thing** — seven instances across 2026-07-15/16, and **every one was in the checking, never in the pipeline**. Ask *before* running any check: *"what would this read if the thing I fear were NOT happening?"* — if the answer is "the same", the check is worthless. Corollaries: every aggregate names its witness (a max without an argmax is unfalsifiable); call the production boundary, don't re-read an intermediate; import constants, never retype. Hardened into `pipeline/verify.py::compare_rasters`, which structurally cannot return a bare aggregate. → HISTORY § 2026-07-16
- **A check that cannot fail is indistinguishable from a check that passed.** False *positives* are cheap and self-correcting; the same mechanism sign-flipped is a false negative. Prove 0 is reachable before reporting 0.
- **One fix, one home.** A decision copied per-call-site has drifted four separate times. Fix it once or it rots at the sibling — see the commonification list above.
- **Retire a superseded path the same day: delete it, or move it out of the production package.** Prose calling it "retired" does not disarm an entry point. `tile_planet.py` sat in `pipeline/tile/` for two days after `shade_planet.py` replaced it, still runnable, still defaulting `--out` to the *live* `data/work/planet_tiles` — it would have cut tiles straight into the served pyramid with `--resume` and no rollback. It had also stopped being a faithful record, since `shade.py` drifted underneath it. git is the archive. → HISTORY § 2026-07-14 (overnight)
