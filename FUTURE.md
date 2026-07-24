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
- **Numbers depend on:** the z0–8 pyramid ≈ 15–16 GB and ~87k tiles per look; composite-stage
  restage ~29 min (PROCESS § what a change costs); `countries.geojson` sub-pixel since the
  hover-outline fix (HISTORY § the blocky hover outline).

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
  **Per look: ~33 min compute** (SVF + composite + cut + pack/convert + caps) **and +15 GB
  storage**; web swaps the `pmtiles://` URL + cap pair. Scales to a curated few, not to many.
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
- Kind 2 only when a specific second look earns its 15 GB; pay the parameterization day then.
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
    are irreplaceable), `planet.pmtiles` (15 GB — doubles as deploy transport), `planet/` fused
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

## AVIF hero variants (analysed 2026-07-23)

- **Trigger:** the astro:assets audit during the 7.1.3 bump — the one genuine feature we forgo by
  bypassing it is AVIF format negotiation, and it belongs in *our* pipeline, not a second
  optimizer re-encoding ratified pixels (one encoder-quality owner).
- **Idea:** AVIF siblings of the existing rungs in `hero_variants.py` (WebP q85 today — France
  0.7 / 2.3 / 6.9 MB at 1920/3840/native); gallery + globe panel switch to `<picture>` with
  `type` fallback. Rule-of-thumb gain ~20–30% smaller at similar quality — **unmeasured on our
  content; measure 2–3 heroes before deciding anything.**
- **Costs to check at pickup:** GDAL AVIF driver present in our build (needs libavif); AVIF
  encode time × ~612 files (AVIF encoders are slow); variant store grows ~+70%; web markup
  change is small.
- **Natural decision point:** the Phase 4 Lighthouse pass, where transfer sizes get audited
  anyway. Not before.

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
