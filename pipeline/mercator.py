"""Web-Mercator geometry, in one home and parameterised by the sphere it is projected on.

WHY THIS MODULE EXISTS. `render/hillshade.py` and `render/snow.py` each carried their own
`EARTH_RADIUS = 6378137.0` and their own transcription of the inverse projection. Two copies of a
constant is the drift this project has already paid for; two copies of the FORMULA is the same
hazard with more surface, and nothing related them — a fix applied to one would have looked
complete.

WHY THE RADIUS IS AN ARGUMENT. Because the conversion is not about Earth. A northing does not name
a latitude on its own; it names one PER SPHERE, and the radius is the whole of the difference. Mars
is ~53% of Earth's radius, so the same metre value reads 41 degrees on one planet and 72 on the
other. Nothing about the wrong answer looks wrong — the hillshade's per-row z-factor simply comes
out plausible at every latitude and correct at none, which is the failure mode that ships.

Kept free of the body registry deliberately: this is projection maths, and coupling it to a planet
catalogue would mean every caller that has a radius but no `Body` had to invent one.
"""

import math

import numpy as np
from numpy.typing import NDArray

#: The sphere EPSG:3857 is DEFINED on, in metres. A projection constant, not a planet's property —
#: it happens to equal Earth's equatorial radius because that is where the projection came from,
#: and it stays this number for every body: PROJ refuses to build an operation between two celestial
#: bodies, so every raster in this pipeline is EPSG:3857 whatever planet its elevations describe.
#:
#: So a northing on a tile grid names a latitude on THIS sphere for Mars exactly as it does for
#: Earth, and a caller reaching into the body registry for it is asking the wrong question — the
#: latitude of a grid row is a property of the grid, not of the ground under it. `bodies.EARTH`
#: pins the same value as the body's own radius, which is a separate coincidence with its own test.
WEB_MERCATOR_RADIUS_M = 6378137.0


def latitude_at(mercator_y, radius_m: float):
    """Latitude in degrees of a Web-Mercator northing, on a sphere of `radius_m`.

    Accepts a scalar or any array shape and preserves it — the callers hand this whole pixel-row
    arrays, and a scalar-only implementation would broadcast into something silently reshaped.
    """
    return np.degrees(2.0 * np.arctan(np.exp(np.divide(mercator_y, radius_m))) - math.pi / 2.0)


def northing_at(latitude_deg, radius_m: float) -> NDArray[np.float64]:
    """The forward projection: Web-Mercator northing of a latitude, on a sphere of `radius_m`.

    Present so a caller never has to re-derive it, and so `latitude_at` has a companion to be
    checked against — the tests use it as an independent oracle rather than asking the inverse to
    confirm itself, which it would do however wrong it was.
    """
    radians = np.radians(latitude_deg)
    return np.asarray(radius_m * np.log(np.tan(math.pi / 4.0 + radians / 2.0)), dtype=np.float64)
