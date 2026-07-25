# Terrella — living plan

Status legend: [ ] todo · [~] in progress · [x] done · [!] blocked

Update at the end of every work session (checkboxes + open questions + active learnings). One-line summaries only — anything needing a paragraph lives in [`HISTORY.md`](HISTORY.md) (dated decisions + rationale; grep it, scan its topical index), [`PROCESS.md`](PROCESS.md) (measured runtimes), [`INVENTORY.md`](INVENTORY.md) (storage), or [`ART.md`](ART.md) (aesthetic decisions), cited as `→ HISTORY § <dated heading>`. Deferred-but-analysed ideas live in [`FUTURE.md`](FUTURE.md) (the v2 parking lot), not here.

## Phase 0 — Proof of concept (one country, end to end) — COMPLETE 2026-07-06

Goal: a single Ramspott-style render of **India** that looks right, before building anything global.

- [x] GLO-30 tiles for India + margin (979 tiles, 34 GB) — `download_glo30.py`
- [x] GEBCO bathymetry subset for the same extent
- [x] Land + bathymetry fused into one seamless 3″ heightfield — `fuse_heightfield.py` (recipe + oracles → HISTORY)
- [x] Manual Blender scene: displacement plane, sun lamp, two-ramp material, ortho camera (`blender/india_hero.blend`)
- [x] Lighting/palette/exaggeration tuned to the reference aesthetic (→ HISTORY § 2026-07-05; constants below)
- [x] Natural Earth border overlay + dashed maritime lines — `overlay_borders.py`, oracle-verified alignment
- [x] 8K still reviewed on desktop and phone
- [x] **Checkpoint: scene rig locked as global constants** (→ "Locked global constants" below)

## Phase 1 — Batch hero renders (all countries) — COMPLETE 2026-07-13

All ~203 in-scope heroes rendered (Kiribati deferred), variants/borders/manifest current. Detail per line → HISTORY; reproducible entry point `README.md` → `docs/pipeline.md`.

- [x] bpy scene script — `render_prep --frame` → `frame.json` → `scene_build --render`, headless (3:36 @ 8K)
- [x] Per-country config — `config/countries.toml` (204 heroes), `country_config.py` resolver
- [x] Per-frame displacement Scale — the locked 15× is *physical* (`docs/framing-math.md`)
- [x] Small rugged countries QA — 1″ fusion is the small-country standard
- [x] Snow/ice as a data mask + shadow legibility (fill sun, land-ramp top de-whitened)
- [x] Antimeridian countries — frame overrides (4 of 5 have land on one side of 180)
- [x] Batch runner — `pipeline/batch.py`: resumable, subprocess-isolated, OOM defense, JSONL failure log
- [x] Hero regeneration documented — `docs/pipeline.md` (the runbook)
- [x] Overnight sweep + QA — closed Phase 1
- [x] Responsive variants (2K/4K/8K WebP) — `hero_variants.py`, ≈16× smaller than PNG

## Phase 2 — Global tile pyramid — COMPLETE 2026-07-23 (successor work → Phase 5)

Scoped 2026-07-10 (→ HISTORY § 2026-07-10): ceiling z8 (~300 m/px), GDAL 3.13.1 pinned for production (OSGeo container; apt's 3.12.2 fine for prototyping), one new dependency (`pmtiles` CLI), SVF via our own `sky_view.py`, WhiteboxTools dropped.

- [x] Toolchain locked — `pmtiles` 1.31.0 vendored via `install_geotools.sh`
- [x] Planet fused heightfield — `fuse_planet.py`, 648 cells @ 10″, 0 failures; Antarctica fused 2026-07-22
- [x] Raster shading — ONE global streaming pass (`shade_planet.py`; supersedes the 194-strip pass)
- [x] Tiles vs Cycles compared — the composite reproduces the hero family (single-NW; multidirectional rejected)
- [x] Global snow — NSIDC-0791 persistence (latitude-ramped) + RGI 7.0 glacier union
- [x] 512px tiles z0–8 cut — 62,177 tiles live (z10 later = a re-fuse at ~2.5″, never a tiling flag)
- [x] Caspian bathymetry — re-fused via `is_caspian`; flat slab → shaded basin (luminance spread 0 → 30.8) → HISTORY § 2026-07-15 — Inland water
- [x] GLOBathy lake depth — a **render layer, not a fusion channel** (tint-only, CC0, z10-proof) → HISTORY § 2026-07-15 — GLOBathy lake depth
- [x] THE TILE CUT — 3:44 measured; the "30–60 min" it carried was a guess wrong ~10× → HISTORY § THE TILE CUT LANDED · PROCESS
- [x] Every pass stage freshness-guarded — `is_stale` everywhere, SVF gated by *laziness* (fresh pass 153.5 → 0.29 s), `tiles.done` sentinel (re-cut 3:33 → 0.4 s); `--resume` deleted as unsafe → HISTORY § THE TILE CUT LANDED · § 2026-07-20 pipeline hardening
- [x] Fill sun ported to the tiles — `fill_strength=0.15` + `hi` 1.12; pure-black mountain land 43.66% → 0.00% → HISTORY § the tiles were missing the hero's fill sun · ART § Fill sun — TILES
- [x] On-globe judgment — z8 not coarse on the sphere → **ceiling LOCKED**; judge look changes on `/globe`, never `planet_tiles/index.html` (a tile smoke test) → HISTORY § z8 LOCKED
- [x] Greenland interior — `snow_curve=gamma8` (Summit 3.14 → 18.84 DN); over full snow the blend discards hillshade+SVF and no linear window fixes a 17× nested range mismatch → HISTORY § 2026-07-17 Greenland · ART § Snow curve — TILES
- [x] Antarctica — FILL chosen: pyramid extended to −85.05° (1.41× every planet raster), planet re-fused −90…90, polar ring root-caused as a premultiplied-alpha blend bug (screen, not data), judgment complete 2026-07-22; RGI-19 deferred (`antarctic_snow_mask`), SVF normalisation proven safe → HISTORY § 2026-07-22 Antarctica FILL
- [x] Hero-"softness" port CLOSED — `ambient_knee` 0.30 + `shadow_warmth` 0.55 SHIPPED (Rohan, `/globe`, 2026-07-21); cast shadows rejected twice (the *mechanism* erases fine modeling — reopen needs a new mechanism, not a new value); hillshade-side lever dropped (every dial is a hero anchor) → HISTORY § 2026-07-21 entries · ART § Hero → tile parameter map
- [x] Package as PMTiles — DONE 2026-07-23: `pack_pmtiles.py` (dir→MBTiles 33 s, TDD) → capped convert 1m11s → 15 GB `planet.pmtiles` (verify clean, byte-compare incl. z8 y=255, 5.3% deduped); `?pmtiles` flag on /globe (pmtiles 4.4.1, header-derived min/maxzoom, TDD'd Range dev route) visually verified live (→ HISTORY § the uncapped pmtiles convert); default-on flip + nginx serving ride Phase 4 deploy — flip evidence from the phone-lag diagnosis: on the SAME desktop, first idle ≈ 4.4 s via the loose-tile dev path vs ≈ 1.3 s via `?pmtiles` (main thread clean both ways), so the flip also fixes the default dev experience, not just prod packaging

## Pipeline optimisation — measured 2026-07-16, now mostly landed

Baseline: 98 min wall on 1.16 of 16 cores; every item measured before proposed (three "obvious flag" fixes died on a profiler) → HISTORY § the instrumented planet pass. Pays on every future shade pass — the composite alone was ~71% of a pass — not on the tile cut.

1. [x] Hillshade float32 + 256-row windows — 932 → 508 s, 11.6 → 2.03 GB → HISTORY § optimisation #1
2. [x] color-relief stage deleted — 24.4% of pass CPU became a 17.6 KB LUT → HISTORY § optimisation #2
3. [x] `num_threads=ALL_CPUS` on the three tile writers — 10× on the writer → HISTORY § optimisation #3
4. [x] Snow + glaciers warped ONCE, in latitude bands (a whole-grid warp DECIMATES a coarse source) → HISTORY § snow warped ONCE
5. [x] Composite threaded — 128/N4, ~3.5×, threaded==serial gated byte-identical → HISTORY § the composite is threaded
6. [ ] `-srcnodata`→0-fill on GLOBathy — 51% of the 62-min lake warp; pays only on a re-extract
7. [x] Prep-walk redundancy cut (2026-07-23) — mosaic freshness skip + 24 h preflight stamp; 35 s → 1.25 s/country → HISTORY § the prep-walk redundancy cut · PROCESS
8. [x] **Commonification DONE 2026-07-23** — `pipeline/raster_io.py`: `GTIFF_CREATE` (format-only; threading stays per-call-site or it oversubscribes fusion — now enforced by test) + `row_bands`/`band_window` adopted at six sites; `warp_once`-behind-`is_stale` found already superseded by `warp_needs_rebuild` (2026-07-22), `lake_ab --left/--right` found already done → HISTORY § commonification LANDED

- Experiments audit (2026-07-16): `sea_ab.py` + `ab_crops.py` retired; a *working* experiment is the record of a decision → HISTORY § 2026-07-16
- `composite_ram.py` measures `composite()` alone — a lower bound, not the pass; the 12 G cap = 1.9× the real peak → HISTORY § composite_ram.py was never the number
- Code in `pipeline/`, output in `data/` — `data/` is gitignored; harnesses live in `pipeline/profile/`, never `data/work/`
- Test coverage measured on demand (2026-07-23): `uv run pytest --cov`, baseline 32.45%, `fail_under=32` as a ratchet; covered = the compute kernels, 0% = network/GPU orchestration → HISTORY § commonification LANDED

## Phase 3 — Frontend

Tiers 1 + 2 shipped on `feat/frontend` (worktree `../maps-frontend`; merge later): Astro 7 static site — gallery + detail + About + `/globe`, capability probe auto-steering. Tier 3's 3D displacement → Phase 5. → HISTORY § 2026-07-10 — Phase 3 begins; asset commands → `docs/pipeline.md`; deploy is Phase 4.

Baked-vs-live rule (locked 2026-07-07): too expensive live → baked; depends on view state → live; invariant + physics-coupled → baked; otherwise live pinned to authored constants; user-exposed settings only where visitor context genuinely varies.

- [x] MapLibre globe over the raster pyramid (PMTiles source deferred to Phase 4)
- [x] NE vector borders + toggle — casing strengthened to a soft dark halo for pale highlands
- [x] Country click → fly-to → in-globe hero panel (NE hit layer, authored-frame `fitBounds`, lazy panel)
- [x] Hover-highlight pole artifacts fixed — `lib/countryHighlight.ts` + 11 regression tests; Rohan confirmed no look regression → HISTORY § 2026-07-19 hover-highlight
- [x] Blocky coasts at z6–8 FIXED 2026-07-23 — both suspects were innocent: the hover outline strokes `countries.geojson`, which was simplified at 0.05° (~5.5 km) for its original life as an invisible hit layer; retightened to 0.002° (sub-pixel at z8), guard test pins it against `Z8_RES` → HISTORY § the blocky hover outline
- [x] Globe polish — starfield, mobile control fixes, sea rework V1 LIVE, Spin toggle
- [x] Capability probe + tier routing + Lite/Globe/Full toggle + FPS degradation — `decideTier()`, WebGL2 hard floor, TDD'd
- [x] Tier 1 no-JS fallback — pure-CSS gazetteer overlay; dead search removed
- [x] **Hero sea-sync sweep — DONE + RATIFIED 2026-07-24** (→ HISTORY § the hero sea-sync sweep): 203 heroes re-rendered (~10.5 h, 0 fail), 609 variants regenerated, gallery judged GOOD by Rohan → **hero-look freeze lifted**. `scene_build` IMPORTS palette (constants are derivations, not copies); the locked-constants section below is re-frozen to the post-sweep truth. Follow-on hero fixes rode the freeze-lift: the **pinecone/AO** default 0.38→0.20 + per-country `sky_view_strength`, and the **resolution floor** anti-striping for 7 microstates (→ HISTORY §§ the "pinecone" islands · the tiny-country "shredding" cured). Pre-seasync hardlink archive prune = Rohan's separate call.
  - Closes four divergences in one ~204-hero re-render: (a) sun 46° → 45° via shared `palette.SUN_ALT_DEG`; (b) `WATER_RGBA` drift → pinned relationally to `SEA_STOPS[0]`; (c) NEW hero lake depth (GLOBathy, `lake_mask.py` — as `snow_mask.py` parallels `snow.py`); (d) hero sea ramp → palette's −6,000 m ramp
  - The gate was never the pyramid — it is the shared palette constants; the constants audit (2026-07-21) found no fifth divergence, and the fill sun was the fourth of this species → HISTORY § the hero/tile colour constants AUDITED · § the tiles were missing the hero's fill sun · ART § Inland water
- [x] Polar caps via a MapLibre custom layer — DONE, default-on (`?nocaps` to disable; Mercator ends ~85°; each cap is a source-shaded AEQD raster over the pole, sea ice over bathymetry, seam-matched light rotating with longitude) → HISTORY § the polar cap: flat fails · § the cap's seam-match
  - [x] Sea ice — OSI SAF ice-frequency climatology, `ICE_LO=0.55` decline-aware → HISTORY § 2026-07-20 sea ice
  - [x] South cap — GEBCO-direct height, forced snow-white land, toned ice
  - [x] `ice_relief_damp` 0.75 SHIPPED + RATIFIED on `/globe` (pack conceals seafloor *shading*, fringe keeps relief, colour glow survives) → HISTORY § 2026-07-22 Antarctica FILL
  - [x] Pole taper RETIRED 2026-07-23 — the damp treats the cause the taper patched → HISTORY § the flat-pole taper RETIRED
  - [x] Cap layer restores GL state each draw (premultiplied-alpha contract in `polarCaps.ts`)
  - [x] **Productionized 2026-07-23** — 8192² WebP q85 (3.2+2.1 MB, was 11.1+4.8 MB PNG; Rohan's crop+globe A/B), the `caps.json` contract replaces hand-copied TS literals, default-on with `?nocaps`, `MAX_TEXTURE_SIZE` clamp → HISTORY § polar caps PRODUCTIONIZED. PMTiles packages only the pyramid — caps stay standalone assets, Tier-3 terrain-RGB would be its own archive

## Phase 4 — Deploy & polish

- [~] nginx container on rohome, cache headers, PMTiles range-request config — the config is BUILT + measured 2026-07-23 (`deploy/`: two server blocks `:80` prod-shape / `:443` local-sim TLS, shared locations include, stores from `web/.env`, curl battery green; local-sim ladder: cold 1.8 s / warm 1.1 s first idle on loopback, cold payload 20.6 MB → HISTORY § the nginx serving block built early). REMAINING: rohome deploy (restart policy + Watchtower labels), WAN-throttle test (~240 ms RTT — the Pangolin double-hop, measured), and the rohome home-uplink bandwidth question
- [ ] **Deployment architecture (host-agnostic; Rohan's calls 2026-07-24)**
  - **Container-based** (Rohan's lean): no re-running anything on restart + reproducible env across dev/rohome/cloud
    - serving container in `deploy/` already models it — add `restart: unless-stopped` + Watchtower labels
    - no pipeline Dockerfile yet — creating one is the portability seam; its base image carries the py3.14 bump
  - **Deploy target = dumb static file host** — zero runtime compute (all pre-rendered, PMTiles range requests, client capability probe); that is what makes it portable
  - **Serving contract (the interface to preserve; `deploy/nginx` = reference impl):**
    - HTTP range requests (client addresses `planet.pmtiles` by byte offset — 15 GB)
    - three cache classes: `_astro/*` immutable 1yr / stores 1wk+ETag / HTML no-cache
    - gzip text-like ONLY (never the pre-compressed pmtiles/webp/png)
    - CORS+range if stores move to another origin
  - **Cloud path when scaling = object storage + CDN** (PMTiles designed for this — no tile server)
    - Cloudflare R2 + CDN preferred (zero egress — the 15 GB archive + tens-of-GB stores make egress the cost driver)
    - VPS+nginx portable as-is; static platforms (Netlify/Vercel/Pages) serve HTML only (stores too big → still need object storage)
  - **Seam to add for the cloud split:** an `ASSET_BASE_URL` — web HARDCODES same-origin store paths today (`location.origin`+`/tiles`|`/pmtiles`; `/caps/`, `/heroes/` across globe.astro/polarCaps.ts/[slug].astro/index.astro) → split-origin is a small multi-site change, not a one-liner
  - Artifact sizes now: `web/dist` tiny · `planet.pmtiles` 15 GB · variants 2.1 GB · caps 5 MB
- [ ] Pangolin route: **terrella.alchez.dev** (Rohan's pick 2026-07-24)
- [ ] Lighthouse pass on all three tiers; test on a weak Android device — carry-ins from 2026-07-23: Firefox blocks ~1.1 s on main-thread cap decode+upload (`createImageBitmap` decodes sync there + slow `texImage2D`, bugzilla 1486454; Rohan's waterfall → HISTORY § polar caps PRODUCTIONIZED); candidate fix = decode in a Web Worker (transferable ImageBitmap). Dev middleware sends no ETag/Last-Modified → no-cache can't 304, full re-downloads every dev load (dev-only; nginx adds validators)
- [ ] Globe web polish (leftovers from the MapLibre API survey → HISTORY § the MapLibre API survey): hovered-country name chip (the gold outline names nothing — needs a design pass); `webglcontextlost` "reload the globe" hint; `setMaxParallelImageRequests` experiment at the Lighthouse pass (first paint ≈40 tile requests vs the 16 default — measure on real network, not localhost). The onAdd-per-projection-transition re-init is FIXED (`gl.isProgram` guard); the phone-lag ladder VERDICT: no main-thread jank exists (250 ms total long tasks) — the wait is the loading window, so the fixes are prod serving (gzip/minify, arrives with the nginx deploy) + the now data-justified `cap_render` 4096 WebP rung + caps.json rung listing (mobile fetch 5.3 → ~1.5 MB ≈ 1.2 s of the window) → HISTORY § the phone ladder verdict. Diagnostic flags `?perf` (long-task overlay; event stamps recorded in globe.astro since the prod build outraces the overlay's dynamic import) and `?bare` (tiles-only) are standing tools. Nginx-sim refinement of the verdict: the window's compute floor decomposed 382/794/985 ms (bare/+countries/+caps) → countries DEFERRED to first idle (interaction data, not first-paint content: warm full 985 → 595 ms, cold window 20.6 → ~18 MB); remaining prod levers are the payload rungs (caps 4096, tiles WebP/AVIF in FUTURE, gzip_static sidecars, vector-tile countries to kill the 9.2 MB parse) → HISTORY § the nginx serving block built early
- [~] About page: data credits (Copernicus, GEBCO, Natural Earth, ESA WorldCover — exact CC-BY string in the locked-constants Snow entry; OSI SAF + reference-period note; NSIDC-0791, RGI 7.0 CC-BY 4.0, GLOBathy CC0 + the lake-depth epistemics), technique notes; worldview section's best concrete example: the Baikonur Cosmodrome hole in Kazakhstan's hover highlight (NE de-facto carves the leased territory — verified, the highlight is correct)
- [x] Bump astro 7.0.7 → 7.1.3 — DONE 2026-07-23 (same major, zero breaking on path; gates green: astro check 0, vitest 45, build 206 pages / 418 ms; dev server restarted on 7.1.3) — contrast: GDAL 3.13 assessed same day and SKIPPED → FUTURE.md
- [ ] (Optional flourish) landing-page "poster mode" beauty shot — Balazh-style sphere; a weekend experiment (decomposed in chat 2026-07-07)
- [~] **Open-source pass** (stated goal 2026-07-23) — mostly done same day: `pipeline/paths.py` seam (ROOT/DATA/BLENDER; `MAPS_DATA`/`MAPS_BLENDER` env overrides; 18 modules migrated, drift-scan test enforces single-homing), LICENSE = MIT code / CC BY-NC 4.0 imagery (README + ATTRIBUTIONS sections; NC trade-off recorded → HISTORY § LICENSE + paths seam). REMAINING: migrate `snow_mask.py` off its freeze allowlist after sweep ratification; final attribution review of shipped products at Phase 4
- [ ] Ship. Post it somewhere.

## Phase 5 — Tier 3 (candidate; go/no-go after Phase 4 ships)

The Tier-3 *gate* already ships (capability probe + Lite/Globe/Full toggle, Phase 3); this phase builds what the gate reveals. The three data items below share one input product and get decided together.

- [ ] Terrain-RGB elevation pyramid — its own PMTiles archive (the pmtiles protocol serves `raster-dem`/terrarium natively, confirmed 2026-07-23)
- [ ] Crispness = a supersampled re-fuse (transient bands, never a stored ~496 GB product); shares the fine re-fuse input with terrain-RGB → HISTORY § 2026-07-20 (evening)
- [ ] Occlusion `cos(lat)` fix — PROVEN (under-occluded 1.22× @35°N, 2.00× @60°N, 3.86× @75°N; per-row ground scale = the hillshade z-factor trick; record occlusion resolution in freshness too); **rides the first full tile restage, whichever comes first** — deferred by Rohan 2026-07-22 (visual impact tiny, SVF burn-only + capped; a solo fix would spend a planet-wide /globe ratification on a subtle delta) → HISTORY § 2026-07-20 (evening) · § 2026-07-22 Antarctica FILL
- [ ] Tier-3 web layer — `raster-dem` displacement on the globe, idle animations, lazy 8K heroes on country click

## Locked global constants (Phase 0 exit checkpoint 2026-07-06; amended 2026-07-08; re-frozen 2026-07-24 post-sea-sync)

Global for all ~195 countries; changing any of these means re-rendering every hero — treat as frozen, re-litigate only with explicit discussion. **The hero and tile look constants are now SHARED BY IMPORT, not copied:** `scene_build.py` and `shade*.py` both import `pipeline/render/palette.py`, so a ported constant cannot drift (→ HISTORY § the hero sea-sync sweep). The 2026-07-24 sweep closed the four copy-drift divergences (sun 46→45°, water tint, sea ramp, hero lake depth); the values below are the post-sweep truth.

- **Terrain:** vertical exaggeration 15× (`palette.EXAGGERATION`, imported by `render_prep` + `shade_planet` — the last copy-pair, collapsed 2026-07-24), Midlevel 0; Scale is per-frame unit conversion `15 ÷ (extent_w/2 in m)`, computed by `render_prep.py` into `frame.json` (`docs/framing-math.md`)
- **Light:**
  - Sun rotation → altitude **45°** (`palette.SUN_ALT_DEG`, shared with the tile `KNOBS["alt"]`), azimuth NW (hero −45°); Angle 12°; Strength 3
  - Fill sun rotation (30°, 0°, 135°) → SE, shadowless (`use_shadow` off); Angle 10°; Strength 0.45 (15% of main)
  - World fill `F2E7D5` @ strength 0.3
- **Color:** view transform **Standard** (never AgX — it greyed the palette)
  - Land ramp, 0→6,000 m: `E9D9C0`@0 / `D7AC8E`@0.083 / `CE9880`@0.25 / `C9AD97`@0.5 / `DCC9B2`@0.75 / `E9DCC8`@1.0 — the top stays warm sand; white/blue belongs to the snow mask alone
  - **Sea ramp (`palette.SEA_STOPS`, shared hero+tile), 0→−6,000 m:** `85B9B7`@0 / `73ABAB`@0.033 / `68A6AC`@0.133 / `56939E`@0.333 / `47808F`@0.633 / `3A6E7D`@1.0 — the hero's old smooth-C −3,000 m ramp was replaced by this in the 2026-07-24 sweep
  - **Water tint `WATER_RGB = 8EC6C4`** (`palette`, imported) — pinned relationally to `SEA_STOPS[0]` lightened ~7% (`test_palette` guards it); the flat inland-water fallback
  - **Lake depth (heroes, 2026-07-24):** `lake_mask.py` emits `lakedepth_aea.tif` (log1p depth → ramp position); the shader tints via `palette.LAKE_STOPS` (position 0 == `WATER_RGB`) — tint-only, never displacement; rivers stay flat
  - Snow `E8F1F6`; land/Lake Mix = water always wins; masks 0/255 PNG, image nodes Non-Color, mask interpolation Closest, no reversed Map Ranges
- **Snow data (heroes):** ESA WorldCover 2021 v200 class 70, warped nearest per frame by `snow_mask.py` (permanent snow/ice only; roots on `paths.DATA` since 2026-07-24). CC-BY 4.0; About page must credit "© ESA WorldCover project 2021 / Contains modified Copernicus Sentinel data (2021) processed by ESA WorldCover consortium". No Antarctica coverage (special-case hero regardless)
- **Camera:** orthographic, straight down; ortho scale = plane's larger dimension × 1.0006; render resolution 7680 px on the raster's *longer* axis (`hero_long_edge` in `config/countries.toml`, per-country overridable; India pinned at 7680×7906)
- **Render:** Cycles, OptiX backend, OIDN denoiser (CPU for 8K frames — VRAM contention), adaptive subdivision dicing 1 px (≈6.8 GB peak at 8K)
- **Post-render shading (2026-07-10; per-country 2026-07-24):** `sky_view.py` — burn-only horizon SVF (AO) from `heightfield_aea`, composited by `batch.py` before the atomic promote; open ground and sea unchanged. Strength is per-country `sky_view_strength` (`config/countries.toml`): **default 0.20**, flat Qatar/Paraguay 0.38 (the original motivation), 7 volcanic islands 0.0 (the pinecone fix) → HISTORY § the "pinecone" islands
- **Resolution floor (heroes, 2026-07-24):** `resolution_floor_m = 60` (`config/countries.toml` default) — `render_prep` box-lowpasses the heightfield only where a tiny frame upsampled >5× past the 30 m DEM (auto-thresholded, engages 7 microstates), killing GLO-30 source striping; andorra exempted → HISTORY § the tiny-country "shredding" cured
- **Borders (overlay, not scene):** land white 95% @ 10 px + casing `#3D2B1F` 35% @ 14 px; disputed/LoC dash [30, 20]; maritime white 80% @ 7 px + casing 25% @ 10.5 px, dash [40, 25]; widths are 8K-canvas px, scale linearly with render width; NE default worldview

## Open questions

Resolved questions move to HISTORY.md — one home per fact. Each question names the point where it gets decided.

- **Hero presentation — geography-conditional, not finalised.** Cutout-cream suits continental, real ocean suits islands, no universal design (the consistent/coherent/neighbour-free trilemma); most countries are *both* coastal and bordered, and every treatment reads flat at the margin. **Decided at:** Phase 3 gallery/globe design; not a look change → doesn't touch the locked constants. → HISTORY § 2026-07-09 — Hero presentation explored
- **Tile-pyramid storage location on rohome** (which mount, backup exclusion). **Decided by:** start of Phase 4 deploy.
- **Prep-ahead producer/consumer runner — designed, deferred, probably moot** (the `--through prep` / `--through render` phase split is the zero-complexity 90% alternative). **Decided at:** only if a full re-render sweep is ever needed again. → HISTORY § 2026-07-09 — Batch runner

## Active learnings (tile pipeline — load-bearing gotchas)

One line each. Anything needing a paragraph belongs in HISTORY.md — this section is scanned before touching the pipeline, not an archive.

- **Planet tile shading is ONE global streaming pass** (`shade_planet.py`): warp → per-row-z hillshade (full-width, 1-row halo → seamless) → globally-normalised SVF → per-window composite.
- **The shade KNOBS were tuned on mountainous Nepal** — validate any knob change on a different terrain type (bright lowland, ice sheet, high latitude), never only on mountains.
- **The region path is a PREDICTION of the planet — check it actually predicts before judging on it**; both paths now derive occlusion from `sky_view.OCCLUSION_TARGET_M_PER_PX`, and any new per-path parameter must too. → HISTORY § 2026-07-20 (evening)
- **`ambient` is a softplus knee since 2026-07-21 (`ambient_knee=0.30`), not a hard cliff** — *raising* ambient stays the twice-rejected fix; the knee reaches the whole curve (nothing can land AT the floor), so anything assuming light 1.0 at `hs == flat` must invert it via `conftest.hillshade_for_light`. → HISTORY § `ambient_knee` 0.30 SHIPS
- **A metric that scores contrast cannot judge softness (twice-failed)** — the clip *manufactures* contrast at its own cliff; judge look on the sphere at planet scale, quote metrics for direction/magnitude only.
- **Occlusion is NOT the softness term — falsified 2026-07-20 by a 6-run sweep**; do not re-litigate. → HISTORY § 2026-07-20 (evening)
- **Softness is view-independent → fully bakeable; crispness is a data ceiling** — z8 (305.7483 m/px) IS the 10″ fuse (308.7 m); real crispness = re-fuse finer and box-filter the shaded RGB down, never the heights.
- **Snow = observed persistence, not permanent ice**; snow shadows must be blue-white (`SNOW_SHADOW_RGB`) — neutral `SNOW_RGB × light` greys rugged snow into a smear.
- **`gdal raster tile` needs `--tile-size 512`** (default 256 halves the master), and never tile a many-source VRT — materialise a tiled GTiff + overviews first.
- **Mercator can't reach the poles → the AEQD custom-layer caps** (flat fill fails: dark = hole, pale = plug); live tiles still carry the interim `CAP_RGB` plug under the cap seam. → HISTORY § the polar cap: flat fails
- **WebMercatorQuad alignment:** warp with `-tap -tr 305.7483` (`20037508.34 = 65536 × 305.7483`) or the tiles seam; planet grid is 131072 × 131072 (±85.05°) since the Antarctica extension — 131072 × 93009 to −60° before it.
- **GEBCO_2026 is ice-*surface* elevation** — Antarctica/Greenland land must come from GLO-30, never a bathymetry clamp.
- **The region path is NOT windowed — cell count is a direct RAM multiplier** (4 cells ≈ 14.5 GiB, OOM-killed at the 12 G cap); scale cells by the cap.
- **The two shade paths have opposite staleness exposure** — `shade.py` re-warps every run (always current, the right pre-flight for a re-fuse); `shade_planet.py` caches (exposed by design, covered by `is_stale`).
- **An artifact that tracks a SEAM is a compositing bug; one pinned to GEOGRAPHY is a data bug** — first question for any visual artifact: assets or screen? (same-camera screenshot layer on/off); custom-layer GL contract lives in `polarCaps.ts`. → HISTORY § 2026-07-22 Antarctica FILL
- **Warp targets are grid-checked, not just source-checked** (`grid_matches` + `warp_needs_rebuild` on all six 3857 warps) — a grid-growing re-fuse falsely left them fresh at the old dimensions (silent corruption). → HISTORY § 2026-07-22 Antarctica FILL
- **The freshness guard is blind to CODE by design** (params, not source, are the dependency) — any *behavioural* change to a shading kernel must be verified against an oracle by hand.
- **`composite_params()` serialises KNOBS wholesale** — anything changing its JSON costs a ~54-min `planet_rgb` rebuild; keep new tunables *inside* KNOBS.
- **The one recurring bug is testing a PROXY instead of the thing** — ask before any check: *"what would this read if the thing I fear were NOT happening?"*; every aggregate names its witness; hardened into `verify.compare_rasters`. → HISTORY § 2026-07-16
- **A check that cannot fail is indistinguishable from a check that passed** — prove 0 is reachable before reporting 0.
- **One fix, one home** — per-call-site copies drifted four separate times; the shared homes are `pipeline/raster_io.py` (GTiff core, band windows), `warp_needs_rebuild`, `palette.py` — point new siblings there. → HISTORY § commonification LANDED
- **Retire a superseded path the same day: delete it or move it out of the production package** — prose calling it "retired" does not disarm a runnable entry point; git is the archive. → HISTORY § 2026-07-14 (overnight)
