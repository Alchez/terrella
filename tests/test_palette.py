"""Tests for the shared hypsometric palette — the single source of truth for the
land/sea color ramps used by both the Cycles heroes and the raster tile shading.

The load-bearing test is `test_color_relief_matches_locked_hero_hex`: an independent
oracle — the frozen hex values transcribed below — that fails loudly if the linear ramp stops ever
drift off the approved hero look.

THIS FILE IS THE ORACLE, not a copy of one. The values were transcribed from the living plan's
locked-constants section, which is kept outside the repository, so nothing a reader can reach holds
them independently of `palette.py` itself. That is the point: an oracle stored beside the code it
checks is no oracle at all, and these literals are deliberately hand-written rather than derived.
Changing one means re-rendering every hero. See ART.md for the look decisions behind them.

WHAT THIS ORACLE CAN NO LONGER SEE. "The approved hero look" meant these stops encoded to these
hexes because the rig's view transform was a plain sRGB encode, exactly like `_srgb8`. It is
`Khronos PBR Neutral` now, so the equality below is a claim about the COMPOSITE path alone and the
hero it is named for renders them darker. Every assertion here still passes and none of them is
about the rig any more; re-freezing them is a look decision, not a test repair.
"""

import dataclasses
import hashlib
import re
from pathlib import Path

import pytest

from pipeline import bodies
from pipeline.look import palette

REPO_ROOT = Path(__file__).resolve().parents[1]


def _hex(code: str) -> tuple[int, int, int]:
    return (int(code[0:2], 16), int(code[2:4], 16), int(code[4:6], 16))


# The frozen hero ramp endpoints. Hand-transcribed on purpose — deriving them from `palette.py`
# would make this test tautological. See ART.md § Lever index for what each one costs to move.
LAND_COAST = _hex("E9D9C0")   # land ramp @ 0 m
LAND_PEAK = _hex("E9DCC8")    # land ramp @ 6000 m
SEA_SHALLOW = _hex("85B9B7")  # sea ramp @ 0 m (shallowest; deepened ~15% from 8FC7C5)
SEA_DEEP = _hex("3A6E7D")     # sea ramp @ -6000 m (deepest; depth extended from -3000)


def _shipped_by(body: bodies.Body, channels: tuple[int, int, int], kind: str) -> tuple[int, ...]:
    """The 8-bit colour `body` actually paints an authored ramp stop, chosen by its producer.

    THE DISPATCH IS THE POINT AND THE ARITHMETIC IS BORROWED. `raytrace` builds its ramps straight
    from the authored stops, so the stop IS the shipped colour; `composite` puts it through
    `shade.composited_chroma` first. Reading that transform from `shade` rather than restating it
    is deliberate: it had two spellings before this file needed a third, and a retune of either
    knob has to reach every reader.
    """
    from pipeline.tile import shade

    if body.planet_producer == "raytrace":
        return tuple(channels)
    if body.planet_producer == "composite":
        return tuple(round(float(value))
                     for value in shade.composited_chroma(channels, kind))
    raise AssertionError(
        f"{body.name} names producer {body.planet_producer!r}, which this oracle has no arm for. "
        f"A new producer draws the ramp its own way and must be transcribed here, not defaulted."
    )


class TestScalarHelpers:
    def test_smoothstep_endpoints_and_midpoint(self):
        assert palette.smoothstep(0.0) == 0.0
        assert palette.smoothstep(1.0) == 1.0
        assert palette.smoothstep(0.5) == pytest.approx(0.5)

    def test_smoothstep_is_monotonic(self):
        samples = [palette.smoothstep(i / 10) for i in range(11)]
        assert samples == sorted(samples)

    def test_lin2srgb_endpoints(self):
        assert palette.lin2srgb(0.0) == pytest.approx(0.0)
        assert palette.lin2srgb(1.0) == pytest.approx(1.0)

    def test_lin2srgb_known_midpoint(self):
        # linear 0.5 encodes to ~0.735 in sRGB
        assert palette.lin2srgb(0.5) == pytest.approx(0.7353569, abs=1e-6)

    def test_lin2srgb_clamps(self):
        assert palette.lin2srgb(-0.2) == pytest.approx(0.0)
        assert palette.lin2srgb(1.5) == pytest.approx(1.0)


class TestRampColor:
    @pytest.mark.parametrize("stops_name", ["LAND_STOPS", "SEA_STOPS"])
    def test_returns_exact_color_at_each_stop(self, stops_name):
        stops = getattr(palette, stops_name)
        for pos, color in stops:
            assert palette.ramp_color(pos, stops) == pytest.approx(color)

    def test_interpolates_between_stops(self):
        # halfway (in position) between two land stops must lie strictly between them
        (p0, c0), (p1, c1) = palette.LAND_STOPS[0], palette.LAND_STOPS[1]
        mid = palette.ramp_color((p0 + p1) / 2, palette.LAND_STOPS)
        for channel in range(3):
            lo, hi = sorted((c0[channel], c1[channel]))
            assert lo <= mid[channel] <= hi

    def test_clamps_below_and_above_range(self):
        assert palette.ramp_color(-1.0, palette.SEA_STOPS) == pytest.approx(palette.SEA_STOPS[0][1])
        assert palette.ramp_color(2.0, palette.SEA_STOPS) == pytest.approx(palette.SEA_STOPS[-1][1])


class TestColorRelief:
    def test_land_rows_span_zero_to_max(self):
        rows = palette.color_relief_rows("land", look=palette.EARTH_LOOK)
        assert rows[0][0] == 0.0
        assert rows[-1][0] == pytest.approx(palette.LAND_MAX_M)

    def test_sea_rows_span_min_to_zero(self):
        rows = palette.color_relief_rows("sea", look=palette.EARTH_LOOK)
        assert rows[0][0] == pytest.approx(palette.SEA_MIN_M)
        assert rows[-1][0] == 0.0

    def test_elevations_are_monotonic(self):
        for kind in ("land", "sea"):
            elevs = [elev for elev, _ in palette.color_relief_rows(kind, look=palette.EARTH_LOOK)]
            assert elevs == sorted(elevs)

    def test_color_relief_matches_locked_hero_hex(self):
        """Independent oracle: generated endpoints == the frozen hex transcribed in this file."""
        land = palette.color_relief_rows("land", look=palette.EARTH_LOOK)
        sea = palette.color_relief_rows("sea", look=palette.EARTH_LOOK)
        assert land[0][1] == LAND_COAST
        assert land[-1][1] == LAND_PEAK
        assert sea[-1][1] == SEA_SHALLOW   # shallowest is at elevation 0 (last sea row)
        assert sea[0][1] == SEA_DEEP       # deepest is at -6000 (first sea row)


class TestSharedConstants:
    """The relational pins that stop the copy-drift class of bug (the sea-sync).

    WATER_RGB went stale against SEA_STOPS[0] once on the tiles and once
    on the heroes (98C5C8) because nothing tied the tint to the sea
    surface. These freeze the value AND the relationship."""

    def test_water_rgb_exact(self):
        assert palette.WATER_RGB == (142, 198, 196)  # 8EC6C4

    def test_water_rgb_is_sea_surface_lightened(self):
        """The lake convention: the sea surface tone lightened ~7%. A ramp rework that
        moves SEA_STOPS[0] and forgets the flat tint fails here, not on a render."""
        surface = palette._srgb8(palette.SEA_STOPS[0][1])
        assert surface == SEA_SHALLOW  # the frozen 85B9B7 anchor
        for tint_channel, surface_channel in zip(palette.WATER_RGB, surface):
            assert abs(tint_channel - round(surface_channel * 1.07)) <= 1

    def test_lake_shore_is_the_flat_tint(self):
        assert palette.LAKE_STOPS[0][1] == palette.srgb8_to_linear(palette.WATER_RGB)

    def test_sun_altitude_is_shared(self):
        """Tile KNOBS["alt"] sources palette.SUN_ALT_DEG; the hero derives its
        SUN_ROTATION X-tilt from the same constant (test_scene_build_sync)."""
        from pipeline.tile import shade

        assert palette.SUN_ALT_DEG == 45.0
        assert shade.KNOBS["alt"] == palette.SUN_ALT_DEG

    def test_exaggeration_is_shared(self):
        """The region shader sources palette.EXAGGERATION.

        TWO legs have left this test and both for the same reason, which is worth stating once: a
        path that draws more than one body takes its exaggeration from `Body.exaggeration`, and
        `test_bodies.py` pins Earth's field against this constant. The planet leg went first. The
        render leg followed when `scene_numbers` stopped importing this constant — it is the block
        prep's seam as well as the hero path's, so importing Earth's 15x gave a Mars block two
        thirds of its displacement with nothing to notice. `test_render_prep.py` now guards it.

        What remains is the region path, and it is not a downgrade — `shade.EXAG` was a THIRD
        literal 15.0 that this guard's own docstring called "the last copy-pair", and no test named
        it. The region path exists to predict the planet, so a look value it holds privately is
        drift by construction.
        """
        from pipeline.tile import shade

        assert palette.EXAGGERATION == 15.0
        assert shade.EXAG == palette.EXAGGERATION

    def test_web_palette_matches_the_ramp_it_copies(self):
        """web/src/lib/palette.ts restates pipeline colours for the browser, which cannot
        import Python. This recomputes each one through _srgb8 and fails on drift — the
        same class of bug WATER_RGB hit twice, in the one place an import cannot reach.

        Adding a colour to that file means adding its stop here in the same edit."""
        web_palette = (REPO_ROOT / "web/src/lib/palette.ts").read_text()

        # name in the TS file -> the ramp stop it encodes
        derived = {
            "DEEP_SEA": palette.SEA_STOPS[4][1],                 # -3800 m, Earth's space-floor
            "TRENCH_FLOOR": palette.SEA_STOPS[5][1],             # -6000 m, Earth's light accent
            "MARS_MODAL_GROUND": palette.MARS_LAND_STOPS[3][1],  #  +655 m, Mars's space-floor
        }
        for name, linear in derived.items():
            red, green, blue = palette._srgb8(linear)
            expected = f'export const {name} = "#{red:02X}{green:02X}{blue:02X}";'
            assert expected in web_palette, (
                f"web/src/lib/palette.ts must declare {name} as "
                f"#{red:02X}{green:02X}{blue:02X} — the palette moved, the copy did not"
            )

    def test_web_mars_ramp_matches_what_mars_actually_ships(self):
        """`MARS_RAMP` in the web palette is what the About page's legend is drawn from, and it
        must be the colour the TILES carry rather than the colour the stops are authored as.

        KEYED ON THE PRODUCER, WHICH IS THE WHOLE REPAIR. This test used to spell the composite's
        chroma chain inline and assert it unconditionally, under the name
        `..._matches_the_composited_stops`. That was right while Mars composited and became the
        defect the day it did not: the legend kept the composited stops, Mars's tiles started
        carrying the authored ones, and the guard that should have caught a 16 DN gap was the thing
        holding it open. A pin written against one producer's answer does not fail when the
        producer changes — it keeps passing, and its subject silently becomes wrong.

        A SECOND DERIVATION, NOT A SECOND COPY OF THE ONE ABOVE. Everything in `derived` there is
        `_srgb8(stop)` and nothing more, because those constants back flat fills that no compositor
        touches. A ramp stop reaches a visitor through whichever producer drew the tiles.

        DERIVED ON PURPOSE, unlike `TestTheShippedTileColourIsPinnedToItsProducer` below. The TS
        file is a COPY of a value `palette.py` owns, so the useful question is whether the copy
        drifted, and deriving is what makes that answerable across a language boundary. The hex
        table down there answers the different question of whether the value itself moved, which is
        why it is hand-transcribed and this is not.

        The light term is deliberately absent from both this and the file it checks: a pixel is
        multiplied by a hillshade that varies per pixel, so there is no single value a swatch could
        carry. `palette.py` annotating stop 0 as shipping `#804D35` is a reading off flat lit
        ground and is not what a legend states.

        This fails if the stops move, if Mars's producer moves, or if either knob moves while the
        composite is the producer — the same retune that changes the map has to change the key.
        """
        web_palette = (REPO_ROOT / "web/src/lib/palette.ts").read_text()

        for position, linear in palette.MARS_LAND_STOPS:
            shipped = _shipped_by(bodies.MARS, palette._srgb8(linear), "land")
            expected = f'hex: "#{shipped[0]:02X}{shipped[1]:02X}{shipped[2]:02X}"'
            assert expected in web_palette, (
                f"web/src/lib/palette.ts MARS_RAMP must carry {expected} for the stop at "
                f"{position} — the ramp or a shade knob moved and the legend did not follow"
            )

        declared = re.findall(r"\{ at: ([0-9.]+), hex:", web_palette)
        assert [float(value) for value in declared] == [
            position for position, _ in palette.MARS_LAND_STOPS
        ], (
            "MARS_RAMP's positions must match MARS_LAND_STOPS exactly — a legend whose stops sit "
            "at different fractions than the ramp's draws the right colours in the wrong places"
        )


class TestWriteColorRelief:
    def test_writes_gdaldem_format_with_nodata(self, tmp_path):
        out = tmp_path / "ramp_land.txt"
        palette.write_color_relief(out, "land", look=palette.EARTH_LOOK)
        lines = out.read_text().splitlines()
        assert lines[-1] == "nv 0 0 0"
        first = lines[0].split()
        assert len(first) == 4                       # elevation R G B
        assert first[0] == "0.00"
        assert all(0 <= int(v) <= 255 for v in first[1:])


class TestTheLookIsByteStable:
    """Golden hashes over every artefact the ramps produce.

    WHY A HASH WHEN THE TESTS ABOVE ALREADY CHECK THE RAMPS. They check PROPERTIES — the stops are
    hit exactly, the sea darkens monotonically, the LUT agrees with the gdaldem rows within 1 DN.
    Every one of those can hold while the output still moves, because they each look at a handful of
    the 6,001 entries. These say the opposite thing: nothing at all moved, anywhere.

    THIS IS THE ORACLE FOR A REFACTOR WHOSE CONTRACT IS "NOTHING CHANGES". A restructuring of how the
    ramps are looked up must leave every byte identical, and no property test can promise that. It is
    also the thing that makes a deliberate look change visible: these hashes are meant to be updated
    in the same commit that moves a colour, and a diff that changes a ramp without touching them is
    a diff whose author did not know what they changed.

    The readable anchors live in the classes above, so a failure here is diagnosed there rather than
    from the hash — an opaque digest is a good ratchet and a poor error message.
    """

    @staticmethod
    def _digest(payload: bytes) -> str:
        return hashlib.sha256(payload).hexdigest()[:16]

    @pytest.mark.parametrize(
        "kind,expected",
        [("land", "c2137fc21d35aaf5"), ("sea", "3318a6ec1e793420")],
    )
    def test_gdaldem_ramp_text_is_unchanged(self, kind, expected):
        assert self._digest(palette.color_relief_text(kind, look=palette.EARTH_LOOK).encode()) == expected

    @pytest.mark.parametrize(
        "kind,expected",
        [("land", "2981572a5c8865f4"), ("sea", "6839535a4a018129")],
    )
    def test_relief_lut_bytes_are_unchanged(self, kind, expected):
        lut = palette.relief_lut(kind, look=palette.EARTH_LOOK)
        # Shape is part of the artefact: a (3, N) that quietly became (N, 3) would hash differently
        # but so would a genuinely different ramp, and only one of those is a transpose bug.
        assert lut.shape == (3, 6001)
        assert self._digest(lut.tobytes()) == expected

    def test_lake_lut_is_unchanged(self):
        flat = bytes(channel for colour in palette.lake_lut() for channel in colour)
        assert self._digest(flat) == "f5395a2466878b91"


# What each registered body's TILES are painted in today, hand-transcribed, every stop of every
# ramp its look declares. Mars has no sea, so it has no sea row and that is a statement.
#
# HAND-WRITTEN FOR THE SAME REASON `LAND_COAST` IS: deriving these from `palette.py` and `shade.py`
# would make the guard tautological. Unlike `TestTheLookIsByteStable` above, which hashes the LUT
# and so can only say that nothing moved, this says WHOSE answer the ramp is currently giving.
SHIPPED_TILE_HEX: dict[str, dict[str, list[str]]] = {
    "earth": {
        "land": ["E9D9C0", "D7AC8E", "CE9880", "C9AD97", "DCC9B2", "E9DCC8"],
        "sea": ["85B9B7", "73ABAB", "68A6AC", "56939E", "47808F", "3A6E7D"],
    },
    "mars": {"land": ["784F3C", "8F5F49", "AC7351", "BE885E", "CBA378", "D4BF9D"]},
}

# The same stops under the COMPOSITE. Nothing ships these today — both bodies raytrace — and that
# is exactly why they are written down: an arm with no registered body selecting it is dead code
# the moment it is written, and a dead arm cannot catch the flip back.
COMPOSITED_TILE_HEX: dict[str, dict[str, list[str]]] = {
    "earth": {
        "land": ["ECD2B0", "DDA57F", "D59172", "CDA789", "DFC2A3", "EBD5B8"],
        "sea": ["89B7B6", "77A9A9", "6CA4AA", "5A919B", "4B7E8C", "3E6D7A"],
    },
    "mars": {"land": ["7E4B33", "965A3F", "B46D44", "C6824F", "D19D68", "D7B98D"]},
}


class TestTheShippedTileColourIsPinnedToItsProducer:
    """The tile colour each body actually paints, pinned to the producer that paints it.

    THE GAP THIS CLOSES, AND IT WAS OPEN BEFORE THE RAYTRACE SWITCH RATHER THAN OPENED BY IT.
    `shade.composite` resaturates land by `saturation` 1.18 and warms it by `warmth` 0.06, and
    `scene_build` applies neither — so which producer draws a body's planet raster moves every land
    pixel by up to 16 DN. Nothing connected that to a test. Earth's ramp is pinned to the HERO hex
    (`test_color_relief_matches_locked_hero_hex`) and the composited hexes appeared nowhere in the
    tree at all, so `planet_producer` could be flipped in either direction, the whole site's land
    colour would move, and every gate would stay green.

    KEYED ON THE BODY, NOT ON THE PRODUCER, WHICH IS THE DIFFERENCE BETWEEN A GUARD AND A LOOKUP.
    A table keyed on the producer would answer a flip by selecting a different row and passing —
    the exact vacuity that let the About page's Mars legend hold a 16 DN error while its own guard
    stayed green. `SHIPPED_TILE_HEX` says what earth paints, full stop; `_shipped_by` derives that
    through `body.planet_producer`; and a flip therefore contradicts the table.

    NOT A LOOK CALL AND NEVER WAS. The 16 DN was carried by every A/B of the judging set (its
    composite arm was cut from the shipped raster, its raytrace arm from the rig), so Rohan
    ratified raytracing everywhere off exactly that difference. A guard needs no ratification;
    what it buys is that the next move of it is deliberate.
    """

    @staticmethod
    def _stops(body: bodies.Body, kind: str):
        """THIS BODY'S own stops, resolved through the look registry.

        Reaching for `palette.LAND_STOPS` here instead is the exact bug the registry exists to
        stop — it is EARTH's ramp under a name that does not say so, and it silently hands Mars
        Earth's colours. It did, on the first run of this class.
        """
        surface = getattr(palette.look_for(body.name), kind)
        assert surface is not None, f"{body.name} draws no {kind}, so it has no stops to pin"
        return surface.stops

    @pytest.mark.parametrize("body_name", sorted(SHIPPED_TILE_HEX))
    def test_a_registered_body_paints_the_transcribed_colour(self, body_name):
        """The pin. Goes red if a stop moves, if a knob the live producer reads moves, or if
        `planet_producer` flips — which is the case no other test in the repo can see."""
        body = bodies.BODIES[body_name]
        for kind, expected in SHIPPED_TILE_HEX[body_name].items():
            stops = self._stops(body, kind)
            assert len(stops) == len(expected), (
                f"{body_name}'s {kind} ramp has {len(stops)} stops against {len(expected)} "
                f"transcribed — a stop was added or removed and the oracle did not follow"
            )
            for (position, linear), want in zip(stops, expected, strict=True):
                shipped = _shipped_by(body, palette._srgb8(linear), kind)
                assert shipped == _hex(want), (
                    f"{body_name} paints its {kind} stop at {position} as "
                    f"#{shipped[0]:02X}{shipped[1]:02X}{shipped[2]:02X}, transcribed as #{want}. "
                    f"{body_name}'s producer is {body.planet_producer!r}."
                )

    @pytest.mark.parametrize("body_name", sorted(COMPOSITED_TILE_HEX))
    def test_the_composite_arm_answers_on_a_synthetic_body(self, body_name):
        """The composite arm, kept alive by a body constructed for it rather than borrowed.

        `dataclasses.replace` and not a registered body, because there is no longer a composited
        one: both answer `"raytrace"`. This is the route the three guards the producer flip turned
        red were repaired onto, and it is what stops this arm rotting into an unreachable branch.
        """
        body = dataclasses.replace(bodies.BODIES[body_name], planet_producer="composite")
        for kind, expected in COMPOSITED_TILE_HEX[body_name].items():
            for (position, linear), want in zip(self._stops(body, kind), expected, strict=True):
                shipped = _shipped_by(body, palette._srgb8(linear), kind)
                assert shipped == _hex(want), (
                    f"the composite arm paints {body_name}'s {kind} stop at {position} as "
                    f"#{shipped[0]:02X}{shipped[1]:02X}{shipped[2]:02X}, transcribed as #{want}"
                )

    def test_the_two_arms_disagree_at_every_land_stop(self):
        """ANTI-VACUITY, and it is the assertion the whole class rests on.

        If the two producers happened to agree, the pin above would pass under either and could not
        detect a flip — green, and blind to the thing it exists for. Measured rather than asserted
        loosely: the land gap is 14 to 16 DN in blue at every stop, which is the number the switch
        was priced at. The sea is deliberately NOT in this check, because its own gap is 1 to 3 DN
        and a threshold that covers both would be too weak to mean anything on land.
        """
        for body_name, shipped in SHIPPED_TILE_HEX.items():
            for live, composited in zip(shipped["land"],
                                        COMPOSITED_TILE_HEX[body_name]["land"], strict=True):
                gap = max(abs(a - b) for a, b in zip(_hex(live), _hex(composited), strict=True))
                assert gap >= 9, (
                    f"{body_name}'s producers agree to within {gap} DN at a land stop "
                    f"(#{live} against #{composited}), so the pin above cannot see a flip"
                )

    def test_an_unknown_producer_is_refused_rather_than_defaulted(self):
        """A third producer must not inherit an arm. Defaulting would paint a planet in whichever
        arm was listed first and pass, which is the failure mode `planet_seam` calls absence not
        being a statement."""
        invented = dataclasses.replace(bodies.EARTH, planet_producer="airbrush")  # type: ignore[arg-type]
        with pytest.raises(AssertionError, match="no arm for"):
            _shipped_by(invented, (1, 2, 3), "land")

    def test_every_body_the_site_ships_is_transcribed(self):
        """Derived, not policed: a new planet must join the table or fail here. The reverse
        direction matters as much — a row for a body that no longer exists is an oracle nothing
        checks, and it would sit green forever."""
        assert set(SHIPPED_TILE_HEX) == set(bodies.BODIES)
        assert set(COMPOSITED_TILE_HEX) == set(bodies.BODIES)


class TestTheLookRegistry:
    """A second look exists, so the seam that was written for one is now load-bearing.

    Every test here is unreachable while Earth is the only planet: with one look, resolving it is
    the same operation as reading the globals, and a mutation that breaks the resolution still
    produces Earth's ramp. The registry is what makes the wrong answer expressible, which is what
    makes these guards able to fail.
    """

    def test_every_registered_body_has_a_look(self):
        """The parity guard, and the reason the two registries are allowed to be separate.

        `pipeline/bodies.py` opens by saying a body is "not a look", so colour lives here instead
        of on the descriptor. The cost of that separation is that adding a planet now means two
        edits, and forgetting the second is the failure that RENDERS rather than raises — a whole
        pyramid in Earth's ramp, every gate green. Nothing but this test spans the two.
        """
        missing = sorted(set(bodies.BODIES) - set(palette.LOOK_BY_BODY))
        assert not missing, (
            f"registered bodies with no look: {missing}. Add an entry to palette.LOOK_BY_BODY — a "
            "body that cannot resolve a look must not be able to reach the shading path at all."
        )

    def test_an_unregistered_body_gets_no_look_at_all(self):
        """No fallback, for the reason `bodies.get` has none: the fallback renders.

        A wrong ramp does not raise, does not warp, and does not look broken in a thumbnail. It
        produces a planet that is internally consistent and belongs to somebody else.
        """
        with pytest.raises(KeyError, match="no look registered"):
            palette.look_for("venus")

    def test_earth_and_mars_resolve_to_different_looks(self):
        """Anti-vacuity for everything above. Two names mapping to one object would pass every
        other test in this class while proving nothing about the seam."""
        assert palette.look_for("earth") is palette.EARTH_LOOK
        assert palette.look_for("mars") is palette.MARS_LOOK
        assert palette.MARS_LOOK is not palette.EARTH_LOOK

    def test_mars_draws_its_own_colours_and_no_longer_borrows_earths(self):
        """Mars's ramp is authored for Mars, and the two bodies share no colour object at all.

        THIS REPLACES A GUARD THAT PINNED THE OPPOSITE, which is the point. While Mars had no
        ratified look it drew Earth's `stops` LIST — shared by identity, so a re-tune of Earth's
        ramp provably dragged Mars along and the borrowing could not silently stop being true. That
        promise has been kept and is now spent: Mars has its own colours, so what needs guarding
        flips to the negative, and re-establishing the sharing must fail rather than pass quietly.

        Identity is asserted in BOTH directions because the failure modes differ. Sharing the list
        object again would make a re-tune of Earth's palette silently repaint Mars. Holding an equal
        but separate list would mean someone had copied Earth's stops back in — the same wrong
        planet, arrived at without an `is` to catch it — so the values are compared too.

        Its sea is None, which is a fact rather than a placeholder: the planet seam declares no
        oceanmask, so no pixel could select a sea ramp however carefully one were written.
        """
        assert palette.MARS_LOOK.land.stops is palette.MARS_LAND_STOPS
        assert palette.MARS_LOOK.land.stops is not palette.EARTH_LOOK.land.stops
        assert palette.MARS_LOOK.land.stops != palette.EARTH_LOOK.land.stops
        assert palette.MARS_LOOK.land is not palette.EARTH_LOOK.land
        assert palette.MARS_LOOK.sea is None
        assert palette.EARTH_LOOK.sea is not None

    def test_mars_land_rises_monotonically_so_height_can_be_read(self):
        """The one property that is a DECISION rather than a measurement, pinned as such.

        Mars's real albedo is brightest at both ends — Hellas is a dust trap, Tharsis is
        dust-mantled — so a ramp faithful to the planet would give the deepest basin and the highest
        summit the same colour. That is precisely the defect Mars inherited from Earth's shoreline
        hinge, where bright-at-zero means "beach" on a body that has one. Rising with elevation is
        the cartographic convention chosen over the fidelity, and the About page discloses it.

        Asserted on LUMINANCE rather than on any single channel: a ramp can rise in red while
        falling in perceived brightness, and it is brightness the eye reads elevation from.
        """
        lumas = [0.2126 * r + 0.7152 * g + 0.0722 * b
                 for _, (r, g, b) in palette.MARS_LAND_STOPS]
        assert lumas == sorted(lumas), (
            f"Mars's land ramp is not monotone in luminance: {[round(v, 4) for v in lumas]}. "
            "Two elevations now share a brightness, which is the Hellas/Olympus collision the "
            "authored ramp exists to remove."
        )
        assert len(set(lumas)) == len(lumas), "two stops share a luminance, so a band reads flat"

    def test_a_zero_width_ramp_is_refused_at_declaration(self):
        """The one failure in this class with no visible symptom at all.

        `span_m` of 0 divides by zero, numpy hands back nan, `np.rint(nan)` is nan, and the cast to
        int32 makes it an arbitrary index — a planet rendered in one wrong colour with no exception
        anywhere and every gate green. Refusing where the ramp is DECLARED is the only cheap place;
        by the time a pixel is being looked up there is no ramp left to name.
        """
        with pytest.raises(ValueError, match="two distinct ends"):
            palette.Surface(stops=palette.LAND_STOPS, origin_m=1000.0, extreme_m=1000.0)

    def test_a_ramp_that_runs_downward_keeps_its_direction(self):
        """A SYNTHETIC ramp whose ends are neither body's, because a parameterisation is unverified
        until something non-default runs through the real entry point — and both real looks happen
        to put position 0.0 at the shallower end, which would hide a `lowest_m` that just returned
        `origin_m`.
        """
        downward = palette.Surface(stops=palette.SEA_STOPS, origin_m=-200.0, extreme_m=-3500.0)
        assert downward.span_m == -3300.0
        assert downward.lowest_m == -3500.0
        upward = palette.Surface(stops=palette.LAND_STOPS, origin_m=-200.0, extreme_m=3500.0)
        assert upward.span_m == 3700.0
        assert upward.lowest_m == -200.0

    def test_mars_land_spans_its_own_measured_elevations(self):
        """The domain is p1/p99 of Mars's own heightfield, area-weighted on the sphere.

        Asserted as an ORDERING against Earth rather than as two literals restated from the module:
        what must stay true is that Mars starts below the datum and Earth does not, which is the
        defect this domain exists to fix. Pinning the numbers here would only pin the transcription.
        """
        mars, earth = palette.MARS_LOOK.land, palette.EARTH_LOOK.land
        assert mars.origin_m < 0 < mars.extreme_m
        assert earth.origin_m == 0.0
        assert mars.span_m > earth.span_m
        assert mars.lowest_m == mars.origin_m

    def test_a_look_with_no_sea_refuses_to_resolve_one(self):
        """Absence is answered by raising, never by handing back the absence itself.

        Returning `None` would push the decision onto every caller and be wrong in whichever one
        forgot — and `Surface | None` makes that the tidy the type checker appears to ask for.
        """
        with pytest.raises(ValueError, match="draws no sea"):
            palette.surface("sea", look=palette.MARS_LOOK)
        assert palette.surface("land", look=palette.MARS_LOOK) is palette.MARS_LOOK.land


#: The authored ramp values, assembled into a `Look`, which outside `palette.py` nothing may read
#: by name. `MARS_LAND_STOPS` joins them on the day Mars stops borrowing Earth's colours: a second
#: body's ramp is reachable by exactly the same bypass, and it is the one whose regrowth would be
#: invisible, since a module reading it renders Earth correctly no matter what it does to Mars.
RAMP_GLOBALS = ("LAND_STOPS", "SEA_STOPS", "LAND_MAX_M", "SEA_MIN_M", "MARS_LAND_STOPS")

#: A read of palette's own globals, qualified or imported. NOT a bare name: `scene_build` defines
#: module constants of its own called `LAND_STOPS`/`SEA_STOPS` — built FROM the look — and those
#: are the seam working rather than bypassing it.
def _bypass_pattern(name: str) -> str:
    return rf"palette\s+import\s+[^\n]*\b{name}\b|palette\.{name}\b"


def test_no_module_reaches_around_the_look_to_the_ramp_globals():
    """The anti-regrowth scan, and it is the guard that would have caught this seam's own defect.

    `Look`, `EARTH_LOOK` and `surface(look=...)` existed for a while before anything used them: the
    tile recipe and the hero rig both read `palette.LAND_STOPS` and friends directly, so every
    body's freshness record carried Earth's ramp and no type checker could say so. **A bypass is
    not a call site.** Removing `surface`'s default named eight LUT helpers and neither module that
    actually drew a planet — those came out of grep, and only a source scan can keep them out.

    Nothing else can see a regrowth. A module reading these globals renders Earth perfectly, passes
    every gate, and is wrong only on a planet nobody has looked at yet.
    """
    positive_control = "value = palette.LAND_STOPS[0]"
    assert re.search(_bypass_pattern("LAND_STOPS"), positive_control), (
        "the bypass pattern no longer matches a qualified read — the scan below cannot bite"
    )

    palette_source = Path(palette.__file__).resolve()
    scanned: set[str] = set()
    offenders: dict[str, list[str]] = {}
    for path in sorted((REPO_ROOT / "pipeline").rglob("*.py")):
        if path.resolve() == palette_source:
            continue
        name = str(path.relative_to(REPO_ROOT))
        scanned.add(name)
        source = path.read_text(encoding="utf-8")
        found = [g for g in RAMP_GLOBALS if re.search(_bypass_pattern(g), source)]
        if found:
            offenders[name] = found

    # Anti-vacuity that NAMES the two modules which actually held the defect, rather than counting
    # files. A count survives a walk narrowed to one package; these two do not.
    must_scan = {"pipeline/tile/shade_planet.py", "pipeline/render/scene_build.py"}
    assert must_scan <= scanned, (
        f"the sweep never reached {sorted(must_scan - scanned)} — the two modules that carried "
        "this exact bug. Whatever it is scanning now, it is not the shading path."
    )
    assert not offenders, (
        f"these modules reach around the look to Earth's ramp globals: {offenders}. Resolve the "
        "body's ramp with `palette.look_for(body.name)` and read `look.land` / `look.sea` — the "
        "globals are the values EARTH'S look is assembled from, not the ramp any planet draws with."
    )
