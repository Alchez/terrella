"""How far exaggerated relief throws a shadow, which is what sizes a block's context.

One formula. Nothing here shades anything: Cycles traces the ray, so that is where a Terrella pixel
gets its cast shadow.

Do not add a numpy cast-shadow term back. The temptation is well founded, since a hillshade sees one
pixel's slope and aspect and cannot know a ridge 40 km upsun blocks the light; `shadow_mask` and
`sun_offsets` stood here to supply it. The mechanism is what fails, not the tuning: attenuating the
main sun scales light amplitude, and fine detail falls with it, so the shadow erases the modelling
it carries. Refused twice, the second time on the mechanism, so a better number is not a way back
in. `test_bodies.TestTheCompositePlanetProducerIsDeletedAndCannotReturn` holds them out.
"""

import math


def shadow_reach_px(max_relief_m: float, zfactor: float, m_per_px: float,
                    altitude: float = 45.0) -> float:
    """Longest shadow, in pixels, that `max_relief_m` of exaggerated relief can cast.

    The sizing oracle for `reach_px`: relief of h metres exaggerated by z stands z*h high and, at a
    sun altitude a, lays its shadow z*h/tan(a) metres along the ground. Kept here rather than done
    by hand at the call site because getting it wrong truncates shadows silently — they simply stop,
    with no error and no visible edge to notice. It sizes a block's context, so an error narrows
    what Cycles can see rather than changing a shading term.
    """
    return zfactor * max_relief_m / math.tan(math.radians(altitude)) / m_per_px
