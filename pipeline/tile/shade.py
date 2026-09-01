"""The lake ramp's curve, and the two paths the planet grid is spelled from.

THIS MODULE NO LONGER SHADES ANYTHING, AND ITS NAME IS ITEM 9's SUBJECT. It held `composite`, the
per-pixel numpy shader every composited pixel went through, and a `--cells` region preview that ran
it over a few Copernicus chunks. Both went with the composite planet producer: every planet is
raytraced, so the shader had no caller and the preview produced a look no body ships.

WHAT IS LEFT HAS READERS. `render/lake_mask.py` reads `LAKE_CURVE` and passes it to `lake_position`,
both on the HERO path, which is a different lane from the tiles entirely. `Z8_MERC_RES` is read by a
resolution test, and `DATA`/`CHUNKS` by the path guards.

`Knobs`, `KNOBS` and `SHADOW_TINT` WERE PRUNED AND MUST NOT COME BACK. They were the deleted
shader's tunables, and the only thing that ever recorded them was `composite_params`, so once that
went they reached no pixel and no recipe. A constant in that state is worse than absent: it reads as
a lever, and a re-tune of one would have restaged nothing and changed nothing.
`test_bodies.TestTheCompositePlanetProducerIsDeletedAndCannotReturn` refuses them, and ART.md holds
what each value was and how it was chosen, which is the half worth keeping.
"""

import math

import numpy as np

from pipeline import paths
from pipeline.look import palette

DATA = paths.DATA
CHUNKS = DATA / "work/planet/chunks"
Z8_MERC_RES = 305.7483  # metres/pixel of a 512px WebMercatorQuad tile at zoom 8

#: Depth-to-ramp-position mapping for inland water, and the one survivor of the shader's knobs.
#:
#: It outlived them because the HERO reads it: `render/lake_mask.py` bakes this curve into the mask
#: Blender displaces from, so hero and tile cannot disagree about it. It was `KNOBS["lake_curve"]`
#: while that dict existed, and it is a bare constant now rather than a one-key dict, since the
#: TypedDict existed only to type a str sitting among fifteen floats.
LAKE_CURVE = "log1p"


def lake_position(depth, curve):
    """Lake depth (m below surface) -> 0..1 along the lake ramp.

    This curve is the honesty/legibility dial, and the two pull against each other. The median
    lake is 11.2 m deep while Baikal is 1642 -- three orders of magnitude -- so a LINEAR axis
    parks 99% of lakes in the first 2% of the ramp and shows nothing. LOG1P spreads them
    (median -> 0.34) but hands most of the ramp to shallow water, which is exactly where
    GLOBathy's cone is least trustworthy (on the Caspian it claims 155 m where the truth is
    under 20 m, measured), so it also maximises the visibility of the layer's worst
    error. SQRT (median -> 0.08) is the conservative middle. Judge on renders, not in the
    abstract.
    """
    if curve == "log1p":
        # Clamped like the others: LAKE_MAX_M is Baikal, so nothing should exceed it today,
        # but an unclamped log1p returns >1 for anything that does -- one re-tune of
        # LAKE_MAX_M to a shallower cap away from indexing off the end of the ramp.
        return (np.log1p(np.clip(depth, 0.0, palette.LAKE_MAX_M))
                / math.log1p(palette.LAKE_MAX_M))
    if curve == "sqrt":
        return np.sqrt(np.clip(depth, 0.0, palette.LAKE_MAX_M) / palette.LAKE_MAX_M)
    if curve == "linear":
        return np.clip(depth, 0.0, palette.LAKE_MAX_M) / palette.LAKE_MAX_M
    raise ValueError(f"unknown LAKE_CURVE {curve!r} (log1p | sqrt | linear)")
