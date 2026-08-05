# Attributions & credits

Terrella is built entirely from open data and open-source tools. This file is the single source of truth for credits; the site's About page draws from it. Where a license requires a specific on-page or in-metadata statement, the exact string is given below.

## Terrella's own outputs

- **Code** (this repository): MIT — see `LICENSE`.
- **Rendered imagery** (hero renders, map tiles, polar caps — everything the pipeline draws, for every body): **CC BY-SA 4.0**. Free to share and adapt for any purpose, commercial use included, with attribution to "Terrella (Rohan Bansal)" and on the condition that adaptations carry the same license. **One license covers both planets rather than one per body.** The Mars blend's publisher labels part of its input share-alike (below), and share-alike is the only output license that complies under both readings of that label; extending it to Earth is a choice rather than an obligation, and it buys a single sentence that is true of every image on the site. The accepted trade is that commercial use is no longer reserved, and that Creative Commons licenses are irrevocable — nothing already published under this can be narrowed later. What it buys back is Wikimedia, which rejects NC-licensed media and accepts BY-SA.

## Data sources

Grouped by body, because the two planets are built from different data under different terms and a merged table invites the reader to assume one set of obligations covers both. The About page carries the same split for the same reason.

### Earth

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

### Mars

| Dataset | Role in the pipeline | License |
|---|---|---|
| [Mars MGS MOLA – MEX HRSC Blended DEM Global 200m v2](https://astrogeology.usgs.gov/search/map/mars_mgs_mola_mex_hrsc_blended_dem_global_200m) | the entire heightfield — Mars enters the pipeline already fused, so there is no acquire or fuse tier | Publisher states: **access constraints "MOLA (CC0) and HRSC (CC BY-SA 3.0 IGO)"**, use constraints "Please cite authors" |

Mars has one source and no others are used. There is no bathymetry, no snow, no glacier, no sea-ice and no boundary dataset, because none of those exist as a Mars product we ship — the relief is the whole picture.

#### The share-alike finding, which contradicts an earlier reading and is answered by taking the strict one

**The USGS product page for the blend states its access constraints as "MOLA (CC0) and HRSC (CC BY-SA 3.0 IGO)".** That was read verbatim off the publisher's own metadata for the exact file this project downloads — the page's "Online File Link" is `Mars_HRSC_MOLA_BlendDEM_Global_200mp_v2.tif`, the 11 GB mosaic in `data/raw/mars/`.

It mattered because the rendered imagery used to be CC BY-NC 4.0, and **share-alike input cannot flow into a non-commercial output** — the two conditions are incompatible in that direction, and the permitted direction is the other one. That incompatibility is what moved the output license to BY-SA, above.

The legal question is genuinely open and both readings are recorded so neither gets lost. **The response no longer depends on which is right**, which is the point of settling it this way:

- **It may be descriptive rather than a grant.** In the FGDC metadata vocabulary the page uses, *Access* constraints and *Use* constraints are separate fields, and USGS put the licences under *Access* while its *Use* constraint says only "Please cite authors". Read that way, the line names the provenance of the two inputs and the blend itself — a US Geological Survey work — carries no share-alike.
- **It may be a real term on the HRSC half.** HRSC contributes 44% of the blend's coverage; if that fraction is BY-SA, the derived tiles are a derivative of BY-SA material regardless of which metadata field records it.

**This supersedes MARS.md's earlier conclusion** that the share-alike trap applies only to ESA's published *pictures* and that the archive route imposes nothing. That conclusion was reached from ESA's own terms and is correct about ESA; what it did not account for is the USGS blend's own metadata making the same claim about the data.

**The resolution is to assume the strict reading and license the output share-alike**, which is correct whichever reading is right, and which needs no legal determination to act on. Three consequences worth stating rather than re-deriving:

- **The output is CC BY-SA 4.0, not 3.0 IGO**, and that is permitted by the input license's own text rather than by analogy: BY-SA 3.0 IGO § 4(b) allows an Adaptation to be distributed under *"a later version of this License with the same License Elements as this License"*. Verified against the legal code, not recalled.
- **Its § 4(c) wants "a credit identifying the use of the Work in the Adaptation"**, which the Fergason citation below already carries. Attribution was never the hard half; share-alike was.
- **The alternative was to change the source rather than the license, and it was declined on the merits.** MOLA MEGDR is CC0 at 463 m/px against a z6 cut of 651 m/px, so swapping it would remove the question outright at no visible cost today — but only today. The trade bites from z7 (326 m/px) onward, where MEGDR is upsampled and the blend is not, and at z8 (163 m/px) it is a 2.8x upsample. The swap therefore forecloses the finer cut, and the blend's detail is wanted more than the permissive license.

The About page continues to state the publisher's own words for the source (`MOLA CC0 · HRSC CC BY-SA 3.0 IGO`) rather than our reading of them — quoting cannot be wrong where a paraphrase would assert something the source contradicts.

### Required / requested attribution strings

- **Copernicus DEM GLO-30** — for adapted/modified data (our case — Article 6(b) of the licence), the exact required notice is: *"produced using Copernicus WorldDEM-30 © DLR e.V. 2010-2014 and © Airbus Defence and Space GmbH 2014-2018 provided under COPERNICUS by the European Union and ESA; all rights reserved"*. The About page (or its legal notice) must also carry the Article 6(c) liability sentence: *"The organisations in charge of the Copernicus programme by law or by delegation do not incur any liability for any use of the Copernicus WorldDEM-30"* — and must not imply official endorsement by ESA/Copernicus (6(d)).
- **ESA WorldCover** — "© ESA WorldCover project 2021 / Contains modified Copernicus Sentinel data (2021) processed by ESA WorldCover consortium."
- **NSIDC-0791** — "Snow persistence from the MODIS/Terra Global Annual Snow-Cover Climatology (NSIDC-0791), NASA NSIDC DAAC (doi:10.5067/9R1AM6NNZLTV)." NASA/US-government data is public domain; the citation is a courtesy. Accessed via NASA Earthdata (earthaccess).
- **RGI 7.0** — "RGI 7.0 Consortium (2023), Randolph Glacier Inventory 7.0 (doi:10.5067/F6JMOVY5NAVZ), CC-BY 4.0." The regional shapefiles were fetched from UNESCO's open IHP-WINS re-host of the RGI/NSIDC files (the NSIDC data pool needs interactive-OAuth; IHP-WINS serves the identical data openly).
- **GEBCO** — "Reproduced from the GEBCO_2026 Grid, GEBCO Compilation Group (2026)."
- **GLOBathy** — "Lake depth from GLOBathy: Khazaei, B., Read, L.K., Casali, M., Sampson, K.M., Yates, D.N. (2022), *GLOBathy, the Global Lakes Bathymetry Dataset*, Scientific Data 9, 36 (doi:10.1038/s41597-022-01132-9)." **CC0**, so no attribution is legally required — this is an academic-citation courtesy, and we chose it deliberately: the tint-only architecture avoided a HydroLAKES join, which is what kept the whole depth layer CC0. The About page must also carry the *epistemics* (the depth shape is a modelled cone, surveyed scale for only 647 of 83,357 lakes) — that is an honesty obligation, not a licensing one.
- **OSI SAF** — "Sea-ice climatology derived from the OSI SAF Global sea ice concentration climate data record 1978–2020 (v3.0, 2022), OSI-450-a, EUMETSAT Ocean and Sea Ice Satellite Application Facility (doi:10.15770/EUM_SAF_OSI_0013)." CC-BY 4.0. The About page should note the reference period actually used (1991–2020 annual ice frequency).
- **Natural Earth** — public domain; a courtesy credit to naturalearthdata.com.
- **MOLA / HRSC blend** — the publisher's own recommended citation, quoted from its product page: *"Fergason, R. L, Hare, T. M., & Laura, J. (2018). HRSC and MOLA Blended Digital Elevation Model at 200m v2. Astrogeology PDS Annex, U.S. Geological Survey."* Its stated use constraint is "Please cite authors", so unlike the public-domain Earth sources this citation is **requested by the publisher rather than a pure courtesy** — carry it. It does double duty: on the strict reading of the share-alike finding above, this is also the credit BY-SA 3.0 IGO § 4(c) asks an adaptation to carry.

### Licensing posture

GEBCO (public domain), Natural Earth (public domain), NSIDC-0791 / MODIS (NASA, public domain), ESA WorldCover (CC-BY 4.0), RGI 7.0 (CC-BY 4.0), and OSI SAF OSI-450-a (CC-BY 4.0) all unambiguously permit derivative works, public display, and redistribution with attribution. Copernicus GLO-30 is the only source under a bespoke licence rather than PD/CC, and its terms have been **verified against the primary licence text** ([License-COPDEM-30.pdf](https://documentation.dataspace.copernicus.eu/APIs/SentinelHub/Data/DEM/resources/license/License-COPDEM-30.pdf)): Article 4 grants **reproduction, distribution, communication to the public, and adaptation/combination**, worldwide, without time limit or purpose restriction — commercial use of derived products included; Article 9 confirms the IPR in work produced *using* the DEM (our renders) belongs to us. **Those two articles are what make a share-alike output license possible on Earth at all**, and the check is not optional: BY-SA promises downstream recipients the right to redistribute and adapt commercially, and a promise like that can only be made where the inputs already permit it. Every other Earth source is PD, CC0 or CC-BY, all of which flow into BY-SA. The obligations are the two exact notices and the liability sentence above, plus no implied endorsement — and they now travel further than they used to, because BY-SA invites the redistribution that NC discouraged. The higher-resolution WorldDEM-10 is expressly outside this licence — this project uses only GLO-30.

## Tools & technique

- **Rendering** — [Blender](https://www.blender.org) (Cycles renderer, OptiX backend, OpenImageDenoise).
- **Geoprocessing** — [GDAL](https://gdal.org), [rasterio](https://rasterio.readthedocs.io), [NumPy](https://numpy.org).
- **Web** — [Astro](https://astro.build) (static site), [MapLibre GL JS](https://maplibre.org) (globe projection), [PMTiles](https://github.com/protomaps/PMTiles) (Protomaps).
- **Technique** — shaded relief in Blender after Daniel Huffman's canonical method; aesthetic reference: Frank Ramspott, "3D Render Topographic Map — Neutral."

## Made with AI

This project was built in collaboration with AI. The pipeline code, documentation, and Blender rendering setup were developed in a pair-programming workflow with Anthropic's Claude (via Claude Code). Data-source selection, design decisions, and final review are the author's.
