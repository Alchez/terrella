# Terrella — decision history

Chronological archive of decisions and their rationale, split out of PLAN.md on 2026-07-14 to keep the living plan lean. Newest first. PLAN.md's locked constants and open questions cite entries here for the *why*; append new decisions here, not in PLAN.md.

## Decision log

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
