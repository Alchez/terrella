"""Relief/shading geometry helpers shared by the hero and tile shading paths.

Kept dependency-free (pure math) so it can be imported from either interpreter.
"""

import math


def mercator_zfactor(latitude_deg: float, exaggeration: float) -> float:
    """gdaldem hillshade `-z` for a Web Mercator grid at a given latitude.

    Mercator is conformal (slope aspect is correct) but scales horizontal distance
    by 1/cos(lat), so a slope computed over grid-meters is too gentle by cos(lat).
    Scaling the vertical exaggeration by 1/cos(lat) restores the intended physical
    exaggeration (the hero's 15x) at every latitude. Shade in latitude bands, each
    band using its mid-latitude here.

    THIS HANDLES THE LATITUDE TERM ONLY, which is all Earth needs. A body whose map units are not
    ground metres — every planet but Earth, since the grid is EPSG:3857 for all of them — must also
    divide by `bodies.ground_metres_per_mercator_unit`. The streaming shader takes that as a required
    argument; this helper serves the region gdaldem branch, which is Earth by construction, so it is
    stated here rather than parameterised."""
    return exaggeration / math.cos(math.radians(latitude_deg))
