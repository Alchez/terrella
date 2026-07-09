# Attributions & credits

Relief Globe is built entirely from open data and open-source tools. This file is the single source of truth for credits; the site's About page draws from it. Where a license requires a specific on-page or in-metadata statement, the exact string is given below.

## Data sources

| Dataset | Role in the pipeline | License |
|---|---|---|
| Copernicus DEM GLO-30 | land elevation (the heightfield) | Copernicus DEM free/open license — see caveat |
| GEBCO 2026 Grid | bathymetry, fused with the land DEM | Public domain / free for any use |
| ESA WorldCover 2021 v200 | permanent snow/ice mask (class 70) | CC-BY 4.0 |
| Natural Earth | borders, coastlines, country bounding boxes | Public domain |

### Required / requested attribution strings

- **Copernicus DEM GLO-30** — distribute derived products with a "Contains modified Copernicus DEM data" notice (the source DEM is Copernicus WorldDEM-30, © DLR e.V. and © Airbus Defence and Space, provided under COPERNICUS by the European Union and ESA). Confirm the exact wording against the current GLO-30 license before publishing.
- **ESA WorldCover** — "© ESA WorldCover project 2021 / Contains modified Copernicus Sentinel data (2021) processed by ESA WorldCover consortium."
- **GEBCO** — "Reproduced from the GEBCO_2026 Grid, GEBCO Compilation Group (2026)."
- **Natural Earth** — public domain; a courtesy credit to naturalearthdata.com.

### Licensing posture (why this project is legally viable)

GEBCO (public domain), Natural Earth (public domain), and ESA WorldCover (CC-BY 4.0) all unambiguously permit derivative works, public display, and redistribution with attribution. Copernicus GLO-30 is the only source under a bespoke EULA rather than PD/CC: it permits creating **modified/derived products** and **distributing them publicly** with attribution, which is exactly what this site does (free display of derived relief renders). Its core prohibition is **reselling the raw DEM as data**. This has NOT been fully verified against the primary license text — for a free website it is fine; **before any commercial use (e.g. selling prints), read the current GLO-30 license directly**, as some Copernicus product licenses restrict commercial derivative use.

## Tools & technique

- **Rendering** — [Blender](https://www.blender.org) (Cycles renderer, OptiX backend, OpenImageDenoise).
- **Geoprocessing** — GDAL, rasterio, WhiteboxTools.
- **Web serving** — [MapLibre GL JS](https://maplibre.org) (globe projection), [PMTiles](https://github.com/protomaps/PMTiles) (Protomaps).
- **Technique** — shaded relief in Blender after Daniel Huffman's canonical method; aesthetic reference: Frank Ramspott, "3D Render Topographic Map — Neutral."

## Made with AI

This project was built in collaboration with AI. The pipeline code, documentation, and Blender rendering setup were developed in a pair-programming workflow with Anthropic's Claude (via Claude Code). Data-source selection, design decisions, and final review are the author's.
