# Terrella

**[terrella.alchez.dev](https://terrella.alchez.dev)**

Ray-traced relief maps of every country on Earth, and of Mars. A static site that opens as an image gallery and upgrades, where the hardware allows, into an interactive globe.

A *terrella*, a "little Earth", is the model globe early scientists spun to study the whole planet at once. This one is rendered from real elevation, not drawn.

Terrella is one person's project for learning how relief maps get made, published so it can be read, run and reused.

## Three tiers

A capability probe picks one pessimistically and upgrades from there; the visitor can override it.

- **Gallery**: instant for everyone. Hero images on Earth; on Mars, a gazetteer of named features.
- **Globe**: MapLibre draping pre-shaded raster tiles. Needs WebGL2.
- **Full**: plus terrain displacement and idle motion. On Earth, a country click opens an 8K hero.

## How it's built

- **Heroes**: Blender Cycles, from Copernicus GLO-30 land and GEBCO bathymetry fused into one heightfield. Low sun, coloured by elevation and depth, in an aesthetic Frank Ramspott's topographic renders helped define.
- **Tiles**: the same rig again, ray traced block by block, so the globe and the heroes are lit by one renderer rather than by two that have to be kept agreeing.
- **Mars is the same pipeline with a different body.** Exaggeration, zoom ceiling, ramp and radii all belong to the body. It arrives pre-fused, as the USGS MOLA/HRSC blend, so there is no fusion tier to run, and it has no ocean, borders or heroes.
- **Why a renderer and not a hillshade**: QGIS and `gdaldem` shade each pixel from the slope beneath it, so nothing in the result knows a ridge stands between that pixel and the sun, and at this exaggeration a gentle real slope presents as a steep one, runs past a low sun and clips to zero across a large share of a mountain range, which `ART.md` measures. That is not a prediction here: Mars shipped the other way once, a hillshade with a ported fill sun and a sky-view term composited in GDAL, and it was replaced by Cycles rather than tuned.
- **Delivery**: three PMTiles archives per body (relief, terrain, vector), the names `{layer}` takes, addressed `{body}/{layer}/{token}/{z}/{x}/{y}` so an address names its own archive. The browser never opens one; a tile server returns a single tile per request.

Everything is pre-rendered, so there is no compute at request time, and no rendered assets or DEM data live in git.

## License

Code [MIT](LICENSE). Imagery [CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0/): attribution, and adaptations share alike. Underlying data has its own terms and required credits.

## Getting the data

Every pyramid the site draws from is downloadable as the PMTiles archive it is served out of, listed at [terrella.alchez.dev/archives](https://terrella.alchez.dev/archives/). Each file states its own credit and what is in it, so a copy stays attributable once it leaves here.

The tile endpoint is open as well, and it is the wrong thing to build on. It runs a worker per tile against a daily allowance shared with the site itself, and no address is promised to stay put: a re-cut ships under a new key and every tile URL moves with it. Take an archive and serve it yourself.

## Read next

- Running the checks, which need no data or GPU → [`CONTRIBUTING.md`](CONTRIBUTING.md)
- How the system is built, and which questions are settled → [`CLAUDE.md`](CLAUDE.md)
- Running the pipeline, from a fresh machine to a served globe → [`docs/pipeline.md`](docs/pipeline.md)
- What adding a moon or another planet would take → [`docs/adding-a-body.md`](docs/adding-a-body.md)
- Framing math → [`docs/framing-math.md`](docs/framing-math.md)
- Frontend, and running the dev server → [`web/README.md`](web/README.md)
- Aesthetic decisions → [`ART.md`](ART.md)
- Measured stage runtimes → [`PROCESS.md`](PROCESS.md)
- Data sources & licenses → [`ATTRIBUTIONS.md`](ATTRIBUTIONS.md)
- Downloading a tile archive instead of rendering one → [`CONTRIBUTING.md`](CONTRIBUTING.md)
- Parked ideas, and what was deliberately not built → [`FUTURE.md`](FUTURE.md)
- What changed, when, and how long this has taken → [the commit history](https://github.com/Alchez/terrella/commits/main/)
- Driving Blender, and the shader gotchas → [`.claude/skills/blender-rig/`](.claude/skills/blender-rig/SKILL.md)
- Acquiring or refetching a source dataset → [`.claude/skills/acquire-data/`](.claude/skills/acquire-data/SKILL.md)
- Reclaiming disk, and what must never be deleted → [`.claude/skills/reclaim-pass/`](.claude/skills/reclaim-pass/SKILL.md)
- Serving, the tile Worker and its landmine → [`.claude/rules/tile-worker-and-delivery.md`](.claude/rules/tile-worker-and-delivery.md)

## Prior art

Daniel Huffman, "Creating Shaded Relief in Blender", is the canonical technique this is built on.
For land and sea fusion: ETOPO 2022 (NOAA), Tozer et al. 2019 (SRTM15+), the GMT `grdblend` docs and
Tom Patterson's shadedrelief.com. The globe and the tile archive follow the MapLibre globe
projection docs and the PMTiles spec (Protomaps).
