"""Shared oracles for the composite tests."""

import math

from pipeline.tile import shade


def hillshade_for_light(light: float) -> float:
    """The hillshade DN whose post-`apply_ambient_floor` light is exactly `light`.

    A test that wants a pixel to land on a known light used to write `flat * light`,
    because the ambient floor was a `np.clip` and therefore an identity everywhere above
    `ambient`. Since `ambient_knee` went to 0.30 (2026-07-21) the floor is a softplus,
    which sits strictly ABOVE its input -- about +5% at the top of the range, enough to
    push a lake off `WATER_RGB` and to shove the snow window's upper end into saturation
    where a curve knob can no longer move it. Both read as the knob being broken.

    Inverting the floor analytically keeps those tests pinned to their stated intent under
    any future `ambient` / `ambient_knee`, instead of re-tuning constants each time.
    """
    flat = 255.0 * math.sin(math.radians(shade.KNOBS["alt"]))
    ambient, knee = shade.KNOBS["ambient"], shade.KNOBS["ambient_knee"]
    if knee <= 0.0:
        return flat * light
    if light <= ambient:
        raise ValueError(f"light {light} is at or below the ambient floor {ambient}; "
                         "the softplus never reaches it, so no hillshade DN produces it")
    return flat * (ambient + knee * math.log(math.expm1((light - ambient) / knee)))
