"""The hero lane's snow stage: the tiles' white, folded on a country's own grid, and the salt that
takes its share of it.

One law with the block prep. The producers `layer_producers` registers answer each layer in
`layers.HERO_LAYERS` and `fold_white` folds them, then `salt.take` gives the salt flats their
ground, so a hero's snow and salt and its tiles' differ only in the grid. The sources land on that
grid from their own files, as the cap tier's do: NSIDC-0791 persistence warped bilinear, RGI's
outlines reprojected and burnt, and the salt baked from Natural Earth's outlines with this grid's
own heightfield and water mask, rather than re-warped from the planet's 3857 rasters at a second
remove.

A grid reaching the forced Antarctic white is refused: that white is a latitude rule less SCAR ADD's
exposed rock, and this stage burns no rock, so it would paint the outcrop.

Resumes on a recipe beside the mask rather than on the mask existing, so a mask made under another
law is rebuilt rather than kept.

Usage:
  python -m pipeline.render.snow_mask --body earth --render-dir data/work/switzerland/render
"""

import argparse
import json
import os
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import rasterio
from pyproj import Transformer
from rasterio.warp import transform_bounds

from pipeline import bodies, freshness, layers, render_files, vector_raster
from pipeline.look import lake_depth, layer_producers, salt, snow
from pipeline.render import prep_block, render_seam

RECIPE_NAME = "snow_recipe.json"

#: Rows of latitude computed per pass, so a large grid never holds every pixel's easting and
#: northing at once.
LATITUDE_BAND_ROWS = 512

#: Degrees added around a frame's lon/lat footprint before glacier outlines are filtered to it, so an
#: outline that crosses the footprint's edge is kept whole.
FOOTPRINT_MARGIN_DEG = 0.1


@dataclass(frozen=True)
class HeroGrid:
    """The grid the heightfield was warped to, which every image in the folder shares."""

    crs: Any
    transform: Any
    width: int
    height: int
    bounds: tuple[float, float, float, float]


def hero_white(body: bodies.Body, sources: "dict[str, np.ndarray | None]", *, ocean: np.ndarray,
               watercode: np.ndarray, latitude: np.ndarray, ground_metres_per_px: float
               ) -> "tuple[np.ndarray, render_seam.Paint | None, np.ndarray | None, render_seam.Paint | None]":
    """The white this body's producers fold on one hero grid and its paint, then the salt's alpha
    and paint, None where the grid has no salt layer landed.

    `sources` maps each `HERO_LAYERS` name to its file landed on this grid, or None where none was.
    Land is the tile tier's: neither open sea nor inland water.
    """
    southmost = float(np.min(latitude))
    if southmost < snow.ANTARCTIC_WHITE_LAT:
        raise ValueError(
            f"this grid reaches {southmost:.1f} degrees, inside the forced Antarctic white, whose "
            f"exposed-rock exclusion this stage does not burn; it would paint the outcrop white")
    land = ~(ocean | lake_depth.inland_water(watercode))
    window = layer_producers.LayerWindow(raw=None, watercode=watercode, land=land, ocean=ocean,
                                         latitude=latitude, ground_metres_per_px=ground_metres_per_px)
    layer_raw = {name: sources.get(name) for name in layers.HERO_LAYERS}
    contributions, paints, exclusions = layer_producers.gather(body, layer_raw, window,
                                                               layers.HERO_LAYERS)
    alpha, _ = layer_producers.fold_white(contributions, land.shape, exclusions=exclusions)
    snow_paint = prep_block.merged_paint(paints, layer_producers.WHITE_UNION, "the white union")
    ground = layer_producers.salt_ground(body, layer_raw, window, layers.HERO_LAYERS)
    if ground is None:
        return alpha, snow_paint, None, None
    packed, (sunlit, shadowed) = ground
    alpha, salt_alpha = salt.take(alpha, packed)
    return alpha, snow_paint, salt_alpha, (prep_block.one_colour(sunlit, "salt sunlit"),
                                           prep_block.one_colour(shadowed, "salt shadowed"))


def recipe(body: bodies.Body) -> dict[str, Any]:
    """What the masks depend on beyond their files: the producers' constants and paint, which layers
    fold in and out, which the body has, and what a producer landed here bakes in, the salt building
    on this grid rather than in the warp stage."""
    builds = {layer.name: producer.build_recipe()
              for layer, producer in layer_producers.producers_for(body, layers.HERO_LAYERS)
              if producer.build_recipe()}
    return {"constants": layer_producers.constants_for(body, layers.HERO_LAYERS, painted=True),
            "white_law": layer_producers.white_law(body, layers.HERO_LAYERS),
            "layers_on": layers.layers_on(body, layers.HERO_LAYERS),
            **({"builds": builds} if builds else {})}


def inputs(render_dir: Path, body: bodies.Body) -> tuple[Path, ...]:
    """The files whose change makes the mask stale: the producers' sources and the grid's own."""
    sources = tuple(source for _layer, producer in
                    layer_producers.producers_for(body, layers.HERO_LAYERS)
                    for source in producer.sources())
    return sources + tuple(render_dir / name for name in (
        render_files.HEIGHTFIELD, render_files.OCEANMASK_TIF, render_files.WATERMASK))


def is_current(render_dir: Path, body: bodies.Body) -> bool:
    """Whether this folder's snow was made under today's recipe from today's inputs, and every
    image the stage declared is still there."""
    recipe_path = render_dir / RECIPE_NAME
    if freshness.recorded_json(recipe_path) != json.loads(json.dumps(recipe(body))):
        return False
    if freshness.is_stale(recipe_path, *inputs(render_dir, body)):
        return False
    written = render_seam.stage_images(render_dir, render_seam.SNOW)
    return written is not None and all((render_dir / image).exists() for image in written)


def record(render_dir: Path, body: bodies.Body) -> None:
    """Write the recipe, then vouch for it. Last, so a crash before it leaves the folder stale."""
    recipe_path = render_dir / RECIPE_NAME
    freshness.write_if_changed(recipe_path, json.dumps(recipe(body), indent=1, sort_keys=True) + "\n")
    freshness.mark_done(recipe_path)


def read_grid(render_dir: Path) -> HeroGrid:
    with rasterio.open(render_dir / render_files.HEIGHTFIELD) as heightfield:
        return HeroGrid(heightfield.crs, heightfield.transform, heightfield.width,
                        heightfield.height, tuple(heightfield.bounds))


def latitude_grid(grid: HeroGrid) -> np.ndarray:
    """True latitude at every pixel centre."""
    to_lonlat = Transformer.from_crs(grid.crs, "EPSG:4326", always_xy=True)
    columns = np.arange(grid.width) + 0.5
    latitude = np.empty((grid.height, grid.width))
    for start in range(0, grid.height, LATITUDE_BAND_ROWS):
        rows = np.arange(start, min(grid.height, start + LATITUDE_BAND_ROWS))[:, None] + 0.5
        eastings = grid.transform.a * columns + grid.transform.b * rows + grid.transform.c
        northings = grid.transform.d * columns + grid.transform.e * rows + grid.transform.f
        _, latitude[start:start + rows.shape[0]] = to_lonlat.transform(eastings, northings)
    return latitude


def lonlat_footprint(grid: HeroGrid) -> "tuple[float, float, float, float] | None":
    """The grid's lon/lat box with a margin, or None where it crosses the dateline and no west-to-east
    box can hold it."""
    west, south, east, north = transform_bounds(grid.crs, "EPSG:4326", *grid.bounds, densify_pts=64)
    if not (west < east and south < north):
        return None
    return (max(-180.0, west - FOOTPRINT_MARGIN_DEG), max(-90.0, south - FOOTPRINT_MARGIN_DEG),
            min(180.0, east + FOOTPRINT_MARGIN_DEG), min(90.0, north + FOOTPRINT_MARGIN_DEG))


def land_persistence(sources: tuple[Path, ...], grid: HeroGrid, render_dir: Path) -> np.ndarray:
    (source,) = sources
    landed = render_dir / "snow_persistence.tmp.tif"
    snow.warp_persistence_raster(grid.bounds, grid.width, grid.height, landed, sp_nc=source,
                                 target_srs=grid.crs.to_wkt())
    with rasterio.open(landed) as dataset:
        packed = dataset.read(1)
    landed.unlink(missing_ok=True)
    return packed


def land_glaciers(sources: tuple[Path, ...], grid: HeroGrid, render_dir: Path) -> np.ndarray:
    (source,) = sources
    projected, landed = render_dir / "glaciers.tmp.gpkg", render_dir / "glaciers.tmp.tif"
    vector_raster.burn_onto_grid(source, grid.crs.to_wkt(), grid.bounds, grid.width, grid.height,
                                 projected, landed, creation_options=("TILED=YES", "COMPRESS=DEFLATE"),
                                 lonlat_filter=lonlat_footprint(grid))
    with rasterio.open(landed) as dataset:
        outlines = dataset.read(1)
    projected.unlink(missing_ok=True)
    landed.unlink(missing_ok=True)
    return outlines


def land_salt(_sources: tuple[Path, ...], grid: HeroGrid, render_dir: Path) -> np.ndarray:
    """The packed salt baked on this grid, from its own heightfield and water mask; `look/salt.py`
    reads the outlines and the persistence the producer lists."""
    with rasterio.open(render_dir / render_files.HEIGHTFIELD) as dataset:
        heightfield = dataset.read(1).astype(float)
    with rasterio.open(render_dir / render_files.WATERMASK) as dataset:
        watercode = dataset.read(1)
    return salt.land(heightfield, watercode, grid.crs, grid.transform)


#: How each `HERO_LAYERS` source reaches a hero grid, by layer. A layer added to that view with no
#: entry here raises before the mask is written.
LANDERS: dict[str, Callable[[tuple[Path, ...], HeroGrid, Path], np.ndarray]] = {
    layers.PERENNIAL_ICE.name: land_persistence,
    layers.GLACIERS.name: land_glaciers,
    layers.SALT_FLATS.name: land_salt,
}


def land_sources(body: bodies.Body, grid: HeroGrid, render_dir: Path) -> "dict[str, np.ndarray | None]":
    landed: dict[str, np.ndarray | None] = {}
    for layer, producer in layer_producers.producers_for(body, layers.HERO_LAYERS):
        sources = tuple(Path(source) for source in producer.sources())
        if not all(layers.layer_is_buildable(body, layer, source, "a hero without it")
                   for source in sources):
            landed[layer.name] = None
            continue
        landed[layer.name] = LANDERS[layer.name](sources, grid, render_dir)
    return landed


def _write_mask(render_dir: Path, image: str, alpha: "np.ndarray | None",
                paint: "render_seam.Paint | None") -> bool:
    """One mask where any pixel is painted, written beside and moved into place, with its paint;
    whether it was written."""
    out = render_dir / image
    out.with_name(out.name + ".aux.xml").unlink(missing_ok=True)
    if alpha is None or not alpha.any():
        out.unlink(missing_ok=True)
        return False
    if paint is None:
        raise ValueError(f"a {image} with no paint declared by any producer is not a usable render input")
    partial = out.with_name(out.name + ".tmp")
    prep_block.write_mask(partial, alpha)
    os.replace(partial, out)
    render_seam.declare_paint(render_dir, image, *paint)
    return True


def write_masks(render_dir: Path, snow_alpha: np.ndarray, snow_paint: "render_seam.Paint | None",
                salt_alpha: "np.ndarray | None", salt_paint: "render_seam.Paint | None") -> None:
    """The snow and salt masks where each paints a pixel, and the stage's record either way."""
    written = [image for image, alpha, paint in ((render_files.SNOWMASK, snow_alpha, snow_paint),
                                                 (render_files.SALTMASK, salt_alpha, salt_paint))
               if _write_mask(render_dir, image, alpha, paint)]
    render_seam.declare(render_dir, render_seam.SNOW, written)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--body", required=True, choices=sorted(bodies.BODIES),
                    help="whose producers paint the snow; no default, because a body that inherited "
                         "Earth's would paint its heroes in Earth's snow")
    ap.add_argument("--render-dir", type=Path, required=True,
                    help=f"existing render dir with {render_files.HEIGHTFIELD}")
    args = ap.parse_args()
    body = bodies.get(args.body)
    render_dir = args.render_dir.resolve()
    if is_current(render_dir, body):
        print(f"{render_dir / RECIPE_NAME} is current: skipping", flush=True)
        return

    grid = read_grid(render_dir)
    with rasterio.open(render_dir / render_files.OCEANMASK_TIF) as dataset:
        ocean = dataset.read(1) != 0
    with rasterio.open(render_dir / render_files.WATERMASK) as dataset:
        watercode = dataset.read(1)
    alpha, paint, salt_alpha, salt_paint = hero_white(
        body, land_sources(body, grid, render_dir), ocean=ocean, watercode=watercode,
        latitude=latitude_grid(grid), ground_metres_per_px=abs(grid.transform.a))
    write_masks(render_dir, alpha, paint, salt_alpha, salt_paint)
    record(render_dir, body)
    print(f"snow: white over {float((alpha >= 0.5).mean()):.2%} of the frame, some over "
          f"{float((alpha > 0.0).mean()):.2%}", flush=True)
    if salt_alpha is not None:
        print(f"salt: over {float((salt_alpha >= 0.5).mean()):.2%} of the frame", flush=True)


if __name__ == "__main__":
    main()
