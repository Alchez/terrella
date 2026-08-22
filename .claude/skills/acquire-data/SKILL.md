---
name: acquire-data
description: Acquiring or refetching one of Terrella's source datasets. Load when downloading, re-downloading or adding a DEM, bathymetry, cryosphere or boundary source, or when a download fails with what looks like an auth error. Carries the access gotchas that are not in the licence table and that each look like a bug in our code.
---

# Acquiring a source

`ATTRIBUTIONS.md` is the authority on which datasets exist, what each does in the pipeline, and what
its licence requires. This skill carries only the operational half: the things that go wrong on the
way to having the bytes, none of which belong in a licence table.

`pipeline/acquire/*` is the only writer of `data/raw`. Downloads need the maintainer's explicit
permission before they start.

## Copernicus DEM GLO-30 has holes, and a hole fuses silently as ocean

The AWS **Public DGED 2021** edition withholds tiles over some regions. A missing tile does not
fail: it fuses as ocean, so the defect is a plausible sea where land should be, discovered by eye
rather than by an error.

Fill the gaps from OpenTopography `2023_1`, which is a keyless S3 bucket, so `--no-sign-request`.

## The cryosphere sources each fail in a way that reads as an auth bug

- **An Earthdata bearer token authenticates CMR granule downloads but NOT the NSIDC file pool.** The same credential that just worked will 401 against the pool, which reads as an expired token rather than as the wrong service.
- **RGI 7.0 is not granule-searchable at all**, so no amount of CMR querying finds it. Take it from the UNESCO IHP-WINS CKAN mirror.
- **OSI SAF OSI-450-a was chosen over the NSIDC sea-ice CDR purely on access**, being anonymous over met.no THREDDS with no token churn. It is reduced to a 1991 to 2020 ice-frequency climatology in `look/seaice.py`.

## Licence terms come from the product, not from the mission

Read the constraint fields on the specific product being downloaded. Two Mars sources in this
project state different terms from what their parent mission is usually cited as, and the
share-alike half of the blended DEM's licence is what makes the whole site's output CC BY-SA 4.0.
Where a source publishes a machine-readable constraint field, re-read it on every acquisition so a
republished archive with changed terms stops the pipeline rather than flowing through unnoticed.
