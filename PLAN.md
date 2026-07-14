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
- [ ] Package as PMTiles (Phase 4 deploy step; gated on the look being final)
- [ ] (Stretch) terrain-RGB elevation tiles for Tier 3 displacement

## Phase 3 — Frontend

Baked-vs-live rule (2026-07-07): too expensive to compute live → baked, always; depends on view state/interaction → live, always; otherwise context-dependent or variant-multiplying → live but pinned to authored constants; invariant and physics-coupled → baked. Live raster grading (dark mode) OK — it commutes with the look; runtime terrain exaggeration only in a narrow range — baked shadows don't move. User-exposed settings only where the user's context genuinely varies (quality tier, border toggle, motion).

**Phase 3 started 2026-07-10 — Tier 1 shipped (branch `feat/frontend`, git worktree `../maps-frontend`; merge to `main` later; all committed).** An Astro 7 static site under `web/`: a responsive gallery of country heroes, per-country detail pages, and an About page — all data-driven so they fill in as renders complete. Decisions:
- **Astro 7 + pnpm.** Self-hosted **Fraunces** display serif via the stable Fonts API (`_astro/fonts`, no runtime external requests); system sans + mono utility face. Component hierarchy: `Base` (shell + fonts + the floating, persistent border toggle) → `Masthead` (eyebrow + heading + optional back link + the elevation legend, per-page via props/slots) → `Legend` (the hypsometric ramp — the signature). Design tokens in `src/styles/global.css` (moved out of a component `<style is:global>` for reliable CSS HMR).
- **Assets are external, never bundled.** Hero WebP + border PNGs live in the render store: a dev-only Vite middleware in `astro.config.mjs` maps `/heroes/*` → `blender/renders/variants/`; in prod nginx serves the same path. The build only emits HTML/CSS/JS that references `/heroes/…` (tens of GB never copied into `dist`).
- **Manifest bridge:** `web/scripts/gen_manifest.py` reads `country_config` + scans the variant store → `src/data/countries.json` (name, continent, aspect, variant sizes, `hasBorder`). Re-run after each asset pass.
- **Borders:** `pipeline/gen_borders.py` (on `main`) draws the standalone transparent border layer + gallery-sized variants from prep outputs only (reuses `overlay_borders`' AEA→pixel mapping), independent of the render.
- **Responsive:** two width tiers — browse grid `min(2200px, 94vw)` with column-*width*-driven masonry (~6 cols at 2K → 1 on mobile); content pages `min(1500px, 92vw)`; prose kept to a readable measure; search capped 720px. Scoped component selectors must not collide with the shared `.legend`/`.card` (Astro `figure[data-astro-cid]` outspecifies a global `.legend` — scope to `.card figure`/`.stage figure`).

**POST-RENDER ASSET WORKFLOW** (run after tonight's `--through render --force` fills all 203 heroes): `python pipeline/hero_variants.py` → `python pipeline/gen_borders.py` → `python web/scripts/gen_manifest.py --repo <repo> --out web/src/data/countries.json` → `pnpm --dir web build`. Gallery + detail + border toggle then populate for every country (only india/srilanka/switzerland are live today).

No longer Phase-2-blocked — the pyramid exists. **Tier 2 globe + vector borders shipped 2026-07-14** (`feat/frontend`, `/globe` route; build notes → [HISTORY.md](HISTORY.md)).

- [x] MapLibre GL globe over the raster pyramid (PMTiles source deferred to Phase 4)
- [x] Natural Earth borders as vector line overlay, with show/hide toggle (land-only; maritime deferred)
- [x] Border legibility over pale highlands/snow — strengthened casing into a soft dark halo (2026-07-14)
- [x] Country click → fly-to → in-globe hero panel (2026-07-14 — invisible NE country-polygon hit layer, authored-frame `fitBounds`, lazy hero panel honouring the border toggle; build notes → [HISTORY.md](HISTORY.md))
- [~] Globe experience polish — detail-page render zoom + starfield done; elevation stat dropped; **sea rework (#3): V1 locked 2026-07-14** (deeper tone + un-flattened seafloor). V1 knobs baked into `shade.py` KNOBS, `tests/test_palette.py` re-frozen to the new sea endpoints (85B9B7/3A6E7D @ 0/−6000), palette/PLAN/ART updated. Winner **z0-8** re-cut from the already-baked `planet_rgb_v1.tif` (no re-composite needed — the A/B run left it with overviews) into `tiles_win/` (62,177 tiles, verified). **Next: go-live swap** `mv tiles tiles_oldsea && mv tiles_win tiles` on Rohan's OK. All scoped → [HISTORY.md](HISTORY.md)
- [ ] **Sync heroes to the reworked sea ramp** — the globe/tile sea look diverged from the Cycles heroes on 2026-07-14 (tiles = deepened, −6,000 m ramp in `palette.py`; heroes still the old 8FC7C5/−3,000 ramp in `scene_build.py`). **Do this once the tile pyramid is finalised** (i.e. after any z10 re-fuse / PMTiles decisions land — no point re-rendering ~204 heroes against a sea ramp that may still move). Port the tile `SEA_STOPS` + `SEA_MIN_M` into `scene_build.py`, re-render all heroes, regenerate variants/borders/manifest. Touches the frozen "Locked global constants" sea ramp → treat as a deliberate re-freeze.
- [ ] Tier 1 fallback: plain HTML gallery over the same hero images, country list/search
- [ ] Capability probe (~100 LOC): WebGL2 check → GPU tier (detect-gpu or renderer string) → network (Network Information API where present, else tile-timing)
- [ ] Quality toggle (Lite / Globe / Full), persisted in localStorage
- [ ] Runtime degradation hook on sustained low FPS
- [ ] Respect Save-Data / prefers-reduced-motion / prefers-reduced-data

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
- Caspian Sea routing (first frame that contains it): its surface sits at −28 m, so neither the ocean rule nor the land ramp handles it cleanly; check its WBM class and whether GEBCO already carries its measured bathymetry. **Decided at:** Phase 1 config of the first Caspian-bordering frame (Kazakhstan / Azerbaijan / Iran / Russia / Turkmenistan); the probe itself is a cheap fusion-window check and can run any time earlier.
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
- **The planet composite is full-width, so window *height* is a hard RAM lever.** At 384 rows × 131072
  wide the float64 composite peaked ~18 GB (numpy compound-expression temporaries stack on the
  persistent arrays) and was **OOM-killed** on the 29 GB box under browser load (2026-07-14). Fix
  shipped: `composite()` computes in **float32** (halves every array) + `WINDOW_ROWS=256` (~6 GB);
  launch with `GDAL_CACHEMAX=512`.
