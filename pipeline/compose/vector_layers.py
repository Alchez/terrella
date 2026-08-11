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

import itertools
from pathlib import Path
from typing import Any

#: MVT tile-space units. Not a knob either body has had reason to move, but it is part of the
#: conversion's contract, so it is named rather than spelled into a command string.
EXTENT = 4096

#: How near ±180 an edge must sit for `seam_closures` to consider it at all. GENEROUS ON PURPOSE,
#: because it only decides what gets ASKED the twin question and never what gets dropped — a wide
#: band costs a comparison and a narrow one silently exempts a publisher who did not snap its cut to
#: the meridian. USGS's Arcadia Planitia closes at 179.711 and 180.091, which is what sets the floor.
SEAM_BAND_DEGREES = 1.0

#: How closely two candidate edges' latitude spans must agree to be called the same cut seen from
#: both sides. Tight, because it is a COINCIDENCE test rather than a magnitude one: a real boundary
#: is not mirrored across the meridian at both ends to within a twentieth of a degree by accident.
SEAM_TWIN_LATITUDE_EPSILON = 0.05


def seam_recipe() -> dict[str, Any]:
    """The seam drop's settings, for a body's recipe sidecar to carry.

    IT IS SHARED CODE MAKING A CHOICE, WHICH IS THE ONE THING A PER-BODY RECIPE CANNOT NOTICE. The
    outlines are gated on their SOURCE's mtime, and a source does not move when this module's
    constants do — so without the sidecar, retuning either knob leaves every archive on disk exactly
    as it was, reading fresh. Returned as a dict rather than spelled into each recipe so a third knob
    reaches both bodies by existing.
    """
    return {
        "seam_band_degrees": SEAM_BAND_DEGREES,
        "seam_twin_latitude_epsilon": SEAM_TWIN_LATITUDE_EPSILON,
    }


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


def seam_closures(rings: list[Any]) -> set[tuple[int, int]]:
    """`(ring index, edge index)` for every edge that is a polygon's cut at ±180 rather than boundary.

    A FEATURE THAT STRADDLES THE ANTIMERIDIAN ARRIVES AS TWO POLYGONS, AND EACH HALF HAS TO CLOSE
    ITSELF ALONG THE CUT. Stroked, those two closures draw one straight line down the meridian
    through the middle of the feature — Arcadia Planitia's runs 20.8° of latitude. It is the same
    phenomenon `outlines_from` already exists for, one stage earlier: there the cut is a tile
    boundary, here it is the fold, and neither is anything a reader should see.

    THE TEST IS A TWIN, NOT A THRESHOLD, and that is the whole difficulty. Proximity to ±180 cannot
    decide it — Fiji contributes 388 edges inside the band and every one is real coast — and neither
    can length, because **Terra Cimmeria's published eastern boundary genuinely follows the meridian
    for 57°**, abutting Terra Sirenum's own 45° western boundary on the other side. Those two are
    single unsplit polygons and their long meridian edges are the source's real answer. What a cut
    has and a boundary does not is a counterpart: the same edge, in the same feature, on the other
    side of the seam, spanning the same latitudes because both halves were closed along one line.

    IT MUST ALSO SURVIVE A PUBLISHER THAT DID NOT SNAP ITS OWN CUT. `-wrapdateline` lands both ends
    on exactly ±180, but the USGS gazetteer ships Arcadia pre-split and closes it at 179.711 and
    180.091 — so an exact-meridian test would fix Earth completely, look correct, and leave the
    worst Mars case untouched. The band is wide and the coincidence test does the discriminating.

    THE KNOWN FALSE POSITIVE is a feature with lobes on both sides whose seam-adjacent edges span
    the same latitudes by chance, which is indistinguishable from a cut and is dropped. It has a
    test; it appears in neither catalogue. Winding cannot rescue it — publishers do not guarantee
    ring orientation — and every threshold that would is one that deletes Terra Cimmeria.
    """
    candidates: list[tuple[int, int, bool, float, float]] = []
    for ring_index, ring in enumerate(rings):
        for edge_index, (start, end) in enumerate(itertools.pairwise(ring)):
            if min(abs(start[0]), abs(end[0])) < 180.0 - SEAM_BAND_DEGREES:
                continue
            if start[0] * end[0] <= 0:  # an edge ACROSS the meridian is not one along it
                continue
            low, high = sorted((start[1], end[1]))
            candidates.append((ring_index, edge_index, start[0] > 0, low, high))

    closures: set[tuple[int, int]] = set()
    for ring_index, edge_index, east, low, high in candidates:
        # A degenerate span would twin with any other degenerate span at the same latitude, which is
        # every pair of short opposite-side edges rather than a cut.
        if high - low <= SEAM_TWIN_LATITUDE_EPSILON:
            continue
        if any(other_east is not east
               and abs(low - other_low) < SEAM_TWIN_LATITUDE_EPSILON
               and abs(high - other_high) < SEAM_TWIN_LATITUDE_EPSILON
               for _, _, other_east, other_low, other_high in candidates):
            closures.add((ring_index, edge_index))
    return closures


def arcs_without(ring: list[Any], dropped: set[int]) -> list[list[Any]]:
    """`ring` as the open arcs left when `dropped` edge indices are removed.

    A ring is closed, so removing an edge in the MIDDLE of the coordinate list has to rejoin the
    tail to the head rather than leave two arcs that meet at a point nothing draws. Walking from
    just past a cut is what makes that fall out; without it the seam looks fixed and the feature's
    outline silently gains a gap at wherever the publisher happened to start the ring.
    """
    edge_count = len(ring) - 1
    if not dropped or edge_count < 1:
        return [ring]
    order = list(range(edge_count))
    if ring[0] == ring[-1] and edge_count > 1:
        resume = (max(dropped) + 1) % edge_count
        order = [(resume + step) % edge_count for step in range(edge_count)]
    arcs: list[list[Any]] = []
    current: list[Any] = []
    for index in order:
        if index in dropped:
            if len(current) > 1:
                arcs.append(current)
            current = []
            continue
        if not current:
            current = [ring[index]]
        current.append(ring[index + 1])
    if len(current) > 1:
        arcs.append(current)
    return arcs


def outlines_from(collection: dict[str, Any], keys: tuple[str, ...]) -> dict[str, Any]:
    """Polygon rings re-expressed as boundary LINES — outer edges and inner holes alike.

    WHY A LINE LAYER RATHER THAN STROKING THE POLYGONS. Clipping a line trims it; clipping a
    polygon closes the ring along the cut, and a `line` layer strokes that phantom edge — the stray
    gold meridian this project already fixed once at runtime. The fix cannot be made in the browser
    for a vector source, so it is made here.

    The antimeridian is the same cut made earlier and by someone else, so `seam_closures` drops it
    here too. A feature whose every ring is one closure would emit no line at all and is skipped,
    which is why the emptiness test moved below the drop.
    """
    features: list[dict[str, Any]] = []
    for feature in collection["features"]:
        properties = carried(feature["properties"], keys)
        if properties is None or not feature.get("geometry"):
            continue
        rings = [ring for part in polygon_parts_of(feature["geometry"]) for ring in part]
        closures = seam_closures(rings)
        lines = [arc
                 for ring_index, ring in enumerate(rings)
                 for arc in arcs_without(
                     ring, {edge for cut_ring, edge in closures if cut_ring == ring_index})]
        if not lines:
            continue
        features.append({
            "type": "Feature",
            "properties": properties,
            "geometry": {"type": "MultiLineString", "coordinates": lines},
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
