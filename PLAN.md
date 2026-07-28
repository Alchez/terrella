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
- [x] Responsive variants (six rungs 640→8K WebP) — `hero_variants.py`, ≈16× smaller than PNG

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
- [x] **Antarctica — FILL chosen** → HISTORY § 2026-07-22 Antarctica FILL
  - Pyramid extended to −85.05° (1.41× every planet raster); planet re-fused −90…90
  - Polar ring root-caused as a premultiplied-alpha blend bug — screen, not data
  - RGI-19 deferred (`antarctic_snow_mask`); SVF normalisation proven safe
- [x] **Hero-"softness" port CLOSED** → HISTORY § 2026-07-21 entries · ART § Hero → tile parameter map
  - `ambient_knee` 0.30 + `shadow_warmth` 0.55 SHIPPED (Rohan, `/globe`)
  - Cast shadows rejected twice — the *mechanism* erases fine modeling
    - Reopening needs a new mechanism, not a new value
  - Hillshade-side lever dropped: every dial is a hero anchor
- [x] **Package as PMTiles — DONE 2026-07-23** → HISTORY § the uncapped pmtiles convert
  - `pack_pmtiles.py` (dir→MBTiles 33 s, TDD) → capped convert 1m11s → 15 GB `planet.pmtiles`
  - Verified: `pmtiles verify` clean, byte-compare incl. z8 y=255, 5.3% deduped
  - Flip evidence: same desktop, first idle ≈4.4 s loose vs ≈1.3 s from the archive
  - **The browser-side pmtiles client is GONE 2026-07-25** → HISTORY § the web seam lands
    - A tile server ranges the archive now; the flag, the Range dev route and `httpRange.ts` went with it

## Pipeline optimisation — measured 2026-07-16, now mostly landed

Baseline: 98 min wall on 1.16 of 16 cores; every item measured before proposed (three "obvious flag" fixes died on a profiler) → HISTORY § the instrumented planet pass. Pays on every future shade pass — the composite alone was ~71% of a pass — not on the tile cut.

1. [x] Hillshade float32 + 256-row windows — 932 → 508 s, 11.6 → 2.03 GB → HISTORY § optimisation #1
2. [x] color-relief stage deleted — 24.4% of pass CPU became a 17.6 KB LUT → HISTORY § optimisation #2
3. [x] `num_threads=ALL_CPUS` on the three tile writers — 10× on the writer → HISTORY § optimisation #3
4. [x] Snow + glaciers warped ONCE, in latitude bands (a whole-grid warp DECIMATES a coarse source) → HISTORY § snow warped ONCE
5. [x] Composite threaded — 128/N4, ~3.5×, threaded==serial gated byte-identical → HISTORY § the composite is threaded
6. [ ] `-srcnodata`→0-fill on GLOBathy — 51% of the 62-min lake warp; pays only on a re-extract
7. [x] Prep-walk redundancy cut (2026-07-23) — mosaic freshness skip + 24 h preflight stamp; 35 s → 1.25 s/country → HISTORY § the prep-walk redundancy cut · PROCESS
8. [x] **Commonification DONE 2026-07-23** → HISTORY § commonification LANDED
   - `pipeline/raster_io.py`: `GTIFF_CREATE` (format-only) + `row_bands`/`band_window`, six sites
   - Threading stays per-call-site or it oversubscribes fusion — now enforced by test
   - Two list items found already done: `warp_needs_rebuild`, `lake_ab --left/--right`

- Experiments audit (2026-07-16): `sea_ab.py` + `ab_crops.py` retired; a *working* experiment is the record of a decision → HISTORY § 2026-07-16
- `composite_ram.py` measures `composite()` alone — a lower bound, not the pass; the 12 G cap = 1.9× the real peak → HISTORY § composite_ram.py was never the number
- Code in `pipeline/`, output in `data/` — `data/` is gitignored; harnesses live in `pipeline/profile/`, never `data/work/`
- Test coverage measured on demand (2026-07-23): `uv run pytest --cov`, baseline 32.45%, `fail_under=32` as a ratchet; covered = the compute kernels, 0% = network/GPU orchestration → HISTORY § commonification LANDED

## Phase 3 — Frontend

Tiers 1 + 2 shipped on `feat/frontend` (worktree `../maps-frontend`; merge later): Astro 7 static site — gallery + detail + About + `/globe`, capability probe auto-steering. Tier 3's 3D displacement → Phase 5. → HISTORY § 2026-07-10 — Phase 3 begins; asset commands → `docs/pipeline.md`; deploy is Phase 4.

Baked-vs-live rule (locked 2026-07-07): too expensive live → baked; depends on view state → live; invariant + physics-coupled → baked; otherwise live pinned to authored constants; user-exposed settings only where visitor context genuinely varies.

- [x] MapLibre globe over the raster pyramid — tiles come from a server that ranges the PMTiles archive
- [x] NE vector borders + toggle — casing strengthened to a soft dark halo for pale highlands
- [x] Country click → fly-to → in-globe hero panel (NE hit layer, authored-frame `fitBounds`, lazy panel)
- [x] Hover-highlight pole artifacts fixed — `lib/countryHighlight.ts` + 11 regression tests; Rohan confirmed no look regression → HISTORY § 2026-07-19 hover-highlight
- [x] **Blocky coasts at z6–8 FIXED 2026-07-23** → HISTORY § the blocky hover outline
  - Both suspects were innocent — the hover outline strokes `countries.geojson`
  - It was simplified at 0.05° (~5.5 km) for its original life as an invisible hit layer
  - Retightened to 0.002° (sub-pixel at z8); guard test pins it against `Z8_RES`
- [x] Globe polish — starfield, mobile control fixes, sea rework V1 LIVE, Spin toggle
- [x] Capability probe + tier routing + Lite/Globe/Full toggle + FPS degradation — `decideTier()`, WebGL2 hard floor, TDD'd
- [x] Tier 1 no-JS fallback — pure-CSS gazetteer overlay; dead search removed
- [x] **Subject-spotlight "Focus" toggle on heroes/gallery** — globe keeps Borders → HISTORY § the subject-spotlight "Focus" view
  - Overlay asset (`gen_spotlight.py`), never baked — the toggle costs no re-render
  - Subject = DEM-land minus neighbours' NE polygons: pixel-exact coast, NE landward border
  - `gen_borders.py` stays live — the globe's hero panel still draws its PNGs
- [x] **Hero sea-sync sweep — DONE + RATIFIED 2026-07-24** → HISTORY § the hero sea-sync sweep
  - 203 heroes re-rendered (~10.5 h, 0 fail), 609 variants regenerated, judged GOOD by Rohan
  - **Hero-look freeze lifted**; `scene_build` now IMPORTS palette (derivations, not copies)
  - Closed four divergences in one re-render
    - (a) sun 46° → 45° via shared `palette.SUN_ALT_DEG`
    - (b) `WATER_RGBA` drift → pinned relationally to `SEA_STOPS[0]`
    - (c) NEW hero lake depth (GLOBathy `lake_mask.py`, as `snow_mask.py` parallels `snow.py`)
    - (d) hero sea ramp → palette's −6,000 m ramp
  - The gate was never the pyramid — it is the shared palette constants
    - The 2026-07-21 audit found no fifth divergence; the fill sun was the fourth
    - → HISTORY § the hero/tile colour constants AUDITED · § the tiles were missing the hero's fill sun
  - Follow-on fixes rode the freeze-lift → HISTORY §§ the "pinecone" islands · the tiny-country "shredding" cured
    - Pinecone/AO default 0.38→0.20 + per-country `sky_view_strength`
    - Resolution floor anti-striping for 7 microstates
  - Pre-seasync archive PRUNED 2026-07-25 → HISTORY § the post-ratification reclaim
- [x] **Polar caps via a MapLibre custom layer** — default-on (`?nocaps` disables) → HISTORY § the polar cap: flat fails · § the cap's seam-match
  - Mercator ends ~85°, so each pole is a source-shaded AEQD raster drawn over it
  - Sea ice over bathymetry; seam-matched light rotating with longitude
  - [x] Sea ice — OSI SAF ice-frequency climatology, `ICE_LO=0.55` decline-aware → HISTORY § 2026-07-20 sea ice
  - [x] South cap — GEBCO-direct height, forced snow-white land, toned ice
  - [x] `ice_relief_damp` 0.75 SHIPPED + RATIFIED on `/globe` (pack conceals seafloor *shading*, fringe keeps relief, colour glow survives) → HISTORY § 2026-07-22 Antarctica FILL
  - [x] Pole taper RETIRED 2026-07-23 — the damp treats the cause the taper patched → HISTORY § the flat-pole taper RETIRED
  - [x] Cap layer restores GL state each draw (premultiplied-alpha contract in `polarCaps.ts`)
  - [x] **Productionized 2026-07-23** → HISTORY § polar caps PRODUCTIONIZED
    - 8192² WebP q85 (3.2+2.1 MB, was 11.1+4.8 MB PNG) on Rohan's crop+globe A/B
    - `caps.json` contract replaces hand-copied TS literals; `MAX_TEXTURE_SIZE` clamp
    - Caps stay standalone assets — PMTiles packages only the pyramid

## Phase 4 — Deploy & polish

**LIVE at `terrella.alchez.dev` since 2026-07-25** — three origins, verified end to end. The
rationale lives in HISTORY; this section carries only what is still open.

### Shipped

Pointers only — every *why*, number and rejected alternative is in the cited HISTORY entry.

- [x] **Cloudflare R2 + CDN**, chosen over rohome → HISTORY § the deploy target moves to R2
  - Site = Workers Static Assets · `assets.` = R2 custom domain · `tiles.` = Worker over an R2 binding
  - Standing constraints: free tier ≈ **2,500 cold visits/day** (a cache HIT still charges a request) ·
    account/zone IDs live in memory, never in this repo · **`deploy/` is the prod-sim, not dead weight**
- [x] P1 web seam — `assetBase.ts`, ranging server-side, pmtiles JS out of the bundle → HISTORY § the web seam lands
- [x] P2 two R2 buckets, 18.20 GB uploaded, multipart ETag reconstructed → HISTORY § Phase 2
- [x] P3 tile Worker — ours, not Protomaps' → HISTORY § the tile Worker is ours
- [x] P4 site shell + `check_deploy_sync.ts` preflight → HISTORY § Phase 4 takes shape
- [x] P5 external vantage + `Server-Timing`: our Worker code is 3–5 ms → HISTORY § P5 end-to-end
- [x] **Asset delivery — rungs, quality policy, WebP tiles**; archive 15 → 3.0 GB →
  HISTORY § the ladder ships against measured layout · ART § Delivery encoding
- [x] Polar cap 4096 rung → HISTORY § the cap rung
- [x] **Cap rungs by projected size** — 156 KB at the default camera, cold window 11.4 → 6.5 MB →
  HISTORY § the polar caps ship 156 KB
- [x] `Timing-Allow-Origin` on both cross-origin surfaces → HISTORY § P5 end-to-end
- [x] **Hovered-country name chip** — top-centre pill, gold dot, desktop-only by design →
  HISTORY § the gold outline finally says what it is
  - Found underneath it: **hover was recomputed on `mousemove` and nothing else**, so the outline and
    the cursor went stale on every drag/zoom/fly-to. `hoverTracking.ts` re-resolves on `moveend`
  - **Never unbind `moveend → viewChanged()`** — every unit test stays green without it; only the
    source guard catches its removal
  - Cost: 0.04–0.07 ms/resolve · 165 fps through spin, 0 long tasks · +226 B gzipped
- [x] About page → HISTORY § the About page closes
- [x] astro 7.0.7 → 7.1.3 (GDAL 3.13 assessed the same day and SKIPPED → FUTURE)
- [x] **RESOLVED: buy nothing for the MRS PoP** → HISTORY § P5 end-to-end
  - An Airtel route, not our plan — so **the P5 ladder numbers are this line, not the site**.
    It is BGP: re-run the two-second `--resolve` check before acting on any of it
- [x] **Hole to space CLOSED** — `background` layer at `#47808F`, 0 bytes and 0 requests →
  HISTORY § the hole to space was never a MapLibre regression
  - **Not a v6 regression** — 5.24 vs 6.0 tile-retention source is IDENTICAL; do not re-suspect the bump
- [x] **Cold-tile levers A + C** — index prefetch (3 reads → 1) and Workers Caching (read-through
  ~28 ms, cold unchanged) → HISTORY § one read instead of three · § Workers Caching ships on its own merits
  - **NEVER add the `cache` block to the site Worker** — it bills otherwise-free static-asset requests
  - Lever B (placement hint) demoted to an experiment likely to be rejected → FUTURE
- [x] **`webglcontextlost`** — v6 recovers unaided, so the planned "reload" hint was wrong advice; the
  real bug was a `moveend` listener stranded per loss → HISTORY § the "reload the globe" hint
  - **`addPolarCaps` must stay bound to `style.load`** — that binding IS the cap recovery path. Test-guarded
- [x] **`setMaxParallelImageRequests` — LEAVE IT AT 16** → HISTORY § the ladder ran and the answer is LEAVE IT AT 16
  - **Do not go below 8**; above 8 there is nothing to win. **Tiles are NOT on the LCP path**
    (LCP 1.5 s against a 16.5 s tile tail), so no tile-payload lever moves LCP either
- [x] **Serving-contract writeup DROPPED** — the two implementations *are* the contract; a doc would
  duplicate 42%-commented config and drift → HISTORY § the writeup is dropped
  - `deploy/README.md` added; three stale refs to the retired rohome/Pangolin shape corrected
- [x] **Open-source pass COMPLETE — nothing blocks going public** → HISTORY § LICENSE lands ·
  § the one licence with an exact-string obligation · § the open-source pass closes clean
  - `paths.py` seam · LICENSE (MIT code / CC BY-NC 4.0 imagery) · About-page credits · attribution
    review (Copernicus 6(b)/6(c), two badges, two-way drift test)
  - **Shipped-artifact scan CLEAN**: repo · built site · R2 stores; no sourcemaps; zero embedded
    metadata across 2,436 heroes + 1,010 border PNGs + 8 caps + 6 live tiles
- [x] **rohome gets no site deploy at all**, not even a mirror — Cloudflare is the only origin; rohome
  keeps the *pipeline* only, per CLAUDE.md § Environment → HISTORY § the deploy target moves to R2
  - `deploy/` stays as the local prod-sim + reference implementation; nothing ships from it

### Open

- [~] **Lighthouse pass** — globe mobile **48** / desktop **79**; Tier-1 separation clean →
  HISTORY § the globe's script time is EXECUTION (carries the full 07-25 baseline)
  - **The bottleneck is script EXECUTION — not payload, and not parse either**: 4,833 ms evaluation
    vs **2 ms** parse, measured twice. No bundle-size lever touches it
  - Attribution was to the **chunk URL, not a function** — **now partly closed by LoAF `scripts[]`**
    → HISTORY § the 4.8 s finally has a name
    - One block dominates: the `countries.geojson` post-fetch chain, **~355 ms, ±2.5% over four
      runs, ~54% of all long-frame script time** — *our* module, not MapLibre init
    - **Does not explain the 4,833 ms** — LoAF sees only >50 ms frames, unthrottled; different scope
    - **LoAF is the first instrument here that beats its own noise** — judge future A/Bs on it,
      never on the mobile score
  - **Variance exceeds most effects we chase** (48/TBT 2,120 vs 53/TBT 3,300, same command) —
    never claim a change moved the score off a single run
  - **`countries.geojson` is the largest single item** (3.08 MB) — bigger than all 36 tiles combined
  - Carry-in: Firefox blocks ~1.1 s on main-thread cap decode+upload → candidate = Web Worker decode
  - Carry-in: the dev middleware sends no ETag/Last-Modified, so `no-cache` can't 304 (dev-only)
- [ ] **Ship** — no technical work left, three separable pieces:
  - **Make `Alchez/terrella` public** (currently PRIVATE). Both scans are clean and nothing blocks it
    → HISTORY § the open-source pass closes clean · § the repo's whole object database is clean
    - **ONE OPEN DECISION:** git metadata publishes the author email across all 138 commits. Inherent
      to git — accept it, or switch to a GitHub noreply address going forward (does not rewrite history)
    - Note a fresh clone deliberately **cannot build** (`countries.json` + `public/caps/` are generated
      and gitignored) — correct, but it is the first thing a visitor hits; `web/README.md` documents it
  - **Decide what the assets are.** The repo is code-only; heroes/borders/archive are served from our
    R2 on a free tier ≈ 2,500 cold visits/day. Posting is the event that tests that ceiling
  - **Post it.** Where is entirely Rohan's call
  - **NOT gated on the Lighthouse pass** — mobile 48–53 is the cost of a WebGL globe, not a defect.
    CLS is already 0; the score is 62% TBT, which is not a Core Web Vital

Parked in FUTURE, deliberately unscheduled: brotli sidecars · vector-tile countries · look presets ·
AVIF · tile size vs DPR · **the tier ladder's permissiveness** · **poster mode** · mobile identify.

Standing diagnostic flags: `?perf` (long-task overlay) · `?bare` (tiles-only) · `?nocaps` ·
`?maxreq=N` (MapLibre's parallel image cap, default 16 — refuses a malformed value loudly).

## Phase 5 — Tier 3 (candidate; go/no-go after Phase 4 ships)

The Tier-3 *gate* already ships (capability probe + Lite/Globe/Full toggle, Phase 3); this phase builds what the gate reveals. The three data items below share one input product and get decided together.

- [x] **Terrain-RGB elevation pyramid — BUILT AND SERVED 2026-07-28.** `terrain.pmtiles` (2.63 GB, z0–8, 8 m, lossless WebP), second key in `terrella-tiles`, routed by the tile Worker under a `terrain/` prefix → HISTORY § terrain gets an archive, a prefix, and four fewer flags
  - **The prefix is load-bearing**: both pyramids are WebP over z0–8, so nothing else in a tile URL tells them apart, and the wrong one displaces the globe rather than 404ing
  - Retired with it: `?dem`/`?quant`/`?demfmt`/`?demdepth` (they named build directories) and the spike dev route
  - **Remaining: the R2 upload + both deploys** — the preflight refuses until `terrain-v1.pmtiles` is in the bucket
- [ ] Crispness = a supersampled re-fuse (transient bands, never a stored ~496 GB product) → HISTORY § 2026-07-20 (evening)
  - The old "shares the fine re-fuse input with terrain-RGB" claim was **stale and is deleted**: terrain-RGB reads `height_3857.tif`, which already exists, so it never waited on a re-fuse
- [ ] **Occlusion `cos(lat)` fix — PROVEN, rides the first full tile restage** → HISTORY § 2026-07-20 (evening) · § 2026-07-22 Antarctica FILL
  - Under-occluded 1.22× @35°N, 2.00× @60°N, 3.86× @75°N
  - Fix = per-row ground scale (the hillshade z-factor trick); record occlusion res in freshness
  - Deferred by Rohan 2026-07-22: visual impact tiny, SVF is burn-only and capped
    - A solo fix would spend a planet-wide /globe ratification on a subtle delta
- [ ] **High-latitude coastline blockiness** — deferred here 2026-07-25, same restage
  - `ocean_3857`/`water_3857` are `-r near` (categorical, correctly so)
  - Mercator stretches one source row over ~6 output rows at 78.6°N (measured), so coasts staircase
  - Underlying cause: the 10″ fuse is 308 m of *latitude* everywhere, whatever the zoom
  - The supersampled re-fuse is the real fix; a bilinear-then-threshold mask is the cheap partial
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
- **Snow data (heroes):** ESA WorldCover 2021 v200 class 70, warped nearest by `snow_mask.py`
  - Permanent snow/ice only; roots on `paths.DATA` since 2026-07-24
  - CC-BY 4.0 — About must credit "© ESA WorldCover project 2021 / Contains modified Copernicus Sentinel data (2021) processed by ESA WorldCover consortium"
  - No Antarctica coverage (a special-case hero regardless)
- **Camera:** orthographic, straight down; ortho scale = plane's larger dimension × 1.0006; render resolution 7680 px on the raster's *longer* axis (`hero_long_edge` in `config/countries.toml`, per-country overridable; India pinned at 7680×7906)
- **Render:** Cycles, OptiX backend, OIDN denoiser (CPU for 8K frames — VRAM contention), adaptive subdivision dicing 1 px (≈6.8 GB peak at 8K)
- **Post-render shading:** `sky_view.py` burn-only horizon SVF → HISTORY § the "pinecone" islands
  - From `heightfield_aea`, composited by `batch.py` before the atomic promote
  - Open ground and sea unchanged
  - Per-country `sky_view_strength`: **default 0.20**; Qatar/Paraguay 0.38; 7 volcanic islands 0.0
- **Resolution floor (heroes):** `resolution_floor_m = 60` default → HISTORY § the tiny-country "shredding" cured
  - `render_prep` box-lowpasses the heightfield, killing GLO-30 source striping
  - Auto-thresholded on >5× upsample past the 30 m DEM — engages 7 microstates
  - Andorra exempted (real alpine detail costs more than the striping does)
- **Borders (overlay, not scene):** land white 95% @ 10 px + casing `#3D2B1F` 35% @ 14 px; disputed/LoC dash [30, 20]; maritime white 80% @ 7 px + casing 25% @ 10.5 px, dash [40, 25]; widths are 8K-canvas px, scale linearly with render width; NE default worldview

## Open questions

Resolved questions move to HISTORY.md — one home per fact. Each question names the point where it gets decided.

- **Hero presentation — geography-conditional, not finalised** → HISTORY § 2026-07-09 — Hero presentation explored
  - Cutout-cream suits continental; real ocean suits islands; no universal design
  - The trilemma: consistent / coherent / neighbour-free — pick two
  - Most countries are *both* coastal and bordered, and every treatment reads flat at the margin
  - **Decided at:** Phase 3 gallery/globe design; not a look change, so the locked constants stand
- ~~Tile-pyramid storage location on rohome~~ — **dissolved 2026-07-25**: the archive ships to R2, not rohome → HISTORY § the deploy target moves to R2.
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
