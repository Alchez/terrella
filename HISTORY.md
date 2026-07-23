# Terrella — decision history

Chronological archive of decisions and their rationale, split out of PLAN.md on 2026-07-14 to keep the living plan lean. Newest first. PLAN.md's locked constants and open questions cite entries here for the *why*; append new decisions here, not in PLAN.md.

## Index — by topic

The log below is **chronological**; this is the view it lacks. Nothing reads this file whole (~51k tokens) — it is *grepped*, and the failure mode is not cost but **not knowing an entry exists**. Scan here, then jump to the heading. Entries are cited by heading, never line number: the log is newest-first, so every new entry shifts every line below it.

### Light & shading — the look itself
*The most re-litigated area in the project. Read before touching any lever.*

- [2026-07-20 — sea ice over bathymetry: OSI SAF chosen, the soft-frequency look, ICE_LO tuned decline-aware, and the recent-data check](#2026-07-20--sea-ice-over-bathymetry-osi-saf-chosen-the-soft-frequency-look-ice_lo-tuned-decline-aware-and-the-recent-data-check) — the sea-side mirror of snow: an **OSI SAF annual ice-frequency climatology** drapes translucent white over bathymetry, gated on `ocean`. **Anonymous OSI-450-a chosen over NSIDC V6 purely on access** (V5 dead, NOAA-Normals NH-only, Bremen/MODIS-AMSR2 short-record). Same-white + a notch cooler (not a bold blue split); `ICE_MAX_ALPHA=0.85` so bathymetry glows through; **`ICE_LO` 0.25→0.55 decline-aware**. **Recent OSI-430-a check: keeping 0.55 costs −4.2% extent = invisible** (the metric is winter-weighted; it can't show the Sept-minimum collapse). North cap rebuilt with ice + a baked dark coastline
- [2026-07-21 (night, later) — the hero/tile colour constants AUDITED at last, and three stale gates in PLAN corrected](#2026-07-21-night-later--the-heroTile-colour-constants-audited-at-last-and-three-stale-gates-in-plan-corrected) — **the hero sea-sync is NOT gated on the pyramid** (PMTiles is packaging; z10 is a planet re-fuse heroes never read) but on the shared **palette constants**, which have been frozen through six tile look changes. **Antarctica was never gated on the pyramid at all** — its snow-curve gate closed 07-17. **Real ordering: Antarctica's ice decisions → the hero sweep**, because `SNOW` is the one constant currently IN SYNC that Antarctic work could break. The long-requested colour audit ran: `LAND_STOPS` / land range / `SNOW` **MATCH**, the 3 diverged are the 3 already known → **no undiscovered fourth colour divergence**. **The audit's first run reported a FALSE divergence** (linear vs sRGB, `× 255` instead of the transfer function) — check the oracle's units before trusting its verdict
- [2026-07-21 (night) — cast shadows REJECTED A SECOND TIME, now on the mechanism: attenuating the main sun necessarily erases the modeling it carries](#2026-07-21-night--cast-shadows-rejected-a-second-time-now-on-the-mechanism-attenuating-the-main-sun-necessarily-erases-the-modeling-it-carries) — **`shadow_strength` stays 0.0**; re-run under the knee (which DID fix the 07-20 collapse-to-one-value) and rejected again. **Do not re-run this A/B without changing the MECHANISM:** `shaded *= (1 - strength * shadow)` scales the main sun, and fine detail is proportional to light amplitude, so it scales with it — **local** detail (5×5 high-pass) keeps only **68%, and 55% in full shadow**, predicted to within a point by arithmetic. **My "the fill is too soft" hypothesis was FALSE — the fill carries 88% of the main sun's fine modeling.** Also **8× the cost** of the composite knobs that shipped (+121% region, est. ~2.6 h planet pass at reach 300). **The metric lesson, third instance: a GLOBAL statistic cannot answer a LOCAL perceptual question** — my global std said 74% retained while the eye saw erasure
- [2026-07-21 (evening) — `shadow_warmth` 0.55 SHIPS: the hero's warm shadow floor, the first term ported by MEASURING the hero rather than reading its constants](#2026-07-21-evening--shadow_warmth-055-ships-the-heros-warm-shadow-floor-the-first-term-ported-by-measuring-the-hero-rather-than-reading-its-constants) — **`shadow_warmth = 0.55` is production** (Rohan, on `/globe`). A **misconstruction, not a mismatch**: our light is ONE SCALAR, so our shadows were *mathematically incapable* of differing in hue from our sunlight — the 07-17 port copied the hero's light GEOMETRY and never its SPECTRA. Measured on the raw Cycles frame: hero shadow is **+61…98% warmer in linear R/B** at matched elevation (monotonic across 10 deciles); ours was **exactly 0%**. The sky alone explains only 1.334× — the residual is **warm GI bounce**, which is *also why a greyscale SVF could never be the softness term*. `SHADOW_TINT` is **luminance-normalised so the knob moves HUE ONLY** (≤ +0.23 DN of brightness — structurally cannot re-create the rejected wash). Self-regulating like the fill: bright quartile **+0.0% on all four test terrains**; the ice margin does not seam. 1.0 rejected as too copper. Composite cost **+8%**
- [2026-07-21 (later) — the hillshade-side lever is DROPPED: its premise was consumed by the knee, and every hillshade dial turns out to be hero-anchored](#2026-07-21-later--the-hillshade-side-lever-is-dropped-its-premise-was-consumed-by-the-knee-and-every-hillshade-dial-turns-out-to-be-hero-anchored) — **`EXAG` 15, `alt` 45°, `fill_strength` 0.15 and the fill geometry are ALL ports of hero constants** → there is no unanchored hillshade dial; `fill_strength` 0.15 is the tile look's only principled anchor, so moving it breaks the anchor rather than turning a dial (table in ART.md § Hero → tile parameter map). Premise also **measured away**: under the shipped knee, sub-floor terrain gets **45%** of lit contrast, not 0%. Reframed to **which hero TERMS were never ported** — (1) cast shadows (built, off), (2) **a warm shadow floor — MEASURED on the raw Cycles frame: hero shadow is +61…98% warmer in linear R/B than lit ground at the same elevation** (monotonic across all 10 luminance deciles), while our composite's shift is **exactly 0% by construction**; `KNOBS["warmth"]` is NOT it (uniform, not light-keyed), (3) GI. **Never tune the heroes: they are the reference, and a change is 204 re-renders**
- [2026-07-21 — `ambient_knee` 0.30 SHIPS: the eye overruled every metric (again), and the test suite exposed how far the knee reaches](#2026-07-21--ambient_knee-030-ships-the-eye-overruled-every-metric-again-and-the-test-suite-exposed-how-far-the-knee-reaches) — **`ambient_knee = 0.30` is production** (Rohan, on `/globe`), overruling my metric-based 0.15. **Local-contrast std is now TWICE-FAILED as a proxy for softness** — and structurally so: the hard clip manufactures contrast at its own cliff, so softening it *scores* as a loss and *looks* like a gain. Never quote it as evidence about the look. The knee's reach is **global, not shadow-only**: fully-lit pixels rise **+4.9%** (flat water left `WATER_RGB`), the snow window's top saturated, and **no land pixel can sit AT `ambient` any more** (darkest light 0.5519 > `snow_lo` 0.55 — shaded snow survives on a 0.9%-of-ramp margin, pinned). Five tests broke on the flip, root cause `flat * light` no longer constructing a known light → the analytic inverse `conftest.hillshade_for_light`
- [2026-07-20 (evening) — chasing the hero's "softness" into the tiles: cast shadows land, occlusion is FALSIFIED, and the two shade paths were occluding at different resolutions](#2026-07-20-evening--chasing-the-heros-softness-into-the-tiles-cast-shadows-land-occlusion-is-falsified-and-the-two-shade-paths-were-occluding-at-different-resolutions) — **softness is bakeable (view-independent); crispness is a data ceiling; exaggeration already matches.** `cast_shadow.py` lands: one-azimuth horizon march, 12° penumbra from the sun's disc, attenuating the **main sun only** so shadows can't reach black. Iran A/B: pure black 0.000%, 7.45% of px moved, **inverts the Nepal trap** (no relief → no occluder). **Rejected at any strength**: the `ambient=0.50` clip is a **cliff at 90.2 DN** that flattens 6.21% of land (control spread std 36 DN → one value); 18.07% was *already* under it. **OCCLUSION FALSIFIED as the softness term** — 6-run sweep, local contrast moves the WRONG WAY (22.190→21.507); do not re-litigate. Also: the region and planet paths occluded **12.9× apart**, so every past region A/B judged a resolution production lacks → one `OCCLUSION_TARGET_M_PER_PX`; and the planet SVF's **missing `cos(lat)`** (2× at 60°N) is proven and unfixed. **`ambient_knee` (softplus) built + swept**: restores form inside the clamped 16.61% (std 8.24→10.76) but pays globally — **0.30 reproduces the rejected ambient-raise wash by another route**, 0.15 is the only defensible value; the real lever is hillshade-side (`fill_strength`/EXAG), not a composite tone curve. **COG overviews proposed then WITHDRAWN** on the 07-16 gdaladdo entry's own headline — the SVF is lazy-guarded, so it is not on the critical path. Storage for a future fine re-fuse: **transient bands, never a stored 496 GB product; remote COG is the wrong shape for a full sequential scan**
- [2026-07-17 — Greenland's interior is blank because the snow blend throws the hillshade away, and no linear window can fix it](#2026-07-17--greenlands-interior-is-blank-because-the-snow-blend-throws-the-hillshade-away-and-no-linear-window-can-fix-it) — over full snow `base_rgb` is **multiplied by zero** — all hillshade + SVF discarded; only `snow_t` survives. **17× dynamic-range mismatch, ranges NESTED → no linear window serves both.** Candidate: a non-linear `snow_curve` (precedent: `lake_curve`). **REMA/ArcticDEM is not the first lever.** Antarctica inherits this
- [2026-07-17 — the tiles were missing the hero's fill sun, and that was the "harshness"](#2026-07-17--the-tiles-were-missing-the-heros-fill-sun-and-that-was-the-harshness) — the tiles never got the hero's fill sun — a lone 45° sun at EXAG 15 left **43.7% of the Alps** at hillshade 0. **Do not raise `ambient` to soften: swept and rejected twice.** Every metric said otherwise and every metric was wrong
- [2026-07-08 (late night) — Snow/ice adopted as a data mask; shadow fill sun; land ramp de-whitened](#2026-07-08-late-night--snowice-adopted-as-a-data-mask-shadow-fill-sun-land-ramp-de-whitened) — **the fill sun's origin.** Ambient-raise tried and rejected — *washed rosy and flat*; the fill restored modeling. Snow adopted as a data mask; land ramp de-whitened. The entry that saved the 07-17 tile port
- [2026-07-14 (day) — Tile-shading rework: readable snow, exposure, seamless per-latitude relief, pole caps, float32/window RAM fix](#2026-07-14-day--tile-shading-rework-readable-snow-exposure-seamless-per-latitude-relief-pole-caps-float32window-ram-fix) — three distinct defects, three causes (do not conflate): readable snow, exposure, seamless per-latitude relief, pole caps, the float32/window RAM fix
- [2026-07-14 (night) — Sea rework (#3): levers 1+2 prototyped, **V1 chosen** (lock + winner z0-8 pending)](#2026-07-14-night--sea-rework-3-levers-12-prototyped-v1-chosen-lock--winner-z0-8-pending) — sea read as a flat tacked-on backdrop. **V1 chosen**: surface deepened ~15%, depth extended to −6,000 m so abyssal plains vary tonally
- [2026-07-10 — Hero look v3: shallow-sea ramp + sky-view shading; full re-run tonight](#2026-07-10--hero-look-v3-shallow-sea-ramp--sky-view-shading-full-re-run-tonight) — shelf seas rendered as white *ice* (Denmark/Ireland). Shallow-sea ramp + sky-view shading
- [2026-07-13 (night) — Snow source reworked: NSIDC-0791 persistence + latitude-ramped soft alpha (replaces WorldCover class 70)](#2026-07-13-night--snow-source-reworked-nsidc-0791-persistence--latitude-ramped-soft-alpha-replaces-worldcover-class-70) — **WorldCover class 70 is permanent ice, not seasonal snow** — replaced by NSIDC-0791 persistence + a latitude-ramped soft alpha
- [2026-07-14 — Snow integrated into shade.py; RGI 7.0 glacier union added and verified](#2026-07-14--snow-integrated-into-shadepy-rgi-70-glacier-union-added-and-verified) — snow into `shade.py` as production; RGI 7.0 glacier union added and verified
- [2026-07-18 — snow source re-confirmed (NSIDC-0791 stays); sea-ice parked for Antarctica](#2026-07-18--snow-source-re-confirmed-nsidc-0791-stays-sea-ice-parked-for-antarctica) — evaluated 5 alternatives; none beat NSIDC-0791 (daily MODIS/VIIRS are its ingredients; Copernicus SCE is operational; SAR-drift + MODIS-AMSR2 are **sea ice**). Finer-snow self-aggregation and a future sea-ice polar layer both parked; sea ice ties to the Antarctica decision
- [2026-07-18 — the polar cap: flat fails, and the pivot to a polar-stereographic custom-layer cap](#2026-07-18--the-polar-cap-flat-fails-and-the-pivot-to-a-polar-stereographic-custom-layer-cap) — **no flat cap colour works** (dark = hole, pale = plug; the problem is flatness, not hue — pale-C landed then rejected on the globe). Mercator can't reach >85° (pole → ∞); the fix is a **polar-stereographic cap from SOURCE data (reaches 90°) drawn via a MapLibre custom layer**, with sea ice over real bathymetry. Supersedes the baked-flat-Mercator-cap; both poles, ties to Antarctica. Feasibility PASSED (see Frontend index)
- [2026-07-19 — the cap's seam-match: light rotates with longitude, and the "glow" was a water-mask bug](#2026-07-19--the-caps-seam-match-light-rotates-with-longitude-and-the-glow-was-a-water-mask-bug) — cap light must ROTATE with longitude (tiles are true-NW everywhere) → `hillshade_array` gains a per-pixel azimuth, `cap = 315 − lon`. The "disc glow" was **not SVF** — a water-mask bug (`astype(bool)` caught **class-1 ocean** → flat `WATER_RGB` painted over the depth ramp); fixed by extracting the shared `lake_depth.inland_water`. Cap ocean now matches the tiles to **+0.5%**; leaving SVF off is vindicated. *Measure before prescribing: the mismatch was chromatic, which lighting cannot cause*
- [2026-07-05 — Tuning session → v2 look (supersedes v1)](#2026-07-05--tuning-session--v2-look-supersedes-v1) — **v2 look, supersedes v1.** View transform Standard locked — AgX's highlight desaturation greyed the palette
- [2026-07-05 — v1 look baseline (superseded by v2)](#2026-07-05--v1-look-baseline-superseded-by-v2) — v1 look — the pre-tuning constants, kept deliberately as the A/B baseline
- [2026-07-05 — First full-look render (india_hero.blend)](#2026-07-05--first-full-look-render-india_heroblend) — the first full-look render: the scene recipe (displacement, sun, two-ramp material)

### Inland water & lakes
*Lakes are their own problem: the sea ramp cannot see them (they sit at any altitude).*

- [2026-07-15 — GLOBathy lake depth: a render layer, not a fusion channel; and what the cone is actually worth](#2026-07-15--globathy-lake-depth-a-render-layer-not-a-fusion-channel-and-what-the-cone-is-actually-worth) — **GLOBathy adopted: a render layer, not a fusion channel.** Tint-only, never carve. Kills the HydroLAKES join → everything stays CC0. What the cone is actually worth
- [2026-07-15 — Inland water: the `WATER_RGB` drift, the Caspian probe (open question resolved), and the lake-depth dataset evaluation](#2026-07-15--inland-water-the-water_rgb-drift-the-caspian-probe-open-question-resolved-and-the-lake-depth-dataset-evaluation) — the `WATER_RGB` drift (an untracked colour relationship), the Caspian probe, and the lake-depth dataset evaluation. **GEBCO's Great Lakes data is broken** — Erie 225 m vs a true 64
- [2026-07-07 (later) — Lake depth: flat stays](#2026-07-07-later--lake-depth-flat-stays) — **lake depth: flat stays** — the v2 cone read well but was rejected as *an artificial gradient, epistemically worse than honest flat*. Bar for reopening: real modeled data (met by GLOBathy, entry above)
- [2026-07-07 — Inland water: full Route A (raster, in-scene); headless rendering becomes standard](#2026-07-07--inland-water-full-route-a-raster-in-scene-headless-rendering-becomes-standard) — full Route A — lakes AND rivers painted from the WBM in-material; vector hydro rejected. Headless rendering becomes standard

### Borders & worldview
*One editorial stance, site-wide. Politically load-bearing.*

- [2026-07-06 — Border overlay designed; worldview: NE default (de-facto), site-wide](#2026-07-06--border-overlay-designed-worldview-ne-default-de-facto-site-wide) — **worldview: Natural Earth default (de-facto), site-wide** — Kashmir must not change shape between the India and Pakistan pages. Disputed/LoC dashed
- [2026-07-06 (evening) — Overlay pipeline live; alignment oracle passed](#2026-07-06-evening--overlay-pipeline-live-alignment-oracle-passed) — overlay pipeline live; the coastline alignment oracle passed (74.5/91.1/93.8% within 2/5/10 px at 8K)

### Heroes — framing, batch, QA

- [2026-07-11 — Full v3 hero render sweep (COMPLETE 2026-07-13): 2 bugs found + post-sweep to-do — all resolved](#2026-07-11--full-v3-hero-render-sweep-complete-2026-07-13-2-bugs-found--post-sweep-to-do--all-resolved) — the full v3 sweep (204 countries): 2 bugs found, all closed
- [2026-07-10 — Overnight render sweep ran to 123/204, then STOPPED to fix hero quality; pipeline hardened](#2026-07-10--overnight-render-sweep-ran-to-123204-then-stopped-to-fix-hero-quality-pipeline-hardened) — the overnight sweep stopped at 123/204 to fix hero quality; pipeline hardened
- [2026-07-08 (night) — Switzerland QA: 1″ is the small-country standard; warp width ≈ render width is the anti-bump guard; resolution bumping rejected for heroes](#2026-07-08-night--switzerland-qa-1-is-the-small-country-standard-warp-width--render-width-is-the-anti-bump-guard-resolution-bumping-rejected-for-heroes) — **1″ is the small-country standard**; warp width ≈ render width is the anti-bump guard; resolution bumping rejected
- [2026-07-08 (evening) — Per-country framing live: frame.json is the contract; India pinned; oracle re-based to meters](#2026-07-08-evening--per-country-framing-live-framejson-is-the-contract-india-pinned-oracle-re-based-to-meters) — per-country framing live — `frame.json` is the contract; India pinned; oracle re-based to metres
- [2026-07-07 (evening) — Phase 1 keystone: scene_build.py rebuilds the hand-built scene from code](#2026-07-07-evening--phase-1-keystone-scene_buildpy-rebuilds-the-hand-built-scene-from-code) — **Phase 1 keystone**: `scene_build.py` rebuilds the hand-built scene from code, proven by three oracles
- [2026-07-09 — Batch runner: crash-safe orchestration + dynamic OOM defense](#2026-07-09--batch-runner-crash-safe-orchestration--dynamic-oom-defense) — batch runner: crash-safe orchestration + dynamic OOM defense
- [2026-07-09 — Antimeridian: no wrap-math; 4 mainland overrides + Kiribati deferred](#2026-07-09--antimeridian-no-wrap-math-4-mainland-overrides--kiribati-deferred) — antimeridian: **premise-check beat the scary version** — no wrap-math, 4 mainland overrides
- [2026-07-09 — Hero presentation explored (spike): no single universal design; geography-conditional; margins read flat](#2026-07-09--hero-presentation-explored-spike-no-single-universal-design-geography-conditional-margins-read-flat) — hero presentation spike: no single universal design; geography-conditional; margins read flat
- [2026-07-06 — First 8K hero approved; CPU-denoise rule; Blender 5.2 plan](#2026-07-06--first-8k-hero-approved-cpu-denoise-rule-blender-52-plan) — first 8K hero approved; **the CPU-denoise rule** (GPU render + GPU OIDN contend for 12 GB VRAM → Xid 31)
- [2026-07-04 — Render projection: Albers equal-area conic](#2026-07-04--render-projection-albers-equal-area-conic) — render projection: Albers equal-area conic, and why geographic degrees are wrong

### Tiles & the pyramid

- [2026-07-23 — the flat-pole taper RETIRED: `ice_relief_damp` treats at the source what the taper patched geometrically](#2026-07-23--the-flat-pole-taper-retired-ice_relief_damp-treats-at-the-source-what-the-taper-patched-geometrically) — the damp conceals the seafloor shading that fed the polar pinwheel wash, so the colat-3° geometric patch measured retirable (pole std 6.16 < annulus 6.70, no ring step, delta confined to the disc) and was **deleted the same day** — no pole special-case remains in either cap; both caps restaged themselves off the recipe change, and the shipped north cap is byte-identical to the measured A/B render
- [2026-07-22 — Antarctica FILL chosen over accept: extend the Mercator pyramid south, code landed, planet re-fused](#2026-07-22--antarctica-fill-chosen-over-accept-extend-the-mercator-pyramid-south-code-landed-planet-re-fused) — the Southern-Ocean ring Rohan saw is the **cap↔tile seam at −59.5°**, not the pole. Chose **fill over accept**: extend the pyramid to the −85° Mercator limit (93009→131072 rows, **1.41× every planet raster**), which moves the seam onto white interior ice AND gives Antarctica full tile resolution. **Cost is build-time + storage, NEVER the browser** (tiles are range-requested; the south cap PNG shrinks). Occlusion `cos(lat)` fix NOT bundled (Rohan). **Precondition FIXED**: the latent grid-freshness bug (`grid_matches`/`warp_needs_rebuild`) — four warp targets gated on source-only would sit falsely fresh when the grid grows. Antarctic land forced white via shared `snow.antarctic_snow_mask` (NSIDC is NH-only, RGI-19 excluded); SH sea ice toned (`seaice.SH_ICE_*`) to kill the halo; `CAP_SOUTH −84`. **Re-fuse DONE, probe-verified — after a stale-mosaic incident every gate was blind to (first attempt fused all of Antarctica as ocean). Same day: full re-shade+re-cut (2:28:01), cap shrink + re-source + freshness guards, and the polar ring ROOT-CAUSED as a custom-layer blending bug (straight alpha onto MapLibre's premultiplied framebuffer + canvas-alpha corruption) — it tracked the cap↔tile boundary, which is why it "moved" with the fill. FIXED, Rohan-confirmed — judgment COMPLETE the same night (north pole good, SH fringe right, blue-hole scan clean), fill rollbacks + the grid-dead gamma8 baseline reclaimed (~35 GB). One new look question — the Arctic pack slightly read as relief above the sea (the ice whites are light-keyed by the seafloor's hillshade) — answered the same night: **`ice_relief_damp` 0.75 shipped + ratified on `/globe`** off a five-rung cap A/B, thick pack calms while the fringe keeps relief and the depth-colour glow survives**
- [2026-07-20 — pipeline hardening: build_tiles guarded and cutting clean, plus the About page credits and lake-depth note](#2026-07-20--pipeline-hardening-build_tiles-guarded-and-cutting-clean-plus-the-about-page-credits-and-lake-depth-note) — **build_tiles was the last unguarded stage**: a `tiles.done` sentinel + `tiles_are_fresh` skip a fresh re-cut (`--tiles` re-run 3:33 → 0.4 s). **`--resume` dropped** — the cut wipes any partial staging and cuts clean, so a truncated png can't survive; the ≤3:44 re-cut on a crash is the price of integrity (chose *deleting* the unsafe path over an IEND-scan verifier). About page: NSIDC-0791 / RGI 7.0 / **GLOBathy (CC0, not the CC-BY the plan assumed)** credited + the lake-depth epistemics note
- [2026-07-17 — z8 LOCKED: the ceiling gate closed on the sphere, where it said it would be](#2026-07-17--z8-locked-the-ceiling-gate-closed-on-the-sphere-where-it-said-it-would-be) — **z8 locked** (Rohan, judged on `/globe`). Unblocks PMTiles + the hero sea-sync + the optimisation section's priority. z9/z10 stay additive/deferrable. **Carries the latent grid-freshness bug any future re-fuse would trip**
- [2026-07-17 — THE TILE CUT LANDED (6:17 total), and it was never the expensive stage](#2026-07-17--the-tile-cut-landed-617-total-and-it-was-never-the-expensive-stage) — **the tile cut landed** — 62,177 tiles, 6:17 total. Every estimate of this step was wrong in the same direction. `gdal raster tile` never reads source overviews
- [2026-07-15 — The staleness trap: freshness guards for the planet shading chain, and a 41 GB reclaim](#2026-07-15--the-staleness-trap-freshness-guards-for-the-planet-shading-chain-and-a-41-gb-reclaim) — **the staleness trap** — freshness guards for the whole shading chain, and a 41 GB reclaim. An exists()-only guard cannot tell *built* from *still correct*
- [2026-07-14 (overnight) — First full planet tile pyramid: snow + glaciers, z0–8, served & verified](#2026-07-14-overnight--first-full-planet-tile-pyramid-snow--glaciers-z08-served--verified) — first full planet pyramid (the retired 194-strip `tile_planet.py`), z0–8, served & verified
- [2026-07-13 — Shading stage designed + first Mercator chunk vs hero; Antarctica prefetched; snow is tile-scope](#2026-07-13--shading-stage-designed--first-mercator-chunk-vs-hero-antarctica-prefetched-snow-is-tile-scope) — shading stage designed; first Mercator chunk vs hero; snow is tile-scope
- [2026-07-13 — First MapLibre globe: Tier-2 stack validated end-to-end (region-first)](#2026-07-13--first-maplibre-globe-tier-2-stack-validated-end-to-end-region-first) — first MapLibre globe — the Tier-2 stack validated end-to-end, region-first
- [2026-07-10 — Phase 2 step A: tiling toolchain locked (WhiteboxTools dropped)](#2026-07-10--phase-2-step-a-tiling-toolchain-locked-whiteboxtools-dropped) — **tiling toolchain locked** — GDAL + our own shader; WhiteboxTools dropped
- [2026-07-10 — Phase 2 step B prototype: raster recipe viable; "quieter tiles" reframed](#2026-07-10--phase-2-step-b-prototype-raster-recipe-viable-quieter-tiles-reframed) — the raster recipe is viable; *quieter tiles* reframed

### Performance & instrumentation
*Everything here is measured. Three 'obvious flag' fixes died on a profiler — propose nothing from analogy.*

- [2026-07-23 — the prep-walk redundancy cut: mosaic freshness skip + a 24 h preflight stamp (35 s/country → 1.25 s)](#2026-07-23--the-prep-walk-redundancy-cut-mosaic-freshness-skip--a-24-h-preflight-stamp-35-scountry--125-s) — the two per-country redundancies from the sea-sync pre-pass decomposition fixed by TDD (12 tests): `build_mosaics.sh` reuses the previous build when a `.sources` sidecar matches AND no source is newer than the VRT (**17.6 → 0.63 s**, rebuild byte-identical, `.tmp`+`mv` hardening); `download_glo30` stamps a passing ETag preflight for 24 h (**one 1.6 s check/day, then ~0.07 s**). Warm six-stage walk **1.25 s/country**; a 204-country walk drops ~1 h. `MAPS_DATA` env override = the first open-source portability seam
- [2026-07-18 — the composite is threaded (opt #5): 128/N4 landed, and why 256 could not thread under 12 G](#2026-07-18--the-composite-is-threaded-opt-5-128n4-landed-and-why-256-could-not-thread-under-12-g) — read-main/compute-workers/write-main `ThreadPoolExecutor`, single-variant only; threaded==serial by construction (unit + real-scale gate). **256 threading OOMs past N=2 under 12 G → byte-identical caps at ~1.8×; the full ~3× needs 128-row windows**, which shift the look sub-perceptibly (worst 20 DN on mountain snow, invisible at true scale — judged on renders, chosen by Rohan). **128 is not a speed lever by itself** (kills the cache-window hypothesis). Full pass 645 s / 10.55 GiB peak / ~3.5×. Freshness fix: `composite_window_rows` now tracked
- [2026-07-18 — snow warped ONCE to the planet grid (opt #4): the packed-vs-unpacked trap](#2026-07-18--snow-warped-once-to-the-planet-grid-opt-4-the-packed-vs-unpacked-trap) — the composite's ~728 per-window `gdalwarp`/`gdal_rasterize` forks replaced by warp-once rasters (lakedepth precedent). **Store the RAW PACKED Float32, not the 0..1 fraction** (composite unpacks per window in float64). **The gate then caught a real bug: a single whole-grid warp DECIMATES a coarse source** (SP 1.1 km → 305 m global Mercator smooths snow off mountains, Ruapehu snow→bare land; `-et 0`/`-ovr NONE`/4096-row bands all fail). **Fix = warp in latitude BANDS** at the composite window height → byte-identical by construction. Generalises: warp-once of any source coarser than target needs banding. Unblocks #5
- [2026-07-16 — the instrumented planet pass: the baseline, and why every warp optimisation we planned was worthless](#2026-07-16--the-instrumented-planet-pass-the-baseline-and-why-every-warp-optimisation-we-planned-was-worthless) — **the instrumented baseline**, and why every warp optimisation we planned was worthless. 98 min wall on 1.16 of 16 cores
- [2026-07-16 — the gdaladdo step DELETED: I optimised it 4.5x an hour before proving it does nothing](#2026-07-16--the-gdaladdo-step-deleted-i-optimised-it-45x-an-hour-before-proving-it-does-nothing) — **I optimised gdaladdo 4.5× an hour before proving the step does nothing.** The trap: aiming at the fastest stage — an hour after reading the entry warning about exactly that
- [2026-07-16 — the composite parallelises with THREADS, and the xarray/dask question is settled by that](#2026-07-16--the-composite-parallelises-with-threads-and-the-xarraydask-question-is-settled-by-that) — **the composite parallelises with THREADS** — numpy releases the GIL. 1.80×@2 / 2.83×@4 / 3.57×@8; ~3× is the ceiling as memory bandwidth saturates. **Settles the xarray/dask question on merits**
- [2026-07-16 — optimisation #2 landed: `gdaldem color-relief` DELETED; the ramps became a 17.6 KB LUT](#2026-07-16--optimisation-2-landed-gdaldem-color-relief-deleted-the-ramps-became-a-176-kb-lut) — `gdaldem color-relief` DELETED — 24.4% of all pass CPU became a 17.6 KB LUT. A per-pixel *search* replaced by a divide
- [2026-07-16 — optimisation #1 landed: hillshade float32 + 256-row windows (1.84x faster, 5.7x less RAM)](#2026-07-16--optimisation-1-landed-hillshade-float32--256-row-windows-184x-faster-57x-less-ram) — hillshade float32 + 256-row windows — 1.84× faster, 5.7× less RAM. The fix its sibling `composite` already had
- [2026-07-16 — optimisation #3 landed: `NUM_THREADS` on the GTiff writers (10x), and the "three for three" record explained](#2026-07-16--optimisation-3-landed-num_threads-on-the-gtiff-writers-10x-and-the-three-for-three-record-explained) — `NUM_THREADS` on the GTiff writers (10×), and why the same flag had been **rejected three times** before (Amdahl, not caprice)
- [2026-07-16 — `composite_ram.py` was never the number PLAN said it was](#2026-07-16--composite_rampy-was-never-the-number-plan-said-it-was) — `composite_ram.py` was never the number PLAN said it was — a fixture measuring a lower bound, quoted as the peak

### Fusion & elevation data

- [2026-07-13 — Planet-wide fused heightfield built (Phase 2, step 1)](#2026-07-13--planet-wide-fused-heightfield-built-phase-2-step-1) — the planet-wide fused heightfield — the analysis-ready Phase-2 artifact
- [2026-07-04 — Fusion reframed after prior-art check](#2026-07-04--fusion-reframed-after-prior-art-check) — **fusion reframed after a prior-art check** — it is a solved problem (ETOPO 2022, grdblend); we were about to reinvent it
- [2026-07-04 — Khambhat fusion experiment: hard splice, −1 m ocean clamp, no feathering](#2026-07-04--khambhat-fusion-experiment-hard-splice-1-m-ocean-clamp-no-feathering) — the Khambhat experiment: hard splice, −1 m ocean clamp, **no feathering**
- [2026-07-04 — Fusion rule refined after full-frame spot checks](#2026-07-04--fusion-rule-refined-after-full-frame-spot-checks) — the fusion rule refined after full-frame spot checks — never convert dry land
- [2026-07-06 (late) — Khambhat seam: data-provenance edge, no smoothing](#2026-07-06-late--khambhat-seam-data-provenance-edge-no-smoothing) — the Khambhat seam is a **data-provenance edge** (TID 16 optical meets TID 40 gravity), not a bug. No smoothing
- [2026-07-13 — South Caucasus data void fixed: Copernicus "Public" withholds 25 tiles; filled from OpenTopography (Path A)](#2026-07-13--south-caucasus-data-void-fixed-copernicus-public-withholds-25-tiles-filled-from-opentopography-path-a) — **Copernicus 'Public' withholds 25 tiles** over the South Caucasus and a missing tile fuses silently as ocean. Filled from OpenTopography
- [2026-07-08 (late night, follow-up) — GLO-30 aux layers audited: hero mountain terrain is ~20–50% fallback-DEM fill; FLM adopted as on-demand diagnostic, not a pipeline stage](#2026-07-08-late-night-follow-up--glo-30-aux-layers-audited-hero-mountain-terrain-is-2050-fallback-dem-fill-flm-adopted-as-on-demand-diagnostic-not-a-pipeline-stage) — GLO-30 aux layers audited — hero mountain terrain is ~20–50% fallback-DEM fill
- [2026-07-09 — Global GEBCO acquired: batch renders unblocked 6 → 198 countries](#2026-07-09--global-gebco-acquired-batch-renders-unblocked-6--198-countries) — global GEBCO acquired: batch renders unblocked 6 → 198 countries
- [2026-07-08 — Raster source provenance audited: GEBCO self-pinned; GLO-30 unversioned bucket gets an ETag oracle](#2026-07-08--raster-source-provenance-audited-gebco-self-pinned-glo-30-unversioned-bucket-gets-an-etag-oracle) — raster provenance audited — GEBCO self-pins; GLO-30's unversioned bucket gets an ETag oracle
- [2026-07-04 — Phase 0 data acquired](#2026-07-04--phase-0-data-acquired) — Phase 0 data acquired; extent locked; GEBCO_2026 over 2025
- [2026-07-07 (night) — Blue Earth Bathymetry 2.0: considered, not adopted; shelved as tile-artifact remedy](#2026-07-07-night--blue-earth-bathymetry-20-considered-not-adopted-shelved-as-tile-artifact-remedy) — Blue Earth Bathymetry 2.0 — considered, **not adopted**; shelved as a tile-artifact remedy
- [2026-07-08 — Natural Earth 6.0 draft: not adopted; disk verified as 5.1.2; download script pinned](#2026-07-08--natural-earth-60-draft-not-adopted-disk-verified-as-512-download-script-pinned) — Natural Earth 6.0 draft — **not adopted** (it is preliminary); download script pinned

### Frontend
*All on `feat/frontend`.*

- [2026-07-23 — the blocky hover outline: a hit-layer geometry had become a display layer (0.05° → 0.002°)](#2026-07-23--the-blocky-hover-outline-a-hit-layer-geometry-had-become-a-display-layer-005--0002) — Rohan's Palawan screenshots: the gold highlight cut straight chords across bays while the raster coast underneath resolved every islet. **Both PLAN suspects innocent** (NE 1:10m has the detail; geojson-vt tolerance already crisp): `countries.geojson` was simplified at **0.05° ≈ 5.5 km ≈ 18 px at z8** for its original life as an *invisible* hit layer — then the 07-19 hover outline started stroking those very rings, and the "not a display layer" premise died silently. Fix: **0.002° (sub-pixel at z8)**, measured size ladder (9.4 MB raw / 2.5 MB gz vs 1.5 / 0.4; async fetch, cached), guard test pins the tolerance **relationally against `shade_planet.Z8_RES`**; verified in-browser on Palawan + Norway fjords (the N–S Mercator worst case). NE-worldview decision NOT re-opened — no finer source needed
- [2026-07-23 — polar caps PRODUCTIONIZED: WebP at 8192², the caps.json contract, default-on](#2026-07-23--polar-caps-productionized-webp-at-8192-the-capsjson-contract-default-on) — 4096² PNGs (11.1+4.8 MB, dev-assets, `?polarspike`) → **8192² WebP q85 (3.16+2.05 MB)** at `web/public/caps/`, chosen by Rohan on crop A/B + `/globe`; the layer now **fetches `caps.json`** (edge_lat, feather ceiling, URLs — the hand-copied TS literals deleted, encoder quality rides in the freshness recipe); **default ON, `?polarspike` → `?nocaps`**; `MAX_TEXTURE_SIZE` canvas clamp (mobile ships 4096 either way); production re-render proved **byte-identical** to the judged A/B rung; `polarCapSpike.ts` deleted same day (→ `polarCaps.ts`), 8 pipeline + 7 vitest tests; same-day: sync 396 ms/cap `texImage2D` decode → off-thread `createImageBitmap` (premultiplyAlpha "none" — ring chemistry), ~800→~230 ms main-thread
- [2026-07-19 — hover-highlight pole artifacts: polygon-clip stray line and tile-buffer fill double-paint](#2026-07-19--hover-highlight-pole-artifacts-polygon-clip-stray-line-and-tile-buffer-fill-double-paint) — two country-highlight bugs visible only looking down the pole: (1) a `line`-over-POLYGON strokes geojson-vt's clip-closing edge → stray gold meridian (fix: a `country-outlines` LINE source; **`maxzoom:0` was tried first and WORSENED it**); (2) the translucent fill wash double-paints in the default 128px tile-buffer overlaps, bunched by the pole's compressed tile grid → stronger patch (fix: `buffer:0`). Diagnosed by observation (mouse-off, rotate, pan-to-equator) + measurement, not guessing. Wiring extracted to `lib/countryHighlight.ts` + 11 regression tests
- [2026-07-18 — the polar cap: flat fails, and the pivot to a polar-stereographic custom-layer cap](#2026-07-18--the-polar-cap-flat-fails-and-the-pivot-to-a-polar-stereographic-custom-layer-cap) — **custom-layer-on-globe feasibility PASSED**: MapLibre 5.24 `CustomLayerInterface` works on globe (3 official examples incl. a georeferenced textured mesh; `defaultProjectionData.mainMatrix`, N pole = `(0,1,0)`; raw-WebGL cap mesh, alpha-feather the seam, 2d/no-depth/draw-last, pin 5.24). Research verdicts: **adopt `pmtiles`** (the one serving plugin); H3/S2 = indexing not tiling (don't fix poles); MLT = vector, irrelevant. Look/decision side under Light & shading
- [2026-07-15 — Frontend: capability probe, tier routing, quality + spin toggles, mobile polish (all committed on `feat/frontend`)](#2026-07-15--frontend-capability-probe-tier-routing-quality--spin-toggles-mobile-polish-all-committed-on-featfrontend) — the capability probe, tier routing, quality + spin toggles, mobile polish
- [2026-07-15 (later) — Frontend hardening: astro-check + TS, `.ts` config + `.env`, Tier-1 gazetteer, Spin option A](#2026-07-15-later--frontend-hardening-astro-check--ts-ts-config--env-tier-1-gazetteer-spin-option-a) — frontend hardening: astro-check + TS, `.ts` config + `.env`, Tier-1 gazetteer
- [2026-07-14 (evening) — Tier 2 globe + Natural Earth vector borders (frontend, `feat/frontend`)](#2026-07-14-evening--tier-2-globe--natural-earth-vector-borders-frontend-featfrontend) — **first interactive globe** — Tier 2 + Natural Earth vector borders
- [2026-07-14 (evening) — Click-to-fly-to → in-globe hero panel (BUILT, `feat/frontend`)](#2026-07-14-evening--click-to-fly-to--in-globe-hero-panel-built-featfrontend) — click-to-fly-to → in-globe hero panel
- [2026-07-14 (evening) — Detail-page hero: in-place pan/zoom (`feat/frontend`)](#2026-07-14-evening--detail-page-hero-in-place-panzoom-featfrontend) — detail-page hero: in-place pan/zoom
- [2026-07-14 (evening) — Starfield space backdrop shipped (`feat/frontend`)](#2026-07-14-evening--starfield-space-backdrop-shipped-featfrontend) — starfield space backdrop
- [2026-07-14 (evening) — Globe experience polish: remaining items scoped (from using the globe)](#2026-07-14-evening--globe-experience-polish-remaining-items-scoped-from-using-the-globe) — globe experience polish, scoped from actually using it
- [2026-07-14 (evening) — #4 "highest point" stat attempted then dropped; Google Earth datasets assessed](#2026-07-14-evening--4-highest-point-stat-attempted-then-dropped-google-earth-datasets-assessed) — the *highest point* stat attempted then **dropped**; Google Earth datasets assessed
- [2026-07-10 — Phase 3 begins: Tier 1 gallery shipped (Astro 7, `feat/frontend`)](#2026-07-10--phase-3-begins-tier-1-gallery-shipped-astro-7-featfrontend) — **Phase 3 begins** — the Tier 1 gallery ships (Astro 7)

### Engineering practice

- [2026-07-23 — LICENSE lands (MIT / CC BY-NC 4.0) and the paths seam single-homes the pipeline](#2026-07-23--license-lands-mit--cc-by-nc-40-and-the-paths-seam-single-homes-the-pipeline) — MIT for code (pyproject field + LICENSE), **CC BY-NC 4.0 for rendered imagery** (Rohan's pick; trade-off recorded: Wikimedia rejects NC media; GLO-30's commercial caveat aligns with NC regardless); `pipeline/paths.py` = ROOT (source-derived, never env) / DATA (`MAPS_DATA`) / BLENDER (`MAPS_BLENDER`), **18 modules migrated** TDD-first with a drift-scan test enforcing single-homing (`snow_mask.py` on a dated freeze allowlist until the sweep ratifies); plus the zsh no-match glob that invented "no README" — a broken oracle owned

- [2026-07-23 — the uncapped pmtiles convert OOM'd the box: tmpfs /tmp, a 12 GB orphan, and swapoff under pressure](#2026-07-23--the-uncapped-pmtiles-convert-oomd-the-box-tmpfs-tmp-a-12-gb-orphan-and-swapoff-under-pressure) — `pmtiles convert` launched WITHOUT the 12 G cap ("it's just IO" — an assumption); go-pmtiles funnels its working set through the system temp dir and **Ubuntu 26.04's `/tmp` is tmpfs = RAM** → swap 100%, fork failures box-wide, and Rohan's `swapoff -a` OOM-killed his session (swapoff itself was oom-reaped; slack et al. died). The SIGKILLed convert left `/tmp/pmtiles3601582229` (12 GB) holding RAM until `rm`. **The standing cap incantation would have contained it** (tmpfs charges the writer's cgroup) — the failure was purely the exemption. Same-day capped retry: **1m11s, 15 GB `planet.pmtiles`, verify clean, 5-tile byte-compare identical incl. z8 y=255; 5.3% deduped**; `?pmtiles` web flag landed same day (Range-supporting `/pmtiles` dev route TDD'd — the tiles middleware had none — + header-derived min/maxzoom; real-JS-client oracle byte-identical)
- [2026-07-23 — commonification LANDED as `raster_io.py`, half the list was already done, and coverage joins the gates](#2026-07-23--commonification-landed-as-raster_iopy-half-the-list-was-already-done-and-coverage-joins-the-gates) — PLAN's four-item commonify list executed TDD-first: `GTIFF_CREATE` (format-only — the threading constraint is now a TEST, not prose) + `row_bands`/`band_window` (the single Window pyright-ignore home) adopted at six sites, `composite_params` byte-unchanged so nothing restaged; the planned `stream_windows(src, rows, dtype)` did NOT survive contact (read patterns irreconcilable — the band *arithmetic* is the shared part); items 3–4 found **already done** (`warp_needs_rebuild` 2026-07-22; `lake_ab --left/--right`). Same day: **pytest-cov added** (`uv run pytest --cov`), baseline 32.45%, `fail_under=32` as a ratchet
- [2026-07-19 — CI gates the web layer; the frontend manifest gets a typed wrapper so astro check runs without it](#2026-07-19--ci-gates-the-web-layer-the-frontend-manifest-gets-a-typed-wrapper-so-astro-check-runs-without-it) — the web had ZERO CI: added a `web` job (pnpm 11 / Node 24 → `pnpm install --frozen-lockfile` → astro check → vitest) and fixed the pyright step to cover `tests/`. `astro check` needs the DATA-DERIVED, gitignored `countries.json` (absent on a clean checkout) → typed wrapper `lib/manifest.ts` decouples the type-check from the data (commit-the-manifest and drop-astro-check both rejected). **Verify CI by removing gitignored files / `git archive`, NOT rsync of the working tree — rsync copied the ignored manifest and hid the failure**
- [2026-07-09 — Per-country config live: countries.toml is the scope/overrides home; long-edge resolution rule; fusion choice formalized](#2026-07-09--per-country-config-live-countriestoml-is-the-scopeoverrides-home-long-edge-resolution-rule-fusion-choice-formalized) — **`countries.toml` is the scope/overrides home** — strict + curated, 208 rows, 9 excluded with reasons
- [2026-07-08 (late) — Pyright adopted as the CLI type-check oracle; pipeline clean](#2026-07-08-late--pyright-adopted-as-the-cli-type-check-oracle-pipeline-clean) — pyright adopted as the CLI type-check oracle
- [2026-07-13 — Test suite + CI on the resolver layer (a bug caught on day one)](#2026-07-13--test-suite--ci-on-the-resolver-layer-a-bug-caught-on-day-one) — test suite + CI on the resolver layer — **a bug caught on day one**
- [2026-07-13 — Known latent bugs (recorded pre-compaction; UNFIXED in tree)](#2026-07-13--known-latent-bugs-recorded-pre-compaction-unfixed-in-tree) — known latent bugs, recorded pre-compaction
- [2026-07-07 (night) — Python packaging: pyproject.toml + uv, manifest-only](#2026-07-07-night--python-packaging-pyprojecttoml--uv-manifest-only) — packaging: pyproject.toml + uv — the venv was the only record of dependencies
- [2026-07-09 — Hero .blend files are build artifacts, not versioned; source is canonical; prior-art audit logged](#2026-07-09--hero-blend-files-are-build-artifacts-not-versioned-source-is-canonical-prior-art-audit-logged) — hero `.blend` files are **build artifacts, not versioned**; source is canonical
- [2026-07-07 (night) — Dead render blobs rewritten out of history](#2026-07-07-night--dead-render-blobs-rewritten-out-of-history) — dead render blobs rewritten out of git history
- [2026-07-13 — Renamed to Terrella; `pipeline/` reorganized into a package; single-letter names purged](#2026-07-13--renamed-to-terrella-pipeline-reorganized-into-a-package-single-letter-names-purged) — renamed to Terrella; `pipeline/` became a package; single-letter names purged

### Project meta

- [2026-07-04 — Purpose reframed: learning first](#2026-07-04--purpose-reframed-learning-first) — **purpose reframed: learning first.** Understanding every piece is the primary goal; the site is secondary
- [2026-07-03 — Project scoped; dev environment decided](#2026-07-03--project-scoped-dev-environment-decided) — project scoped; dev environment decided

## Decision log

### 2026-07-23 — the blocky hover outline: a hit-layer geometry had become a display layer (0.05° → 0.002°)

Rohan reported the border overlay reading "terribly jagged" on coasts and islands at z6–8, with a Palawan screenshot pair that made the diagnosis: the raster coastline underneath resolved every bay and islet, while the gold hover outline cut straight chords across bays and reduced islets to triangles. The geometry being stroked had far fewer vertices than the coast it traced.

- **Both suspects in the PLAN item were innocent.** The item guessed "NE 1:10m generalization limit vs geojson-vt tolerance." But NE 1:10m tracks every bay Palawan has, and the runtime source options were already at the crisp default (`tolerance: 0.375` — the same lesson the white borders learned earlier). The detail was on disk all along.
- **Root cause: premise death by feature accretion.** `countries.geojson` was born as the *invisible* click-target layer, and `countries_geojson.py` simplified accordingly — Douglas-Peucker at 0.05°, on the recorded premise *"this is not a display layer… the layer is transparent."* (Its "~1 km at the equator" comment was also 5× wrong: 0.05° ≈ **5.5 km ≈ 18 px at z8**.) Then the 2026-07-19 hover outline began stroking those very rings as the visible gold line, and the wash painted the same polygons. Nobody revisited the constant; the outline stroked 18-px-wrong geometry faithfully. Symptoms matched exactly: chords across bays, and islets outside the wash (DP had triangulated the rings but kept all 97 of the Philippines' islands).
- **Fix: `SIMPLIFY_DEG` 0.05 → 0.002** (~220 m ≈ 0.7 px at z8 on the equator; N–S error grows toward the poles in Mercator px, ~3 px at 75°N, accepted). Measured ladder before choosing: 0.05/0.01/0.005/0.002/0.001/none → 0.4/1.2/1.7/**2.5**/2.9/3.3 MB gzipped. The fetch is async behind first paint and cached, so fidelity won; 0.005° would have saved ~800 KB but shows 2–4 px chords exactly at fjord latitudes.
- **TDD:** `tests/test_countries_geojson.py` — the tolerance is pinned **relationally against `shade_planet.Z8_RES`** ("simplification error stays sub-pixel at the top zoom"), so re-coarsening for size or raising the zoom ceiling both fail the test instead of the look; `ogr_command()` extracted pure with a contract test (`-select ADMIN`, RFC7946, precision) and an argument-order test (DST before SRC — swapped, ogr2ogr would overwrite the Natural Earth shapefile). Suite 424, pyright 0.
- **Verified live** (Chrome automation, window visible): regen kept 258 features; Philippines 804 → 5,470 vertices, same 97 rings. Palawan's outline hugs every islet; Norway at z7.6/62°N — the N–S worst case, predicted ~1.2 px sag — traces individual fjord arms with no visible chording. Localhost fetch of the 9.4 MB file: 28 ms, indexing in MapLibre's worker; production nginx gzips to 2.5 MB.
- **Rejected:** a second, detailed outline-only file (the wash and outline would visibly disagree at the coast); vector-tiling the layer (tooling overkill for z≤8). The NE-worldview decision is NOT re-opened — no finer *source* was ever needed.
- **Collateral find:** the paths-seam migration silently broke the documented direct-script invocation (`python pipeline/compose/…` can't `from pipeline import paths`; `ModuleNotFoundError`). The two compose docstrings now say `python -m pipeline.compose.…`; the Blender lines in scene_build/country_config were checked and are correct as-is (`blender --python` takes a file path, and scene_build inserts its own root).

### 2026-07-23 — LICENSE lands (MIT / CC BY-NC 4.0) and the paths seam single-homes the pipeline

The afternoon docket's Task 3, executed after the PMTiles close. Two decision sets and one seam.

- **Licenses (Rohan's picks, batched questions):** code = **MIT** (LICENSE at root with an
  assets-pointer coda; pyproject gains `license = "MIT"` + `license-files`). Rendered imagery
  (heroes, tiles, caps) = **CC BY-NC 4.0** — his intent is free educational/entertainment reuse
  with commercial use reserved, and NC is the standard instrument for exactly that. Trade-off laid
  out and accepted: **Wikimedia projects reject NC media**, so the maps can't illustrate Wikipedia;
  dual-licensing (public NC + case-by-case commercial grants) stays open. Alignment note: the
  GLO-30 EULA's commercial caveat (ATTRIBUTIONS) means commercial redistribution needed a fresh
  license read no matter what we picked. README gained a License section; ATTRIBUTIONS gained
  "Terrella's own outputs".
- **The paths seam (`pipeline/paths.py`):** three constants — `ROOT` (source-tree-derived, never
  env-driven: repo outputs like `web/public` must follow the checkout, not the data store),
  `DATA` (`MAPS_DATA` override, default `<repo>/data`), `BLENDER` (`MAPS_BLENDER` override,
  default the documented tarball). **18 modules migrated** by a fail-loud script (most-specific
  regex first; abort on any surviving `Path.home()`); module attrs preserved, so every
  monkeypatching test passed untouched. TDD: 7 tests in `tests/test_paths.py` — subprocess
  env-override probes (import-time binding makes in-process reload a lie) + the **drift scan**
  that fails on any `Path.home()` outside paths.py. `snow_mask.py` rides a **dated allowlist**
  (hero-look freeze until the sweep ratifies — Step 5 must migrate it and delete the entry).
  Consumer-level proof: `MAPS_DATA=/tmp/elsewhere` moves `shade.DATA` and `glo30.DATA_DIR`;
  `MAPS_BLENDER` moves `country_config.BLENDER`. Gates: **pytest 421, pyright 0**.
- **GLO-30 licence VERIFIED against the primary text (same day, Rohan's ask):** fetched
  `License-COPDEM-30.pdf` (Copernicus Data Space) and read it whole. Article 4 grants
  reproduction, distribution, communication to the public, and adaptation — worldwide, no time
  limit, **no purpose restriction (commercial derived use permitted)**; Article 9: IPR in work
  produced using the DEM is ours; the old "core prohibition is reselling the raw DEM" claim was
  wrong (no such clause). Obligations: the EXACT Article 6(b) adapted-data notice ("produced
  using Copernicus WorldDEM-30 © DLR e.V. 2010-2014 and © Airbus Defence and Space GmbH
  2014-2018…"), the 6(c) liability sentence, no implied endorsement (6(d)). Our placeholder
  notice ("Contains modified Copernicus DEM data") was NOT the licence wording — corrected in
  ATTRIBUTIONS. Consequence: the NC choice's "matches upstream necessity" justification was
  retracted — upstream permits commercial; NC is purely Rohan's choice. Same pass: the
  **OSI SAF sea-ice source was missing from ATTRIBUTIONS entirely** (ships in tiles + both
  caps) — row + citation added (OSI-450-a v3.0, CC-BY 4.0, doi:10.15770/EUM_SAF_OSI_0013);
  stale WhiteboxTools tool credit dropped (retired at the 2026-07-10 scoping); source links
  added to every dataset row.
- **The broken oracle, owned:** Task 3 nearly shipped a root README stub because `ls README*
  LICENSE*` reported "no README". zsh's NO_MATCH on the unmatched `LICENSE*` glob aborted the
  ENTIRE command before `ls` ran, the `|| echo` fallback printed my own words back, and I read a
  shell artifact as a repo fact — Rohan caught it ("the repo already has a README"). The root
  README existed and is good. A check used as proof must fail on its *target*: separate the
  probes (`ls README*; ls LICENSE*`) or glob-guard, never compound them under one fallback.

### 2026-07-23 — the uncapped pmtiles convert OOM'd the box: tmpfs /tmp, a 12 GB orphan, and swapoff under pressure

The PMTiles spike's first half went perfectly — `pipeline/tile/pack_pmtiles.py` (TDD, 7 tests, the
XYZ→TMS row flip pinned both ways) packed all 87,381 tiles into a 16.15 GB MBTiles in **33 s**. The
second half took the box down:

- **The mechanism.** `tools/pmtiles convert` was launched **uncapped** — "it's an IO-bound Go binary"
  was an assumption, exactly the species the one-heavy-job rule exists to forbid. go-pmtiles stages
  its working set in the system temp dir, and **Ubuntu 26.04 mounts `/tmp` as tmpfs — RAM**. ~12 GB
  of archive materialised in memory on a 29 GiB box: swap hit 100%, every forked shell died (the
  Claude harness writes its own tracking files under `/tmp`, so even `echo` failed — the observation
  channel broke before the diagnosis could run), and the desktop went unresponsive.
- **The swapoff trap.** `sudo swapoff -a` — the standard clear-swap move, used successfully before —
  needs free RAM ≥ swap-used to reabsorb pages. Run while the box was still starved, it fed the OOM
  killer instead: the kernel log shows **swapoff itself oom-reaped mid-flight**, then session apps
  (slack among them) killed. Lesson: kill + clean the hog FIRST; clear swap only with headroom.
- **The orphan.** The `pkill -9` on convert left `/tmp/pmtiles3601582229` (12 GB) behind — Go's
  deferred temp-file cleanup never runs on SIGKILL, and a tmpfs file holds its RAM until unlinked.
  One `rm`: available RAM 3.4 → 12 Gi, tmpfs 80% → 5%, swap self-drained 6.2 → 3.3 Gi.
- **The rule already covered this.** The memory's standing incantation
  (`systemd-run --user --scope -p MemoryMax=12G -p MemorySwapMax=0`) would have contained the whole
  event — tmpfs pages are charged to the writing process's cgroup, so the convert would have died
  cleanly inside its cap at worst. The failure was not a gap in the rule but an *exemption* from it.
  Ops memory updated: no third-party exemptions; know where a tool writes temp (`--tmpdir` onto
  ext4 — the "big data on ext4" rule applies to tools' internals too); check `/tmp` after killing
  anything big.
- **The capped retry closed it same-day (13:03):** health confirmed (15 Gi available, swap 0,
  tmpfs 5%), then the standing incantation + `--tmpdir data/work/planet_tiles/tmp` → **1m11s**,
  15 GB `planet.pmtiles`, temp self-cleaned (Go's deferred cleanup runs when the process exits
  normally — the orphan was a SIGKILL artifact). Verified: `pmtiles show` (spec v3, clustered,
  z0–8, png), `pmtiles verify` clean, and 5 extracted tiles byte-identical to the source dir
  **including z8/137/255** — the Antarctica bottom-row tile that proves the XYZ→TMS→PMTiles
  double flip is an identity round-trip. Dedup kept ON (the `--no-deduplication` speed flag is
  for known-unique inputs; ours demonstrably isn't): 87,381 addressed → 82,746 unique contents,
  **4,635 duplicates (5.3%) collapsed** — the flat abyssal-clamp and 100%-ice tiles, as
  predicted. `planet.mbtiles` is now reclaimable (INVENTORY updated).
- **The `?pmtiles` web flag completed the spike the same afternoon.** The blocker the docs never
  mention: the `/tiles` dev middleware pipes whole files and **ignores the `Range` header**, and
  the pmtiles client reads the archive purely as byte slices — without `206` support a browser
  would try to pull 15 GB. Precision (Rohan's challenge, confirmed by probe + search): **vite
  itself DOES serve ranges** — its public-dir serving (sirv) answered a probe 206 — but the asset
  stores live *outside* `public/` precisely so builds don't copy tens of GB, and our external-store
  middlewares are the layer with no Range support. Upstream wart worth knowing: vite#10744 (closed
  not-planned) 416s when the requested end exceeds the file — Firefox sends those; our
  `parseByteRange` clamps per RFC instead (pinned by test). In-browser protocol timings (probed in
  the live page): TileJSON synthesis 4 ms, first tile 6 ms, warm tile 2 ms, pmtiles chunk import
  1 ms (vite pre-bundles it) — the whole pmtiles-specific boot is **~10 ms**, so the ~1–2 s
  page-load delay Rohan observed is NOT this path's overhead (path-independent suspects: the two
  8192² cap texture decodes/uploads, dev-mode module serving; a foreground waterfall would settle
  it). Landed: a dedicated `/pmtiles` dev route (4th store env var
  `PMTILES_STORE`, same loud-failure pattern) with real single-range support — `parseByteRange`
  TDD'd in `web/src/lib/httpRange.ts` (13 vitest: 206 slice / 416 unsatisfiable / suffix / clamp /
  ignore-malformed per RFC 9110); `pmtiles` npm 4.4.1; `globe.astro` builds `reliefSource`
  conditionally behind `?pmtiles` — Protocol registered before the Map via conditional top-level
  await, and the `pmtiles://` source URL **derives min/maxzoom from the archive header**, retiring
  two more hand-copied web literals (the caps.json species). The archive deliberately stays OUT of
  the tiles dir: `iter_tiles` does `int(p.name)` and would crash on `planet.pmtiles`. Proof
  ladder: curl (206 + correct `Content-Range`, 416, interior slice byte-identical to the raw
  file), then the **real pmtiles JS client** over dev-server HTTP — header (z0–8, png), metadata,
  and the same 5 tiles byte-identical including z8/137/255. Gates: vitest 45 (32+13), astro check
  0, build 206 pages. Remaining: Rohan's visual `/globe?pmtiles` look, then default-on + nginx
  (whose Range support is native — the dev route is parity, not production code).

### 2026-07-23 — polar caps PRODUCTIONIZED: WebP at 8192², the caps.json contract, default-on

The last non-sweep Phase-3 pipeline item, done in the pre-launch afternoon window.

- **Assets:** `web/public/dev-assets/cap_{north,south}.png` (4096², 11.1 + 4.8 MB, plain
  `gdal_translate -of PNG`) → `web/public/caps/cap_{north,south}.webp` (**8192², WebP q85,
  3.16 + 2.05 MB** — 4× the pixels at ~28% of the PNG bytes, `hero_variants`' proven GDAL WebP
  path). Renders 56 + 44 s (was ~21 s/cap at 4096; PROCESS updated).
- **Resolution decided on evidence, ladder in `experiments/ab_cap_prod.py`:** Rohan judged native-scale
  crop pairs (Greenland coast, pole pack, Antarctic interior — all visibly crisper at 8192; the 4096
  smooths sastrugi-scale ice texture away entirely) plus the live globe with the 8192 rung swapped in.
  After pinning `CAP_PX=8192`, the production `cap_render` run came out **byte-identical to the judged
  rung** — the determinism oracle that proves the A/B showed exactly what production ships.
- **The caps.json contract:** `polarCaps.ts` (renamed from `polarCapSpike.ts`, spike deleted same day)
  now FETCHES `/caps/caps.json` — `edge_lat` ±78, the ±84 feather ceiling (= `shade_planet`'s
  `CAP_NORTH`/`CAP_SOUTH` plug boundary) and texture URLs — instead of carrying them as hand-copied
  literals, the same copy-drift species as the hero/tile colour constants. The WebP quality rides in
  `cap_recipe`, so an encoder change restages the caps (the 2026-07-22 freshness rule).
- **Default ON; `?polarspike` inverted to `?nocaps`** — the escape stays because layer-on/off
  comparison is the exact diagnostic that isolated the 2026-07-22 polar ring. Textures clamp to
  `gl.MAX_TEXTURE_SIZE` via canvas downscale (constrained mobile GPUs get 4096 instead of silent
  black), so 8192 costs desktop bytes only.
- **Tests:** 8 pipeline (`test_cap_render.py` — the linear AEQD radius law as an independent geometry
  oracle, rotated-azimuth shade invariants, the manifest contract, recipe-covers-the-asset) + 7 vitest
  (`polarCaps.test.ts` — contract mapping incl. the signed-south `Math.abs` feather, mesh UV pins,
  the clamp). One red-phase self-catch: my longitude-orientation assertion had top/bottom swapped —
  the probe said bottom-centre = lon 0, matching `y = −ρ·cos(lon)`; the test was wrong, not the code.
- **Off-main-thread decode (same day, after Rohan reported a ~1–2 s first-load delay):** measured
  in-page — `texImage2D(HTMLImageElement)` does a SYNCHRONOUS main-thread decode, **396 ms per 8192²
  cap** (≈800 ms across both poles; fetch itself is 5 ms). Replaced with
  `createImageBitmap(blob, { premultiplyAlpha: "none" })` → decode moves to Chrome's worker pool,
  leaving ~117 ms of GPU upload per cap on the main thread; `bitmap.close()` frees the ~268 MB
  decode immediately. `premultiplyAlpha: "none"` is load-bearing — the shader premultiplies
  in-shader, and a decode-time premultiply would double-apply (the polar-ring alpha chemistry).
  Deliberately NOT lazy/idle-deferred: that would trade a visible cap pop-in at the poles for
  ~230 ms, the wrong side of the bargain. **Firefox postscript (Rohan's second-load waterfall):**
  every request ≤7 ms but a **1.1 s network-silent gap (153→1257 ms)** opening exactly at
  cap-fetch completion — Firefox runs `createImageBitmap` decode ON the main thread (sync, per
  Mozilla's own bugzilla) and its ImageBitmap→`texImage2D` upload is slow besides (bug 1486454),
  so the stall Chrome sheds persists there. A fallback also landed same day: `premultiplyAlpha`
  is an unimplemented dictionary member in Firefox (silently dropped — safe, the mesh samples
  only the opaque disc), and if `createImageBitmap` itself rejects the loader drops to the
  original Image path. Fix queued to the Lighthouse pass (PLAN Phase 3): decode in a Web Worker,
  transfer the ImageBitmap — forces off-thread on every engine.

### 2026-07-23 — commonification LANDED as `raster_io.py`, half the list was already done, and coverage joins the gates

Pulled forward with the prep-walk cut (same motive: the open-source intent). PLAN's four-item
commonification list, executed TDD-first — and auditing it against the code first found **half of it
already done**, which is itself the lesson: a queued refactor list rots as the code evolves under it.

- **`pipeline/raster_io.py`** (new, 15 tests written red-first):
  - `GTIFF_CREATE` — the GTiff format core (tiled/512/512/deflate) of the three tile writers
    (`hillshade`, `shade` region, `shade_planet` composite). **Format-only, and the constraint is now
    a test rather than prose:** `test_raster_io` asserts `num_threads` is not in the constant and not
    in either fusion source — `fuse_planet` sets `GDAL_NUM_THREADS=1` on purpose (parallelism across
    cells) and a creation option would override it into oversubscription.
  - `row_bands(height, band_rows, start)` — the full-width band iteration (the hand-rolled `min()`
    at every site); `band_window(width, row0, row1)` — the single home of the pyright ignore for
    rasterio's untyped `Window`. Adopted at six sites: hillshade (loop + halo + write windows),
    shade_planet (`read_window`), verify (compare loop + probe), snow + seaice band writers.
  - The planned `stream_windows(src, rows, dtype)` did NOT survive contact with the sites: the read
    patterns are irreconcilable (hillshade's halo reads, the composite's eight-file gather, verify's
    two-dataset compare) — the *arithmetic* is the shared part, so `row_bands` is the honest extraction.
- **Items 3–4 were already done:** `warp_once(...)` behind `is_stale` was superseded by
  `warp_needs_rebuild` + per-source guards (the 2026-07-22 grid-freshness fix — every 3857 warp
  routes through it; only `height`, which *defines* the grid, uses plain `is_stale`); and
  `lake_ab.py --left/--right` shipped earlier, its docstring citing this very list as the reason.
- **Identity, not behaviour:** `composite_params` byte-unchanged (no restage of the 33 GB
  `planet_rgb`); the byte-equality suites are the real gate (threaded==serial composite,
  banded==whole snow/seaice warps, hillshade window-invariance) and all run through the new helpers
  now. Suite 399 passed, pyright 0.
- **Coverage joined the gates the same day:** `pytest-cov` dev dep; `[tool.coverage]` in pyproject
  (source `pipeline`; bpy scripts, `experiments/`, `profile/` omitted — unit tests can never import
  bpy, and the shared constants ARE covered via the `test_scene_build_sync` stub). **On demand**
  (`uv run pytest --cov`), not in addopts — a default `--cov` would make every single-file test run
  trip the floor. Local baseline **32.45%**; the number is not the point, the *boundary* is — the
  100%-covered files are the compute kernels, the 0% files are network/GPU/subprocess orchestration,
  and the report makes that long-claimed split visible.
- **CI wiring (same day, after the first CI run failed):** the runner had no GDAL CLI, so the five
  `test_build_mosaics` tests died on `gdalbuildvrt: command not found` — fixed by installing
  `gdal-bin` in the check job, NOT by a skipif (a drift guard that silently never runs is the exact
  class the suite documents). The pytest step became `pytest --cov`, and the floor moved to the
  **CI-visible** baseline: CI skips 12 data-bound tests (NSIDC/RGI/OSI SAF sources absent), measured
  locally by deselecting those classes → **30.94%**, so `fail_under=30` — one number, enforced where
  the gate actually runs; a full local run reads ~32.45% against the same floor.

### 2026-07-23 — the prep-walk redundancy cut: mosaic freshness skip + a 24 h preflight stamp (35 s/country → 1.25 s)

The sea-sync pre-pass measured ~35 s/country of pure walk overhead; the decomposition (PROCESS § Hero
renders) named two redundancies, queued for after the sweep. Pulled forward the same morning — Rohan
wants the project open-sourced eventually, and the fix also shortens the held overnight sweep itself
by ~1 h, since `--through render` re-walks the same prep stages.

- **`build_mosaics.sh` freshness skip.** The batch invokes the script once per country, but the tile
  store only changes when a download lands — the other ~200 invocations rebuilt two 26,475-source VRTs
  identically (~17 s each ≈ 53 min/walk). The previous build is now reused when (a) the current source
  list is byte-identical to a `.sources` sidecar written at build time — catches added AND deleted tiles
  (deletion leaves every survivor *older* than the VRT; mtime alone cannot see it) — and (b) no source
  is newer than the VRT — catches a re-downloaded tile (same name, same count). Either failing rebuilds
  both VRTs (fuse consumes them as a pair). **17.6 → 0.63 s**, and a forced `rm`-rebuild proved
  **byte-identical** to the saved VRTs. Hardening rider: VRTs now build to `.tmp` + `mv` — previously a
  crash mid-`gdalbuildvrt` left a truncated VRT that any freshness check would then trust. This is the
  same comparison whose *absence* caused the 2026-07-22 stale-mosaic all-ocean fuse, so the skip hardens
  that class rather than trading against it.
- **`download_glo30` preflight stamp.** The edition-swap oracle (3 ETag HEADs + 3 full-tile md5s) ran
  per country — 550+ identical round-trips per walk guarding against a month-scale event. A passing
  check now writes `preflight_ok.json` (UTC timestamp + the verified tile names, atomic) and is reused
  for `PREFLIGHT_TTL_HOURS = 24`. A mismatch still aborts and never stamps; absent/expired/malformed/
  **future-dated** stamps re-verify; no-held-tiles never stamps (nothing was verified). `rm` the stamp
  to force.
- **TDD, 12 tests** (`test_build_mosaics.py` drives the real script + gdalbuildvrt against a throwaway
  store via a new `MAPS_DATA` env override — the first portability seam toward open-sourcing;
  `test_download_preflight.py` fakes the bucket via monkeypatched urlopen). Red-phase lesson: the first
  red run hit the REAL store, because the not-yet-implemented `MAPS_DATA` fell through to the production
  default — a red test that shells out needs its isolation seam to exist *first* (harmless here: one
  idempotent 17 s rebuild, source count verified 26,475 after).
- **Measured end-to-end:** estonia's warm six-stage walk 35 s → **1.25 s**; remaining cost is the
  deliberate six-subprocess GDAL import tax (OOM isolation). Suite 384 passed, pyright 0.

### 2026-07-23 — the flat-pole taper RETIRED: `ice_relief_damp` treats at the source what the taper patched geometrically

The taper (a colat-3° smoothstep ramp of cap relief to the local flat level, north-only since the south dropped it 2026-07-22) existed because the longitude-rotated light azimuth sweeps 360° across a few pixels at the pole, washing directional relief into a pinwheel disc. `ice_relief_damp=0.75` conceals the seafloor's shading under the pack — which is the wash's entire food supply — so the patch and the disease now overlapped. **Measured before deleting** (21 s cap A/B, taper off at damp 0.75): pole disc std **6.16 < surrounding annulus 6.70** — honest texture *milder* than its surroundings, the same verdict that cleared the south; disc-vs-annulus mean step −1.41 vs −1.19 DN with the taper (no ring signature; the south's retired disc was +4.06); the delta confined entirely inside colat 3° (outside: byte-identical), mean ~1 DN. **Deleted:** `POLE_TAPER_COLAT`, the `CapGrid.pole_taper_colat` field, `_shade`'s taper block, and `_colatitude` (its only caller) — no pole special-case remains in either cap. Both caps restaged themselves off the recipe change (the field vanishing from the sidecar — the 07-22 freshness guard working as designed), and the shipped north cap is **byte-identical to the A/B render that was measured**. pyright 0, 355 tests.

### 2026-07-22 — Antarctica FILL chosen over accept: extend the Mercator pyramid south, code landed, planet re-fused

Rohan reported a faint ring in the Southern Ocean, concentric to the pole. Diagnosed from the pixels (after two wrong offline guesses — a −57° feather seam, then the −87° pole-taper disc, both refuted by the screenshot): it is the **cap↔tile seam at −59.5°**. The Mercator pyramid stops at −60° (`--skip-south -60`) and the AEQD custom-layer cap supplies Antarctica, cross-fading into the tiles across −57…−59.5° over open ocean, where the cap's ocean and the tiles' ocean don't render identically.

**The decision: fill, not accept.** Extend the Mercator pyramid itself south to the −85.06° projection limit, so the seam moves off open ocean onto the white interior ice (~−84°, barely visible) and Antarctica renders at full tile resolution (308 m/px, pyramided) instead of a coarse ~1.9 km/px monolithic cap. Grounded checks before deciding:

- **Cost lands on the build box + server, NEVER the visitor.** Tiles are range-requested, so global tile count is irrelevant to per-view cost; a viewer of Europe downloads zero Antarctic tiles. The one per-user runtime cost is the cap PNG (downloaded whole, GPU-resident) — and fill *shrinks* the south cap. Build cost: 93009→131072 rows = **1.41× every planet raster permanently** (height 31→44 GB, planet_rgb 11→15.5, tiles 14→20), a ~2 h pass, ~+30 GB. Premise verified: 7,044 Antarctic GLO-30 tiles on disk, 459 GB free; `fuse_planet --dry-run` = 0 land cells missing tiles globally.
- **Occlusion `cos(lat)` fix NOT bundled** (Rohan's call). It is worst in Antarctica (~11× at −85°) but its visual impact is tiny (SVF capped hard), and bundling would blur the /globe judgment across the whole planet. Stays deferred.

**Why fill is more than un-skipping.** Three things would otherwise break, all now handled in code:

- **The grid-freshness precondition (the latent bug PLAN flagged).** `lakedepth`/`snow_persistence`/`glacier`/`seaice` are freshness-gated on their own SOURCE only. When the grid grows, they sit falsely fresh at the old 93009 dimensions and the composite reads window slices past their bottom → silent corruption. Fixed with `grid_matches` + `warp_needs_rebuild` (a dimension/bounds comparison, NOT an mtime dep on height — so a same-grid re-fuse like the Caspian still skips them). Load-bearing test: fresh source + shrunken grid must rebuild.
- **Antarctic land would render as the tan LAND ramp** (NSIDC-0791 is NH-only, RGI region 19 excluded, so snow_alpha and the glacier union are both 0 there). Forced white by `snow.antarctic_snow_mask(land, latitude, lat_max=-60)` — the ONE shared home, called by both the tile composite and `cap_render.render_cap_south`, so they agree across the seam. The whole Antarctic Peninsula is south of −60; sub-Antarctic islands north of it stay bare (deferred RGI-19 polish).
- **The SH sea-ice belt would halo.** Now toned to the cap's fainter, pulled-in fringe (`seaice.SH_ICE_LO`/`SH_ICE_MAX_ALPHA`, moved out of cap_render as the shared home), applied south of the equator; recorded in `composite_params`. Also `CAP_SOUTH −59.5 → −84` so the flat `CAP_RGB` fill covers only the last smeared Mercator sliver.

**The re-fuse (same day, later) — and the stale-mosaic incident.** The first pass (108 new s70/s80/s90 cells; 540 skipped by per-cell resume) reported `ok: 108, warned: 0, failed: 0` in seconds and was **entirely garbage**: every Antarctic cell fused as ocean, the whole interior clamped to −1 m. Caught only by an independent elevation-probe oracle (Dome A read −1.0 instead of ~4090). The mechanism, and why every gate passed:

- `fuse_heightfield` reads the DEM through `data/work/dem_mosaic.vrt`, and that VRT (built Jul 13) predated the Antarctic download. A VRT enumerates its sources at build time, so the 7,044 tiles on disk were invisible → "outside GLO-30 coverage" ⇒ ocean ⇒ GEBCO's +4 km ice surface clamped to ≤ −1 m.
- **Both gates were blind by construction.** `fuse_planet`'s tileList preflight checks tiles ON DISK (they were). The in-cell coverage-gap check counts land pixels lacking DEM — but "land" comes from the WBM mosaic, which was *equally* stale → 0 land pixels → 0 gap. The index and its own oracle went stale together. Same disease as the grid-freshness bug fixed this morning: an intermediate index freshness-gated on nothing. That invariant is now code (`enforce_land_guard`, landed same day, Rohan's call): after a tileList-listed *land* cell fuses, its ocean mask must hold ≥1 land pixel — on pure ocean the cell goes `failed` with an error.log naming `build_mosaics.sh`, and its outputs are deleted so the resume contract retries instead of trusting the garbage. Output-side, so it cannot go stale with its inputs.
- Remediation: `build_mosaics.sh` (whose own header says "run after each extent expansion" — the step the download session skipped) — which then hit **ARG_MAX** at 26,475 sources → switched it to `-input_file_list` (small committed-code change). Deleted the 108 all-ocean chunks, re-fused: 108 ok in ~1:52 of fusing (polar tiles are thin — GLO-30 decimates longitude toward the pole), `work/planet` 12→14 GB.
- **Probe-verified** (planet VRTs now 129600×64800, lat −90…90): Dome A 4083 m, Vostok 3493 m, Ross shelf +47.6 m and masked *land*, Vinson massif 4647 m, McMurdo Dry Valleys 872 m, Weddell Sea −4060 m; oceanmask land=0/ocean=1. Southern Thule (the only S60-tile land, 2 tiles) confirmed intact from the ORIGINAL sweep (Cook Island 552 m) — no pre-existing s60 gap.

**State: the full fill pipeline ran same day; only the /globe judgment remains.** The step-5 pass (`run_pass.sh --tiles`) completed in **2:28:01** — grid grew to 131072×131072 as designed, dominated by the grid-guarded re-warps (lake 1:01:44, **unchanged**: no lakes south of −60). Probe-verified: Dome A/Vostok exactly `SNOW_RGB` (232,241,246); a Transantarctic slope at −84.5° reads (216,226,233) = shaded snow, so relief survives; the old −59.5° seam band is ordinary sea-ramp ocean; z8 rows reach y=255. Stage times re-measured at the permanent new grid → PROCESS (composite now 21:37; a composite-knob iteration ≈ ~29 min). Step-6 cap shrink landed too: `edge_lat −78` + frontend feathers mirror north (81→84 == CAP_SOUTH −84), south cap re-rendered **19 → 4.5 MB**. Code green (334 tests, pyright 0), all UNCOMMITTED (git is Rohan's). Rollbacks: `tiles_old/` (pre-Antarctica pyramid) + `planet_rgb_pre_antarctica.tif`. The residual no gate can see: interior `tileList.txt` index voids would fuse as ocean → blue holes in the ice — a /globe check. Full plan → the session plan file (`polymorphic-jumping-pelican.md`).

**Late evening — the interior ring, diagnosed by radial oracle; three cap fixes landed.** Rohan judged: −59.5° ring GONE, relief good, but a fainter ring moved inside the continent. Band-vs-band measurement (after a wrong-units first pass — colat bins mislabeled as latitude bands — and a flat-target error that overstated the cap↔tile offset ~2×): the ring is the **pole-taper disc** — gamma8 saturates the taper's flat fill at 239.45 while the honestly-shaded −86 dome annulus averages 235.4, a +4.06 DN concentric step. Landed, each measured: (1) **south cap re-sourced from the fused planet VRTs** — GEBCO special-case and constant deleted the day their premise died; blend-zone offset +1.48 → +1.31 DN and the masks now match the tiles by construction; (2) **south taper OFF** (new `CapGrid.pole_taper_colat`; north keeps 3.0) — ring +4.06 → **+3.54 DN**, the sterile disc replaced by honest texture, and the feared pinwheel wash measured *milder than the surrounding real terrain* (pole std 6.1 vs 10.9) — the taper is north medicine (seafloor relief) the flat south dome never needed; the residual ring is real dome-slope shading made ring-coherent by the rotating light, inherent to the cap design; (3) **the stale-cap discovery**: both on-disk cap PNGs predated PR #9's ambient-knee/warm-floor — the north cap sat **−6.7 DN darker than the tiles it feathers into** since 2026-07-21; fresh renders close it to +0.3–0.5 DN. Cap PNGs are shade-stage outputs with **no freshness guard** — the same disease as the mosaics and warps, third instance today. A flat_dn "continuity" fix was tried first and **refuted by measurement** (south medians coincide — byte-identical output; the apparent north delta was the knee confound), then reverted.

**Rohan's re-judgment:** the interior ring is still visible ("barely changed"), though white-on-white — much less objectionable than the old teal-ocean ring. He then challenged whether we understood the ring at all, and the deeper investigation **refuted the "dome shading" story**: the radial-mean dip at colat 4 is **sectoral, not a ring** — flat (±0.5 DN) in 8 of 12 azimuth sectors, −13 DN only where the Transantarctic Mountains cross that colatitude; the radial mean had averaged a mountain arc into a fake annulus. Reconstructing the actual on-screen composition (tiles × feather × cap, 0.1° steps) showed **no pole-concentric band above ~1 DN anywhere in −78..−85** — the data no longer contains a ring an eye should see. What CAN produce one and matches every symptom (z0-visible, z8-invisible, immune to all texture tone fixes, "no change" before/after): **the cap texture is minified without mipmaps** — `polarCapSpike.ts` set `TEXTURE_MIN_FILTER = LINEAR` and never called `generateMipmap`, so at low zoom GL bilinear-samples 4 texels per ~40×40 block of the 4096² texture; the aliased relief detail organizes along the radial UV mapping as **concentric moiré rings**. Fixed: `generateMipmap` + `LINEAR_MIPMAP_LINEAR` — correct hygiene, but the ring survived it, and Rohan's challenge ("does banding explain the ring MOVING with the boundary?") forced the decisive test. **Pixel-level proof of the real chain:** his screenshot shows exact integer staircases (60 px of G=241, steps to 246, back — 8-bit quantization arcs), but sampling BOTH assets along the same georeferenced path (lon 43°E) showed cap AND tiles dead flat at 241/226 — **the +5 swell exists only in the browser's composited output, peaked exactly at the −84 boundary.** Brighter-than-both-inputs = non-convex blending: `polarCapSpike.ts` output **straight alpha** (`vec4(c.rgb, a)`) with `blendFunc(SRC_ALPHA, 1−α)` onto **MapLibre's premultiplied framebuffer** — and that blendFunc also wrote `α²+(1−α)` into the canvas's own alpha channel, so the map canvas turned translucent along the feather band and Chrome composited the dark starfield page through the globe there. Both violations peak in the feather band → a smooth swell pinned to the crossfade, which 8-bit quantization renders as crisp concentric arcs (banding = the lens, not the cause). **This is the artifact that TRACKED the boundary**: the pre-fill teal ring at −57..−59.5 over ocean was the same compositor bug amplified by the larger cap-vs-tile ocean gap — Rohan's "the ring moved" observation was the correct root-cause instinct all along. Fixed to the contract: shader premultiplies (`vec4(c.rgb*a, a)`), `blendFuncSeparate(ONE, 1−α, ZERO, ONE)` pins destination alpha. /globe verdict pending. Dead ends this investigation killed and recorded: taper disc (partial, real, removed), cap tone mismatch (real, ~1 DN, re-source landed), mipmaps (hygiene), dither-the-composite (unnecessary if the blend fix holds — the assets were never the problem). **Cap freshness guard landed the same night (Rohan's call):** `cap_recipe` sidecar built on `shade_planet.composite_params` (ONE recipe home — a look change restages tiles AND caps; `fill_strength` listed explicitly since composite_params filters it as hillshade-stage) + `cap_sources` mtimes, `cap_is_fresh` pure and tested, `--force` override, and **`shade_planet`'s pass tail now invokes `cap_render`** (subprocess, ~2 s when fresh) so the guard actually runs — closing the fourth unguarded-output hole of the day (mosaics, warps, cap PNGs × recipe, cap PNGs × sources). 345 tests, pyright 0.

**Judgment COMPLETE + reclaim (same night).** Rohan on `/globe`: the ring is GONE (the blend fix held — confirming the root cause), the north pole reads well, the SH sea-ice fringe is right with no bright ring in any belt, and the blue-hole scan is clean (screenshot-verified: no teal voids anywhere in the interior). **The Antarctica fill is DONE** — PLAN's line flipped to [x]. Reclaimed under the standing rule (remove only what is required for nothing at all; targets ls'd for stray code first — clean): `tiles_old/` (14 GB) and `planet_rgb_pre_antarctica.tif`+`.done` (9.9 GB), whose keep-gate was exactly this judgment, plus `planet_rgb_gamma8_baseline.tif` (11 GB), **structurally dead since the fill** — it is 93,009 rows and every future composite is 131,072, so no byte-comparison against it can ever run again. 414 → 447 GB free. **One NEW open look question out of the judgment** — a refinement of the 2026-07-20 "ocean floor under ice" decision, not a reversal: the Arctic pack *slightly reads as relief above the sea*. Mechanism (verified in `shade.composite`): the ice whites are light-keyed by `snow_t(light)` where `light` is the **seafloor's** hillshade, so even at full pack the floor's ridges are painted into the ice at full strength — bright-vs-shadow white is exactly how land snow renders mountains, so the eye reads terrain; the 15% translucency (`ICE_MAX_ALPHA=0.85`) carries the *colour* glow, which reads correctly as depth. Answered the same night: **`ice_relief_damp` landed, 0.75 chosen (Rohan)**. The knob pulls the ice's light-key toward its flat-ocean position in proportion to `damp × ice_alpha` — thick pack calms, the marginal fringe keeps its relief, and the colour glow-through is a different channel, untouched (a test pins each property; 10 new, 355 total). Judged on a **five-rung cap A/B** (`experiments/ab_ice_damp.py`, ~21 s a rung — the browser-free pole loop, no globe iteration): rungs measured cleanly linear (mean 2.8/5.2/7.6/10.0 DN on icy pixels at 0.25→1.0, max 29; SH side-effect tiny at 3.9% px / ~3 DN — the toned fringe), so the choice was pure strength. 1.0 read soft; **0.75 kept a touch more surface life**. Shipped via a full `--tiles` pass (twice — the first pass shipped 0.0 because the "ship it" edit changed the provenance COMMENT but not the `KNOBS(...)` value; the post-pass sidecar check caught the drift, which is the verify-the-oracle lesson wearing a new coat: gates that can't see a comment-vs-value split all stayed green) and **ratified on `/globe` the same night**. Open follow-up: the north cap's `pole_taper` (colat < 3°) is a geometric patch for this same disease and is probably retirable now.

### 2026-07-21 (night, later) — the hero/tile colour constants AUDITED at last, and three stale gates in PLAN corrected

Rohan asked why the hero sea-sync and Antarctica were "gated on the pyramid being final". Checking instead of repeating the doc showed **both gates were wrong, and I had propagated one of them.**

- **The hero sea-sync's real dependency is the shared PALETTE CONSTANTS, not the pyramid.** PMTiles is packaging (zero pixels change) and z10 is a *planet* re-fuse the heroes never read — they render from their own 1″/3″ fusions. Evidence: `SEA_STOPS` has not changed since the first tile commit (`15f02c3`) and `SEA_MIN_M` not since the 07-14 sea rework (`185a801`), while **six** tile look changes landed on top (fill sun, snow curve, threading, sea ice, ambient knee, warm shadow floor) — every one moved *light*, never a *ramp*.
- **Antarctica was never gated on the pyramid at all.** PLAN gates it on the snow-curve / ice look, and **that gate is satisfied**: `snow_curve=gamma8` landed 2026-07-17 and the south cap's ice was tuned 2026-07-20. I carried "gated on the pyramid" over from the hero item to Antarctica, where it never appeared — a phrase propagating between items is its own failure mode.
- **The real ordering constraint runs the other way: Antarctica's ice decisions → the hero sweep.** `SNOW_RGB` (tiles) and `SNOW_RGBA` (heroes) are **currently in sync** at E8F1F6, so Antarctic ice work is the one pending item that can break a constant that presently agrees — and the sweep is an overnight, desktop-occupying job you do not want to run twice.

**The audit PLAN has asked for since 2026-07-17 was finally run** ("an audit of the two against each other is worth more than the next lucky catch" — every divergence so far had been found by accident). Result table in ART.md § Hero → tile parameter map. **`LAND_STOPS`, the land range and `SNOW` all MATCH; the three DIVERGED entries are the three already known** (`SEA_STOPS`, sea depth range, `WATER`). **The negative result is the valuable half: there is no undiscovered fourth colour divergence**, so "found so far, not complete" is now closed *for colour*. What stays unaudited is behaviour — the 46°/45° sun split and hero lake depth (a missing feature, not a drifted value).

- **Method note, and it nearly published a false finding:** the first run reported `SNOW` as DIVERGED. `scene_build.py` stores **linear** RGB and `palette.py` stores **8-bit sRGB**, and I had converted with `× 255` instead of the sRGB transfer function. Both sides are E8F1F6. An audit that invents a divergence is worse than no audit — it would have sent someone to "fix" a constant that was already correct, and it is the same class of error as the watermask `< 128` bug caught earlier the same day. **Check the oracle's units before trusting its verdict.**
- `scene_build.py` imports `bpy`, so the audit **parses it with `ast`** rather than importing — worth remembering for any future hero/tile comparison run from the venv.

### 2026-07-21 (night) — cast shadows REJECTED A SECOND TIME, now on the mechanism: attenuating the main sun necessarily erases the modeling it carries

**Decision (Rohan, on the Iran A/B): `shadow_strength` stays 0.0.** *"I don't like this lever, it's still erasing details in the nooks and crannies in the mountain ranges."* The 07-20 rejection was against the `ambient` CLIFF and was therefore re-run under the knee — the knee did remove the collapse-to-one-value failure, and the term was still rejected. **Do not re-run this A/B a third time without a change to the MECHANISM below.**

- **My headline metric was the wrong statistic, and his eye had the right one.** I reported "spread among shadowed pixels 28.49 → 20.96 DN, 74% retained" and called the detail preserved. A **global** std is dominated by *which ridge a pixel sits on*, not by texture inside a gully. Measured as **local** high-frequency energy (image minus a 5×5 box mean) — which is what "nooks and crannies" means — it is **68% kept overall and 55% in fully-shadowed pixels**. Nearly half the fine texture, gone.
- **The mechanism is arithmetic, not tuning.** `per_row_zfactor_hillshade` applies `shaded *= (1 - strength * shadow)`, so the MAIN sun's term is scaled by `(1 - strength)`. Fine detail amplitude is proportional to light amplitude, so it scales with it. Predicted from the two suns' measured local-detail RMS (main 32.29, fill 28.35 at `fill_strength` 0.15): **69% at strength 0.35, vs 68% measured.** The prediction lands within a point.
- **A hypothesis of mine that the measurement KILLED, worth recording so it is not repeated:** I first proposed that shadowed areas lose modeling because the surviving light is the fill, which is "deliberately soft". **False** — the fill carries **88%** of the main sun's fine modeling (28.35 vs 32.29 DN local RMS). A 60° sun is not meaningfully flatter than a 45° one at this exaggeration. The fill is not the problem; multiplying the dominant term is.
- **Therefore: any cast-shadow implementation that works by attenuating the main sun erases fine detail in proportion to its strength.** That is intrinsic to the design, not a value that needs finding. Cycles avoids it because its shadowed areas receive *bounced directional* light (GI), which re-models the surface — our fill is added at fixed strength and cannot compensate for what the attenuation removes. Any future attempt must change that, not the strength.
- **Cost, measured while we were here (kept in PROCESS.md regardless of the verdict):** Iran region 16.73 s → 37.01 s, **+121%**, peak RSS unchanged at 6.3 GB — the wide halo costs time, not memory. The march is `reach_px` full-raster passes, so cost is **linear in `shadow_reach`**: extrapolated to the planet at 0.625 s/Mpx, a pass would be **~2.6 h at reach 300**, ~1.6 h at 150. So the term was also 8× the cost of the composite-side knobs that did ship.
- **What the term DID accomplish:** pure black stayed at **0.000%** at both strengths (the fill floor holds exactly as designed), and terrain selectivity held (Alborz 18.5% / Zagros 11.3% / Kavir desert 4.5% darkened at 0.35). The implementation is correct; the idea is what failed.
- **Pattern across three sessions, and the reason to write it down:** the knee (07-21), the warm floor (07-21) and now this were each judged by eye against a summary statistic of mine, and the eye was right all three times. The common error is choosing a **global** statistic for a **local** perceptual question. Before quoting a metric about how something looks, state which spatial scale the eye is judging at and measure at that scale.

### 2026-07-21 (evening) — `shadow_warmth` 0.55 SHIPS: the hero's warm shadow floor, the first term ported by MEASURING the hero rather than reading its constants

**Decision (Rohan, judged on `/globe`): `shadow_warmth = 0.55` is production.** It is the default in `shade.KNOBS`, the live pyramid was cut with it, and `composite_params.json` already records 0.55 — so the freshness guard sees no drift and nothing re-runs.

**What it fixes was a misconstruction, not a mismatch.** Our tile light is ONE SCALAR per pixel (`base_rgb = color * (light * svf_factor)`), and a scalar multiplies all three channels equally — so our shadows were *mathematically incapable* of differing in hue from our sunlight. The hero has three coloured lights (white sun, white fill, warm `F2E7D5` sky at 0.3) plus GI off rosy terrain, so its shadow hue shifts with light as a consequence of physics. **The 2026-07-17 port copied the hero's light GEOMETRY — altitudes, azimuths, the 0.15 fill ratio — and never its SPECTRA.** That omission is invisible for two of the three lights (sun and fill are both ~white, where a scalar is exactly right) and total for the third, which is why nobody noticed for four days.

**Measured, not assumed** — on `heroes/raw/switzerland.png`, the pure Cycles frame before our SVF post-process. Linear-light R/B, darkest quartile vs brightest, *inside narrow elevation bands* so the elevation-keyed ramp colour is constant by construction: **+77% / +98% / +82% / +61%** at 600–900 / 1200–1500 / 1800–2100 / 2400–2700 m. Verified as lighting rather than a binning artifact by a decile sweep in one band — R/B falls monotonically across all ten (6.79 → 2.94). Ours was **exactly 0%**.

- **The tint's derivation, and what it revealed:** the sky's own chromaticity explains only **1.334×** of the measured ~1.80×. The residual is **warm GI bounce off the warm land ramp** — so `SHADOW_TINT` is the world colour deepened to the measured ratio (`WORLD_RGBA ** 2.0373`). This is also **an independent explanation for why the occlusion sweep came up empty on 07-20**: a greyscale SVF term darkens, but it structurally cannot carry the *colour* of the light it stands in for.
- **The design decision worth keeping: the tint is normalised to luminance 1.0, so the knob moves HUE ONLY.** A warm term that also brightened would be the twice-rejected `ambient` raise wearing a different hat, and no A/B could have separated the two effects. Confirmed on real terrain — mean luminance moved **+0.23 DN at worst** across four regions.
- **Self-regulating across terrain, like the fill sun**, validated at 0.55 on four regions before any planet pass: px moved 35.1% (Alps) / 31.3% (Scandes) / 14.9% (Sahara) / 2.5% (SW Greenland), dark-quartile R/B +17.9 / +13.1 / +6.9 / +1.0%, and the **bright quartile +0.0% at every site** — flat lit ground does not move anywhere on Earth. That is the Nepal-trap check.
- **The ice margin does not seam** — the named risk was that warming land while snow stays deliberately blue would create an edge that never existed. Land within 4 px of ice moves 8.08 DN vs 7.81 DN for land >25 px away, and warms *less* in R/B (+10.3% vs +11.6%).
- **A null run worth recording:** the first Greenland attempt used chunk `w050_n70`, which is pure ice sheet and ocean — **0.00% of pixels moved**, testing no land whatsoever. It would have been reported as "Greenland clean" off a run that examined nothing. Re-run on `w050_n60`. *Check that a test region contains the thing being tested.*
- **1.0 was rejected on Alpine crops as too copper**, so 0.55 is 55% of the measured hero. The value is still anchored to a measurement even where it departs from one — the alternative was an unanchored art dial.
- **Cost:** composite 878.0 s vs 807.5 s for the knee pass — the tint is about **+8%** on the composite stage. Pass total 20:44.
- **No test fallout**, in contrast to the knee's five broken tests: the term is confined to land below full light, and skips ocean, inland water and snow (all pinned).

### 2026-07-21 (later) — the hillshade-side lever is DROPPED: its premise was consumed by the knee, and every hillshade dial turns out to be hero-anchored

Rohan asked what the hillshade-side lever actually involves and whether the hero has an equivalent. Answering the second question changed the answer to the first, and the item is dropped rather than scheduled.

- **The premise was measured, not assumed.** The lever was queued on "a composite tone curve can only redistribute what the hillshade produced — 18.07% of land arrives below the clip carrying nothing", written while the knee was expected to ship at 0.15 or not at all. At the shipped 0.30 the transfer function says otherwise: sub-floor terrain `[0.0, 0.5]` now occupies **0.156** of light range where it occupied zero, which is **45% of the contrast-per-unit that lit ground gets**. The information is compressed, not absent. The argument the lever rested on no longer holds in the form it was written.
- **The cost the lever would add lands on the same axis the knee already spends.** Lit terrain's range is compressed to **0.688** by the knee, and `fill_strength` compresses too (max DN 255 → 226 at 0.15 → 213 at 0.25 — `combine_fill`'s rescale is the mechanism). Raising the fill on top of the knee is two compressions in series, at ~32 min per value tried.
- **The decisive argument, and the one I had not assembled before: every hillshade dial is a port of a hero constant.** `EXAG` 15 = `render_prep.EXAGGERATION` 15; `alt` 45° ≈ `SUN_ROTATION`'s 46°; `fill_strength` 0.15 = `FILL_STRENGTH 0.45 / SUN_STRENGTH 3.0` exactly; `FILL_ALTITUDE/AZIMUTH` = `FILL_ROTATION` exactly. **`fill_strength` 0.15 is therefore not a tuned value — it is the single principled anchor the tile look has**, and "pull the hillshade-side lever" means "break the anchor" on a pipeline whose entire purpose is to look like the heroes. Recorded as a table in ART.md § Hero → tile parameter map so this is looked up, not re-derived.
- **The heroes are not the thing to tune.** They are the reference the tiles are measured against, they are approved, and a change means re-rendering 204 countries. If tiles and heroes disagree, the tiles are wrong by definition.

**Reframed: the useful question is not which lever to pull but which hero TERMS were never ported.** Three, in order of promise: (1) **cast shadows** — implemented 2026-07-20, sitting at `shadow_strength=0.0`, a true hero term (`SUN_ANGLE 12°` + ray-traced shadows); (2) **a warm shadow floor** — the hero fills shadow with warm sky (`WORLD_RGBA F2E7D5` @ `WORLD_STRENGTH 0.3`) plus a white fill, so shadowed ground shifts *hue*, while ours multiplies the land ramp by a scalar and only drops *value*. **`KNOBS["warmth"]` is not this** — it tints all land uniformly regardless of light. Composite-side, so ~19.6 min per iteration, the cheapest of the three; (3) **GI**, whose stand-in `svf_strength` was already falsified as the softness term.

**The warm-shadow term was then MEASURED the same day, and it is the largest unported difference found so far.** Sampled on `heroes/raw/switzerland.png` — the pure Cycles frame, before our SVF post-process — with ocean/water/snow excluded and every comparison made *inside* a narrow elevation band, because the land ramp is elevation-keyed and shadowed pixels sit disproportionately on steep high terrain (comparing all-dark vs all-light would have measured the ramp, not the light). Linear-light R/B, darkest quartile vs brightest: **+77% at 600–900 m, +98% at 1200–1500 m, +82% at 1800–2100 m, +61% at 2400–2700 m.** Verified as lighting rather than a binning or alignment artifact by a decile sweep inside one band: R/B falls **monotonically across all ten deciles** (6.79 → 2.94), smoothly. **Our composite's shift is exactly 0% by construction** — `land = base × light`, then saturation (which scales with luminance) and `warmth` (fixed per-channel factors), so R/B is light-invariant at every pixel. `KNOBS["warmth"]` cannot substitute: it is uniform, not light-keyed. Numbers and method in ART.md § Hero → tile parameter map.

**A confound caught mid-check, worth recording because it would have inflated the exact number being sought:** the first run filtered masks with `< 128`, but `watermask_aea.tif` is **classed 0/2/3**, not 0/255 — so every lake passed as land. A sunlit lake (`WATER_RGBA` R/B ≈ 0.54) lands in the *lit* quartile and drags its R/B down, inflating the shift. Corrected to a nonzero test with nearest-neighbour resampling (averaging a class raster invents classes); the result moved only 77.16% → 77.33%, so the confound was real but small. The check was worth running anyway — an unchecked version of it would have been indistinguishable from a result that *was* driven by it.

**Method note.** The lever survived two sessions in PLAN because it was never premise-checked after the condition it assumed changed. The trigger that caught it was a question about the *hero*, not about the lever — asking what the reference does is what exposed that our dials were already equal to it.

### 2026-07-21 — `ambient_knee` 0.30 SHIPS: the eye overruled every metric (again), and the test suite exposed how far the knee reaches

**Decision (Rohan, judged on `/globe`): `ambient_knee = 0.30` is production.** It is now the default in `shade.KNOBS`, so the pyramid cut at 23:32 the previous night is the shipped look and stays fresh — `composite_params.json` already records `0.3`, and flipping the constant to match means the guard sees no change.

- **My recommendation was 0.15 and it was wrong.** The sweep's local-contrast std fell 3.7 points at 0.30 and mean brightness rose 12.1 DN, which I read as "reproduces the twice-rejected ambient-raise wash by another route". On the sphere it does not read as a wash — it reads as mountains getting their form back. **This is the same proxy that lost the 2026-07-08 fill-sun A/B**, where "every metric said 0.62 was best and every metric was wrong". Local-contrast std is now **twice-failed** as a stand-in for perceived softness; it is not evidence about the look, and it should not be quoted as though it were.
- **Why the metric mislead is structural, not bad luck:** std over the whole frame cannot distinguish *contrast that carries shape* from *contrast that is a clipping edge*. The hard clip manufactures enormous local contrast at the 90.2 DN cliff — a hard boundary between "shaded terrain" and "one flat value". Softening the cliff **removes** that contrast, which the metric scores as a loss and the eye scores as a gain. Any metric that rewards the artifact will keep voting for the artifact.
- **Rohan's process is what produced the right answer:** he refused to judge from region crops and asked for a full planet pass — *"I need to see it with my eyes"*. A 19:32 pass was the cost of not shipping the metric's answer.
- **An independent byte-level signal, noticed after the fact:** the new pyramid is **14 G vs 15 G** at identical tile count and encoder. The images compress better because a population of dark pixels moved toward a common brighter value — the wash, visible in the file sizes. It confirmed the *direction* the region metrics reported while saying nothing about whether it was good, which is the correct division of labour between a measurement and a judgement.

**The knee's reach is global, and the test suite is what proved it** — five tests broke on the default flip, none of them about the knee:

- **Full light is no longer 1.0.** The softplus sits strictly above its input, so a pixel at `hs == flat` lands at 1.053, and flat lake water rendered `(149, 206, …)` instead of `WATER_RGB (142, 198, 196)` — **+4.9% on every fully-lit pixel on the planet**. The knee is not a shadow-only tool; it lifts the entire curve, most at the bottom and by ~5% even at the top.
- **The snow window's top saturated.** `test_snow_curve` fed light 1.035 to prove the curve knob reaches the pixel; under the knee that input lands at 1.081, past `snow_hi_pt` 1.05, so gamma8 and linear rendered identically. The knob was fine — **the test's input had left the range the test believed it was in**, which reads exactly like a broken knob.
- **Root cause of all five: tests constructed a known light as `flat * light`**, exact only while the floor was `np.clip`. Fixed with one analytic inverse, `conftest.hillshade_for_light`, which inverts the softplus and raises rather than approximates when asked for a light at or below `ambient` (unreachable by construction). It carries its own round-trip test — a silently wrong oracle makes every assertion it feeds silently wrong.
- **The floor is now asymptotic: no land pixel can sit AT `ambient` any more.** Darkest reachable light is **0.5519** (0.5545 after exposure) against `snow_lo` 0.55 — so the bottom of the snow ramp is no longer addressable *by light*. **I predicted this would lift shaded snow off `SNOW_SHADOW_RGB` and it does not**: the margin is 0.9% up the ramp = 0.50/0.38/0.24 DN, and the shipped gamma8 takes `0.009**8` to zero. Pinned in `test_the_knee_does_not_lift_snow_off_its_bottom_stop` **because it is a floor with no headroom** — a future knee raise would bleach shaded snow, and that test is where it will surface. (Asserting the effect before measuring the pixel was the third time this session that a predicted *effect size* was wrong while the mechanism was right.)

**Still open and unchanged by this:** `shadow_strength` stays 0.0 pending its own verdict; the hillshade-side levers (`fill_strength` / EXAG) remain the untried real lever for dynamic range, since a composite tone curve can only redistribute what the hillshade produced; the planet SVF's missing `cos(lat)` is still proven and unfixed.

### 2026-07-20 (evening) — chasing the hero's "softness" into the tiles: cast shadows land, occlusion is FALSIFIED, and the two shade paths were occluding at different resolutions

**The question that started it (Rohan):** can the Blender renders' softness reach the globe without the browser paying, and can the tiles get the hero's exaggeration and crispness? Answering it required comparing the hero and tile paths directly — the first time anything did — and the comparison produced more than the answer.

**Framing, which turned out to matter more than any result.** The question is three questions with three different answers. *Softness* is view-independent (a Lambertian surface under a fixed sun looks the same from every angle), so essentially all of it is bakeable at zero browser cost. *Exaggeration* already matches — `tile/shade.py`'s `EXAG = 15.0` is the hero's locked 15× — but as a hillshade z-factor, i.e. **shading** exaggeration, not **geometry**. Geometry buys cast shadows, silhouette and parallax; only the first is bakeable, and at globe scale the other two contribute almost nothing, so the expensive third is the third we don't need. *Crispness* is neither: the planet is fused at 10″ (308.7 m) and z8 is 305.7483 m/px, so **the pyramid is exactly source-limited with zero headroom**. The hero's edge is not a finer output grid (India is ~430 m/px, *coarser* than z8) — it is a 3″/1″ source supersampled through a raytracer at 4,096 samples, folding sub-pixel relief into each pixel as tone.

**Cast shadows: built, and they work.** `pipeline/render/cast_shadow.py` marches one azimuth (the sun's) tracking the steepest horizon — deliberately *not* the SVF, which averages 16 azimuths to model ambient sky. Two properties are inherited rather than invented: the penumbra is `SUN_ANGULAR_DIAMETER = 12.0`, lifted from `scene_build.SUN_ANGLE`, because the horizon takes exactly the sun's angular diameter to cross the disc — no post-blur, no invented parameter; and the shadow attenuates **the main sun only**, so a fully-occluded face lands on the fill floor (~28 DN, analytically pinned) instead of black. That is the 2026-07-17 fill-port invariant, upheld deliberately now that it is no longer free. Streaming needed the halo widened from 1 row to the shadow reach — a cast shadow is the one non-local term here — and window-invariance still holds, tested with windows *smaller* than the reach so a wrong halo cannot pass. Rows edge-replicate (the north pole must not shadow the south); columns wrap, because the planet is cyclic in longitude.

**Iran A/B (`e040_n30 e050_n30`, 32.4 Mpx, 37.8 s per run).** Pure black **0.000% on both sides** — the risk that mattered did not materialise. Only **7.45%** of pixels moved >1 DN; mountains took it (Alborz 20.7% of pixels darkened >5 DN, Zagros 16.0%) and bright flat desert did not (Kavir 0.68%). **The term inverts the Nepal trap by construction**: no relief, no occluder, so it cannot blow out flat bright ground the way every other knob does.

**Rohan's verdict: 1.0 is too consuming — detail gone in the mountains.** Correct, and the mechanism is not "too strong". `composite` does `light = clip(hs/flat, ambient=0.50, hi)`, and with `flat = 255·sin(45°) = 180.3` that floor bites at **90.2 DN** — everything below collapses to an identical flat 0.50. The shadow pushed **6.21% of land** under it; those pixels had a control spread of **std 36.0 DN**, all flattened to one value. **The clamp is a cliff, not a slope**, so turning strength down barely helps: 0.50 still causes 59% of the damage (3.66% of 6.21%). **`shadow_strength` is therefore the wrong lever, and is left at 0.0** — the live pyramid is untouched. Independently measured and pre-existing: **18.07% of Iran's land was already under that clamp with no shadow at all.**

**The tooling was lying, by 12.9×.** The region path sized its sky-view downsample with a region-local `long_edge = 2400` (≈760 m/px of ground at Iran); the planet used `SVF_LONG_EDGE = 4096` over a raster 18× wider (≈9,784 m/px, horizon reach ~411 km, finest resolvable feature ~20 km). **The region exists to predict the planet**, so every region A/B ever run — including the tuning that set `svf_strength` and `svf_threshold` — was judged at a resolution production does not have. Neither number was wrong locally, which is exactly why nothing caught it: 2,400 is a sensible preview size and 4,096 a sensible global one. **The defect existed only in the relationship, and nothing expressed the relationship.** Fixed by making it unrepresentable rather than merely correct: one `sky_view.OCCLUSION_TARGET_M_PER_PX`, with `occlusion_shape()` deriving both paths' downsample from that single **ground** scale. `SVF_LONG_EDGE` deleted. Production byte-identical — the planet shape is still (2907, 4096), pinned by test.

**A real bug, now proven rather than suspected:** the planet occlusion feeds `horizon_svf` a **map-unit** scale (`Z8_RES × 32`), but ground metres in Web Mercator are `Z8_RES × cos(lat)`. The horizon run is understated by `1/cos(lat)` — **1.22× at 35°N, 2.00× at 60°N, 3.86× at 75°N** — so high latitudes are systematically **under-occluded**. The global affine renormalisation provably cannot absorb a latitude-varying error: same grid, two scales, occ mean **0.3213 vs 0.2934**. The region path and the hero path are both ground-correct (the hero shades in an equal-area projection where map units *are* ground metres), which is what makes this an oversight rather than a choice. **Unfixed** — it changes production pixels and needs a per-row ground scale, the hillshade's z-factor trick.

**OCCLUSION AS THE SOFTNESS TERM IS FALSIFIED — the entry's most useful result.** Predicted (by Claude, before measuring — see the correction below) that finer occlusion was what "softness" named. A 6-run sweep, occlusion target {9784, 2000, 760} m/px × `svf_strength` {0.20, 0.35}, says otherwise: mean luminance moves at most **−3.01 DN** across the whole grid, and **local (32 px ≈ 10 km) contrast moves the WRONG WAY — 22.190 → 21.507 as the term gets finer and stronger.** It darkens valleys uniformly; it does not add form. **Do not re-litigate occlusion resolution or strength as a route to softness.** `svf_strength = 0.20` behind `svf_threshold = 0.45` caps the term's contribution so hard that its resolution is close to irrelevant — which also means the 12.9× divergence, though real and worth fixing, was never doing much visual damage.

**What that leaves.** Two candidates, in cost order: **(1) the `ambient = 0.50` clip itself** — a hard clamp discarding all hillshade information on 18% of land, which is a bigger legibility lever than either term tried here and is a one-knob region A/B (note: *raising* ambient was swept and rejected twice, 07-08 and 07-17 — the move here is softening the **knee**, not lifting the floor, which is a different change); and **(2) the supersampled re-fuse** — shade at 2.5″/5″ and box-filter the **shaded RGB** down onto the z8 grid, never the heights. That reproduces the hero's actual mechanism, and 2.5″ is 16× the pixels (the 31 GB height raster → ~500 GB against 415 GB free), so 5″ (2×2 SSAA, ~124 GB) is the affordable form. It also shares its output with any future terrain-RGB pyramid, so Tier 3 wants the same re-fuse.

**The ambient knee, built and measured (same evening).** `shade.apply_ambient_floor` replaces the `np.clip` lower bound with a softplus; `ambient_knee = 0.0` is the hard clip, **bit-identical, not an approximation**. It is emphatically *not* the twice-rejected `ambient` raise (07-08 washed rosy and flat; 07-17 every metric said otherwise and every metric was wrong) — the floor stays exactly where it is and only the *arrival* at it changes. Iran region sweep, measured **inside exactly the pixels the clip had flattened** (16.61% of frame): spread std **8.24 → 8.32 (knee 0.05) → 9.34 (0.15) → 10.76 (0.30)**. So it genuinely restores form. But the cost is global: mean luminance **159.83 → 160.02 → 162.33 → 171.93**, and local (32 px) contrast **22.190 → 21.997 → 20.793 → 18.493**. **At 0.30 it reproduces the washed-flat failure of the rejected ambient raise by a different route** (+12.1 DN mean, −3.7 local contrast); 0.05 is a no-op; **0.15 is the only defensible candidate and is a modest win, not a transformation.** Rohan declined to judge on the region metrics — *"I don't trust your judgement of brightness and local contrast exactly, I need to see it with my eyes"* — correctly, since local contrast averaged over 32 M px is a summary statistic and not a look; a planet pass at 0.30 was run for judgment on `/globe`.

**The structural read that outlives the knob:** the composite can only redistribute what the hillshade handed it. 18% of land arriving below 90 DN is a **hillshade** consequence — `arctan(15 · gradient)` at EXAG 15 drives any moderately steep face past a 45° sun. `fill_strength` and exaggeration decide *how much* lands there; the clip's shape only decides how it is spread. **Do not expect a composite-side tone curve to fix a hillshade-side dynamic-range problem.**

**Two pipeline fixes rode along.** (1) The occlusion resolution reached **no freshness record** — it was a module constant that visibly changes `planet_rgb`, so moving it left a stale pyramid looking fresh (the `WATER_RGB` trap again); `composite_params` now records `occlusion_target_m_per_px`. (2) **`--knob` added to `shade_planet`**: a planet look change previously meant *editing the constant in source*, so an experiment and production shared one source of truth. Overrides are freshness-safe by construction, since both params records serialise KNOBS.

**COG overviews: PROPOSED, then WITHDRAWN on this log's own evidence — a near re-litigation of the gdaladdo entry.** Claude proposed adding overviews to `height_3857.tif` to accelerate `global_occlusion`, and Rohan challenged it from memory of the 2026-07-16 deletion. Checking showed **two rejections, neither identical to the proposal**: `gdaladdo` on `planet_rgb` was deleted because **`gdal raster tile` never reads source overviews** (consumer-specific — and that same entry states *RasterIO does auto-use overviews for any downsampled **source** read*, which is exactly `global_occlusion`'s call path, so the mechanism was sound); and `--overview-resampling=average` was rejected for the **tile pyramid's** z0–7, a different raster and consumer, though its lesson — resampling silently changes output, pin it by test — stands. **What killed it was the entry's headline, which Claude walked past: *"optimise only after proving the stage is on the critical path; 'it runs every pass' is not that proof."*** The SVF has been **lazy-guarded since 07-17** — 0.29 s on a fresh pass, and it only runs when the composite is *already* stale, i.e. when 10–20 min of composite is being paid anyway. Ceiling ~2:44 off a ~17–26 min pass, minus minutes to build overviews on a 31 GB raster. Verified `height_3857.tif` has no overviews today, so the saving is real — just too small to spend attention on. **Overviews are not banned** (`fuse_heightfield.build_overviews` is real and kept): the rule is **overviews pay only where a consumer actually does reduced-resolution reads**, and here the only such consumer is guarded.

**Tier 3 inherits one trap:** baked cast shadows are computed against 15× exaggerated relief, so a MapLibre terrain layer displacing at any other exaggeration will disagree visibly with its own shadows. Match `terrain.exaggeration` to the bake, or don't bake shadows.

**Storage, for any future supersampled re-fuse.** Measured: `height_3857.tif` is **31 GB** at 10″ (deflate; 48.8 GB raw), so 2.5″ ≈ **496 GB** and 5″ ≈ 124 GB against ~415 GB free, with the hillshade scaling too (~12 GB → ~195 GB at 2.5″). **The fine fuse should be a TRANSIENT, not a stored product** — fuse a band, shade it, box-filter the RGB onto the z8 grid, discard the band; peak storage is one band and `planet_rgb` stays ~11 GB. That is what makes 2.5″ affordable at all; as a materialised product only 5″ fits. **Remote COG is the wrong shape for this**: COG buys *selective* reads, our pass is a full sequential scan (2–3× per pass), and 496 GB over gigabit LAN is ~75 min of streaming before any compute — it would make a ~35 min pass I/O-bound.

**Method note, recorded because it is the recurring failure and it recurred.** Claude asserted a predicted effect size for the occlusion term across two messages before measuring it, and the measurement contradicted it. It also used "SVF" and "AO" as two names for one term, manufacturing a decision Rohan had to make between two things that were the same thing. Both are the *assert-before-measuring* pattern PLAN already names; naming it is evidently not sufficient to prevent it.

### 2026-07-20 — pipeline hardening: build_tiles guarded and cutting clean, plus the About page credits and lake-depth note

Three latent risks off the PLAN open-items list, closed as the piece after the south cap merged (PR #7). Main was on latest; all three came straight from PLAN's own "known but unfixed" notes.

- **`build_tiles` was the one unguarded stage.** Every other stage skips when fresh (`is_stale`), but the tile cut always re-ran (~3:44): the staging dir is renamed away on success, so GDAL's `--resume` started from empty and the live pyramid had no completion stamp. Fix = mirror the existing discipline — `mark_done(live)` stamps `tiles.done` after the atomic swap, and a pure `tiles_are_fresh(planet_tif, out)` skips the cut when `tiles.done` is newer than **`planet_rgb.done`** (keyed off the `.done`, never the `.tif` — GDAL stamps its target at write-start, the exact trap `is_stale` exists to avoid). Proven end-to-end: after the first cut created the sentinel, a fully-fresh `--tiles` re-run skipped in **0.4 s** (vs the 3:33 re-cut).
- **`--resume` dropped — every cut is now a clean full cut.** GDAL writes each png in place, and `--resume` skips existing files by existence *without reading them*, so a png truncated by a mid-write kill would survive into the pyramid (the 07-15 cut *was* OOM-interrupted and resumed, so this was a hit-before failure mode, not a hypothetical). `build_tiles` now `rm -rf`s any partial `tiles_new` first and cuts without `--resume`. **This trades CLAUDE.md's "a crash at tile N must not restart the world" for guaranteed integrity** — the right trade here: the tile cut is ~3:44, not the multi-hour composite/fuse the convention protects, and re-cutting from empty on a rare crash is cheaper than ever trusting a partial tile. *Deleting the unsafe mechanism beat bolting a verifier onto it* — the considered alternative (scan `tiles_new` for pngs missing the `IEND` trailer before resuming) was ~30 lines more code for a strictly worse guarantee.
- **About page: credits completed, lake-depth epistemics finally written.** Added NSIDC-0791 snow persistence, RGI 7.0 glaciers (CC-BY 4.0), and **GLOBathy — which is CC0, not the CC-BY the plan assumed.** That was verifiable, not guessed: `download_globathy.py` pins figshare v1 and *aborts* if the licence ever stops reporting CC0. A "Lake depth" note now states the honesty the pipeline always carried in `lake_depth.py`: the depth *shape* is a synthetic cone for all 1.43 M lakes (0.53 correlation on the Caspian, the one checkable lake), the *scale* is surveyed for only 0.8% of them, and uniform modelled treatment is deliberate (surveyed-only would render survey funding as geology — 85% are in the USA). The globe's raster attribution gained GLOBathy + OSI SAF. **The "Snow" step still credits ESA WorldCover** (the hero mask) rather than the tiles' NSIDC-0791 — left as-is by decision (Rohan): the "How it's made" steps tell the hero-render story, and the Data section now carries the full per-tier truth.

### 2026-07-20 — sea ice over bathymetry: OSI SAF chosen, the soft-frequency look, ICE_LO tuned decline-aware, and the recent-data check

The sea-side mirror of land snow, and the surface truth the 2026-07-18 polar-cap decision was waiting on: the pole is deep bathymetry UNDER floating sea ice, so ice is a translucent white overlay driven by an ice-frequency climatology, gated on `ocean` exactly as snow is gated on `~(ocean|water)`. One shared `shade.composite` blend → it lands on the Mercator tiles, the region renders, AND the polar cap by construction.

- **Dataset — CHOSEN: OSI SAF Global Sea-Ice Concentration CDR, OSI-450-a v3.0** (`conc_450a_files`, monthly-mean, EASE-Grid 2.0 25 km, BOTH hemispheres, var `ice_conc` %). **Anonymous** THREDDS/FTP (met.no), EUMETSAT free — no NASA Earthdata login and no ~60-day token churn, the deciding factor over the equivalent NSIDC CDR. We reduce the record to ONE number per pixel: **annual frequency-of-occurrence** = fraction of monthly means with concentration ≥ 15% (the standard ice edge), over the **1991–2020 WMO 30-year normal** (wholly inside OSI-450-a → no splice with the interim record). Packed IDENTICALLY to snow persistence (uint16 ×1e-4, fill 65535) so `render/seaice.py` is a structural copy of `snow.py`. Pole hole pre-filled by OSI SAF → the cap reaches 90° with no special-case.
- **Datasets REJECTED (the log that stops re-litigation):**
  - NSIDC/NOAA CDR **V5** — retired June 2026 (dead).
  - NSIDC/NOAA CDR **V6** (G02202 v6, released 13 Jan 2026, AMSR2 input from 2025) — equal-quality 25 km PMW CDR, but delivered via `earthaccess`/CMR (our snow Earthdata-token path). Lost to OSI-450-a **purely on anonymous access + no token churn**.
  - NOAA **Sea-Ice Climate Normals 1981–2010** — NH-only (bbox south edge 31.1°N, verified) → no Antarctica.
  - U.Bremen **AMSR2 6.25 km** / **MODIS-AMSR2 1 km** — 2012+ single-sensor, daily cloud-gappy snapshots → no stable 30-yr climatology. **This re-examined and overturned the parked 2026-07-18 lean toward "MODIS-AMSR2 1 km"** (its own "wants a climatology" note argues against it). Kept only as a *future* high-res-edge upgrade.
  - **Copernicus CDS** — the same OSI SAF data behind a CDS-API-key wall. **Copernicus Marine GLORYS** — reanalysis, heavier, account-walled. **MASIE** — NH-only binary extent. **NSIDC Sea-Ice Index median edge (G02135)** — a crisp edge LINE, anonymous + tiny, kept in reserve as an *alternative look*; not chosen since Rohan picked the soft fill.
- **The look (composite blend, `tile/shade.py` + `render/palette.py`).** `ice_alpha(freq)` is a plain smoothstep, **NO latitude ramp** — unlike snow, whose latitude ramp suppresses mid-latitude seasonal snow; the ice-frequency field already encodes where ice is. Ice reuses snow's light-keyed white but a **notch cooler + dimmer** — `ICE_RGB (212,228,240)` / `ICE_SHADOW_RGB (156,184,210)` vs snow's `E8F1F6`/`B0C7DB` — so floating sea ice reads distinct from the land ice-sheet **without a hard blue/white split** (a bold split was rejected as gimmicky and off-Patterson; the coastline + relief carry the rest). `ICE_MAX_ALPHA=0.85` keeps even the perennial pack slightly translucent so the deep bathymetry glows through (the "ocean floor under ice" reading, Rohan). **Edge smoothing:** the coarse OSI **25 km land mask** left blocky bare-sea patches at coasts, where our fine `ocean_3857` keeps pixels OSI marks land (freq 0) — fixed in `download_seaice.build_climatology` with `rasterio.fill.fillnodata` (nearest ocean freq into land cells) + a Gaussian (`SMOOTH_SIGMA_PX=2.0` native EASE2 px). The open-ocean edge was already smooth — diagnosed via a grayscale freq dump; a masked/normalised blur did NOT fix it because it will not cross the coast.
- **ICE_LO tuned decline-aware, 0.25 → 0.55.** At 0.25 (band 0.40) we painted ~the winter-MAXIMUM extent and the alpha saturated seasonal ice as solid as perennial — Rohan on the globe (mobile): "too much sea ice, even around Canada." Diagnosed with data, NOT a bug: the frequencies are physically correct (Canadian Archipelago 0.97 = genuine multi-year ice, Hudson Bay 0.64 = iced ~64% of the year). Raised `ICE_LO` to 0.55: perennial pack solid, marginal declining seas (Hudson/Baffin/Kara/Laptev) fade to open teal — doubles as decline-aware. Previewed A/B before committing; confirmed on the globe.
- **The recent-data check (does "current" move it? — no).** Rohan asked whether a current-state dataset would justify going bleaker (he suggested 0.45 — **corrected: lowering ICE_LO ADDS ice**; the bleaker direction is HIGHER, and the threshold cannot shrink the *saturated* perennial core anyway — only move the seasonal fringe). Pulled the one clean candidate — **OSI-430-a v3.0 ICDR** (`conc_cra_files`, `ice_conc_*_ease2-250_icdr-v3p0_YYYYMM.nc`, 2021→2025-09-30, same EASE2 grid + same algorithm, anonymous) — and computed the same NH metric over 1991–2020 vs 2011–2020 vs 2021–2024. **Result: minimal for what we render.** Perennial core unchanged (89°N/Lincoln/Beaufort still ~1.0/0.94); change confined to the seasonal margins (Barents −0.11 now annually ice-free, Hudson −0.08, Kara/Laptev −0.04); mean Δ over the Arctic ocean domain −0.007. At ICE_LO=0.55 the iced extent shrinks only **−4.2%** (invisible). The genuine decline signal IS present — the near-perennial core AREA (freq ≥ 0.85/0.95) shrank **−9/−10%** — but it sits ABOVE 0.55, so it barely touches the picture. **Why this metric can't show the Wikipedia collapse:** annual frequency is winter-weighted; the dramatic Arctic decline is the **September minimum + ice thickness**, which "fraction of months with any ice" structurally does not encode. Showing THAT would need a September-specific climatology — a different derivation, and it would render the poles far more open. **Decision: keep 0.55 on the 1991–2020 normal; note the reference period on About.** (Recent files reclaimed after measuring.)
- **North cap rebuilt into the pipeline** (`pipeline/tile/cap_render.py`; the original AEQD recipe lived only in a reboot-wiped /tmp scratchpad): AEQD grid (lat_0=90, inscribed edge 78°N = `polarCapSpike.ts` `TEX_EDGE_LAT`, 4096²), reprojecting height/ocean/water + snow persistence + **sea ice** onto the cap; per-pixel light azimuth `AZ−lon` / `FILL_AZIMUTH−lon` (longitude via an exact pyproj AEQD→4326 transform — near the pole "NW" turns with the meridian); snow_a via the CONSTANT high-lat thresholds (the whole cap is > `RAMP_LAT_HI`, so `snow_alpha`'s Mercator per-row latitude would be wrong here); ice_a needs no latitude term → valid on AEQD; `inland_water` mask (never `astype(bool)` — the 2026-07-19 disc-glow trap); SVF off. **Coastline baked** (`_bake_coastline`): a subtle DARK steel-blue line (`COAST_RGB (96,122,142)`) — a WHITE coast vanishes between white snow and white ice — separates the land ice-sheet from sea ice where MapLibre's Mercator vector borders cannot reach the pole. Orientation verified vs the frontend UV.
- **Landed (git uncommitted — Rohan's to commit):** new `acquire/download_seaice.py`, `render/seaice.py`, `tile/cap_render.py`, `tests/test_seaice_warp_once.py` (15 tests: pure unpack/alpha + warp-once byte-identity on the real source); modified `tile/shade.py` (ocean-gated ice blend), `tile/shade_planet.py` (banded warp-once + per-window plumbing + deps/params), `render/palette.py` (ICE_RGB/ICE_SHADOW_RGB), `tests/test_shade_planet.py`. Full recomposite + tile cut landed (62,177 tiles live; `tiles_old`/`tiles_preice` rollbacks). pyright 0 / suite green.
- → PLAN Phase 3 cap item · ART § Sea ice — TILES + caps · INVENTORY (raw `seaice/` + `seaice_3857.tif` + `work/cap/`) · PROCESS

### 2026-07-19 — CI gates the web layer; the frontend manifest gets a typed wrapper so astro check runs without it

- **Context:** the frontend had ZERO CI coverage — `ci.yml` ran only pyright (`pipeline/` only) + pytest on `pull_request`. The vitest suite (capability + the new countryHighlight guards), `astro check`, and even `tests/` type-checking never ran on a PR.
- **Added a `web` job:** `pnpm/action-setup@v6` (pnpm 11) → `actions/setup-node@v6` (Node 24, pnpm cache) → `pnpm install --frozen-lockfile` → `pnpm check` (astro check) → `pnpm test` (vitest). Verified pnpm 11.15.0 reads the committed pnpm-10 `lockfileVersion 9.0` lockfile cleanly ("Lockfile is up to date"). Node pinned **24** (Rohan; matches local dev; the `engines` floor is 22.12 if we ever want a floor/matrix).
- **Fixed the pyright step:** `uv run pyright pipeline/` → `uv run pyright` (no path), so it uses `[tool.pyright] include = ["pipeline","tests"]` and covers `tests/`. The explicit-path form silently skipped test type-errors in CI — the exact "tests were never checked" trap CLAUDE.md warns about, reintroduced at the CI boundary.
- **The manifest snag + the chosen fix.** `astro check` failed on CI: the 3 pages statically import `web/src/data/countries.json`, which `gen_manifest.py` DERIVES from the rendered hero variants + the NE shapefile and which is gitignored (root `data/` rule) → absent on a clean checkout, and CI can't regenerate it (no assets). Options weighed: (a) commit the manifest — rejected, reverses the deliberate "code/config only, no generated data" policy; (b) drop astro check — rejected, loses the frontend type-check; (c) **CHOSEN — a typed wrapper** `web/src/lib/manifest.ts`: explicit `Country`/`Manifest` interfaces + one `@ts-ignore` on the generated-JSON import. The pages import `{ manifest, Country }` from it, so `astro check` type-checks consumers against the contract without the file present, while the real `astro build` still reads the real JSON (the `as unknown as Manifest` cast erases — runtime unchanged). Keep the interfaces in lockstep with gen_manifest.py's payload.
- **The verification lesson (it cost a round-trip).** The first CI sim `rsync`'d the working tree, which COPIED the gitignored `countries.json`, so it passed while real CI (clean `git checkout`) failed on the missing file. **Replicate CI by removing gitignored files (or `git archive`), never rsync of the working tree.** The wrapper was then verified the right way — real JSON moved aside: `pnpm check` 0 / `pnpm test` 26, both with it absent and present.

### 2026-07-19 — hover-highlight pole artifacts: polygon-clip stray line and tile-buffer fill double-paint

- **Context:** with the polar cap in place, scrutinising the pole-down view exposed two artifacts in the country hover-highlight — both invisible at normal (oblique) angles, so easy to miss in review. They are *separate* bugs with *separate* causes; the first masked the second.
- **Bug 1 — a stray gold meridian across the hovered country (Russia, Canada).**
  - Cause: the hover outline (`country-hl-line`/`-casing`, gold `#eca834`) was a `line` layer over the `countries` POLYGON source. geojson-vt clips a huge polygon at an internal tile boundary and CLOSES the ring along the cut; a `line` layer strokes that phantom closing edge. (A `fill` doesn't; the white `borders` don't — they're a LINE source, and clipping a line just trims it.)
  - **Rejected first attempt — `maxzoom:0` on the source. It made it WORSE:** one over-zoomed z0 tile whose own clip/simplification edges are then stroked at *every* zoom and angle (stray line through Russia, US, Canada, China, India). Reverted. Recorded so it is never retried.
  - Fix: `outlinesFrom()` re-expresses each in-scope polygon as its boundary lines (every ring → `MultiLineString`, ADMIN carried), served as a separate `country-outlines` LINE source; both highlight layers stroke that. Confirmed on the globe: no stray lines at any angle.
- **Bug 2 — a stronger fill patch near the pole (Russia's east flank, Canada's west).**
  - Surfaced only after Bug 1 was gone. Diagnosed by observation, not theory: mouse-off kills it (⇒ it's the translucent `country-fill` wash, not the base tiles); it's angle-dependent, present pole-down and gone toward the equator (⇒ a rendering artifact, not self-overlapping data, which would show at all angles).
  - Ruled out by measurement: "dense island outlines in the east" — Russia's outline vertices actually peak in the *centre* (~90–120°E), not the east. Confirmed Russia is split at ±180 with far-east parts on the −180 side.
  - Cause: geojson-vt gives every tile a default 128px buffer that overlaps its neighbours; a *translucent* fill paints twice in those overlaps (0.16 over 0.16 ≈ 0.3). Spread out at the equator the bands are invisible; near the pole the globe compresses the tile grid so they bunch into a visible patch on one flank.
  - Fix: `buffer: 0` on the `countries` source (tiles abut, no double-paint). Confirmed: patch gone, no tile seams. The outline is a separate source, unaffected.
- **Refactor + regression tests (Rohan asked for coverage).** The highlight wiring is extracted from the inline `globe.astro` script into `web/src/lib/countryHighlight.ts` (`outlinesFrom`, `countriesSource`/`outlineSource`, `fillLayer`/`highlightLayers`, source-id consts) — the `capability.ts` pattern, so it is importable and unit-testable (AstroContainer renders server output, not our client script, so extraction is the route). `countryHighlight.test.ts` = 11 tests: the conversion logic (Polygon/MultiPolygon/holes/ADMIN/in-scope/non-polygon) plus **guards that lock the two fixes** — `buffer:0`, and both highlight layers on the LINE source (not the polygon). Web suite 26 green, `pnpm check` 0. First web-side tests beyond `capability`.
- **Method note (the reusable lesson):** two wrong theories died before the right cause each time (`maxzoom:0`; "dense east islands"). What converged it was cheap discriminating observations Rohan could run (mouse-off, rotate-around-pole, pan-to-equator) plus a vertex-density count — not more armchair reasoning. Same shape as the cap "glow" the day before (measured, not asserted).

### 2026-07-19 — the cap's seam-match: light rotates with longitude, and the "glow" was a water-mask bug

Two refinements to the 2a bathymetry cap (next entry), each confirmed against the live tiles.

**Light must rotate with longitude (the azimuth fix).** The tiles light from true-NW *everywhere* — Mercator's grid-north is true-north at every pixel — so on the globe near the pole "NW" swings around with longitude. The cap baked a single fixed azimuth, so it agreed with the tiles at only one meridian and was fully reversed at λ=180° (the Pacific side, which the first screenshot happened not to show). Fix: `hillshade_array` now accepts a per-pixel azimuth array (scalar path byte-identical, pinned by `TestPerPixelAzimuth`), and `cap_render.py` lights with `315 − longitude` (main) / `135 − longitude` (fill), where `longitude = atan2(xx, yy)` is PROJ-verified at probe pixels *before* rendering (a flipped sign would rotate the light the wrong way, worsening the seam). On AEQD near the pole a scalar z-factor stays correct — tangential-scale distortion is <1% inside 78°. Confirmed on the globe, both sides (Rohan).

**The "disc glow" was NOT sky-view — it was a water-mask bug, and measuring first is what caught it.** Zoomed out, the cap ocean read as a bright disc ~+30% over the tiles. The tempting diagnosis was the deferred SVF-off, and it was WRONG: sky-view caps at ~10%, and the mismatch was *chromatic* (per-channel 1.39/1.29/1.23), which a grayscale light×svf term cannot produce. Per-point matching against `planet_rgb.tif` (same lon/lat, so the depth ramp cancels) showed the depths identical (mean |Δ| 6.5 m) yet the cap flat and depth-invariant at exactly `WATER_RGB = (142,198,196)`. Cause: `cap_render.py` built the inland-water mask as `watermask.astype(bool)`, which catches **class 1 (ocean)** — so `composite`'s water branch overwrote the whole Arctic sea with flat `WATER_RGB`, discarding the depth ramp. The "bathymetry" we'd both admired was the hillshade relief alone; the depth colour had been thrown away since the cap's first build (Rohan's eye caught it; my "looks correct" missed it). Fix: extracted `lake_depth.inland_water(watercode) = (==2)|(==3)` as the ONE shared classifier — the mirror of `lakes_only`'s "class 1 (ocean) must never be touched" — and repointed `shade.py` + `shade_planet.py` + `cap_render.py`. This is precisely the per-call-site-copy-drifts failure the float32/`combine_fill` entry (2026-07-16) warns about, recurring in a script that reimplemented the classification instead of sharing it. After the fix the cap ocean matches the tiles to **+0.5% luminance, uniform per-channel** — which also vindicates leaving **SVF off**: the residual is <1% here, masked by snow on the ice caps and ~0 over open ocean. (`cap_render.py` lives in the session scratchpad, which the PC reboot wiped; reconstructed from context + the plan file, which carries its full spec.)

### 2026-07-18 — the polar cap: flat fails, and the pivot to a polar-stereographic custom-layer cap

**The "blue hole" diagnosed.** The composite overwrites everything above `CAP_NORTH`=84°N (and below `CAP_SOUTH`=−59.5°S) with a flat `CAP_RGB` (`_compose`, `shade_planet.py`) — the module docstring calls it a "clean polar disc." It read as a *hole* not because of hue but because it was **flat, featureless, and mismatched**: `CAP_RGB=(67,118,132)` "deep sea" is *darker* than the lighter Arctic-shelf sea rendered beside it at the pole, so on the sphere the top band wraps into a dark flat disc inside lighter textured water. Two separable causes: the **need** to fill (Mercator has no data past ~85°, and 84–85° is smeared — below), and the **bad look** (flat + mismatched).

**The pale-sea-ice experiment — landed, then rejected on the globe.** Tried `CAP_RGB → (216,226,233)` (a pale ice tone sampled from the render's own Greenland ice `(229,234,235)`, pulled cooler), plus a freshness companion test (`test_cap_rgb_change_is_recorded` — the cap was the one RGB knob in `composite_params` with no such test). Recomposed under the 12 G cap (SVF 157 s + composite **10:48 / 727 windows / peak 10.24 GiB** — reconfirms the 128/N4 numbers; the cap change costs nothing), re-cut tiles (**3:28**), preserving the 256 gamma8 pyramid as `tiles_256_gamma8` first (else `build_tiles`' `rm -rf tiles_old` rotation would have deleted it). Verified the live pyramid carries it (a top-row z6 cap tile is uniform `(216,226,233)`; `tiles_old` = the dark-cap 128, the rollback). **On the globe it reads as a too-clean white plug.** Load-bearing conclusion: **no flat colour works — dark reads as a hole, pale as a plug; the problem is FLATNESS, not hue.** Feathering the edge (deferred earlier) would not have saved it — the complaint is the disc *body*, not its rim. Do not iterate more flat colours.

**Why Mercator can't reach the pole (root cause).** Web Mercator is conformal, so it stretches N–S by `1/cos φ` to match the E–W stretch; `y = R·ln(tan(π/4 + φ/2)) → ∞` as `φ → 90°`. The pole is infinitely far up the map — a singularity, not a resolution limit. "Web Mercator" then truncates at `y = πR` to make the map a **square** (a clean power-of-two quadtree), and `y = πR` solves to **φ = 85.0511°N**. So no tile exists above ~85°, and just below it the `1/cos φ` stretch is already ~10–11× (84° = 9.6×, 85° = 11.5×) → severe vertical smear. The flat cap patched *both*, pushed down to 84° to also hide the worst smear.

**Uncapped, the real bathymetry is natural and usable.** Compositing the polar band with the cap disabled (`CAP_NORTH=90`, reusing the cached SVF `occ.npy` — ~1–3 min, no full recompose) and reprojecting to EPSG:3995 (Arctic Polar Stereographic) shows the pole as a **textured Arctic Ocean disc** — Lomonosov/Gakkel ridges, the basins, shelves — *continuous* with its surroundings, only mild stretching near 85°. Not smeared garbage. The disc has a small black dot dead-centre: the genuine >85.05° no-data gap — but that is an **artifact of reprojecting the already-Mercator-clipped raster**; a cap built from the SOURCE (GEBCO reaches 90°N) fills the disc completely.

**What's actually at the pole, and why "show real sea" is a half-measure.** The North Pole is deep Arctic Ocean floor (~4,000 m — our GEBCO bathymetry) *under floating sea ice* (the surface). Our data is the seafloor: accurate for the floor, wrong for the surface (open teal water where a viewer expects white ice). **Sea ice is the surface reality** — and NOT a rival to the bathymetry: the Patterson/Blue-Earth school draws sea ice as translucent white *over* the real bathymetry (sea showing through at the thinning edges), so **uncapping to reveal the bathymetry is the foundation the sea-ice layer sits on**, not a detour. Decision: the pole look is **sea ice draped over real bathymetry**, both poles.

**Decided delivery: a polar-stereographic cap asset drawn via a MapLibre custom layer — this supersedes the baked-flat-Mercator-cap entirely.** **[Later note, 2026-07-20: implementation delivered the caps on AEQD grids, not polar-stereographic/EPSG:3031. Because we control both the cap texture's projection and the frontend UV, an AEQD texture sampled by the existing linear-colatitude UV cancels exactly on the globe — lower risk than a stereographic-UV rewrite, for no visible difference. See the 2026-07-19/20 cap entries above.]** Since Mercator can't reach the pole and MapLibre renders only WebMercatorQuad tiles, the caps are produced offline as a **separate polar-stereographic raster** (shaded from source, reaching 90°) and drawn over the pole via a **custom WebGL layer**, alpha-feathered into the Mercator tiles at the ~85° seam. The south cap at −59.5° is the Southern-Ocean sea-ice zone around the (currently absent) continent, so it ties into the **Antarctica** decision; the **north pole is the clean place to prove the technique**.

**Three research agents grounded the direction.** (1) **MapLibre Tile Spec (MLT)** is a *vector* tile format (MVT successor); irrelevant to our raster relief and negligible for the thin Natural-Earth border overlay → **ignore now**; only file away that PMTiles v3 can carry MLT if the borders ever grow dense/attributed. (2) **H3/S2** are spatial *indexing* systems, not tiling/rendering; they do NOT fix the pole (it is a projection/renderer property — MapLibre renders only WebMercatorQuad, so re-indexing changes nothing downstream), and the one polar-stereo projection plugin (`backproj`/maplibre-proj) *cannot run in globe mode*. Their redirect — "render a separate polar-stereographic cap over the pole" — independently confirmed our direction. (3) **Plugins**: the only one to **adopt is `pmtiles`** (mandatory for static serving; raster fully supported, tiny stable `addProtocol` API); the polar cap and a country search are both "build it yourself" (a geocoder is overkill for a fixed ~200-country list); all terrain/contour plugins are dead weight because we bake shading offline.

**Feasibility PASSED (proven by official examples, not theory).** MapLibre GL JS v5 supports `CustomLayerInterface` under the globe projection (we're on **5.24.0**), with **three official globe custom-layer examples** — including a georeferenced, *textured* 3D mesh placed at a lng/lat, almost exactly our case. `render(gl, args)` receives `args.defaultProjectionData` (`mainMatrix` maps a unit-sphere planet → screen; `clippingPlane` for horizon culling; `projectionTransition`); the **North Pole is `(0,1,0)`** on that unit sphere. Recommended build: a **raw-WebGL custom layer** (~100 lines, no three.js), geometry = a **tessellated cap mesh** (concentric lat rings ~80°→90° so it conforms to the sphere — a flat tangent disc floats/intersects across 10° of curvature), per-vertex UV = position in the GDAL polar-stereo cap image; **seam** = overlap *past* 85° and ramp alpha 0→1 across a latitude band so the cap dissolves into the tiles; **no z-fight** = draw last, `renderingMode:'2d'`, depth off, and skip unless in globe mode (`projectionTransition≥1`, which also dodges a known globe→Mercator transition bug). Risks manageable: **pin MapLibre 5.24.0** (the globe projection-data API has churned across v5 minors), and two items (raster texture-sampling in a raw-WebGL globe shader, and the derived unit-sphere convention) are "verify via a spike." `globe.astro` integrates cleanly — inline style, one raster `relief` layer; the cap `addLayer`s above `relief`, below the borders.

**Tools built for browser-free pole iteration** (scratchpad; promote when the cap pipeline starts). `disc_preview.py` composites the polar band uncapped via the cached SVF and reprojects to EPSG:3995 → a disc PNG, so the pole look is judged without tiles or the browser (supporting: `north_cap_crop.py`, `uncapped_pole.py`, `cap_candidates.py`, `cap_feather.py`). **Iteration-cost lesson:** a full recompose (13 min) + full re-cut (3.5 min) to preview one flat colour was overkill — a *flat* cap-colour change touches only the cap rows (patch in place), and the pole *preview* needs no tiles at all (the disc render). The cap pipeline makes this moot, but the loop lesson stands.

**State & next.** Live tiles = the pale-C plug (interim, superseded by this decision; revert-to-dark vs leave-until-the-cap-lands is Rohan's low-stakes call). `planet_rgb.tif` = pale-C 128; `planet_rgb_gamma8_baseline.tif` = 256 gamma8; `tiles_old` = dark-cap 128; `tiles_256_gamma8` = 256 pyramid. **Spike CONFIRMED 2026-07-18** (`web/src/lib/polarCapSpike.ts`, behind `/globe?polarspike`): a test-pattern disc drawn via the manual unit-sphere path (`mainMatrix * vec4(p(λ,φ),1)`) **lands on the North Pole and tracks on pan/zoom** — validating BOTH risky items at once (raster texture-sampling in a raw-WebGL globe layer, and the derived convention `p(λ,φ)=(cosφ·sinλ, sinφ, cosφ·cosλ)`). Wiring gotcha: add the layer on `style.load`, not `load` (both fire from the throttled render loop, but headless/automated tabs never complete `load` — so the layer never adds under automation; a foreground browser is fine). Next: the horizon-clipping cull (the spike omits it, so the disc bleeds through when the pole faces away), then the cap pipeline (source → polar-stereo EPSG:3995/3031 → shade → sea ice over real bathymetry).

### 2026-07-18 — the composite is threaded (opt #5): 128/N4 landed, and why 256 could not thread under 12 G

Optimisation #5, gated on #4 (the fork-free composite). **`ThreadPoolExecutor`, not processes** — settled 2026-07-16 (numpy releases the GIL). Design: **read on the main thread, compute on workers, write back on the main thread in window order** (rasterio datasets are not thread-safe). `composite_planet` factors the per-window work into pure `_compute_shared` (masks / snow-alpha / polar cap — sea-knob-independent) + `_compose` (`shade.composite` + cap); `_compute_window_rgb` chains them as one worker unit. A bounded in-flight `deque` (throttle at `max_workers + INFLIGHT_BUFFER=2`) caps RAM. Threading engages ONLY for the single-variant production path (`max_workers>1 and len(variants)==1`); the A/B multi-variant loop mutates the global KNOBS between variants, so it stays serial. Serial and threaded run the SAME `_compute_shared`/`_compose`, so **threaded == serial by construction** — proven at unit scale (`tests/test_composite_threading.py`, workers 2/4, `compare_rasters` tol=0, plus companions that the oracle can fail and that serial/multi-variant never build a pool) and at real scale (GATE 1: a serial 128 band composite == the threaded full output over the Alps, byte-identical, all 3 bands).

**The 12 G cap forces the look/speed trade — the central finding.** A 24-window sizing bench: 256-serial peaks 6.33 G; **256/N3 and 256/N4 both OOM.** One 256-row full-width compute transient is >2.84 G (from `serial = base + 1× = 6.33` and the N=3 kill), so `base + 3× > 12 G` even at read-ahead 0 — algebra, not luck. So **byte-identical (256) threading caps at N=2, ~1.8×.** The full ~3× needs SMALLER windows to fit N=4: **128/N4 = 8.5 G on the bench, 10.55 G over the full 727-window pass** (fragmentation growth, still under cap; N=6 was 11.3 G on 24 windows → would OOM a full pass, for only +9% speed = the bandwidth knee the 2026-07-16 study predicted). **128 is NOT a speed lever by itself** — serial rows/s are ~equal at 256 and 128 (40.9 vs 38.7), which **kills the plan's "cache-sized windows beat 3×" hypothesis**; 128's only value is fitting more workers under the cap.

**128 changes the look sub-perceptibly, judged on renders not metrics.** `window_rows` slices the SVF occlusion per window (`occ[sr0:sr1]` upsampled by `zoom`), so 256→128 perturbs the output: ~0.4–0.7% of rugged mid-latitude px shift ≥1 DN, almost all by 1–2, worst **20 DN** on the most extreme mountain snow (Karakoram/K2; 15 in the Alps). Rendered 256-vs-128 crops of both the Alps and the Karakoram worst-case witness are **indistinguishable at true scale** — the difference is a faint, structured SVF-window-boundary pattern visible only under ~10× amplification (`scratchpad/*_256_vs_128.png`). **Rohan judged the crops and chose 128/N4**: the current planet's look is z8-locked, but the change does not show, and Phase B's motive is affordable iteration (esp. Antarctica, where the look is re-judged fresh anyway). **256/N2 (~1.8×) stays the fallback** if strict bit-preservation is ever wanted.

**Landed:** `COMPOSITE_ROWS=128` + `N_WORKERS=4` are the production composite; `WINDOW_ROWS=256` stays = the snow-persistence band height, sliced 128 rows at a time, so the Phase-A snow warp is untouched (a 128-row slice of the 256-banded raster is deterministic and independent of composite window height — exactly what the delta A/B used). Full pass: composite **645 s (10:45), 1.13 win/s, peak 10.55 GiB, ~3.5× the same-session serial rate**; tiles re-cut (62,177, live; 256 kept as `tiles_old` + `planet_rgb_gamma8_baseline.tif`). **Freshness fix found along the way:** window_rows changes pixels but was untracked, so `composite_params` now records `composite_window_rows` (and deliberately NOT `max_workers`, which is byte-identical) — closing the gap AND forcing the 256→128 recompose. Generalisable lesson: **a "RAM lever" that touches windowed interpolation is a look input — track it, and prove it invariant before assuming window size (or threads) are free.**

### 2026-07-18 — snow warped ONCE to the planet grid (opt #4): the packed-vs-unpacked trap

Optimisation #4 off the 2026-07-16 ranked list. The composite loop forked `gdalwarp` (snow persistence) and `gdal_rasterize` (RGI glaciers) **for every window** — ~728 subprocesses per pass, 7.8% CPU, writing into two **fixed-path** temps (`_sp_win.tif`/`_rgi_win.tif`). Those shared paths were the hard blocker for #5 (threading): two workers would clobber each other's temp. The fix is the precedent `warp_inputs` already sets for height/ocean/water/**lakedepth** — warp once to the whole 3857 grid, read a window slice per iteration.

**The packed-vs-unpacked trap (the reason this needed care, not just a move).** The plan first said "store the unpacked 0..1 persistence." That would have broken byte-identity, caught while reading the code: the old per-window path warps to a **packed Float32** temp (0..10000, fill 65535), then `warp_persistence` does `.astype(float)` → **float64** and runs `snow_alpha` in float64 before the final blend and the uint8 quantize. Store the *unpacked* value as Float32 and read it back, and `snow_alpha` would run in float32 → the blend shifts sub-DN → not bit-identical. So the warp-once raster stores the **RAW PACKED Float32**, byte-for-byte what `_sp_win.tif` already held, just whole-grid; `unpack_persistence` (the float64 unpack, split out) stays per-window. Each window slice is then identical to the old per-window temp **by construction**, not by luck.

**Factoring** (`pipeline/render/snow.py`): `warp_persistence` → `warp_persistence_raster` (gdalwarp only, no read) + `unpack_persistence` (the float64 unpack); `rasterize_glaciers` → `rasterize_glaciers_raster` (gdal_rasterize only — it does **not** read the result back, because a whole-planet Byte read is ~12 GB; the composite reads window slices). The old `warp_persistence`/`rasterize_glaciers` names survive as **thin wrappers** (raster + read [+ unpack]) so the region path (`shade.py`) is byte-for-byte unchanged. Writers gained `TILED/DEFLATE/BIGTIFF` (storage only — values identical, and a mostly-constant field DEFLATEs small: `lakedepth_3857` is 310 MB for the same grid).

**Freshness:** `snow_persistence_3857.tif` + `glacier_3857.tif` joined `composite_deps`. The ramp *tunables* (`RAMP_*`) run at composite time inside `snow_alpha`, so they stay in `composite_params`, not the warp-once freshness — this pair tracks the warp SOURCES (`.nc`/`.gpkg`, re-fuse to a new grid) only. `glacier` may be absent (RGI not downloaded); `newest_mtime` scores a missing path 0.0, so listing it unconditionally is safe.

**Verification.** TDD-first: `tests/test_snow_warp_once.py` warps a small Alps region whole-grid and per-window using composite's *exact* window-bounds formula, then asserts `np.array_equal` **through `unpack_persistence`** (unpacked, float64, as `snow_alpha` sees it), with a companion that shifts the slice and requires it to DIFFER (so a uniform-snow region can't pass trivially) and one pinning the wrapper's region-path output. 208 tests green, pyright 0. This proves window-slice == per-window at unit scale on the real NSIDC/RGI source; the **planet-scale gate is still pending** — a full instrumented pass whose `planet_rgb.tif` must be `compare_rasters(gamma8_baseline, new, tolerance=0)` byte-identical (copy the current `planet_rgb.tif` aside as the baseline FIRST, since the pass overwrites it). Adding the two rasters to `composite_deps` means that next pass re-composites once — that re-composite IS the gate, not wasted work. Only after it passes does #5 (threading) begin.

**The gate caught a real bug: a single whole-grid warp DECIMATES a coarse source.** The first full gate FAILED — `worst 162 DN` at lon 175.6 / lat −39.3, **Mt Ruapehu, NZ**: baseline `(176,199,219)` = `SNOW_SHADOW_RGB` (full snow), warp-once `(105,72,57)` = bare land. Traced entirely to the persistence **warp** (glaciers were byte-identical — `gdal_rasterize` is exact vector burn). The NSIDC source at Ruapehu is genuinely structured (0.88–0.999 on the snowy plateau, down to 0.12); a **per-window strip warp reproduces it** (0.756 at the witness ≈ source 0.74), but the **whole-grid warp flattens it to a smooth 0.30–0.54 ramp** — persistence 0.756 → 0.409, crossing the snow threshold → snow becomes bare land. Mechanism: SP is COARSE (~1.1 km) and the target is a fine global Web-Mercator grid (~305 m); gdalwarp picks ONE source-read decimation for the whole op from the pole-inflated average scale and applies it everywhere, so mid-latitude mountains that should upsample get smoothed instead. It hits ONLY snow — height/lakedepth/masks have near-target-resolution sources, so they never trip it, and it's why the old per-window baseline (small-extent strips) was faithful. The unit test missed it because its "whole grid" was a small region, not planet-scale. **Rejected fixes, each measured:** `-et 0` (exact transformer) changed the whole warp by 5e-11 — not the transformer; `-ovr NONE` was a no-op — the source has no overviews, so the decimation isn't overview-based; **4096-row bands still decimate at Ruapehu** (0.489), while a 256-row strip is faithful. **Fix = warp in latitude BANDS** (`snow.warp_persistence_raster(band_rows=…)` mosaics band warps into the one raster; `warp_inputs` passes `band_rows == WINDOW_ROWS == 256`). At the composite window height, aligned to it, **each band IS the per-window warp** it replaces → the mosaic is byte-identical to the old path by construction, *and* fork-free in the composite (#4's whole point). The region path (`band_rows=None`) stays a single warp. Rebuilt persistence verified byte-identical vs per-window at Ruapehu / Mont Blanc / Greenland Summit / Aconcagua (`max|d|=0`); full-composite gate re-run in progress. **Watch item:** `lakedepth_3857` is also a whole-grid warp — if GLOBathy's native resolution is coarser than 305 m it may be mildly over-smoothed the same way (invisible to this gate: same in baseline and new). The lesson generalises — **warp-once of any source COARSER than the target needs banding, not one whole-grid gdalwarp.**

### 2026-07-18 — snow source re-confirmed (NSIDC-0791 stays); sea-ice parked for Antarctica

Rohan asked whether five alternative datasets beat NSIDC-0791 for the snow layer. **None do**, and the reasons sort them on two axes. (1) **Climatology vs daily/operational:** our layer is a *timeless* persistence climatology (why we left WorldCover class-70, 2026-07-13). *MODIS/Terra Snow Cover Daily (500 m)* and *VIIRS/NPP Daily (375 m)* are the raw DAILY products NSIDC-0791 is aggregated FROM — finer, but a single day is wrong for a timeless map and self-aggregating 22 years reproduces (worse) what NSIDC already did; VIIRS also has only a ~2012+ record. *Copernicus Global SCE (1 km)* is operational current-conditions extent — wrong temporal semantics, no resolution gain. (2) **Land snow vs sea ice:** *SAR Sea Ice Drift* is ocean ice *velocity* (wrong domain and variable); *MODIS-AMSR2 Merged Sea-Ice Concentration (1 km)* is a good product but SEA ICE, not land snow. **Two real levers this surfaced, both parked:** finer snow → self-aggregate MODIS-500/VIIRS-375 into our own climatology (big effort, marginal cartographic gain — and note the Ruapehu problem was a *warp* bug, not source resolution); and **sea ice as a future SEPARATE polar layer** (MODIS-AMSR2 is the right family, wants a climatology, interacts with sea/bathymetry) — tie it to the **Antarctica** decision, since the poles are capped flat today. Our snow pain has always been downstream (warp decimation, the gamma8 contrast curve), never source quality.

### 2026-07-17 — Greenland's interior is blank because the snow blend throws the hillshade away, and no linear window can fix it

Chased after the z8 lock, because Greenland's flat white interior was a deferred gap and **Antarctica is
the same problem at ten times the area** — worth understanding *before* the re-fuse, not after.

**The fill sun did nothing to Greenland, and provably could not.** A/B of `tiles_old` (pre-fill) vs the
live `tiles` at Summit and northern Greenland: **0.0% of interior pixels changed by more than 2 DN**, max
delta 4 DN. The Alps control in the same run moved 38.6% of pixels at up to 42 DN, so the probe could see
change; Greenland had none. The reason is **this morning's own invariant**: the fill leaves *zero-slope
ground exactly unchanged*. Greenland's interior is the closest thing on Earth to zero-slope land, so it is
the one place the fill provably cannot reach. An independent confirmation of the rescale contract, on the
terrain that best isolates it.

**The mechanism — `shade.py:375-380`.** Over full snow (`alpha = 1`):

```
final = base_rgb * (1 - alpha) + snow_rgb * alpha
```

`base_rgb` is **multiplied by zero**. That term carries `light * svf_factor` — every bit of hillshade and
sky-view modelling — and over full snow it is *discarded entirely*. Relief reaches the image through one
surviving channel: `snow_t = clip((light - snow_lo) / (snow_hi_pt - snow_lo))`, a linear stretch across a
**0.50-wide window**, driving a two-colour ramp whose endpoints (`B0C7DB` → `E8F1F6`) are **43.9 DN apart
in luminance**. That is the entire contrast budget for any fully-snow pixel on the planet.

This is **deliberate and correct where it was designed** — 2026-07-14 replaced a neutral `SNOW_RGB × light`
because it *muddied to grey on rugged terrain*. It fixed the Alps. Over a nearly-flat ice sheet it leaves
nothing.

**Measured (`light` over full-snow pixels, reconstruction validated against the shipped `planet_rgb` to
1 DN at Greenland — over full snow the output colour is a pure function of the hillshade, so `occ` never
enters and no global SVF read is needed):**

| site | `light` span p1–p99 | % of the 0.50 window used | delivered luminance |
|---|---|---|---|
| Greenland Summit | **0.0349** | 7% | **2.87 DN** |
| Greenland north | 0.0524 | 10% | 4.60 DN |
| Alps snow | **0.6105** | 122% (overflows) | 43.89 DN |
| Himalaya snow | 0.6510 | 130% (overflows) | 43.89 DN |

**A ~17× dynamic-range mismatch, and the ranges are NESTED, not adjacent** — Greenland's `[1.017, 1.052]`
sits inside the *top* of the Alps' `[0.50, 1.11]`. A window fitted to Greenland (`[1.017, 1.052]`) buys a
**14.3× contrast gain, ~41 DN where there is now 2.87** — the signal is in the hillshade and the window is
throwing it away — but it turns Alpine snow into a **binary blue/white cartoon**: nearly every Alpine snow
pixel falls below 1.017 → `snow_t = 0` → flat `snow_shadow`. **A window wide enough for the Alps gives
Greenland 7% of its travel; a window narrow enough for Greenland is a threshold for the Alps. No single
linear window serves both** — measured, not argued. Same shape as `EXAG 15`: one global constant
straddling two terrains an order of magnitude apart, and the same species as the recorded learning that
*the KNOBS were tuned on mountainous Nepal and blow out flat bright terrain*.

**The candidate is a non-linear `snow_curve`, and the precedent is in our own KNOBS: `lake_curve="log1p"`**
— the identical problem (a pond and Baikal on one ramp), solved with a curve instead of a window, and
deliberately parked *inside* KNOBS. A composite-stage knob: ~50 min, no re-fuse, no new data.

**`snow_curve="gamma8"` CHOSEN and promoted to a KNOB (Rohan, same day)**, off a four-curve A/B
(`linear`/`gamma4`/`gamma8`/`knee`) rendered through the real `composite()` with production inputs —
real hillshade, real masks, the real cached global SVF, real snow alpha including the RGI union and the
ocean/water zeroing. The `linear` column reproduced the shipped `planet_rgb` at **max err 0 DN** at both
Greenland sites, which is what proves the rig was wired to the thing and not a lookalike.

| curve | Summit | north | Alps snow changed | Himalaya snow changed |
|---|---|---|---|---|
| linear (was shipping) | 3.14 DN | 4.35 DN | — | — |
| gamma4 | 10.63 (3.4×) | 14.99 (3.4×) | 29.0% | 29.0% |
| **gamma8 (chosen)** | **18.84 (6.0×)** | **24.12 (5.5×)** | **33.9%, mean 6.99 DN** | **29.3%, mean 5.75 DN** |
| knee | 18.84 (6.0×) | 18.77 (4.3×) | 32.6% | 28.0% |

**`knee` was rejected on merit, not taste:** it matches gamma8 at Summit but is weaker in the north
(4.3× vs 5.5×) and costs two more constants (`KNEE_X`, `KNEE_SHARE`) for less.

**The predicted trade did not arrive, and the prediction was mine.** "The ramp is a fixed 43.9 DN budget,
so every gain for flat ice is paid by rugged snow" is true in the arithmetic (a test pins it), but the bill
is small: rugged snow's light is **bimodal** — 62–65% pinned at the `ambient` floor, a few % at the top —
so it barely occupies the midtones the curve borrows from. The curve takes its slope from a band the Alps
hardly use. A fact about the terrain, not about the curve.

**`snow_lo`/`snow_hi_pt` deliberately stay 0.55/1.05.** The window is not the lever.

**Two instrument failures worth keeping, both mine, both in the checking.**

- **The first A/B metric was blind.** A p1–p99 luminance span reported **45.68 DN / 1.00× for all four
  curves** at the Alps — saturated, because `snow_t` is bimodal there, so it would have said "no change"
  whether or not the curves hurt. This morning's lesson, re-learned within hours: *a contrast metric
  cannot distinguish softer from flatter*. Replaced with change-vs-the-linear-control over full-snow
  pixels — the statistic that can fail, and the one the fill A/B used.
- **The rugged oracle reads 24–26 DN and that is the harness, not the curves.** Reproducing production's
  SVF zoom on a 512 px crop is not exact — production zooms a full-width 4096-column occlusion slice up
  to 131072, and a sub-window cannot reproduce that interpolation. It moves **land** tone only, and
  identically in all four columns (`svf_factor` does not depend on `snow_curve`), so column-to-column
  comparison stays exact. Greenland is 100% snow, so `base_rgb` is annihilated and its panels are exact.

**Two structural fixes landed with it.** `hs_params()` was **split out of `build_hillshade`** so both
halves of the freshness contract are testable from outside — the asymmetry was the hazard, since
`composite_params` had tests pinning what it must and must not record while its sibling had none, and
every freshness bug so far has been a tunable that missed one of the two records. And the `snow_curve`
tests take an **autouse restore fixture**: `KNOBS` is module-level mutable state, so a test that sets it
and walks away silently re-tunes every test after it (`test_lake_depth.py` does exactly this today).

**`position ** 8` is deliberately left as a pow.** Repeated squaring is **1.7× faster** on a real
131072×256 float32 window (44.7 → 26.1 ms) but saves **6.8 s of a ~2,980 s composite: 0.23%**, and is not
bit-identical (1.8e-7, or 8e-6 DN). Measured before writing it, not after — this is the `gdaladdo` trap,
which is aiming at a stage that is not the cost.

**Verified before any pass ran:** `hs_params.json` **unchanged** (the 11:48 hillshade correctly stays
fresh — `snow_curve` is composite-only and the hillshade cannot see it), `composite_params.json` changed
by **exactly `snow_curve: None -> 'gamma8'`**. So this restages SVF + composite + tiles and nothing else.

**It landed.** Instrumented pass exit 0, **55:48 total**, 62,177 tiles live, `tiles_old` = rollback (now
this morning's fill+linear pyramid). Stage times confirmed the pre-flight prediction to the second: the
**hillshade did not run** (composite-only knob), SVF 167 s, composite **49:33** (vs 49:40 for the fill
pass — the `** 8` cost is inside the noise, exactly as the 0.23% benchmark said), tiles 3:28. **This is the
first measurement of a pure composite-stage re-tune: 67:44 − 11:48 hillshade = 55:56 ≈ measured 55:48.**

Greenland at planet scale, live gamma8 vs `tiles_old` linear (the isolation the rollback happens to give):
Summit interior contrast **std 0.70 → 4.27**, north **1.16 → 6.01** (~5–6×), 96–99% of the tile changed —
the blank field now carries modelled relief. The Alps whole tile changed only **17.3%** (its snow fraction
alone; bare rock is `snow_curve`-invariant). The predicted asymmetry, confirmed on the sphere's own data.

**REMA/ArcticDEM is NOT the first lever here** (against the 2026-07-13 filing, which assumed a data
limit). Better elevation raises the input signal into a stage that is discarding 93% of what it already
has. Fix the blend, then ask whether the data is short.

**Two side findings.**

- **62% of Alpine snow pixels sit at `light = 0.5000` exactly — the `ambient` floor.** The fill sun took
  *hillshade pure black* to 0.00%, but `light` clips at `ambient` whenever `hs < 90`. **"0% pure black" and
  "0% at the floor" are different claims** and this morning's write-up conflated them. This does **not**
  reopen `ambient` — swept and rejected twice, and that stands — it means the floor does more work than
  the black-percentage suggested.
- **The recurring check-not-pipeline bug, instance eight.** The first probe reported the rugged oracle
  failing by 90–123 DN. Not a finding — the probe omitted production's `alpha = np.where(ocean | water,
  0.0, snow_a)`, so frozen lakes counted as full snow. Fixed → error fell to 2.0–2.3 DN, which is exactly
  what an `alpha > 0.99` mask predicts (1% of `base_rgb` ≈ 200 bleeding through). **Every instance so far
  has been in the checking, never in the pipeline.**

### 2026-07-17 — z8 LOCKED: the ceiling gate closed on the sphere, where it said it would be

**Decided by Rohan, on `/globe`, after looking**: z8 is reasonable; locked. This is the resolution the
gate had been holding out for since 2026-07-10 — its recorded condition was *"decided at: after the z8
globe is viewable live — 'z8 feels coarse' cannot be judged until seen on the sphere."* The question was
never answerable from a number. 306 m/px is legible as arithmetic and meaningless as a judgement; the
pyramid had to exist, be served, and be looked at. It was cut 07-17 and carries the fill sun, so what was
judged is the current look, not `tiles_old`.

**What the lock decides, and what it does not.** It is a *ceiling*, not a claim that finer would look
worse — z9/z10 stay recorded as **additive and deferrable** exactly as scoped, because a deeper pyramid
is crisper on zoom-in and **not heavier to render at runtime** (MapLibre fetches only viewport tiles;
PMTiles serves by range request). The cost of a re-fuse is build-time and storage, paid once. Rohan's
"for now" is doing real work in that sentence: this closes the gate, it does not burn the road.

**Three things it unblocks, which is why it was "the big one":**

- **PMTiles** — the packaging step was gated on the look being final. It now is.
- **The hero sea-sync** — gated on the pyramid being final, so ~204 heroes would not be re-rendered
  against a ramp that might still move. It won't move. Four divergences ride on that one re-render.
  **[CORRECTED 2026-07-21 — this framing was wrong and produced a wrong recommendation. The sea-sync
  depends on the shared PALETTE CONSTANTS, not on the ceiling or the packaging: PMTiles changes zero
  pixels and z10 is a planet re-fuse the heroes never read. The instinct here — "it won't move" — was
  right for the wrong reason. → § 2026-07-21 (night, later)]**
- **The optimisation section's priority** (not its worth). z10 would have made the composite ~12.5 h
  single-threaded vs ~4.2 h at the measured ~3×. At z8 it stays ~49 min — but that is **~71% of every
  67-min art iteration**, which is why the gate's old line *"z8 final → items 4-6 never pay"* was already
  disproven on 07-17, before this lock. The lock sets urgency. It does not revive that claim.

**What stays latent, and is now the one thing this decision must not lose.** `ocean` / `water` /
`lakedepth_3857` take their grid from `height_3857.tif` but **none depends on it for freshness**. Harmless
at z8 forever. The moment a z10 re-fuse lands, height re-warps to a new grid while `lakedepth` sits
falsely "fresh" at the old dimensions — a silently wrong composite, not a crash. The fix is a
**dimension/bounds comparison, not an mtime dep** (an mtime dep forces a needless 62-min re-warp every
time height rebuilds to the *same* grid). **Fix before any re-fuse, not after.** Locking z8 is precisely
what makes this easy to forget, so it is recorded here rather than left in a resolved open question.

### 2026-07-17 — the tiles were missing the hero's fill sun, and that was the "harshness"

Rohan judged the live Sri Lanka z8 tile "slightly harsh". The cause was **not** the colour ramp
(`LAND_STOPS` never exceeds chroma 26 and moves ≤5.5 ΔE/100 m — checked first, and it exonerated the
ramp). It was the light, and the fix was already in this repo's own art history, on the other renderer.

**The measurement.** A single 45° sun on the 15×-exaggerated 305 m grid makes the Horn slope term
`arctan(15 · gradient)`, so a **4° real slope presents as 46°** — past the sun — and the face goes to
hillshade **0**. Pure-black fraction of land at z8: **Alps 43.66%**, Andes 37.97%, Scotland 32.41%,
Himalaya 30.45%, Sri Lanka 12.39%, Sahara 4.59%, Great Plains 0.29%, Amazon 0.02%. Rohan had flagged
one of the *mildest* mountain cases; nearly half the Alps was a flat black slab. The distribution is
**bimodal** (p10 = 0, p25 = 85, p50 = 158) and that hole is what the eye reads as crunch. Separately,
~20% of land pixels had a channel pinned at 255 — both ends clipping, so a fifth of the image at each
extreme rendered identically.

**The fix was recorded on 2026-07-08, for the hero.** ART.md:73-79: the hero hit this exact symptom
("shadows are hiding texture") and the answer was a shadowless SE fill sun at 15%, explicitly beating
the alternative — *"ambient-raise lifted levels but washed rosy and flat; fill restored modeling"*.
The hero has three softening mechanisms the tiles had **none** of: `SUN_ANGLE` 12° (penumbra), the
fill, and a world ambient. The tiles copied the hero's main sun on 2026-07-14 and never got the fill,
which post-dated them. **So this is a hero/tile divergence — the fifth — not a new tile knob.** The
same 15× produces sculpture in Cycles and crunch in a hillshade, because Cycles has penumbra and
bounce and a hillshade is a bare Lambertian dot product.

**Ported at the hero's own numbers** (60° up, azimuth 135°, 15% = `FILL_STRENGTH 0.45`/`SUN_STRENGTH 3`).
Any strength ≥0.10 drives pure black to **0.00% on all eight sites**, and it self-regulates exactly as
ART.md:80-83 claims: the Amazon does not move. **`hi` 1.30 → 1.12** rides with it (the fill lowers peak
light, so the old ceiling only clips).

**Rejected, with reasons:**
- **Lowering EXAG** (15→8 halves the black). It is the series promise (ART.md:44-54), it would diverge
  tiles from heroes on the one constant declared global, and it treats the symptom not the cause.
- **Raising `alt` 45→55** (also works, kills highlight clipping outright). It would *widen* the known
  46°/45° hero split instead of closing it. `alt` belongs to the sea-sync.
- **Raising `ambient`** — see below. This one I got wrong first.

**The lesson worth more than the fix: every metric said 0.62 and every metric was wrong.** I proposed
`ambient` 0.50→0.62 *paired* with the fill, citing ART.md:56 ("tune the pair"). The sweep improved
monotonically with ambient — floor up, clipping down, Andes crunch 39.1→34.9→30.8 — and the renders
got monotonically **worse**, hazing into exactly the "washed rosy and flat" the 2026-07-08 A/B had
already rejected. I was re-committing a rejected error with the fill present to mask it. **`ambient`
stays 0.50**: ART.md:90's own division of labour says *the fill IS the shadow floor*, so a flat clamp
underneath it can only lift things. A contrast metric cannot tell **softer** from **flatter**, which is
the only distinction that matters here. Recorded in ART.md's tuning protocol.

**The Andes "haze" is the ramp, not the light** — ablated: snow is 0.9% of that tile and SVF burn is
p50 0.001; disabling both changes nothing (lum p50 97 → 97). That tile's land sits at p50 **3405 m**
where `LAND_STOPS` has desaturated to (205,178,156), chroma ~49 vs ~78 at 1500 m. The ramp is *designed*
to go pale up high; `ambient` merely amplified it. Elevation-keyed, so **z10 will not worsen it**.

**Two implementation findings:**
- **uint8 headroom is a PROOF, not a measurement.** Bounding both suns at 255 gives
  `255(1+s)·sin(alt)/(sin(alt)+s·sin(fill_alt))`, which is ≤255 exactly when **alt ≤ fill_alt**. At
  45 vs 60 it cannot overflow at any strength, so the fill bakes into the existing single band with
  no extra raster. The measured 255→226→213 was sampling something the geometry guarantees. (The bound
  is strict and never attained — opposed azimuths mean both suns cannot peak on one pixel — which made
  the first clip-backstop test vacuous at a setting that only reaches 187 DN.)
- **`composite_params` serialises KNOBS wholesale, and that is a trap.** Putting `fill_strength` in
  KNOBS (correct — `alt` is already a KNOBS entry consumed by the hillshade, and it buys `--knob` for
  region A/Bs) meant *merely adding the key at 0.0* changed composite_params.json → a 53.8 min
  composite + 3:44 tile cut for byte-identical pixels, and the live pyramid falsely reported stale.
  Caught before any pass ran, by diffing generated params against disk. Fix: `HILLSHADE_ONLY_KNOBS`,
  filtered out — safe because the value reaches planet_rgb via `composite_deps`' dependency on `hs`.
  The filter defaults to **include**; `alt` is deliberately not in it (composite reads it too).
  Symmetrically, `hs_params.json` records the fill block **only when strength ≠ 0**, so landing the
  mechanism left hs_3857 legitimately fresh instead of falsely stale.

**The shared helper.** `hillshade.combine_fill` is the one implementation; the planet path reaches it
through `per_row_zfactor_hillshade`, the region path (`shade.py --cells`, which shades with `gdaldem`
and therefore needs a second pass) through `shade.add_fill_gdaldem`. Not copied — HISTORY:265 records
that a per-call-site copy of a shared decision is exactly how the float32 fix reached `composite` and
never reached `hillshade`. Cross-checked: the two paths agree to **max 2 DN, 99.58% within 1 DN**, and
the region path independently reached max DN 226 at 0.15, the same number the planet sweep measured.

**It landed.** `run_pass.sh --tiles`, exit 0, **67:44** — warps 0.3 s (all four skipped, including the
1:01:38 lake warp), hillshade 11:48, SVF 2:44, composite 49:40, tile cut 3:32. 62,177 tiles live, served
md5 == disk md5, `tiles_old` = the pre-fill rollback. **Pure black → 0.00% at all six probe sites** (the
Alps was 43.66%) and **max DN 226 at every one** — the geometry proof holding at planet scale. Two
runtime facts worth carrying: the fill cost **+3:20** of wall, not the +4:30 a synthetic compute
benchmark projected (only ~half the hillshade stage is arithmetic — 1.17 cores); and the composite came
in at **49:40 against the 53.8 min baseline**, which is optimisation #3 (`num_threads` on the writers,
landed 07-16) cashing in for the first time at ~68% of its predicted "~6 min, upper bound".

**A verification arm I got wrong, and then diagnosed wrong.** I predicted the flat controls would barely
move; they moved *most* by pixels-touched (Amazon 63.5% vs the Alps' 38.6%). I blamed `hi` — a composite
knob that touches every sloped pixel — and decomposing against a common baseline killed that too: `hi`
alone moves the Amazon **1.20** mean DN, **the fill alone moves it 4.37**. The truth is that **the fill
compresses contrast on ANY non-zero slope**, darkening what the main sun lit and lifting what it did
not, so gentle terrain simply gets gentle compression. The exact invariant is **zero-slope ground is
unchanged** (pinned by `test_flat_ground_is_unmoved_by_any_fill_strength`) — *not* "flat regions are
unchanged", which is not what ART.md:80-83 claims either. Self-regulation does hold, in **magnitude**:
mean |ΔDN| Amazon 4.37 < Sahara 5.05 < Alps 6.87. `>2 DN changed%` counts pixels *nudged*, not how far —
the wrong statistic for the claim. **Consequence for judging: the Amazon and Sahara are slightly softer
too, not only the mountains.**

### 2026-07-17 — THE TILE CUT LANDED (6:17 total), and it was never the expensive stage

The pre-Caspian, pre-GLOBathy pyramid is gone: **62,177 tiles swapped live**, `tiles_old` kept as
rollback, exit 0, first cut ever run under instrumentation (`run_pass.sh --tiles`).

**The headline is that every estimate of this step was wrong, in the same direction.** PLAN carried it as
the gated blocker for days; I guessed "30–60 min" (flagged as a guess — the only reason it wasn't worse).

| stage | wall | cores (of 16) | read | write |
|---|---|---|---|---|
| **SVF — entirely wasted** | **153.5 s (41% of the pass)** | **0.80** (single-threaded) | 30.88 GiB | 0 |
| **tiling** | **223.7 s** | **12.03** (75% util) | 109.77 GiB @ 502 MB/s | 30.25 GiB |
| total | **377.5 s** | | | |

- **`global_occlusion` has no freshness guard, and its consumer does.** `main()` calls it
  unconditionally (`shade_planet.py:414`), then `composite_planet` returns at `:280`
  (`planet_rgb fresh -> skip composite`) **without ever reading `occ`**. So a tiles-only re-run spends
  **2:33 single-threaded reading the whole 31 GB master to compute an array it throws away** — 41% of
  the pass. This is the "only unguarded stage" problem I declared dissolved when gdaladdo was deleted:
  it did not dissolve, it **moved**, and I only found it because the instrumentation printed the stage
  boundaries. Fixing the guard makes the tiles-only pass **377 s → 224 s for free**.
- **The cut is well-parallelised already**: 12.03 of 16 cores, 502 MB/s read. `gdal raster tile`'s
  `-j ALL_CPUS` default needs no help. There is no cheap win left in the tiler itself.
- **`perf` was OFF (paranoid=4) and it did not matter — the right call, for the right reason.**
  `gdal raster tile` is an external black box whose only levers are already flags (`-j`, `--tile-size`,
  `--output-format`); symbol-level attribution pays off on code we own (it is what found the LUT win in
  *our* composite), not here. `stamp.py` — the cheapest instrument, a timestamp per stdout line — found
  the 2:33 waste that perf would not have flagged as waste at all, because perf shows where CPU goes,
  never whether the answer is discarded. **The harness now degrades instead of blocking**, so a missing
  optional instrument can never cost a pass.
- **`memory.current` is not RSS, and believing it would have caused a false alarm.** The cgroup pressed
  its 16 G cap the whole run — but `anon` was **0.58 GiB** against `file` **14.49 GiB**: reclaimable page
  cache from streaming the master, with `oom_kill 0, max 0`. Real peak RSS: **0.71 GiB (SVF) / 2.02 GiB
  (tiling, 18 procs)**. The cap was throttling page cache, not guarding real memory. This is exactly why
  `watchdog.py` tracks **anon**, and I nearly panicked at the total before checking.
- **Verified at the pixel, not the count.** 62,177 tiles matches 07-14 exactly, which proves nothing
  about content. Oracle: Caspian z8/164/96 **100% of px >2 DN, max 78** (the re-fuse landed);
  control Sahara z8/136/111 **0.0% >2 DN, max exactly 2** — the pre-registered LUT/float32 noise floor
  and not one DN more. The change is where it should be and nowhere else. Served tile md5 == disk md5.
- **`--webviewer=none` confirmed at planet scale**: zero leaflet/openlayers/mapml/stac files in the new
  pyramid, where the 07-14 cut left four.
- **The SVF guard, landed the same day: a fully-fresh pass is 153.5 s → 0.29 s.** SVF has no output file,
  so it cannot be `is_stale`-gated like everything else; the guard is **laziness** — `composite_planet`
  now takes `compute_occlusion: Callable[[], np.ndarray]` and invokes it *below* the early return, so it
  runs if and only if the composite is stale. One caller, and `occ` was already first used after that
  return, so no restructuring. Proven with **both arms**: fresh → the callable is never invoked; stale →
  it is (without the second arm the first is vacuous, since an ignored argument would also pass). Every
  stage in the pass is now guarded, and `build_tiles` inherits the "only unguarded stage" title honestly.
- **A viewer, not the tiles, nearly read as a regression.** Post-cut the starfield "disappeared" — because
  the check was run on `planet_tiles/index.html` (a zero-dependency tile smoke test with a daytime-blue
  sky, no stars) rather than `globe.astro` at `/globe`, which is what PLAN's gate actually names. I had
  pointed at the wrong viewer by following a 07-14 HISTORY instruction written before the frontend
  existed. **Dated instructions outlive their context; the viewer is now labelled in-page and in its
  `<title>` so it cannot impersonate the product again.** Kept rather than deleted: it is a *different
  tool* (proves tiles render without the Astro stack), it is read-only rather than a loaded gun like
  `tile_planet.py`, and being gitignored means deletion is permanent — git is not its archive.

### 2026-07-16 — the gdaladdo step DELETED: I optimised it 4.5x an hour before proving it does nothing

Read the gdaladdo docs before the cut, found three candidate flags, killed two on measurement, landed the
third at **4.5x** — and then read the `gdal raster tile` docs and discovered **the whole step is inert.**
The 4.5x was a speed-up of a no-op. HISTORY's own 2026-07-15 lesson — *"the morning's entire optimisation
plan was aimed at the fastest stage"* — was read the same day and walked into anyway. **Optimise only after
proving the stage is on the critical path; "it runs every pass" is not that proof.**

**`gdal raster tile` NEVER reads the source's overviews.** It builds each low zoom from the tiles it just
generated — which is precisely why `--resampling` is documented as *"for max zoom"* and
`--overview-resampling` exists separately. Proven by tiling one raster with and without overviews:
**byte-identical manifest over every tile, identical wall time.** GDAL's RasterIO auto-uses overviews for
any downsampled *source* read, so had low zooms come from the source, both bytes and time would have moved.

- **Where the false belief came from — a confounded fix.** The 2026-07-14 note (*"tiling the 194-source VRT
  directly re-reads every block per low-zoom tile — far too slow"*) bundled **two** changes: materialising
  the VRT to a GTiff, and adding overviews. Materialisation was the real fix; the overviews rode along on
  the same commit and were **never tested separately**. Two changes, one measurement, credit to both.
- **Cost of the belief:** ~3 min and ~4 GB appended to the master, every cut, for nothing — plus the
  "`build_tiles` is the only unguarded stage" wart, which **dissolves**: the unguarded stage no longer exists.
- **Two GDAL facts, still true, still worth keeping** (they apply to `fuse_heightfield`'s `build_overviews`,
  which is real). Recorded *because* they are dead ends — each is plausible enough to be re-proposed:
  **`COMPRESS_OVERVIEW`** is a no-op (internal overviews already inherit the main image's DEFLATE — the docs
  say it is "honoured" since 3.6 but never state the default, which is why it needed checking), and
  **`GDAL_TIFF_OVR_BLOCKSIZE`** is a no-op (they already build at 512, inherited; the documented default of
  128 never applies).

**Two more landed from the same doc read, both proven byte-safe on a tile-ALIGNED rig** (col/row multiples
of 512, matching `planet_rgb`'s `-tap` alignment — the first probe used col 60,000, off-grid, which would
have forced resampling production never does):

- **`--webviewer=none`.** The default is `all`. The live pyramid has been carrying `leaflet.html`,
  `openlayers.html`, `mapml.mapml` and `stacta.json` since 07-14 — dead weight we never serve, and they
  would have ridden into PMTiles. Tiles byte-identical; only the four files disappear.
- **`--overview-resampling=cubic` — a PIN, not a change.** Identified by elimination: unset, it silently
  inherits `--resampling`, so **z0-7 have always been cubic**. `average` was proposed and **rejected on
  test — it is NOT the default and changes z0-7 pixels**; cubic is what built the verified 07-14 pyramid,
  and there is no evidence against it. Pinned so most of the globe's zoomed-out surface stops depending on
  an undocumented default. (Full elimination table: only `cubic` reproduced the default's bytes; `q1`
  degenerates to `min` at these block sizes.)
- **Hazard, docs-derived and NOT measured:** `--resume` "generates only missing files" with **no
  verification**, so a tile left truncated by a kill is skipped rather than repaired. Not hypothetical —
  the 07-15 cut was OOM-interrupted and resumed. Worth a verify pass before trusting a resumed pyramid.

### 2026-07-16 — optimisation #3 landed: `NUM_THREADS` on the GTiff writers (10x), and the "three for three" record explained

`-co NUM_THREADS` had been measured and **rejected three times** here (`-multi`, `-wm`/`-wo NUM_THREADS`,
and `-co NUM_THREADS` for color-relief — see § the profile that killed three flags). PLAN then proposed a
fourth instance on the strength of one number, *libdeflate = 9.93% of python-side CPU*, which lived
nowhere but PLAN and had **no surviving perf artifact**. So it was measured rather than trusted, on real
data (`pipeline/experiments/writer_threads.py`).

**Result: 8.79 s → 0.88 s, a 10.0x speedup on the writer**, with output **byte-identical** (same MD5, with
an LZW control proving the comparison can fail).

**Why this is not a contradiction of the three rejections — the reason matters more than the result.**
Every earlier rejection was Amdahl's law, not a broken flag: for color-relief, libdeflate was **4.33%** of
a stage dominated by libgdal's **19.37%** interpolation, so threading DEFLATE could touch ~18% of it at
best. A *pure writer* has no interpolation — it is essentially all DEFLATE — so the same flag addresses
~100% of the stage. **The flag was never useless; it was pointed at stages that were not compression-bound.**
The rejections and this acceptance are the same finding read at two different call sites.

- **Three writers, not the two PLAN named.** `shade.py`'s region writer is the composite writer's sibling,
  and the "one implementation, both shade paths" rule (§ optimisation #2 landed) exists precisely because
  the float32 fix reached `composite` and never reached `hillshade`. Taking only PLAN's two would have been
  the **fifth** instance of that bug. Applied to `shade_planet.py` (composite), `hillshade.py`, `shade.py`.
- **Two of the remaining writers must STAY unflagged — and that is a hard constraint on `GTIFF_CREATE`.**
  `fuse_heightfield.py:212` and `build_void_wbm.py:116` run under `fuse_planet.py`'s `FUSE_ENV`, which sets
  **`GDAL_NUM_THREADS=1` deliberately**: *"parallelism is across cells, not within a warp"*, with
  `--workers W` cells in flight at a budgeted ~1.5 GB each. An **explicit creation option overrides that
  config**, so flagging them would oversubscribe W x 16 threads against a sized RAM envelope. A shared
  `GTIFF_CREATE` that carried `num_threads` everywhere would therefore silently break fusion's design —
  **the constant must carry the FORMAT options; threading is per-call-site policy.** `render_prep.py:117`
  (hero path) is merely unpaid, not unsafe.
- **Verified in the pass's own environment, not just a clean one.** The first benchmark ran without
  `GDAL_CACHEMAX=512`, which `run_pass.sh` sets and which changes block-cache flush timing — the exact
  shape of this project's seven proxy bugs (the check diverging from the real thing). Re-run under it:
  **10.10x**, unchanged. The tile pass sets no `GDAL_NUM_THREADS`, so the creation option governs there.
- **No rebuild forced.** `composite_params()` serialises KNOBS + palette, never creation options, and
  `hs_params.json` is only `{alt, az, exag}` — verified: params byte-identical, `planet_rgb` still fresh,
  **with a control that fires** (a just-edited source as a dep returns True). The first control tried was
  itself blind — `is_stale` reads `newest_mtime`, which ignores a path that does not exist, so a missing
  dependency can never mark anything stale. The blind-oracle bug (§ 2026-07-06), caught in its own control.
- **Extrapolated saving: ~6 min of the composite's 53.8**, and that is an **upper bound** — the benchmark
  band compresses 2.0x against the planet's 3.0x average, and flatter data deflates faster. The hillshade's
  share is unmeasured; the 3-band RGB number does not transfer to a 1-band raster. **Pays only on the next
  pass**, which is why it is worth exactly one line each and no more.

### 2026-07-16 — `composite_ram.py` was never the number PLAN said it was

PLAN carried *"`composite_ram.py`'s 6.93 GiB is STALE — re-run the fixture so it stops disagreeing with
reality."* Re-running it moves it **further** from the real pass, not closer, because the premise was wrong:
**6.93 GiB was never the fixture's output.** It was the *pipeline* peak measured on 2026-07-15 with the
fixture's help (§ GLOBathy lake depth), and the fixture was rewritten for the post-LUT signature in the same
commit that landed it — so nobody had re-run it since its inputs changed.

Measured today, capped, both arms in separate processes: **3.88 GiB without depth, 4.50 GiB with** — the
depth branch costs **+0.62 GiB** (the 07-15 pipeline-scope figure was +0.48).

**The fixture and the pass measure different things, and always did.** `composite_ram.py` measures
`composite()` *in isolation*; it opens no dataset. The real pass adds five readers, the writers, the GDAL
block cache (`GDAL_CACHEMAX=512`) and runtime overhead — so the fixture is a **lower bound on the pass**,
by ~1.7 GiB, and no amount of re-running will reconcile 4.50 with 6.24. That is not a defect: the docstring
says exactly what it measures. The defect was PLAN conflating two scopes into one number.

**Nothing needs resizing.** The real pass peaks at **6.24 GiB** (§ optimisation #2 landed) against the 12 G
cap = **1.9x**, and composite is once again the peak stage now that the hillshade fix took it 11.6 → 2.03 GB.
`watchdog.py`'s `ANON_WARN_MB = 10_000` sits correctly between the two. Only the quoted numbers were stale.

### 2026-07-16 — the composite parallelises with THREADS, and the xarray/dask question is settled by that

Asked whether the pipeline should move to the xarray/dask ecosystem. Answered by measurement rather than
by argument, because the first answer given was argued from memory and three of its four reasons did not
survive checking (below).

**The measurement.** `shade.composite` — the production function, imported, not retyped — over real
windows read off the real `height/ocean/water/hs/lakedepth_3857` rasters, 8 windows × 32 rows × 131072,
under the usual 12 G scope. (Honest caveat: `snow_a` is zeros and `occ` synthetic; both are
elementwise/interpolation ops whose *cost* is value-independent, so this times the same work. The
bandwidth-driving arrays are real.)

| threads | wall | cpu | cores | speedup | efficiency |
|---|---|---|---|---|---|
| 1 | 3.84 s | 3.83 s | 1.00 | 1.00× | 100% |
| 2 | 2.14 s | 4.05 s | 1.90 | 1.80× | 90% |
| 4 | 1.36 s | 4.80 s | 3.54 | **2.83×** | 71% |
| 8 | 1.08 s | 6.97 s | 6.48 | 3.57× | 45% |

- **numpy releases the GIL, so plain threads work.** 4 threads genuinely occupy 3.54 cores. This kills the
  `ProcessPoolExecutor` design drafted the same morning — it existed to dodge a GIL that does not bind,
  and would have paid ~36 GB of pickling across 1456 windows to do it. Threads need no IPC, no fork-safe
  handle juggling, and no serialisation. **~10 lines around the existing loop.**
- **Memory bandwidth is the real ceiling, not the GIL and not the scheduler.** Efficiency decays 90%→45%
  between 2 and 8 threads; CPU time inflates 3.83→6.97 s for the same work. **~3× is the ceiling and 4 is
  the knee.** No framework changes this — it is a property of streaming 100 MB float32 arrays.
- **Therefore the xarray/dask case collapses on its own merits, not on taste.** Dask's headline benefit
  here is parallel scheduling, and its threaded scheduler would reach the same ~3× by the same mechanism
  (threads + GIL-releasing ufuncs) that a `ThreadPoolExecutor` reaches for free. Two supporting facts,
  both verified rather than recalled: **rioxarray does not replace rasterio** — it is "a geospatial xarray
  extension *powered by rasterio*" (PyPI, 0.22.0), so adopting it *adds* a layer; and **xarray-spatial
  cannot do our hillshade at all** — `hillshade(agg, azimuth, angle_altitude, name, shadows, boundary)`
  has **no z-factor parameter**, which is the entire reason `render/hillshade.py` exists.
- **What dask would genuinely buy, recorded honestly so this can be reopened:** `map_overlap` expresses
  the 1-row halo we hand-rolled; named dims/coords make the per-row latitude z a natural broadcast
  instead of a `.reshape(-1, 1)`; chunk management would retire the manual `del` + `gc.collect()`. All
  real, none worth a migration of code that was verified bit-for-bit this week — and none of it is
  parallelism, which was the thing we wanted.
- **The retracted argument, kept as the lesson.** The first answer gave four reasons to reject dask. Only
  one survived: CLAUDE.md's "prefer boring, debuggable scripts over frameworks" (a real, quotable
  convention). "Zero RAM headroom" was false (`free`: 20 GB available). "OOM-killed twice this week" was
  false (`journalctl -k`: exactly one, 2026-07-15 22:17). "Dask replaces a measured number with a
  scheduler that decides for you" was wrong — dask chunks are explicit. And "dask graphs are harder to
  debug" was judgment presented as finding. **Four reasons felt more rigorous than one; three were
  decoration.** Same disease as the proxy bugs, one level up: the check felt thorough because there were
  several of them. → § 2026-07-16 — the instrumented planet pass

### 2026-07-16 — optimisation #2 landed: `gdaldem color-relief` DELETED; the ramps became a 17.6 KB LUT

`composite()` now takes ELEVATION and applies the land/sea ramps itself via `palette.relief_lut`.
Both `gdaldem color-relief` passes are gone from both shade paths.

**Why a flag could never have fixed it.** color-relief was **28:19 and 24.4% of all pass CPU**,
single-threaded, each pass reading the full 31 GB height raster to write 1 GB. The profile split it
**`libgdal` 19.37% (interpolation) vs `libdeflate` 4.33%** — so `-co NUM_THREADS`, which threads only
DEFLATE, could reach ~18% of it at best. That 19.37% is a per-pixel **binary search** over the 241 rows
`color_relief_rows(step=25)` emits. gdaldem searches because its file format permits arbitrary stop
positions. **Ours are uniform** (0..6000 every 25 m), so the bracketing index is just `elevation/step` —
a divide, not a search. gdaldem cannot know that; numpy can. The LUT is **17.6 KB** at 1 m resolution,
i.e. *finer* than the 25 m rows gdaldem interpolated across.

**Measured, end to end (planet, 12.19 G px):**

| | before | after |
|---|---|---|
| color-relief | 28.3 min | **0 — deleted** |
| composite | 44.3 min | 53.8 min (+9.5: it now reads the 31 GB height, not 1.6 GB of RGB) |
| **the pair** | **72.6 min** | **53.8 min — net −18.8 min** |
| composite peak RSS | 6.93 GiB | **6.24 GiB** (one Float32 window replaces two RGB windows) |
| whole pass | ~98 min | **~72 min (−26%)** with the hillshade fix |

**Correctness, twice, against independent pre-existing oracles:**
1. LUT vs `gdaldem`'s own `land_3857`/`sea_3857` (written before the LUT existed): **6/6 bands, 100%
   coverage, 96.7% identical, 3.3% at exactly 1 DN, ZERO beyond.**
2. LUT-fed `planet_rgb` vs the gdaldem-fed mosaic: **3/3 bands, 100% coverage, ~92% identical, ~7.5%
   at 1 DN, ~0.35% at 2 DN, ZERO beyond.** The tolerance of 2 was **pre-registered with its reasoning**
   (1 DN input x composite's max gain, saturation 1.18 x hi 1.30 = 1.53) — and the distribution landed
   exactly there. A bar set before the run is a prediction; set after, it is a rationalisation.

- **The trap this opened, and closed.** `LAND_STOPS`/`SEA_STOPS` were tracked *only* by
  `ramp_{land,sea}.txt`, whose sole purpose was gating the gdaldem stages. Deleting color-relief without
  moving them into `composite_params()` would have left `planet_rgb` **falsely fresh** after any ramp
  re-tune — silently rendering the planet with the old palette, the exact failure the guard exists for.
  Three new tests pin it (land stops, sea stops, `LUT_STEP_M`).
- **The ramps are applied INSIDE `composite()`, not in each caller** — deliberately. A per-call-site copy
  of a shared decision is precisely how the float32 fix reached `composite` and never reached
  `hillshade` (11.6 GB). One implementation, both shade paths.
- **Follow-up:** `composite_ram.py`'s 6.93 GiB is now stale (its inputs changed). The real pass measures
  **6.24 GiB**, so the 12 G cap is ~1.9x — sound, but re-derive from the real number, not the fixture.

### 2026-07-16 — optimisation #1 landed: hillshade float32 + 256-row windows (1.84x faster, 5.7x less RAM)

Carried `composite()`'s 2026-07-14 fix to its sibling, `per_row_zfactor_hillshade`, which had never
received it. Measured on the real planet (12.19 Gpx), not a fixture:

| | before (float64 @ 1024) | after (float32 @ 256) |
|---|---|---|
| wall | 932 s (15:32) | **508 s (8:28)** — **1.84x** |
| peak RSS | 11.6 GB | **2.03 GB** — **5.7x** |
| cgroup reclaims | 122,501 | — |

**Correctness, full-raster against an independent pre-existing oracle** (`hs_3857.tif`, written by the
OLD code during the previous night's pass, before this change was designed): **99.9374% of 12.19 billion
pixels bit-identical, 0.0626% differ by exactly 1 DN, ZERO beyond 1 DN.** Worst pixel: 1 DN at lon
-179.408 / lat 85.051 — inside the polar band that gets capped flat regardless.

- **The speed-up was not the goal and is the interesting part.** The change was made for RAM; float32
  halved the bytes crossing cache/RAM and removed 122k reclaims, and the stage got ~2x faster for free.
  It is still 97% CPU on one core — numpy is not threaded here — so the win is pure memory traffic.
- **The float64 was always dead weight:** the function emits **uint8**. Tests show float32 tracks float64
  to <=1 DN, so every one of those extra bytes was discarded on the last line.
- **The trap that TDD caught, and that a colour test never would have.** `zfactor` is built from
  `np.cos(latitude)` -> float64; under NEP 50 `float32 array * float64 array` -> **float64**, which
  silently restores every byte the change saves *while all output assertions still pass*. Fixed inside
  `hillshade_array` (`np.asarray(zfactor, dtype=heights.dtype)`) rather than at the call site, so no
  future caller can reintroduce it. Latitude stays float64 upstream — `merc_y ~2e7` needs the mantissa.
  `tests/test_hillshade.py` (9 tests, suite 120 -> 129) pins dtype, <=1 DN equivalence, and window
  invariance at 256/97/1024/4096 — the last being what makes changing `window_rows` safe at all.
- **My own proxy bug, the seventh, caught by the oracle in one shot.** The first benchmark ran
  `altitude=46.0`, typed from CLAUDE.md's *locked constants* — but those are the **Blender hero** sun
  altitude; the tile path uses `KNOBS["alt"] = 45.0`. Result: 10.3 billion px "differing", **mode at
  3 DN**. 255·sin(46°) − 255·sin(45°) = **3.1 DN** — the offset was the entire histogram. Diagnosed
  instantly by the *shape*: precision noise centres on 0, a systematic offset does not. **A sampled
  check, or one reporting only a mean, would have read as "small float32 rounding" and shipped.**
  Distribution over aggregate; and the re-run does `from pipeline.tile.shade_planet import EXAG, ALT, AZ`
  — imported, not retyped, because a benchmark that retypes a constant measures a different program.
- **A real divergence, flagged not fixed:** heroes use sun altitude **46°**, tiles **45°**. Same species
  as the known hero/tile sea-ramp divergence — visually nil (3 DN on flat ground), but a second instance
  of the two render families drifting. Fold into the deferred hero sea-sync, do not touch alone.
- **The guard is blind to code changes, by design, and that was right here.** `hs_params.json` records
  `{exag, alt, az}` — *source-level params*, not code — so this pure-performance change left
  `hs_3857.tif` fresh and did NOT trigger a 31 GB rebuild. Correct, because equivalence was *proven*.
  But note the general gap: had the change altered the algorithm's output, the guard would not have
  noticed. It is the deliberate trade for not having `git checkout` force a full-planet rebuild
  (`write_if_changed`, 2026-07-15) — so any *behavioural* change to a shading kernel must be verified
  against an oracle by hand, exactly as this one was.

### 2026-07-16 — the instrumented planet pass: the baseline, and why every warp optimisation we planned was worthless

The GLOBathy + Caspian + `WATER_RGB` pass, run once under full instrumentation (`perf record -F 49 -g`
wrapping the whole job so it inherits into every forked child; a 0.5 s cgroup sampler for RSS/threads/
disk; the pass's own stage prints timestamped; the cgroup's own `memory.peak`). **98 min wall, exit 0,
`planet_rgb.tif` 11.96 GB, 349,384 perf samples in 65 MB.** Shade only — tiling deliberately gated on
looking at the mosaic first.

**Mosaic verified** against a *pre-registered* known-bad (what it would read if depth never reached the
pixels: all lakes identical at `(141,197,195)`):
Baikal `(81,137,149)` lum 121.6 over 959,498 px · Namtso `(100,155,164)` lum 139.6 over 28,092 px —
**18.0 lum apart** where yesterday they were the same pixel. Tanganyika `(81,136,149)` lands on Baikal,
as absolute (not per-lake) calibration requires. Caspian: 2,372,060 class-1 px, spread **0.0 → 30.8**.
Its planet numbers (137.1/158.9/167.8) match the region render's (137.0/158.8/167.8) to a decimal — an
unplanned cross-validation that the two shade paths agree.

**The stage timeline — the whole point, since none of this had ever been measured:**

| stage | wall | CPU | threads | note |
|---|---|---|---|---|
| height warp (31 GB out) | **5:07** | **486%** | 17 | already parallel |
| ocean + water warps | 2:32 | 110% | 17 | |
| **color-relief (land)** | **12:31** | 98% | **1** | reads 31 GB → writes 1 GB |
| **color-relief (sea)** | **15:48** | 98% | **1** | reads 31 GB again |
| **per-row-z hillshade** | **15:32** | — | — | **anon peaks 11.6 GB** |
| global SVF | 2:29 | — | — | free |
| composite (364 windows) | 44:20 | — | — | 2.7 GB, comfortable |

CPU attribution (6,830 CPU-s total): python 43.5% · gdalwarp 23.0% (height) · gdaldem sea 13.6% ·
gdaldem land 10.8% · **gdal_rasterize ×363 4.0%** · **gdalwarp ×363 3.8%**.

- **The morning's entire optimisation plan was aimed at the fastest stage.** The 31 GB height warp runs
  at **486% CPU / 17 threads in 5 minutes**. `-wo NUM_THREADS=ALL_CPUS` + `-wm` would have optimised a
  warp that is *already ~5× parallel* — and we'd have credited the flags with any noise. The correction
  recorded on 2026-07-15 (that the lake warp's profile does not transfer) was right, and the reason is
  now visible: **the expensive warp was the small one.** 310 MB in 62 min (masker-bound) vs 31 GB in 5.
- **`-co NUM_THREADS` is NOT the fix for color-relief either — the third "obvious flag" to die.**
  Measured split of gdaldem's 24.4% of all CPU: **`libgdal.so` 19.37% (the interpolation) vs
  `libdeflate.so` 4.33% (compression)**, `libz` 0.01%. So the flag that threads only DEFLATE addresses
  **~18%** of the stage; best case ~5 min of 28. Symbol addresses cluster tight
  (`0x1a99c8b`–`0x1a99ca8`) = one hot loop in a stripped libgdal. Flag drift *looked* like the
  explanation (the height warp has the flag, color-relief doesn't); the profile says otherwise.
  Three for three: `-multi`, `-wm`/`-wo NUM_THREADS`, `-co NUM_THREADS`.
- **The box averaged 1.16 of 16 cores** across 98 min wall / 114 min CPU. The pipeline is ~93% idle
  silicon, and it is not I/O-bound (the height warp: 126 MB/s write vs 6 MB/s read, 720 MB RSS).
- **The 12 G cap was sized from the wrong stage.** PLAN called it "1.7× measured" from `composite()`'s
  6.93 GiB. Measured here, the **hillshade** peaks at **11.6 GB** — the cap is **1.03×**, and the cgroup
  logged **122,501 reclaim events** grinding to keep it under. It survived (`oom_kill 0`), but the
  hillshade's 15:32 is a *thrashing* number, not a clean one. The composite measurement was never wrong;
  it was the wrong stage. Same disease as the day's proxy bugs, one level up.
- **Instrumentation notes for next time.** `perf record -- cmd` inherits across fork+exec, so one file
  covers gdalwarp/gdaldem/gdal_rasterize/numpy, filterable with `--comms`; use `-g none` for a flat
  report or the call graphs swamp it; libgdal is stripped, so read the *dso* split
  (libgdal-vs-libdeflate) rather than hunting symbols. Sample by **cgroup**, never `pgrep -f` (which
  matched the `/usr/bin/time` wrapper on 2026-07-15 and, twice on 2026-07-16, matched the very shell
  issuing the `pkill`). Attribute per **PID**, never comm+time-window: differencing across two
  same-named processes produced **−0.1% CPU**, an impossible number that was caught only because it was
  impossible on its face.

### 2026-07-15 — GLOBathy lake depth: a render layer, not a fusion channel; and what the cone is actually worth

Reopens the 2026-07-07 "Lake depth: flat stays" decision, whose stated bar was *"real modeled data —
GLOBathy or better"*. Acquired, wired, validated on renders, **approved by Rohan on the Tibet + Baikal
A/B**. The full pass is not yet run.

- **Architecture reversed: a render layer beside snow, NOT the re-fuse PLAN.md:67 specified.** The
  deciding constraint was already on the books and PLAN.md had simply not restated it — *"tint-only,
  never carve displacement (at 15× Namtso becomes a 1.5 km crater and the shadow-catching plate dies)"*.
  If depth never enters the heightfield, the fusion master is not its home: it is a **rendering** input,
  exactly like snow, which is warped at composite time and has never touched fusion. Three consequences,
  all good: **no re-fuse**; **no HydroLAKES join** (it existed only to place basins vertically, and
  nothing is placed) → **the layer stays CC0 with no attribution obligation**; and a future z10 re-fuse
  would not redo it, since depth is not in the master. `HISTORY.md:1110` had recorded this fork as open
  ("post-tint stage vs fusion depth channel"); this closes it.
- **The epistemics, measured — and my first "validation" was circular.** I checked `Dmax_use_m` against
  published depths for Baikal/Erie/Superior/Tanganyika/Ladoga/Titicaca, got exact matches, and called
  the calibration verified. All six sit in the **0.10% of lakes (1,487) that carry a surveyed depth**,
  where GLOBathy *uses the published number verbatim* — I was comparing a value to itself. The real
  split: of our 83,357 rendered lakes, **647 (0.78%) surveyed, 82,710 (99.22%) random-forest estimate**
  — though **14 of the 15 deepest are surveyed**, so the visual weight lands on real numbers.
- **The cone is right in scale, wrong in shape (the Caspian is the only place it can be falsified).**
  `experiments/globathy_vs_gebco.py`: deepest point within **68 km** on a 1,200 km lake and max depth
  within 1.6 m (1023.6 vs 1022.0) — my prediction that it would *invert* the Caspian was wrong. But
  correlation is only **0.534**, median |error| **191 m**, and where the truth is under 20 m the cone
  claims **155 m** — it renders the famously ~5 m north shelf as a 236 m basin, because it cannot know
  about shelves or sills. This **empirically settles** keeping the Caspian on GEBCO.
- **GEBCO is not a usable oracle for lakes.** Erie's true max is 64 m; GEBCO says **225** (its "deepest
  point" lands near Buffalo, at the Niagara outflow). Superior's is 406; GEBCO says **469**. GLOBathy's
  `Dmax` beats GEBCO on both. So two of the three checks were void — you cannot falsify a model against
  a broken measurement — and only the Caspian (sea-like, properly surveyed) is a genuine test.
- **Surveyed-only was tested and rejected.** Restricting depth to the 647 surveyed lakes was tempting
  (they carry **55.7% of all lake pixels**) but **84.7% of every surveyed lake on Earth is in the USA**:
  Canada has 41,793 lakes worth drawing and 58 real depths. It would render **survey funding as geology**,
  with the discontinuity landing on the US/Canada border, through the Great Lakes. Worse than either
  uniform option, and it fixes the *scale* axis while leaving the *shape* — which was the actual
  objection — untouched. Uniform modelled treatment is the deliberate choice; caveat it on the About page.
- **The ramp: log1p, decided by measurement not taste.** The median lake is **11.2 m** and Baikal is
  1642 — three orders of magnitude. Linear parks the median lake at **0.7%** of the ramp (invisible);
  sqrt at 8.3%. Across 457,722 real lake px in Tibet the p10–p90 spread is **log1p 0.38 vs sqrt 0.14** —
  sqrt is a no-op dressed as caution. Caveat worth keeping: log1p hands most of the ramp to shallow
  water, which is exactly where the cone is least trustworthy. `LAKE_STOPS[0]` is **derived from**
  `WATER_RGB` rather than copied, so the shore tint cannot drift from the flat tint the way WATER_RGB
  itself drifted from the sea.
- **What the flat fill was costing, in one number:** today Baikal (1642 m) and Namtso (125 m) render
  **the identical pixel colour, (141,197,195)** — 13× the depth, zero difference. With depth: (75,131,145)
  vs (97,152,162). Coverage is fine: GLOBathy reaches 71% of WBM lake px in Tibet / 99% at Baikal, and of
  the shortfall ~31% is whole ponds with a **median size of 2 px** (no gradient possible at any threshold,
  so lowering `MIN_BYTES` buys nothing) while ~69% is rim inside graded lakes — the HydroLAKES↔WBM
  shoreline mismatch — invisible because the ramp starts at `WATER_RGB` and reads as a shelf.
  **528 bodies carry 91% of all lake pixels**, which is why a threshold that keeps 83,357 of 1.43 M
  rasters loses nothing visible.
- **RAM measured (`experiments/composite_ram.py` + a timed region render), and the cap was already wrong.**
  Real pipeline peak: **6.45 GiB without depth, 6.93 GiB with** — the depth branch costs **+0.48 GiB**,
  not the ~1 GB I predicted by summing temporaries (numpy frees as it goes; the peak is not the sum).
  The finding is that **today's code already peaked at 6.45 GiB against the 8 GB cap** — 19% headroom
  *before* this change. That 8 GB was never sized against anything; it was picked reactively after the
  morning's OOM, when the box had ~10 GB free because 12 GB was trapped in tmpfs. **Cap raised to 12 GB**:
  1.7× the measured peak, still half the 24 GB now available, so it still kills the job and not the box.
- **The one-shot 83k-source warp, profiled (`perf`, paranoid lowered to 1). Verdict: viable, ~50 min,
  and every one of my three bottleneck hypotheses was wrong.** The warp source is the **VRT** (gdalwarp
  sees `lakedepth.vrt [1/1]`, one logical dataset); the VRT fans out internally, holding ~450 of the
  83,356 TIFFs open at a time. Where the CPU actually goes:
  `GDALWarpNoDataMasker` **51.3%**, `GDALCopyWords64` 7.2%, `VRTComplexSource::RasterIO` **2.4%**.
  - **So the bottleneck is `-srcnodata` masking, not the sources and not the resampling.** The masker
    walks every source pixel testing it against -9999 on a raster that is ~98% nodata. The VRT read path
    is 2.4%, so the many-source VRT is a **non-issue** — the "materialise before touching a many-source
    VRT" learning applies to the *tiler* (which re-reads per tile), not a one-shot warp that touches each
    source once. **No fallback pre-mosaic needed.**
  - **Dead ends this killed:** all 83,356 sources are LZW + **STRIPED, never tiled** (GDAL's ~8 KB default
    → Baikal gets 1-row strips of 88 KiB, an apparent 88× read amplification for a 256² window). Looks
    damning, measures at 2.4%: chunking evidently spans each source's width, so each strip decodes about
    once. **Re-tiling 83 k files would have bought nothing** — a fix I was about to propose.
  - **Docs correction that matters (`gdalwarp` page):** `-multi` is *"Two threads... **Note that
    computation is not multithreaded itself**"* — it overlaps I/O with compute and would have bought ~0
    here. **`-wo NUM_THREADS=ALL_CPUS`** is the option that parallelises computation, and **`-wm`** (never
    set by us, docs: *"shared among all threads... especially beneficial when running with `-wo
    NUM_THREADS` greater than 1"*) sizes the chunks. `-co NUM_THREADS` is a **GTiff creation option** for
    *"multi-threaded compression"* only — which is exactly the observed 17 threads / 16 idle: DEFLATE
    workers starved by a single warp thread at 99%.
  - **Untested lead, worth a look before optimising blindly:** `-srcnodata -9999` merely restates the
    nodata the VRT already declares. If the sources carried **0** as their fill instead, no masking would
    be needed at all — and bilinear blending toward 0 at a lake edge is *physically correct*, since depth
    really does go to 0 at the shore. That could delete ~half the warp's CPU, but it is a source rewrite.
  - **Cost is spatially non-uniform, which broke my estimate:** 10% at 2:25 and 20% at 3:32 (the polar
    band above ~78N is empty of lakes) → I projected ~20 min; it hit the 50-70N lake belt (Canada,
    Scandinavia, Siberia) and collapsed ~7x, landing near **50 min**. Output ~400 MB for 12.19 Gpx.
  - **The real prize is elsewhere:** the same serial path, no `-wm` and no `-wo NUM_THREADS`, applies to
    the **31 GB height warp**, which re-runs on *every* re-fuse — whereas this lake warp is a
    freshness-guarded one-shot. `ocean`/`water` already use GDAL's documented fast path (`-r near
    -ot Byte`, no nodata) and have nothing to win.
  - **CORRECTION, same day — this profile does NOT transfer to the height warp, so the "prize" above is
    unfounded.** Checked rather than assumed, on both counts that produced it:
    (a) **The 51% masker cannot even run there.** `GDALWarpNoDataMasker` is driven by nodata;
    `planet_heightfield.vrt` declares **zero** `NoDataValue` entries and the height warp passes no
    `-srcnodata`. Half the measured cost is absent from the height warp *by construction*.
    (b) **The "17 threads, 16 idle" is an artifact of output size.** That was `-co NUM_THREADS`' DEFLATE
    pool with nothing to compress — the lake warp writes **310 MB**. The height warp writes **31 GB**, 100×
    more, so the already-set `-co NUM_THREADS=ALL_CPUS` has real work and the write side may already be
    parallel.
    The height warp's bottleneck is therefore **unknown**, not "the same". Generalising one warp's profile
    to another warp is the same error as the day's other five — reasoning from an unrepresentative sample.
    **We also have no baseline wall-clock for it at all**, which is the decisive practical point: changing
    its flags before measuring it once would destroy the only free chance to learn whether they helped.
  - **Method note:** the first three profiling samples were of `/usr/bin/time`, not gdalwarp — `pgrep -f`
    matched the wrapper's command line — and reported "Threads: 1, zero source opens, zero reads" while
    progress advanced. Impossible on its face, and it *fit my pool-churn hypothesis*, so I built on it
    instead of questioning it. Four predictions were wrong today (+1 GB RAM → +0.48; the cone would
    invert the Caspian → 68 km; ~20 min → ~50; VRT/striping is the bottleneck → 2.4%). Measure.
  - **Landed: `1:01:38` wall, peak RSS `2.18 GB`, 310 MB output, exit 0** (102% CPU — the single warp
    thread plus DEFLATE workers). Grid is byte-identical to what `warp_inputs` generates (`-te`/`-ts`
    both derive from `height_3857.tif`), so the hand-run artifact was stamped `.done` rather than
    re-warped. **RSS is the quiet headline: 2.18 GB.** The warp is nowhere near the RAM cliff, so `-wm`
    (which sizes warp chunks and is currently unset → GDAL's 64 MB default) has plenty of room to grow
    alongside `-wo NUM_THREADS`. That pairing is the untested prize on the 31 GB height warp.
- **The calibration oracle, run on the WARPED planet raster — the check the 2026-07-07 prototype lacked
  and was rejected for.** Max depth within each lake vs its published survey: Baikal 1638.3/1642 (0.998),
  Tanganyika 1464.7/1470 (0.996), Ladoga 229.7/230 (0.999), Titicaca 279.1/281 (0.993), Superior
  405.5/406 (0.999), Namtso 123.9/125 (0.991). All within 1%. This proves *two* things at once: GLOBathy's
  cone is calibrated to real surveys where they exist, **and** the 3857 warp preserved it — no shift, no
  rescale, no nodata clobber. (The ~0.5% shortfall is expected: the cone's apex rarely lands exactly on a
  306 m pixel centre.)
  - **My first oracle was broken, and it cried wolf on the Caspian.** It took the **max over a lat/lon
    bounding box**, which for the Caspian catches every Iranian, Turkmen and lower-Volga lake in the
    rectangle — it reported a 92 m "leak" whose argmax sits at 49.88E/40.45N, *on land near Baku*. Point
    samples on open Caspian water (deep S basin, mid S basin, middle basin, N shelf ×2) all read exactly
    **0.0**. The lesson is the recurring one: a rectangle is not a lake, and an oracle that can't tell the
    difference will fail on the one body you most need it to be right about.
- **The freshness guard fired on the real thing, first time out.** The entire `planet_tiles/` derived chain
  dates from **2026-07-14 10:38–11:24**, while the planet VRTs were rebuilt **2026-07-15 16:08** after the
  Caspian re-fuse → `height`/`ocean`/`water` all correctly report `stale=True`, `lakedepth` `False`. Made
  concrete: **`water_3857.tif` today reads watermask class `2` at the Caspian deep basin**, not the `1` the
  re-fuse wrote — i.e. without the guard, a re-run would have shaded the Caspian from the pre-re-fuse mask
  and the flat-slab bug would have survived the fix silently. This is exactly the trap the guard was built
  for on 2026-07-15, and it is why no manual `rm` list is needed before the pass.
  - **The two shade paths have opposite staleness exposure, which is worth keeping straight.** The
    **region** path (`shade.py --cells`) is immune: `reproject_cell` warps from `CHUNKS/<name>/` with
    `-overwrite` on every run, so it always sees the current chunks — that is *why* it has no skip-if-present
    and the deferred "region idempotency" item is not costing correctness. The **planet** path caches into
    `planet_tiles/` and is exposed by design, which is what the guard exists to cover. Practical consequence:
    a Caspian regression check is valid via the region path today, and only valid via the planet path *after*
    the mask re-warp.
- **Item 6 — the Caspian regression, proven at the render level (`e040_n30`/`e050_n30`, 7281×4456).**
  Measured over the 2,372,061 class-1 Caspian px: routing is 100% class 1 → sea ramp; **0 px** of lake
  depth reach `composite()`; and the structure result is the one worth keeping — luminance p10/p50/p90 was
  **182.9 / 182.9 / 182.9 before (spread 0.0 across 2.37 M pixels — a *literal* flat slab)** and is now
  **137.0 / 158.8 / 167.8 (spread 30.8)**. The `before` is the same geographic pixels in `planet_rgb_v1.tif`,
  proven pixel-comparable rather than assumed: exact integer lattice offset (80100, 49621 px) and land
  correlating **0.9972** (mean |Δ| 2.7 lum = the region path's *regional* SVF normalisation vs the planet's
  *global* one — a real difference to remember when reading any region render as a proxy for the planet).
  The PLAN's prediction held exactly: the win is **structure, not darkness** — the Caspian stays legitimately
  bright (p50 158.8, median depth only ~48 m); a flat slab became a shaded basin.
  - **Why it was runnable before the pass at all:** the two shade paths differ in what they read. `shade.py`'s
    `reproject_cell` warps from `CHUNKS/<name>/` with `-overwrite` every run → always current. The planet path
    caches into `planet_tiles/`, whose `water_3857.tif` still reads **class 2** at the deep basin, so a planet
    re-shade today would have tested the old bug and "confirmed" a failure that no longer exists.
  - **The region path is NOT windowed** — it composites the whole region at once, so cell count is a direct RAM
    multiplier. I widened the scope to 4 cells (70 Mpx = 2.1× the planet's 33.6 Mpx window) → **~14.5 GiB →
    OOM-killed at the 12 G cap** (`constraint=CONSTRAINT_MEMCG`: the cap killed the job, not the box, which is
    exactly what raising 8 G → 12 G was for). The morning's 6.93 GiB measurement predicted this precisely and I
    failed to apply it. PLAN's original 2-cell scope = 32.4 Mpx ≈ one planet window, and fits.
  - **Two false alarms in one session, same root cause: testing a proxy instead of the contract.** (a) A **bbox
    max is not a lake oracle** — it caught Iranian and lower-Volga lakes and reported a 92 m Caspian "leak"
    whose argmax sat on land near Baku. (b) `lakedepth_*.tif` **on disk is the raw, unmasked warp**; `lakes_only`
    is applied in memory (`shade.py:163`), so 1,578 px of shore-lake bleed look like a leak in the file and are
    zeroed before any pixel sees them. Both were my oracle, not the pipeline. **Select by watermask; assert on
    what `composite()` is handed.** Also discarded: an RGB-distance test comparing shore px to the *mean* of all
    sea px — meaningless when the population spans a 98-lum deep basin.
- **Latent dependency gap, found while stamping (not yet fixed, bites only at z10):** the `ocean`/`water`/
  `lakedepth` warps take their grid (`-te`/`-ts`) from `height_3857.tif`, but **none of them depends on it**
  for freshness — `lakedepth`'s only dep is `LAKE_VRT`. Harmless while the grid is frozen at z8; the moment
  a z10 re-fuse re-warps height to a different grid, `lakedepth` stays "fresh" at the old dimensions and the
  composite reads mismatched windows. An mtime dep on `height` is the wrong fix (it would force a needless
  62-min re-warp every time height rebuilds to the *same* grid) — the right one is to compare the existing
  raster's `width/height/bounds` against the target and rebuild only on a genuine mismatch.
- **Process, and the day's real culprit: `/tmp` is a 15 GB RAM-backed tmpfs.** Region renders had been
  writing their intermediates into the session scratchpad — 12 GB of `c_land`/`c_sea`/`sp_merc`/`height`
  tifs from finished experiments (`southasia`, `prod_iceland`, `seamtest`, `stress/scandinavia`), held in
  RAM and spilling to swap. That is why **swap sat pinned at 7/7 all day**, and why the morning's region
  render OOM-killed a box that looked like it had room: the composite's arrays were the trigger, but this
  was why there was no headroom to absorb them. It also broke the Bash tool for ~40 minutes (Warp's
  output-capture hook hitting the tmpfs quota). Clearing it returned 11.5 GB of /tmp, **all 7 GB of swap**,
  and 4 GB of RAM. CLAUDE.md already says to keep project data on ext4; the scratchpad is not an exception.

### 2026-07-15 — The staleness trap: freshness guards for the planet shading chain, and a 41 GB reclaim

Found while auditing INVENTORY.md, which was stale only in the boring way (sizes/dates) but omitted
enough to hide both problems below.

- **`exists()` conflated "built" with "still correct" — one flaw, two symptoms.** Every stage of
  `shade_planet.py` guarded on `if not out.exists()`. The Caspian re-fuse rewrote 4 of 540 chunks, so a
  plain re-run would have **skipped every stage and re-cut tiles from the pre-Caspian rasters**. Worse:
  `planet_rgb.tif` + its `.done` both existed, so the composite would have been skipped too — and that
  file predated `ramp_sea.txt` (12:28 vs 18:59), so the run would have silently **regressed the locked sea
  rework** on top of missing the Caspian. The same flaw also forces a 31 GB rewrite for a 0.15% change:
  the cache granularity is the file (the planet), the change granularity is 4 cells.
- **Fixed with content-gated mtime (`is_stale`).** A stage re-runs if its output is missing, was never
  stamped `.done`, or is older than any input. Three decisions earn their place: (1) inputs include the
  chunk **directory**, not just its VRT — re-fusing a cell never moves the VRT's mtime, which is exactly
  how this hid; (2) freshness reads the **`.done` marker, never the raster** — GDAL stamps its target at
  the *start*, so a crashed pass leaves a full-sized, freshly-dated, half-written file that any mtime test
  on the raster would accept (this closes a partial-output hole the old guard also had, now that `.done`
  covers all 7 outputs, not just `planet_rgb`); (3) params that live only in source (`KNOBS`,
  `WATER_RGB`, ramp stops) are **materialised into generated files via `write_if_changed`**, which rewrites
  only on a real value change. Hashing a 31 GB raster to decide whether to rebuild it is self-defeating,
  and plain mtime on `palette.py` would force a full planet rebuild on every `git checkout`; a generated
  file whose mtime moves iff a value moved gives precision without either cost. `palette.color_relief_text`
  was split out of `write_color_relief` so a ramp can be compared without being touched (byte-identity
  tested). `tests/test_shade_planet.py` covers all of it, including the re-fused-cell case.
- **Windowed patching: possible, rejected for now.** The Caspian is ~0.15% of `height_3857.tif` (≈3,277 ×
  5,462 px of 12.19 billion) — a ~680× write amplification. The prep chain *is* patchable and provably
  seam-free: `gdalwarp` opens an existing target in update mode and resamples from the source VRT (so
  `-te` yields bit-identical output), color-relief is per-pixel, hillshade is local given a halo. Rejected
  because **it wouldn't help**: `WATER_RGB` is a planet-wide change, so the composite (the expensive stage)
  must re-run regardless — and GLOBathy will force a full pass anyway, so a patch path would cost real
  effort, risk reintroducing the seams `shade_planet.py` exists to prevent, and still not spare that pass.
  Batch Caspian + `WATER_RGB` + GLOBathy into one pass instead. (Wrinkle if it's ever built:
  `global_occlusion` normalises against a planet-wide `svf.min()/max()` — non-local, the same hazard flagged
  for GLOBathy's shore-distance transform.)
- **Reclaimed 41 GB** (487 → 529 GB free) — itemised in [INVENTORY.md](INVENTORY.md). Mostly superseded
  generations the old one-line `planet_tiles/` summary hid: the retired 194-strip `blocks/` (8.2 GB), the
  pre-rework `tiles_old/` (13 GB) and `planet_rgb.tif` (14 GB, also the trap above), the `redsea_proto/`
  A/B variants (4.8 GB). Kept `planet_rgb_v1.tif` — it is the source of the live tiles and the only RGB
  rollback until the Caspian re-shade lands.

### 2026-07-15 — Inland water: the `WATER_RGB` drift, the Caspian probe (open question resolved), and the lake-depth dataset evaluation

Triggered by Rohan spotting a "stark difference" between inland lakes/rivers and the reworked sea on the
globe (Caucasus/Caspian screenshot).

- **`WATER_RGB` had silently drifted, and it was a test gap.** The 2026-07-14 sea rework deepened the sea
  surface ~15% (`8FC7C5` → `85B9B7`) but left the flat inland tint stranded at the old-era `98C5C8`
  (152,197,200) — brighter *and* bluer than the sea it's meant to sit beside (B=200 > G=197, a cool cyan
  lean the teal sea doesn't have). Originally the two *were* related (inland = a slightly-lighter tint of the
  sea surface, the standard lake convention); the rework broke that silently because
  **`tests/test_palette.py` freezes the land/sea ramp endpoints but not `WATER_RGB`** — nothing tied the
  inland tint to the sea surface, so nothing failed. Re-synced to **`#8EC6C4` (142,198,196)** = the new sea
  surface lightened ~7%. Worth adding a guard that pins `WATER_RGB` *relative to* `SEA_STOPS[0]` so the
  relationship can't drift again.
- **But the base colour was never the real problem — measured, not assumed.** The re-render moved the
  Caspian only 184 → 180 luminance: imperceptible. Sampling the actual raster showed why: the sea spans
  **lum 126 (deep basin) → 191 (coastal shallow)** depending on depth, so the Caspian's flat 180 already
  sat right next to the sea's *coastal* band. The eye compares it against the **deep** basin, and no flat
  fill can close a 126-vs-180 gap. **The clash is structural — flat fill vs depth shading — not chromatic.**
  The `#8EC6C4` change is kept on its own merit (small/shallow lakes and rivers *should* be flat, and they
  now sit in the sea's green-teal family), but it is not the answer to what Rohan saw.
- **Open question resolved — "Caspian Sea routing" (both halves of its probe).** WBM class = **2 (inland
  lake)**, and GEBCO **does** carry its measured bathymetry. The fusion consults GEBCO only where `ocean`
  (`fuse_heightfield.py:211`), and `coastal_water` (`|land| ≤ 1`) can't fire on a −28 m surface → the
  heightfield takes GLO-30's flat lake surface. Verified: fused = **−28.0 m at both the deep basin and the
  north shelf**, while GEBCO holds **−464 m / −1026 m**. The data exists and fusion discards it.
- **The fix, as shipped** (`fuse_heightfield.is_caspian`, re-fused 2026-07-15; migrated here from PLAN on
  2026-07-16 once it stopped being a forward plan). One rule absorbs the Caspian into `ocean`, after which
  *everything downstream flows with no shading change* — oceanmask → sea ramp + `sea_lift`/`sea_shade`/
  `sea_svf`, and `classify_water` reclassifies 2→1 so the flat-water branch stops catching it:

      (wbm == 2) & (land < CASPIAN_MAX_SURFACE_M) & in_bbox(46.5, 36.5 → 55.5, 47.5)

  **Each clause earns its place, and the bbox is load-bearing rather than laziness:**
  - `wbm == 2` gives the **DEM's own shoreline**, so GEBCO's coarse 15″ coast never defines the edge
    (`min(gebco, -1)` then keeps shallow margins continuous instead of cutting a ring).
  - `land < −5 m` excludes the **Mingevir Reservoir** (+83 m); the Caspian's surface is a uniform −28 m.
  - The **bbox** excludes the **Dead Sea** (−430 m, WBM lake, but **no GEBCO bathymetry**). Without it the
    rule catches the Dead Sea, which collapses to `min(gebco, -1) = −1` and renders as a flat bright slab —
    a regression. This is why the rule is not simply "below-sea-level lakes".
  - Uniquely cheap **because the Caspian is below sea level throughout**, so absolute elevation maps onto the
    existing sea ramp: no new ramp, no per-lake datum. Nothing else on the planet qualifies.
  - **Expected result was structure, not darkness** — median Caspian depth is only ~48 m, so it stays
    legitimately bright. Predicted lum 180 → 168 shelf / 152 mid / 146 deep (vs Black Sea 129). The
    2026-07-15 regression render measured p10/p50/p90 = **137.0 / 158.8 / 167.8** against a *literal* flat
    slab (spread **0.0** over 2.37 M px). A flat slab became a shaded basin, as predicted.
- **Lake-depth datasets evaluated (answers `lake_depth_prototype.py`'s "see the PLAN.md open question").**
  GEBCO was probed across every major lake: real bathymetry for **the Caspian and the Great Lakes only** —
  Baikal, Tanganyika, Victoria, Titicaca, Ladoga, Great Bear and the Aral all return a flat surface
  elevation. So there is no general "lakes get bathymetry" feature available from what we already hold.
  - **GLOBathy** (Khazaei 2022, *Sci Data*; CC0; 1.43 M waterbodies; 1″) — **chosen** as the general answer.
    It is literally `lake_depth_prototype.py` *with* calibration: the same linear cone `D = l × Dmax / L`
    (Hollister & Milstead distance method over HydroLAKES), but with true published `Dmax` for every lake
    GEBCO misses. Fake but *visually plausible*, which is the stated bar. Caveats: a single deepest point per
    lake, no sills/ridges; depth-below-surface with **no elevation column** → needs a HydroLAKES join
    (CC-BY-4.0 attribution, unlike GLOBathy's CC0) to place basins vertically.
  - **Architectural catch that shapes the eventual implementation:** a shore-distance transform is inherently
    **non-local**, but `fuse_planet` is deliberately per-pixel/co-located precisely so cells are independent
    and share bit-identical seams. A lake straddling a cell edge would compute wrong distances cell-wise —
    which is the argument for eating GLOBathy's pre-computed, globally-consistent per-lake rasters rather
    than rolling our own cone. (At 306 m/px only lakes more than a few km across show any gradient, so a
    few thousand rasters, not 1.4 M.)
  - **3D-LAKES** (Huang 2025, *Sci Data*) — **rejected.** Its bathymetry covers only the lake bed *exposed
    by water-level variation* over Landsat 1984–2021 (the drawdown zone); anything below the historical
    minimum water level is absent, so a stable-level lake like Baikal yields a thin rim and nothing else.
    Also quantized to 91 elevation steps (terraced). Built for storage-change hydrology, not relief.
  - **GLDB / Kourzeneva v2** — **rejected as a foundation, retained as a possible supplement.** Probing the
    actual raster: **36 lakes carry real digitized bathymetry** (Great Lakes via ETOPO1, plus Ladoga,
    Victoria, Great Bear, Great Slave, Winnipeg, Balkhash, Sevan, Onego…, from ILEC surveys and Russian navy
    charts); everything else is a flat slab at mean depth (Baikal = a single 744 m value). Decisively, the
    gridded file is **freshwater-only — the Caspian is absent entirely.** 30″ (~1 km ≈ 3× our z8 px, adequate),
    10.2 MB gzipped / 2.8 GB unpacked, HTTP-only host; **GLDBv3 is unobtainable** (host 404s, only v2 served).
  - **Decision: decouple.** Caspian now via GEBCO (measured data beats GLOBathy's cone *for that lake*, and
    GLDB doesn't have it); GLOBathy logged as the decided answer to the general lake-depth question, to be
    done as its own pass (needs a lake ramp + planet-wide re-fuse and re-tile).
- **Process note (cost a real OOM):** the first preview re-render (4 cells, 70 M px) was killed entering
  `composite()` — it materialises a stack of full-size float32 arrays at once, and the box was already at
  0 GB free with swap full. It took the terminal *and* the astro dev server with it. Re-ran 2 cells under
  `systemd-run --user --scope -p MemoryMax=8G -p MemorySwapMax=0` → clean. **Any region render must be
  cgroup-capped**, per CLAUDE.md's one-heavy-job-at-a-time rule. Separately: `shade.py`'s region path
  re-runs reprojection, colour-relief and hillshade *unconditionally* (no skip-if-present, unlike
  `shade_planet.py`), so a crash in `composite()` discards ~2 min of prep already on disk — at odds with the
  "idempotent and resumable" convention and worth fixing if we iterate on palette values much.

### 2026-07-15 (later) — Frontend hardening: astro-check + TS, `.ts` config + `.env`, Tier-1 gazetteer, Spin option A

All on `feat/frontend` (uncommitted at time of writing — Rohan's to commit).

- **`astro check` wired up; 106 strict-mode errors cleared → 0/0/0.** Added `@astrojs/check`; **pinned
  `typescript` to 6.x** — TS 7's native (Go) compiler dropped the programmatic API `astro check` relies on,
  so it errors at startup; 6.x is the newest that works. (This *overrides* "use latest verified versions":
  7 is latest but not *compatible* — don't bump it until `@astrojs/check` supports the native compiler.)
  Load-bearing gotcha found: **JSDoc `@type` casts are silently ignored inside Astro `<script>` blocks**
  (they're TS, not JS) → several `getElementById`/`querySelector` refs stayed `Element|null` and failed
  strict; converted to real `as` casts. Maplibre paint/filter consts typed with
  `ExpressionSpecification`/`FilterSpecification` as **annotations** (contextual typing validates the array
  literals), not `as` assertions.
- **`astro.config.mjs` → `astro.config.ts`.** Dev-only asset-store paths (`HERO/TILES/BORDERS_STORE`) moved
  out of committed source into a **gitignored `.env`** (+ committed `.env.example`), read via Vite
  `loadEnv` (needed because `.env` isn't in `process.env` at config-load). **No fallback** — the on-disk
  layout will change when this worktree folds into the main repo, so a sibling-path guess would silently
  resolve wrong; an unset var fails loudly instead. **Validation is per-request inside the middleware, NOT
  at `configureServer`:** Astro's *build* creates a Vite server that runs `configureServer`, so validating
  there breaks `astro build`; the asset routes are never *requested* during build, so a per-request check
  keeps build green and 500s the dev route clearly when a var is unset (proven live by cycling the dev
  server without `.env`).
- **Spin option A shipped.** Above `SPIN_MAX_ZOOM` (z3) the Spin toggle is now **disabled + greyed with a
  "Zoom out to spin" tooltip**, re-enabled on zoom-out (`zoomend` → `syncSpinAvailability`) — fixes the
  dead-toggle confusion (checking it there was a silent no-op). Auto-resume still deferred (see entry below).
- **Tier-1 no-JS fallback = the gazetteer.** The gallery already SSGs all 203 cards, so browsing needs no
  JS; the only gaps were the dead search box + no find-by-name. Removed the search entirely; added an atlas
  **gazetteer** — every country a link with its **bbox-centroid coordinates** (mono), grouped under Fraunces
  letter-markers, with an A–Z rail. Rohan rejected a bottom-of-page placement (buried on mobile), so it
  **opens as a full-screen overlay** from the header "Index" link, done in **pure CSS**: `.gazetteer:target`
  opens it, `.gazetteer:has(:target)` keeps it open through letter-jumps (kept as *separate* rulesets so a
  browser without `:has()` still honours `:target` and can open it) — zero JS, and Cmd/Ctrl+F searches it
  once open. Plus a `no-js`→`js` `<html>` class flip (inline pre-paint) so `.fab-stack` (border/quality
  toggles) hides when JS is off — no dead controls. Grid untouched. Design chosen via the frontend-design
  skill: the atlas *gazetteer* is the subject-true find tool; coordinates are the signature detail.

### 2026-07-15 — Frontend: capability probe, tier routing, quality + spin toggles, mobile polish (all committed on `feat/frontend`)

Shipped the three-tier selection end-to-end and polished the globe on mobile. Commits: `a595ef9`
(capability probe + auto-steer), `c7eda66` (spin toggle + the fixes below).

- **Capability probe** (`src/lib/capability.ts`): pure `decideTier(signals, quality)` (WebGL2 hard
  floor; software-GPU via `WEBGL_debug_renderer_info`; Save-Data / slow-net / low-mem / reduced-motion),
  TDD, 15 vitest cases. A pre-paint inline `<head>` guard in `Base.astro` steers capable visitors
  `/` → `/globe/` (bounces incapable/Lite deep-links back), no flash. Quality toggle persists `rg:quality`.
- **Mobile fixes:** control-collision → single bottom-right `.fab-stack` (order Spin, Borders,
  Lite/Globe/Full — quality at the bottom per Rohan). Borders de-jagged: the geojson source `tolerance`
  was **1.2** (3× default) → back to **0.375** + `buffer: 256` (the staircase + intermittent breaks).
  Attribution compact-collapses to the ⓘ on small screens and is **re-parented to `<body>`** so, when
  expanded, it floats above the controls — it's otherwise trapped under `.fab-stack` inside `#globe`'s
  `position:fixed; z-index:1` stacking context (no element z-index can escape that).
- **Spin (current, committed):** idle rotation at ≤ z3; **any interaction retires it** (Spin checkbox
  unticks) and the **Spin toggle restarts it**. `map.stop()` on pointer-down kills the in-flight easeTo
  so a pan starting mid-spin can't fight it / misfire as a country click. Suppressed above z3 because the
  fixed 2°/s sweep whips the surface past too fast to follow.
- **FAILED experiment — resume-on-zoom-out (do NOT re-attempt naively).** Tried making Spin a persistent
  auto-rotate *mode* (a `userInteracting` flag; resume by calling `spin()`/easeTo from `mouseup` /
  `zoomend` / `moveend`; `zoomstart`/`zoomend` handlers to pause). It **broke MapLibre's render loop** —
  re-entrant `easeTo`/`map.stop` from the map's own animation events →
  `TypeError: this._onEaseFrame is not a function` and `Error: Attempting to run(), but is already
  running`; the zoom handlers chopped scroll-zoom into janky micro-steps fighting the spin; and pan died
  after zooming in. Reverted. **Lesson:** never call `easeTo`/`map.stop` re-entrantly from MapLibre's
  `mouseup`/`zoomend`/`moveend` during an animation. Resume-on-zoom-out is still wanted but **deferred** —
  if revisited, use MapLibre's official spin-globe pattern (no `map.stop`, no custom zoom handlers) and
  test the full zoom + pan + click matrix in a real browser *before* declaring it done.

### 2026-07-14 (night) — Sea rework (#3): levers 1+2 prototyped, **V1 chosen** (lock + winner z0-8 pending)

The sea read as a flat, tacked-on backdrop with no depth. Diagnosis (from the code): `shade.py`
shaded the seafloor at only `sea_shade=0.26` off a land-exaggerated hillshade (near-flat on gentle
bathymetry), forced ocean SVF to 1.0 (no ambient occlusion), and `palette.py` `SEA_MIN_M=-3000`
clamped all deep ocean to one slab while the ramp squeezed shelves into ~7% of its range.

**Levers applied (PROTOTYPE — uncommitted, not yet locked):**
- `palette.py`: `SEA_STOPS` redistributed so the two brightest bands sit in the top 800 m (shelves
  read as a gradient); `SEA_MIN_M` -3000 → **-6000** (deep ocean varies, e.g. Gulf of Aden);
  surface + shelf stops **deepened ~15%** (pull the bright cyan toward a richer teal — Rohan's ask).
- `shade.py`: new `sea_svf` knob (ocean gets a fraction of the land occlusion); un-compressed
  `sea_shade`. Caveat: the SVF input zeroes bathy below -500 m, so deep-basin AO is limited — shelves
  and shelf-edges carry it; deep gets depth from ramp+hillshade. (Lever 3 = a sea-specific
  high-exaggeration hillshade — deferred; would sculpt the abyss but wasn't needed for 1+2.)

**Candidates (sea knobs; shared palette/tone):** V1 `{sea_shade 0.55, sea_lift 1.00, sea_svf 0.5}`
(calmer, water-like sheen), V2 `{0.72, 0.98, 0.7}` (stronger relief). Prototyped on the Red Sea via
`shade.py --cells` (fast, no planet re-shade). **Rohan chose V1** — pending his final go to lock.

**A/B infra (all verified live on the globe):** `pipeline/experiments/sea_ab.py` **[deleted
2026-07-16 — fully dead: its subject locked at V1, its winner's knobs baked into `shade.py`'s
KNOBS, and both stages it drove (`color_and_hillshade`, `sea_3857.tif`) removed with the
color-relief deletion. The dual-variant machinery it exercised SURVIVES as
`composite_planet(variants=..., max_windows=...)` for the next A/B]** drove a
dual-output planet composite (both variants in one pass) → non-destructive `tiles_v1`/`tiles_v2`
(z0-7; z8 deferred to the winner), live tiles untouched. Frontend: `globe.astro` Current/V1/V2
segmented toggle + two hidden raster sources; `astro.config.mjs` serves `/tiles-v1` `/tiles-v2`.
Both sets built (15,585 tiles each).

**Profiling (measured, `composite_bench.py`):** the hotspot is the **composite numpy math**
(~2 s/window, run once per variant), then the per-window snow-warp + glacier-rasterize gdal
subprocesses (~2 s combined). Optimizations tested: **#1** share-across-variants — pixel-identical
but only ~4% faster, **dropped**; **#3** bigger windows — **dropped** (caused an OOM, below);
**#2 precompute global snow_alpha + glacier rasters once** (warp+rasterize to two 3857 rasters,
~24 GB disk, composite reads slices) — **saves ~2.9 s/window; BUILD THIS for the winner z0-8 pass.**

**OOM incident (20:40):** ran `composite_bench` concurrently with the v2 tiling; the benchmark held
all 5 windows + composited a 768-row window (~19 GB RSS) and the box (29 GB RAM, 8 GB swap already
**full**) OOM-killed it, interrupting the v2 tile cut (since resumed). **Operating rule: one heavy
pipeline job at a time — no second pass or benchmark alongside it.** (`composite_bench` has this
memory bug: holds all windows + a 768-row composite — bound it before any re-run.)

**NOT DONE / next (blocked on Rohan's go to lock V1):**
1. Bake V1 knobs into `shade.py` KNOBS defaults (currently the OLD `sea_shade=0.26, sea_lift=1.08,
   sea_svf=0.0`); `palette.py` already holds the new ramp/tone as prototype.
2. Update `tests/test_palette.py` + the CLAUDE.md locked sea constants (still the OLD `8FC7C5`/
   `3A6E7D` at 0/-3000 — the frozen set Rohan OK'd moving; the test will fail until updated).
3. Run the winner's full **z0-8** into the live tiles, built with the **#2 precompute** optimization,
   run **solo**. Then a globe re-check + commit.

Uncommitted prototype state: `palette.py`, `shade.py`, `shade_planet.py`, `sea_ab.py`,
`composite_bench.py` (main worktree); `globe.astro`, `astro.config.mjs` (frontend worktree).

### 2026-07-14 (evening) — #4 "highest point" stat attempted then dropped; Google Earth datasets assessed

**Highest-point stat — dropped.** Tried computing a per-country highest point from our fused
heightfields (`data/work/<slug>/heightfield_{1s,3s}.tif`, EPSG:4326 float32 m) by masking with the
NE country polygon (zonal max). Prototyped thoroughly; dropped for two reasons:
- **Accuracy wart from generalised NE borders.** NE 10m borders assign border-straddling summits to
  one side, so the masked max misattributes marquee peaks. Worst case **Nepal → ~8,140 m, not Everest
  8,849** (NE draws the border south of the summit; the 8,731 m pixel lands on the China side, and even
  ~600 m of mask dilation only reached 8,371). Most countries were within ~2 % (France nailed Mont
  Blanc 4,804; India 8,535≈Kangchenjunga; Netherlands 325≈Vaalserberg) — but a visibly-wrong Nepal on
  a relief site isn't worth shipping. This is inherent to our committed NE-default worldview, not a bug.
- **Compute cost for giants.** An accurate masked max must scan all interior pixels; native block-stream
  of Russia's 3s field (10 G cells) exceeded 2 min *per country* (~15 giants → 30 min+). The coarse
  global `planet_heightfield.vrt` (10 arc-sec) is fast (Russia 18 s) but its coarse mask **leaks foreign
  terrain into small countries** (Netherlands → 819 m, grabbing German uplands). A size-gated hybrid
  (native for small, decimated for giants) would work but wasn't worth the complexity for a card stat.

Verdict: the panel keeps its current copy; no computed elevation. Revisit only if we want a curated
highest-point table (hand-authored, off our data) — deliberately not doing that now.

**Google Earth datasets vs ours (from its Data-attribution panel).** Its list — *SIO/NOAA/US Navy/NGA/
GEBCO, Landsat/Copernicus, IBCAO, USGS, PGC/NASA* — maps to: ocean floor = SRTM15+ (Scripps) blended
with GEBCO, i.e. **the same ~15″ (~450 m) altimetry-predicted bathymetry class we use** (so Google's
oceans are smooth for the same reason — confirms the **#3** finding that our blurry/flat deep sea is a
data limit, fix is aesthetic not data); Landsat/Copernicus = optical *imagery* (Sentinel-2, a different
product from the Copernicus **DEM** GLO-30 we use — not our medium); IBCAO = Arctic bathymetry already
inside GEBCO; USGS = SRTM-class land (older/inferior to our TanDEM-X-derived GLO-30 globally).
**The one genuinely-better source is PGC/NASA = REMA (Antarctica) + ArcticDEM (Greenland/Arctic), 2 m
native** — relevant only to our deferred polar work (both currently flat-capped). Filed for the
Antarctica/Greenland pass; no change to land (GLO-30) or bathymetry (GEBCO) choices.

### 2026-07-14 (evening) — Starfield space backdrop shipped (`feat/frontend`)

Built #5. The globe now sits in dark space with a sparse, static starfield instead of the flat teal
fill. Approach: a full-viewport `<canvas id="starfield">` painted **behind** a now-transparent map
(dropped the solid-teal `space` background layer, so MapLibre's canvas is transparent in space and
the stars read through around the sphere). Ground is `#0e1519` (very dark desaturated navy, not pure
black — stays in the Neutral palette); ~1 pale star per 5200 CSS px², radius 0.4–1.3 px, opacity
0.16–0.66. **Static — no twinkle**, so it's inherently calm and reduced-motion-safe; repainted only
on resize (DPR-backed for crisp hi-DPI stars). No "when zoomed out" logic needed — the sphere covers
the field when zoomed in.

The one risk flagged when scoping — that dropping the teal background (which also "blends any gap at
the capped poles into the disc") would expose stars through the un-tiled sliver above +85°/below −60°
— proved a **non-issue**: the flat polar caps baked into the tiles plus the atmosphere fully cover
the top, verified by zooming the north pole (Greenland's white cap, no stars poking through). The
soft blue `setSky` atmosphere, kept unchanged, reads as a gentle earth-glow against the dark space
(the earlier worry it would wash to light grey was unfounded).

### 2026-07-14 (evening) — Globe experience polish: remaining items scoped (from using the globe)

Five notes from living with the globe. #1 (in-place render zoom) is BUILT — see the next entry.
The rest are scoped-not-built; capturing so they survive compaction:

- **#5 Starfield (NEXT UP):** a space backdrop when zoomed out. MapLibre `setSky` has **no star
  support** (Mapbox-only) → DIY: replace the solid teal `space` background layer with a transparent
  space + a sparse, faint starfield on a **very dark desaturated navy** (not pure black — stay in the
  Neutral palette), **no twinkle** (or honour `prefers-reduced-motion`). Needs no "when zoomed out"
  logic: space is only visible when the globe is small, so stars appear only zoomed out.
- **#4 Richer hero panel:** add **elevation range / highest point** — computable from our own fused
  heightfield in `gen_manifest.py` (sample per-country min/max), reinforces the relief theme; and/or
  the hypsometric `Legend` scaled to the country. **Push back on population/area/capital** (off-brand
  almanac data).
- **#3 Bathymetry reads blurry + flat** — **not a Tier-3 issue** (Tier 3 = 3D displacement). Two
  separate causes: (a) *blurry* is a hard data limit — GEBCO ~450 m (15″) vs GLO-30 30 m land, ~15×
  coarser → upsampled = smooth; unfixable globally. (b) *flat* is **our own tunable choice** —
  `palette.py` `SEA_MIN_M = -3000` clamps every depth past 3 km to one deepest colour (most open
  ocean → featureless slab), and the sea hillshade is faint on GEBCO's gentle gradients at the current
  z. Fix direction: extend/band the depth ramp (hypsometric sea tint = the "shelf seas" signature) +
  a stronger sea-specific hillshade — a `palette.py` + `shade_planet.py` tune; **prototype on Red Sea /
  Mediterranean** (good shelf structure) before any planet re-shade. Lives under the Phase-2 "on-globe
  tile judgment" item.
- **#2 Mumbai-in-viewport (answered, no work):** pyramid ceiling is z8 ≈ 290 m/px at 19°N → a laptop
  viewport frames ~250 km (Mumbai ~70 px). Filling the screen with the city needs ~z11 (~30 m, GLO-30
  native) = the deferred finer re-fuse (the z10+ open question), not available today.

Sequence: #1 done → **#5 starfield next** → #3 as its own focused session; #4 opportunistic.

### 2026-07-14 (evening) — Detail-page hero: in-place pan/zoom (`feat/frontend`)

The full-size render (`/[slug]/`) now zooms in-place: wheel / double-click / pinch to zoom,
drag or arrow-keys to pan, a Reset control, edge-clamped so no gutters. The **native full-res
variant is lazy-loaded the first time you zoom** so the page still loads on the light display
variant. Vanilla pointer-events, no library; descriptive names throughout.

**Perf rewrite (do not regress to CSS transform).** First cut CSS-`transform: scale()`-ed a
`<img>` of the 7680 px hero: catastrophically janky — wheel sluggish, the Reset *click* delayed
5–10 s and worse the more you'd zoomed. Cause: transform-scaling the bitmap forces the browser to
re-rasterise the whole scaled image each frame, and once scaled dims pass the ~8192 px GPU max
texture size it falls back to CPU-tiled raster; those multi-hundred-ms tasks starve the input queue.
Fix: render into a viewport-sized box and sample the source via **`background-size` +
`background-position`** (`.zoom-hero`/`.zoom-border` divs) — the painted element stays frame-sized
(verified 1420×1338 even at scale), so every frame is one small raster, never a giant re-raster.
No `will-change`, no rAF batching (background-* are paint-only → the browser already coalesces to one
paint/frame; rAF also went dead in backgrounded tabs, which broke local verification).

Follow-up fixes (same session): (1) **Reset needed a few tries** — the figure's `pointerdown` did
`setPointerCapture`, which retargets the pointerup and swallows the Reset button's `click`; guard with
`resetButton.contains(event.target) → return`. (2) **Black flash on first zoom** — swapping
`background-image` to the not-yet-loaded native URL showed the dark figure background through the gap;
now preload + `img.decode()` and only swap on `.finally()`, so the display variant holds until native
is ready. (3) **Globe → hero navigation spammed `AJAXError: NetworkError`** — MapLibre tiles in flight
abort on navigation; added a `map.on("error")` gate that silences AJAX/Network errors once a `pagehide`
flag is set, but still surfaces genuine errors during use.

### 2026-07-14 (evening) — Click-to-fly-to → in-globe hero panel (BUILT, `feat/frontend`)

Globe interaction: click a country → `fitBounds` to it → show its hero in a floating panel.
Built exactly on the design below; Rohan's two calls were **in-globe overlay panel** (not detail-page
nav) and **one pass**. Pieces: `pipeline/compose/countries_geojson.py` (new; NE country polygons
simplified at 0.05° → `data/work/borders/countries.geojson`, 1.5 MB, served via the existing
`/borders` middleware), `bbox=list(r["frame"])` added to `gen_manifest.py`, and the interaction +
floating `.hero-panel` in `globe.astro`. The panel reuses the hero `srcset`/`variantWidth` math and
the shared `body.borders-on` toggle from the detail page.

Latent bug fixed in passing: `gen_manifest.py`'s import was stale (`sys.path` at `pipeline/` +
`from country_config import …`) since `country_config` moved to `pipeline/frame/` and switched to
absolute `pipeline.*` imports — now inserts the repo **root** and imports `pipeline.frame.country_config`.

Verified live (Chrome): the invisible `fill-opacity:0` layer is queryable (click hit "Chad",
`promoteId:'ADMIN'` gives feature id = ADMIN), panel populates (eyebrow/name/`/slug/` link/hero),
border overlay follows the toggle, and the `padding.right:460` frames the country **clear of the
panel**. Note: the `fitBounds` *animation* couldn't be observed in the harness (the automation tab is
`visibilityState:hidden` → `requestAnimationFrame` is paused, so all easing/tile-fade/`load`/`idle`
stall; screenshots still force a one-off paint). Destination framing validated via a synchronous
`jumpTo(cameraForBounds(...))`; the animation is stock MapLibre and runs when the tab is visible.

UX refinement (same session, on Rohan's feedback): (1) the flat white hover *tint* didn't delineate
the boundary, so hover now draws a **gold silhouette wash + gold outline over a soft dark casing**
(`country-hl-casing`/`country-hl-line`, added above the borders). Gold is the one hue that pops on all
three grounds — the teal accent would vanish along coasts against the teal sea — and it reads as an
interactive pick, distinct from the white informational borders. (2) The panel's "View full render"
was opaque about what it offered, so it now carries a descriptor ("A ray-traced relief render — softer
shadows and heightened terrain than the globe's live tiles") and the link reads "Open full-size render
→". Fixed in passing: a shared `.hp-figure img { display:block }` outranked `.hp-border`'s
`display:none`, forcing the panel's border overlay **on regardless of the toggle** — scoped the
`display:block` to `.hp-hero` (the detail page dodges this by not putting `display` on the shared rule).

Original design (discovered from `country_config.resolve()`, `gen_manifest.py`, and the NE countries
shapefile), for reference:

- **Hit detection:** the globe is raster, so add NE `ne_10m_admin_0_countries` polygons (258,
  EPSG:4326, attrs `ADMIN`/`ISO_A3`) as an *invisible fill* layer; `map.on('click','country-fill')`
  + `queryRenderedFeatures` returns the clicked country. Shapefile is 8.8 MB → **simplify hard**
  (`ogr2ogr -simplify`) to a few hundred KB (only needed for hit-testing + a hover tint, not
  coastline detail). New generator `pipeline/compose/countries_geojson.py` (mirror
  `borders_geojson.py`), served via the `/borders`-style middleware.
- **The join is FREE:** `countries.json.name` IS the NE `ADMIN` string (`gen_manifest` sets
  `name = resolve()["admin"]`). So clicked `feature.properties.ADMIN` → our record by
  `name === ADMIN`; no ISO matching. NE 258 polygons vs our ~204 scope → gate hover/pointer/click
  to matched names; unmatched (Antarctica, micro-territories, excludes) are no-ops.
- **Fly-to bbox = the authored hero frame:** `resolve()["frame"]` = (w,s,e,n) 4326 — same framing
  as the heroes, and it already fixes the awkward multipolygon cases (France's *raw* bbox spans to
  French Guiana; the override frame uses metropolitan France; same for US/Chile/Russia). Surface
  via ONE line in `gen_manifest.py` (`bbox=list(r["frame"])`), regenerate countries.json, then
  `fitBounds(bbox)` or `cameraForBounds→flyTo` (curved). **VERIFY on build:** MapLibre accepts the
  flat `[w,s,e,n]` bounds form, and `fitBounds` frames sanely under *globe* projection for big/
  high-lat countries (Russia/Canada).
- **Hover polish:** pointer + faint fill tint via `feature-state` + `promoteId:'ADMIN'`; a click
  stops the idle spin; Esc/close returns to the globe.
- **RESOLVED:** hero display → in-globe overlay panel (lazy `<img srcset>` from `/heroes/` + close/Esc,
  a "View full render →" link to `/[slug]/`); built in one pass. The "rendering…" placeholder path is
  moot — all 203 in-scope countries are rendered, and the fill layer is filtered to those names, so an
  unrendered country is simply not clickable.

### 2026-07-14 (evening) — Tier 2 globe + Natural Earth vector borders (frontend, `feat/frontend`)

First interactive globe. Standalone `/globe` route (deliberately independent of the not-yet-built
capability probe, so Tier 2 can be judged in isolation; the probe will later route `/` here with the
gallery as fallback).

- **Library:** MapLibre GL **5.24.0** (current stable; v6 is prerelease). Verified via research that
  v6 (ESM-only, WebGL1-drop, raster mipmaps) and WebGPU are *below-the-API* changes — nothing we'd
  author differently today; authored v6-safe anyway (ESM `import`, public API only, no `map.transform`,
  modern array expressions). WebGPU in GL JS is Phase 4 of a 5-phase plan (mid-Phase-1 in mid-2026),
  realistically 2027+, and lands as an opt-in over a WebGL2 default — a future no-op tier, not a rewrite.
- **Config lifted from the proven `planet_tiles/index.html` viewer:** raster source
  `/tiles/{z}/{x}/{y}.png`, `tileSize:256` (512px assets @2x for crisp DPI), globe projection declared
  in the style (v5 stable), soft sky, `maxZoom:8` (data ceiling; never reaches the z12 globe→mercator
  auto-switch). Baked polar caps show as clean discs on the sphere — no starburst.
- **Framework-free integration:** the Astro site has no UI framework, so MapLibre lives in a plain
  Astro-bundled `<script>` (code-split — absent from the gallery bundle). Dev serving mirrors the
  existing `heroDevServer()`: added `/tiles` + `/borders` Vite middlewares in `astro.config.mjs`
  (same-origin → no CORS; nginx serves the same paths in prod; PMTiles is a Phase-4 packaging swap).
- **Controls:** Navigation + Globe (globe⇄flat toggle) + Scale + Attribution (bottom-left, clear of
  the border toggle). **Idle spin** refactored onto the map's own gesture events
  (`dragstart`/`zoomstart`/…) rather than ad-hoc DOM listeners — pauses cleanly, never fights its own
  `easeTo`, and is skipped entirely under `prefers-reduced-motion`.
- **Vector borders (land-only v1):** the hero border PNGs are baked into each country's Albers camera
  and cannot drape on a sphere, so the globe needs live vector geometry (CLAUDE.md already mandates a
  vector overlay, never baked). `pipeline/compose/borders_geojson.py` = one `ogr2ogr` call translating
  NE `ne_10m_admin_0_boundary_lines_land` (already EPSG:4326 → format change, not reprojection) →
  `data/work/borders/boundary_lines.geojson` (505 lines, FEATURECLA carried, 3 non-rendered classes
  dropped, ~1 m precision, 2.0 MB, gitignored). One MapLibre `geojson` source (`maxzoom:8`, `tolerance`
  for low-zoom thinning, NE attribution) → four `line` layers: dark casing under white ink, each split
  solid-international vs dashed-disputed/LoC by a **layer `filter` on FEATURECLA** (not a source filter,
  not `promoteId`). Toggled by layer `visibility` off the shared `rg:borders` key (one control across
  gallery/detail/globe). **Maritime indicator lines: added then dropped (2026-07-14)** —
  NE's maritime "indicator" data is open `LineString` segments (median/treaty/200 nm limits)
  that *divide* seas rather than enclose territory, so on a relief-first globe they read as
  disconnected offshore noise, not boundaries; land borders already carry country identity.
  Generator (`borders_geojson.py`) and frontend reverted to land-only. (EEZ *polygon* zones
  would be a different, larger, more political dataset if maritime territory is ever wanted.)
- **Border legibility fix (same day):** the white line vanished over pale highlands + snow
  (Tibet/Himalaya) — a single-colour line can't self-contrast against both light and dark ground, and
  the casing (`#3d2b1f` @ 0.5, thin) was decorative. Fix (Option A + blur): strengthened the casing
  into a real dark halo — darker/near-neutral colour, higher opacity, wider rim, slight `line-blur` to
  match the soft raytraced aesthetic. Rejected terrain-adaptive line colour (MapLibre can't condition
  line colour on the raster beneath it; cased line is the correct tool).

### 2026-07-14 (day) — Tile-shading rework: readable snow, exposure, seamless per-latitude relief, pole caps, float32/window RAM fix

Fixes to the overnight globe, driven by on-8765 review. **Three distinct defects, three causes** (do not conflate):

- **Himalaya grey smear vs white Greenland** — a *rendering* issue, not data. Snow is a soft alpha
  over the hillshade; the neutral `SNOW_RGB × light` floored shaded snow on rugged terrain to grey,
  while flat Greenland (persistence≈1) stayed white. Fix: two-colour snow ramp —
  `palette.SNOW_SHADOW_RGB` (blue-white) → `SNOW_RGB`, keyed by light. Verified Karakoram/Alps/Greenland.
- **Sri Lanka "washed out / too bright"** — a *land-exposure* blow-out, unrelated to snow. Pale-sand
  lowland (233,217,192) × `exposure=1.30`'s 1.15× flat-lit gain clipped to white (30% of land ≥235).
  Fix: `exposure` 1.30 → **1.05** (flat land ≈ true colour; mountains keep punch — `ambient`/`hi`
  unchanged). Knobs were Nepal-tuned, so flat bright lowland was never seen. Verified Sri Lanka + Alps.
- **North-pole starburst** — MapLibre's globe smears the non-uniform ±85.05° edge row into the pole.
  Fix: flat deep-sea pole caps (>84°N, <−59.5°S). Same for the −60°S (Antarctica-deferred) edge.
- **Seams + wrong exaggeration** (the "refinements") — retired per-strip `tile_planet.py` (single
  global z=20 blew out tropics; per-strip `--compute_edges` seamed ocean) for **one global streaming
  pass** `pipeline/tile/shade_planet.py`: warp→3857 once, global color-relief, a **custom per-row-z
  hillshade** `render/hillshade.py` (z=15/cos(lat), full-width + 1-row halo → seamless + correct 15×
  everywhere; matches gdaldem ≤1 DN), globally-normalised SVF (back on), per-window composite.
- **OOM fix** — the full-width float64 composite at 384 rows peaked ~18 GB (numpy temporaries stack
  on persistent arrays; memory *creeps* over windows) and was OOM-killed under browser load. Fix:
  `composite()` in **float32** (output-identical, ≤1 DN), `WINDOW_ROWS=256`, per-window `del`+`gc`,
  launch `GDAL_CACHEMAX=512` → ~2.6 GB RSS in practice.
- **Docs** — split the 726-line decision log into HISTORY.md; PLAN.md 870→~185 lines + a new "Active
  learnings" section; CLAUDE.md +4 gotchas (Earthdata/RGI access, GLO-30 withheld tiles, OptiX crash,
  8K-CPU-denoise reconcile); new INVENTORY.md (storage map).

**Status:** all crop-verified; the full-planet z0–8 rebuild is running on the float32 path (~2.6 GB,
past the prior OOM point). **On-globe 8765 verification is the last open step.** Relaunch (skips cached
head stages, resumes at composite): `GDAL_CACHEMAX=512 python -m pipeline.tile.shade_planet --out
data/work/planet_tiles --tiles`. When checking if it's running, filter on `comm==python` — a bare
`pgrep -f shade_planet` self-matches the launch shell and false-aborts. After tiling it swaps
`tiles_new`→`tiles` (old kept as `tiles_old`); verify via `cd data/work/planet_tiles && python3 -m
http.server 8765`.

### 2026-07-14 (overnight) — First full planet tile pyramid: snow + glaciers, z0–8, served & verified

**`pipeline/tile/tile_planet.py`** shades the non-Antarctic planet as **194 RAM-safe horizontal
cell-strips** (grouped under an 80 Mpx budget — 6-cell strips at the equator down to 1-cell at high
latitudes where Mercator stretches), each via `shade.py` with a **single global z-factor** (20.0 ≈ lat 41;
`--zfactor` added to shade.py) so the hillshade is seamless across strips, and **SVF off**
(`--knob svf_strength=0` — per-block SVF min/max normalisation would seam). Strips are `-tap` pixel-aligned,
so the VRT mosaic is seamless. Resumable + fault-tolerant (**0/194 failed**); a cross-strip seam test
(Alps + central-Europe strips) confirmed the join is invisible.

**Mosaic → tiles.** VRT mosaic 131072×93009 RGBA (alpha for the Antarctica/pole gaps), 8.2 GB of strips.
Materialised to a tiled GTiff + overviews first (tiling the 194-source VRT directly re-reads every block
per low-zoom tile — far too slow), then `gdal raster tile --tile-size 512 --skip-blank` → **z0–8, 62,177
tiles, 13 GB** at `data/work/planet_tiles/tiles/{z}/{x}/{y}.png`. Globe page: `data/work/planet_tiles/index.html`
(MapLibre v5 globe, 512px@2x). **Serve:** `cd data/work/planet_tiles && python3 -m http.server 8765`.
**Verified** on 8765 (whole-planet mosaic + Alps z5 tile): seamless across strips, global persistence+ramp
snow, RGI glaciers crisp (Greenland/Arctic/Himalaya/Andes/Alps), full bathymetry.

> **`tile_planet.py` DELETED 2026-07-16.** Recover with
> `git show a7b7223:pipeline/tile/tile_planet.py` — a7b7223 is an ancestor of main, so the copy is
> permanent and byte-identical to what was removed. This entry is now the record; the file was not.
>
> **Why it went, beyond being superseded** — the reasons are the transferable part:
> - **A retired path kept in production aims at production.** Both scripts defaulted `--out` to
>   `data/work/planet_tiles`, so `tile_planet --tiles` would re-shade 194 strips for hours, then hit
>   `if not planet_tif.exists()` — silently **skipping its own mosaic** because the *good* verified
>   `planet_rgb.tif` was sitting there — and cut tiles **straight into the live `tiles/`** with
>   `--resume`, which *skips existing tiles*. Result: a hybrid of new and pre-Caspian tiles with **no
>   `tiles_old` rollback**. It predates every safety mechanism that replaced it (`.done`, `is_stale`,
>   stage-into-`tiles_new`-then-swap). It still parsed, and `shade.py` still exposed the `--zfactor` and
>   `svf_strength=0` it shelled out to — so it **ran**. Dead code that still runs and still points at the
>   live outputs is not clutter; it is a loaded gun.
> - **It had stopped being a faithful record — the thing it was being kept for.** It shelled out to
>   `shade.py`, which moved underneath it: LUT ramps replaced color-relief, lake depth arrived,
>   `WATER_RGB` changed, float32 replaced float64. Running it would reproduce **neither** the strip
>   output documented above **nor** the current look — only a chimera of today's palette with the
>   retired z=20/no-SVF geometry. Its own line 32 already admitted the drift ("safe for the float64
>   composite"). The experiments audit's bar for keeping things is that *a **working** experiment is the
>   record of a decision*; a script whose dependencies have drifted under it cannot reproduce what it
>   records, so it fails that bar even though it is not "broken".
> - **Retirement hygiene, stated generally:** when a path is superseded, *delete it or move it out of
>   the production package the same day*. Prose calling it "retired" (PLAN, INVENTORY, and
>   `shade_planet.py`'s own docstring all did) does not disarm an entry point. git is the archive.

**First-pass caveats — refinements, not blockers:**
1. Faint **vertical lines in deep ocean** = lon-adjacent strip boundaries; `gdaldem hillshade --compute_edges`
   extrapolates each strip's shared edge ~1px differently. Fix: shade strips with a small overlap and crop,
   or one global hillshade (windowed composite).
2. **Single global z-factor** over-exaggerates the tropics and flattens high latitudes vs the hero's
   per-latitude 15×. Fix: per-row/banded z-factor (a custom hillshade) — the real seamless-per-latitude answer.
3. **SVF off** → valley shadows subtler than the heroes. Fix: compute SVF globally, slice per strip.
4. Antarctica deferred; Greenland interior renders flat white (persistence=1 over smooth ice).

**Not yet:** PMTiles packaging (Phase 4); the three seamless refinements above; tuning against the on-globe look.

### 2026-07-14 — Snow integrated into shade.py; RGI 7.0 glacier union added and verified

**shade.py integration.** SP + latitude ramp are now production: new `pipeline/render/snow.py`
(`warp_persistence` → `snow_alpha` with the per-row latitude ramp), `shade.py`'s WorldCover class-70
branch removed, `composite()` soft-blends shaded `SNOW_RGB` over land by the alpha. pyright-clean;
full-res Alps in 16 s reproduces the prototype.

**RGI glacier union.** RGI 7.0 (NSIDC-0770 v7) has **no CMR granules** and its NSIDC data pool needs
interactive-OAuth (a token-only earthaccess session is bounced to the login page *even after authorizing
`nsidc-daacdata`*), so we fetch from **UNESCO's open IHP-WINS re-host** (`pipeline/acquire/download_rgi.py`:
CKAN `package_search` → 18 GTN-G region shapefiles, region 19 Antarctic skipped, merged/reprojected to
`data/raw/rgi/rgi7_g_3857.gpkg`, **271,789 glaciers**). `snow.rasterize_glaciers` burns them onto the
Mercator grid; `shade.py` unions `alpha = max(persistence_alpha, glacier)` → crisp permanent ice over the
soft persistence snow. Graceful when RGI is absent (returns None → persistence-only). **Verified:** Alps
(47 k glacier px, sharper massif cores) and Iceland (829 k px — Vatnajökull/Langjökull/Hofsjökull/Mýrdalsjökull
render crisp and bright, distinct from the softer seasonal snow).

**Data-access learnings (July 2026).** A NASA Earthdata bearer token (`EARTHDATA_TOKEN`, gitignored `.env`,
~60-day) authenticates **CMR granule** downloads (NSIDC-0791 via `earthaccess`) but **not** the NSIDC file
pool's OAuth. RGI isn't granule-searchable at all; the open IHP-WINS CKAN mirror is the reliable programmatic
source. `earthaccess 0.18` added as a dep.

**Docs updated:** ATTRIBUTIONS (NSIDC-0791 public-domain + RGI 7.0 CC-BY 4.0, with attribution strings),
both pipeline `.mmd` diagrams (snow sources + the tile path, marked in-progress), `docs/pipeline.md`
(a Phase-2 tile-pipeline section).

**Still open for the tiles:** the seamless **full-planet shade** (single vs per-latitude z-factor across
blocks) and windowing; tiling → PMTiles. See the globe-build note below/next.

### 2026-07-13 (night) — Snow source reworked: NSIDC-0791 persistence + latitude-ramped soft alpha (replaces WorldCover class 70)

**Why.** The 5-region stress test (one global shade knob set) exposed that WorldCover class 70 is *permanent ice
only*, so mid/high-latitude ranges render bare. The heroes had the identical gap (Norway 0.37 %, Argentina 0.35 %
snow) — a deliberate "eternal snow" editorial stance (`snow_mask.py`), only glaring now that we render high-latitude
mountains as tiles; Nepal/South-Asia tile validation hid it (subtropics, where permanent ice ≈ the visible snowline).
Rohan's requirement: snow that "closely resembles reality," not an estimate. Snow is seasonal, so "reality" = an
observed *climatology*, not a snapshot or a modeled elevation×latitude snowline.

**Decision.** Snow = **NSIDC-0791** (MODIS/Terra Global Annual Snow-Cover Climatology, 0.01°, WY2001–2023), variable
`snow_persistence_climatology` (packed uint16 × 1e-4 → 0..1 fraction; 65535 = fill). Persistence → **soft alpha**
(smoothstep) so margins fade and snow still takes the hillshade (never flat white). A single global persistence
cutoff traded Alps (want ~0.40) against the boreal (Scandinavia floods at 0.40, right at 0.60) — the same
latitude-regime tension as the z-factor. Resolved with a **per-pixel latitude ramp**: low = 0.40 at |lat| ≤ 45° →
0.60 at |lat| ≥ 63° (linear), high = low + 0.32. One global rule, correct everywhere: Alps + Scandinavia both good
simultaneously, Sahara/Indonesia bare, Andes naturally patchy (arid). Prototype `pipeline/experiments/snow_proto.py`.

**Consequences / next.**
- Cured the stress test's "dark muddy high country" too (the darkest pixels were the highest terrain → now
  snow-capped; the remaining brown is correct mid-slope) — no separate palette rework for peaks.
- **RGI 7.0** glacier outlines to be unioned for crisp permanent ice (1 km persistence blurs glacier tongues), then
  fold SP + ramp (+ RGI) into production `pipeline/tile/shade.py`, replacing the class-70 branch.
- That integration makes `data/raw/worldcover` (114 GB) reclaimable — keep only a compact class-70 floor if RGI
  under-covers; the remaining tie is WBM void-fill for any re-fusion.
- Dataset vetting (July 2026, web-verified): NSIDC-0791 beat raw MOD10CM (pre-computed persistence, finer, gap-filled);
  HLS 30 m rejected (no product, petabyte-scale, over-resolved for z8); Copernicus global 1 km daily (new Feb-2026)
  held in reserve for the *seasonal* overlay path. RGI 7.0 = NSIDC-0770 v7, direct-download (no CMR granules).
- Access: Earthdata bearer token in gitignored `.env` (`EARTHDATA_TOKEN`, ~60-day); earthaccess 0.18 added.
  SP granule `data/raw/snow/NSIDC-0791_SP_0.01Deg_WY2001-2023_V01.0.nc` (1.6 GB).

### 2026-07-13 — First MapLibre globe: Tier-2 stack validated end-to-end (region-first)

Built the first working globe over our z8 tiles — the full chain **shade → tile → MapLibre globe** — on a
South Asia region (6 cells, 70–100°E / 20–40°N: N India, Himalaya, Tibet, Myanmar), to de-risk the whole
stack before a full-planet build. **Judge the z8 look on the sphere here — this is what the z8-vs-z10 call was
waiting on.** Reopen: `python -m http.server 8765` in the tiles dir, open `localhost:8765` (scratchpad artifact,
regenerable via the commands below).

- **`pipeline/tile/shade.py`** (new, production) — shades a set of chunks into ONE seamless Web Mercator RGB.
  Reprojects each chunk's height+masks to a **WebMercatorQuad-aligned 3857 grid** (`gdalwarp -tap -tr 305.7483`,
  which snaps to the z8 tile grid because 20037508.34 = 65536 × 305.7483), VRT-mosaics them, then shades the
  **mosaic once** (color-relief × hillshade × SVF, mask-composited) so there are **no chunk-edge seams** (shading
  per-chunk would seam at the hillshade 3×3 / SVF halo). Locked knobs (single-NW, physical 15× via
  `relief.mercator_zfactor` at the region mid-latitude, tuned composite defaults). Composite loads the whole
  region into RAM — **a planet run must window it**. ~27 s for 6 cells; pyright-clean.
- **Tiling path:** `gdal raster tile --tiling-scheme WebMercatorQuad --min-zoom 0 --max-zoom 8 region_rgb.tif
  DIR/tiles` → XYZ dir (z0–8; 571 tiles / 70 MB for the region; ~3 s). **Default tile size is 256 px — production
  wants 512 px** (still to set). gdal's default `xyz` convention matches MapLibre's raster scheme (no y-flip).
  **For local dev, serve the XYZ dir with `http.server` + a MapLibre raster source at `/tiles/{z}/{x}/{y}.png` —
  no PMTiles needed.** PMTiles is the Phase-4 single-file deploy; `pmtiles convert` only reads **MBTiles**, so the
  eventual pack path is gdal→MBTiles→`pmtiles convert` (or gdal→dir→mb-util→pmtiles).
- **The globe page** (MapLibre GL JS v5 via CDN, `projection: {type:'globe'}`, a raster XYZ source + a background
  ocean layer + `setSky` atmosphere) is a ~40-line `index.html` in scratchpad — trivial to rebuild.
- **Validated:** MapLibre globe + our shaded z8 tiles render correctly, seamless across chunks, correctly placed.
  The Tier-2 stack works on our data.
- **Caveats (all deliberate):** region-only (rest of sphere = flat ocean bg); 256 px; snow only where WorldCover
  is already on disk; the untuned grey high-country gap; single mid-lat z-factor per region (planet bands it).
- **Next:** judge z8 on the sphere → the z8-vs-z10 call; then scale to the full planet (+ global snow layer,
  512 px, latitude-band the z-factor, window the composite, PMTiles); optionally a composite-knob sweep first to
  warm the high country.
- **Uncommitted (Rohan commits):** `pipeline/tile/shade.py` + `pipeline/tile/__init__.py` (this milestone) — plus
  the still-uncommitted `pipeline/render/palette.py`, `relief.py`, `tests/test_palette.py`, `test_relief.py`,
  `pipeline/experiments/tile_chunk.py`, and `PLAN.md`.

### 2026-07-13 — Shading stage designed + first Mercator chunk vs hero; Antarctica prefetched; snow is tile-scope

Started Phase 2 step 2 (raster shading). Design decided and validated on one chunk before a global build.

- **Antarctica prefetched (data only).** All **26,450** GLO-30 land tiles now on disk (the deferred ~7,042
  Antarctic tiles added, ~55 GB — they compress small). Antarctica *fusion* stays a separate special-case
  pass: GEBCO_2026 is ice-SURFACE elevation, not bathymetry, so the fusion's no-tile→ocean rule would clamp
  it to −1 m. New `download_glo30 --tiles` + `fuse_planet --emit-missing` drive precise scattered-gap fetches.
- **Tier scope clarified — the shaded raster tiles are the visual skin for BOTH Tier 2 and Tier 3.** Tier 3 =
  the same draped tiles + a terrain-RGB *displacement* layer (elevation encoded as RGB, carries no color) +
  click-to-hero. So **snow must be visible on the tiles**, else Tier-3 fly-to shows bare peaks while the heroes
  (Tier 1, and the Tier-3 click-to-hero) show them snow-capped. → a **global snow layer is required tile-scope**,
  not merely a Tier-1 hero input.
- **Projection: shade natively in Web Mercator with a per-latitude-band z-factor** (`relief.mercator_zfactor =
  exaggeration / cos(latitude)`; `pipeline/render/relief.py`, TDD'd). Reversed an initial equal-area-then-
  reproject lean, on this reasoning: hillshade needs correct slope *aspect* (an angle), and the projection
  property that preserves angles is **conformality**, not equal-area. **Mercator IS conformal** → aspect is
  already correct; its only error is scale (`1/cos φ`, flattening relief poleward), fixed exactly by the band
  z-factor. Equal-area would distort aspect (wrong-facing slopes) *and* needs a lossy reproject before tiling.
  So Mercator-native is both **more faithful and simpler** (tiling is a pass-through, no resample). The heroes'
  per-country AEA works only because a small area is near-conformal in any projection.
- **Recipe = `gdaldem color-relief` (shared palette) × `gdaldem hillshade` × SVF, composited by mask** — ported
  from the `experiments/tile_recipe.py` prototype. New `pipeline/render/palette.py` is the **single source of
  truth** for the land/sea/snow/water ramps (bpy-free so the hero scene can import it too), TDD'd with an
  independent-oracle drift guard against the frozen hero hex (E9D9C0/E9DCC8, 8FC7C5/3A6E7D). pytest is back in.
- **First artifact — Nepal cell `e080_n20`, ~27 s** (`experiments/tile_chunk.py`, which shades one chunk and
  knob-sweeps vs a hero). The Mercator recipe **reproduces the hero family** (warm land, brown mountains, snow,
  teal water). Findings: **single-NW sun beats multidirectional** (multidir greys the high country; matches the
  hero's baked NW convention) → the `[ ]` shading checkbox's "multidirectional" is superseded; exaggeration
  ~×1.0–1.2; the one real gap is the high Himalaya/Tibet reading grey/desaturated vs the hero's warm brown,
  which the *composite* knobs (saturation/warmth/exposure) address. This **leans the raster-vs-Blender fork
  toward raster.**
- **Cost model (why tuning is cheap):** the expensive layers (reproject, color-relief, SVF, snow) are computed
  once per chunk (~30 s); hillshade re-runs per light/exaggeration (~5 s); the composite is pure numpy (~ms) —
  so a whole knob grid costs about one build. Next: sweep the composite knobs to warm the high country, then
  judge final restraint on the real MapLibre globe (not in the abstract).
- **Uncommitted (Rohan commits):** `pipeline/render/palette.py`, `pipeline/render/relief.py`,
  `tests/test_palette.py`, `tests/test_relief.py`, `pipeline/experiments/tile_chunk.py`.

### 2026-07-13 — Planet-wide fused heightfield built (Phase 2, step 1)

The first Phase-2 artifact: a seamless global land+bathymetry heightfield, the analysis-ready
input the tile pyramid is shaded and cut from. New `pipeline/fuse/fuse_planet.py` orchestrates
`fuse_heightfield.py` over the globe; `fuse_heightfield` gained `--coverage-warn`, `download_glo30`
gained `--tiles` (both leave existing paths unchanged).

- **Grid: EPSG:4326 @ 10 arcsec, chunked into 10x10-degree whole-degree cells** (3600x3600 px;
  648 global, 540 run). 4326 over 3857 because a constant-degree grid and WebMercator both scale
  ground-res by cos(lat), so 10" feeds the locked z8 ceiling 1:1 at every latitude with no polar
  oversampling — and a projection-agnostic master keeps the 3857 warp + latitude-varying hillshade
  z-factor as the *shading* stage's job. Whole-degree cells put every edge on an exact output-pixel
  boundary, so adjacent cells share bit-identical seams (the fusion mask is purely window-local, no
  neighbour lookup). Verified: 80E boundary reads seamless from the VRT, 0 nodata.
- **Memory was never the constraint** — `fuse_heightfield` is already windowed (~1.3 GB peak/process
  regardless of extent). Chunking buys parallelism, resume, and per-cell coverage, not RAM. Measured:
  43 s/dense-land cell, 12 workers ~9 GiB aggregate RSS, whole sweep ~15 min (the earlier "overnight"
  guess was wrong — dominated by ocean/sparse cells that fuse in ~5 s). CPU-bound at 12-wide, not
  RAM-bound; ulimit -n on this box is 524288 so the flat-VRT FD concern was moot.
- **The coverage oracle (the reason fuse_planet exists).** At fusion time an un-downloaded 1x1 land
  cell (dem=-9999, wbm=255) is pixel-identical to open ocean and `fuse_heightfield` routes it to
  min(gebco,-1) — silently flooding real land as sea, uncounted by its in-window gap check. Only
  `tileList.txt` (the AWS land index) distinguishes the two, so `fuse_planet` asserts every listed
  tile intersecting a land cell is on disk *before* fusing, and fails loudly (naming cell + missing
  keys) otherwise. `--emit-missing` prints the exact gap list for `download_glo30 --tiles`. Verified:
  deep-interior land (Kazakhstan/Sahara/Congo/Australia/Tibet) all 100% land, no flooding.
- **Antarctica deferred** (`--skip-south -60`), consistent with PLAN's special-case stance. It was
  92% of the missing tiles (7,044 of 7,659); deferring shrank the download to 615 tiles (~14 GB,
  ~2 min) from ~180 GB. Cost: the WebMercator basemap's southern cap (-60..-85, which Mercator does
  show) is blank until a later Antarctica pass. GEBCO_2026 is ice-SURFACE elevation, so a proper
  Antarctica needs its own GLO-30 ice tiles (not a bathymetry clamp) — a reason it's its own step.
- **Output as per-chunk GTiffs + VRTs, not one BigTIFF** — parallel writes/overviews/resume, and the
  tiler reads reduced-res through the VRT down to per-chunk overviews (z0-z4 mosaic with no global
  overview pass). Emits all three layers (heightfield/oceanmask/watermask) the shading recipe needs.
- **Uncommitted (Rohan commits):** `pipeline/fuse/fuse_planet.py` (new), `fuse_heightfield.py`,
  `pipeline/acquire/download_glo30.py`, `PLAN.md`. Outputs live in gitignored `data/`.
- **Next:** the raster shading stage — reproject 4326->3857, multidirectional hillshade (with the
  latitude z-factor) + `sky_view.py` SVF + the hero land/sea ramps, matched to the hero family.

### 2026-07-13 — Test suite + CI on the resolver layer (a bug caught on day one)
Added `pytest` (dev dep) + `tests/` covering the pure geometry/config layer — `pad_frame` (incl. the ±180 antimeridian clamp), `country_config` validation (the fail-loudly contract), `build_scope`, `resolve` (frame/aspect/size/fusion + the "no resolved frame escapes the world" invariant), and `main_part_fraction` — all on synthetic countries, **no external data**. Rendering/fusion/downloads are deliberately not unit-tested (GPU/data-bound). `.github/workflows/ci.yml` runs the fast gate on push-to-main + PRs: `uv sync` → `pyright pipeline/` → `pytest` (needs `libcairo2-dev` for pycairo). The suite earned its keep immediately — it caught a real fail-loudly bug: `build_scope` with an unknown `[scope].include` ADMIN recorded the error but then crashed with a raw `KeyError` before its clean `sys.exit`; fixed to build the admin set from valid includes only. Also cleared the one standing pyright finding (`download_cop30_void.ot_index` did `.search(...).group()` on a possibly-`None` match → rewritten to capture the key in the `findall`) so the CI baseline is green. A heavier data-dependent job (download Natural Earth, assert `--all` = 204/203/1 across the real scope) is a deliberate follow-up, not built.

### 2026-07-13 — Known latent bugs (recorded pre-compaction; UNFIXED in tree)
Two real defects surfaced this session by a data-free pytest suite on the resolver layer (the suite + a fast GitHub-Actions CI job were built and exercised — pyright + pytest — but are not committed to the tree). Both are latent (no live-operation crash), which is exactly why they're easy to forget — so they're recorded here with the known fix:
- **`pipeline/acquire/download_cop30_void.py` → `ot_index`** — `KEY_RE.search(stem).group()` dereferences an `Optional[Match]` (the sole pyright finding). Safe *today*: every `stem` comes from a `re.findall` whose pattern contains the tile key, so `search` never returns `None` — but brittle if that DEM-name pattern ever drifts. **Fix:** capture the key as a second group in the `findall` (`r"(Copernicus_DSM_10_([NS]\d\d_00_[EW]\d\d\d_00)_DEM)"`) and drop the separate `search`.
- **`pipeline/frame/country_config.py` → `build_scope`** — an unknown ADMIN in `[scope].include` (a `countries.toml` typo) raises a raw `KeyError` at `scope[slug] = by_admin[admin]` *before* the function's clean `sys.exit`, degrading the fail-loudly contract to a traceback. **Fix:** build the admin set from valid includes only — `… | {name for name in cfg["scope"]["include"] if name in by_admin}` — so the already-recorded "no such ADMIN" error reaches the exit.

### 2026-07-13 — Renamed to Terrella; `pipeline/` reorganized into a package; single-letter names purged
Three pre-Phase-2 cleanups, all on `main` (`feat/frontend` stays unmerged until Phase 3; it barely touches `pipeline/`, so the eventual merge mostly takes main's version):
- **Relief Globe → Terrella** (a *terrella* is the little model globe of the Earth that early scientists spun — Gilbert, Birkeland; picked over plain "Terra" because NASA's Terra Earth-observation satellite, whose ASTER instrument made the ASTER GDEM, is a direct search/branding collision for an elevation project). Renamed brand strings (site titles, masthead, About-page lede with a one-line etymology) + docs + `pyproject.toml`/`uv.lock`. **Not** renamed: the `maps/`/`maps-frontend/` folders, the git branch, the deploy domain — separate calls.
- **`pipeline/` is now a Python package**, grouped by phase — `acquire/ fuse/ frame/ render/ compose/`, with `batch.py` + `ot_oracle.py` at the root, `experiments/` unchanged. Stages now run as **`python -m pipeline.<sub>.<module>`** (was `python pipeline/<file>.py`); shell stages as `bash pipeline/<sub>/<script>.sh`; the Blender scene stays a file path (`--python pipeline/render/scene_build.py` — it imports only `bpy`). Sibling imports became absolute (`from pipeline.frame.country_config import …`); the two `sys.path.insert` hacks (gen_borders, ot_oracle) removed; `Path(__file__)…parent.parent` → `parents[2]` in the four movers that anchor on repo root; the three shell scripts' `$(dirname "$0")/..` → `/../..`. Blast radius stayed small because the command strings are centralized in `country_config.stage_commands()` + `batch.bootstrap()`. Also fixed `experiments/tile_recipe.py`'s import (double-broken: its earlier move into `pipeline/experiments/` had already broken its `sys.path` anchor). **Verified:** `pyright pipeline/` clean (one pre-existing `download_cop30_void.py` regex-`None` guard, left as out-of-scope), `-m` resolution + `--all` = 204/203/1, a srilanka run through the moved chain (download→mosaics→fuse→prep→snow all executed via the new invocations), and Blender loading `scene_build.py` at its new path. The full 8K render+sky_view wasn't run to completion — memory-gated by the desktop session, not the reorg.
- **Single-letter variable names purged** across all `pipeline/*.py` (readability; project-wide preference). Geo tuples included — `w,s,e,n`→`west,south,east,north`, `x,y`→`x_coord(s)/y_coord(s)`, `d/w/g`→`dem_win/wbm_win/geb_win`. Pure renames, no behavior change (the resolver's `--country`/`--all` output is byte-identical).

### 2026-07-13 — South Caucasus data void fixed: Copernicus "Public" withholds 25 tiles; filled from OpenTopography (Path A)
- **Root cause (not an oceanmask bug after all).** Armenia/Azerbaijan rendered as flat teal because Copernicus GLO-30 **DGED edition 2021** ("Public", the AWS Open Data tier this pipeline downloads) *withholds* the tiles over the South Caucasus — exactly **25 tiles** (lat 38–42, lon 43–51). Where the DEM is absent, fusion had nothing to place, so the frame read as ocean. Quantified with a fresh oracle: Armenia fused mean **282.9 m** (min −1.0, ~81% "ocean") vs the truth **1571.1 m** — the country is a highland, not a coast.
- **Fix — Path A (keyless fill), chosen over Path B (CDSE auth).** The void-filled tiles exist in OpenTopography's edition **2023_1**, served from a keyless public S3 bucket (`s3://raster/COP30/COP30_hh/` at `https://opentopography.s3.sdsc.edu`, `--no-sign-request`, plain-HTTPS-GETtable). Path A adds no credential to the pipeline and no friction to a future dataset bump; Path B (CDSE 2024_1) would have added OAuth for a 25-tile gap. New stages: `pipeline/download_cop30_void.py` (computes `withheld = OT_tile_index − AWS_tileList`, live not hardcoded, downloads to `data/raw/cop30_void/dem/`) and `pipeline/build_void_wbm.py` (OT ships no water-body mask, so synthesize one from ESA WorldCover: class 80 → lake=2, else land=0 — matches how the Caspian is already classed). `build_mosaics.sh` globs both `raw/glo30/` and `raw/cop30_void/` into the VRTs (`shopt -s nullglob`).
- **Oracle.** `pipeline/ot_oracle.py` fetches an independent reference clip via the OpenTopography REST API (`API_Key` from `.env`) and compares it to the pipeline's fusion — the tool that proved the void quantitatively (matched COP90 to the decimal). Kept as a dev-time validation oracle only: the REST API caps at 50 calls/24h and 450,000 km² per call for 30 m, so it is impractical for bulk fetch but ideal as a fusion witness.
- **Result.** Re-fused Armenia: mean 282.9 → **1571.1 m**, min −1.0 → 75.4, ocean 0%. Re-rendered the 5 affected countries (armenia 81% void, azerbaijan 66%, georgia 28%, iran/turkey corner slivers); kazakhstan/russia Caspian corners are cosmetic and deferred. The OpenTopography API key is gitignored (`.env`); their terms prohibit publicizing it.

### 2026-07-11 — Full v3 hero render sweep (COMPLETE 2026-07-13): 2 bugs found + post-sweep to-do — all resolved
**Status 2026-07-13 — all items below closed:** snow_mask OOM fixed (streamed via `gdalwarp` with a warp-memory cap, `snow_mask.py`), Russia + Canada re-rendered; South Caucasus oceanmask fixed via the void-fill migration (OpenTopography 2023_1 tiles for the 25 withheld tiles + synthesized WBM — see the 2026-07-13 entry), Armenia/Azerbaijan re-rendered clean; usa CONUS verified; assets (variants/borders/manifest) regenerated. Phase 1 closed.
Full v3 re-render of all 201 prepped countries (`batch.py --through render --force`, launched
2026-07-10 ~22:00), watched by a self-firing ScheduleWakeup loop + `~/render_watch.sh` logger +
`~/hero_montage.py` visual QA of every batch. Interrupted at 147/201 by an OOM at russia; **resumed**
via `batch.py --through render --only <54 remaining> --force` (russia+canada excluded — their cached
prep is absent so the OOM-prone stage is skipped). On completion the 201 prepped countries have v3
heroes; the items below are **outstanding, to handle after the sweep**:
- **BUG — snow_mask OOM on continent-scale frames.** russia + canada both die at stage 4 (`snow_mask.py`)
  loading their huge WorldCover mask (~2542 tiles) into one ~29 GB array on the 29 GB box (russia's
  killed the runner+terminal — shared cgroup). FIX: memory-bound `snow_mask.py`'s WorldCover reads
  (tile/stream the window) for huge high-lat frames; then re-prep + re-render russia + canada. Their
  download/fuse/render_prep are fine (russia's download self-healed on retry) — only snow_mask OOMs.
- **BUG — South Caucasus oceanmask over-marks water.** armenia (84% ocean) + azerbaijan (76%) render
  mostly flat featureless teal (land jammed in a corner). Confined to those two: georgia (37% = real
  Black Sea) and kazakhstan (Caspian) both render CLEAN. FIX: correct the oceanmask for armenia +
  azerbaijan, re-render. (Prep/data bug — the terrain itself renders fine.)
- **NOTE — ecuador framing.** Sea-heavy frame (Galápagos in-frame; coherent render *with* bathymetry,
  NOT the oceanmask bug) pushes the mainland to the edge — optional framing revisit, low priority.
- **VERIFY — usa** antimeridian CONUS render looks right (Rohan's request); check at/after completion.
- **VALIDATED:** antimeridian handling works end-to-end — fiji + newzealand render correctly, usa in
  the resume batch. ~197 of 201 heroes clean on visual QA (only armenia/azerbaijan broken).
- **THEN — post-render asset workflow** for the good heroes: `pipeline/hero_variants.py` →
  `pipeline/gen_borders.py` → `web/scripts/gen_manifest.py` → `pnpm build` (Phase 3, populates gallery/
  detail/borders for all countries).

### 2026-07-10 — Phase 3 begins: Tier 1 gallery shipped (Astro 7, `feat/frontend`)

Migrated here from PLAN.md on 2026-07-16 — these are shipped architecture decisions, not forward plan.
An Astro 7 static site under `web/` (git worktree `../maps-frontend`, merge to `main` later): responsive
gallery of country heroes, per-country detail pages, About page — all data-driven so they fill in as
renders complete.

- **Astro 7 + pnpm.** Self-hosted **Fraunces** display serif via the stable Fonts API (`_astro/fonts`,
  **no runtime external requests**); system sans + mono utility face. Component hierarchy: `Base` (shell +
  fonts + the floating persistent border toggle) → `Masthead` (eyebrow + heading + optional back link +
  legend, per-page via props/slots) → `Legend` (the hypsometric ramp — the signature element). Design
  tokens live in `src/styles/global.css`, moved out of a component `<style is:global>` for reliable CSS HMR.
- **Assets are external, never bundled** — the rule that keeps `dist` small. Hero WebP + border PNGs live
  in the render store: a dev-only Vite middleware maps `/heroes/*` → `blender/renders/variants/`; in prod
  nginx serves the same path. The build emits only HTML/CSS/JS referencing `/heroes/…`, so **tens of GB are
  never copied into `dist`**.
- **Manifest bridge:** `gen_manifest.py` reads `country_config` + scans the variant store → `countries.json`
  (name, continent, aspect, variant sizes, `hasBorder`). Re-run after each asset pass. Operational command
  chain lives in `docs/pipeline.md` § From heroes to the website — **not** in PLAN, where a stale copy
  rotted against moved paths (`pipeline/hero_variants.py`, `web/scripts/`) before being deleted 2026-07-16.
- **Borders** are drawn by `gen_borders.py` from prep outputs only (reusing `overlay_borders`' AEA→pixel
  mapping), independent of the render — which is what lets the gallery toggle them.
- **Responsive: two width tiers.** Browse grid `min(2200px, 94vw)` with column-*width*-driven masonry
  (~6 cols at 2K → 1 on mobile); content pages `min(1500px, 92vw)`; prose kept to a readable measure.
  **CSS gotcha worth keeping:** scoped component selectors must not collide with the shared
  `.legend`/`.card` — Astro's `figure[data-astro-cid]` **outspecifies** a global `.legend`, so scope to
  `.card figure` / `.stage figure` instead.

### 2026-07-10 — Phase 2 step B prototype: raster recipe viable; "quieter tiles" reframed
- **Result (`experiments/tile_recipe.py`, Switzerland):** gdaldem color-relief × gdaldem hillshade
  (`-z 15`, exaggeration read from frame.json) × our `horizon_svf`, reusing the hero's exact ramps +
  WATER_RGBA/SNOW_RGBA under the Standard view transform, reproduces the hero's structure and palette;
  inland lakes/rivers and snow composite in; ~20 s/run. The raster arm is viable (the raster-vs-Blender
  -tile open question leans raster), and reusing `sky_view.py` verbatim settles the SVF engine (our own
  code, not WBT/RVT). Runs on the AEA `render_1s` grid so output overlays 1:1 on the Cycles hero.
- **"Tune quieter than the heroes" → "match the hero family; decide final restraint in-context."** The
  old note borrowed a real convention (relief recedes under overlays, Huffman) that applies weakly here:
  the relief *is* the brand, typography is minimal, and borders already read on the dramatic heroes — so
  a muted globe would only break Tier 2↔Tier 3 (globe↔hero) continuity. Surviving tile-only constraints
  are high-zoom 30 m noise (fix: shelved resolution-bumping) and border/label legibility headroom — both
  argue for *slight* restraint, not flattening. "How quiet" is only fairly judged against the actual
  overlays, so decide it on the MapLibre globe with borders at several zooms, not a static side-by-side.

### 2026-07-10 — Phase 2 step A: tiling toolchain locked (WhiteboxTools dropped)
- **Locked stack:** GDAL (gdaldem hillshade/color-relief + `gdal raster tile`) + our own
  `pipeline/sky_view.py` for the SVF/openness term + `pmtiles` for packaging. `pmtiles` 1.31.0 is the
  sole vendored binary (pinned github release, installed by `pipeline/install_geotools.sh` into
  gitignored `tools/`; no brew, no `.venv` touch → reproduces in the rohome container and is safe to
  run during a live prep sweep).
- **WhiteboxTools dropped.** It was briefly installed (v2.4.0, whiteboxgeo prebuilt) as the SVF
  comparison arm, then removed the same day on two findings: (1) its repo is now **legacy** — the
  README redirects to a next-gen rewrite (`whitebox_next_gen`, Rust, no releases/binaries yet, and
  GDAL-free so no architectural fit for us); (2) the community SVF specialist is **RVT** (`rvt-py`
  2.2.3, 2025-07-04 — SVF / anisotropic SVF / openness; built on numpy/scipy/gdal/rasterio), which
  supersedes WBT for the one job it had. Decisive: our own `sky_view.py` is **already the production
  openness pass** burned into every hero, so reusing it for tiles makes them palette-consistent by
  construction. RVT is kept only as an **optional one-off numeric oracle** (needs Python <3.12; our
  venv is 3.12.10, so a throwaway 3.11 env), never a pipeline dependency.
- **GDAL pinned to 3.13.1** (latest; 2026-06-05) as the production target, delivered via the official
  OSGeo GDAL container (reproducible on dev + rohome). apt on Ubuntu 26.04 tops out at 3.12.2, and
  3.13 brings nothing our recipe needs over 3.12 (its tiling headline is the gdal2tiles→`gdal raster
  tile` default-remap of a path we already call directly) — so the step-B prototype runs on the box's
  3.12.2 and we adopt 3.13.1 at containerization. The prep sweep is unaffected either way: the venv's
  rasterio bundles its own GDAL (3.12.1) rather than linking the system `gdal-bin`.
- **Deferred:** `tippecanoe` (vector borders/coastlines → vector tiles) — a from-source build needed
  only when the vector-tile step lands, not for the raster recipe.

### 2026-07-10 — Overnight render sweep ran to 123/204, then STOPPED to fix hero quality; pipeline hardened

- **The sweep.** `batch.py --through render --clean` ran ~14 h and produced **123 heroes** before Rohan
  reviewed them and stopped it to re-assess (next entry). Single-runner throughput ~9–10 heroes/h
  (blended, incl. giant-download lulls); GPU duty cycle only ~9 % (renders are 1–4 min; most wall-clock
  is downloads — the prep-ahead redesign would reclaim this). Thermals a non-issue: GPU peaked 61 °C even
  at 98 % render load; the CPU briefly hits its 95 °C Tjmax cap during the CPU-OIDN denoise of each 8K
  frame (self-throttling, safe — a lone 95 °C read is normal, only *sustained* would be a fault). A 60 s
  GPU temp logger + a 30-min watchdog loop ran throughout (both stopped now).
- **Bug #1 — two-runner collision (Claude's error).** Rohan launched the sweep; then asked Claude to
  run+monitor it and Claude launched a **second** runner without checking → two `batch.py` raced a→z,
  `--clean`-pruning each other's `data/work/<slug>` (⇒ `heightfield.tmp: No such file` fuse errors) and
  double-downloading tiles (~30 % download failures). Killed the duplicate ~1 h in. Most of the run's ~53
  failure log-lines (27 distinct countries) trace to that hour; recoverable on re-run. **Lesson: a
  single-instance guard is needed** (the `flock` in the prep-ahead design); check
  `pgrep -af pipeline/batch.py` before launching.
- **Bug #2 — snow_mask non-idempotent (FIXED, uncommitted).** `snow_mask.py` `sys.exit`'d non-zero when
  its output existed instead of skip-exit-0 like fuse/render_prep → every already-prepped country FAIL@4'd
  and never rendered. Now prints "… exists — skipping" and returns 0.
- **Bug #3 — silent partial-data renders (GUARDED, uncommitted).** Georgia shipped with a flat nodata
  block (missing GLO-30 tiles, likely corrupted when its Caucasus tiles were fetched during the
  collision) and the runner never noticed. Added a **coverage-validation guard** to `fuse_heightfield`:
  counts land px with no GLO-30 tile (`DEM==nodata & WBM==land`) and `sys.exit`'s above 1 % → the re-run
  auto-flags + re-downloads these instead of rendering garbage.
- **Antimeridian snow_mask edge (deferred).** fiji + newzealand (+ russia, unreached) FAIL@4 — frames
  at/near 180°E hit a WorldCover edge case. A small AM snow_mask fix is needed later; those 3 (plus
  kiribati) stay unrendered until then.
- **Broken heroes on disk:** brazil + cambodia are flat/empty (collision fuse-race casualties;
  relief-detail 4.1 vs 70 median — the *only* two empties, per a full audit). The forced re-run redoes them.

### 2026-07-10 — Hero look v3: shallow-sea ramp + sky-view shading; full re-run tonight

Rohan reviewed the 123 heroes and flagged: shallow shelf seas render as white "ice" (Denmark/Ireland/
Kuwait/Netherlands/Estonia/Malaysia/El Salvador); flat countries look basic (Paraguay/Qatar); atoll
nations show ~no land (Maldives/Palau/Marshall Is./Micronesia/Mauritius/Cape Verde); Georgia/Iran partial
gaps; Monaco/Nauru banding; brazil/cambodia empty. Decisions (each validated with rendered/post-processed
demos before adopting):

- **Sea ramp → "smooth-C" (6-stop), uncommitted.** The shallowest `SEA_STOPS` stop was C6E4E2 (near-white)
  so shelf seas read as ice. New 6-stop ramp from **8FC7C5** (a real teal) with a smooth shelf→deep
  gradient, set in `scene_build.SEA_STOPS` (linear values from sRGB). Fixes the ice look AND turns
  Maldives' lagoons teal. **Supersedes the locked sea-ramp constant.** (Candidate "D" was stronger/moodier
  but needed the whole ramp re-toned; Rohan chose C.)
- **Shading → post-composite horizon sky-view-factor, burn-only. New file `pipeline/sky_view.py`,
  uncommitted.** Horizon openness (16 dir) from `heightfield_aea`, computed at reduced res + upsampled
  (~20–30 s CPU, overlaps the GPU render), **burn-only**: darkens genuinely-occluded valleys above a
  threshold and leaves open ground at rendered brightness — so flat countries gain drainage/valley depth
  with no dimming and no "desert" wash (dodge-and-burn was rejected: brightening the dominant open flats
  read as desert). Land only (ocean mask). Wired into `batch.py`'s render stage: shades the `.tmp.png`
  before the atomic promote ⇒ applied **exactly once**, never compounds; a sky_view failure fails the
  country cleanly. Strength **~0.38** (tunable). **Chosen over per-country adaptive exaggeration** (breaks
  the one-consistent-vertical-scale look) **and over in-Blender Cycles AO** (dims the whole scene, grainy
  "dirt" at ridge bases even at tight AO distance, +2.5 min/render; SVF is free by comparison).
- **Shelf edge: kept, equal exaggeration.** The shelf→deep abruptness is real geography (continental
  slope) plus the 15× exaggeration applied equally to bathymetry; Rohan chose to keep it ("truest picture
  even if shocking"). No sea-exaggeration change.
- **Maldives / atolls: accept as mostly ocean.** Tested 1″ + max-resampling (added `--land-resampling` to
  fuse; **default unchanged = average, status quo**) — **no gain** (0.46 %→0.46 % land; frame is 99.9 %
  ocean). Data reality; the stronger sea ramp handles the look.
- **THE RE-RUN (do this next):** `python pipeline/batch.py --through render --force` — **no `--clean`**
  (keep prep for fast iteration) and **`--force`** so all 204 re-render with the new ramp + SVF (the sea
  change is baked in Blender ⇒ every hero must re-render; prep re-fuses from the **cached raw GLO-30
  tiles** — no re-download except gaps/remaining countries). **SINGLE RUNNER ONLY** (`pgrep` first). The
  coverage guard + snow_mask fix + single runner prevent the earlier damage. fiji/nz/russia + kiribati
  stay unrendered pending the AM snow_mask fix. Expect a full overnight (~re-prep all 123 done + download
  the ~81 remaining + render all + SVF).
- **Raw-render preservation (uncommitted `batch.py`).** The render stage now writes the raw Cycles frame to
  `blender/renders/heroes/raw/<slug>.png` (kept) and sky_view derives the shaded `heroes/<slug>.png` as a
  separate file. A cached raw + no `--force` **skips the GPU and re-shades only**, so future post tweaks
  (sky_view strength/threshold, border overlay, grading) re-composite over every hero in minutes with no
  re-render — provided `data/work/<slug>/render/` (heightfield+oceanmask) is kept, i.e. still **no
  `--clean`**. ~12 GB for 203 8K raws vs 556 GB of tiles. Landed *before* the render pass so tonight's run
  captures the raws (retrofitting would mean re-rendering to recover discarded raws).
- **Workflow split (2026-07-10):** prep-all now (`--through prep`, running — dry-run: 179 would-run, 24
  skip-done, only Kiribati skipped; russia/usa/nz/fiji now resolve via frame overrides and are attempted —
  their snow_mask outcome is the open question the prep run answers), then a GPU-only `--through render
  --force` pass tonight (prep stages skip in seconds). GPU has large thermal headroom (61 °C peak vs ~83 °C
  throttle) — run renders back-to-back, no throttle; steady load is gentler than thermal cycling.
- **Antimeridian/polar snow_mask fix (uncommitted `snow_mask.py`).** Root-caused the canada/nz/fiji
  stage-4 failures: `snow_mask` derived its WorldCover tile window from `transform_bounds` of the AEA
  raster, which for a large high-latitude or antimeridian frame fans past the pole/dateline and returns a
  wrapped window (west ≥ east) → `tiles_for_bounds` selects 0 tiles → false "every tile absent" abort. Fix:
  keep `transform_bounds` as primary (byte-identical for normal countries — verified chile 135, cambodia 9,
  chad 35, bulgaria 6 unchanged), fall back to render_prep's `frame_lonlat` **only** when the window wraps
  (canada 0→594, nz→42, fiji→8). Self-contained in `snow_mask.py`, so russia/usa are auto-handled when the
  running prep reaches them, and canada/nz/fiji regenerate their snowmask during tonight's `--force` render.
  Resolves the deferred antimeridian snow_mask item; russia/usa/nz/fiji can now render.
- **Uncommitted (Rohan commits):** `snow_mask.py`, `fuse_heightfield.py`, `scene_build.py`, `batch.py`,
  `pipeline/sky_view.py` (new), `PLAN.md`.

### 2026-07-09 — Hero presentation explored (spike): no single universal design; geography-conditional; margins read flat

- **Question:** beyond the rectangular framed hero, how should a country be *presented* in
  the gallery? Ran as post-processes on existing heroes (Sri Lanka = coastal, Switzerland =
  landlocked) reusing `overlay_borders` geometry — no look change to the renders, no
  locked-constant touch.
- **Ruled out (incoherent / artefacts):** (1) country-shape cutout with a faded **sea ring**
  into a cream page — three unrelated zones (land → teal ring → paper); water doesn't dissolve
  into cream. (2) hard-edged coastal **rim** of sea — a uniform band that reads as an outline,
  "juts." (3) **synthesising** a generous ocean from the tight render — real bathymetry ends at
  the render frame, so beyond it is invented → visible rectangle/glow seams (the frame boundary
  is literally visible).
- **What works:** (a) **cutout-cream** — country land silhouette + **drop shadow** on a cream
  vignette; the shadow is essential (grounds it; without it the silhouette floats). Coherent,
  honest, neighbour-free; works for island *and* landlocked. (b) **real generous ocean** —
  re-render at a bigger frame so real GEBCO bathymetry fills the sea edge-to-edge with an ocean
  vignette; coherent and on-brand. Demoed: Sri Lanka at 35 % pad, 3″ fusion (adequate — the
  97 m/px render is coarser than the 3″ source), rendered 2:24; generous frames pull in
  **neighbours** (India across the Palk Strait).
- **The trilemma (why no universal rule):** *consistent across all countries* / *coherent (no
  land–sea–cream salad)* / *only the target country visible* cannot all hold at once.
  cutout-cream = consistent + coherent + neighbour-free + real-data but **no sea**; real-context
  = consistent + coherent but **neighbours dominate** (a landlocked country is lost in neighbour
  terrain); everyone-an-island (mask all neighbour land → sea) = consistent + coherent +
  neighbour-free but the sea is synthetic and **fictional for landlocked** (Switzerland floating
  in an ocean); real generous ocean = gorgeous + coherent + real but only honest for **true
  islands** (landlocked have no sea) → cannot be universal.
- **Conclusion (Rohan, deliberately not finalised):** no single fixed design — presentation is
  **geography-conditional**: cutout-cream suits continental/landlocked; real-ocean suits
  genuinely water-surrounded (island) countries.
- **Central open gap:** the two treatments fit the *extremes* (pure island, pure landlocked);
  **most countries are BOTH coastal and bordered** (France, USA, India, Brazil) and the split
  doesn't classify them. Needs a tier rule (coastline-fraction of perimeter? land-neighbour
  count? % sea in frame?).
- **Second open problem (Rohan):** **every** treatment reads **flat at the country margin** —
  the boundary transition lacks depth. Unsolved; wants its own pass (edge relief / lighting /
  gradient?).
- **Cost is not a blocker for two of three.** cutout-cream and everyone-island are **pure
  post-processes of the existing tight renders** — no re-render, no frame change → the current
  tight-frame prep sweep is correct for them. Only the island real-ocean tier needs bigger
  frames; of the three cost paths (A synthetic = fake; B full generous re-renders ≈ 2–3× GPU +
  storage; C low-res sea pass + high-res land composite ≈ +10–20 %), **C** is the sweet spot if
  that tier is pursued.
- **Reusable machinery (for the Phase-3 revisit):** AEA→render-pixel mapping via
  `overlay_borders.render_mapping` (reads `frame.json` `ortho_scale`), validated by the coast
  oracle (< 2500 m); ocean-mask convention **0 = land, 1 = sea**; hero PNGs are opaque RGBA
  (`film_transparent` off, opaque sand world) so alpha only means something after a cut;
  neighbour removal is an NE-polygon mask (keep real sea, drop neighbour land); sea shares the
  land's 15× vertical exaggeration → dramatic submarine relief (a knob if calmer sea is wanted —
  Rohan: exaggeration is fine).
- **Housekeeping:** throwaway spike scripts (`pipeline/experiments/hero_*_spike.py`) and demo
  outputs removed; the reusable core stays in `overlay_borders.py`; `CUTOUT.md` graduated into
  this entry. **Decided at:** Phase 3 gallery/globe design, once the rectangular heroes exist to
  judge against — does not touch the locked constants.

### 2026-07-09 — Antimeridian: no wrap-math; 4 mainland overrides + Kiribati deferred

- **Premise-check beat the scary version.** True antimeridian wrap-math (W>E frames, shifted
  source VRTs across ±180, touching 4 pipeline files) looked inevitable. A cos-lat-area part
  audit of the 5 marked countries showed the land concentrates on ONE side of 180 for four:
  Russia 99.3% at 19.6-180E, US 100% western (CONUS=82.9%), NZ 99.7% at 166-179E, Fiji 95.8%
  at 174.6-180E. So each reduces to a **non-crossing mainland/main-island frame override** —
  the existing France/Chile mechanism, zero wrap-math. Dropped trans-180 remainders (Chukotka
  sliver, Alaska/Hawaii, Chathams, Lau group) recorded in each `notes`; consistent with the
  mainland-only far-flung policy.
- **Kiribati deferred** (decided with Rohan): genuinely split 32% Gilberts (east, capital
  Tarawa) / 68% Phoenix+Line (west, largest atoll Kiritimati), no dominant side. No
  non-crossing frame represents it and a true 40deg crosser is mostly empty ocean — a
  special-case like Antarctica, kept `status="antimeridian"` (in-scope but skipped), no hero.
- **Code: two tiny changes.** `frame_country.pad_frame` now clamps to [-180,180]x[-90,90]
  (a no-op off the antimeridian; **also fixes Tuvalu**, whose 179.9E island padded to 180.1
  and failed the GEBCO window). `country_config.resolve` skips the "raw bbox spans 180 -> need
  a status marker" abort when a `frame` override is present (the override is authoritative).
- **Verified:** the 4 resolve to frames with E<=180, GEBCO covers, GLO-30 fetches on demand
  (Russia 4919 tiles — the sweep's biggest, `--clean` reclaims it); `--all` now 203 resolved /
  1 antimeridian-skipped (was 199/5); **no** resolved frame escapes [-180,180]x[-90,90];
  nepal/switzerland/france/india/chile frames byte-identical (clamp is inert elsewhere).

### 2026-07-09 — Batch runner: crash-safe orchestration + dynamic OOM defense

- **`pipeline/batch.py`** drives the full pipeline across the in-scope countries, reusing
  `country_config` (scope, frames, `stage_commands`). Each stage runs as an isolated
  subprocess (a Blender segfault/OOM kills only that process), sequential (the render is
  GPU-bound). `--through prep` (default) runs download→snow; `--through render` adds the
  render. Default prep so a bare run can never start the ~10–13 h render sweep; `--dry-run`
  previews (204 → 5 antimeridian, 1 GEBCO/Tuvalu-past-±180°, 196 to run). `--only`/`--limit`/
  `--force`. `--clean` (render mode) prunes each country's `data/work/<slug>` + `.blend`
  once its hero lands — the disk-safety valve for a full sweep, which otherwise accretes
  ~500 GB of GLO-30 tiles + fusions on top of the 285 GB already used (hero PNGs and the
  shared raw tiles are kept). Failures → one timestamped JSONL line in
  `blender/renders/batch_failures.jsonl`, country's rest skipped, run continues; the
  end-of-run summary rosters the failed + low-mem-skipped slugs by name so a re-run is
  informed at a glance. Fail-once-then-skip is accepted (Rohan): recover by re-running the
  same command (filesystem resume).
- **Resilience to abrupt shutdown (Rohan's requirement) is the keystone.** Filesystem-resume
  is only safe if "output exists" means "output complete," so **every stage now finalizes
  atomically** — `fuse_heightfield`, `render_prep`, `snow_mask` write to `.tmp` and
  `os.replace` on success (PNG `.aux.xml` sidecar moved too); the runner renders to a
  `.tmp.png` it promotes on exit 0. (This fixed a latent CLAUDE.md violation — those stages
  wrote straight to final paths, so a kill mid-write left a partial file resume would trust.)
  `fuse_heightfield` also aligned to skip-exit-0 when complete (was a hard error), so
  "re-run all stages, each skips what it finished" is the uniform resume contract. **Verified:**
  SIGKILL mid-fusion leaves only `.tmp` (no partial final); re-run recovers byte-identical;
  deleting a snowmask and re-running re-executes only `snow_mask` (fusion skip-exit-0).
- **Dynamic OOM defense** (machine: 30 GiB): sequential; a pre-render memory gate waits
  (bounded 30 min) if `MemAvailable` < floor (default 14 GiB, `--mem-floor-gib`) then defers
  the country rather than starting a doomed render; heavy stages (fuse, render) run under a
  best-effort `systemd-run --user` cgroup `MemoryMax` (≈85 % of MemTotal, `MemorySwapMax=0`)
  so a runaway is cleanly killed, not left to thrash. **Cap enforcement verified** on the dev
  box (300 MB under a 64 MB cap → rc 137; memory controller delegated to the user manager);
  degrades to no-cap where unavailable (container). An OOM-kill (rc 137) is logged `kind:oom`
  and the country skipped — **no silent quality-degrade** (locked-look consistency); the human
  decides from the log. Runner keeps no durable in-memory state → a killed runner just re-runs.
- **Prep-ahead producer/consumer runner: designed, measured, DEFERRED — and probably permanently.**
  (Migrated here from PLAN.md on 2026-07-16; it sat as an unbuilt 25-line design in the living plan long
  after its gate passed.) `batch.py` serialises prep (stages 0–4: download/mosaic/fuse/warp/snow —
  network/CPU/disk, GPU-idle) with the render (stage 5 — GPU) per country, so the GPU idles through
  downloads. **Measured on the 2026-07-09 sweep: ~9% GPU duty cycle** — ≈15 min of rendering inside
  ~2h49m; Canada's 6376-tile download alone idled the GPU ~40 min, while renders are only ~1–4 min each.
  - **Design, if ever built.** Render is VRAM-locked to one-at-a-time (8K peaks ~11–12 GB of 12 GB), so
    *render must stay serial*; the win is overlapping prep with render (disjoint hardware). One render
    worker holds **the sole GPU lease**, draining a queue; 1–few prep workers stay N countries ahead.
    The ready queue is **implicit** — countries whose `render/`+snowmask exist but hero doesn't,
    discoverable by filesystem scan — so **resume stays filesystem-only, with no durable queue state**.
    Prep **smallest-first** (by GLO-30 tile count) so the renderer never starves behind a giant download.
    Disk bounds the queue depth N (each un-pruned work dir is up to ~4.5 GB).
  - **Safety invariants that must NOT regress** — each one is a bug this project already paid for:
    (1) **single-instance `flock`** — the 2026-07-09 two-runner collision was exactly this missing guard;
    (2) **per-country claim** (atomic `mkdir data/work/<slug>/.claim`) so no two workers share a work dir
    — this is what produced the `--clean`-vs-fuse race and its `heightfield.tmp: No such file` errors;
    (3) `--clean` stays post-render and render-worker-only; (4) atomic stage finalisation unchanged;
    (5) **RAM-aware gating** — cap concurrent memory-heavy ops (≤1 fuse) and keep the pre-render
    `MemAvailable` gate + cgroup cap, since a big fuse plus a ~12 GB render can blow past 30 GB.
  - **Why it is probably moot.** Expected win was wall-clock → `max(total_prep, total_render)` instead of
    the sum (~2–4× on download-heavy runs). Its gate was "after Phase 1 hero renders complete" — which
    passed on 2026-07-13, with the sweep already done. The **zero-complexity 90% alternative** is the
    existing phase split (`--through prep` to completion, *then* `--through render` = pure GPU), which
    suffices whenever prep may finish first. Build it only if a full re-render sweep is ever needed again.

### 2026-07-09 — Global GEBCO acquired: batch renders unblocked 6 → 198 countries

- **Why now:** a data audit via `country_config`'s own preflights found only **6 of 204**
  countries were renderable — all inside the single regional GEBCO tile
  (60–100°E/0–40°N); the other 193 failed GEBCO coverage. GLO-30 was never the blocker
  (on-demand per country). Global bathymetry was the true critical path for the whole rest
  of Phase 1. Chosen over antimeridian handling (those 5 are blocked on this same data and
  can't be render-validated without it).
- **Acquired:** GEBCO_2026 **ice-surface** global grid, 8× 90° GeoTIFF tiles (15″, Int16,
  nodata −32767), ~4 GB zip direct from CEDA
  (`dap.ceda.ac.uk/bodc/gebco/global/gebco_2026/ice_surface_elevation/geotiff/`) →
  `data/raw/gebco/gebco_2026_global.vrt` via `gdalbuildvrt`. Ice-surface not under-ice
  (relief shows the visible landscape; Greenland is a hero). TID grid deferred
  (diagnostic-only, like GLO-30's FLM). Regional tile kept as the `--gebco` regression
  reference. **Refined the plan** (which said "single translated GeoTIFF"): a VRT over the
  8 tiles matches the `dem_mosaic.vrt` convention and avoids a 7.5 GB copy.
- **Wiring:** `fuse_heightfield.py` `GEBCO` → the global VRT, plus a `--gebco PATH`
  override (default = the constant, so `country_config`'s import still resolves);
  `country_config.preflight_gebco` message now points a coverage miss at the antimeridian
  item (the only way to miss a global grid). Unblock proven: `--country japan` passes GEBCO;
  scope-wide GEBCO coverage **6 → 198/204** (remainder = antimeridian frames past ±180°).
- **Regression (Sri Lanka, all-coast, re-fused from global vs regional):** land and both
  masks **bit-identical**; ocean differs by **±1 m at ~0.02 % of pixels**. Chased to ground
  with independent oracles: the two GEBCO sources are **byte-identical where they overlap**
  (0 diffs at native res), and wrapping the regional tile in a VRT is bit-identical to
  reading it directly — so it is not a data difference and not the VRT path, but
  `Resampling.cubic_spline`'s source-structure-dependent numerics (diff count itself
  shifts 1804/1465/1299 with source tiling/extent). **Sub-visible and irrelevant:** ±1 m is
  below GEBCO's own vertical accuracy (tens of m) and invisible under a sea ramp spanning
  0→−3000 m in 4 stops. Consequence noted: the 6 held fusions came from the regional tile,
  so they differ from global by this same sub-visible ocean noise — optional one-source
  re-fusion later; India's render is approved/pinned, so no re-render is warranted.
- **Reproducibility (follow-up, same day):** GEBCO was the only dataset acquired by hand
  (an ad-hoc curl) — a fresh clone / rohome could not fuse. Closed by
  `pipeline/download_gebco.py` (mirrors download_glo30: reuses its `download_one`,
  resumable, versioned-path edition pin, 404 = naming-drift abort; fetches the 8 tiles and
  rebuilds the VRT). `country_config --country` now prints it + `download_naturalearth.sh`
  as **stage 0** (once per machine), so the printed recipe is a complete fresh-clone
  bootstrap. Folder-grouping the download scripts was considered and **deferred**: the
  cross-module flat imports (`country_config` ← download_glo30/frame_country/…) would force
  the package layout CLAUDE.md defers until the batch runner reveals the seams.

### 2026-07-09 — Hero .blend files are build artifacts, not versioned; source is canonical; prior-art audit logged

- **Decision:** stop git-versioning generated hero `.blend` scenes (`blender/*.blend` gitignored; `git rm --cached` the two tracked ones). The **one exception** kept in git is `india_hero_handbuilt_phase0.blend` — the hand-built Phase 0 scene, which no script reproduces (archival provenance of the origin recipe).
- **Why:** each `.blend` is a thin ~96K pointer file that references the heightfield/mask rasters living in gitignored `data/`, so a committed copy opens with dangling textures on a fresh clone — it is not a working artifact. It is fully regenerated by `scene_build.py` from committed constants + `frame.json` (+ data), so it is a build artifact in the same class as a rendered PNG (already gitignored). It also goes stale silently the moment a constant changes. The canonical, diffable, forkable form of a scene is `scene_build.py` itself — the script is the better open-source artifact than a binary with broken paths. If a ready-to-open scene is ever wanted for third parties, the mechanism is a *packed* `.blend` (Blender File → External Data → Pack) shipped as a GitHub Release asset, not a repo-tracked file.
- **Follow-up:** end-of-Phase-1 item added to document the regeneration/CLI path (a fresh clone reproduces any hero from source).
- **Prior-art audit (context):** GitHub + web survey of neighbours. Closest is **LuisSevillano/relievo** (bbox→Blender relief in one command; per-map, no fusion/snow/tiling/globe); also tbloch1/dsm_blend, mattf1n/Relief-Map, joewdavies/geoblender (technique automation); globe engines NASA WorldWind / openglobus / Cesium; global raster relief galleries shadedrelief.com / Natural Earth. **No project combines all-countries raytraced heroes + interactive relief globe + PMTiles static serving** — the novelty is the integration; the gap is labor/compute, not law (see ATTRIBUTIONS.md for the licensing posture). Neighbours mostly *validated* our choices by convergent evolution (dry-run preview, sun+fill two-light, TOML config, min-viable-resolution, low-pass anti-bump); two genuinely new ideas captured as spikes above (country-shape alpha cutout; gdaldem post-composite = our Phase 2 tile arm). Made-with-AI attribution + full data-license posture recorded in the new ATTRIBUTIONS.md.

### 2026-07-09 — Per-country config live: countries.toml is the scope/overrides home; long-edge resolution rule; fusion choice formalized

- **Scope (decided with Rohan): strict + curated.** NE admin-0 `ADMIN == SOVEREIGNT` (de-facto worldview) selects 208 rows; 9 excluded with reasons in config (Bir Tawil, Spratly, Scarborough Reef, Bajo Nuevo, Serranilla, Cyprus No Mans Area, Brazilian Island, S. Patagonian Ice Field; **Antarctica deferred** — special-case hero: polar projection, no WorldCover); 5 curated dependent territories included (Greenland, Faroe Islands, New Caledonia, French Polynesia, Puerto Rico) = **204 heroes**. Audit that drove the design: 62 countries over 9,000 px tall under fixed-width-7680 (Maldives 56k, Norway 25k), 37 far-flung-inflated bboxes, 6 antimeridian crossers.
- **Resolution (decided with Rohan): hero long edge 7680**, config default + per-country override (`hero_long_edge`; render_prep `--hero-long-edge`). Wide countries are a no-op by construction — replaying scene_numbers against Nepal/Switzerland frame.jsons reproduces all five numbers exactly. Sri Lanka's frame.json regenerated: only res_x/res_y changed, 7680×12498 → 4720×7680; scene_build cross-check passes. India stays pinned at 7680×7906.
- **Far-flung (decided with Rohan): whole bbox unless catastrophic** (main landmass under ~25% of a bbox axis). Five mainland frames authored in config — France, Netherlands, Norway, Portugal, Chile — as mainland-part bbox unions through the standard pad_frame math; every dropped part verified by coordinates (Easter Island, Svalbard, Azores, Caribbean municipalities, Guiana/Mayotte/Réunion…). 17 further far-flung rows flagged informational only (genuine archipelagos: Micronesia 1%, Tuvalu 1% — whole bbox is their correct frame).
- **Resolver (pipeline/country_config.py), read-only glue:** frame (override or bbox+pad), projected aspect via the frame's own AEA, warp width (long grid edge ≈ 8192), **auto fusion — 1″ iff the 3″ mosaic would upsample into the warp grid** (reproduces the India/Nepal/Switzerland history; Sri Lanka's legacy 3″/3072 QA-era grid predates the rule and would re-fuse at 1″ if ever redone), GLO-30 held-tiles preflight from tileList.txt (land-tile index ⇒ ocean cells can't count missing), GEBCO window preflight (fails loudly; global GEBCO = Phase 2 acquisition), `--emit-pin` (config/frames/<slug>.json → workdir; India's round-trips byte-identical; render_prep no-op re-verified), `--all` audit (204 rows, 0.45 s). Fail-loudly oracles *witnessed* on doctored configs: unknown keys, unresolvable names, unmarked antimeridian bbox.
- Antimeridian rows (Russia, US, NZ, Fiji, Kiribati) marked `status = "antimeridian"` and skipped loudly — their own Phase 1 item. Noted for it: **Tuvalu's padded frame crosses 180°** (pad pushes 179.9 → 180.1) without its bbox crossing; the marker list isn't the whole story.

Newest first. Each entry records what was decided, the deciding evidence, and what it would take to reopen. Constants and tunable levers live in the locked section above and in ART.md — not here.

### 2026-07-08 (late night, follow-up) — GLO-30 aux layers audited: hero mountain terrain is ~20–50% fallback-DEM fill; FLM adopted as on-demand diagnostic, not a pipeline stage

- The bucket carries, per tile: DEM + 4 aux rasters (EDM edit mask, FLM filling mask, HEM 1σ height error, WBM) + ACM/SRC KMLs + XML + quicklooks; same URL pattern (`<tile>/AUXFILES/<name>_FLM.tif`).
- FLM legend (Product Handbook i5.0, Table 7): 0 void, 1 edited, **2 native (not edited/not filled)**, 3 ASTER, 4 SRTM90, 5 SRTM30, 6 GMTED2010, 7 SRTM30plus, 8 TerraSAR-X radargrammetric, 9 AW3D30, 100+ national DEMs. EDM (Table 6): 0 void, 1 not edited, 2 infill, 3 interpolated, 4 smoothed, 5 airport, 6 raised-negative, 7 flattened, 8/9/10 ocean/lake/river, 11 shoreline, 12 morphed, 13 shifted.
- One-time audit of six money-terrain tiles (fill = 100% − native − edited): **Karakoram/K2 ~49% filled** (30% SRTM30 + 17% AW3D30), **Nanga Parbat ~48%** (46% SRTM30), Everest ~19%, Zanskar ~22%, Valais ~17%, Aletsch E ~28%. TanDEM-X radar fails exactly on steep snow/ice faces, so fill concentrates in the dramatic terrain our heroes feature.
- Verdict: no visible seams or texture anomalies in any approved render to date (India v3/v4, Switzerland, Nepal, Sri Lanka — all QA'd at 1:1), so **no action and no pipeline stage** — the risk is real but not manifest; Airbus's delta-surface blending plus our 15× shading evidently masks source boundaries at poster scale. **FLM is the first thing to fetch when a hero ever shows a smooth patch, texture seam, or implausible mountainside**; EDM is the first fetch for shoreline oddities (relevant to the known NE-vs-WBM lagoon-spit disagreement class). HEM = per-pixel trust map, third in line.

### 2026-07-08 (late night) — Snow/ice adopted as a data mask; shadow fill sun; land ramp de-whitened

- **Why:** satellite imagery shows permanent snow on the high Alps that the hero couldn't — snow is climate, not elevation (snowline ~3,000 m Alps vs ~5,500 m Himalaya), so no global elevation ramp can paint it honestly. Same-day decision window deliberately: a look change now costs 2 re-renders, after the batch ~195.
- **Dataset: ESA WorldCover 2021 v200 class 70** (10 m, Sentinel-1/2 full-year composite, frozen versioned edition, CC-BY 4.0, public S3 COGs — same provenance family as GLO-30). Full-year composite ⇒ class 70 is *permanent* snow/glacier; seasonal snowpack excluded by construction — matching the hero's editorial stance everywhere (permanent water, perennial rivers). Rejected: RGI 7.0 (year-2000 snapshot, no ice sheets), ESRI/IO annual (mutating series, Clouds holes), Dynamic World (not pinnable), CGLS-100m + MODIS MOD10/climatologies (too coarse: 100 m–1.1 km), DLR Global SnowPack (500 m; **shelved as the persistence-audit layer** if class-70 contamination ever appears), Copernicus HR-WSI Persistent Snow Area (semantically ideal, 20 m, but pan-European only — kept as validation reference), HLS (reflectance record, not a classification — would mean rolling our own snow science), NE glaciated_areas (1980s–90s DCW vintage), Glaciers CCI (unshipped), climatic snowline formula / per-country ramp normalization (invented data / breaks locked semantics).
- **Masks sane:** Switzerland 2,936 km² in-frame (≈½ non-Swiss Alps: Mont Blanc, Monte Rosa south side, W Austria), India 117,252 km² (Karakoram–Himalaya–Pamir–Kunlun–Tibet); both hug the high chains, zero lowland speckle; 10 m→48 m nearest edge speckle reads as natural fragmented snowfields (majority filter held in reserve, on evidence only).
- **Snow color E8F1F6** (glacial blue-white) over F4F8FA/FFFFFF/warmer arms: at continental scale the cool cast is what separates snow from pale high ramp colors — on India, F4F8FA vanished into the ramp; warm ivory failed outright.
- **Shadow legibility** (Rohan's observation: shadowed faces hid texture, jagged sun/shadow alternation): shadowed slopes had only flat world fill — no directional light to express texture; 15× on the finely-resolved Swiss grid maximizes shadow area. Chosen: **shadowless SE fill sun @ 15% + main sun angle 12°** — fill restores modeling in shadow while barely touching sunlit faces; benign on India. Rejected: ambient 0.3→0.5 (lifts levels, adds no modeling, washes rosy), angle-only (≈no effect on depth), higher sun altitude (kills the low-sun signature), per-country exaggeration (breaks series comparability), post tone-lift (second look-definition outside the scene). 10/15/20% sweep: 15% balanced; 10% defensible-moodier.
- **Land ramp top de-whitened:** 0.75 E8DFD2→DCC9B2, 1.0 F6F1E8→E9DCC8. Pale-peaks tinting was the snow *proxy*; with real snow it double-signals and misfires exactly where high ≠ snowy (Ladakh/W Tibet rendered cream-white). India A/B: "warm" makes the tri-partition legible (warm rock / cool snow / teal water); "cap" (flatten to E8DFD2) too timid; Switzerland unaffected (needs 4,500 m to reach the zone). Affects the India/Nepal/Andes class; Everest clamps at the recolored stop.
- **Verification:** pre-adoption India regression zero-diff (snow branch inert without mask); post-adoption dump-diff exactly the intended change set (ramp stops + evaluation, Snow mix splice, fill light, sun angle — nothing else); scene_dump now prints use_shadow. Confirmed at 8K: swiss_hero_8k_v2 + india_hero_8k_v4 (supersede swiss_hero_1s / india v3 as look references; pinned frame.json values untouched — geometry unchanged). Canonical homes after the same-day renders cleanup: renders/heroes/switzerland.png + heroes/india.png, scenes switzerland_hero.blend + india_hero.blend; superseded arms in renders/archive/, prototype blends pruned, hand-built Phase 0 scene kept as india_hero_handbuilt_phase0.blend (only non-regenerable artifact).
- **Infra:** pipeline/snow_mask.py promoted from experiments (runs after render_prep): 6-worker downloads, 404 = legitimate ocean cell, all-absent = naming-drift abort, atomic .part; pin is the versioned v200/2021 URL path (multipart ETags — no md5 oracle, size checks only). Cache data/raw/worldcover ≈ 9.8 GB (146 tiles), shared across countries. Reopen only if prototype-scale seasonal contamination appears (then: DLR SnowPack duration ∩ class 70).

### 2026-07-08 (night) — Switzerland QA: 1″ is the small-country standard; warp width ≈ render width is the anti-bump guard; resolution bumping rejected for heroes

- Three-arm A/B on the finest hero yet (51 m/px; frame 5.7–10.7°E / 45.5–48.1°N, both arms warped to the same 8192-px / 48 m grid): 3″ reads soft (its 6120-px source is *undersampled*), 1″ reads crisp — sharper crests, cirques, gullies — with only faint orange-peel in the low-relief Mittelland. Huffman-style bumpiness did not appear.
- Why: the warp grid is the low-pass. Bumpiness needs the displacement texture to out-resolve the render; at texture ≈ render width, 1-px dicing cannot resurrect what the warp already removed. **Rule codified: warp --width ≈ render width (7680) and ≤ source width; 1″ fusion for countries whose 3″ source falls under the render width.** (docs/framing-math.md updated.)
- Third arm (experiments/resolution_bump.py: σ=3 px low-pass + 10% detail, Patterson's recipe) lost decisively — smeared landforms, fattened crests, even rounded the Lake Geneva shoreline (smoothing bleeds lake plates). Bumping treats texture-out-resolves-display; our width rule prevents that condition, so for heroes it only destroys signal. It stays shelved for Phase 2 tiles, where high zooms genuinely out-resolve the display.
- First out-of-extent data expansion, infrastructure now honest: download_glo30.py takes --extent + runs the ETag preflight automatically (first live pass: 3 held tiles matched — bucket unmoved); the formerly unscripted VRT rebuild is pipeline/build_mosaics.sh (system gdalbuildvrt; nodata fills match fuse's constants); post-rebuild India oracle byte-identical (196.24 m @ 77.5E/28.5N); fusion class counts: ocean 0.00% in the landlocked frame, identical lake/river fractions across 3″/1″.
- Memory data point: 7680×5738 renders peak at ~11.4 GB host RSS (dicing-dominated, not texture) in ~3.5 min; "free" undercounts headroom — check `available` (reclaimable page cache).

### 2026-07-08 (late) — Pyright adopted as the CLI type-check oracle; pipeline clean

- `uv run pyright` (dev dependency group; [tool.pyright] in pyproject.toml) runs the same engine as Pylance, so IDE findings are reproducible at the terminal and in CI; experiments/ excluded as archival one-offs.
- Triage of the initial 38 errors: the pyshp Optional/union findings were *valid* (the shapefile spec allows null shapes; DBF fields can be non-str) — None-guards added in frame_country + overlay's read_lines, ADMIN coerced via str(). rasterio and affine ship no py.typed, so Window(...) calls and Affine attribute access are checker inference gaps on correct code — suppressed with scoped pragmas naming the reason. bpy imports pragma'd (exists only in Blender's interpreter).
- The regeneration diff-oracle caught a real wrinkle: frame.json's dst_crs spelling differed between the --frame branch (pretty aea_crs string) and the from-file branch (PROJ-normalized) — render_prep now normalizes both; Nepal/Sri Lanka frame.json regenerated, India's pin re-spelled to match, Sri Lanka oracle re-run byte-identical (97.8%).

### 2026-07-08 (evening) — Per-country framing live: frame.json is the contract; India pinned; oracle re-based to meters

- Chain complete and proven twice end-to-end: frame_country.py (NE bbox + 5%-of-larger-span pad, rounded outward to 0.1°) → render_prep --frame (Albers per the ⅙ rule, emits frame.json with plane/ortho/displacement/resolution) → scene_build/overlay_borders consume frame.json. All derivations in docs/framing-math.md; India constants deleted from every script.
- frame.json doubles as the override mechanism: hand-authored files are never overwritten. India's is hand-authored with the v3 hand-rounded values (decided with Rohan: v3 stays canonical; derived exacts differ ≤0.15%). Regression: render_prep on the India dir is a zero-write no-op, and the scene built from the pinned file dump-diffs to zero against india_hero_scripted.blend; the resolution formula reproduces 7680×7906 exactly.
- Nepal (wide frame, landlocked) = first fully scripted hero, 4:34 @ 7680×4787; exposed that oceanmask_aea.png had been hand-made for India and scripted nowhere — render_prep now emits it (0/255, same class-PNG path as lake/river). Sri Lanka (tall frame) proved the orientation flip and the coastline oracle.
- Oracle lesson: fixed pixel tolerances silently change meaning per country (5 px = 2.4 km on India's render, 650 m on Sri Lanka's) — Sri Lanka "failed" at 65% within 5 px while perfectly aligned. Measured signed offsets (west −5±16 px, east +10±8 px, opposite signs, high variance) = NE 1:10m vs WBM product disagreement around lagoon spits, not mapping error; India re-scored 91.1% on the same code. coast_agreement re-based to ground meters (600/1200/2500, bar ≥90% @ 2500 m): India 91.1%, Sri Lanka 97.8%.
- Fixed-width resolution rule strains on tall countries (Sri Lanka wants 7680×12498) — the per-country config item inherits the cap decision. scene_build gained --render and --render-scale (scripted version of the 2048-wide test convention).
- Cosmetic debt noted: numpy 2.5 DeprecationWarnings in rasterio reads, and Blender 6.0 will remove Material.use_nodes — both harmless today.

### 2026-07-08 — Raster source provenance audited: GEBCO self-pinned; GLO-30 unversioned bucket gets an ETag oracle

- GEBCO: filenames carry release + extent (gebco_2026_* + TID twin) — self-documenting, nothing to fix. The full-globe grid for Phase 2 will be a separate deliberate download of the same release.
- GLO-30: the AWS bucket (copernicus-dem-30m) has no edition in any path, so a future fetch could silently mix Copernicus DEM editions across tiles. Checked tiles are Last-Modified 2022-05-09 — the bucket has been frozen for 4 years, so current holdings are edition-coherent.
- Standing oracle (validated on N28/E077: local md5 == bucket ETag): before any future download_glo30 run, HEAD a few held tiles and compare ETag to local md5 — a mismatch means the bucket moved; stop and decide the edition question deliberately.
- Completeness verified 2026-07-08: 979/979 DEM + 979/979 WBM tiles for the 60–100°E / 0–40°N extent, none missing, none outside the extent, no failures.txt, no stray .part files.

### 2026-07-08 — Natural Earth 6.0 draft: not adopted; disk verified as 5.1.2; download script pinned

- Trigger: shadedrelief.com/ne-draft/ surfaced as "Blue Earth 6.0" — it's actually the Natural Earth 6.0 preliminary (Blue Earth is at 2.0, entry below); first major NE release since 5.1.2 (2022), explicitly a work in progress soliciting error reports.
- Rasters irrelevant: land rasters are replaced by our own Copernicus renders, and the 6.0 ocean-bottom raster is the same 21,600×10,800 / 60″ grid as Blue Earth 2.0 (its NE packaging) — rejected per the entry below.
- Vector draft not adopted: borders are the stability-critical layer (worldview policy, disputed segments, bbox-derived camera frames); draft→final polygon shifts would orphan any hero rendered against draft geometry.
- Skew false alarm (corrected same day): layers first looked version-mixed (coastline 5.0.0-pre9, countries 5.1.1), but VERSION.txt is per-layer — it records when that layer last changed, not which release it shipped in; repo tag v5.1.2 carries the identical values. Content oracle: every on-disk layer sha256-matches the tag on .shp/.shx/.dbf; text components identical modulo line endings. Disk is 5.1.2; no re-download needed.
- Real gap fixed instead: download_naturalearth.sh fetched unversioned naciscdn "latest" (a fresh machine running it after 6.0 finals would silently get 6.0) and omitted disputed_areas — repointed to per-file raw downloads from the pinned GitHub tag (nvkelso/natural-earth-vector @ v5.1.2), disputed_areas added to its layer list, upgrade = deliberate one-line TAG bump. Fetch path proven by re-fetching disputed_areas: binaries identical to the naciscdn original, second run a clean no-op. countries_ind (India-POV variant, unused — worldview is NE default) stays out of the script; verified unreferenced repo-wide and deleted from disk 2026-07-08.
- Reopen when 6.0 goes final: deliberate one-time migration — re-download, bbox-diff all country frames, re-check disputed-segment styling. Check its release timing before Phase 2 mass production; worst case is 6.0 finalizing right after a 200-country render pass against 5.x.

### 2026-07-07 (night) — Blue Earth Bathymetry 2.0: considered, not adopted; shelved as tile-artifact remedy

- Trigger: Patterson released v2.0 on 2026-07-06; the project had cited Blue Earth only as aesthetic prior art (CLAUDE.md reference list) and never evaluated it as a bathymetry source — this entry closes that gap.
- Rejected as primary source: it's a 60″ global grid (21,600×10,800) — 4× coarser than GEBCO 15″, and our heroes sample at ~229 m/px (z8 at 306 m/px) where GEBCO is already the limiting layer; shelf detail (the signature look) would upsample ~8× into mush. It also ships no TID provenance channel (the Khambhat diagnosis depends on one), and v2.0's deep basins are BathDNN25 (neural-net-predicted) selectively composited with GEBCO plus manual edits of "suspiciously unnatural" ridges — curated for looks, a step further from auditable truth than GEBCO's gravity model.
- Shelved as the ocean analogue of Patterson resolution bumping: if the tile-shading open question resolves badly (GEBCO survey noise / provenance edges pop at low zooms), Blue Earth 2.0 is purpose-built to clean exactly those artifacts and its native resolution is adequate through ~z5 (1.85 km/px at the equator, vs z5 tiles at 2.45 km/px) — use it there, or replicate its selective-compositing recipe on our own GEBCO to keep one source family.

### 2026-07-07 (night) — Dead render blobs rewritten out of history

- Two 2K PNGs (15 MB) existed only in history (added f6e9647, deleted 6afead7). With no remote yet the rewrite was free: soft-reset to 5b18632, both commits recreated as one, stale water-mask branch / ORIG_HEAD / reflog cleared, gc'd. Repo 15.39 MiB → 323 KiB; the blob-scan oracle returns empty.
- `blender/*.png` added to .gitignore as a tripwire. After the first push this class of rewrite is gone for good — done now deliberately.

### 2026-07-07 (night) — Python packaging: pyproject.toml + uv, manifest-only

- Premise: the venv was the only record of dependencies — unreconstructible after loss.
- pyproject.toml declares the six direct deps with `[tool.uv] package = false` (scripts, not an installable library). Committed uv.lock pins the full tree to the validated environment (numpy held at 2.5.0 after the resolver wanted 2.5.1) — upgrades happen via `uv lock --upgrade`, never incidentally.
- Python pinned two ways: `requires-python = ">=3.12"` is the compatibility floor; `.python-version` (3.12) is what uv provisions and runs. The bpy scripts run on Blender's bundled 3.13.9, outside all of this — shared code must stay compatible with both interpreters.
- Verified by syncing the lock into a throwaway env: package set identical to the live venv, all six imports OK (rasterio wheels bundle GDAL 3.12.1). The live .venv is now lock-managed (`uv sync`; pip survives as a seed package).
- Deferred on purpose: package structure (src layout, shared modules, entry points) waits until per-country generalization reveals the real seams.

### 2026-07-07 (evening) — Phase 1 keystone: scene_build.py rebuilds the hand-built scene from code

- Verified by three oracles, strongest last: structural (pipeline/scene_dump.py, order-normalized, ramp stops included), ramp-function (cr.evaluate() sampled at 10 positions per ramp), pixel (2K renders: max |diff| = 2/255, 0.0000% of samples differ by > 1 — denoiser noise).
- Bug 1, bpy ColorRamp: elements.new() and position writes re-sort the collection and invalidate held element references — colors land on wrong stops, and a surviving default white stop painted the shelf seas white. Fix: shrink to one element, append stops in ascending order, color each via the reference .new() returns. (How-to also in CLAUDE.md.)
- Bug 2, blind oracle: the first structural diff passed on the broken scene — its grep filter for object `loc=` lines also deleted every material-node line, exactly where the bug was; the pixel diff caught what the filtered diff blessed. Lesson, now encoded in scene_dump.py: a check must be shown to FAIL on a known-bad input before its pass means anything.
- Loose end: the hand-built plane height 2.058 is rounded (exact raster aspect 2.0588); switching to exact is a per-country-generalization decision, expected to *improve* coastline registration by ~1.6 px N-S.
- Notes: scene_build takes explicit numbers via CLI — all geo math stays outside Blender (bundled Python has no GDAL); it clears the scene, not factory settings, so user prefs (OptiX) survive.

### 2026-07-07 (later) — Lake depth: flat stays

- The v2 distance-transform prototype (shore anchored at the flat teal, size-attenuated contrast) proved intra-lake gradients read at hero scale and arguably beat flat on looks — rejected regardless: geometry-only depth is an artificial gradient, epistemically worse than honest flat and blind on deep lakes. Parked in pipeline/experiments/lake_depth_prototype.py.
- Reopening bar: real modeled data — GLOBathy or better (costs bulk acquisition + HydroLAKES→WBM shoreline re-registration; MERIT Hydro is river flow/width, not depth). Implementation choice then: post-tint stage vs fusion depth channel + shader ramp.
- Constraints if reopened: tint-only, never carve displacement (at 15× Namtso becomes a 1.5 km crater and the shadow-catching plate dies); needs a per-lake depth channel + its own shallow ramp cap (lakes sit above sea level, mostly < 50 m — the sea ramp can't see them).
- River depth rejected outright: no real global bed data exists (SWOT measures the water surface), and 5–15 m river depths are one ramp tone anyway.

### 2026-07-07 — Inland water: full Route A (raster, in-scene); headless rendering becomes standard

- Verdict: lakes AND rivers painted from the WBM in the material; vector hydro rejected, hybrid explicitly declined — truth over pop. Trigger: the approved 8K had no inland water (the fusion ocean rule absorbs only sea-level water, by design).
- Build: fusion emits a 4-class watermask (0 land / 1 ocean / 2 lake / 3 river; class 1 verified pixel-identical to the ocean mask over all 1.6 Gpx; `--watermask-only` backfills without recomputing); render_prep warps it onto the existing AEA grid and splits 0/255 lake/river PNGs; the shader gains Lake/River Mix switches fed by one RGB node — the tuning lever, documented in ART.md (gotcha: the GUI hex field converts sRGB→linear silently; raw bpy values would not).
- Deciding evidence (Tibet): the WBM carries 3,358 plateau lakes in one 8°×4° window (1,849 survive at hero 229 m/px, 1,381 at z8; everything ≥ 0.5 km² survives at all scales) vs ~10 generalized NE polygons whose outlines visibly contradict the DEM's own basins.
- Rivers: NE centerlines are more legible but are synthesized courses that drift off the braid plains and miss reservoirs; raster rivers render as a pale broken trace (nearest sampling preserves water *area*, not *continuity*) — they stay raster and faint. `--mode hydro` stays in overlay_borders.py as a documented rejected experiment. NE hydro quirks: the current 10m rivers file has no strokeweig, and its DBF fields are lowercase (unlike the boundary files).
- Flatness is ground truth: GLO-30 hydro-flattens water surfaces (Namtso: one plate at 4,725 m; the Ganges: 82→38 m in steps over 83–85.5°E). The *ocean* is the stylized element — bathymetric tint renders seafloor, not surface.
- Ops finding: the GUI 8K render OOMed at 18.4 GB host RSS (kernel oom-kill took the desktop down; unsaved node work lost, rebuilt). The identical render headless: 3 min 36 s, 12.3 GB host peak. `blender -b` is the standard render path from now on.

### 2026-07-06 (late) — Khambhat seam: data-provenance edge, no smoothing

- TID probe: the straight offshore seam is rectangular blocks of TID 16 "optical" (satellite-derived bathymetry, scene-shaped) meeting TID 40 gravity-predicted fill; ENC soundings sprinkle the gulf itself. Extent-wide ocean mix: 83.3% gravity-predicted / 13.0% multibeam / 2.3% optical / 1.2% gravity-guided soundings. Straight edges recur wherever optical blocks exist (shallow coastal water).
- Decision: no smoothing — nobody noticed it on the approved v2 8K. Spot-check the seam zone (72.3–72.6°E, 21.0–21.8°N, offshore Saurashtra) once by eye; reopen only if Phase-2 tile shading makes provenance edges pop.

### 2026-07-06 (evening) — Overlay pipeline live; alignment oracle passed

- Coastline oracle: 74.5 / 91.1 / 93.8 % of drawn NE coastline within 2 / 5 / 10 px of the ocean-mask boundary at 8K, no directional bias in crops — the AEA→pixel mapping (including the ~2 px ortho-margin correction) is confirmed. Residual disagreement is NE 1:10m generalization vs our 30 m coast (Khambhat tidal flats, as predicted at design time).
- First composite: 59 solid / 17 dashed / 14 maritime features in frame; the standalone transparent border layer is emitted alongside (the gallery-toggle asset).
- Aesthetics left open: white-on-bone contrast over high pale terrain (halo/casing is the designated lever); maritime dash visibility to be judged on the 8K; borders drawing over the flat no-data collar at the frame corners — really a Phase-1 framing/collar decision, not a borders bug.

### 2026-07-06 — Border overlay designed; worldview: NE default (de-facto), site-wide

- One editorial stance for all heroes (Kashmir must not change shape between the India and Pakistan pages); disputed/LoC segments dashed; policy noted on the About page. NE ships 31 national POV variants for the country *polygons* only — boundary *lines* exist in the default worldview alone (a POV would be a filtering transform we'd own).
- Rendering route: composite in post (pipeline/overlay_borders.py). With a straight-down ortho camera, draped-3D and flat-2D lines project to identical pixels (no parallax, no overhangs), so the in-scene route buys nothing; evaluated fully anyway (BlenderGIS + Grease Pencil Dot Dash / Freestyle / GN dashing are all real) and rejected on iteration cost (re-render vs recomposite), GUI-add-on dependency in the headless Phase-1 batch, Freestyle perf vs diced terrain — and the frontend needs a standalone transparent border layer anyway, which the compositor emits as a byproduct (gallery toggle = stacked <img>; globe tiers toggle their MapLibre vector layer for free).
- Alignment oracle defined: NE coastline rasterized onto the render grid must hug the land/sea color boundary (checks systematic offset; NE 1:10m is more generalized than our 30 m coast, so local disagreement is expected and fine).
- Styling classes from the DBF (uppercase `FEATURECLA` in this NE release — don't filter on lowercase): solid white = "International boundary (verify)"; dashed = Disputed / Line of control / Indefinite / Indeterminant frontier; maritime indicators all dashed per the reference look.
- Stack (versions verified current on PyPI 2026-07-06): pyshp + pyproj + pycairo — read/reproject/draw needs no geometric ops, so geopandas/shapely would be dead weight; fiona unmaintained since 2024-09 (pyogrio succeeded it); cairo has native dashes/AA/RGBA. pycairo builds from sdist: needs system libcairo2-dev + pkg-config. Data from naciscdn.org via pipeline/download_naturalearth.sh: boundary_lines_land, maritime_indicator, countries (Phase-1 camera bboxes), coastline (oracle).

### 2026-07-06 — First 8K hero approved; CPU-denoise rule; Blender 5.2 plan

- 7680×7906 completed at 1 px dicing, 6.8 GB VRAM peak; approved on desktop and phone (phone softening = display downscaling, not a defect). Claude's prediction that 1 px geometry wouldn't fit was wrong (per-quad memory overestimated; Max Subdivisions also caps effective dicing) — trust the empirical peak, not the estimate.
- The morning's Xid 31 MMU fault re-attributed, low confidence, to GPU render + GPU OIDN denoise VRAM contention at 8K (known pattern, blender/blender#119035; the failed attempt had GPU denoise on, the success had it off) → rule: denoise on CPU for 8K frames. OIDN over the OptiX denoiser for final stills (detail preservation; OptiX is a viewport tool).
- GPU debug recipe: OPTIX_ERROR_UNKNOWN at context creation right after a failed render → check `journalctl -k` for NVRM Xid lines; if the Xid pid is Blender, the driver is fine — restart Blender to clear the dead CUDA context.
- Version plan: finish Phase 0 and the Phase 1 bpy script on 5.1.2; pin 5.2 LTS (releases 2026-07-14) once out — its Cycles texture cache (`--command maketx`) and geometry-memory reduction target exactly our batch workload, and our API surface is untouched by its breaking changes (Geometry Nodes/paint APIs only). Verify the switch with an A/B render against a 5.1.2 reference before trusting it.

### 2026-07-05 — Tuning session → v2 look (supersedes v1)

- View transform **Standard**, locked — AgX's highlight desaturation greyed the palette; a map has no speculars, so filmic compression buys nothing.
- Exaggeration 15× paired with sun altitude 46° — pairing math: shadow length ∝ height × cot(altitude), so cot(new) = cot(old) ÷ exaggeration ratio holds drama constant while adding lowland micro-relief. Sun angle 5° (3° vs 5° invisible at 2K — penumbra sub-pixel at test res; re-judged at 8K).
- World fill F2E7D5 @ strength 0.3 (was default dark grey) — lifts shadow cores to warm brown, tints the backdrop paper-bone; the raytraced analogue of Phase-2's sky-view factor.
- Land ramp rebuilt around cap 6,000 m: rose peaks ~1,500 m then rises to bone/near-white (the Ramspott pale-highlands move); C68A76 retired as too heavy. Sea ramp audited, unchanged from v1. Full stops live in "Locked global constants" above.

### 2026-07-05 — v1 look baseline (superseded by v2)

- Pre-tuning constants, kept as the tuning baseline: 10× (Scale 5.3e-6), sun (55°, 0°, −45°) @ angle 3°, land ramp cap 2,000 m ending in C68A76, view transform AgX. Reference renders: blender/renders/india_look_v1.png (canonical) and *_check.png (accidental sun-angle drift — instructive soft-shadow example, kept).

### 2026-07-05 — First full-look render (india_hero.blend)

- Scene recipe: plane scaled to raster aspect, Simple subdivision + adaptive dicing, Float32 heightfield (Non-Color) driving Displacement, sun lamp, ortho camera from above, two ColorRamps switched by the ocean mask via Mix. (Now reproduced in code by pipeline/scene_build.py.)
- Hard-won lessons for the bpy era: (a) Blender divides 8-bit images by 255 — masks must be exported 0/255, Float32 passes raw; (b) image nodes Non-Color, mask interpolation Closest; (c) Map Range with any reversed range is undefined territory in 5.1.2 — use forward ranges or Math Multiply+Clamp; (d) ColorRamp stops re-sort by position and renumber — never identify a stop by index (the final bug was a hidden 5th pale stop that four index-walking verifications missed).
- Debug toolkit proven: binary mask test, independent numpy albedo oracle, base-resolution ASCII map, revert-to-baseline + minimal diff.

### 2026-07-04 — Render projection: Albers equal-area conic

- India frame: `+proj=aea +lat_1=10 +lat_2=32 +lat_0=21 +lon_0=82.5`. Geographic degrees are E-W stretched (~5% at 21°N mid-frame, varying N-S); a conic with standard parallels ⅙ in from the frame's latitude edges keeps scale near-uniform, so displaced terrain isn't anisotropically distorted. Phase 1 derives per-country params the same way (pipeline/render_prep.py). Heights stay in meters; exaggeration is a Blender-side constant.

### 2026-07-04 — Fusion rule refined after full-frame spot checks

- Rule: ocean = WBM class 1 ∪ no-coverage ∪ (class 2/3 with |elev| ≤ 1 m); never convert dry land; high-altitude lakes unaffected. Context: WBM classifies coastal lagoons and tidal channels as lake/river (~2,200 km² of sea-level "lakes" + ~8,000 km² of sea-level "rivers" in the India frame — Chilika, Kerala backwaters, Sundarbans).
- Spot-check oracles for any future fusion run: Delhi ~214 m, Everest ~8.7 km (3″ averaging shaves the true 8,849 m peak), open Arabian Sea deeply negative, Chilika lagoon ≤ −1 m with mask = 1.
- Caveat learned the hard way: verify anomalies at the data's own pixel scale before calling them bugs — 79.7°E 9.5°N reads +0.6 m/land *correctly* (ESA maps an emergent tidal flat there; the water starts one pixel west).

### 2026-07-04 — Khambhat fusion experiment: hard splice, −1 m ocean clamp, no feathering

- Run on the adversarial macro-tidal case (pipeline/experiments/fuse_khambhat.py; confirmed by the two-ramp color test, color_khambhat.py — naive fusion renders phantom sand-colored land inside the gulf, the clamp eliminates it).
- Decisions: sea = WBM ocean class only (lakes/rivers keep the land surface — their water *tint* is a material decision, not a fusion decision); hard splice with ocean clamped ≤ −1 m; feathering rejected — no visible seam in multidirectional hillshade even here.
- Key learning: naive fusion's failure mode is *coloring*, not shading — 3.2% of ocean pixels resolve ≥ 0 m (up to +18 m) and would key off the wrong end of a depth ramp. The clamp also makes sign-of-elevation a valid sea/land key downstream (caveat: rare below-sea-level land like Kuttanad mis-keys; the mask COG stays ground truth).
- Side find: a dead-straight GEBCO source boundary offshore W Khambhat — diagnosed 2026-07-06 via TID (see above).

### 2026-07-04 — Fusion reframed after prior-art check

- Land/sea DEM fusion is a solved problem (ETOPO 2022 is the finished 15″ product; grdblend the standard tool; cartographers do this routinely). We proceed with our own fusion anyway — justified by 1″ land detail for small countries and z9–z10 tiles, plus learning value — treated as method selection, with ETOPO 2022 as an external validation oracle. Noted honestly: for a ship-it project, "use ETOPO 2022" would be the right call at hero scale (~370 m/px for India-sized framing).

### 2026-07-04 — Phase 0 data acquired

- Extent locked 60–100°E / 0–40°N (979 GLO-30 tiles, half-open east/north edges); GEBCO_2026 (April 2026 release) chosen over 2025; water-body masks (WBM) downloaded alongside DEMs as a candidate coastline source.
- The downloader's stdlib-only .part → verify → atomic-rename pattern is the template for all later pipeline stages. Git initialized (code only; data/ ignored).

### 2026-07-04 — Purpose reframed: learning first

- Understanding every piece is the primary goal; the shipped site is secondary. Claude acts as guide, not workhorse; the plan is expected to change significantly as understanding surfaces. (Charter recorded in CLAUDE.md.)

### 2026-07-03 — Project scoped; dev environment decided

- Scoped in a claude.ai conversation; architecture, data sources, and rendering approach locked into CLAUDE.md. Phase 0 target: India.
- All work in the Ubuntu boot of the dual-boot desktop (Blender + pipeline on one ext4 filesystem, native OptiX); Windows boot and WSL ruled out. Rohome remains deploy target and production runner for the tile pipeline. Constraint: overnight GPU renders occupy the desktop (no gaming those nights).
