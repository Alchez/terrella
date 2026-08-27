"""Where every external dataset sits inside the raw store, and what puts it there.

ONE HOME FOR A LAYOUT THAT WAS SPELLED AT ITS READERS. Thirty-three module-level constants named
twenty-two locations between them, so eight were spelled more than once: `glo30/tileList.txt` in
four modules, `gebco_2026_global.vrt` in three. Nothing went red when one moved, because the
acquirer that writes a file and the stages that read it each held their own copy of where it was.

AND EVERY ONE OF THEM FROZE THE STORE, which is the rule `paths.py` states: a module-level
`SOMEWHERE = DATA / "x"` resolves once, at import, so redirecting `MAPS_DATA` afterwards moves some
of a module's paths and not others, with no error in it. `naturalearth.DIR` was the sharpest case,
its docstring promising that `MAPS_DATA` relocates the vectors while being the line that stopped it.
These resolve on every call, so both defects close together.

FUNCTIONS RATHER THAN A NAME-KEYED LOOKUP, which is a departure from `bodies.work_dir(body, stage)`
and `naturalearth.layer(name)` for a stated reason: each of those keys drives a CONVENTION the
function applies, and there is none here — every entry below is an arbitrary path, so a key would
parameterise nothing and buy only a vocabulary to memorise. A fresh clone runs the type checkers
and both suites and none of the stages that read these files, so a mistyped string key would pass
every check a contributor can run and fail in a stage they cannot. A mistyped function name does not.

EACH LINE SAYS WHAT WRITES IT AND NOTHING ELSE. What a dataset IS, what it does in the pipeline,
its source and its licence are `ATTRIBUTIONS.md`'s, which carries all four as a table; restating any
of it here would be a second copy. Two datasets have no acquirer in `pipeline/acquire/` and say so,
because a missing file reads as a broken script until you know it was always a manual download.

`work/` is not here. That tree is `bodies.work_dir`'s, and derived outputs belong to whatever stage
produces them.
"""

from pathlib import Path

from pipeline import paths


def _raw(*parts: str) -> Path:
    """The raw store's own root, joined at call time so a redirected `MAPS_DATA` reaches it."""
    return paths.DATA.joinpath("raw", *parts)


def addrock() -> Path:
    """SCAR Antarctic rock outcrop, written by `acquire/download_add_rock.py`."""
    return _raw("addrock")


def addrock_gpkg() -> Path:
    """The reprojected outcrop polygons, written by `acquire/download_add_rock.py`."""
    return _raw("addrock", "add_rock_3857.gpkg")


def cop30_void() -> Path:
    """Copernicus DEM void masks, written by `acquire/download_cop30_void.py`."""
    return _raw("cop30_void")


def gebco() -> Path:
    """GEBCO bathymetry tiles, written by `acquire/download_gebco.py`."""
    return _raw("gebco")


def gebco_vrt() -> Path:
    """The GEBCO global mosaic, built by `acquire/download_gebco.py`."""
    return _raw("gebco", "gebco_2026_global.vrt")


def glo30() -> Path:
    """Copernicus DEM GLO-30 tiles, written by `acquire/download_glo30.py`."""
    return _raw("glo30")


def glo30_tile_list() -> Path:
    """The GLO-30 tile manifest, written by `acquire/download_glo30.py`."""
    return _raw("glo30", "tileList.txt")


def globathy() -> Path:
    """GLOBathy lake bathymetry, written by `acquire/download_globathy.py`."""
    return _raw("globathy")


def globathy_zip() -> Path:
    """The per-lake raster archive, written by `acquire/download_globathy.py`.

    Read by `acquire/extract_globathy.py`, which unpacks it into `work/`.
    """
    return _raw("globathy", "Bathymetry_Rasters.zip")


def mars() -> Path:
    """Mars rasters, written by both `acquire/download_mars_dem.py` and `download_viking_mosaic.py`."""
    return _raw("mars")


def mars_nomenclature() -> Path:
    """IAU Mars feature names, written by `acquire/download_nomenclature.py`."""
    return _raw("mars", "nomenclature")


def mars_sim3292() -> Path:
    """The USGS SIM 3292 geologic map, written by `acquire/download_sim3292.py`."""
    return _raw("mars", "sim3292")


def naturalearth() -> Path:
    """Natural Earth vectors, written by `acquire/download_naturalearth.sh`.

    `naturalearth.layer` is what turns a layer NAME into a shapefile beneath this, since that
    doubling convention is its own and no call site should spell it.
    """
    return _raw("naturalearth")


def rgi() -> Path:
    """Randolph Glacier Inventory 7.0, written by `acquire/download_rgi.py`."""
    return _raw("rgi")


def rgi_gpkg() -> Path:
    """All nineteen RGI regions merged and reprojected, written by `acquire/download_rgi.py`."""
    return _raw("rgi", "rgi7_g_3857.gpkg")


def seaice() -> Path:
    """Sea-ice concentration source data, written by `acquire/download_seaice.py`."""
    return _raw("seaice")


def seaice_frequency() -> Path:
    """The 1991-2020 sea-ice frequency composite, built by `acquire/download_seaice.py`."""
    return _raw("seaice", "seaice_frequency_1991-2020_4326.tif")


def seaice_monthly() -> Path:
    """The monthly grids the composite is built from, written by `acquire/download_seaice.py`."""
    return _raw("seaice", "monthly")


def snow_persistence() -> Path:
    """NSIDC-0791 snow persistence. NO ACQUIRER: download it by hand, source in ATTRIBUTIONS.md."""
    return _raw("snow", "NSIDC-0791_SP_0.01Deg_WY2001-2023_V01.0.nc")


def worldcover() -> Path:
    """ESA WorldCover 2021 v200. NO ACQUIRER: download it by hand, source in ATTRIBUTIONS.md."""
    return _raw("worldcover")
