"""How far exaggerated relief throws a shadow, which is what sizes a block's context.

WHAT THIS MODULE IS NOW IS ONE FORMULA. It used to render directional cast shadows for the raster
path as well, supplying the one light term a hillshade structurally cannot produce: `gdaldem
hillshade` sees one pixel's slope and aspect and nothing else, so it cannot know that a ridge 40 km
upsun is blocking the light. Cycles knows, because it traces the ray, and that is now the only way
a Terrella pixel gets a cast shadow.

`shadow_mask` AND `sun_offsets` WERE DELETED AND MUST NOT COME BACK, and the reason is a rejection
rather than a tidy. Their only caller was `look/hillshade.py`, the compositor's last leaf. The
mechanism was refused twice before that: attenuating the main sun scales light amplitude, and fine
detail amplitude falls with it, so such a shadow erases the modelling it carries. CLAUDE.md records
that reopening needs a different mechanism, not a different number, and
`test_bodies.TestTheCompositePlanetProducerIsDeletedAndCannotReturn` refuses their return.

ONE HALF OF A TWO-ARM LAW WENT WITH THEM, and the surviving arm is the rig's. The penumbra had to
read `palette.SUN_ANGULAR_DIAMETER_DEG` rather than hold a local copy, and a mutation case planted
that local copy here. The same law binds `scene_build`, where its own case still guards it, so the
law is intact with one arm rather than two.
"""

import math


def shadow_reach_px(max_relief_m: float, zfactor: float, m_per_px: float,
                    altitude: float = 45.0) -> float:
    """Longest shadow, in pixels, that `max_relief_m` of exaggerated relief can cast.

    The sizing oracle for `reach_px`: relief of h metres exaggerated by z stands z*h high and, at a
    sun altitude a, lays its shadow z*h/tan(a) metres along the ground. Kept here rather than done
    by hand at the call site because getting it wrong truncates shadows silently — they simply stop,
    with no error and no visible edge to notice.

    THIS IS THE LIVE HALF OF THE MODULE and `block_plan` is its only caller: it sizes every block's
    context, so an error here narrows what Cycles can see rather than changing a shading term.
    """
    return zfactor * max_relief_m / math.tan(math.radians(altitude)) / m_per_px
