"""Web-Mercator geometry, in one home and parameterised by the sphere it is projected on.

The radius is an argument because the conversion is not about Earth. A northing names a latitude per
sphere, and the radius is the whole of the difference: Mars is ~53% of Earth's, so the same metre
value reads 41 degrees on one planet and 72 on the other, and a per-row z-factor built on the wrong
one comes out plausible at every latitude and correct at none.

Kept clear of the body registry, so a caller holding a radius but no `Body` need not invent one.
"""

import math

import numpy as np
from numpy.typing import NDArray

#: The sphere EPSG:3857 is defined on, in metres. A projection constant, not a planet's property: it
#: equals Earth's equatorial radius because that is where the projection came from, and it stays this
#: number for every body, since PROJ refuses an operation between two celestial bodies and every
#: raster here is EPSG:3857 whatever planet it describes. `bodies.EARTH` pinning the same value is a
#: separate coincidence with its own test.
WEB_MERCATOR_RADIUS_M = 6378137.0

#: Half the width of the Web Mercator plane in map units: where the world's east and west edges sit,
#: and so what "this raster is global" means to a caller holding only bounds.
#:
#: Derived rather than transcribed, because the digits drift and a truncation still passes any
#: tolerance worth writing. Earth's heightfield overshoots this by 12.25 m and Mars lands on it
#: exactly, so a globalness test compares against a pixel size, never against these decimals.
MERCATOR_HALF_M = math.pi * WEB_MERCATOR_RADIUS_M

#: Ground metres per pixel of a 512px WebMercatorQuad tile at zoom 8, at the equator. Every other
#: latitude is this times `cos(lat)`, which is what `ground_metres_per_pixel` below is for.
Z8_MERC_RES = 305.7483


def latitude_at(mercator_y, radius_m: float):
    """Latitude in degrees of a Web-Mercator northing, on a sphere of `radius_m`.

    Scalar or any array shape, preserved: callers pass whole pixel-row arrays.
    """
    return np.degrees(2.0 * np.arctan(np.exp(np.divide(mercator_y, radius_m))) - math.pi / 2.0)


def ground_metres_per_pixel(latitude_deg, map_units_per_pixel: float, ground_scale: float):
    """Ground metres one pixel of a Web-Mercator grid covers at this latitude.

    Two factors, neither optional: Mercator stretches by 1/cos(latitude), and a map unit is a ground
    metre only where the body's radius matches the projection sphere's, which is
    `bodies.ground_metres_per_mercator_unit`, 1.0 on Earth and 1.878 on Mars. Both are supplied
    rather than looked up, so a caller cannot silently get Earth.

    Scalar or a per-row array of latitudes, shape preserved.
    """
    return map_units_per_pixel * ground_scale * np.cos(np.radians(latitude_deg))


def northing_at(latitude_deg, radius_m: float) -> NDArray[np.float64]:
    """The forward projection: Web-Mercator northing of a latitude, on a sphere of `radius_m`.

    The independent oracle `latitude_at` is checked against, rather than against its own inverse.
    """
    radians = np.radians(latitude_deg)
    return np.asarray(radius_m * np.log(np.tan(math.pi / 4.0 + radians / 2.0)), dtype=np.float64)
