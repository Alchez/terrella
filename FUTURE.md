# FUTURE — the v2 parking lot

Ideas deliberately **not** planned: analysed enough to record, parked without commitment. This is
not PLAN.md — nothing here has a phase or a checkbox, and nothing here is promised. When an idea
graduates, it moves to PLAN and this file keeps a one-line pointer. Each entry carries the date of
its analysis and the facts its numbers depend on — check both before trusting an old entry, and
grep HISTORY before re-arguing anything an entry says was already decided.

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
  `countries.geojson` sub-pixel since the hover-outline fix (HISTORY § the blocky hover outline).

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
    are a rejected shape (HISTORY § chasing the hero's "softness": "remote COG is the wrong shape
    for a full sequential scan").
  - The **~56 GB worth putting in a cloud is the backup set, not an offload**: heroes+raws+variants
    (27 GB real bytes, hardlink archives ~free; Cycles isn't bit-deterministic so ratified pixels
    are irreplaceable), `planet.pmtiles` (**3 GB** — doubles as deploy transport), `planet/` fused
    cells (14 GB — the one expensive-to-rebuild intermediate), caps/geojson/frame pins. ≈ $1/mo on
    R2/B2 (ballpark; R2's zero egress is the differentiator — verify pricing at pickup).
- **The big lever:** if Phase 5 goes no-go on a finer re-fuse, `glo30/` (551 GB) drops to
  per-country-on-demand like WorldCover — the upstream *is* the cloud store. Rohan deferred the
  whole topic to after Phase 5.

## Kiribati presentation — the one antimeridian-deferred country (analysed 2026-07-24)

- **Trigger:** Kiribati is the sole in-scope country with no hero (`status="antimeridian"`,
  `config/countries.toml`), skipped by design 2026-07-09 (HISTORY § Antimeridian: no wrap-math)
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

## Raster tile resolution vs device pixel ratio (analysed 2026-07-25)

- **Trigger:** Rohan asked whether serving 512 px tiles "@2x" is wasted on a DPR-1 desktop, and
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
  handled per-device with no look change → HISTORY § the polar caps ship 156 KB. The tiles cannot
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
  triangles. That figure is inferred by subtraction, **not directly measured**; measure it before
  using it to justify any work.
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
- **But weigh it against what the same pass found on the main thread:** script evaluation is
  5,702 ms on throttled mobile, **4,064 ms of it MapLibre's own init**, versus a TBT of 2,120 ms.
  Payload is no longer the globe's binding constraint, so measure the tessellation share directly
  before spending effort here. → PLAN § Lighthouse pass
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
  be made against q95 where it matters. → HISTORY § the ladder ships against measured layout.
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

Raised by Rohan reviewing the gallery after the sea-sync sweep (the sea look he approved;
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
