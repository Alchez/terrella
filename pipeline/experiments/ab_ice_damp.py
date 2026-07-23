"""A/B ladder for `ice_relief_damp`: render the polar caps at several damping strengths.

Each rung renders the full cap through the production composite (the "fast browser-free
pole-look loop", ~21 s a cap) and copies the PNG to data/work/cap/ab_ice_damp/ for
full-scale side-by-side judging. The rungs run strongest-first and end at 0.0 — today's
look — so the served dev-assets PNGs are left restored.

Run: python -m pipeline.experiments.ab_ice_damp
"""

import shutil
from typing import Any, cast

from pipeline.tile import cap_render, shade

NORTH_RUNGS = [1.0, 0.75, 0.5, 0.0]  # the pole that prompted the knob gets the full ladder
SOUTH_RUNGS = [1.0, 0.0]             # the shared-code side effect only needs a bracket


def main() -> None:
    ladder_dir = cap_render.WORK / "ab_ice_damp"
    ladder_dir.mkdir(parents=True, exist_ok=True)
    knobs = cast(dict[str, Any], shade.KNOBS)
    for strength, renderer, cap_name in (
            [(value, cap_render.render_cap_north, "north") for value in NORTH_RUNGS]
            + [(value, cap_render.render_cap_south, "south") for value in SOUTH_RUNGS]):
        knobs["ice_relief_damp"] = strength
        rendered_png = renderer()
        rung_png = ladder_dir / f"cap_{cap_name}_damp_{strength:.2f}.png"
        shutil.copyfile(rendered_png, rung_png)
        print(f"{cap_name} damp {strength:.2f} -> {rung_png}", flush=True)


if __name__ == "__main__":
    main()
