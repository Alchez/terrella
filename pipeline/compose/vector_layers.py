"""The vector-tile machinery both bodies' pyramids need, owned once.

WHAT LIVES HERE IS WHAT DRIFTS SILENTLY IF IT DOES NOT. Earth cuts countries and Mars cuts named
features; the two differ in their sources, their property sets and their zoom ceilings, but the
geometry walk, the staging trick and the conversion's option set are the same code answering the
same questions. Copied, a fix to either copy leaves the other wrong and nothing goes red — the
trigger this repo uses for deciding a thing needs an owner.

WHAT DELIBERATELY DOES NOT LIVE HERE is anything a body ASSERTS about its own output: the recipe
sidecar, the freshness rule, the simplification constants and their justifications. Those read as
shared and are not — a tolerance is argued against the raster of one particular body, and a recipe
is a producer's claim about what it emitted. Hoisting them would make one body's measurement look
like a law.
"""

from pathlib import Path
from typing import Any

#: MVT tile-space units. Not a knob either body has had reason to move, but it is part of the
#: conversion's contract, so it is named rather than spelled into a command string.
EXTENT = 4096


def polygon_parts_of(geometry: dict[str, Any]) -> list[Any]:
    """Every polygon PART of a geometry, whatever container the publisher wrapped it in.

    The GeometryCollection branch is not defensive coding. Natural Earth ships **Greenland** as a
    collection of 129 polygons plus one stray LineString; the two inline copies this replaced both
    returned nothing for it, so an in-scope country had a fill wash and a click but no hover
    outline and no hit targets. `-nlt MULTIPOLYGON` does not fix it upstream — GDAL keeps the
    collection precisely because the LineString cannot join a MultiPolygon.

    Mars's gazetteer ships no collections today, which is exactly why the branch stays owned here
    rather than being trimmed to what the newer caller happens to need: the case is a PUBLISHER's
    habit, and the second publisher has not promised anything.
    """
    kind = geometry["type"]
    if kind == "MultiPolygon":
        return list(geometry["coordinates"])
    if kind == "Polygon":
        return [geometry["coordinates"]]
    if kind == "GeometryCollection":
        return [part for member in geometry["geometries"] for part in polygon_parts_of(member)]
    return []


def carried(properties: dict[str, Any], keys: tuple[str, ...]) -> dict[str, Any] | None:
    """The subset of `properties` a derived layer carries, or None if the first key is unusable.

    THE FIRST KEY IS THE IDENTITY and the rest are payload — a feature with no name cannot be
    hovered as one thing, labelled, or joined to anything, so it is dropped rather than carried
    anonymously. The remaining keys are copied when present and simply absent when not, because a
    missing `origin` is a thinner card and a missing name is a broken layer.
    """
    identity = properties.get(keys[0])
    if not isinstance(identity, str) or not identity:
        return None
    return {key: properties[key] for key in keys if properties.get(key) is not None}


def outlines_from(collection: dict[str, Any], keys: tuple[str, ...]) -> dict[str, Any]:
    """Polygon rings re-expressed as boundary LINES — outer edges and inner holes alike.

    WHY A LINE LAYER RATHER THAN STROKING THE POLYGONS. Clipping a line trims it; clipping a
    polygon closes the ring along the cut, and a `line` layer strokes that phantom edge — the stray
    gold meridian this project already fixed once at runtime. The fix cannot be made in the browser
    for a vector source, so it is made here.
    """
    features: list[dict[str, Any]] = []
    for feature in collection["features"]:
        properties = carried(feature["properties"], keys)
        if properties is None or not feature.get("geometry"):
            continue
        rings = [ring for part in polygon_parts_of(feature["geometry"]) for ring in part]
        if not rings:
            continue
        features.append({
            "type": "Feature",
            "properties": properties,
            "geometry": {"type": "MultiLineString", "coordinates": rings},
        })
    return {"type": "FeatureCollection", "features": features}


def stage_command(source: Path, destination: Path, layer: str, update: bool) -> list[str]:
    """One layer into a staging GeoPackage.

    A GPKG intermediate exists because the PMTiles driver **cannot append a layer** to an archive
    it already wrote — `-update -append` fails with "cannot be created by the output driver". Every
    layer therefore has to reach `ogr2ogr` as one multi-layer dataset.
    """
    return [
        "ogr2ogr", "-f", "GPKG",
        *(["-update"] if update else []),
        str(destination), str(source),
        "-nln", layer,
    ]


def pmtiles_command(
    source: Path,
    destination: Path,
    *,
    name: str,
    min_zoom: int,
    max_zoom: int,
    buffer: int,
    simplification: float,
    simplification_max_zoom: float,
) -> list[str]:
    """The staged dataset to a PMTiles pyramid. Argument order is [options] DESTINATION SOURCE.

    THAT ORDER READS BACKWARDS AND HAS BEEN GOT WRONG BEFORE, which is most of why this is one
    function rather than a string in each caller.

    GDAL SIMPLIFIES NOTHING BY DEFAULT, and that is not a safe default for either body: on Earth's
    countries it measured a 4.3x weight regression against a tolerance-3 tiler, invisible unless the
    tiles are weighed. Both knobs are therefore required arguments with no defaults — a caller that
    forgets one fails to construct rather than quietly shipping the unsimplified cut.
    """
    return [
        "ogr2ogr", "-f", "PMTiles",
        str(destination), str(source),
        "-dsco", f"MINZOOM={min_zoom}",
        "-dsco", f"MAXZOOM={max_zoom}",
        "-dsco", f"NAME={name}",
        "-dsco", f"BUFFER={buffer}",
        "-dsco", f"EXTENT={EXTENT}",
        "-dsco", f"SIMPLIFICATION={simplification}",
        "-dsco", f"SIMPLIFICATION_MAX_ZOOM={simplification_max_zoom}",
    ]
