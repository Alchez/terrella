# FUTURE — the v2 parking lot

Ideas deliberately **not** planned: analysed enough to record, parked without commitment. This is
not
graduates, it moves to PLAN and this file keeps a one-line pointer. Each entry carries the date of
its analysis and the facts its numbers depend on — check both before trusting an old entry, and
grep HISTORY before re-arguing anything an entry says was already decided.

## MapLibre's WebGPU backend — irrelevant to our memory problem, and NOT the no-op we recorded (analysed 2026-07-29)

Prompted by the graphics-modernization roadmap. Read it against the DEM-cache work rather than in
the abstract, and the answer is "no" on the question that motivated the reading.

- **The roadmap is four phases** — WebGL2 texture/shader work, a drawable architecture with UBOs,
  WebGL2 vertex work, then **WebGPU as phase 4** including GLSL→WGSL conversion. Each phase is
  independently shippable. **No timeline is published.**
- **It contains no mention of GPU memory management, memory budgets, resource lifetimes, device
  loss, or tile caching.** It is a rendering-backend modernization, not a resource-management one.
- **It cannot touch our root cause, which is not in the renderer.** The `_source.tileSize` vs
  `tileManager.tileSize` mismatch lives in `tile_manager.ts`, and `DEMData` holds a `Uint32Array` —
  **JS heap, not GPU memory**. A backend swap leaves both exactly as they are.
- **The seam already exists in the shipped API, which dates the work rather than the promise.**
  `canvasContextAttributes.contextType` is typed today and documented as *restricted to `'webgl2'`,
  kept as a forward-looking API for future WebGPU support* — i.e. the option is reserved and the
  backend is not written. Found in the v6.0.0 `.d.ts` during the API audit, not in the roadmap.

**The one real win is a failure SIGNAL, and it is the missing piece of the evidence-driven budget.**
In WebGL an allocation that exhausts VRAM does not fail — it takes the context down, which is
precisely the 2026-07-29 freeze. WebGPU has typed errors via `pushErrorScope`/`popErrorScope`, so
`GPUOutOfMemoryError` is catchable and attributable *before* the tab dies rather than after. Today
the only feedback the platform gives is "the context died". Secondary: `GPUDevice.lost` resolves
once and permanently, forcing explicit recreation — a stricter contract than the
`webglcontextlost`/`restored` pair whose ambiguity is what hid our recovery notice; and explicit
`destroy()` on buffers and textures gives deterministic release.

**Correction to a recorded prediction.** The Tier-2 globe work
assessed WebGPU as "a future no-op tier, not a rewrite". That was true of the code as it stood and
is **false now**: `polarCaps.ts` is a MapLibre **custom layer**, and that API hands you a raw
`WebGLRenderingContext`. We author GLSL, build VBOs and call `gl.drawElements` directly, so a
WebGPU backend cannot preserve the signature — **the caps need a WGSL port, displacement shader
included**. Anyone pricing the migration must count that; the old entry says they need not.

**Verdict: not a lever for the cache work, and not free when it lands.** Revisit if MapLibre
publishes a timeline, or if the evidence-driven cache budget gets built and wants a real
out-of-memory signal to drive it.

## Flat ice saturates the snow ramp, and the curve was fitted before Antarctica existed (analysed 2026-07-29)

Zooming into Antarctica to judge the terrain feather showed it "basically washed out". Two
independent causes, split by depth in the frame — the far field was the atmosphere (fixed, → HISTORY
§ the atmosphere ramps on PITCH too), and **the near field is this**, which is unfixed.

**Mechanism.** Over full snow (`alpha = 1`) the composite is `base_rgb * (1 - alpha) + snow_rgb *
alpha`, so `base_rgb` is multiplied by zero and every bit of hillshade *and the entire elevation
ramp* is discarded. Relief survives only through `snow_t`, a two-colour ramp. Antarctic land is
forced to alpha 1 by `snow.antarctic_snow_mask` because **there is no snow dataset for it** —
NSIDC-0791 is NH-only and RGI region 19 is excluded — so without the mask Antarctica renders on the
tan LAND ramp, i.e. a brown continent. Flatness is a side effect of that substitution, not its
purpose.

**Then the ramp saturates.** Ice sheets have real elevation (the z6 plateau tile spans 2512–2944 m,
a 432 m range) but almost no SLOPE — about 0.1° across a ~200 km tile, with a median neighbour step
of 0.0 m, below the 8 m quantisation. Hillshade keys on slope, so the light lands at or above
`snow_hi_pt = 1.05` and `snow_t` clips to exactly 1. **Elevation is therefore discarded twice:**
once because hillshade cannot see it, once because the ramp clips.

**Measured 2026-07-29, 3×3 z6 blocks, snow pixels only — the same method HISTORY's gamma8 table used:**

| site | delivered | pinned at top of ramp |
|---|---|---|
| Greenland Summit *(in the gamma8 sample)* | 20.67 DN | 82.1% |
| Greenland north *(in the gamma8 sample)* | 12.67 DN | 89.3% |
| Dome A / Argus | 14.67 DN | 84.3% |
| Vostok | 16.00 DN | 80.0% |
| **E Antarctic plateau (−77, 0)** | **6.33 DN** | **91.3%** |
| Transantarctic Mountains | 20.67 DN | 14.6% |

**Not a systematic failure — a tail case.** Most of Antarctica lands inside the range already
accepted (Dome A and Vostok beat Greenland north, which shipped), and the mountains are fine. The
flat plateau is the outlier, and it is where the review happened to look.

**The gap that makes a re-check legitimate rather than re-litigation:** `snow_curve = "gamma8"` was
chosen **2026-07-17**, and Antarctica was fused into the pyramid **2026-07-22, five days later**.
The curve's whole A/B table is Greenland Summit, Greenland north, Alps and Himalaya — **the largest
snow surface on the planet was not in the sample it was fitted on, because it was not in the
pyramid yet**. No regression was
found (a Summit 3×3 block measures 20.7 DN against the entry's 18.84, consistent), so the curve
does what it was tuned to do; it was simply never asked about this terrain.

**`snow_hi_pt` is NOT the lever, and that is already settled**. The
window was measured and rejected: Greenland uses 7% of it, the Alps overflow at 122%, and **the two
ranges are nested rather than adjacent**, so a window fitted to flat ice turns Alpine snow into a
binary blue/white cartoon. Do not re-argue it.

**Candidates, none costed:** re-fit the gamma exponent with Antarctic sites in the sample (a
composite-stage knob — no re-fuse, no new data, and `experiments/ab_ice_damp.py` is the ~21 s
browser-free precedent); or give the snow ramp an ELEVATION term the way the land ramp has one,
which is what would make a 432 m dome read as a dome. The second is a genuine look decision, not a
bug fix.

**Consequence worth carrying:** while the plateau is pinned white, terrain displacement there is
invisible — our shading is baked, so displacement reads as silhouette and parallax only, and a
uniform white surface offers neither. That gates the payoff of PLAN's Step 2 feather re-cut.

## GDAL 3.13 — assessed and SKIPPED (analysed 2026-07-23)

- **State at analysis:** system CLI 3.12.2 (Ubuntu 26.04 archive — the LTS will stay there);
  rasterio 1.5.0 bundling GDAL 3.12.1 on the Python side; CI on the runner's distro gdal-bin;
  no pipeline container yet.
- **Possible:** mechanically yes, but only via source build / PPA / the OSGeo container images —
  and rasterio can't follow until a wheel bundles 3.13, so a CLI-only upgrade widens today's
  benign 3.12.1/3.12.2 split. All listed 3.13 breaking changes are C/C++-API-side; our
  CLI + rasterio surface is untouched (the `--src/--dst` → `--input/--output` rename keeps old
  names).
- **Useful: no.** The one headline naming our tool — `gdal raster tile` automatic source
  *overview* selection — doesn't apply (our design deliberately has no overviews; low zooms
  build from the tiles). Everything else on our surface is a no-op. Two items are mild *risk*:
  the warper Lanczos special-case removal and "RasterIO resampling now operates in output buffer
  type by default" — resampling changes shift output **bytes**, our pyramid is ratified by
  byte-compare, and the freshness guard is version-blind → an upgrade mid-stream risks a
  mixed-generation pyramid.
- **Revisit when:** (a) a full-restage boundary arrives (the Phase 5 supersampled re-fuse
  regenerates every byte, making version drift moot) AND (b) rasterio bundles 3.13+.
- **Actionable now (Phase 4, not deferred):** when the rohome pipeline container gets built, pin
  its GDAL to 3.12.x to match dev — the same-version principle matters more than the number.

## Look presets — user-selectable globe styles (analysed 2026-07-23)

- **Trigger:** could users pick looks — default, every-country-coloured, seasonal variants (the
  St. Patrick's green-sea example)?
- **Numbers depend on:** the z0–8 pyramid **≈ 3 GB** and ~87k tiles per look — it was 15–16 GB when
  this was analysed, so the WebP q95 switch made a second look **5× cheaper in storage** and moves
  Kind 2 well down the cost ladder; composite-stage restage ~29 min (PROCESS § what a change costs);
  `countries.geojson` sub-pixel since the hover-outline fix

Presets decompose into **three kinds by where the variation lives** — costs differ by orders of
magnitude, so the taxonomy is the decision:

### Kind 1 — vector-over-raster (client-side, ~free) — the one to build first

- "Every-country-coloured" is this kind, **not** a raster look: country identity is vector data we
  already ship and already draw — the hover wash *is* this preset with one colour.
- Implementation: carry `MAPCOLOR13` through `countries_geojson.py` (`-select ADMIN,MAPCOLOR13` —
  Natural Earth pre-computes 7/8/9/13-colour schemes where neighbours never collide, verified
  present in our shapefile), a 13-colour palette tuned over the relief, a `fill` layer at
  ~0.25 opacity, a visibility toggle. Zero pipeline, zero storage, zero caps work.
- Same kind: border-style variants, maritime emphasis, label layers — data-driven styling on
  shipped vectors.
- A weekend feature, and it exercises the whole preset *system* (registry, picker, persistence)
  without touching the pipeline.

### Kind 2 — raster recolors (one PMTiles archive per look)

- Green sea, sepia, dark relief: the look is baked into pixels, so each look = its own archive.
  **Per look: ~28 min compute** (SVF + composite + cut + pack/convert + caps) **and +3 GB
  storage** — the storage term was +15 GB before tiles became WebP q95, and that was the number
  that made this kind expensive; web swaps `PUBLIC_TILE_BASE` (or a per-look path the Worker routes
  on) + the cap pair. Now plausibly scales to several looks, not just a curated few.
- **One-time prerequisite: look parameterization (~a day).** Today every guardrail treats a second
  look as drift — correctly: `test_palette` pins `WATER_RGB` relationally (+7% of sea surface),
  palette is shared by import so editing it in place marks the heroes stale. Looks must become
  first-class: named looks in palette, `composite_params`/freshness/output dirs/cap recipes keyed
  by look, relational pins per-look. Corollary to remember: `LAKE_STOPS[0]` derives from
  `WATER_RGB`, so a naive green sea also greens every lake and river — a choice, not an accident.
- One-off stunt rungs, if a *single day* ever justifies a gag without the plumbing:
  `raster-hue-rotate` on the relief layer (free, but rotates land too, and our custom-layer caps
  ignore raster paint properties — they'd need a shader tint uniform), or a translucent green
  ocean `fill` veil (client-only, bathymetry shading survives underneath, reads as a veil not a
  repaint).

### Kind 3 — client-side colorization (looks become shader LUTs)

- Split colour from data: ship shading + masks as data channels (grayscale light, snow/ice/lake
  alphas — packable into one RGBA archive; elevation via the Phase 5 terrain-RGB archive) and
  apply ramps in a custom WebGL layer. Look N then costs a LUT, ~0 bytes.
- **The counterweight:** it reimplements `shade.composite` in GLSL — a twin look engine, i.e. the
  copy-drift disease at engine scale, in a codebase whose architecture exists to forbid exactly
  that. Only worth opening if presets prove popular enough to be a headline feature; it is a
  Phase-5-sized decision and pairs naturally with the terrain-RGB work if that ships.

### The preset system itself (needed for any kind)

- A **`presets.json` contract** emitted by the pipeline, fetched by the web (the `caps.json`
  pattern — pipeline facts never hand-copied into TypeScript).
- **UI + persistence** following existing precedents: localStorage like the quality/border
  toggles, shareable `?look=` param.
- **Scoping decision to make explicitly:** presets are a *globe* feature; heroes/gallery stay
  single-look (204 Cycles re-renders per preset is not a menu item).

### Recommendation ladder (as analysed)

- Kind 1 first, when wanted — cheap, complete, exercises the system.
- Kind 2 is **materially cheaper than when this was analysed** (3 GB per look, not 15) — the
  remaining cost is the parameterization day, not the storage.
- Kind 3 only if presets become a proven headline feature; decide alongside Phase 5 terrain-RGB.

## Cloud offload / offsite backup (analysed 2026-07-23; revisit after Phase 5)

- **Trigger:** could stores move to S3/R2 to free local disk? **Answer: ~0 GB usefully** — the
  taxonomy is the finding:
  - ~680 GB of raw sources are *caches of free public clouds* (GLO-30 = AWS Open Data, WorldCover
    = ESA's bucket, etc.) — the offload is deletion + on-demand re-fetch, already gated by the
    INVENTORY reclaim picture, never an upload.
  - ~360 GB of intermediates are compute-regenerable — and remote reads for full sequential scans
    are a rejected shape
    for a full sequential scan").
  - The **~56 GB worth putting in a cloud is the backup set, not an offload**: heroes+raws+variants
    (27 GB real bytes, hardlink archives ~free; Cycles isn't bit-deterministic so ratified pixels
    are irreplaceable), `planet.pmtiles` (**3 GB** — doubles as deploy transport), `planet/` fused
    cells (14 GB — the one expensive-to-rebuild intermediate), caps/geojson/frame pins. ≈ $1/mo on
    R2/B2 (ballpark; R2's zero egress is the differentiator — verify pricing at pickup).
- **The big lever:** if Phase 5 goes no-go on a finer re-fuse, `glo30/` (551 GB) drops to
  per-country-on-demand like WorldCover — the upstream *is* the cloud store. Deferred the
  whole topic to after Phase 5.

## A z9 / z10 pyramid — z10 is BLOCKED ON DISK, z9 is reachable (analysed 2026-07-26)

- **The framing that governs everything: z10 is a planet RE-FUSE at ~2.5″, never a tiling flag**
  (PLAN Phase 2). The grid is `131072²` = exactly `512 × 2⁸`, so a deeper pyramid means re-fusing at
  4× linear and re-warping every layer onto `524288²` — **16× area on every intermediate**.
- **Measured cost model** (each stage ×16 from PROCESS's current numbers; storage projected off the
  real rasters on disk):

  | target | m/px | intermediates | build | tiles | archive | GEBCO upsample |
  |---|---:|---:|---:|---:|---:|---:|
  | z0–8 (live) | 305.7 | 111 GB | 2.7 h | 87,381 | 3.0 GB | 1.5× |
  | z0–9 | 152.9 | 443 GB | 10.8 h | 349,525 | 12 GB | 3.0× |
  | z0–10 | 76.4 | **1,773 GB** | **43.2 h** | 1,398,101 | 48 GB | 6.1× |

- **z10 does not fit, and that is the decision.** 1.73 TB of intermediates against a 1.8 TB disk
  already holding ~1.3 TB. Reclaiming every hero intermediate *and* WorldCover (~304 GB) still falls
  short, and `glo30/`'s 551 GB cannot go — it is what the re-fuse reads. This is a hardware
  precondition, not a scheduling one.
- **The single worst stage is the lake warp: 1:01:44 → ~16.5 h**, more than a third of the 43 h.
- **WebP changed the delivery side only.** A z10 archive is ~48 GB in WebP vs ~260 GB in PNG (5.2×,
  measured on the real pyramid: 16 GB → 3.0 GB). That is what would make a deep pyramid *shippable*
  at all. The intermediates are uncompressed working rasters and are unmoved — so "we use WebP now"
  does not reopen z10.
- **The aesthetic argument, which stands independently of cost.** GEBCO is 15 arc-sec — **measured on
  the file: 464 m/px**. Land has real headroom at z10 (30 m source into 76 m/px); the sea does not.
  Upsampling goes **1.5× → 6.1×**, so z10 makes land crisper while leaving the sea exactly as soft as
  it is now, **quadrupling the land/sea detail mismatch**. Bathymetry is signature, not optional
  (CLAUDE.md § Data sources), so this is a look regression bought with 43 hours.
- **The old precondition is CLOSED — do not re-raise it.** Locking z8 recorded a latent gap
  (`ocean`/`water`/`lakedepth` take their grid from `height_3857` but did not depend on it, so a
  re-fuse would leave `lakedepth` falsely fresh at old dimensions — a silently wrong composite) with
  *"fix before any re-fuse, not after."* It was fixed at the Antarctica re-fuse: `warp_needs_rebuild`
  is now `is_stale(...) or not grid_matches(...)`, exactly the prescribed dimension/bounds test.
  Reading the 07-17 entry alone still reads as outstanding; it is not.
- **Sequencing vs Tier 3 — Tier 3 first, and it is not close.** (a) z10 is blocked, so there is no
  ordering to decide; (b) Tier 3 is disk-cheap — terrain-RGB is a single-band elevation encode cut
  from the `height_3857.tif` that already exists, roughly the colour archive's size, not another
  1.7 TB; (c) they are **independent MapLibre sources with their own `maxzoom`**, so terrain need not
  match the colour pyramid's depth — displacement meshes are coarse and z8 terrain is ample. Building
  Tier 3 now is therefore not invalidated by a later re-fuse, and `warp_needs_rebuild`'s grid
  comparison would restage it correctly if one ever landed.
- **Measured 2026-07-27, correcting two estimates above; settled 2026-07-28.** (b) held, and better
  than projected: the built z0–8 terrain archive is **2.63 GB** against the colour archive's 3.0 GB
  (the ~3.3 GB projection was 25% high). (c) was wrong — **"z8 terrain is ample" confused what is
  built with what is reachable.** MapLibre picks the DEM zoom from the *declared* tile size, so depth
  is not a free choice: at `tileSize: 512` the DEM sits at `camera − 2` and **nothing past z6 could
  ever load** against `maxZoom: 8`; 256 reaches z7; only **128 reaches z8**, which is what shipped.
  z8 is the floor in any case — 256 tiles × 512 px = 131,072 px, exactly the master's grid, so
  anything deeper needs a re-fuse and lands squarely in the z9/z10 question above.
- **If depth is wanted, z9 is the reachable one:** 443 GB and ~11 h, fits today's free space, 3×
  GEBCO upsample rather than 6×. Not recommended, but it is the option that exists.
- **Revisit when:** a larger disk lands. Then re-derive from PROCESS rather than trusting this table —
  every number here is ×16 of a measured z8 stage, not itself measured. Ties to the `glo30/` retention
  lever above: a firm no-go on a finer re-fuse is what would let 551 GB drop to on-demand.

## Hero presentation — geography-conditional, and no universal design exists (analysed 2026-07-09)

Parked here from PLAN, where it was the last surviving open question with no tracked home.

The finding is a **trilemma: consistent / coherent / neighbour-free — pick two.** Cutout-cream framing
suits continental countries; real ocean suits islands; and most countries are *both* coastal and
bordered, so every single treatment reads flat at the margin for a large fraction of the set.

Not a look change in the locked-constants sense — the sun, ramps and exaggeration are untouched by it,
so nothing here threatens the freeze. It is a *presentation* choice made per gallery/globe surface,
which is why it never blocked anything.

## Kiribati presentation — the one antimeridian-deferred country (analysed 2026-07-24)

- **Trigger:** Kiribati is the sole in-scope country with no hero (`status="antimeridian"`,
  `config/countries.toml`), skipped by design 2026-07-09
  because its land is genuinely split — Gilberts 32% at 169–177°E (capital Tarawa) vs Phoenix+Line
  68% at 175–151°W (largest atoll Kiritimati), no dominant side. "No hero *for now*" lived only in
  a TOML note; this is its analysed home.
- **The decisive facts (checked, not assumed):**
  - **Low relief is NOT the disqualifier.** Kiribati averages ~1.8 m elevation (max ~3 m; only
    Banaba, in the Gilberts, is a raised 81 m island). But the other flat atoll nations — Maldives,
    Marshall Islands, Tuvalu, Nauru — **all rendered heroes**, and they read as striking
    bathymetry-dominant seamount fields (Maldives especially). So an atoll hero is on-aesthetic; the
    *only* real blocker is the antimeridian split.
  - **The render pipeline is single-frame end-to-end** — one slug → one bbox → one `frame.json` →
    one ortho render → one hero (`country_config.py:100-102` unpacks exactly one `[W,S,E,N]`;
    `scene_build.py` one camera/one render; no montage in `pipeline/compose/` — the only `montage()`
    is an unwired RGB experiment in `experiments/tile_chunk.py`).
  - **The frontend already degrades gracefully for a hero-less country** — `rendered:false`/`sizes:[]`
    is a first-class manifest state (`gen_manifest.py:97-98`, `lib/manifest.ts`), and both the
    gallery card (`index.astro:110-115`) and detail page (`[slug].astro:57-61`) render a placeholder.
    It is dead code today because Kiribati is dropped at the manifest step (`gen_manifest.py:82-83`
    `continue`s on `resolve()==None`).

### Viable option A — composited twin-panel hero (keeps Kiribati as one country)

- One Kiribati entry, one hero image holding two framed insets (Gilberts | Line+Phoenix), each a
  normal non-crossing frame rendering like Maldives/Marshall. Preserves country integrity (one
  sovereign nation = one gallery card) — the reason it beats sub-heroes (below).
- **Effort: HIGH.** The single-frame pipeline has no seam for it — needs new code at ~every stage:
  a `panels=[...]` config key + list validation (`country_config.py:67,100-102`); per-panel
  work/render subdirs through `stage_commands` (each panel is a *different* AEA projection with its
  own `frame.json`/heightfield/masks); **a brand-new compositor stage** (the keystone — nothing
  composites two RGBA renders today); a batch loop over panels; and per-panel border/overlay mapping
  (`overlay_borders.py`/`gen_borders.py` assume one `ortho_scale`). The two lobes are at very
  different scales — panel sizing is a real design choice, not automatic.

### Viable option B — gallery card, no hero (the low-effort default)

- Kiribati appears as a placeholder card + gazetteer + detail page, no relief hero — honest about a
  permanent deferral. Keeps it as one entry.
- **Effort: LOW, and entirely in the data/manifest layer** (presentation already exists): (1) emit an
  `rendered:false` manifest entry for antimeridian-deferred countries instead of dropping them
  (`gen_manifest.py:82-83`); (2) author a `bbox` — Kiribati has `status`/`notes` but no `frame`, and
  the gazetteer + globe fly-to read `country.bbox`; (3) guard the globe's `openPanel()`
  (`globe.astro:685`) which unconditionally requests `…-${sizes[0]}.webp` → a broken
  `kiribati-undefined.webp` for an unrendered entry; (4) optional distinct "deferred" copy — today's
  only placeholder string is "still rendering," which misrepresents a permanent state.

### Ruled out (do not re-litigate)

- **Wide antimeridian crosser** — dead on two counts: it needs the exact trans-180 wrap-math the
  2026-07-09 premise-check rejected (W>E frames, shifted VRTs, 4 files), *and* even a compact atoll
  frame is mostly ocean, so a ~40° crosser would be ~90% empty Pacific with two edge clusters. High
  cost, poor result.
- **Two separate sub-heroes** (the France+New Caledonia "separate heroes" precedent) — does **not**
  transfer. France's territories are distinct Natural Earth admin-0 units that enter scope naturally;
  Kiribati's island groups are one admin unit, so sub-heroes would need invented sub-country slugs
  with no backing NE geometry (borders/gazetteer have no matching entries) **and** fragment one
  sovereign nation into two gallery cards. More bespoke than option A and semantically wrong.

### Recommendation (as analysed)

- Option B if Kiribati should simply *appear* — cheap, honest, keeps the set complete at 204.
- Option A only if a Kiribati *hero* is wanted badly enough to build the pipeline's first multi-frame
  path (which would also unlock France+territories, USA+Alaska/Hawaii as composited heroes — the
  currently-dropped far-flung remainders). Worth pricing against just shipping those as the
  already-decided separate territory heroes.

## Worker placement hint near the APAC bucket — the prize shrank when lever A shipped (analysed 2026-07-26)

- **Was PLAN's lever B; demoted the day Workers Caching shipped.** Not rejected — the expected win
  is now uncertain in sign and size, which is not the same as zero, and it is one config line to try.
- **What changed:** pre-lever-A a cold tile paid **three sequential Marseille↔APAC reads**, so an
  explicit `placement.region` hint collapsed three long-haul round trips into roughly one — the
  basis of the 07-25 "380 ms → ~100 ms" estimate. Lever A left **one** read, and placement does not
  remove that leg, it **moves** it: today the request lands at MRS and the read crosses to APAC;
  under placement the request crosses to APAC and the read is local. **The tile bytes cross the
  same ocean exactly once either way.** What remains is R2's long-haul read overhead minus
  Cloudflare's backbone RTT.
- **Second discount:** the 07-25 Mumbai control did the same read in **~60 ms**, so the Indian
  visitors who land at BOM next to the bucket already have a fast read and gain nothing. The hint
  helps US/EU visitors and the maintainer's own route — a real audience, but not "everyone".
- **The blocker is gone**, so this is now cheap to test: Workers Caching shipped 2026-07-26, hits no
  longer run the Worker, and the docs are explicit that *"the cache is always consulted before Smart
  Placement is considered"*. Both the hint and the revert are config-only.
- **Design the experiment against the right control.** `r2;dur` is measured *inside* the Worker and
  is the only number a cache in front of the Worker cannot influence — but it also moves a lot on
  its own (median 419 ms vs 251 ms hours apart on 2026-07-26). Interleave placed and unplaced
  measurements, or the route's own drift will out-vote the effect.
- **Not the same thing as `mode: "smart"`**, which is available on all plans but needs *"consistent
  traffic from multiple locations"* Terrella does not have. An explicit region hint needs no warm-up.
- Two follow-ups belong with this work rather than before it: delete the now-redundant
  `caches.default` tile-body layer and its `X-Terrella-Cache` marker, and add
  `Access-Control-Expose-Headers: Cf-Cache-Status` so a browser-side check can tell HIT from MISS.

## Pinned low-zoom base layer — a deterministic floor under missing tiles (analysed 2026-07-26)

- **Trigger:** the hole-to-space fix shipped a flat `#47808F` background layer, which is a *colour*
  floor. It cannot be right over land — a gap over the Himalayas reads as ocean. This is the
  version that would be right everywhere, parked because the flat fill may well be enough.
- **Mechanism:** a second raster source over the same tiles with `maxzoom: 1`. Its ideal tiles are
  always the few world-covering ones, so they sit in the **in-view** set where the LRU cannot evict
  them — unlike the same tiles inside the main source, which are the first things dropped. That
  makes MapLibre's parent walk (`minCoveringZoom` reaches z0) *always* terminate, so an uncovered
  tile shows blurred earth with correct land and sea rather than a flat colour.
- **Measured cost (live tile Worker, 2026-07-26):** z0 = 1 tile **71 KB** · z1 = 4 tiles **273 KB**
  · z2 = 16 tiles **~1.4 MB**. One extra textured draw per frame.
- **Why not now:** 273 KB is ~4% back onto a cold window just cut 11.4 → 6.5 MB, and it lands in
  the critical path. Mounting it at first idle (as `countries.geojson` already does) avoids that
  but then it does not help first paint — which is exactly where the flat layer *does* help.
- **Downside to weigh:** at z6–z8 a z1 tile is magnified 32–128×, a heavy smear that may read worse
  than clean teal. Judge on the sphere, not in the abstract.
- **Decide at:** only if the flat fill is observed to read badly in practice. Strictly better than
  raising `maxTileCacheZoomLevels`, which buys a probabilistic win for **+264 MiB** of desktop GPU
  texture

## Mobile lightweight identify — "what is this?" without committing (analysed 2026-07-26)

- **Trigger:** the hover name chip shipped desktop-only, correctly — touch has no hover state to
  leave anonymous. But that framing hides a *different* gap on touch, and this is where it is parked
  so the chip is not mistaken for having covered it
- **The asymmetry:** on desktop, "what country is this?" costs a pointer move. On touch it costs a
  **2.2 s `fitBounds` flight + a card over the screen + a hero image fetch**, then a close and a
  re-orient. Same question, wildly different price — and the expensive one is on the platform with
  the least patience.
- **Already rejected, do not re-litigate without a new mechanism:** a **two-stage tap** (first tap
  identifies, second opens). It taxes the primary action for every user to serve a secondary one, and
  the primary action — flying to a country and seeing its hero — is the point of the globe.
- **Unexplored shapes, if this is ever reopened:** long-press to identify (leaves tap alone, but is
  undiscoverable and collides with the OS text/context menu); a persistent "identify mode" toggle in
  the view bar (discoverable, costs a control slot for a rarely-used mode); or naming the country in
  the card *faster* — the name is known at tap time, so the card could paint its `<h2>` immediately
  and let the image and the flight land after, which is a **latency fix rather than a new gesture**
  and is probably the cheapest real improvement here.
- **Why not now:** unmeasured. Nobody has reported the problem, and the card already names the
  country within a few hundred ms of the tap. **Verify the premise on a real phone before designing** —
  the flight is the reward, not a tax, and this may be a problem only on paper.

## The tier ladder is more permissive than it reads (analysed 2026-07-26, **FIXED 2026-07-28**)

**Closed as Tier 3 Step 1**.
Kept here because the analysis below is what the fix was built from, and because one of its own
claims turned out to be wrong. Outcome per gap: the threshold became **`<= 4`**; the softwareGpu
asymmetry was closed by giving `Base.astro` the same floor; the Safari/Firefox blindness was
**deliberately left optimistic** and handed to the runtime ladder, which gained a `disable-terrain`
rung — so the deferral note's last line turned out to be the right instinct after all.

**Corrected 2026-07-28:** "clamped at both ends" is wrong. There is no upper clamp in current
Chrome — the W3C text describes one at 8 GiB and Chrome does not apply it (a 29 GiB machine
measures **32**), and the rounding is to the *nearest* power of two, not down. Neither changes the
conclusion below, which rests only on there being no value between 2 and 4.

- **Trigger:** the capability probe looks like it protects weak devices. Measured against the spec and
  the code, it barely does. Deferred rather than fixed — the question is a product one (*is `full` the
  right default for these visitors?*), and nobody has reported a bad experience.
- **`capability.ts:119` is `lowMemory = deviceMemory < 4`** — but **`navigator.deviceMemory` is
  spec-quantised to powers of two** (0.25 / 0.5 / 1 / 2 / 4 / 8, clamped at both ends). So `< 4`
  **cannot** mean "under 4 GB". It means **2 GB or less**. There is no 3.
- **It is Chromium-only.** Absent → `Infinity` → never `lowMemory`, so **every Safari and Firefox
  visitor gets `full`** regardless of the machine.
- **The Moto G Power reports exactly 4** → `full`. That is Lighthouse's own mobile reference device,
  i.e. the mobile score is measured on a device the ladder treats as healthy.
- **A second, independent gap:** `Base.astro`'s pre-paint guard gates `/globe/` on `webgl2()` alone,
  while `decideTier`'s `capable()` also requires `!softwareGpu`. A software-rasterizer visitor who
  deep-links `/globe/` is therefore never bounced to the gallery, and `globe.astro` reads
  `currentTier()` only to decide whether to spin — so they get a full globe on SwiftShader.
- **If reopened, decide these separately:** the memory threshold is a *tuning* question (2 GB is a very
  low bar; `<= 4` would catch mid-range Android), the Safari/Firefox blindness is a *coverage* question
  (there is no portable memory signal — `hardwareConcurrency` is the only widely-supported hint), and
  the softwareGpu asymmetry is simply a **guard that does not match the function it mirrors**.
- **Verify before acting:** instrument a real mid-range phone rather than trusting the ladder's
  intent. The FPS watchdog already degrades at runtime, so the gate being permissive may cost nothing.
- **`hardwareConcurrency` was investigated and REJECTED, 2026-07-28** — do not re-propose it as the
  portable substitute this note suggests. **WebKit clamps it to 8 on macOS and 2 on iOS**, so every
  iPhone and every iPad Pro reports 2 while a budget Android reports 8: as a device-strength signal
  it is not merely weak, it is *inverted*. MDN says the same in general terms ("don't treat this as
  an absolute measurement of the number of cores"), and Safari 26 blocks known fingerprinting
  scripts from reading it at all.

## The tier picker is a radiogroup made of toggle buttons (analysed 2026-07-27, DEFERRED)

- **Trigger:** found while adding tooltips to Lite / Globe / Full. Verified in the live DOM, not read
  off the source: `.quality-fab` carries `role="radiogroup"`, and its three children have
  **`role: null`, `aria-pressed`, and no `aria-checked`**.
- **Why it is wrong:** an ARIA `radiogroup` must own elements with `role="radio"`. A plain button with
  `aria-pressed` inside one is announced as a *toggle button within a radio group* — incoherent — and
  the group loses the positional "1 of 3" that makes a radio group worth using in the first place.
  The three tiers are genuinely mutually exclusive, so radiogroup is the right *intent*; only the
  children are wrong.
- **Why it was not just fixed:** the correct markup is `role="radio"` + `aria-checked`, but the filled
  "this one is active" styling is `.view-bar button[aria-pressed="true"]` — **one selector shared with
  Borders, Spin and Focus**. Switching the tier buttons to `aria-checked` silently un-fills them
  unless the CSS is split at the same time. So it is a markup + CSS change with a visual regression
  risk, not the attribute swap it looks like.
- **If reopened:** change all three children together, split the fill rule into
  `[aria-pressed="true"], [aria-checked="true"]`, and check the active tier still reads filled on the
  globe, the gallery **and** a hero page. Keyboard arrow-key navigation between radios is the other
  half of the radio contract and is currently absent — decide whether to implement it or drop
  `radiogroup` for a plain group, which is honest and costs nothing.

## Landing-page "poster mode" (deferred 2026-07-26, never scoped)

- **What it is:** an optional flourish — a landing-page beauty shot of the sphere, styled as a print
  poster rather than as an interactive map. Recorded here verbatim from PLAN because it was never
  scoped beyond one line, and PLAN was its only home.
- **Status:** a weekend experiment, explicitly optional. Nothing depends on it and nothing is blocked
  by it. The gallery already opens on hero renders, so this is decoration on decoration.
- **If reopened:** decide first whether it replaces the gallery's current entry point or sits beside
  it — that is the only part with a real cost, since the gallery is the Tier-1 fallback everyone gets
  while the capability probe runs.

## Raster tile resolution vs device pixel ratio (analysed 2026-07-25)

- **Trigger:** the question of whether serving 512 px tiles "@2x" is wasted on a DPR-1 desktop, and
  whether phones get enough for DPR 3. The answer inverts the intuition, so it is worth parking
  rather than discarding.
- **Mechanism, measured on the live globe:** the source declares `tileSize: 256` for 512 px
  assets, so MapLibre requests `z_map + 1` and **a source tile always covers 256 CSS px, at every
  zoom**. Confirmed at map zoom 1.3 → z2/z3 requested, and the canvas backing store equals its CSS
  size on DPR 1 (ratio 1.00, i.e. MapLibre is not supersampling the canvas).
- **The scheme is centred on DPR 2, not DPR 1:**
  - DPR 1 — 512 px into a 256 device px slot: **2× oversupplied** (4× the pixels).
  - DPR 2 — 512 into 512: **exactly 1:1**.
  - DPR 3 — 512 into 768: **0.67×, upscaled and softer than native.**
  - So **modern phones are the UNDER-served ones**, not the over-served ones. (DPR 1 measured;
    the other two follow from the same CSS-px mechanism and were not measured on real devices.)
- **The DPR-1 oversupply is not pure waste.** The GPU minifies 512→256 through mip/bilinear
  filtering, which is 2×2 supersampling on exactly the high-frequency multidirectional hillshade
  this look rests on — and more so on a globe, where tiles are warped onto a sphere and sampled
  anisotropically toward the limb. It errs in the safe direction: oversampling looks good,
  undersampling looks blurry.
- **Why there is no automatic fix:** MapLibre raster sources have **no DPR negotiation** — no
  `@2x` URL convention, no srcset equivalent. Tile selection is computed in CSS pixels and is
  DPR-blind by design. `tileSize` is the only lever, and it is global.
- **The lever, if picked up:** `tileSize: devicePixelRatio >= 2 ? 256 : 512` at source
  construction (DPR is known before the map is built). DPR-1 clients drop a zoom level → **4×
  fewer tile pixels and 4× fewer tile requests**, the latter mattering against the free tier's
  ~2,500 cold-visit/day request ceiling. DPR ≥2 is untouched.
- **Why it is parked and not done:** it is a **look change on DPR-1 screens** (supersampled →
  native 1:1, more aliasing), and look changes here get eyes on them at full scale before they
  ship. It is also small: tiles are ~2.6 MB of the cold window at q95, so it saves ~2 MB for
  desktop visitors — against the ~80 MB the hero rungs took off the gallery.
- **Not proposed:** a 1024 px pyramid to serve DPR 3 at 1:1. That is 4× the tiles for the band
  that is merely soft, not broken.
- **The polar caps solved this exact mechanism, and the tiles still have not** (2026-07-25). The cap
  now picks its texture from its projected on-screen size × the canvas backing ratio, so DPR is
  handled per-device with no look change
  reuse that: MapLibre's raster source has no DPR negotiation and `tileSize` is global, which is why
  the lever above is a one-line `tileSize` switch rather than a picker. Worth re-reading that
  implementation before picking this up — it settles what "demand" means here, and the
  `canvas.width / canvas.clientWidth` ratio is the right input for both.

## Brotli sidecars for the text-like assets (analysed 2026-07-25, BLOCKED)

- **Trigger:** measuring what the edge actually negotiates for `countries.geojson`. It picks the
  *worst* of the three encodings it offers.
- **Measured, same source file:** edge zstd **2.98 MB** · edge gzip 2.61 MB · static brotli-11
  **1.56 MB**. `boundary_lines.geojson` goes 642 → 376 KB the same way. Together ≈ 1.5 MB off the
  cold window.
- **BLOCKED on a correctness question, not on effort:** one stored R2 object cannot
  content-negotiate. Serving a `.br` sidecar means either a second object plus request-time
  selection, or storing only brotli and breaking any client that does not advertise it.
- R2's `Content-Encoding` passthrough behaviour is **undocumented** in the docs search — it needs a
  probe object before anything is designed on top of it.
- `DecompressionStream` has **no brotli**, so decompressing it in page JS is not an escape hatch.
- **Low priority on purpose:** this is deferred-to-idle transfer (~0.4 s), entirely off the
  first-paint path. The polar caps are the larger and simpler target → PLAN Phase 4.

## Vector-tile countries (analysed 2026-07-25 — the stated reason was FALSIFIED)

- **Trigger:** "the 9.39 MB `countries.geojson` costs a big JSON parse, so make it vector tiles."
  That reason does not survive measurement.
- **Falsified, measured on the live page:** `JSON.parse` of the 9.39 MB is **19 ms**; TextDecode
  4 ms; the geometry walk ~0 ms. Parsing is not the cost and never was.
- **What the ~0.41 s actually is:** MapLibre **tessellation** — turning polygons into GPU
  triangles. That figure was inferred by subtraction and flagged as not directly measured.
  **NOW MEASURED, and it holds: ~355 ms.**
  - Chrome **LoAF script attribution** on production names one block: `sourceCharPosition`
    **1,005,956** (99.9% through the chunk, i.e. *our* page module, not MapLibre's vendor bulk),
    `invokerType: resolve-promise`, invoker `Response.json.then` — exactly the
    `addCountries → addBorders → addCountryHighlight` chain after `countries.geojson` resolves.
  - **365 / 357 / 352 / 348 ms over four cold loads — ±2.5%**, and **~54% of all long-frame script
    time** (total 640–686 ms). Unthrottled desktop; 4× CPU throttle would put it near 1.4 s.
  - **Not yet split** between the three `addSource` calls and our two geometry walks. `outlinesFrom`
    builds a full second copy of every ring as `MultiLineString`, so MapLibre ingests the geometry
    **twice** — that duplication exists to fix the stray-gold-meridian bug and is the first thing to
    measure if this is reopened.
- **Consequence for the design space:** only *geometry reduction* (fewer/simpler polygons) touches
  tessellation. Compression, a faster parser, and a binary container all miss it entirely.
- **"The transfer side is already handled" was true when written and is now the weakest claim here.**
  It is deferred to first idle and gzipped 9.39 → 2.99 MB, but the Lighthouse pass
  (2026-07-25) puts it at **3.08 MB — the single largest item in the globe's cold window, bigger
  than all 36 tiles combined (2.65 MB)**, now that the polar caps dropped to 0.15 MB. Shrinking
  everything around it promoted this to the top of the payload.
- **So the idea is alive, on a different reason than it started with.** Do not resurrect the parse
  argument (19 ms, falsified); the case is transfer size plus tessellation. Both are touched only by
  geometry reduction, which is exactly what vector tiles do.
- **But weigh it against what the main thread costs:** ~4.8 s of script time on throttled mobile,
  and it is **execution, not parse** — measured 2026-07-26 by two independent instruments
  (Lighthouse `bootup-time`: **4,833 ms evaluation vs 2 ms parse**; Chrome LoAF: **0 ms compile**).
  constraint, so measure the tessellation share directly before spending effort here.
- **That measurement strengthens this entry rather than weakening it:** tessellation *is* execution,
  which is the term shown to dominate — so geometry reduction remains the only lever that touches
  either half of the case, and compression / a faster parser / a binary container still miss both.
- Related: the same `countries.geojson` is the input to Kind 1 look presets above, so any
  re-encoding decision should be taken once, for both.

## AVIF hero variants (analysed 2026-07-23, premise restated 2026-07-25)

- **Trigger:** the astro:assets audit during the 7.1.3 bump — the one genuine feature we forgo by
  bypassing it is AVIF format negotiation, and it belongs in *our* pipeline, not a second
  optimizer re-encoding ratified pixels (one encoder-quality owner).
- **The baseline this was analysed against has MOVED — re-measure before costing it.** It assumed
  WebP q85 across three rungs (France 0.7 / 2.3 / 6.9 MB at 1920/3840/native). The ladder is now
  **six rungs (640/960/1280/1920/3840/native) at a split quality — q85 up to 1920, q95 above** —
  so both the file count and the per-file baseline are different, and the AVIF comparison has to
  be made against q95 where it matters.
- **Idea:** AVIF siblings of the existing rungs in `hero_variants.py`; gallery + globe panel
  switch to `<picture>` with `type` fallback. Rule-of-thumb gain ~20–30% smaller at similar
  quality — **unmeasured on our content; measure 2–3 heroes before deciding anything.**
- **Costs to check at pickup:** GDAL AVIF driver present in our build (needs libavif); AVIF
  encode time — now × ~1,200 hero files rather than ~612, and the q95 rungs are the slow ones;
  variant store growth; web markup change is small.
- **Natural decision point:** the Phase 4 Lighthouse pass, where transfer sizes get audited
  anyway. Not before.
- **Note the tile pyramid is NOT a candidate for the same treatment** — it is one archive with one
  declared tile type, so a `<picture>`-style negotiation has nowhere to live.

## Hero presentation — large-country warp & small-island exaggeration (analysed 2026-07-24)

Raised while reviewing the gallery after the sea-sync sweep (the sea look was approved;
these are pre-existing framing concerns). The country-extent concern is being SOLVED separately
by the subject-spotlight "Focus" toggle (compose-layer, no re-render). These two remain, and BOTH
require a re-render, so they are parked until a re-render is on the table anyway.

### Large countries warp — the Russia equal-area-conic "fan"

- **What:** each hero is one Albers equal-area conic centred on its frame; for a ~160° longitude
  span (Russia) the conic splays into a wedge with big empty margins. **China (~60°) looks fine** —
  a mild trapezoid — so this is ~4-5 extreme countries (Russia worst; Canada, USA, Kazakhstan,
  Greenland), not "large countries" broadly.
- **Why it's low-ROI:** the fan is *inherent* to equal-area for a transcontinental span — any single
  projection either fans (conic) or grossly distorts area (Mercator). Levers are weak: trim the frame
  margin; bespoke-frame the few worst to a representative region (breaks the "whole country" promise);
  or accept it as honest cartography. **Rec: accept, or just trim margin. Do not overhaul the projection.**

### Small steep islands look like "pinecones" (Saint Lucia, Dominica)

- **Measured root cause:** exaggeration is a global **15×** applied to real height ÷ width, so visual
  steepness = `15 × (relief / frame-width)`. A 950 m peak on a 30 km island → ~0.47 (peak stands ~half
  the frame tall → bristly); a continent → ~0.025 (gentle). Same constant, wildly different look.
- **The principled fix = adaptive exaggeration:** taper the factor for small high-relief-ratio frames.
  This makes the *visual* relief MORE consistent across the gallery, not less — the "tuned once, applied
  globally" rule (ART.md) is what currently makes the look *inconsistent*. Bounded cost: only ~20-30
  small steep islands re-render (~1 h, not a planet sweep). Touches the FROZEN `render_prep.py`
  (`EXAGGERATION = 15.0`), so it wants the sea-sync freeze lifted (ratified) first.
- **Note:** validated that atoll/island heroes themselves read well (Maldives/Marshall are striking) —
  the problem is only over-exaggeration of *steep* small islands, not small frames per se.
