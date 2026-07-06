# Relief Globe — living plan

Status legend: [ ] todo · [~] in progress · [x] done · [!] blocked
Update this file at the end of every work session. Record decisions in the log at the bottom.

## Phase 0 — Proof of concept (one country, end to end)

Goal: a single Ramspott-style render of **India** that looks right, before building anything global.

- [x] Download Copernicus GLO-30 tiles covering India + margin (979 tiles, 60–100°E /
      0–40°N, DEM + WBM, 34 GB — `pipeline/download_glo30.py`)
- [x] Download GEBCO bathymetry for the same extent (GEBCO_2026 GeoTIFF subset + TID,
      via download.gebco.net)
- [x] Fuse land + bathymetry into one seamless GeoTIFF heightfield — done at 3″ for the
      66–99°E/4–38°N frame (pipeline/fuse_heightfield.py + ocean mask COG; recipe and
      oracles in decision log). 1″ runs deferred until small-country heroes / z9+ tiles.
- [x] Manual Blender scene: displacement plane, sun lamp, two-ramp material, ortho camera
      (blender/india_hero.blend — working recipe and debug lessons in decision log)
- [x] Iterate lighting/palette/exaggeration until it matches the reference aesthetic
      (2026-07-05 tuning session — v2 constants in decision log; final judgment at 8K)
- [x] Add Natural Earth border overlay (white, ~like reference) + dashed maritime lines
      (2026-07-06 — pipeline/overlay_borders.py, oracle-verified alignment, cased
      poster-weight styling approved)
- [x] Render 8K still; review on both desktop and phone (2026-07-06, approved; 1 px
      dicing, 6.8 GB peak, CPU denoise)
- [x] **Checkpoint: lock the scene rig parameters (light azimuth/altitude, ramps,
      exaggeration) — these become global constants** (2026-07-06 — see "Locked
      global constants" below. Phase 0 complete.)

## Phase 1 — Batch hero renders (all countries)

- [ ] Script the Phase 0 scene in bpy: load heightfield, frame ortho camera from a
      country bounding box (Natural Earth), render headless
- [ ] Per-country config: bbox padding, camera framing overrides for awkward shapes
      (Chile, Indonesia, Russia, island nations)
- [ ] Handle antimeridian-crossing countries (Fiji, Russia, NZ) explicitly
- [ ] Batch runner: queue all ~195 countries, resumable, logs failures
- [ ] Overnight render run on 4070 Super; QA pass over outputs
- [ ] Generate responsive variants (2K/4K/8K WebP) per country

## Phase 2 — Global tile pyramid

- [ ] Build planet-wide fused heightfield (chunked; will not fit in RAM)
- [ ] Raster shading pipeline: multidirectional hillshade + sky-view factor (WhiteboxTools)
      + land/sea color ramps, composited to match hero-render palette
- [ ] Compare a tile region side-by-side with the Cycles render; tune until acceptable
- [ ] Cut 512px tiles, zoom 0–8 (extend to 10 later if quality/storage allows)
- [ ] Package as PMTiles
- [ ] (Stretch) terrain-RGB elevation tiles for Tier 3 displacement

## Phase 3 — Frontend

- [ ] MapLibre GL v5 globe with the PMTiles raster source
- [ ] Natural Earth borders as vector overlay layer, with show/hide toggle (gallery
      tier: stacked transparent border image over the hero, same toggle)
- [ ] Country click → fly-to → hero render view (lazy-loaded)
- [ ] Tier 1 fallback: plain HTML gallery over the same hero images, country list/search
- [ ] Capability probe (~100 LOC): WebGL2 check → GPU tier (detect-gpu or renderer
      string) → network (Network Information API where present, else tile-timing)
- [ ] Quality toggle (Lite / Globe / Full), persisted in localStorage
- [ ] Runtime degradation hook on sustained low FPS
- [ ] Respect Save-Data / prefers-reduced-motion / prefers-reduced-data

## Phase 4 — Deploy & polish

- [ ] nginx container on rohome, cache headers, PMTiles range-request config
- [ ] Pangolin route: maps.alchez.dev (or chosen subdomain)
- [ ] Lighthouse pass on all three tiers; test on a weak Android device
- [ ] About page: data credits (Copernicus, GEBCO, Natural Earth), technique notes
- [ ] Ship. Post it somewhere.

## Locked global constants (Phase 0 exit checkpoint, 2026-07-06)

Global for all ~195 countries. Changing any of these after Phase 1 starts means
re-rendering every hero — treat as frozen; re-litigate only with explicit discussion.

- **Terrain:** vertical exaggeration 15× — Displacement Scale `8.0e-6`, Midlevel 0
  (1 Blender unit = extent_width/2 meters; 15× assumes the India-frame scale — the bpy
  script recomputes Scale per frame as `15 × unit_in_meters⁻¹ × ... ` from first
  principles, see Phase 1).
- **Light:** Sun rotation (44°, 0°, −45°) → altitude 46°, azimuth NW; Angle 5°;
  Strength 3. World fill `F2E7D5` @ strength 0.3.
- **Color:** View transform **Standard** (never AgX). Land ramp: heights 0→6,000 m on
  positions 0→1, stops E9D9C0@0 / D7AC8E@0.083 / CE9880@0.25 / C9AD97@0.5 /
  E8DFD2@0.75 / F6F1E8@1.0. Sea ramp: depths 0→−3,000 m, stops C6E4E2@0 / 98C5C8@0.15
  / 649BA4@0.4 / 487D8A@1.0. Masks 0/255 PNG, image nodes Non-Color, mask
  interpolation Closest, no reversed Map Ranges.
- **Camera:** orthographic, straight down; ortho scale = plane's larger dimension
  × 1.0006 (India: 2.06 over a 2 × 2.0588 plane); render resolution from raster
  aspect (India: 7680×7906 final, 2048-wide tests).
- **Render:** Cycles, OptiX backend, OIDN denoiser (GPU off for 8K frames —
  VRAM contention), adaptive subdivision dicing 1 px (≈6.8 GB peak at 8K).
- **Borders (overlay, not scene):** land white 95% @ 10 px + casing #3D2B1F 35% @
  14 px; disputed/LoC dash [30, 20]; maritime white 80% @ 7 px + casing 25% @ 10.5 px,
  dash [40, 25]. Widths are 8K-canvas pixels; scale linearly with render width.
  NE default worldview.

## Open questions

- ~~Land/sea heightfield fusion~~ RESOLVED 2026-07-04 (see decision log): WBM ocean
  class as mask, hard splice, ocean clamped ≤ −1 m, no feathering. Confirmed by the
  Khambhat color test — naive fusion produces phantom land in macro-tidal seas; the
  clamp eliminates it and shading shows no seam either way.
- Exact palette hex values — sample from reference image or design fresh in the same spirit?
- ~~Disputed boundaries policy~~ RESOLVED 2026-07-06 (see decision log): Natural Earth
  default (de-facto) worldview, site-wide; disputed/LoC segments dashed; About page
  notes the choice.
- Tile shading: is pure raster compositing good enough, or render z0–z6 tiles in
  Blender for true shadows and switch to raster at higher zooms?
- Storage location for the tile pyramid on rohome (which mount, backup exclusion).
- Straight survey-boundary seam in GEBCO offshore W Khambhat (~72.5°E 21.7°N): sample
  the TID grid along it to identify the sources; decide whether it survives final
  color+light or needs local smoothing. Check whether it's widespread in our extent.

## Decision log

- 2026-07-06 (evening) — Overlay pipeline live (pipeline/overlay_borders.py). Coastline
  oracle passed: 74.5 / 91.1 / 93.8 % of drawn NE coastline within 2 / 5 / 10 px of the
  ocean-mask boundary at 8K, no directional bias in crops → the AEA→pixel mapping
  (including the ~2 px ortho-margin correction) is confirmed. Residual disagreement is
  NE 1:10m generalization vs our 30 m coast (Khambhat tidal flats, as predicted at
  design time). First borders composite: 59 solid / 17 dashed / 14 maritime features
  in frame; standalone transparent layer emitted alongside (gallery-toggle asset).
  Aesthetics still open: white-on-bone contrast over high pale terrain (halo/casing is
  the designated lever), maritime dash visibility to be judged on the 8K, and borders
  drawing over the flat no-data collar at the frame corners — that last one is really
  a Phase-1 framing/collar decision, not a borders bug.

- 2026-07-06 — Border overlay designed; worldview decided: **Natural Earth default
  (de-facto)**, site-wide — one editorial stance for all heroes (Kashmir must not
  change shape between the India and Pakistan pages); disputed/LoC segments get dashed
  styling; policy noted on the About page. Context: NE ships 31 national POV variants
  + an ISO variant, but only for the countries *polygons* — boundary *lines* exist in
  the default worldview only (a POV would be a filtering transform we'd own).
  Rendering route: **composite in post** (pipeline/overlay_borders.py, next) — with a
  straight-down ortho camera, draped-3D and flat-2D lines project to identical pixels
  (no parallax, no heightfield overhangs), so the scene route buys nothing; it was
  fully evaluated anyway (BlenderGIS import + Grease Pencil Dot Dash / Freestyle / GN
  dashing are all real) and rejected on iteration cost (re-render vs recomposite),
  GUI-add-on dependency in the headless Phase-1 batch, Freestyle perf vs diced
  terrain, and the frontend toggle needing a standalone transparent border layer
  anyway — which the compositor emits as a byproduct (gallery toggle = stacked <img>;
  globe tiers toggle their MapLibre vector layer for free). Alignment oracle: NE
  coastline rasterized onto the render grid must hug the land/sea color boundary
  (checks systematic offset; NE 1:10m is more generalized than our 30 m coast, local
  disagreement is expected and fine). Data downloaded (naciscdn.org, via
  pipeline/download_naturalearth.sh): boundary_lines_land, maritime_indicator,
  countries (Phase-1 camera bboxes), coastline (oracle). Styling classes from the DBF
  (field is uppercase `FEATURECLA` in this NE release — don't filter on lowercase):
  solid white = "International boundary (verify)"; dashed = Disputed / Line of
  control / Indefinite / Indeterminant frontier; maritime indicators all dashed per
  the reference look. Overlay stack (versions verified current on PyPI 2026-07-06):
  pyshp 3.1.4 + pyproj 3.7.2 + pycairo 1.29.0 — read/reproject/draw needs no
  geometric ops, so geopandas/shapely would be dead weight; fiona is unmaintained
  since 2024-09 (pyogrio succeeded it); cairo has native dashes/AA/RGBA and clips to
  canvas. pycairo builds from sdist and needs system libcairo2-dev + pkg-config.

- 2026-07-06 — First 8K hero render (7680×7906) completed **at 1 px dicing**, peak
  6.8 GB VRAM. Approved on desktop and phone (slight detail softening on phone =
  display downscaling, not a render defect). Claude's prediction that 1 px geometry
  wouldn't fit was wrong (per-quad memory overestimated; Max Subdivisions also caps
  effective dicing) — recorded so we trust the empirical peak, not the estimate. The
  morning's Xid 31 MMU fault is re-attributed, low confidence, to GPU render + GPU
  OIDN denoise VRAM contention at 8K (known failure pattern, blender/blender#119035;
  the failed attempt had GPU denoise on, the successful one had it off) → rule:
  denoise on CPU for 8K frames. Denoiser decision verified by research: OIDN beats the OptiX
  denoiser on detail preservation for final stills (community consensus; OptiX is a
  viewport tool); OIDN has a GPU mode since 4.1, but GPU render + GPU denoise can OOM
  on big frames → denoise on CPU for 8K. GPU debug lesson: OPTIX_ERROR_UNKNOWN at
  context creation right after a failed render = check `journalctl -k` for NVRM Xid
  lines; if the Xid pid is Blender, the driver is fine — restart Blender to clear the
  dead CUDA context. Version plan: finish Phase 0 and start the Phase 1 bpy script on
  5.1.2; pin 5.2 LTS (releases 2026-07-14) once out — its Cycles texture cache
  (`--command maketx`) and geometry-memory reduction target exactly our batch
  workload, and our API surface is untouched by 5.2's breaking changes (Geometry
  Nodes/paint APIs only). Verify the switch with an A/B test render against a 5.1.2
  reference before trusting it.

- 2026-07-05 — Tuning session → v2 look (supersedes v1 constants below). View transform
  **Standard**, locked — AgX's highlight desaturation greyed the palette; a map has no
  speculars, so filmic compression buys nothing. Exaggeration **15× (Scale 8.0e-6)**
  paired with **sun altitude 46° (X rot 44°)** — pairing math: shadow length ∝
  height × cot(altitude), so cot(new) = cot(old) ÷ exaggeration ratio holds drama
  constant while adding lowland micro-relief. Sun **angle 5°** (3° vs 5° invisible at 2K:
  penumbra ≈ shadow length × tan(angle), sub-pixel at test res — re-judge at 8K). World
  fill **F2E7D5 @ strength 0.3** (was default dark grey) — lifts shadow cores to warm
  brown, tints the backdrop paper-bone; raytraced analogue of Phase-2's sky-view factor.
  Land ramp rebuilt: **cap 6,000 m**, stops E9D9C0@0 / D7AC8E@0.083 / CE9880@0.25 /
  C9AD97@0.5 / E8DFD2@0.75 / F6F1E8@1.0 — rose peaks ~1,500 m then rises to bone/near-
  white (the Ramspott pale-highlands move); C68A76 retired as too heavy. Sea ramp
  unchanged from v1 (audited, no tweak needed). Sun strength 3, ortho scale 2.06
  unchanged. Remaining before the Phase-0 lock checkpoint: 8K render review on
  desktop + phone (incl. sun-angle re-judge), Natural Earth borders.
- 2026-07-05 — v1 look constants (pre-tuning baseline, all art-directable): exaggeration
  10× (Displacement Scale 5.3e-6 on the 2-unit plane); sun rot (55°, 0°, −45°), angle 3°,
  strength 3; land ramp cap 2,000 m, stops E9D9C0@0 / D7AC8E@0.25 / CE9880@0.5 /
  C68A76@1; sea ramp cap −3,000 m, stops C6E4E2@0 / 98C5C8@0.15 / 649BA4@0.4 /
  487D8A@1; ortho scale 2.06; test res 2048×2109, final 7680×7906; view transform AgX
  (default — A/B against Standard during tuning). Tuning agenda: pale high-Himalaya
  stop, exaggeration↔sun-altitude sweep, sun angle (shadow softness), world color/
  strength, view transform, then Natural Earth borders + 8K + lock constants.
  Reference renders: blender/renders/india_look_v1.png (canonical), *_check.png
  (accidental sun-angle drift — soft-shadow example, instructive to keep).
- 2026-07-05 — First full-look Blender render achieved (india_hero.blend). Scene recipe:
  plane scaled to raster aspect, Simple subdivision + adaptive dicing, heightfield as
  Float32 TIFF (Non-Color) driving Displacement (Midlevel 0, Scale 5.3e-6 = 10x), sun
  55° tilt / −45° azimuth / 3° angle / strength 3, ortho camera from above, two
  ColorRamps switched by ocean mask via Mix. Hard-won lessons for the bpy script:
  (a) Blender divides 8-bit images by 255 — mask must be exported 0/255 (PNG in
  render/), Float32 passes raw; (b) image nodes must be Non-Color, mask interpolation
  Closest; (c) Map Range nodes with any reversed range are undefined territory in
  5.1.2 — use forward ranges or Math Multiply+Clamp; (d) ColorRamp stops re-sort by
  position and renumber — never identify a stop by index; the final bug was a hidden
  5th pale stop that four index-walking verifications missed. Debug toolkit proven:
  binary mask test, independent numpy albedo oracle, base-resolution ASCII map,
  revert-to-baseline + minimal diff.

- 2026-07-04 — Render projection chosen: Albers equal-area conic for the India frame
  (+proj=aea +lat_1=10 +lat_2=32 +lat_0=21 +lon_0=82.5). Rationale: geographic degrees
  are E-W stretched (~5% at 21°N mid-frame, varying N-S); a conic with standard
  parallels ⅙ in from the frame's latitude edges keeps scale near-uniform, so the
  displaced terrain isn't anisotropically distorted. Per-country conic params will be
  derived the same way in Phase 1 (pipeline/render_prep.py). Heights stay in meters;
  exaggeration is a Blender-side constant.
- 2026-07-04 — Fusion rule refined after full-frame v1 spot checks: WBM classifies
  coastal lagoons and tidal channels as lake/river (Palk Bay patch = class 2; ~2,200 km²
  of sea-level "lakes" + ~8,000 km² of sea-level "rivers" in the India frame — Chilika,
  Kerala backwaters, Sundarbans). Rule is now: ocean = class 1 ∪ no-coverage ∪
  (class 2/3 with |elev| ≤ 1 m). High-altitude lakes unaffected. Never convert dry land.
  Spot-check oracles for any future fusion run: Delhi ~214 m, Everest ~8.7 km (3″
  averaging shaves the true 8,849 m peak), open Arabian Sea deeply negative, Chilika
  lagoon ≤ −1 m with mask = 1. Caveat learned the hard way: verify anomalies at the
  data's own pixel scale before calling them bugs — 79.7°E 9.5°N reads +0.6/land
  correctly (ESA maps an emergent tidal flat there; the water starts one pixel west).
- 2026-07-04 — Khambhat seam experiment (pipeline/experiments/fuse_khambhat.py), run on
  the adversarial macro-tidal case. Decisions (confirmed by the two-ramp color test,
  pipeline/experiments/color_khambhat.py — naive fusion renders phantom sand-colored
  land inside the gulf; hard clamp eliminates it):
  sea = WBM ocean class only (lakes/rivers keep the land surface; their water *tint* is
  a later material decision, not a fusion decision); hard splice with ocean clamped to
  ≤ −1 m; feathering rejected — no visible seam in multidirectional hillshade even here.
  Key learning: the naive fusion's failure mode is not shading but *coloring* — 3.2% of
  ocean pixels resolve ≥ 0 m (up to +18 m) and would key off the wrong end of a
  depth-keyed ramp. The −1 m clamp also makes sign-of-elevation a valid sea/land key for
  downstream materials (caveat: rare below-sea-level land like Kuttanad mis-keys; keep
  the mask COG as ground truth). Found a dead-straight GEBCO source boundary offshore
  W Khambhat — survey-grid seam, diagnose via TID (see open questions).
  Tooling: project .venv created (numpy, rasterio w/ GDAL 3.12) — needed for windowed
  raster passes.
- 2026-07-04 — Fusion reframed after prior-art check: land/sea DEM fusion is solved
  (ETOPO 2022 is the finished product at 15"; grdblend is the standard tool; the
  cartography community does this routinely). We proceed with our own fusion anyway —
  justified by 1" land detail for small countries and z9–z10 tiles, plus learning value —
  but treat it as method selection, with ETOPO 2022 as an external oracle for validation.
  Noted honestly: for a ship-it project, "use ETOPO 2022" would be the right call for
  country-scale renders (~370 m/px at 8K for India-sized framing).
- 2026-07-04 — Phase 0 data acquired. Extent locked at 60–100°E / 0–40°N (979 GLO-30
  tiles, half-open east/north edges). GEBCO_2026 (April 2026 release) chosen over 2025.
  Water-body masks (WBM) downloaded alongside DEMs as a candidate coastline source for
  fusion. Downloader is stdlib-only Python using the .part → verify → atomic-rename
  pattern; that pattern is the template for all later pipeline stages. Git initialized
  (code only; data/ ignored).
- 2026-07-03 — Project scoped in claude.ai conversation. Architecture, data sources,
  and rendering approach locked into CLAUDE.md. Phase 0 target: India.
- 2026-07-04 — Project purpose reframed: learning/understanding every piece is the primary
  goal; the shipped site is secondary. Claude acts as guide, not workhorse. Plan is
  expected to change significantly as understanding surfaces. (Recorded in CLAUDE.md.)
- 2026-07-03 — Dev environment decided: Ubuntu boot of the dual-boot desktop for all
  work (Blender + pipeline on one ext4 filesystem, native OptiX). Windows boot and WSL
  ruled out. Rohome remains deploy target and production runner for the tile pipeline.
  Constraint noted: overnight GPU renders occupy the desktop (no gaming those nights).
