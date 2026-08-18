# Terrella

**[terrella.alchez.dev](https://terrella.alchez.dev)**

Ray-traced relief maps of every country on Earth, and of Mars. A static site that opens as an image
gallery and upgrades, where the hardware allows, into an interactive globe.

A *terrella*, a "little Earth", is the model globe early scientists spun to study the whole planet
at once. This one is rendered from real elevation, not drawn.

## Three tiers

A capability probe picks one pessimistically and upgrades from there; the visitor can override it.

- **Gallery**: instant for everyone. Hero images on Earth; on Mars, a gazetteer of named features.
- **Globe**: MapLibre draping pre-shaded raster tiles. Needs WebGL2.
- **Full**: plus terrain displacement and idle motion. On Earth, a country click opens an 8K hero.

## How it's built

- **Heroes**: Blender Cycles, from Copernicus GLO-30 land and GEBCO bathymetry fused into one
  heightfield. Low sun, coloured by elevation and depth, after Frank Ramspott's
  *3D Render Topographic Map*.
- **Tiles**: a raster pyramid approximating that look without ray tracing, using hillshade, sky-view
  shading and the same ramps.
- **Mars is the same pipeline with a different body.** Exaggeration, zoom ceiling, ramp and radii
  all belong to the body. It arrives pre-fused, as the USGS MOLA/HRSC blend, so there is no fusion
  tier to run, and it has no ocean, borders or heroes.
- **Delivery**: three PMTiles archives per body (relief, terrain-RGB, vectors), addressed
  `{body}/{layer}/{token}/{z}/{x}/{y}` so an address names its own archive. The browser never opens
  one; a tile server returns a single tile per request.

Everything is pre-rendered, so there is no compute at request time, and no rendered assets or DEM
data live in git.

## License

Code [MIT](LICENSE). Imagery [CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0/):
attribution, and adaptations share alike. Underlying data has its own terms and required credits.

## Read next

- Running the checks, which need no data or GPU → [`CONTRIBUTING.md`](CONTRIBUTING.md)
- Pipeline, and regenerating a hero → [`docs/pipeline.md`](docs/pipeline.md)
- Framing math → [`docs/framing-math.md`](docs/framing-math.md)
- Frontend, and running the dev server → [`web/README.md`](web/README.md)
- Aesthetic decisions → [`ART.md`](ART.md)
- Measured stage runtimes → [`PROCESS.md`](PROCESS.md)
- Data sources & licenses → [`ATTRIBUTIONS.md`](ATTRIBUTIONS.md)
