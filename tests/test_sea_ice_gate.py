"""One law with two producers: the sea-ice alpha is zero wherever there is no ocean.

WHY THIS FILE EXISTS SEPARATELY. The law spans `look/layer_producers.py` (Mercator windows) and
`tile/cap_render.py` (the AEQD disc), and a guard living inside either one would only ever be run
against the producer it sits next to. The defect it exists to prevent was exactly that shape: the
gate had one honourer, a second prep was written without it, and nothing went red.

WHY THE GATE BELONGS TO THE PRODUCER AND NOT THE CONSUMER. The alpha is spent twice in the rig --
`Mix.004 Ice` paints ice-white and `Mix.005 Ice Flatten` pulls displacement toward sea level -- so
an ungated one does not merely miscolour land, it drags the shoreline to sea level at full
exaggeration. Measured before the fix: 99.92% of the north disc's land and 100% of the south's, with
land relief cut to 0.46x. A consumer-side gate cannot protect a consumer nobody has written yet.
"""
import re

import numpy as np
import pytest

from pipeline import bodies, layers, paths
from pipeline.look import layer_producers, seaice, snow
from pipeline.tile import cap_render

ROWS, COLS = 24, 16
#: Far enough south that `_earth_sea_ice` takes its toned branch, which is the arm with two
#: `ice_alpha` calls in it and so the one where a gate is easiest to apply to only half the rows.
TOP, BOTTOM = -8_000_000.0, -9_000_000.0


def _packed() -> np.ndarray:
    """Frequencies that unpack to real alpha everywhere, so a gate has something to remove."""
    return np.linspace(4_000, 10_000, ROWS * COLS, dtype="float32").reshape(ROWS, COLS)


def _mercator_window(ocean: np.ndarray) -> layer_producers.LayerWindow:
    latitude = snow.latitude_per_row(TOP, BOTTOM, ROWS)
    return layer_producers.LayerWindow(
        raw=_packed(), watercode=np.zeros((ROWS, COLS), dtype=np.uint8),
        land=~ocean, ocean=ocean, latitude=latitude,
        ground_metres_per_px=np.full(ROWS, 300.0), top=TOP, bottom=BOTTOM)


def _checkerboard() -> np.ndarray:
    """Ocean interleaved with land, so a producer that gated on the wrong axis still fails.

    A half-and-half split passes a gate applied to the wrong hemisphere, the wrong rows or the
    wrong sign; a fine alternation does not.
    """
    row, col = np.mgrid[0:ROWS, 0:COLS]
    return ((row + col) % 2).astype(bool)


class TestEveryProducerGatesItsOwnAlpha:
    def test_the_mercator_producer_returns_nothing_off_ocean(self):
        ocean = _checkerboard()
        got = layer_producers.producer_for(bodies.EARTH, layers.SEA_ICE).contribution(
            _mercator_window(ocean))
        assert got is not None
        assert (np.asarray(got)[~ocean] == 0).all(), "alpha survived where there is no ocean"
        assert (np.asarray(got)[ocean] > 0).any(), (
            "nothing survived anywhere — a gate that zeroes everything passes the line above")

    def test_the_cap_producer_returns_nothing_off_ocean(self, monkeypatch):
        ocean = _checkerboard()
        alpha = seaice.ice_alpha(seaice.unpack_seaice(_packed()))
        # Only the warp is stubbed: the unpack, the smoothstep and the gate are the code under test.
        monkeypatch.setattr(cap_render, "_warp", lambda *a, **k: _packed())
        monkeypatch.setattr(cap_render.layers, "layer_is_buildable", lambda *a, **k: True)
        grid = cap_render.north_grid(bodies.EARTH)
        got = cap_render._cap_sea_ice(grid, ocean, "the test disc paints no pack ice")
        assert got is not None
        assert (np.asarray(got)[~ocean] == 0).all(), "alpha survived where there is no ocean"
        assert alpha.max() > 0, "the fixture produced no alpha, so the assertion above is vacuous"


class TestTheProducerSetIsComplete:
    """The two tests above name their producers, so a THIRD one is invisible to them.

    Derived rather than listed: every call site of `seaice.ice_alpha` in the pipeline is a place the
    alpha is manufactured, so counting them is how a new producer announces itself. A new one is not
    an error — it just has to be given a gate and a case above.
    """

    def test_no_producer_manufactures_the_alpha_outside_the_two_gated_ones(self):
        sites: dict[str, int] = {}
        for module in sorted((paths.ROOT / "pipeline").rglob("*.py")):
            source = re.sub(r"#.*", "", module.read_text())
            found = len(re.findall(r"\bice_alpha\(", source))
            if found and module.name != "seaice.py":
                sites[str(module.relative_to(paths.ROOT))] = found
        assert sites == {"pipeline/look/layer_producers.py": 2,
                         "pipeline/tile/cap_render.py": 1}, (
            f"the alpha is manufactured somewhere this file does not gate: {sites}")


class TestTheConsumersNoLongerGate:
    """`shade.composite` used to gate for its own paint, which is what let the cap free-ride.

    Kept as a test rather than a deletion note: a consumer-side gate reappearing is not a bug on its
    own, but it silently restores the world where a producer can ship an ungated alpha and only the
    consumers that happen to gate are safe.

    ASKED OF THE PACKAGE RATHER THAN OF ONE FILE. It used to read `tile/shade.py`, the module that
    held `composite` -- which has since lost that function and then been deleted outright, so the
    guard was reading a lake ramp and passing for want of anything to find. A consumer that regates
    would not have put itself back in that file, and now it does not have to.
    """

    def test_no_consumer_regates_what_it_is_handed(self):
        regating = sorted(
            str(module.relative_to(paths.ROOT))
            for module in (paths.ROOT / "pipeline").rglob("*.py")
            if "np.where(ocean, np.asarray(ice_a"
            in re.sub(r"#.*", "", module.read_text(encoding="utf-8"))
        )
        assert not regating, (
            f"a consumer is gating the alpha again in {regating}; the producers own that now")


@pytest.mark.parametrize("empty", [np.zeros((ROWS, COLS)), np.zeros((ROWS, COLS), dtype=bool)])
def test_an_alpha_with_no_ocean_under_it_comes_back_as_none(empty):
    """None and not zeros, because that is what decides whether a mask is written and painted.

    the painter skips the blend entirely on None where a zero array would run it and multiply
    the disc by nothing, and `prep_block` uses it to decide whether the layer exists at all here.
    """
    assert seaice.gated_alpha(np.ones((ROWS, COLS)), np.asarray(empty, dtype=bool)) is None


def test_ice_over_ocean_survives_the_gate_at_full_value():
    """The positive half. Without it, a gate that zeroed everything would pass every case above."""
    ocean = np.zeros((ROWS, COLS), dtype=bool)
    ocean[:, : COLS // 2] = True
    gated = seaice.gated_alpha(np.full((ROWS, COLS), 0.85), ocean)
    assert gated is not None
    assert gated[:, : COLS // 2].min() == 0.85
    assert not gated[:, COLS // 2:].any()


def test_no_contribution_at_all_reads_as_nothing_to_write():
    assert seaice.gated_alpha(None, np.ones((ROWS, COLS), dtype=bool)) is None
