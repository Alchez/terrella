---
name: acquire-data
description: Acquiring or refetching one of Terrella's source datasets. Load when downloading, re-downloading or adding a DEM, bathymetry, cryosphere or boundary source, or when a download fails with what looks like an auth error. Carries the access gotchas that are not in the licence table and that each look like a bug in our code.
---

# Acquiring a source

`ATTRIBUTIONS.md` is the authority on which datasets exist, what each does in the pipeline, and what its licence requires. This skill carries only the operational half: the things that go wrong on the way to having the bytes, none of which belong in a licence table.

`pipeline/acquire/**` is the only writer of `data/raw`, held there by `test_fetch.test_only_an_acquirer_reaches_a_server`. Downloads need the maintainer's explicit permission before they start.

Two stages download as they run, each fetching the WorldCover tiles it reads: `fuse/build_void_wbm.py`, and `acquire/earth/extract_gwl.py`, whose first run fetches the tiles under GWL_FCS30's saline class, INVENTORY's `worldcover/` row. Ask before running either on a store without them.

## Where a new source's module goes

- **If it reaches a server it goes under its body**, `pipeline/acquire/earth/` or `acquire/mars/`, since no source serves two planets. This is the only package in `pipeline/` grouped that way and `docs/pipeline-layout.md` says why it does not generalise. A tool rather than a dataset stays above the bodies, as `install_geotools.sh` does.
- **Several readers is not a reason to move it out**, which is the instinct to distrust here: `download_glo30.py` is read by two stages for its naming rules and still belongs under `earth/`. What a second reader means is that the fact needs one owner, not that the owner sits higher up.
- **A source too large to fetch whole takes a required `--extent`** and stays an acquirer. GLO-30 and WorldCover both do; neither has a shape that fetches a planet by default.
- **The top level of `pipeline/` is for the READ side of a source nothing here fetches**, which is `naturalearth.py` alone: a path helper and the layer vocabulary, reaching no server. Its own docstring states that rule.

## Copernicus DEM GLO-30 has holes, and a hole fuses silently as ocean

The AWS **Public DGED 2021** edition withholds tiles over some regions. A missing tile does not fail: it fuses as ocean, so the defect is a plausible sea where land should be, discovered by eye rather than by an error.

Fill the gaps from OpenTopography's keyless `2023_1` edition: `download_cop30_void` fetches exactly the withheld set, and `fuse/build_void_wbm.py` synthesises the water mask OpenTopography does not serve from WorldCover class 80. Without that mask the fuse reads the gap as ocean all the same.

## The cryosphere sources each fail in a way that reads as an auth bug

- **An Earthdata bearer token authenticates CMR granule downloads but NOT the NSIDC file pool.** The same credential that just worked will 401 against the pool, which reads as an expired token rather than as the wrong service.
- **RGI 7.0 is not granule-searchable at all**, so no amount of CMR querying finds it. Take it from the UNESCO IHP-WINS CKAN mirror.
- **OSI SAF OSI-450-a was chosen over the NSIDC sea-ice CDR purely on access**, being anonymous over met.no THREDDS with no token churn. It is reduced to a 1991 to 2020 ice-frequency climatology in `look/seaice.py`.

## A tiled source's tiles may not share one grid

- **Check that a tile's cell count times its resolution equals the span its name gives.** GWL_FCS30's 5° tiles are 18,553 cells of 0.000269494585°, a quarter cell short, so neighbouring tiles sit on grids a quarter cell apart.
- **`gdalbuildvrt` over such tiles moves each one up to half a cell and says nothing**, placing it at a fractional offset and filling by nearest. Where position matters, read each tile on its own, as `salt.saline_share` does.

## Licence terms come from the product, not from the mission

Read the constraint fields on the specific product being downloaded. Two Mars sources in this project state different terms from what their parent mission is usually cited as, and the share-alike half of the blended DEM's licence is what makes the whole site's output CC BY-SA 4.0. Where a source publishes a machine-readable constraint field, re-read it on every acquisition so a republished archive with changed terms stops the pipeline rather than flowing through unnoticed.
