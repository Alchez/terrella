"""Salt flats: the ground two instruments misread, painted as salt on any grid.

NSIDC-0791 reads bright salt crust as persistent snow, and the elevation data's water body mask reads
it as lake. Two sources say where salt lies. Natural Earth's playas are outlines it calls dry lake
beds, saying nothing of salt; GWL_FCS30's saline class, a 30 m wetland map's, arrives as the share of
each cell it holds (`acquire/earth/extract_gwl.py`), and a patch is the 8-connected ground where that
share reaches `PATCH_SHARE`. On a grid the salt is:

  - each outline and each patch on its level floor, within `FLOOR_TOLERANCE_M` of its median height,
    so a hill or a slope inside a generalised outline stays land: an outline at its coverage of each
    cell, a patch at its share over itself and a `PATCH_RIM_CELLS` rim;
  - every lake body touching that salt which lies mostly inside the outlines and patches, whole, the
    water mask drawing a flat past its outline; a body lying mostly outside is a lake they brush, and
    none of it is salt;
  - the white connected to an outline, or to a patch's floor, on NSIDC-0791's own grid, at the
    white's own strength.

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
from rasterio.transform import array_bounds, from_bounds
from rasterio.warp import Resampling, reproject, transform_bounds, transform_geom
from scipy import ndimage

from pipeline import naturalearth
from pipeline.acquire.earth import extract_gwl
from pipeline.look import lake_depth, snow
from pipeline.raster_io import GTIFF_CREATE

#: Natural Earth's layer of dry lake beds.
LAYER = "ne_10m_playas"

#: How far from an outline's or a patch's median height a pixel still stands on its floor.
FLOOR_TOLERANCE_M = 10.0
#: Samples per pixel edge when an outline's coverage is measured, so its edge is antialiased.
COVERAGE_SUPERSAMPLE = 4
#: NSIDC-0791 cells added around the connected white, so its softened edge is taken with it.
WHITE_GROW_CELLS = 1
#: The share of a lake body the outlines and patches must hold for the whole body to be salt.
LAKE_INSIDE_FRACTION = 0.5
#: The saline share at which a cell belongs to a patch.
PATCH_SHARE = 0.5
#: Cells around a patch painted at their own share, so its edge is antialiased.
PATCH_RIM_CELLS = 1

#: The packed raster: the low seven bits carry the full-strength share in `FULL_LEVELS` steps, the
#: high bit the gate on the white.
FULL_LEVELS = 127
GATE_BIT = 128

#: Degrees of NSIDC-0791 read around a box before its white is followed, doubled until no kept
#: component meets the edge.
WHITE_MARGIN_DEG = 1.0
#: Pixels around an outline's box or a saline tile on the planet grid, and a window's first widening,
#: each widening after it doubling the total.
PLANET_MARGIN_PX = 256

EIGHT = np.ones((3, 3), bool)


def outlines() -> list[dict]:
    """Every outline in the layer, as a GeoJSON geometry in lon/lat."""
    reader = shapefile.Reader(str(naturalearth.layer(LAYER)))
    try:
        return [dict(shape.__geo_interface__) for shape in reader.shapes() if shape is not None]
    finally:
        reader.close()


def saline_tiles() -> list[tuple[str, tuple[float, float, float, float]]]:
    """Every tile the extractor wrote, which are the tiles holding saline, beside its lon/lat box with
    the span rounded to whole degrees, which its cells fall short of."""
    vrt = extract_gwl.saline_vrt()
    if not vrt.exists():
        raise FileNotFoundError(f"{vrt} missing: run pipeline.acquire.earth.extract_gwl")
    with rasterio.open(vrt) as mosaic:
        tiles = [name for name in mosaic.files if name.endswith(".tif")]
    found = []
    for tile in tiles:
        with rasterio.open(tile) as source:
            west, north = source.bounds.left, source.bounds.top
            span = round(source.bounds.right - west)
        found.append((tile, (west, north - span, west + span, north)))
    return found


def saline_share(crs, transform: Affine, shape: tuple[int, int],
                 tiles: list[tuple[str, tuple[float, float, float, float]]]) -> np.ndarray:
    """GWL_FCS30's saline class averaged onto a grid: the share of each cell it holds, 0 to 1.

    Each of `tiles`, as `saline_tiles()` gives them, is averaged onto the grid on its own, and a cell
    takes its share from the tile whose box holds its centre or, where that tile writes nothing into
    it, the most any tile writes there.
    """
    share = np.zeros(shape, np.float32)
    taken = np.zeros(shape, bool)
    elsewhere = np.zeros(shape, np.float32)
    west, south, east, north = transform_bounds(crs, "EPSG:4326", *array_bounds(*shape, transform),
                                                densify_pts=21)
    for tile, box in tiles:
        tile_west, tile_south, tile_east, tile_north = box
        if west < east and not (west < tile_east and tile_west < east and south < tile_north
                                and tile_south < north):
            continue
        part = np.full(shape, np.nan, np.float32)
        with rasterio.open(tile) as source:
            reproject(rasterio.band(source, 1), part, dst_transform=transform, dst_crs=crs,
                      dst_nodata=np.nan, resampling=Resampling.average)
        written = ~np.isnan(part)
        if not written.any():
            continue
        held = written & _burn([(transform_geom("EPSG:4326", crs, _box_polygon(box)), 1)], shape,
                               transform).astype(bool)
        share[held] = part[held]
        taken |= held
        elsewhere[written] = np.maximum(elsewhere[written], part[written])
    return np.where(taken, share, elsewhere)


def _box_polygon(bounds: tuple[float, float, float, float]) -> dict:
    """A lon/lat box as a polygon with enough points along each edge to stay a box once projected."""
    west, south, east, north = bounds
    steps = np.linspace(0.0, 1.0, 65)
    ring = ([(west + (east - west) * step, south) for step in steps]
            + [(east, south + (north - south) * step) for step in steps]
            + [(east - (east - west) * step, north) for step in steps]
            + [(west, north - (north - south) * step) for step in steps])
    return {"type": "Polygon", "coordinates": [ring]}


def _components(mask: np.ndarray) -> tuple[np.ndarray, int]:
    """The 8-connected components of `mask`, numbered from 1, and how many there are."""
    labels, count = ndimage.label(mask, structure=EIGHT)  # pyright: ignore[reportGeneralTypeIssues]
    return np.asarray(labels, dtype=np.int64), int(count)


def _burn(shapes: list[tuple[dict, int]], shape: tuple[int, int], transform: Affine) -> np.ndarray:
    return np.asarray(features.rasterize(shapes, out_shape=shape, transform=transform, fill=0,
                                         dtype="uint8"))


def patch_field(share: np.ndarray, heightfield: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Every saline patch on one grid: its paint, 0 to 1, the patches' cells, and the cells of each
    standing on its floor, which are what the white joins it from.

    A patch stands on its own median height, and is painted at its share over itself and a
    `PATCH_RIM_CELLS` rim wherever those cells stand on that floor.
    """
    labels, _count = _components(share >= PATCH_SHARE)
    paint = np.zeros(share.shape)
    on_floor = np.zeros(share.shape, bool)
    for index, box in enumerate(ndimage.find_objects(labels), 1):
        if box is None:
            continue
        grown = tuple(slice(max(part.start - PATCH_RIM_CELLS, 0), part.stop + PATCH_RIM_CELLS)
                      for part in box)
        member = labels[grown] == index
        floor = float(np.median(heightfield[grown][member]))
        level = np.abs(heightfield[grown] - floor) <= FLOOR_TOLERANCE_M
        rim = (np.asarray(ndimage.binary_dilation(member, structure=EIGHT, iterations=PATCH_RIM_CELLS), bool)
               if PATCH_RIM_CELLS else member)
        paint[grown] = np.maximum(paint[grown], np.where(rim & level, share[grown], 0.0))
        on_floor[grown] |= member & level
    return paint, labels > 0, on_floor


def white_cells(alpha: np.ndarray, inside: np.ndarray) -> np.ndarray:
    """The cells whose white connects to the salt: 8-connected components of `alpha` above zero that
    touch `inside`, grown by `WHITE_GROW_CELLS`."""
    labels, _count = _components(alpha > 0)
    touching = np.unique(labels[inside & (labels > 0)])
    kept = np.isin(labels, touching[touching > 0])
    # scipy reads zero iterations as "until nothing changes", which would flood the whole grid.
    if not WHITE_GROW_CELLS:
        return kept
    return ndimage.binary_dilation(kept, structure=EIGHT, iterations=WHITE_GROW_CELLS)


def _meets_edge(mask: np.ndarray) -> bool:
    return bool(mask[0].any() or mask[-1].any() or mask[:, 0].any() or mask[:, -1].any())


def ground_on(geometries: list[dict], seed, transform: Affine, shape: tuple[int, int]) -> np.ndarray:
    """The cells of a lon/lat grid the white joins salt on: `geometries` burnt, in lon/lat, and the
    cells of `seed`, a (mask, transform, crs) on any grid, landed wherever one of them falls."""
    ground = np.zeros(shape, bool)
    if geometries:
        ground |= _burn([(geometry, 1) for geometry in geometries], shape, transform).astype(bool)
    if seed is not None:
        mask, seed_transform, seed_crs = seed
        landed = np.zeros(shape, np.uint8)
        reproject(mask.astype(np.uint8), landed, src_transform=seed_transform, src_crs=seed_crs,
                  dst_transform=transform, dst_crs="EPSG:4326", resampling=Resampling.max)
        ground |= landed.astype(bool)
    return ground


def connected_white(bounds: tuple[float, float, float, float], geometries: list[dict],
                    seed=None) -> tuple[np.ndarray, Affine]:
    """`white_cells` on NSIDC-0791's own grid around a lon/lat box, and that grid's transform.

    The white joins `ground_on(geometries, seed)`. The tiles' own ramp decides which cells are white.
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
            gate = white_cells(alpha, ground_on(geometries, seed, transform, packed.shape))
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
          patches: tuple[np.ndarray, np.ndarray], gate: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """The salt on one grid: its full-strength share, 0 to 1, and the gate the white is salt under.

    `geometries` are the outlines in the grid's own coordinates, `patches` the saline patches' paint
    and cells as `patch_field` gives them, `lake` the water mask's lake class and `gate` the
    connected white landed on the grid.
    """
    paint, cells = patches
    full = np.array(paint, dtype=float)
    inside = np.array(cells, dtype=bool)
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


def _landed(cells: np.ndarray, cells_transform: Affine, crs, transform: Affine,
            shape: tuple[int, int]) -> np.ndarray:
    """Connected white from NSIDC-0791's grid, landed on this one."""
    landed = np.zeros(shape, np.uint8)
    reproject(cells.astype(np.uint8), landed, src_transform=cells_transform, src_crs="EPSG:4326",
              dst_transform=transform, dst_crs=crs, resampling=Resampling.nearest)
    return landed.astype(bool)


def land_white(geometries: list[dict], crs, transform: Affine, shape: tuple[int, int]) -> np.ndarray:
    """The white connected to each outline, followed on NSIDC-0791's grid and landed on this one."""
    gate = np.zeros(shape, bool)
    for geometry in geometries:
        gate |= _landed(*connected_white(features.bounds(geometry), geometries), crs, transform, shape)
    return gate


def land_patch_white(on_floor: np.ndarray, crs, transform: Affine) -> np.ndarray:
    """The white connected to the patches' floors, followed on NSIDC-0791's grid and landed on this one."""
    if not on_floor.any():
        return np.zeros(on_floor.shape, bool)
    rows, cols = np.nonzero(on_floor)
    box = windows.Window(cols.min(), rows.min(), cols.max() - cols.min() + 1,  # pyright: ignore[reportCallIssue]
                         rows.max() - rows.min() + 1)
    bounds = transform_bounds(crs, "EPSG:4326", *windows.bounds(box, transform), densify_pts=21)
    return _landed(*connected_white(bounds, [], (on_floor, transform, crs)), crs, transform,
                   on_floor.shape)


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
    paint, cells, on_floor = patch_field(saline_share(crs, transform, shape, saline_tiles()), heightfield)
    if not near and not cells.any():
        return np.zeros(shape, np.uint8)
    gate = (land_white([geometry for geometry, _ in near], crs, transform, shape)
            | land_patch_white(on_floor, crs, transform))
    full, gate = field(heightfield, watercode == lake_depth.LAKE_CLASS, transform,
                       [projected for _, projected in near], (paint, cells), gate)
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


def _padded(box: windows.Window, cells: int) -> windows.Window:
    return windows.Window(box.col_off - cells, box.row_off - cells,  # pyright: ignore[reportCallIssue]
                          box.width + 2 * cells, box.height + 2 * cells)


def _holds(window: windows.Window, box: windows.Window) -> bool:
    return (box.col_off >= window.col_off and box.row_off >= window.row_off
            and box.col_off + box.width <= window.col_off + window.width
            and box.row_off + box.height <= window.row_off + window.height)


def _taking_in(window: windows.Window, boxes: list[windows.Window],
               clusters: list[windows.Window]) -> windows.Window:
    """`window` grown to hold the cluster of every box it cuts, until it cuts none."""
    while True:
        cut = [box for box in boxes if windows.intersect(box, window) and not _holds(window, box)]
        met = [cluster for cluster in clusters
               if not _holds(window, cluster) and any(windows.intersect(cluster, box) for box in cut)]
        if not met:
            return window
        window = windows.union(window, *met)


def _core(bounds: tuple[float, float, float, float], transform: Affine) -> windows.Window:
    """A lon/lat box's cells on the planet grid, each edge rounded on its own, so tiles that meet
    divide the cells between them."""
    west, south, east, north = transform_bounds("EPSG:4326", "EPSG:3857", *bounds)
    col0, col1 = (round((x - transform.c) / transform.a) for x in (west, east))
    row0, row1 = (round((y - transform.f) / transform.e) for y in (north, south))
    return windows.Window(col0, row0, col1 - col0, row1 - row0)  # pyright: ignore[reportCallIssue]


def _whole_patches(share: np.ndarray, own: "windows.Window | None") -> tuple[np.ndarray, bool]:
    """`share` less every patch within `PATCH_RIM_CELLS + 1` cells of the window's edge, which the
    edge may cut, bar the window's own; and whether any of its own lies there.

    A patch is the window's own when the first of its cells in raster order lies in `own`, the
    window's saline tile in window coordinates. That cell lies in one tile, so one window grows to
    hold the patch and every other window that cuts it leaves it.
    """
    labels, count = _components(share >= PATCH_SHARE)
    reach = PATCH_RIM_CELLS + 1
    band = np.zeros(share.shape, bool)
    band[:reach] = band[-reach:] = True
    band[:, :reach] = band[:, -reach:] = True
    near_edge = np.unique(labels[band & (labels > 0)])
    if not len(near_edge):
        return share, False
    owned = np.zeros(count + 1, bool)
    if own is not None:
        order = np.arange(labels.size, dtype=np.int64).reshape(labels.shape)
        first = np.asarray(ndimage.minimum(order, labels, near_edge), np.int64)
        rows, cols = np.divmod(first, labels.shape[1])
        owned[near_edge] = ((rows >= own.row_off) & (rows < own.row_off + own.height)
                            & (cols >= own.col_off) & (cols < own.col_off + own.width))
    dropped = np.zeros(count + 1, bool)
    dropped[near_edge] = True
    dropped &= ~owned
    return np.where(dropped[labels], 0.0, share), bool(owned.any())


def build_planet(bounds: tuple[float, float, float, float], width: int, height: int, out: Path,
                 heightfield: Path, watermask: Path) -> None:
    """Every salt flat's packed field on the planet's 3857 grid, written into `out`.

    The work goes by window: one for each cluster of outlines whose boxes meet, and one for each
    saline tile. Merging touching tiles as the outlines merge is the temptation, and it makes one
    window of a continent's salt. A window grows until every outline it meets lies inside it, none of
    its own patches lies near its edge, and nothing it paints meets the edge, so a lake body or a
    white component is never cut by a window and then by a block. An outline it cuts brings its whole
    cluster in, and anything else widens it on every side, each widening doubling the total. Widening
    for a cut outline too looks simpler, and across a field of outlines each widening cuts another
    until the window outgrows memory. Where windows overlap, the salt is the most any of them paints.
    """
    transform = from_bounds(*bounds, width, height)
    pairs = _projected(outlines(), "EPSG:3857")
    boxes = [windows.from_bounds(*features.bounds(projected), transform=transform)
             .round_offsets().round_lengths() for _, projected in pairs]
    tiles = saline_tiles()
    clusters = _clusters([_padded(box, PLANET_MARGIN_PX) for box in boxes])
    seeds: list[tuple[windows.Window, windows.Window | None]] = [(cluster, None) for cluster in clusters]
    seeds += [(_padded(core, PLANET_MARGIN_PX), core)
              for core in (_core(box, transform) for _tile, box in tiles)]
    out.unlink(missing_ok=True)
    with rasterio.open(out, "w", driver="GTiff", width=width, height=height, count=1,  # pyright: ignore[reportCallIssue]
                       dtype="uint8", crs="EPSG:3857", transform=transform, BIGTIFF="YES",
                       SPARSE_OK="TRUE", **GTIFF_CREATE):
        pass
    with rasterio.open(heightfield) as height_source, rasterio.open(watermask) as water_source, \
            rasterio.open(out, "r+") as target:
        for seed, core in seeds:
            window, full, gate = bake_window(seed, core, height_source, water_source, pairs, boxes, clusters,
                                             tiles)
            held_full, held_gate = unpack(target.read(1, window=window))
            target.write(pack(np.maximum(held_full, full), held_gate | gate), 1, window=window)


def bake_window(seed: windows.Window, core: "windows.Window | None", height_source, water_source,
                pairs: list[tuple[dict, dict]], boxes: list[windows.Window], clusters: list[windows.Window],
                tiles: list[tuple[str, tuple[float, float, float, float]]],
                ) -> tuple[windows.Window, np.ndarray, np.ndarray]:
    """One of `build_planet`'s windows, grown from `seed` until it cuts nothing it keeps: the window,
    and its full share and gate. `core` is its saline tile, None for a cluster of outlines."""
    grid = windows.Window(0, 0, height_source.width, height_source.height)  # pyright: ignore[reportCallIssue]
    window = seed.intersection(grid)
    grow = 0
    while True:
        window_transform = height_source.window_transform(window)
        members = [index for index, box in enumerate(boxes) if windows.intersect(box, window)]
        elevation = height_source.read(1, window=window).astype(float)
        watercode = water_source.read(1, window=window)
        shape = elevation.shape
        own = None if core is None else windows.Window(core.col_off - window.col_off,  # pyright: ignore[reportCallIssue]
                                                       core.row_off - window.row_off, core.width, core.height)
        share, own_at_edge = _whole_patches(saline_share("EPSG:3857", window_transform, shape, tiles), own)
        paint, cells, on_floor = patch_field(share, elevation)
        gate = (land_white([pairs[index][0] for index in members], "EPSG:3857", window_transform, shape)
                | land_patch_white(on_floor, "EPSG:3857", window_transform))
        full, gate = field(elevation, watercode == lake_depth.LAKE_CLASS, window_transform,
                           [pairs[index][1] for index in members], (paint, cells), gate)
        cuts = (own_at_edge or _meets_edge((full > 0) | gate)
                or not all(_holds(window, boxes[index]) for index in members))
        if not cuts or window == grid:
            return window, full, gate
        taken = _taking_in(window, boxes, clusters).intersection(grid)
        if taken == window:
            step = max(PLANET_MARGIN_PX, 2 * grow)
            taken = _padded(window, step - grow).intersection(grid)
            grow = step
        window = taken


def build_recipe() -> dict:
    """The constants the packed raster bakes in, and the snow ramp that decides which cells are white."""
    return {"salt_floor_tolerance_m": FLOOR_TOLERANCE_M,
            "salt_coverage_supersample": COVERAGE_SUPERSAMPLE,
            "salt_white_grow_cells": WHITE_GROW_CELLS,
            "salt_lake_inside_fraction": LAKE_INSIDE_FRACTION,
            "salt_patch_share": PATCH_SHARE,
            "salt_patch_rim_cells": PATCH_RIM_CELLS,
            "salt_full_levels": FULL_LEVELS,
            "snow_ramp_lat_lo": snow.RAMP_LAT_LO, "snow_ramp_lat_hi": snow.RAMP_LAT_HI,
            "snow_ramp_low_min": snow.RAMP_LOW_MIN, "snow_ramp_low_max": snow.RAMP_LOW_MAX,
            "snow_ramp_band": snow.RAMP_BAND}
