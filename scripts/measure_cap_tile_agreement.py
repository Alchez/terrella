"""Do a body's shipped terrain tiles and its polar cap texture report the same height?

The unit test for this property (`test_the_encode_is_a_pure_function_of_metres_at_every_latitude`)
runs a constructed raster through the encoder, deliberately touching no archive: it has to stay
green between a recipe change and the re-cut that answers it, so it cannot read what is on disk.
This is the other half — it reads the ARTIFACTS, and it is the check to run after a cut.

The two producers overlap between `cap_render.CAP_EDGE_LAT` and the Mercator limit, and
`polarCaps.ts` crossfades between them there, so a disagreement is two surfaces the viewer sees at
once. A polar elevation ramp in the tile path once put them 4.7 km apart on Mars and 3.5 km on
Earth while every encoding test passed, because those tests compare bytes and this compares ground.

Usage: `python -m scripts.measure_cap_tile_agreement --body mars` (or `earth`).
"""
import argparse
import math
from pathlib import Path

import rasterio

from pipeline import bodies
from pipeline.tile import cap_render, terrain_rgb

#: Latitudes to compare — the crossfade band, from the cap disc's own edge to the Mercator limit.
#: Nothing below `CAP_EDGE_LAT` belongs here: the cap does not exist there, and a sampler that
#: clamped to the texture's edge instead of refusing reported a 1.2 km disagreement that was its
#: own doing.
SAMPLE_LATITUDES = (80.0, 81.0, 82.0, 83.0, 84.0, 84.8)

#: A disagreement this large cannot be the cap texture's own coarseness — it samples ~2.3 km/px on
#: Mars against a tile's ~325 m, so a few hundred metres of terrain roughness is expected and a
#: kilometre is a systematic term.
TOLERANCE_M = 500.0


def tile_metres(tiles: Path, zoom: int, latitude: float, longitude: float) -> float:
    """Decode one shipped tile's pixel at a lat/lon, through the same arithmetic MapLibre applies."""
    world = terrain_rgb.TILE_SIZE * 2**zoom
    sin_lat = math.sin(math.radians(latitude))
    pixel_x = (longitude + 180.0) / 360.0 * world
    pixel_y = (0.5 - math.log((1 + sin_lat) / (1 - sin_lat)) / (4 * math.pi)) * world
    tile_x, tile_y = int(pixel_x // terrain_rgb.TILE_SIZE), int(pixel_y // terrain_rgb.TILE_SIZE)
    path = tiles / str(zoom) / str(tile_x) / f"{tile_y}.webp"
    if not path.exists():
        raise SystemExit(f"no tile at {path} — cut the pyramid first")
    with rasterio.open(path) as dataset:
        encoded = dataset.read()
    column = int(pixel_x) % terrain_rgb.TILE_SIZE
    row = int(pixel_y) % terrain_rgb.TILE_SIZE
    return float(terrain_rgb.decode_array(encoded, terrain_rgb.QUANTISATION_M)[row, column])


def cap_metres(body: bodies.Body, latitude: float, longitude: float) -> float:
    """Decode the north cap's AEQD elevation texture at a lat/lon. Radius is LINEAR in colatitude."""
    grid = cap_render.north_grid(body)
    with rasterio.open(cap_render.cap_elev_asset(grid)) as dataset:
        encoded = dataset.read()
    side = encoded.shape[1]
    radius = (90.0 - abs(latitude)) / (90.0 - abs(grid.edge_lat))
    if radius > 1.0:
        raise SystemExit(f"lat {latitude} is outside the cap disc (edge {grid.edge_lat})")
    angle = math.radians(longitude)
    column = min(side - 1, max(0, int((0.5 + 0.5 * radius * math.sin(angle)) * side)))
    row = min(side - 1, max(0, int((0.5 + 0.5 * radius * math.cos(angle)) * side)))
    return float(terrain_rgb.decode_array(encoded, terrain_rgb.QUANTISATION_M)[row, column])


def main() -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").split("\n")[0])
    parser.add_argument("--body", required=True, choices=sorted(bodies.BODIES))
    parser.add_argument("--tiles", type=Path, default=None,
                        help="override the pyramid directory (default: the shipped variant)")
    parser.add_argument("--lon", type=float, default=0.0, help="meridian to sample")
    arguments = parser.parse_args()
    body = bodies.get(arguments.body)
    tiles = arguments.tiles or (bodies.work_dir(body, "planet_terrain")
                                / f"bathy_s{terrain_rgb.QUANTISATION_M:g}_webp" / "tiles")
    zoom = terrain_rgb.master_zoom_for(body)

    print(f"{body.name}: z{zoom} tiles under {tiles}, north cap texture, meridian {arguments.lon}\n")
    print(f"{'lat':>6} {'cap m':>10} {'tile m':>10} {'gap m':>10}")
    print("-" * 40)
    worst = 0.0
    for latitude in SAMPLE_LATITUDES:
        cap = cap_metres(body, latitude, arguments.lon)
        tile = tile_metres(tiles, zoom, latitude, arguments.lon)
        gap = cap - tile
        worst = max(worst, abs(gap))
        print(f"{latitude:6.1f} {cap:10.1f} {tile:10.1f} {gap:10.1f}")

    print(f"\nworst |gap| {worst:.1f} m against a {TOLERANCE_M:.0f} m tolerance")
    if worst > TOLERANCE_M:
        print("DISAGREE — the two surfaces the crossfade blends are not at the same height")
        return 1
    print("AGREE")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
