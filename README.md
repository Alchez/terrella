# Terrella

Ray-traced relief maps of every country, presented as a static website that starts as an image gallery and upgrades — where the visitor's hardware allows — into an interactive 3D globe.

A *terrella* — a "little Earth" — is the small model globe that early scientists like William Gilbert and Kristian Birkeland spun to study the whole planet at once. This is a modern one: every country rendered from real elevation, not drawn.

## The idea

Each country's hero image is **ray-traced in Blender Cycles from real elevation data** — Copernicus GLO-30 land and GEBCO bathymetry fused into one seamless heightfield, lit by a low sun for long relief shadows, colored by elevation and depth, and finished with crisp white Natural Earth borders. The aesthetic follows Frank Ramspott's "3D Render Topographic Map": the result reads more like a physical relief model photographed under raking light than a conventional map.

The site meets each visitor where their device can take them, in three tiers:

- **Gallery** — responsive hero images; renders instantly for everyone, and the pessimistic default while a capability probe runs.
- **Globe** — a MapLibre globe draping pre-shaded raster tiles (needs WebGL2).
- **Full** — the globe plus 3D terrain displacement, idle motion, and lazy-loaded 8K heroes on country click (gated on GPU tier and network).

The probe upgrades optimistically and the visitor can override the choice. Everything is pre-rendered and served statically — no compute at request time.

## How it's built

Two asset pipelines feed one site. Heroes are pre-rendered offline in Blender from the fused heightfield (one scene rig, framed per country). A global **raster tile pyramid** approximates the same look without ray tracing — hillshade + sky-view shading and the same color ramps — and will ship as a single **PMTiles** archive so the globe needs no tile server. The frontend is a static Astro site; it's served behind nginx on self-hosted infrastructure with aggressive caching. Everything is reproducible from committed source — **no rendered assets or DEM data live in git**, only code, config, and per-country frame pins.

## Status

- **Phase 1 — done.** The all-country hero render pipeline; ~200 heroes, each reproducible from source.
- **Phase 2 — done bar the packaging.** The global raster tile pyramid is built and serving the globe (512 px tiles, zoom 0–8, planet-wide land + bathymetry + snow + lake depth). Packaging it as PMTiles is a Phase 4 step.
- **Phase 3 — Tiers 1 and 2 ship.** The gallery and the interactive MapLibre globe are both live, with a capability probe steering each visitor to the one their device can take. Tier 3's 3D terrain displacement is deferred — it needs an elevation-tile pyramid that isn't built yet.
- **Phase 4 — next.** Deploy and polish.

## Read next

- **Running the pipeline / regenerating a hero** → [`docs/pipeline.md`](docs/pipeline.md)
- **How a country becomes a framed render** (the math) → [`docs/framing-math.md`](docs/framing-math.md)
- **The living plan and every decision** → [`PLAN.md`](PLAN.md)
- **The locked aesthetic** (sun, ramps, exaggeration) → [`ART.md`](ART.md)
- **Data sources & licenses** → [`ATTRIBUTIONS.md`](ATTRIBUTIONS.md)
