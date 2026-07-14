# Attributions & credits

Terrella is built entirely from open data and open-source tools. This file is the single source of truth for credits; the site's About page draws from it. Where a license requires a specific on-page or in-metadata statement, the exact string is given below.

## Data sources

| Dataset | Role in the pipeline | License |
|---|---|---|
| Copernicus DEM GLO-30 | land elevation (the heightfield) | Copernicus DEM free/open license — see caveat |
| GEBCO 2026 Grid | bathymetry, fused with the land DEM | Public domain / free for any use |
| ESA WorldCover 2021 v200 | hero snow/ice mask (class 70); superseded for the tiles by NSIDC-0791 + RGI | CC-BY 4.0 |
| NSIDC-0791 — MODIS/Terra Global Annual Snow-Cover Climatology | tile snow: latitude-ramped soft alpha from observed snow *persistence* (2001–2023) | NASA/NSIDC — free & open (US-government, public domain); cite DOI |
| RGI 7.0 — Randolph Glacier Inventory | tile snow: crisp permanent-ice (glacier) union over the persistence layer | CC-BY 4.0 |
| Natural Earth | borders, coastlines, country bounding boxes | Public domain |

### Required / requested attribution strings

- **Copernicus DEM GLO-30** — distribute derived products with a "Contains modified Copernicus DEM data" notice (the source DEM is Copernicus WorldDEM-30, © DLR e.V. and © Airbus Defence and Space, provided under COPERNICUS by the European Union and ESA). Confirm the exact wording against the current GLO-30 license before publishing.
- **ESA WorldCover** — "© ESA WorldCover project 2021 / Contains modified Copernicus Sentinel data (2021) processed by ESA WorldCover consortium."
- **NSIDC-0791** — "Snow persistence from the MODIS/Terra Global Annual Snow-Cover Climatology (NSIDC-0791), NASA NSIDC DAAC (doi:10.5067/9R1AM6NNZLTV)." NASA/US-government data is public domain; the citation is a courtesy. Accessed via NASA Earthdata (earthaccess).
- **RGI 7.0** — "RGI 7.0 Consortium (2023), Randolph Glacier Inventory 7.0 (doi:10.5067/F6JMOVY5NAVZ), CC-BY 4.0." The regional shapefiles were fetched from UNESCO's open IHP-WINS re-host of the RGI/NSIDC files (the NSIDC data pool needs interactive-OAuth; IHP-WINS serves the identical data openly).
- **GEBCO** — "Reproduced from the GEBCO_2026 Grid, GEBCO Compilation Group (2026)."
- **Natural Earth** — public domain; a courtesy credit to naturalearthdata.com.

### Licensing posture (why this project is legally viable)

GEBCO (public domain), Natural Earth (public domain), NSIDC-0791 / MODIS (NASA, public domain), ESA WorldCover (CC-BY 4.0), and RGI 7.0 (CC-BY 4.0) all unambiguously permit derivative works, public display, and redistribution with attribution. Copernicus GLO-30 is the only source under a bespoke EULA rather than PD/CC: it permits creating **modified/derived products** and **distributing them publicly** with attribution, which is exactly what this site does (free display of derived relief renders). Its core prohibition is **reselling the raw DEM as data**. This has NOT been fully verified against the primary license text — for a free website it is fine; **before any commercial use (e.g. selling prints), read the current GLO-30 license directly**, as some Copernicus product licenses restrict commercial derivative use.

## Tools & technique

- **Rendering** — [Blender](https://www.blender.org) (Cycles renderer, OptiX backend, OpenImageDenoise).
- **Geoprocessing** — GDAL, rasterio, WhiteboxTools.
- **Web serving** — [MapLibre GL JS](https://maplibre.org) (globe projection), [PMTiles](https://github.com/protomaps/PMTiles) (Protomaps).
- **Technique** — shaded relief in Blender after Daniel Huffman's canonical method; aesthetic reference: Frank Ramspott, "3D Render Topographic Map — Neutral."

## Made with AI

This project was built in collaboration with AI. The pipeline code, documentation, and Blender rendering setup were developed in a pair-programming workflow with Anthropic's Claude (via Claude Code). Data-source selection, design decisions, and final review are the author's.
