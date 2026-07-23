# Attributions & credits

Terrella is built entirely from open data and open-source tools. This file is the single source of truth for credits; the site's About page draws from it. Where a license requires a specific on-page or in-metadata statement, the exact string is given below.

## Terrella's own outputs

- **Code** (this repository): MIT — see `LICENSE`.
- **Rendered imagery** (hero renders, map tiles, polar caps — everything the pipeline draws): **CC BY-NC 4.0**. Free to share and adapt for non-commercial use — education, entertainment, personal projects — with attribution to "Terrella (Rohan Bansal)". Commercial use is reserved; separate commercial grants can be issued case-by-case, and individual images can additionally be released under a free-culture license (e.g. CC BY-SA for Wikimedia use) at the author's discretion — multi-licensing is explicitly permitted. Chosen deliberately over plain CC BY: the known trade-off is that Wikimedia projects reject NC-licensed media.

## Data sources

| Dataset | Role in the pipeline | License |
|---|---|---|
| [Copernicus DEM GLO-30](https://dataspace.copernicus.eu/explore-data/data-collections/copernicus-contributing-missions/collections-description/COP-DEM) | land elevation (the heightfield) | Copernicus WorldDEM-30 licence — free & open incl. derived-product distribution; required notices below ([licence text](https://documentation.dataspace.copernicus.eu/APIs/SentinelHub/Data/DEM/resources/license/License-COPDEM-30.pdf)) |
| [GEBCO 2026 Grid](https://www.gebco.net) | bathymetry, fused with the land DEM | Public domain / free for any use |
| [ESA WorldCover 2021 v200](https://esa-worldcover.org) | hero snow/ice mask (class 70); superseded for the tiles by NSIDC-0791 + RGI | CC-BY 4.0 |
| [NSIDC-0791 — MODIS/Terra Global Annual Snow-Cover Climatology](https://nsidc.org/data/nsidc-0791) | tile snow: latitude-ramped soft alpha from observed snow *persistence* (2001–2023) | NASA/NSIDC — free & open (US-government, public domain); cite DOI |
| [RGI 7.0 — Randolph Glacier Inventory](https://www.glims.org/RGI/) | tile snow: crisp permanent-ice (glacier) union over the persistence layer | CC-BY 4.0 |
| [OSI SAF OSI-450-a v3.0](https://osi-saf.eumetsat.int/products/osi-450-a) | tile + polar-cap sea ice: annual ice-frequency climatology (reference period 1991–2020) from the monthly-mean CDR | CC-BY 4.0 (EUMETSAT) |
| [GLOBathy](https://doi.org/10.1038/s41597-022-01132-9) | tile lake depth: modelled bathymetry that shades lakes instead of leaving them flat plates | **CC0** (public domain dedication) |
| [Natural Earth](https://www.naturalearthdata.com) | borders, coastlines, country bounding boxes | Public domain |

### Required / requested attribution strings

- **Copernicus DEM GLO-30** — for adapted/modified data (our case — Article 6(b) of the licence), the exact required notice is: *"produced using Copernicus WorldDEM-30 © DLR e.V. 2010-2014 and © Airbus Defence and Space GmbH 2014-2018 provided under COPERNICUS by the European Union and ESA; all rights reserved"*. The About page (or its legal notice) must also carry the Article 6(c) liability sentence: *"The organisations in charge of the Copernicus programme by law or by delegation do not incur any liability for any use of the Copernicus WorldDEM-30"* — and must not imply official endorsement by ESA/Copernicus (6(d)).
- **ESA WorldCover** — "© ESA WorldCover project 2021 / Contains modified Copernicus Sentinel data (2021) processed by ESA WorldCover consortium."
- **NSIDC-0791** — "Snow persistence from the MODIS/Terra Global Annual Snow-Cover Climatology (NSIDC-0791), NASA NSIDC DAAC (doi:10.5067/9R1AM6NNZLTV)." NASA/US-government data is public domain; the citation is a courtesy. Accessed via NASA Earthdata (earthaccess).
- **RGI 7.0** — "RGI 7.0 Consortium (2023), Randolph Glacier Inventory 7.0 (doi:10.5067/F6JMOVY5NAVZ), CC-BY 4.0." The regional shapefiles were fetched from UNESCO's open IHP-WINS re-host of the RGI/NSIDC files (the NSIDC data pool needs interactive-OAuth; IHP-WINS serves the identical data openly).
- **GEBCO** — "Reproduced from the GEBCO_2026 Grid, GEBCO Compilation Group (2026)."
- **GLOBathy** — "Lake depth from GLOBathy: Khazaei, B., Read, L.K., Casali, M., Sampson, K.M., Yates, D.N. (2022), *GLOBathy, the Global Lakes Bathymetry Dataset*, Scientific Data 9, 36 (doi:10.1038/s41597-022-01132-9)." **CC0**, so no attribution is legally required — this is an academic-citation courtesy, and we chose it deliberately: the tint-only architecture avoided a HydroLAKES join, which is what kept the whole depth layer CC0. The About page must also carry the *epistemics* (the depth shape is a modelled cone, surveyed scale for only 647 of 83,357 lakes) — that is an honesty obligation, not a licensing one.
- **OSI SAF** — "Sea-ice climatology derived from the OSI SAF Global sea ice concentration climate data record 1978–2020 (v3.0, 2022), OSI-450-a, EUMETSAT Ocean and Sea Ice Satellite Application Facility (doi:10.15770/EUM_SAF_OSI_0013)." CC-BY 4.0. The About page should note the reference period actually used (1991–2020 annual ice frequency).
- **Natural Earth** — public domain; a courtesy credit to naturalearthdata.com.

### Licensing posture

GEBCO (public domain), Natural Earth (public domain), NSIDC-0791 / MODIS (NASA, public domain), ESA WorldCover (CC-BY 4.0), RGI 7.0 (CC-BY 4.0), and OSI SAF OSI-450-a (CC-BY 4.0) all unambiguously permit derivative works, public display, and redistribution with attribution. Copernicus GLO-30 is the only source under a bespoke licence rather than PD/CC, and its terms have been **verified against the primary licence text** ([License-COPDEM-30.pdf](https://documentation.dataspace.copernicus.eu/APIs/SentinelHub/Data/DEM/resources/license/License-COPDEM-30.pdf)): Article 4 grants **reproduction, distribution, communication to the public, and adaptation/combination**, worldwide, without time limit or purpose restriction — commercial use of derived products included; Article 9 confirms the IPR in work produced *using* the DEM (our renders) belongs to us. The obligations are the two exact notices and the liability sentence above, plus no implied endorsement. The higher-resolution WorldDEM-10 is expressly outside this licence — this project uses only GLO-30.

## Tools & technique

- **Rendering** — [Blender](https://www.blender.org) (Cycles renderer, OptiX backend, OpenImageDenoise).
- **Geoprocessing** — [GDAL](https://gdal.org), [rasterio](https://rasterio.readthedocs.io), [NumPy](https://numpy.org).
- **Web** — [Astro](https://astro.build) (static site), [MapLibre GL JS](https://maplibre.org) (globe projection), [PMTiles](https://github.com/protomaps/PMTiles) (Protomaps).
- **Technique** — shaded relief in Blender after Daniel Huffman's canonical method; aesthetic reference: Frank Ramspott, "3D Render Topographic Map — Neutral."

## Made with AI

This project was built in collaboration with AI. The pipeline code, documentation, and Blender rendering setup were developed in a pair-programming workflow with Anthropic's Claude (via Claude Code). Data-source selection, design decisions, and final review are the author's.
