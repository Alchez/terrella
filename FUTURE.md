# FUTURE: the v2 parking lot

Ideas deliberately **not** planned: analysed enough to record, parked without commitment. This is not the plan: nothing here has a phase or a checkbox, and nothing here is promised. When an idea graduates, it moves to the living plan and this file keeps a one-line pointer. Each entry carries the date of its analysis and the facts its numbers depend on: check both before trusting an old entry, and grep HISTORY before re-arguing anything an entry says was already decided.

## How this file is organised

- **Every entry carries a one-line stanza under its heading**: its state, who can act on it, and the event that would reopen it. `grep -n "^> " FUTURE.md` lists all of them at once.
- **Physical order in the body carries no meaning.** It is the order things were written down. The index below is the only place order says anything.
- **Three states, and the boundary between them is what an entry needs before anyone can start.**
  - **OPEN**: analysed and parked on a choice. Someone could begin today.
  - **BLOCKED**: a named precondition has to land first, and wanting it more does not move it. A bigger disk, an upstream release, a probe nobody has run.
  - **OBSERVED, NOT ANALYSED**: seen once and written down before it was forgotten. The next action is a measurement, not a decision.
- **An idea that ships, gets fixed or gets built leaves this file entirely**, and its record is the HISTORY entry written when it landed. Kept here past that point it reads as open work to everyone except the person who closed it.
- **An idea that was REJECTED is the exception and stays**, because the reasoning that killed it is what stops it being proposed again, and nothing else in a clone carries that.
- **Tags say who can act, never what it is worth.** `no-data-needed` runs on a fresh clone; `needs-render-store` and `needs-gpu` do not, per the table in CONTRIBUTING; `look-call` changes what the site looks like, which is a judgement the maintainer makes by eye; `product` is a question rather than a piece of work.
- **There is deliberately no impact or effort ranking.** Most entries state in their own words that they are unmeasured or uncosted, so a rank would be invented rather than recorded, and nothing would go red when it drifted.
- **The reopening trigger is the axis worth having instead, because it clusters.** One event makes several unrelated entries worth doing at once, which no ranking can show you, and the index groups them that way.

## Index

### OPEN, and a named event would reopen these

**A hero re-render is scheduled.** Three entries, and they are one job.

- [Heroes record no recipe](#heroes-record-no-recipe-so-nothing-on-disk-says-which-rig-made-any-of-the-203-analysed-2026-08-21-parked) · needs-render-store
- [Large-country warp and small-island exaggeration](#hero-presentation-large-country-warp--small-island-exaggeration-analysed-2026-07-24) · look-call · needs-gpu
- [Hero and block renders differ in their contents](#hero-and-block-renders-differ-in-their-contents-when-only-their-projection-should-raised-2026-08-24) · look-call · needs-gpu

**An accessibility pass.** Each says to do the other at the same time, for one round of judgement.

- [`forced-colors` is unhandled](#forced-colors-is-unhandled-and-the-rails-icons-are-the-thing-it-breaks-analysed-2026-08-02) · no-data-needed
- [The tier picker is a radiogroup made of toggle buttons](#the-tier-picker-is-a-radiogroup-made-of-toggle-buttons-analysed-2026-07-27-deferred) · no-data-needed

**Someone reports it, or a real device gets measured.**

- [Pinned low-zoom base layer](#pinned-low-zoom-base-layer-a-deterministic-floor-under-missing-tiles-analysed-2026-07-26) · look-call
- [Mobile lightweight identify](#mobile-lightweight-identify-what-is-this-without-committing-analysed-2026-07-26) · product

**An authoritative summit source is adopted.**

- [The detail card cannot state an elevation the DEM does not know](#the-detail-card-cannot-state-an-elevation-the-dem-does-not-know-analysed-2026-08-27) · product · needs-data

**A transfer audit, where sizes get looked at anyway.**

- [AVIF hero variants](#avif-hero-variants-analysed-2026-07-23-premise-restated-2026-07-25) · needs-render-store

**Hero variants get regenerated for some other reason.**

- [The ladder is keyed to the long edge, and `srcset` selects on width](#the-ladder-is-keyed-to-the-long-edge-and-srcset-selects-on-width-analysed-2026-08-02) · needs-render-store

**The finer-re-fuse question gets settled, either way.**

- [Cloud offload / offsite backup](#cloud-offload--offsite-backup-analysed-2026-07-23-revisit-after-phase-5)

### OPEN, with nothing named that would reopen them

Not a lower tier. Nobody has written down what would make them worth doing, and that absence is itself the open question.

- [Shadow saturation on the land is a shading term](#shadow-saturation-on-the-land-is-a-shading-term-and-the-sea-that-was-ratified-rides-mostly-on-lit-pixels-analysed-2026-08-27) · look-call · needs-gpu
- [The display face swaps in at a different width](#the-display-face-swaps-in-at-a-different-width-and-the-metric-matched-fallback-is-inert-analysed-2026-08-02)
- [Flat ice saturates the snow ramp](#flat-ice-saturates-the-snow-ramp-and-the-curve-was-fitted-before-antarctica-existed-analysed-2026-07-29) · look-call · needs-render-store
- [The snow persistence source paints salt playas white](#the-snow-persistence-source-paints-salt-playas-white-and-nobody-has-counted-them-analysed-2026-08-25) · look-call · needs-render-store
- [Look presets: user-selectable globe styles](#look-presets-user-selectable-globe-styles-analysed-2026-07-23) · look-call · product
- [Hero presentation: geography-conditional](#hero-presentation-geography-conditional-and-no-universal-design-exists-analysed-2026-07-09) · product
- [Kiribati presentation](#kiribati-presentation-the-one-antimeridian-deferred-country-analysed-2026-07-24) · product
- [Worker placement hint near the APAC bucket](#worker-placement-hint-near-the-apac-bucket-the-prize-shrank-when-lever-a-shipped-analysed-2026-07-26)
- [Landing-page "poster mode"](#landing-page-poster-mode-deferred-2026-07-26-never-scoped) · product
- [Raster tile resolution vs device pixel ratio](#raster-tile-resolution-vs-device-pixel-ratio-analysed-2026-07-25) · look-call
- [Metatile batching](#metatile-batching-collapse-round-trips-instead-of-running-more-of-them-analysed-2026-08-01)
- [Small debts and open calls](#small-debts-and-open-calls-carried-out-of-the-working-plan-parked-2026-08-24) · mixed, and its own subsections carry the states

### BLOCKED, on a precondition that has to land first

- [A z9 / z10 pyramid](#a-z9--z10-pyramid-z10-is-blocked-on-disk-z9-is-reachable-analysed-2026-07-26) · a bigger disk
- [Brotli sidecars for the text-like assets](#brotli-sidecars-for-the-text-like-assets-analysed-2026-07-25-blocked) · an R2 `Content-Encoding` probe nobody has run
- [The polar caps are a texture](#the-polar-caps-are-a-texture-because-maplibre-allows-nothing-else-and-the-ceiling-is-webps-analysed-2026-08-07) · MapLibre gaining a TileMatrixSet source
- [MapLibre's WebGPU backend](#maplibres-webgpu-backend-irrelevant-to-our-memory-problem-and-not-the-no-op-we-recorded-analysed-2026-07-29) · MapLibre publishing a timeline
- [GDAL 3.13](#gdal-313-assessed-and-skipped-analysed-2026-07-23) · a full-restage boundary, and rasterio bundling 3.13
- [The layer-rename alias cannot be deleted yet](#the-layer-rename-alias-cannot-be-deleted-yet-and-the-clock-is-longer-than-it-reads-analysed-2026-08-31) · a year of `immutable` URLs expiring, then a production log read

### OBSERVED, NOT ANALYSED, so the next action is a measurement

- [A cold page load at high zoom paints a flat fill and never recovers](#a-cold-page-load-at-high-zoom-paints-a-flat-fill-and-never-recovers-observed-2026-08-11-not-analysed)
- [Tiles "jump" a little when panning around a pole](#tiles-jump-a-little-when-panning-around-a-pole-observed-2026-08-11-not-analysed)

## The detail card cannot state an elevation the DEM does not know (analysed 2026-08-27)

The globe's detail card carries a country's name, its continent and a link, and nothing else. Elevation is the fact that would actually belong on a relief site, so it was scoped and then dropped, on Rohan's rule that a card reporting a wrong value for any country should not ship. What follows is the measurement, so nobody re-derives it.

**Two error sources, and they have OPPOSITE SIGNS, which is what makes this worse than either alone.**

- **A country's frame is not the country.** The manifest's `bbox` is the authored hero frame, a composition rectangle, so it holds whatever neighbour shares the box. Measured against published summits, over the per-country heightfields already cut to that frame: Monaco **+981 m**, San Marino **+663 m**, Liechtenstein **+245 m**, Switzerland **+171 m**, Vatican **+91 m**. Switzerland's figure is Mont Blanc, which is in France. A Natural Earth polygon burn fixes this half, and `vector_raster.py` already owns reproject-and-burn.
- **The raster clips summits, and the planet master clips them twice as hard.** A pyramidal peak is averaged across a cell, so the maximum is never the summit. At the hero heightfields' posting: Nepal **-138 m** (Everest reads 8,711 against 8,849), Bhutan -79, Uruguay -8. At `height_3857.tif`, which is **305.7 m/px** and the durable source a stage would have to read, Nepal reads **8,586 m**, so **-263 m**. No mask reaches this.
- **They cancel.** Switzerland's frame reads 4,725 m at the planet master against a published 4,634: contamination pushing up, clipping pulling down, landing on a plausible number that is wrong for two reasons at once. A spot check would pass it.

**So the reopening event is a summit AUTHORITY, not a finer re-fuse.** Even GLO-30 at 30 m is 138 m short on Everest, so resolution alone never closes this. Natural Earth's row carries `WIKIDATAID` for every country, which is the cheapest route to a published summit name and height, and it brings a new data dependency with its own licence question and an offline fetch.

**What could ship with no new data, if the claim changes rather than the method:** state the relief span of the rendered view instead of a fact about the country. The frame IS what the card's link opens, so contamination stops being an error and becomes the subject, and nothing in the sentence can be falsified. Rejected for now because it answers a question nobody asked.

## The display face swaps in at a different width, and the metric-matched fallback is inert (analysed 2026-08-02)

> **OPEN** · no-data-needed. Options priced, none taken. Nothing named would reopen it, and the entry says which measurement comes first.

- **State at analysis:** Fraunces is self-hosted at `font-display: swap`, so the browser lays text out in a substitute and re-lays it when the real face arrives. Measured on the gallery heading: **103 px in the fallback, 117 px in Fraunces**: a 13.6% width change after first paint.
- **The mitigation is present and does nothing.** Astro generates a metric-matched fallback face at `size-adjust: 115.4462%` with `ascent-override`/`descent-override`, which is exactly the right mechanism, but its source is **`src: local("Times New Roman")`**, and that family resolves on neither Linux nor Android, so the face errors and the browser falls through to plain `Georgia, serif` at 100%. Confirmed in the built page: the fallback faces report `status: "error"` while the real ones report `"loaded"`.
- **There is no configuration route to fixing it.** Building with `fallbacks: ['Noto Serif', 'Georgia', 'Times New Roman', 'serif']` still emits a Times New Roman face: Astro picks from its own metrics table regardless of the order given, and that table does not carry the families Android and Linux actually ship.
- **What it still costs, now that the gallery masthead has been given slack:** `/about/` **0.0936** and the longest country pages **0.0191**, both cold-load only and both inside the "good" band (≤ 0.1). The gallery reads 0.0000 because its header row now has 31–97 px spare at every width it serves, not because the swap stopped happening: it still does, on every cold visit.
- **Options priced, none taken:**
  - `display: 'optional'`: one line, and measured at **0.0010 cold on the gallery before the masthead fix**. Deterministic, but it means the display face **does not render at all** on a cold slow visit: measured `h1` stayed at the fallback's 103 px. Renders on repeat visits.
  - Hand-written fallback faces in `global.css`, one `local()` per platform family with its own `size-adjust`. Keeps Fraunces on every visit. The measured ratio here is 113.6%, close to Astro's 115.4% for Times New Roman, but each platform's family needs its own number and only the Linux one is verifiable on this box.
  - **Preloading is measured and REJECTED, do not revive.** `<Font preload />` cost **+100 ms FCP and +164 ms LCP** and did not get the face in inside the block window on a 1.6 Mbps link, so it buys nothing in either `swap` or `optional`.
- **The one thing to measure first if this is picked up:** whether `optional` renders Fraunces on an ordinary connection. Everything above was measured at the Lighthouse mobile throttle (1.6 Mbps, 150 ms RTT), where it does not.

## The ladder is keyed to the long edge, and `srcset` selects on width (analysed 2026-08-02)

> **OPEN** · needs-render-store · **reopens when** hero variants get regenerated for some other reason. The symptom already shipped a fix; what is left here is the root cause.

- **State at analysis:** the variant ladder is a fixed tuple of LONG EDGES (640/960/1280/1920/3840 + native). `srcset` selects on WIDTH. For a landscape hero those coincide; for a portrait one the delivered width is `rung × aspect`, so the same rungs give Albania 297/446/595/892/1786 and a DPR-3 phone falls through the doubling gap onto 3840: across the q85 → q95 boundary.
- **A per-country fill rung has SHIPPED as the approximation**: `hero_variants.fill_rung` adds the smallest 512-multiple long edge delivering 1,187 px of width, closing 25 of the 27 affected countries for 19.0 MB. What remains here is the root cause, not the symptom.
- **The principled fix is to key the ladder to WIDTH.** Generate variants at target widths, so every country, portrait or landscape, has rungs exactly where `srcset` selects. It **deletes** code: `variantWidth()` in `index.astro` exists only to translate long-edge keys into widths, and under a width ladder the descriptor is just the rung.
- **It is the only thing that can serve Chile (0.307) and Maldives (0.234)**, which need long edges of 3,867 and 5,064, above the inspection floor, so no fill rung below 3840 can reach them, and one above it would be a q95 file delivered as a thumbnail.
- **It would also let `quality_for` key on the right quantity.** Today it takes the long edge, which for a portrait file is its HEIGHT, so a 3840-long-edge hero only 1,786 px wide is charged inspection quality for a thumbnail. Under a width ladder the discriminator is the same number `srcset` selects on. Note the tension to resolve first: the *same file* also serves the country page full-screen, where q95 is right.
- **Compute is not the obstacle, storage might be.** Measured: hero variants **6 min** at `--jobs 8`, spotlight **1m45s**, borders **7m21s** (and a border rung costs a full regeneration). But a portrait country gets TALLER files for the same width, so the served store grows, and **there is no R2 headroom left to grow into**; the free tier is spent, so any growth is overage from the first byte. It rounds up to whole GB-months at $0.015, which makes this cheap rather than free: measure the growth before committing, and price it, rather than treating storage as headroom.
- **It would close the border gap too**, which is real and currently exempted in the ladder guard: `gen_borders` stops at 1920, so a portrait border jumps to native: a lossless PNG at ~3× the width the panel draws. Off the cold path only because the layer is hidden until Borders is on.

## `forced-colors` is unhandled, and the rail's icons are the thing it breaks (analysed 2026-08-02)

> **OPEN** · no-data-needed · **reopens when** an accessibility pass is run. Do it alongside the tier picker, for one round of judgement.

- **State at analysis:** no `forced-colors` or `prefers-contrast` rule exists anywhere in `web/src`. Grepped, not assumed.
- **Why the rail specifically:** its icons are alpha stencils: `mask-image` shapes a box painted by `background-color: currentColor`. Windows High Contrast overrides `background-color`, so the *paint* is exactly what the mode takes away. Every other surface degrades to "wrong colours"; this one can degrade to "no glyph" or "solid slab", which is the same failure class `railIcons.browser.test.ts` was written for: reached through a door that guard cannot see, since it asserts the authored cascade and not the UA's override of it.
- **Testable, which is why it is worth recording rather than shrugging at:** Playwright takes `forcedColors: 'active'`, and the browser project already runs Playwright-backed chromium, so the cost is a context option and a handful of assertions, not new infrastructure.
- **Not scheduled** because nobody has reported it and the audience is unmeasured. Deliberately kept out of the rail-icon guard rather than smuggled in: a guard that asserts two different worlds at once tells you nothing about which one broke.
- **Adjacent, same sweep:** the tier picker's `radiogroup` a11y defect is already parked here. If either is ever picked up, do both: one accessibility pass, one round of judgement.

## A cold page load at high zoom paints a flat fill and never recovers (observed 2026-08-11, not analysed)

> **OBSERVED, NOT ANALYSED**. Reproduced three times with nothing measured, so the next action is `read_network_requests` rather than a fix.

- **Reproduced three times while checking the antimeridian**: loading `/mars/?…#map=8/-20/180/0/0` from scratch leaves the whole viewport one flat sand colour. The UI, the scale bar and the tier pill all render, so the page is alive; only the map surface is empty, and waiting does not fix it.
- **Changing only the HASH from an already-loaded overview works every time**, which is the whole observation and also the workaround: load an overview first, then jump.
- **Nothing here is measured**: no console read, no network read, no check of whether tiles were requested at all. Worker-thread fetches do not appear in the main thread's `performance` entries, so the obvious first probe has to be `read_network_requests` rather than a page script.
- The shape suggests there is no lower-zoom tile to overzoom from while the first z8 requests are in flight, but that is a guess with nothing behind it. **Not antimeridian-specific**: it reproduced at 180° only because that is where the camera happened to be.

## Tiles "jump" a little when panning around a pole (observed 2026-08-11, not analysed)

> **OBSERVED, NOT ANALYSED**. Seen by eye on Mars, with no camera and no magnitude recorded. Every candidate below is a hypothesis to test.

- **Observed by eye on Mars**, after the polar seam fix landed and was judged stable: panning around the pole shows the tiles shifting slightly rather than sliding. Judged not a big deal at the time, and recorded so it is not re-discovered as new.
- **Nothing here is measured yet**: no camera, no magnitude, no frame capture. Treat every sentence below as a hypothesis to test, not a finding.
- Likely candidates, in the order worth checking: the render-tile covering set churning as the globe reassigns zoom near the limb (`terrainZoomsFor` records that a pitched view drops a DEM level); the cap-to-tile alpha crossfade re-evaluating per frame; and `TERRAIN_SKIRT_DEFAULT = "none"`, which we ratified knowing it trades skirt artifacts for hairline gaps at zoom boundaries.
- **The cheapest first move is to tell those apart, not to fix any of them**: `?skirt=auto` isolates the third in one page load, and it is a control that can fail.
- **Not Mars-specific until shown to be.** Everything named above is body-independent, so check Earth's poles before scoping this as a Mars defect.

## Heroes record no recipe, so nothing on disk says which rig made any of the 203 (analysed 2026-08-21, PARKED)

> **OPEN** · needs-render-store · **reopens when** a hero re-render is scheduled. One of three entries that fire on that same event.

- **State at analysis:** `scene_build.rig_recipe` exists and has exactly one caller, `pipeline/tile/block_render.py`. The hero lane never invokes it, and `batch.py`'s freshness test is bare file existence (`target.exists() and not force`). So a hero is "current" if its PNG is present, whatever produced it.
- **This is the producer-declares rule, unimplemented on the lane holding 203 approved artefacts.** The block tier states what it emitted, per stage, precisely so a consumer never has to infer it. The hero tier infers everything from one file's existence.
- **Two rig changes have already landed that the heroes cannot see.** The sun moved to 315 degrees and the base grid became a per-caller argument that heroes deliberately do not take. Every hero on disk carries the old sun and the single quad, and nothing beside them records either fact.
- **The live hazard is the TARGETED re-render, which PROCESS.md documents as a normal ~28 minute workflow.** Re-rendering a handful of countries today emits heroes that differ from their 202 neighbours in lighting, and the only way to tell afterwards is to look at the pixels.
- **What it would take:** the block tier's shape, a recipe written beside the output and compared on the next run. The hero lane's own `frame.json` is per-country and never overwritten, so it is not a candidate; this wants a separate file with the rig's constants in it.
- **Parked deliberately** rather than deferred by accident: the fleet re-render is itself waiting on the tiles carrying raytraced terrain, and a recipe with no re-render behind it only records that everything is stale. Revisit when that re-render is scheduled.

## The polar caps are a texture because MapLibre allows nothing else, and the ceiling is WebP's (analysed 2026-08-07)

> **BLOCKED** on MapLibre gaining a TileMatrixSet source, or on Antarctic detail being judged short on the sphere. Never on the number alone.

- **State at analysis:** each pole ships one AEQD texture with a four-rung ladder (1024/2048/4096/8192) picked from the cap's measured on-screen size. It is not a tile pyramid, and the reason has been assumed rather than recorded.
- **GDAL is not the constraint.** `gdal raster tile --tiling-scheme` offers `APSTILE` and `LINZAntarticaMapTilegrid` alongside `WebMercatorQuad`: both polar stereographic, both able to cut a real pyramid over a pole.
- **MapLibre is.** Its raster and vector sources are Web Mercator only; `scheme` chooses `xyz` vs `tms` and that is the whole vocabulary. Consuming a polar pyramid means a custom loader, LOD selector and stitcher: most of what the custom cap layer already does, with 8 files instead of thousands.
- **The texture ceiling is 16,383 px, and it is a file-format limit, not a taste one.** WebP cannot encode a larger side at all; GPU `MAX_TEXTURE_SIZE` is typically 16,384 on desktop and the mobile budget already clamps to 4096. So the largest cap that could ever ship is 2× today's linear size.
- **What that would buy, measured against each body's own source:** Mars nothing: its cap already interpolates its 200 m/px blend. Earth's south cap is the one real gap, sitting several times coarser than the land DEM beneath it and than the tiles it feathers into at the seam.
- **Verdict: parked, and the gap is Earth's, not Mars's.** Revisit only if MapLibre gains a TileMatrixSet source, or if Antarctic detail is judged short on the sphere, never from the number.

## MapLibre's WebGPU backend: irrelevant to our memory problem, and NOT the no-op we recorded (analysed 2026-07-29)

> **BLOCKED** on MapLibre publishing a timeline. Carries a correction to an earlier recorded prediction: the caps need a WGSL port, so this is not free when it lands.

Prompted by the graphics-modernization roadmap. Read it against the DEM-cache work rather than in the abstract, and the answer is "no" on the question that motivated the reading.

- **The roadmap is four phases**: WebGL2 texture/shader work, a drawable architecture with UBOs, WebGL2 vertex work, then **WebGPU as phase 4** including GLSL→WGSL conversion. Each phase is independently shippable. **No timeline is published.**
- **It contains no mention of GPU memory management, memory budgets, resource lifetimes, device loss, or tile caching.** It is a rendering-backend modernization, not a resource-management one.
- **It cannot touch our root cause, which is not in the renderer.** The `_source.tileSize` vs `tileManager.tileSize` mismatch lives in `tile_manager.ts`, and `DEMData` holds a `Uint32Array`: **JS heap, not GPU memory**. A backend swap leaves both exactly as they are.
- **The seam already exists in the shipped API, which dates the work rather than the promise.** `canvasContextAttributes.contextType` is typed today and documented as *restricted to `'webgl2'`, kept as a forward-looking API for future WebGPU support*, i.e. the option is reserved and the backend is not written. Found in the v6.0.0 `.d.ts` during the API audit, not in the roadmap.

**The one real win is a failure SIGNAL, and it is the missing piece of the evidence-driven budget.** In WebGL an allocation that exhausts VRAM does not fail: it takes the context down, which is precisely the 2026-07-29 freeze. WebGPU has typed errors via `pushErrorScope`/`popErrorScope`, so `GPUOutOfMemoryError` is catchable and attributable *before* the tab dies rather than after. Today the only feedback the platform gives is "the context died". Secondary: `GPUDevice.lost` resolves once and permanently, forcing explicit recreation: a stricter contract than the `webglcontextlost`/`restored` pair whose ambiguity is what hid our recovery notice; and explicit `destroy()` on buffers and textures gives deterministic release.

**Correction to a recorded prediction.** The Tier-2 globe work assessed WebGPU as "a future no-op tier, not a rewrite". That was true of the code as it stood and is **false now**: `polarCaps.ts` is a MapLibre **custom layer**, and that API hands you a raw `WebGLRenderingContext`. We author GLSL, build VBOs and call `gl.drawElements` directly, so a WebGPU backend cannot preserve the signature: **the caps need a WGSL port, displacement shader included**. Anyone pricing the migration must count that; the old entry says they need not.

**Verdict: not a lever for the cache work, and not free when it lands.** Revisit if MapLibre publishes a timeline, or if the evidence-driven cache budget gets built and wants a real out-of-memory signal to drive it.

## Shadow saturation on the land is a shading term, and the sea that was ratified rides mostly on lit pixels (analysed 2026-08-27)

> **OPEN** · look-call · needs-gpu. Two of the three terms in the trade are measured. The third is the one that killed cast shadows twice, and nobody has priced it.

Rohan ratified the raytraced rig's look and named one reservation: slightly too much saturation on the land, "mostly on the high-elev side of the colour ramp", explicitly not a dealbreaker. **The named axis is falsified and the ramp is not the lever.** Binned on hue so albedo is held fixed, with the luminance split inside each bin separating lit from shadowed, over 120 million pixels across twelve blocks spread from the Arctic to Antarctica:

| surface | tone | pixels | saturation |
|---|---|---:|---|
| land | lit | 12.2 M | 0.261 → 0.260 (−0.6%) |
| land | shadowed | 11.4 M | 0.389 → 0.461 (+18.3%) |
| sea | lit | 49.0 M | 0.384 → 0.510 (+32.7%) |
| sea | shadowed | 47.4 M | 0.417 → 0.608 (+45.8%) |

**Lit land did not move.** That is the control: the ramp's own output is unchanged to within a rounding error, so every bit of the land's gain is shading, and a ramp edit would move the one population that is already right. The first pass at this binned on ELEVATION and reached the opposite conclusion, because the ramp's mid stops are both dark and already saturated, so "dark" and "saturated" were confounded.

**The levers are `fill_strength` 0.45, `world_strength` 0.3 and `world_rgba`, all in `scene_build.py` and all global**, so any of them reaches the sea as well. The sea survives that better than feared: its gain is majority-LIT (+32.7% before shadow adds 13 more points), so a lever that removes the shadow-specific saturation entirely should leave the sea near +33% against the +39% measured overall, keeping roughly four fifths of what was ratified. **That last sentence is a prediction from the split above, not a rendered arm.**

**The unpriced third term.** Those levers work by lifting ambient into shadow, and shadow contrast is what carries the relief modelling. Cast shadows were rejected twice, the second time on precisely this mechanism: scaling light amplitude scales fine detail with it. These are fill and world rather than the main sun, so the objection does not transfer automatically, and it does not obviously fail either.

**The cheap way to close it, and the reason this is parked rather than abandoned.** `~/terrella-scratch/seam-block/` holds a prepped block plus its `arm.py`; prep is the expensive half because it reads the 1.1 TB store, so an arm is a two-minute render rather than a 12-hour pass. Render two or three fill/world settings, measure the high-pass detail in shadowed land, and the third term stops being a guess. Only then is a pass worth committing.

## Flat ice saturates the snow ramp, and the curve was fitted before Antarctica existed (analysed 2026-07-29)

> **OPEN** · look-call · needs-render-store. Candidates listed, none costed, and one of them is a genuine look decision rather than a bug fix. `snow_hi_pt` is settled and is not the lever.

Zooming into Antarctica to judge the terrain feather showed it "basically washed out". Two independent causes, split by depth in the frame: the far field was the atmosphere, fixed by ramping `atmosphere-blend` on PITCH as well as on zoom, since an unpitched overview takes no damage while a pitched one takes it at every zoom, and **the near field is this**, which is unfixed.

**Mechanism.** Over full snow (`alpha = 1`) the composite is `base_rgb * (1 - alpha) + snow_rgb * alpha`, so `base_rgb` is multiplied by zero and every bit of hillshade *and the entire elevation ramp* is discarded. Relief survives only through `snow_t`, a two-colour ramp. Antarctic land is forced to alpha 1 by `snow.antarctic_snow_mask` because **its snow dataset has holes**: NSIDC-0791 covers the continent and saturates over it, but 9 to 14% of that land arrives as clustered fill that RGI's peripheral region 19 does not reach, so without the mask those render on the tan LAND ramp, i.e. brown blotches inside the ice sheet. Flatness is a side effect of closing them, not its purpose.

**Then the ramp saturates.** Ice sheets have real elevation (the z6 plateau tile spans 2512–2944 m, a 432 m range) but almost no SLOPE: about 0.1° across a ~200 km tile, with a median neighbour step of 0.0 m, below the 8 m quantisation. Hillshade keys on slope, so the light lands at or above `snow_hi_pt = 1.05` and `snow_t` clips to exactly 1. **Elevation is therefore discarded twice:** once because hillshade cannot see it, once because the ramp clips.

**Measured 2026-07-29, 3×3 z6 blocks, snow pixels only: the same method HISTORY's gamma8 table used:**

| site | delivered | pinned at top of ramp |
|---|---|---|
| Greenland Summit *(in the gamma8 sample)* | 20.67 DN | 82.1% |
| Greenland north *(in the gamma8 sample)* | 12.67 DN | 89.3% |
| Dome A / Argus | 14.67 DN | 84.3% |
| Vostok | 16.00 DN | 80.0% |
| **E Antarctic plateau (−77, 0)** | **6.33 DN** | **91.3%** |
| Transantarctic Mountains | 20.67 DN | 14.6% |

**Not a systematic failure: a tail case.** Most of Antarctica lands inside the range already accepted (Dome A and Vostok beat Greenland north, which shipped), and the mountains are fine. The flat plateau is the outlier, and it is where the review happened to look.

**The gap that makes a re-check legitimate rather than re-litigation:** `snow_curve = "gamma8"` was chosen **2026-07-17**, and Antarctica was fused into the pyramid **2026-07-22, five days later**. The curve's whole A/B table is Greenland Summit, Greenland north, Alps and Himalaya: **the largest snow surface on the planet was not in the sample it was fitted on, because it was not in the pyramid yet**. No regression was found (a Summit 3×3 block measures 20.7 DN against the entry's 18.84, consistent), so the curve does what it was tuned to do; it was simply never asked about this terrain.

**`snow_hi_pt` is NOT the lever, and that is already settled**. The window was measured and rejected: Greenland uses 7% of it, the Alps overflow at 122%, and **the two ranges are nested rather than adjacent**, so a window fitted to flat ice turns Alpine snow into a binary blue/white cartoon. Do not re-argue it.

**Candidates, none costed:** re-fit the gamma exponent with Antarctic sites in the sample (a composite-stage knob: no re-fuse, no new data, and `pipeline/tile/cap_ladder.py` is the ~21 s browser-free precedent); or give the snow ramp an ELEVATION term the way the land ramp has one, which is what would make a 432 m dome read as a dome. The second is a genuine look decision, not a bug fix.

**Consequence worth carrying:** while the plateau is pinned white, terrain displacement there is invisible: our shading is baked, so displacement reads as silhouette and parallax only, and a uniform white surface offers neither. The polar feather it once gated has since been deleted rather than re-cut (see ART § the tile pipeline, terrain polar encode), so this gates nothing now.

## GDAL 3.13: assessed and SKIPPED (analysed 2026-07-23)

> **BLOCKED** on both a full-restage boundary and rasterio bundling 3.13. One line of it is actionable now: pin the future pipeline container to 3.12.x to match dev.

- **State at analysis:** system CLI 3.12.2 (Ubuntu 26.04 archive: the LTS will stay there); rasterio 1.5.0 bundling GDAL 3.12.1 on the Python side; CI on the runner's distro gdal-bin; no pipeline container yet.
- **Possible:** mechanically yes, but only via source build / PPA / the OSGeo container images: and rasterio can't follow until a wheel bundles 3.13, so a CLI-only upgrade widens today's benign 3.12.1/3.12.2 split. All listed 3.13 breaking changes are C/C++-API-side; our CLI + rasterio surface is untouched (the `--src/--dst` → `--input/--output` rename keeps old names).
- **Useful: no.** The one headline naming our tool: `gdal raster tile` automatic source *overview* selection: doesn't apply (our design deliberately has no overviews; low zooms build from the tiles). Everything else on our surface is a no-op. Two items are mild *risk*: the warper Lanczos special-case removal and "RasterIO resampling now operates in output buffer type by default": resampling changes shift output **bytes**, our pyramid is ratified by byte-compare, and the freshness guard is version-blind → an upgrade mid-stream risks a mixed-generation pyramid.
- **Revisit when:** (a) a full-restage boundary arrives (the Phase 5 supersampled re-fuse regenerates every byte, making version drift moot) AND (b) rasterio bundles 3.13+.
- **Actionable now (Phase 4, not deferred):** when the rohome pipeline container gets built, pin its GDAL to 3.12.x to match dev: the same-version principle matters more than the number.

## Look presets: user-selectable globe styles (analysed 2026-07-23)

> **OPEN** · look-call · product. Three kinds at different orders of magnitude, and Kind 1 is web-only and cheap. Nothing named would reopen it.

- **Trigger:** could users pick looks: default, every-country-coloured, seasonal variants (the St. Patrick's green-sea example)?
- **Numbers depend on:** the z0–8 pyramid **≈ 3 GB** and ~87k tiles per look: it was 15–16 GB when this was analysed, so the WebP q95 switch made a second look **5× cheaper in storage** and moves Kind 2 well down the cost ladder; composite-stage restage ~29 min (PROCESS § what a change costs); `countries.geojson` sub-pixel since the hover-outline fix

Presets decompose into **three kinds by where the variation lives**: costs differ by orders of magnitude, so the taxonomy is the decision:

### Kind 1: vector-over-raster (client-side, ~free), the one to build first

- "Every-country-coloured" is this kind, **not** a raster look: country identity is vector data we already ship and already draw: the hover wash *is* this preset with one colour.
- Implementation: carry `MAPCOLOR13` through `countries_geojson.py` (`-select ADMIN,MAPCOLOR13`; Natural Earth pre-computes 7/8/9/13-colour schemes where neighbours never collide, verified present in our shapefile), a 13-colour palette tuned over the relief, a `fill` layer at ~0.25 opacity, a visibility toggle. Zero pipeline, zero storage, zero caps work.
- Same kind: border-style variants, maritime emphasis, label layers; data-driven styling on shipped vectors.
- A weekend feature, and it exercises the whole preset *system* (registry, picker, persistence) without touching the pipeline.

### Kind 2: raster recolors (one PMTiles archive per look)

- Green sea, sepia, dark relief: the look is baked into pixels, so each look = its own archive. **Per look: ~28 min compute** (SVF + composite + cut + pack/convert + caps) **and +3 GB storage**: the storage term was +15 GB before tiles became WebP q95, and that was the number that made this kind expensive; web swaps `PUBLIC_TILE_BASE` (or a per-look path the Worker routes on) + the cap pair. Now plausibly scales to several looks, not just a curated few.
- **One-time prerequisite: look parameterization (~a day).** Today every guardrail treats a second look as drift: correctly: `test_palette` pins `WATER_RGB` relationally (+7% of sea surface), palette is shared by import so editing it in place marks the heroes stale. Looks must become first-class: named looks in palette, `composite_params`/freshness/output dirs/cap recipes keyed by look, relational pins per-look. Corollary to remember: `LAKE_STOPS[0]` derives from `WATER_RGB`, so a naive green sea also greens every lake and river: a choice, not an accident.
- One-off stunt rungs, if a *single day* ever justifies a gag without the plumbing: `raster-hue-rotate` on the relief layer (free, but rotates land too, and our custom-layer caps ignore raster paint properties: they'd need a shader tint uniform), or a translucent green ocean `fill` veil (client-only, bathymetry shading survives underneath, reads as a veil not a repaint).

### Kind 3: client-side colorization (looks become shader LUTs)

- Split colour from data: ship shading + masks as data channels (grayscale light, snow/ice/lake alphas: packable into one RGBA archive; elevation via the Phase 5 terrain-RGB archive) and apply ramps in a custom WebGL layer. Look N then costs a LUT, ~0 bytes.
- **The counterweight:** it reimplements `shade.composite` in GLSL: a twin look engine, i.e. the copy-drift disease at engine scale, in a codebase whose architecture exists to forbid exactly that. Only worth opening if presets prove popular enough to be a headline feature; it is a Phase-5-sized decision and pairs naturally with the terrain-RGB work if that ships.

### The preset system itself (needed for any kind)

- A **`presets.json` contract** emitted by the pipeline, fetched by the web (the `caps.json` pattern: pipeline facts never hand-copied into TypeScript).
- **UI + persistence** following existing precedents: localStorage like the quality/border toggles, shareable `?look=` param.
- **Scoping decision to make explicitly:** presets are a *globe* feature; heroes/gallery stay single-look (204 Cycles re-renders per preset is not a menu item).

### Recommendation ladder (as analysed)

- Kind 1 first, when wanted: cheap, complete, exercises the system.
- Kind 2 is **materially cheaper than when this was analysed** (3 GB per look, not 15): the remaining cost is the parameterization day, not the storage.
- Kind 3 only if presets become a proven headline feature; decide alongside Phase 5 terrain-RGB.

## Cloud offload / offsite backup (analysed 2026-07-23; revisit after Phase 5)

> **OPEN** · **reopens when** the finer-re-fuse question is settled either way, since a firm no-go is what would let 551 GB drop to on-demand.

- **Trigger:** could stores move to S3/R2 to free local disk? **Answer: ~0 GB usefully**; the taxonomy is the finding:
  - ~680 GB of raw sources are *caches of free public clouds* (GLO-30 = AWS Open Data, WorldCover = ESA's bucket, etc.): the offload is deletion + on-demand re-fetch, already gated by the INVENTORY reclaim picture, never an upload.
  - ~360 GB of intermediates are compute-regenerable, and a remote read is a rejected shape for reading them: COG buys selective reads, while a pass is a full sequential scan two or three times over. HISTORY, *remote COG is the wrong shape for a full sequential scan*.
  - The **~56 GB worth putting in a cloud is the backup set, not an offload**: heroes+raws+variants (27 GB real bytes, hardlink archives ~free; Cycles isn't bit-deterministic so ratified pixels are irreplaceable), `planet.pmtiles` (**3 GB**: doubles as deploy transport), `planet/` fused cells (14 GB: the one expensive-to-rebuild intermediate), caps/geojson/frame pins. ≈ $1/mo on R2/B2 (ballpark; R2's zero egress is the differentiator: verify pricing at pickup).
- **The big lever:** if Phase 5 goes no-go on a finer re-fuse, `glo30/` (551 GB) drops to per-country-on-demand like WorldCover: the upstream *is* the cloud store. Deferred the whole topic to after Phase 5.

## A z9 / z10 pyramid: z10 is BLOCKED ON DISK, z9 is reachable (analysed 2026-07-26)

> **BLOCKED** on a bigger disk. Its 2026-08-25 subsection is a different question carrying its own state: a finer fuse at a fixed z8, which is not disk-blocked and inflates one store only.

- **The framing that governs everything: z10 is a planet RE-FUSE at ~2.5″, never a tiling flag.** The grid is `131072²` = exactly `512 × 2⁸`, so a deeper pyramid means re-fusing at 4× linear and re-warping every layer onto `524288²`: **16× area on every intermediate**.
- **A second reason for the finer fuse, and this one does not want a deeper pyramid at all.** At 10″ a source row is a fixed 309 m of ground at every latitude, while a 3857 pixel covers `305.75 × cos(lat)` metres in both axes, so `-r near` replicates each source row over `1.011 / cos(lat)` output rows: the land/sea mask can only step every 4.95 rows at 78°N. The blockiness on Svalbard and the Arctic islands is that lattice, and it is purely vertical because the horizontal ratio is 1.011 at *every* latitude. **At 2.5″ a source row is 77 m, so the ratio stays under 1 up to 75.4° and the lattice stops existing rather than being smoothed over.** It is blocked by the same disk wall and unblocks nothing, but it means a re-fuse would pay for itself at z8 alone. The cheap alternative (bilinear-then-threshold) was measured and argued down: it cannot add what 10″ never sampled, and it moves every coast on Earth to fix the band above 75°. HISTORY, *the high-latitude coastline is a resampling lattice*.
- **Measured cost model** (each stage ×16 from PROCESS's current numbers; storage projected off the real rasters on disk):

  | target | m/px | intermediates | build | tiles | archive | GEBCO upsample |
  |---|---:|---:|---:|---:|---:|---:|
  | z0–8 (live) | 305.7 | 111 GB | 2.7 h | 87,381 | 3.0 GB | 1.5× |
  | z0–9 | 152.9 | 443 GB | 10.8 h | 349,525 | 12 GB | 3.0× |
  | z0–10 | 76.4 | **1,773 GB** | **43.2 h** | 1,398,101 | 48 GB | 6.1× |

- **z10 does not fit, and that is the decision.** 1.73 TB of intermediates against a 1.8 TB disk already holding ~1.3 TB. Reclaiming every hero intermediate *and* WorldCover (~304 GB) still falls short, and `glo30/`'s 551 GB cannot go: it is what the re-fuse reads. This is a hardware precondition, not a scheduling one.
- **The single worst stage is the lake warp: 1:01:44 → ~16.5 h**, more than a third of the 43 h.
- **WebP changed the delivery side only.** A z10 archive is ~48 GB in WebP vs ~260 GB in PNG (5.2×, measured on the real pyramid: 16 GB → 3.0 GB). That is what would make a deep pyramid *shippable* at all. The intermediates are uncompressed working rasters and are unmoved, so "we use WebP now" does not reopen z10.
- **The aesthetic argument, which stands independently of cost.** GEBCO is 15 arc-sec: **measured on the file: 464 m/px**. Land has real headroom at z10 (30 m source into 76 m/px); the sea does not. Upsampling goes **1.5× → 6.1×**, so z10 makes land crisper while leaving the sea exactly as soft as it is now, **quadrupling the land/sea detail mismatch**. Bathymetry is signature, not optional (CLAUDE.md § Data sources), so this is a look regression bought with 43 hours.
- **The old precondition is CLOSED: do not re-raise it.** Locking z8 recorded a latent gap (`ocean`/`water`/`lakedepth` take their grid from `height_3857` but did not depend on it, so a re-fuse would leave `lakedepth` falsely fresh at old dimensions: a silently wrong composite) with *"fix before any re-fuse, not after."* It was fixed at the Antarctica re-fuse: `warp_needs_rebuild` is now `is_stale(...) or not grid_matches(...)`, exactly the prescribed dimension/bounds test. Reading the 07-17 entry alone still reads as outstanding; it is not.
- **Sequencing vs Tier 3: Tier 3 first, and it is not close.** (a) z10 is blocked, so there is no ordering to decide; (b) Tier 3 is disk-cheap: terrain-RGB is a single-band elevation encode cut from the `height_3857.tif` that already exists, roughly the colour archive's size, not another 1.7 TB; (c) they are **independent MapLibre sources with their own `maxzoom`**, so terrain need not match the colour pyramid's depth: displacement meshes are coarse and z8 terrain is ample. Building Tier 3 now is therefore not invalidated by a later re-fuse, and `warp_needs_rebuild`'s grid comparison would restage it correctly if one ever landed.
- **Measured 2026-07-27, correcting two estimates above; settled 2026-07-28.** (b) held, and better than projected: the built z0–8 terrain archive is **2.63 GB** against the colour archive's 3.0 GB (the ~3.3 GB projection was 25% high). (c) was wrong: **"z8 terrain is ample" confused what is built with what is reachable.** MapLibre picks the DEM zoom from the *declared* tile size, so depth is not a free choice: at `tileSize: 512` the DEM sits at `camera − 2` and **nothing past z6 could ever load** against `maxZoom: 8`; 256 reaches z7; only **128 reaches z8**, which is what shipped. z8 is the floor in any case: 256 tiles × 512 px = 131,072 px, exactly the master's grid, so anything deeper needs a re-fuse and lands squarely in the z9/z10 question above.
- **If depth is wanted, z9 is the one that is merely expensive rather than impossible:** 443 GB and ~11 h, 3× GEBCO upsample rather than 6×. Not recommended, and it **no longer fits the free space** either: 443 GB against **389 GB free**, so it fits only by deleting the ~100 GB z8 store first, i.e. with no rollback. **Nothing in the raytraced-tile work needs it**: a raytraced pyramid renders the same 17.18 Gpx z8 grid, and depth makes its one known amplification (GEBCO's survey artefacts) worse. HISTORY, *the raytraced planet costs about 24 hours*.
- **Revisit when:** a larger disk lands. Then re-derive from PROCESS rather than trusting this table: every number here is ×16 of a measured z8 stage, not itself measured. Ties to the `glo30/` retention lever above: a firm no-go on a finer re-fuse is what would let 551 GB drop to on-demand.

### A re-fuse WITHOUT a deeper pyramid: it inflates one store and leaves delivery alone (analysed 2026-08-25)

- **THE TWO DECISIONS ARE INDEPENDENT AND THE TABLE ABOVE FUSES THEM.** Every ×16 up there comes from the GRID growing, not from the fusion growing: `block_plan.grid_px` is `CELL_PX << tile_max_zoom`, so the 131072² grid, all `*_3857.tif`, `planet_rgb.tif`, the 87,381 tiles and the archive are functions of the zoom ceiling alone. A finer fuse at a fixed z8 changes what is INSIDE those files and not one of their sizes. The bullet above already says a re-fuse "would pay for itself at z8 alone"; this is that case costed on its own.
- **What inflates is `data/work/planet/` and nothing else.** Measured split of the 15 GB store: `heightfield_10s` **13.66 GB**, the four mask products the remaining ~0.74 GB.

  | re-fuse | scaling | projected heightfield store |
  |---|---|---:|
  | 5″ isotropic | 4× area | ~45 GB |
  | 2.5″ isotropic | 16× area | ~179 GB |
  | 1″ isotropic | 100× area | **~1.12 TB** |
  | 2.5″ lat × 10″ lon | 4× rows | ~45 GB |
  | 1″ lat × 10″ lon | 10× rows | ~112 GB |

  The compression return is **~0.82, measured rather than assumed**: the mask re-fuse of 2026-08-24 took 10× the rows for 8.2× the bytes (0.08 GB to 0.66 GB). It was taken on Byte class codes, so Float32 elevation may differ; treat it as an indication.
- **1″ ISOTROPIC IS UNSUPPORTED BY THE SOURCE, and the failure lands exactly where the fuse is for.** Verified on real tiles: GLO-30 is **1.0″ in latitude at every band** (3,600 rows per 1° tile) and coarsens only in longitude, **1.0″ / 1.5″ / 3.0″ / 5.0″ at N00 / N50 / N79 / N81**. So above ~50° a 1″ isotropic grid upsamples longitude, by 3× at N79 and 5× at N81. It invents its detail in the band it claims to sharpen, at 100× the cost of the latitude-only grid that is native everywhere.
- **The options, so "finer" is never one undifferentiated word again**: do nothing · resample-only (argued down above) · latitude-only, which `fuse_heightfield.make_grid` already supports · band-limited to the ~72 Arctic cells, ~11% of the cost for one resolution seam · isotropic · raise `tile_max_zoom`, which is the table above and the only option that moves R2.
- **Delivery moves only second-order.** Tile count is fixed at 87,381 and the pyramid is exactly full at every zoom, so only per-tile bytes can rise, where new information actually lands: poleward of ~75°, about 18% of the northern grid rows and mostly Arctic Ocean with no relief to gain. That content moves archive bytes with the count fixed is measured, not assumed: the raytraced tiles of 2026-08-25 came in at **0.747×** the composite's over 24 addresses.
- **The benefit is `1.011 / cos φ` and therefore nothing at low latitude**: 1.01× at the equator, 1.43× at 45°, 2.0× at 60°, 3.9× at 75°, 8.3× at 83°. Below ~45° a finer fuse is downsampled straight back out at z8.
- **The coastline half is ALREADY BANKED at 1/20th the cost**, so what a heightfield re-fuse still buys is high-latitude RELIEF and not the lattice. The masks went to 1″ latitude on 2026-08-24 for +840 MB, and the finer masks read against the still-coarse heightfield flip **0.123% of a cell's pixels** (65,229 of 53.2 M), symmetrically: 32,704 gain land and 32,525 gain ocean. The flips sit AT SEA LEVEL, median **+0.92 m** one way and **+0.90 m** the other against bracketing controls of **+399 m** for pixels both grids call land and **-397 m** for pixels both call sea, so this is a coastline drawn better rather than one that moved.
- **The real cost is not disk, it is a second pass.** `warp_needs_rebuild` gates on the chunk DIRECTORY, which is why the masks-only fuse alone forced a 6:48 height re-warp; a heightfield re-fuse restages warps, all 1,024 blocks, the cut and the caps, **~12.3 h measured**.
- **The GEBCO asymmetry from the bullet above applies here unchanged and is a LOOK call, not a technical one.** GEBCO is 15″ (464 m/px, verified on the file), already coarser than the 10″ fuse, so a 1″ fuse upsamples the sea 15×. It reads as SOFTNESS rather than as an artefact, because the coastline comes from the watermask and not from the heightfield crossing zero: the mask-only fuse removing the rendered staircase is the proof. Crisp land against a crisp coast in front of a soft sea floor is the outcome to judge.

## Hero presentation: geography-conditional, and no universal design exists (analysed 2026-07-09)

> **OPEN** · product. A trilemma rather than a task: consistent, coherent, neighbour-free, pick two. It has never blocked anything.

Parked here from the living plan, where it was the last surviving open question with no tracked home.

The finding is a **trilemma: consistent / coherent / neighbour-free; pick two.** Cutout-cream framing suits continental countries; real ocean suits islands; and most countries are *both* coastal and bordered, so every single treatment reads flat at the margin for a large fraction of the set.

Not a look change in the locked-constants sense: the sun, ramps and exaggeration are untouched by it, so nothing here threatens the freeze. It is a *presentation* choice made per gallery/globe surface, which is why it never blocked anything.

## Kiribati presentation: the one antimeridian-deferred country (analysed 2026-07-24)

> **OPEN** · product. Two viable options priced, A high effort and B low and entirely in the data and manifest layer. The open question is which, not whether.

- **Trigger:** Kiribati is the sole in-scope country with no hero (`status="antimeridian"`, `config/countries.toml`), skipped by design 2026-07-09 because its land is genuinely split: Gilberts 32% at 169–177°E (capital Tarawa) vs Phoenix+Line 68% at 175–151°W (largest atoll Kiritimati), no dominant side. "No hero *for now*" lived only in a TOML note; this is its analysed home.
- **The decisive facts (checked, not assumed):**
  - **Low relief is NOT the disqualifier.** Kiribati averages ~1.8 m elevation (max ~3 m; only Banaba, in the Gilberts, is a raised 81 m island). But the other flat atoll nations: Maldives, Marshall Islands, Tuvalu, Nauru: **all rendered heroes**, and they read as striking bathymetry-dominant seamount fields (Maldives especially). So an atoll hero is on-aesthetic; the *only* real blocker is the antimeridian split.
  - **The render pipeline is single-frame end-to-end**: one slug → one bbox → one `frame.json` → one ortho render → one hero (every `west, south, east, north =` unpack in `pipeline/frame/country_config.py` takes exactly one `[W,S,E,N]`; `scene_build.py` one camera/one render; there is no `montage()` anywhere in the tree, so a multi-frame hero has no existing machinery to extend).
  - **The frontend already degrades gracefully for a hero-less country**: `rendered:false`/`sizes:[]` is a first-class manifest state (`gen_manifest.py`'s `rendered=bool(sizes)`, `lib/manifest.ts`), and both the gallery card and the detail page branch on `country.rendered` to render a placeholder. It is dead code today because Kiribati is dropped at the manifest step: `gen_manifest.py`'s `main()` `continue`s on `resolve() is None`.

### Viable option A: composited twin-panel hero (keeps Kiribati as one country)

- One Kiribati entry, one hero image holding two framed insets (Gilberts | Line+Phoenix), each a normal non-crossing frame rendering like Maldives/Marshall. Preserves country integrity (one sovereign nation = one gallery card): the reason it beats sub-heroes (below).
- **Effort: HIGH.** The single-frame pipeline has no seam for it: needs new code at ~every stage: a `panels=[...]` config key + list validation (`country_config.py`'s `COUNTRY_KEYS` and its `[W,S,E,N]` unpacks); per-panel work/render subdirs through `stage_commands` (each panel is a *different* AEA projection with its own `frame.json`/heightfield/masks); **a brand-new compositor stage** (the keystone: nothing composites two RGBA renders today); a batch loop over panels; and per-panel border/overlay mapping (`overlay_borders.py`/`gen_borders.py` assume one `ortho_scale`). The two lobes are at very different scales: panel sizing is a real design choice, not automatic.

### Viable option B: gallery card, no hero (the low-effort default)

- Kiribati appears as a placeholder card + gazetteer + detail page, no relief hero: honest about a permanent deferral. Keeps it as one entry.
- **Effort: LOW, and entirely in the data/manifest layer** (presentation already exists): (1) emit an `rendered:false` manifest entry for antimeridian-deferred countries instead of dropping them: `gen_manifest.py`'s `main()` skips them with `if r is None: continue`; (2) author a `bbox`: Kiribati has `status`/`notes` but no `frame`, and the gazetteer + globe fly-to read `country.bbox`; (3) guard the globe's `openPanel()` in `Globe.astro`, which sets `heroImg.src` from `country.sizes[0]` unconditionally → a broken `kiribati-undefined.webp` for an unrendered entry; (4) optional distinct "deferred" copy: today's only placeholder string is "still rendering," which misrepresents a permanent state.

### Ruled out (do not re-litigate)

- **Wide antimeridian crosser**: dead on two counts: it needs the exact trans-180 wrap-math the 2026-07-09 premise-check rejected (W>E frames, shifted VRTs, 4 files), *and* even a compact atoll frame is mostly ocean, so a ~40° crosser would be ~90% empty Pacific with two edge clusters. High cost, poor result.
- **Two separate sub-heroes** (the France+New Caledonia "separate heroes" precedent): does **not** transfer. France's territories are distinct Natural Earth admin-0 units that enter scope naturally; Kiribati's island groups are one admin unit, so sub-heroes would need invented sub-country slugs with no backing NE geometry (borders/gazetteer have no matching entries) **and** fragment one sovereign nation into two gallery cards. More bespoke than option A and semantically wrong.

### Recommendation (as analysed)

- Option B if Kiribati should simply *appear*: cheap, honest, keeps the set complete at 204.
- Option A only if a Kiribati *hero* is wanted badly enough to build the pipeline's first multi-frame path (which would also unlock France+territories, USA+Alaska/Hawaii as composited heroes: the currently-dropped far-flung remainders). Worth pricing against just shipping those as the already-decided separate territory heroes.

## Worker placement hint near the APAC bucket: the prize shrank when lever A shipped (analysed 2026-07-26)

> **OPEN**, maintainer-only: it is a config line on this Cloudflare account. Cheap to try, and the expected win is now uncertain in sign rather than zero.

- **Was the second delivery lever; demoted the day Workers Caching shipped.** Not rejected: the expected win is now uncertain in sign and size, which is not the same as zero, and it is one config line to try.
- **What changed:** pre-lever-A a cold tile paid **three sequential Marseille↔APAC reads**, so an explicit `placement.region` hint collapsed three long-haul round trips into roughly one: the basis of the 07-25 "380 ms → ~100 ms" estimate. Lever A left **one** read, and placement does not remove that leg, it **moves** it: today the request lands at MRS and the read crosses to APAC; under placement the request crosses to APAC and the read is local. **The tile bytes cross the same ocean exactly once either way.** What remains is R2's long-haul read overhead minus Cloudflare's backbone RTT.
- **Second discount:** the 07-25 Mumbai control did the same read in **~60 ms**, so the Indian visitors who land at BOM next to the bucket already have a fast read and gain nothing. The hint helps US/EU visitors and the maintainer's own route: a real audience, but not "everyone".
- **The blocker is gone**, so this is now cheap to test: Workers Caching shipped 2026-07-26, hits no longer run the Worker, and the docs are explicit that *"the cache is always consulted before Smart Placement is considered"*. Both the hint and the revert are config-only.
- **Design the experiment against the right control.** `r2;dur` is measured *inside* the Worker and is the only number a cache in front of the Worker cannot influence, but it also moves a lot on its own (median 419 ms vs 251 ms hours apart on 2026-07-26). Interleave placed and unplaced measurements, or the route's own drift will out-vote the effect.
- **Not the same thing as `mode: "smart"`**, which is available on all plans but needs *"consistent traffic from multiple locations"* Terrella does not have. An explicit region hint needs no warm-up.
- Two follow-ups belong with this work rather than before it: delete the now-redundant `caches.default` tile-body layer and its `X-Terrella-Cache` marker, and add `Access-Control-Expose-Headers: Cf-Cache-Status` so a browser-side check can tell HIT from MISS.

## Pinned low-zoom base layer: a deterministic floor under missing tiles (analysed 2026-07-26)

> **OPEN** · look-call · **reopens when** the flat fill is observed to read badly in practice. Judge it on the sphere, not in the abstract.

- **Trigger:** the hole-to-space fix shipped a flat `#47808F` background layer, which is a *colour* floor. It cannot be right over land: a gap over the Himalayas reads as ocean. This is the version that would be right everywhere, parked because the flat fill may well be enough.
- **Mechanism:** a second raster source over the same tiles with `maxzoom: 1`. Its ideal tiles are always the few world-covering ones, so they sit in the **in-view** set where the LRU cannot evict them: unlike the same tiles inside the main source, which are the first things dropped. That makes MapLibre's parent walk (`minCoveringZoom` reaches z0) *always* terminate, so an uncovered tile shows blurred earth with correct land and sea rather than a flat colour.
- **Measured cost (live tile Worker, 2026-07-26):** z0 = 1 tile **71 KB** · z1 = 4 tiles **273 KB** · z2 = 16 tiles **~1.4 MB**. One extra textured draw per frame.
- **Why not now:** 273 KB is ~4% back onto a cold window just cut 11.4 → 6.5 MB, and it lands in the critical path. Mounting it at first idle (as `countries.geojson` already does) avoids that but then it does not help first paint, which is exactly where the flat layer *does* help.
- **Downside to weigh:** at z6–z8 a z1 tile is magnified 32–128×, a heavy smear that may read worse than clean teal. Judge on the sphere, not in the abstract.
- **Decide at:** only if the flat fill is observed to read badly in practice. Strictly better than raising `maxTileCacheZoomLevels`, which buys a probabilistic win for **+264 MiB** of desktop GPU texture

## Mobile lightweight identify: "what is this?" without committing (analysed 2026-07-26)

> **OPEN** · product · **reopens when** someone reports it or a real phone gets measured. Verify the premise first: the flight may be the reward rather than a tax.

- **Trigger:** the hover name chip shipped desktop-only, correctly: touch has no hover state to leave anonymous. But that framing hides a *different* gap on touch, and this is where it is parked so the chip is not mistaken for having covered it
- **The asymmetry:** on desktop, "what country is this?" costs a pointer move. On touch it costs a **2.2 s `fitBounds` flight + a card over the screen + a hero image fetch**, then a close and a re-orient. Same question, wildly different price, and the expensive one is on the platform with the least patience.
- **Already rejected, do not re-litigate without a new mechanism:** a **two-stage tap** (first tap identifies, second opens). It taxes the primary action for every user to serve a secondary one, and the primary action, flying to a country and seeing its hero, is the point of the globe.
- **Unexplored shapes, if this is ever reopened:** long-press to identify (leaves tap alone, but is undiscoverable and collides with the OS text/context menu); a persistent "identify mode" toggle in the view bar (discoverable, costs a control slot for a rarely-used mode); or naming the country in the card *faster*: the name is known at tap time, so the card could paint its `<h2>` immediately and let the image and the flight land after, which is a **latency fix rather than a new gesture** and is probably the cheapest real improvement here.
- **Why not now:** unmeasured. Nobody has reported the problem, and the card already names the country within a few hundred ms of the tap. **Verify the premise on a real phone before designing**: the flight is the reward, not a tax, and this may be a problem only on paper.

## The tier picker is a radiogroup made of toggle buttons (analysed 2026-07-27, DEFERRED)

> **OPEN** · no-data-needed · **reopens when** an accessibility pass is run. Not the attribute swap it looks like: one fill selector is shared with Borders, Spin and Focus.

- **Trigger:** found while adding tooltips to Lite / Globe / Full. Verified in the live DOM, not read off the source: `.quality-fab` carries `role="radiogroup"`, and its three children have **`role: null`, `aria-pressed`, and no `aria-checked`**.
- **Why it is wrong:** an ARIA `radiogroup` must own elements with `role="radio"`. A plain button with `aria-pressed` inside one is announced as a *toggle button within a radio group*, incoherent, and the group loses the positional "1 of 3" that makes a radio group worth using in the first place. The three tiers are genuinely mutually exclusive, so radiogroup is the right *intent*; only the children are wrong.
- **Why it was not just fixed:** the correct markup is `role="radio"` + `aria-checked`, but the filled "this one is active" styling is `.view-bar button[aria-pressed="true"]`: **one selector shared with Borders, Spin and Focus**. Switching the tier buttons to `aria-checked` silently un-fills them unless the CSS is split at the same time. So it is a markup + CSS change with a visual regression risk, not the attribute swap it looks like.
- **If reopened:** change all three children together, split the fill rule into `[aria-pressed="true"], [aria-checked="true"]`, and check the active tier still reads filled on the globe, the gallery **and** a hero page. Keyboard arrow-key navigation between radios is the other half of the radio contract and is currently absent: decide whether to implement it or drop `radiogroup` for a plain group, which is honest and costs nothing.

## Landing-page "poster mode" (deferred 2026-07-26, never scoped)

> **OPEN** · product. Never scoped beyond one line. Nothing depends on it and nothing is blocked by it.

- **What it is:** an optional flourish: a landing-page beauty shot of the sphere, styled as a print poster rather than as an interactive map. Recorded here verbatim because it was never scoped beyond one line, and it had no other home.
- **Status:** a weekend experiment, explicitly optional. Nothing depends on it and nothing is blocked by it. The gallery already opens on hero renders, so this is decoration on decoration.
- **If reopened:** decide first whether it replaces the gallery's current entry point or sits beside it: that is the only part with a real cost, since the gallery is the Tier-1 fallback everyone gets while the capability probe runs.

## Raster tile resolution vs device pixel ratio (analysed 2026-07-25)

> **OPEN** · look-call. This heading is cited from `CLAUDE.md` and from `web/src/lib/reliefSources.ts`, so it is the one heading in this file that must not be renamed.

- **Trigger:** the question of whether serving 512 px tiles "@2x" is wasted on a DPR-1 desktop, and whether phones get enough for DPR 3. The answer inverts the intuition, so it is worth parking rather than discarding.
- **Mechanism, measured on the live globe:** the source declares `tileSize: 256` for 512 px assets, so MapLibre requests `z_map + 1` and **a source tile always covers 256 CSS px, at every zoom**. Confirmed at map zoom 1.3 → z2/z3 requested, and the canvas backing store equals its CSS size on DPR 1 (ratio 1.00, i.e. MapLibre is not supersampling the canvas).
- **The scheme is centred on DPR 2, not DPR 1:**
  - DPR 1: 512 px into a 256 device px slot: **2× oversupplied** (4× the pixels).
  - DPR 2: 512 into 512: **exactly 1:1**.
  - DPR 3: 512 into 768: **0.67×, upscaled and softer than native.**
  - So **modern phones are the UNDER-served ones**, not the over-served ones. (DPR 1 measured; the other two follow from the same CSS-px mechanism and were not measured on real devices.)
- **The DPR-1 oversupply is not pure waste.** The GPU minifies 512→256 through mip/bilinear filtering, which is 2×2 supersampling on exactly the high-frequency multidirectional hillshade this look rests on, and more so on a globe, where tiles are warped onto a sphere and sampled anisotropically toward the limb. It errs in the safe direction: oversampling looks good, undersampling looks blurry.
- **Why there is no automatic fix:** MapLibre raster sources have **no DPR negotiation**: no `@2x` URL convention, no srcset equivalent. Tile selection is computed in CSS pixels and is DPR-blind by design. `tileSize` is the only lever, and it is global.
- **The lever, if picked up:** `tileSize: devicePixelRatio >= 2 ? 256 : 512` at source construction (DPR is known before the map is built). DPR-1 clients drop a zoom level → **4× fewer tile pixels and 4× fewer tile requests**, the latter mattering against the free tier's ~2,500 cold-visit/day request ceiling. DPR ≥2 is untouched.
- **Why it is parked and not done:** it is a **look change on DPR-1 screens** (supersampled → native 1:1, more aliasing), and look changes here get eyes on them at full scale before they ship. It is also small: tiles are ~2.6 MB of the cold window at q95, so it saves ~2 MB for desktop visitors: against the ~80 MB the hero rungs took off the gallery.
- **Not proposed:** a 1024 px pyramid to serve DPR 3 at 1:1. That is 4× the tiles for the band that is merely soft, not broken.
- **The polar caps solved this exact mechanism, and the tiles still have not** (2026-07-25). The cap now picks its texture from its projected on-screen size × the canvas backing ratio, so DPR is handled per-device with no look change reuse that: MapLibre's raster source has no DPR negotiation and `tileSize` is global, which is why the lever above is a one-line `tileSize` switch rather than a picker. Worth re-reading that implementation before picking this up: it settles what "demand" means here, and the `canvas.width / canvas.clientWidth` ratio is the right input for both.

## The layer-rename alias cannot be deleted yet, and the clock is longer than it reads (analysed 2026-08-31)

> **BLOCKED** on a year of `immutable` tile URLs expiring, and then on a production log actually being read. A deletion, not a design.

- **What it is:** `RENAMED_LAYER_WORDS` in `web/src/lib/tileAddress.ts`, one entry mapping the word `countries` to the `vector` layer, so the tile Worker keeps serving requests spelled the way the site spelled them before the layer became a role.
- **Why it cannot just go:** the layer token compiles into the SITE bundle while the Worker is a separate deploy, and every page a visitor already has open holds tile URLs marked `immutable` for a year. A Worker that refused the old spelling would blank the countries on a live globe rather than paint a stale name.
- **The clock is longer than the calendar suggests, and the date is a floor rather than the signal.** A year from the rename puts the earliest possible removal around 2027-08, but expiry only stops NEW old-spelling requests being guaranteed; it does not say none arrive.
- **The real signal is `addressedLayerWord` in production logs.** It reports the word a request SPELLED, and a server compares that against the layer the request resolved to. When that comparison stops finding a difference, the alias has no clients left. Nothing else can tell you, because an aliased request is served correctly and silently, which is exactly what makes it safe and exactly what makes it invisible.
- **Carried here rather than on the plan's queue because it is not work.** It is a wait with a check at the end of it, and sitting in a numbered queue it reads as something someone could pick up.

## Brotli sidecars for the text-like assets (analysed 2026-07-25, BLOCKED)

> **BLOCKED** on an R2 `Content-Encoding` passthrough probe nobody has run. A correctness question rather than an effort one.

- **Trigger:** measuring what the edge actually negotiates for `countries.geojson`. It picks the *worst* of the three encodings it offers.
- **Measured, same source file:** edge zstd **2.98 MB** · edge gzip 2.61 MB · static brotli-11 **1.56 MB**. `boundary_lines.geojson` goes 642 → 376 KB the same way. Together ≈ 1.5 MB off the cold window.
- **BLOCKED on a correctness question, not on effort:** one stored R2 object cannot content-negotiate. Serving a `.br` sidecar means either a second object plus request-time selection, or storing only brotli and breaking any client that does not advertise it.
- R2's `Content-Encoding` passthrough behaviour is **undocumented** in the docs search: it needs a probe object before anything is designed on top of it.
- `DecompressionStream` has **no brotli**, so decompressing it in page JS is not an escape hatch.
- **Low priority on purpose:** this is deferred-to-idle transfer (~0.4 s), entirely off the first-paint path. The polar caps are the larger and simpler target.

## Metatile batching: collapse round trips instead of running more of them (analysed 2026-08-01)

> **OPEN**, maintainer-only: it needs a new Worker route. Deliberately unquantified, because two predicted effect sizes here were already falsified on measurement.

- **Trigger:** the concurrency sweep answered "run more requests at once" and shipped it: MapLibre's parallel image-request cap went 16 → 32, worth ~2.1× the achieved concurrency. This is the *other* half of the same cost, and the cap cannot touch it: the queue limits how many requests are in flight, not how many are needed.
- **The measurement that argues for it**, from `server-timing` on cold z7 tiles: `worker;dur=280` of a **760 ms** tile, `worker;dur=383` of a **1030 ms** tile. Roughly **half of every tile is client↔edge round trip**, paid once per tile: 119 times on one cold z5 load.
- **Shape:** an `addProtocol` handler asks the tile Worker for a 2×2 (or 4×4) metatile and slices it client-side. Four MapLibre queue slots are still held, but only ONE ocean crossing happens behind them. The R2 reads it replaces become subrequests inside Cloudflare's network, which `worker/wrangler.jsonc` already records as unbilled.
- **Deliberately unquantified.** The gain depends on how R2 read latency composes when several are issued together, which cannot be known without building the endpoint. Two predicted effect sizes were quoted and then falsified on 2026-08-01 alone; this one waits for a measurement.
- **Cost is the reason it is parked:** a new Worker route, a client protocol handler, and slicing code: against a one-line constant that already bought 2.1×.
- **Known-settled, so it is not re-derived** (read out of the shipped MapLibre source, not the docs): `addProtocol` does NOT escape the request queue; `ImageRequest.getImage` pushes to `imageRequestQueue` unconditionally, and `getProtocol(url)` appears only as a condition choosing `makeRequest` over an `<img>` load, both inside the queued path. So a protocol handler can only ever be MORE restrictive than the cap. `transformRequest` cannot help either: its `RequestParameters` carries no priority or ordering field. The one true bypass is `addSourceType`, i.e. reimplementing `RasterTileSource` with its fade/retain/unload/expiry surface: far more than this idea is worth on its own.

## AVIF hero variants (analysed 2026-07-23, premise restated 2026-07-25)

> **OPEN** · needs-render-store · **reopens when** a transfer audit happens anyway. Its baseline has already moved once since analysis, so re-measure before costing it.

- **Trigger:** the astro:assets audit during the 7.1.3 bump; the one genuine feature we forgo by bypassing it is AVIF format negotiation, and it belongs in *our* pipeline, not a second optimizer re-encoding ratified pixels (one encoder-quality owner).
- **The baseline this was analysed against has MOVED: re-measure before costing it.** It assumed WebP q85 across three rungs (France 0.7 / 2.3 / 6.9 MB at 1920/3840/native). The ladder is now **six rungs (640/960/1280/1920/3840/native) at a split quality: q85 up to 1920, q95 above**, so both the file count and the per-file baseline are different, and the AVIF comparison has to be made against q95 where it matters.
- **Idea:** AVIF siblings of the existing rungs in `hero_variants.py`; gallery + globe panel switch to `<picture>` with `type` fallback. Rule-of-thumb gain ~20–30% smaller at similar quality: **unmeasured on our content; measure 2–3 heroes before deciding anything.**
- **Costs to check at pickup:** GDAL AVIF driver present in our build (needs libavif); AVIF encode time: now × ~1,200 hero files rather than ~612, and the q95 rungs are the slow ones; variant store growth; web markup change is small.
- **Natural decision point:** the Phase 4 Lighthouse pass, where transfer sizes get audited anyway. Not before.
- **Note the tile pyramid is NOT a candidate for the same treatment**: it is one archive with one declared tile type, so a `<picture>`-style negotiation has nowhere to live.

## Hero presentation: large-country warp & small-island exaggeration (analysed 2026-07-24)

> **OPEN** · look-call · needs-gpu · **reopens when** a hero re-render is scheduled. Both halves need one, which is why they are parked together.

Raised while reviewing the gallery after the sea-sync sweep (the sea look was approved; these are pre-existing framing concerns). The country-extent concern is being SOLVED separately by the subject-spotlight "Focus" toggle (compose-layer, no re-render). These two remain, and BOTH require a re-render, so they are parked until a re-render is on the table anyway.

### Large countries warp: the Russia equal-area-conic "fan"

- **What:** each hero is one Albers equal-area conic centred on its frame; for a ~160° longitude span (Russia) the conic splays into a wedge with big empty margins. **China (~60°) looks fine**: a mild trapezoid, so this is ~4-5 extreme countries (Russia worst; Canada, USA, Kazakhstan, Greenland), not "large countries" broadly.
- **Why it's low-ROI:** the fan is *inherent* to equal-area for a transcontinental span: any single projection either fans (conic) or grossly distorts area (Mercator). Levers are weak: trim the frame margin; bespoke-frame the few worst to a representative region (breaks the "whole country" promise); or accept it as honest cartography. **Rec: accept, or just trim margin. Do not overhaul the projection.**

### Small steep islands look like "pinecones" (Saint Lucia, Dominica)

- **Measured root cause:** exaggeration is a global **15×** applied to real height ÷ width, so visual steepness = `15 × (relief / frame-width)`. A 950 m peak on a 30 km island → ~0.47 (peak stands ~half the frame tall → bristly); a continent → ~0.025 (gentle). Same constant, wildly different look.
- **The principled fix = adaptive exaggeration:** taper the factor for small high-relief-ratio frames. This makes the *visual* relief MORE consistent across the gallery, not less: the "tuned once, applied globally" rule (ART.md) is what currently makes the look *inconsistent*. Bounded cost: only ~20-30 small steep islands re-render (~1 h, not a planet sweep). Touches the FROZEN `render_prep.py` (`EXAGGERATION = 15.0`), so it wants the sea-sync freeze lifted (ratified) first.
- **Note:** validated that atoll/island heroes themselves read well (Maldives/Marshall are striking): the problem is only over-exaggeration of *steep* small islands, not small frames per se.

## Hero and block renders differ in their contents, when only their projection should (raised 2026-08-24)

> **OPEN** · look-call · needs-gpu · **reopens when** a hero re-render is scheduled. Every part of it is a hero deficiency, and none of it changes a raytraced tile.

`scene_build` is one rig with two callers, and the split between them was meant to be geometric: `render_prep` warps a country into its own Albers equal-area conic, the block prep windows a global EPSG:3857 master. That much is inherent, and the per-row displacement correction exists only because Mercator's scale varies with latitude inside one block. What drifted alongside it is the LOOK, which was never meant to differ.

- **Snow comes from a different dataset on each path.** Tiles take NSIDC-0791 persistence plus all nineteen RGI 7.0 regions; heroes take ESA WorldCover class 70. HISTORY's *Snow source reworked* entry replaced WorldCover for the tiles on the finding that class 70 is permanent ice rather than seasonal snow, and the hero path kept it. `snow_mask.py` states a coherent reason of its own (the hero's editorial stance is eternal snow), so this is half a decision and half a question nobody re-asked after the tile side moved.
- **Sea ice reaches the block rig and never the hero rig.** HISTORY's *sea ice reaches the rig* entry wires one ocean-gated alpha in the block prep. Nothing records a decision to leave heroes out, so an Arctic country's hero draws open water where its own tiles draw pack.
- **The rig's conditional branches exist only because of that divergence**, and they are where the inline literals that bypassed the freshness recipe were living. Converging the two paths removes the branches rather than guarding them.

**The target is that projection is the only thing the two paths may differ in**: same layers, same sources, same constants, with the frame and the CRS as the only arguments. Getting there means giving the hero path the tile path's layer set rather than the reverse, since the tile set is the one that was revised on evidence.

Deferred past the 22h Earth pass deliberately: every part of it is a HERO deficiency, and none of it changes a raytraced tile.

## The snow persistence source paints salt playas white, and nobody has counted them (analysed 2026-08-25)

> **OPEN** · look-call · needs-render-store. Nothing named would reopen it, because **the sizing has not been done and that is the open question**, not the fix.

- **What it looks like:** small hard-edged white blobs on terrain that has never held snow. Two on the Iranian plateau, at **52.87E 32.15N** (the Gavkhouni salt marsh) and **55.39E 29.33N** (the Sirjan playa), sitting beside the correctly drawn Bakhtegan and Tashk lakes.
- **The cause is one layer and the others are eliminated.** Sampling every input at both sites against a desert control 40 km east: `snow_persistence_3857` reads **5,434 to 7,418** where the control reads **0.12 mean, 2.63 max**, while `glacier`, `addrock`, `seaice`, `water` and `ocean` are all exactly **0**. NSIDC-0791 classifies bright evaporite crust as persistent snow, and the pipeline paints what it is told.
- **It is NOT a raytracing defect and it is live in production.** The same pixels in the previous composite pyramid are already 100% near-white at Sirjan and 66% at Gavkhouni. The raytraced pass moved them 239 to 244 and 227 to 234 luminance, so it brightened them slightly and did not create them.
- **The next action is a measurement, not a fix.** 4,931 near-white pixels is 0.049% of a 3641 x 2742 Iran window, and nobody has swept the planet. Every low-latitude playa is a candidate: Etosha, Uyuni, the Lut, the Australian salt lakes. **The answer at five sites and the answer at five hundred are different decisions**, and the sweep is a real job on the 30 GB master.
- **Why a fix is not obvious even once sized.** The layer is a persistence percentage with no class information, so nothing in it distinguishes salt from snow. Masking by latitude would take real snow off mid-latitude ranges, which is the failure that made the tiles drop WorldCover class 70 in the first place. A separate playa mask is a new dataset and a new licence.

## Small debts and open calls, carried out of the working plan (parked 2026-08-24)

> **MIXED**, and the subsections below carry the states. The guard repairs under *One concept with two homes* are the most pickable work in this file: they need a clone and nothing else.

The working plan had become the project's only backlog as well as its live state, which is why it kept hitting its own line cap. These are the items that had no deadline and no relation to the arc in hand. None is urgent; each is here so it is greppable rather than compressed away.

### Stated numbers that are wrong, and cannot go red

- **The cap's elevation resolution is wrong in two files and the error is load-bearing.**
  - `CAP_ELEV_PX`'s comment says the disc is "2,668 km diameter, ~5.2 km/px" and `polarCaps.ts`'s `RINGS` comment repeats the 5.2. Both are edge-78 figures; the truth is 2,223.9 km and 4.34 km/px.
  - Those same two comments are the mesh ladder's ONLY sizing argument: `RINGS = 160` is justified as sitting "just under" 5.2 km/px, and against the real 4.34 the mesh is no longer the limit it claims to be. So correcting the comment also reopens whether 160 is right.
- **The TERRAIN staleness claim is unverified**: its sidecar is not at `planet_terrain/terrain_params.json`, so the claim rests on a path that does not exist.
- **The Mars DEM ships a `.tif.md5` its acquirer ignores**, and the mosaic host now has two spellings that nothing ties together.

### Test and freshness gaps

- **Nothing pins any of the gallery manifest.** A garbage `countries.json` with cold caches still passes 1,415 of 1,415, so no test reads the real one.
- **`--mosaic` redirects the raster and its markers but not the recipe**, so a scratch A/B restages the shipping planet's freshness. `--work` is the workaround rather than the fix.
- **Open call: should `check.sh` run the suite a second time under an empty `MAPS_DATA`?** 17.5 s to reproduce CI exactly. Without it, a store-reading test is green locally and red only after a push.
  - **The trigger has now fired twice.** Five recipe tests in `test_block_render.py` went red in CI this way, and then a registry sweep in `test_planet_pass.py` did the same, in a module written after the first was fixed. Both were green on every local gate.
  - The second one is what settles the shape of the objection: the fix for the first was a per-file helper, so the next file could not inherit it. A gate is the only form of this that reaches a module nobody has written yet.
- **An explicit env override on `pass_cap.HEAVY_JOB_GIB`** is the half of the ratified cap ruling `4f4daf8` that never landed. The two measured caps stay fixed either way.
- **Every planet fusion chunk is older than the mosaics it was fused from, and nothing can notice.** `fuse_planet.fuse_cell` skips a cell on `heightfield_10s.tif` EXISTENCE, so rebuilding `dem_mosaic.vrt` or `wbm_mosaic.vrt` after a tile download never restages one.
  - Measured on `e010_n70`: re-fusing today moves **928 px of 12.96 M, 0.0072%**, scattered and symmetric. Small per cell, systematic across all 648, and invisible from disk.
  - The module already guards the OPPOSITE direction, warning that a stale mosaic fuses new land as ocean. This is the same hazard with the arrow reversed and no guard at all.
  - The fix is an mtime gate rather than an existence one, which is what every other stage in this pipeline already uses. Cheap; unscheduled because a full re-fuse is 15 min and nobody has judged whether 0.0072% is worth spending it on.

### One concept with two homes

- **The two render preps are named in opposite orders, and the package docstring no longer matches.**
  - `render_prep` and `prep_block` are the same category of stage: build a render directory, then shell into `scene_build`. Nothing in HISTORY justifies the difference, so it is drift.
  - `pipeline/render/__init__.py` says "the rest of this package is the hero path" and enumerates four modules. `prep_block.py` sits in that package, is not the hero path, and is not enumerated.
  - Renaming changes no recipe, so it is neither cheaper nor dearer after the render pass.
- **17 mutation cases name a guard that does not catch them**, found by `sabotage.py --audit` on 2026-08-24. Each is a guard repair rather than a pipeline change, and none of them changes a rendered pixel, so none gates a render pass. HISTORY's *the audit runs* entry carries every conclusion about the audit and none of the items, which is why they are enumerated here.
  - **The list is re-derivable in 8.5 min** by re-running `--audit`, and a re-run is the honest list rather than this one, which rots as the table changes. Prefer it if any of the 17 has been touched since.
  - The 394 web and collection cases could not be audited at all, since neither suite can be narrowed to one guard, so their guards remain unproven and are not counted here.
  1. *a refactor moves a needle out from under its case*. A regression from the same day: the in-flight skip keys on the mutated PATH, so every needle pointing at that file is skipped, the moved one included. Fix is to key it on the in-flight CASE.
  2. *the region preview regrows its own exaggeration*, `test_exaggeration_is_shared`.
  3. *the hillshade forgets the ground scale*. The guard captures `exaggeration` and not `ground_scale`, on a body whose ground ratio is exactly 1.0.
  4. *the warp asks the disk before the body*, caught by three other tests and naming a fourth.
  5. *the reprojection stops removing its target*. CONFIRMED WRONG against the full suite; the real catcher is `test_a_corrupt_intermediate_does_not_survive_into_the_burn`.
  6. *the brightness recipe stops recording its weights*, `test_changed_weights_are_STALE`.
  7. *the recipe drops the source edition*, `test_a_republished_source_edition_is_STALE`.
  8. *the cap recipe stops recording which layers are off*, `test_turning_a_layer_off_restages_although_its_source_stops_being_a_dependency`.
  9. *the gazetteer extracts as it verifies*, `test_a_bad_digest_writes_NOTHING_not_even_the_members_before_it`.
  10. *an edge ACROSS the meridian counts as one along it*. CONFIRMED MISSED against the full suite; nothing catches it.
  11. *the writer re-derives the law instead of calling it*. The replacement is numerically identical, so only asserting `row_scale` is CALLED can catch it.
  12. *the context is sized at the block centre*, `test_no_block_row_is_narrower_than_sizing_at_its_centre`.
  13. *the scratch VRT is built outside the directory*, `test_an_unchanged_source_set_leaves_the_file_untouched`.
  14. *served assets are resolved against the data store*, `test_served_assets_follow_the_checkout_not_the_data_store`.
  15. *the About page keeps the superseded output licence*, `test_every_site_states_the_output_license`.
  16. *gen_spotlight restates the ladder instead of importing it*, `test_the_ladder_matches_the_spotlight_overlay`.
  17. *the render dir drifts from the work dir*, `test_it_follows_a_relocated_store`.
- **A freshness recipe could be derived from the built scene rather than enumerated by hand.** `scene_dump.py` already dumps the graph exhaustively, including sampled ramp evaluations, and it reads the BUILT graph rather than the source, so it sees values written inline. Hashing it would have caught all three instances of the enumeration going short. The obstacle is that it needs real Blender, where the freshness check today runs with `bpy` stubbed; the graph is body-shaped rather than block-shaped, so one invocation per pass would do.
- **The composite and cap tiers still fold the white law without recording it.**
  - `layer_producers.white_law` exists and `block_render.params` reads it; `shade_planet.composite_params` and `cap_render.cap_recipe`, which embeds it, do not.
  - So a layer moving between `WHITE_UNION` and `WHITE_EXCLUSIONS` repaints the Antarctic outcrop on both and leaves both looking fresh. Measured on the recipe strings, with the block tier as the positive control.
  - Deferred on cost rather than on doubt: adopting it restages whatever those tiers still produce, and both bodies are `planet_producer="composite"` today, so doing it before Earth flips would recompute a 57:23 composite that unit 9 replaces. After the flip it is Mars's composite plus both caps.
  - It does not retire with the switch. `cap_render` calls `shade.composite` outright and reuses `composite_params`, so the caps keep both alive past units 9 and 10.
- **No test pins that `PERENNIAL_ICE` and `GLACIERS` are IN `WHITE_UNION`.** Every membership assertion in the suite is negative, so a layer silently ceasing to be white is caught by nothing. Belongs with the guard repairs above rather than with the recipe work, since it changes no recipe.
- **The RGI glacier path is spelled twice and its burn argv has no owner.**
  - `snow.RGI_GPKG` and `download_rgi.GPKG` are one path written in two places, and `rasterize_glaciers_raster` carries a copy of the argv `vector_raster.rasterize_argv` now owns.
  - The rock layer deliberately has one of each, so this is the last instance rather than a pattern.
- **INVENTORY does not track `~/terrella-scratch`**, so roughly 20 GB of arc scratch is invisible to the file that calls itself the storage map, and no reclaim rule reaches it.

### Rejected, with the reason, so it is not re-proposed

- **Bedmap3 `bm3_masks.tif` as a replacement for the whole Antarctic white rule: REJECTED for now.**
  - In its favour: CC BY 4.0, no OAuth, 345 MB, 500 m EPSG:3031, and the only product carrying ice and rock together (classes grounded, transient, floating, rock, nodata).
  - Against it: its coastline is the grounding line and cannot match our fused DEM's, its nodata conflates sea with no-coverage, and its rock reads 75,627 km2 against ADD's 26,340 on our grid.
  - Reopening needs a coastline reconciliation, not a re-read of the licence.
- **Every superseded R2 object STAYS**: R2 has no undelete, so the previous cut is the whole difference between a rollback that is a revert-and-redeploy and one that is a re-render.
  - **Do not read a count or a list out of this line.** The enumeration it replaces named four objects and was already stale by two, because a re-cut supersedes an object without any reader that can go red.
  - Derive the set instead: the objects in `terrella-tiles` that no `objectKey` in `web/src/lib/tileAddress.ts` names. It measures 6 objects and 8.57 GB, about 13 cents a month at $0.015 per GB-month, which prices the policy rather than any one object.
- **`_crism_scout` (60 MB) is the one reclaim not taken.** Its index tables are the evidence behind a closed census, and 0.24% of the reclaim is not worth destroying them for.

### Unpriced or unscheduled work

- **72 of Earth's 1,024 blocks are under-sized at the sun's OWN altitude**, which is a different defect from the soft-sun limb and outlived its rejection. `haloed` maxes relief per BLOCK, so a ring pairing one block's summit against an adjacent block's valley holds more range than the sizing block was told about; worst ratio 0.674.
  - **Do not act on this before it gets the treatment the limb got.** It is a census of RANGES, and the limb's control established that only a single occluder's REACH puts a shadow anywhere, so the same instrument that manufactured that finding produced this one. `block_plan.context_for` carries the mechanism.
  - The ring measured is one 512 px cache cell wide, so the number itself is a lower bound on the population rather than a measurement of the shortfall.
- **The last unbuilt pipeline optimisation**: 0-filling GLOBathy instead of `-srcnodata` deletes about 51% of the 62-minute lake warp, but it is a source rewrite that pays only on a re-extract.
- **256 px DEM assets stay unmeasured**: 4x fewer bytes per slot with slot count and refetch unchanged, but z8 falls from 306 to 612 m/px and z9 cannot rescue it.
- **The low-data path is unpriced at both ends.** Replacing `downlink` wants a pure `summariseTileTimings` over `PerformanceResourceTiming`, and `saveData` visitors are routed to a gallery that then serves everyone identically.
- **The `Protocol` conversion for both ice registries**: no behaviour change, reversible, unscheduled.
- **The next Mars pass rebuilds the ice caps and the ice tile layer.** The recovered units carry today's mtime and `_mars_sources` gates on mtimes, so the output is correct but not free.
- **`data/raw` is written by `pipeline/acquire/*` alone**, so making it read-only on disk is the candidate that removes the target instead of detecting the write. Rohan's call, being 1.1 TB of his own data.

### A colour call and a product question

- **`MARS_MODAL_GROUND` is the authored stop and the tiles ship the composited one**, so the space floor behind a missing tile is cooler than its surroundings. Cosmetic, pre-existing, a colour call.
- **Mars phase 4 is an open product question rather than queued work**: whether the body gets a curated landmark set or a hero per feature. Nothing downstream is waiting on the answer.
