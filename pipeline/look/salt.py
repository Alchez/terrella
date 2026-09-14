"""Salt flats: the ground two instruments misread, painted as salt on any grid.

NSIDC-0791 reads bright salt crust as persistent snow, and the elevation data's water body mask reads
it as lake. The outlines are Natural Earth's playas, which calls every one a dry lake bed and says
nothing of salt. On a grid the salt is:

  - each outline on its level floor, within `FLOOR_TOLERANCE_M` of the outline's median height, so a
    hill or a slope inside a generalised outline stays land;
  - every lake body touching that salt which lies mostly inside an outline, whole, the water mask
    drawing a flat past its outline; a body lying mostly outside is a lake the outline brushes, and
    none of it is salt;
  - the white connected to an outline on NSIDC-0791's own grid, at the white's own strength.

Growing an outline across the level ground it touches looks like the cure for its roughness, and it
floods the plains around a flat at the flat's own height.

Both tiers read one packed Byte raster: the planet's, baked once by the warp stage because a lake body
and a white component cross block edges, and a hero's, landed on the hero's own grid.
"""

from pathlib import Path

import numpy as np
import rasterio
import shapefile
from affine import Affine
from rasterio import features, windows
from rasterio.transform import from_bounds
from rasterio.warp import Resampling, reproject, transform_geom
from scipy import ndimage

from pipeline import naturalearth
from pipeline.look import lake_depth, snow
from pipeline.raster_io import GTIFF_CREATE

#: Natural Earth's layer of dry lake beds.
LAYER = "ne_10m_playas"

#: How far from an outline's median height a pixel still stands on its floor.
FLOOR_TOLERANCE_M = 10.0
#: Samples per pixel edge when an outline's coverage is measured, so its edge is antialiased.
COVERAGE_SUPERSAMPLE = 4
#: NSIDC-0791 cells added around the connected white, so its softened edge is taken with it.
WHITE_GROW_CELLS = 1
#: The share of a lake body an outline must hold for the whole body to be salt.
LAKE_INSIDE_FRACTION = 0.5

#: The packed raster: the low seven bits carry the full-strength share in `FULL_LEVELS` steps, the
#: high bit the gate on the white.
FULL_LEVELS = 127
GATE_BIT = 128

#: Degrees of NSIDC-0791 read around a box before its white is followed, doubled until no kept
#: component meets the edge.
WHITE_MARGIN_DEG = 1.0
#: Pixels around an outline's box on the planet grid, doubled until nothing kept meets the edge.
PLANET_MARGIN_PX = 256

EIGHT = np.ones((3, 3), bool)


def outlines() -> list[dict]:
    """Every outline in the layer, as a GeoJSON geometry in lon/lat."""
    reader = shapefile.Reader(str(naturalearth.layer(LAYER)))
    try:
        return [dict(shape.__geo_interface__) for shape in reader.shapes() if shape is not None]
    finally:
        reader.close()


def _components(mask: np.ndarray) -> tuple[np.ndarray, int]:
    """The 8-connected components of `mask`, numbered from 1, and how many there are."""
    labels, count = ndimage.label(mask, structure=EIGHT)  # pyright: ignore[reportGeneralTypeIssues]
    return np.asarray(labels, dtype=np.int64), int(count)


def _burn(shapes: list[tuple[dict, int]], shape: tuple[int, int], transform: Affine) -> np.ndarray:
    return np.asarray(features.rasterize(shapes, out_shape=shape, transform=transform, fill=0,
                                         dtype="uint8"))


def white_cells(alpha: np.ndarray, inside: np.ndarray) -> np.ndarray:
    """The cells whose white connects to an outline: 8-connected components of `alpha` above zero
    that touch `inside`, grown by `WHITE_GROW_CELLS`."""
    labels, _count = _components(alpha > 0)
    touching = np.unique(labels[inside & (labels > 0)])
    kept = np.isin(labels, touching[touching > 0])
    # scipy reads zero iterations as "until nothing changes", which would flood the whole grid.
    if not WHITE_GROW_CELLS:
        return kept
    return ndimage.binary_dilation(kept, structure=EIGHT, iterations=WHITE_GROW_CELLS)


def _meets_edge(mask: np.ndarray) -> bool:
    return bool(mask[0].any() or mask[-1].any() or mask[:, 0].any() or mask[:, -1].any())


def connected_white(bounds: tuple[float, float, float, float],
                    geometries: list[dict]) -> tuple[np.ndarray, Affine]:
    """`white_cells` on NSIDC-0791's own grid around a lon/lat box, and that grid's transform.

    `geometries` are the outlines in lon/lat. The tiles' own ramp decides which cells are white.
    """
    west, south, east, north = bounds
    margin = WHITE_MARGIN_DEG
    with rasterio.open(f'NETCDF:"{snow.persistence_nc()}":{snow.SP_VAR}') as source:
        whole = windows.Window(0, 0, source.width, source.height)  # pyright: ignore[reportCallIssue]
        while True:
            window = windows.from_bounds(west - margin, south - margin, east + margin, north + margin,
                                         source.transform).round_offsets().round_lengths()
            window = window.intersection(whole)
            packed = source.read(1, window=window)
            transform = source.window_transform(window)
            latitude = transform.f + (np.arange(packed.shape[0]) + 0.5) * transform.e
            alpha = snow.snow_alpha(snow.unpack_persistence(packed), latitude)
            inside = _burn([(geometry, 1) for geometry in geometries], packed.shape,
                           transform).astype(bool)
            gate = white_cells(alpha, inside)
            if not _meets_edge(gate) or margin >= 16 * WHITE_MARGIN_DEG:
                return gate, transform
            margin *= 2


def coverage(geometry: dict, transform: Affine, shape: tuple[int, int]) -> np.ndarray:
    """The fraction of each pixel the polygon covers, sampled `COVERAGE_SUPERSAMPLE` times finer
    inside its bounding box. `geometry` is in the grid's own coordinates."""
    cover = np.zeros(shape)
    box = windows.from_bounds(*features.bounds(geometry), transform=transform)
    col0, row0 = max(0, int(np.floor(box.col_off))), max(0, int(np.floor(box.row_off)))
    col1 = min(shape[1], int(np.ceil(box.col_off + box.width)))
    row1 = min(shape[0], int(np.ceil(box.row_off + box.height)))
    if col0 >= col1 or row0 >= row1:
        return cover
    fine = transform * Affine.translation(col0, row0) * Affine.scale(1.0 / COVERAGE_SUPERSAMPLE)
    rows, cols = row1 - row0, col1 - col0
    burnt = _burn([(geometry, 1)], (rows * COVERAGE_SUPERSAMPLE, cols * COVERAGE_SUPERSAMPLE), fine)
    cover[row0:row1, col0:col1] = burnt.reshape(rows, COVERAGE_SUPERSAMPLE, cols,
                                                COVERAGE_SUPERSAMPLE).mean(axis=(1, 3))
    return cover


def field(heightfield: np.ndarray, lake: np.ndarray, transform: Affine, geometries: list[dict],
          gate: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """The salt on one grid: its full-strength share, 0 to 1, and the gate the white is salt under.

    `geometries` are the outlines in the grid's own coordinates, `lake` the water mask's lake class
    and `gate` the connected white landed on the grid.
    """
    full = np.zeros(heightfield.shape)
    inside = np.zeros(heightfield.shape, bool)
    for geometry in geometries:
        cover = coverage(geometry, transform, heightfield.shape)
        core = cover >= 0.5
        if not core.any():
            continue
        inside |= core
        floor = float(np.median(heightfield[core]))
        full = np.maximum(full, cover * (np.abs(heightfield - floor) <= FLOOR_TOLERANCE_M))
    gate = np.asarray(gate, bool)
    labels, count = _components(lake)
    if count:
        size = np.bincount(labels.ravel(), minlength=count + 1)
        held = np.bincount(labels[inside], minlength=count + 1)
        touched = np.zeros(count + 1, bool)
        touched[np.unique(labels[full >= 0.5])] = True
        touched[0] = False
        mostly_inside = held >= LAKE_INSIDE_FRACTION * size
        full = np.where((touched & mostly_inside)[labels], 1.0, full)
        brushed = (touched & ~mostly_inside)[labels]
        full = np.where(brushed, 0.0, full)
        gate = gate & ~brushed
    return full, gate


def pack(full: np.ndarray, gate: np.ndarray) -> np.ndarray:
    levels = np.rint(np.clip(full, 0.0, 1.0) * FULL_LEVELS).astype(np.uint8)
    return levels | np.where(gate, GATE_BIT, 0).astype(np.uint8)


def unpack(packed: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    packed = np.asarray(packed, np.uint8)
    return (packed & FULL_LEVELS).astype(float) / FULL_LEVELS, (packed & GATE_BIT) != 0


def take(white: np.ndarray, packed: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """The white left for snow once the salt takes its ground, and the salt's own alpha."""
    full, gate = unpack(packed)
    return white * (1.0 - np.maximum(full, gate)), np.maximum(full, white * gate)


def land_white(geometries: list[dict], crs, transform: Affine, shape: tuple[int, int]) -> np.ndarray:
    """The white connected to each outline, followed on NSIDC-0791's grid and landed on this one."""
    gate = np.zeros(shape, bool)
    for geometry in geometries:
        cells, cells_transform = connected_white(features.bounds(geometry), geometries)
        landed = np.zeros(shape, np.uint8)
        reproject(cells.astype(np.uint8), landed, src_transform=cells_transform, src_crs="EPSG:4326",
                  dst_transform=transform, dst_crs=crs, resampling=Resampling.nearest)
        gate |= landed.astype(bool)
    return gate


def _projected(geometries: list[dict], crs) -> list[tuple[dict, dict]]:
    """Each outline beside its reprojection, dropping any the target cannot hold."""
    kept = []
    for geometry in geometries:
        projected = transform_geom("EPSG:4326", crs, geometry)
        if np.isfinite(features.bounds(projected)).all():
            kept.append((geometry, projected))
    return kept


def land(heightfield: np.ndarray, watercode: np.ndarray, crs, transform: Affine) -> np.ndarray:
    """The packed salt on one whole grid, a hero's."""
    shape = heightfield.shape
    grid = windows.Window(0, 0, shape[1], shape[0])  # pyright: ignore[reportCallIssue]
    near = []
    for geometry, projected in _projected(outlines(), crs):
        box = windows.from_bounds(*features.bounds(projected), transform=transform)
        if (box.col_off < grid.width and box.col_off + box.width > 0
                and box.row_off < grid.height and box.row_off + box.height > 0):
            near.append((geometry, projected))
    if not near:
        return np.zeros(shape, np.uint8)
    gate = land_white([geometry for geometry, _ in near], crs, transform, shape)
    full, gate = field(heightfield, watercode == lake_depth.LAKE_CLASS, transform,
                       [projected for _, projected in near], gate)
    return pack(full, gate)


def _clusters(boxes: list[windows.Window]) -> list[windows.Window]:
    """The boxes merged wherever two meet, until none do."""
    merged = list(boxes)
    joined = True
    while joined:
        joined = False
        for first in range(len(merged)):
            for second in range(first + 1, len(merged)):
                if windows.intersect(merged[first], merged[second]):
                    merged[first] = windows.union(merged[first], merged[second])
                    del merged[second]
                    joined = True
                    break
            if joined:
                break
    return merged


def build_planet(bounds: tuple[float, float, float, float], width: int, height: int, out: Path,
                 heightfield: Path, watermask: Path) -> None:
    """Every outline's packed salt on the planet's 3857 grid, written into `out`.

    Outlines whose boxes meet are worked together, and a box grows until nothing it keeps meets its
    edge, so a lake body or a white component is never cut by a box and then by a block.
    """
    transform = from_bounds(*bounds, width, height)
    pairs = _projected(outlines(), "EPSG:3857")
    lonlat = [geometry for geometry, _ in pairs]
    boxes = [windows.from_bounds(*features.bounds(projected), transform=transform)
             .round_offsets().round_lengths() for _, projected in pairs]
    out.unlink(missing_ok=True)
    with rasterio.open(out, "w", driver="GTiff", width=width, height=height, count=1,  # pyright: ignore[reportCallIssue]
                       dtype="uint8", crs="EPSG:3857", transform=transform, BIGTIFF="YES",
                       SPARSE_OK="TRUE", **GTIFF_CREATE):
        pass
    grid = windows.Window(0, 0, width, height)  # pyright: ignore[reportCallIssue]
    padded = [windows.Window(box.col_off - PLANET_MARGIN_PX, box.row_off - PLANET_MARGIN_PX,  # pyright: ignore[reportCallIssue]
                             box.width + 2 * PLANET_MARGIN_PX, box.height + 2 * PLANET_MARGIN_PX)
              for box in boxes]
    with rasterio.open(heightfield) as height_source, rasterio.open(watermask) as water_source, \
            rasterio.open(out, "r+") as target:
        for cluster in _clusters(padded):
            grow = 0
            while True:
                window = windows.Window(cluster.col_off - grow, cluster.row_off - grow,  # pyright: ignore[reportCallIssue]
                                        cluster.width + 2 * grow, cluster.height + 2 * grow).intersection(grid)
                window_transform = height_source.window_transform(window)
                members = [index for index, box in enumerate(boxes) if windows.intersect(box, window)]
                elevation = height_source.read(1, window=window).astype(float)
                watercode = water_source.read(1, window=window)
                shape = elevation.shape
                gate = land_white([lonlat[index] for index in members], "EPSG:3857", window_transform, shape)
                full, gate = field(elevation, watercode == lake_depth.LAKE_CLASS, window_transform,
                                   [pairs[index][1] for index in members], gate)
                if not _meets_edge((full > 0) | gate) or window == grid:
                    break
                grow = max(PLANET_MARGIN_PX, 2 * grow)
            held_full, held_gate = unpack(target.read(1, window=window))
            target.write(pack(np.maximum(held_full, full), held_gate | gate), 1, window=window)


def build_recipe() -> dict:
    """The constants the packed raster bakes in, and the snow ramp that decides which cells are white."""
    return {"salt_floor_tolerance_m": FLOOR_TOLERANCE_M,
            "salt_coverage_supersample": COVERAGE_SUPERSAMPLE,
            "salt_white_grow_cells": WHITE_GROW_CELLS,
            "salt_lake_inside_fraction": LAKE_INSIDE_FRACTION,
            "salt_full_levels": FULL_LEVELS,
            "snow_ramp_lat_lo": snow.RAMP_LAT_LO, "snow_ramp_lat_hi": snow.RAMP_LAT_HI,
            "snow_ramp_low_min": snow.RAMP_LOW_MIN, "snow_ramp_low_max": snow.RAMP_LOW_MAX,
            "snow_ramp_band": snow.RAMP_BAND}
