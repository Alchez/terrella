"""The look as `shade.composite` sees it — does the body's ramp actually reach the pixel.

`palette` owns which ramp a body draws with and `tests/test_palette.py` guards that. This file
guards the other half: that the answer travels. The two used to be the same question because there
was one look and the composite read the module globals directly, so nothing could tell a resolved
ramp from a hardcoded one. With a second look registered they come apart, and the interesting case
is the one Earth cannot produce — a body whose look carries NO sea ramp.

The claim under test is not "Mars renders". It is that skipping the sea is a statement about the
planet and not an optimisation: a body with no sea must composite to exactly what it would have
composited to with a sea ramp it never selects. If those two ever differ, `sea=None` has stopped
meaning "draws no sea" and started meaning "draws something else".
"""

import numpy as np
import pytest
from conftest import hillshade_for_light

from pipeline.render import palette
from pipeline.tile import shade

SHAPE = (4, 8)


def _composite(look: palette.Look, ocean: np.ndarray) -> np.ndarray:
    """One window, lit flat, with the ocean mask the caller wants to test.

    Heights are below sea level everywhere so the sea ramp has something to colour wherever the
    mask selects it — the MASK picks the ramp, never the sign, so these same pixels are ordinary
    land wherever it does not.
    """
    heights = np.full(SHAPE, -2000.0, dtype="float32")
    return shade.composite(
        heights,
        ocean,
        np.zeros(SHAPE, dtype=bool),
        np.zeros(SHAPE, dtype="float32"),
        np.full(SHAPE, hillshade_for_light(1.0), dtype="float32"),
        np.zeros((1, 1), dtype="float32"),
        (1, 1),
        SHAPE,
        look=look,
    )


#: Mars's look with a sea ramp bolted on: the SAME land ramp, differing from `MARS_LOOK` in exactly
#: one field. The comparison used to be Mars against Earth, which worked only while the two shared a
#: land `Surface` and stopped meaning anything the moment Mars took its own domain — it would have
#: been comparing two ramps and calling the difference "the sea". Varying one field is the claim.
MARS_LOOK_WITH_A_SEA = palette.Look(land=palette.MARS_LOOK.land, sea=palette.EARTH_LOOK.sea)


class TestABodyThatDrawsNoSea:
    def test_a_body_with_no_sea_ramp_composites_from_land_alone(self):
        """Skipping the sea changes nothing, which is what makes it a statement rather than a
        shortcut. With an all-False mask, a look carrying a sea ramp and the same look without one
        must agree to the byte — the sea is absent from the OUTPUT because no pixel selects it,
        not because anything downstream is behaving differently."""
        dry = np.zeros(SHAPE, dtype=bool)
        assert np.array_equal(_composite(palette.MARS_LOOK, dry),
                              _composite(MARS_LOOK_WITH_A_SEA, dry))

    def test_the_sea_ramp_reaches_the_pixel_when_there_is_an_ocean(self):
        """ANTI-VACUITY for the test above, and it is not optional.

        That equality would also hold if this fixture could never produce a sea pixel at all — a
        light model that flattened everything, a height the sea ramp clamps to the land colour, a
        mask read in the wrong orientation. Then `sea=None` would be proven equivalent to nothing.
        So: prove the mask moves the pixels before proving that it does not.
        """
        wet = np.ones(SHAPE, dtype=bool)
        assert not np.array_equal(_composite(MARS_LOOK_WITH_A_SEA, wet),
                                  _composite(MARS_LOOK_WITH_A_SEA, np.zeros(SHAPE, dtype=bool)))

    def test_a_no_sea_look_refuses_an_ocean_mask_with_pixels_set(self):
        """The look and the planet seam disagreeing about the planet is loud, not silent.

        Rendering those pixels as land would be the plausible-and-wrong outcome: a shoreline that
        simply is not there, on a planet nobody would think to check for one.
        """
        with pytest.raises(ValueError, match="no sea but the ocean mask"):
            _composite(palette.MARS_LOOK, np.ones(SHAPE, dtype=bool))
