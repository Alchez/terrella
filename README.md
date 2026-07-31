# Terrella

**[terrella.alchez.dev](https://terrella.alchez.dev)**

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

Two asset pipelines feed one site:
- Heroes are pre-rendered offline in Blender from the fused heightfield (one scene rig, framed per country).
- A global **raster tile pyramid** approximates the same look without ray tracing — hillshade + sky-view shading and the same color ramps.

The data then ships as **PMTiles** archives — one of shaded relief, and a second holding terrain-RGB elevation for the 3D tier, distinguished by a path prefix. The browser never opens them: a thin tile server reads the byte range for one `z/x/y` tile and returns just that tile — an Astro dev middleware locally, an edge worker in production. Serving a multi-gigabyte archive to the browser directly is the one shape a CDN cannot cache, so the ranging stays on the server side.

The frontend is a static Astro site, served from a CDN edge worker with the heavy assets — heroes, border vectors, the tile archive — in object storage beside it. Everything is reproducible from committed source — **no rendered assets or DEM data live in git**, only code, config, and per-country frame pins.

## License

Code is [MIT](LICENSE). The rendered imagery (hero renders, tiles, polar caps) is [CC BY-NC 4.0](https://creativecommons.org/licenses/by-nc/4.0/) — free for educational, personal, and entertainment use with attribution; commercial use reserved. Underlying data carries its own licenses and required credits → [`ATTRIBUTIONS.md`](ATTRIBUTIONS.md).

## Read next

- **Running the pipeline / regenerating a hero** → [`docs/pipeline.md`](docs/pipeline.md)
- **How a country becomes a framed render** (the math) → [`docs/framing-math.md`](docs/framing-math.md)
- **The locked aesthetic** (sun, ramps, exaggeration) → [`ART.md`](ART.md)
- **Measured stage runtimes** → [`PROCESS.md`](PROCESS.md)
- **Data sources & licenses** → [`ATTRIBUTIONS.md`](ATTRIBUTIONS.md)

### A note on `

Comments and docs throughout this repo cite decisions as `. Those point at a
dated decision archive, and a companion living plan, that are kept **outside** the repository — they
are how the work gets done rather than part of what it ships. So a citation names *why* a value is
what it is and tells you the reasoning was written down; it is not a link you can follow here. The
constants themselves, and the reasoning that has to travel with the code, are in the files above and
in the source comments beside each decision.
