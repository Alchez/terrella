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
    band using its mid-latitude here."""
    return exaggeration / math.cos(math.radians(latitude_deg))
