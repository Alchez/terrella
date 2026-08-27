"""Which producer made the planet raster: that both producers declare it, and that a switch is seen.

THE DEFECT THIS FILE EXISTS FOR IS SILENT IN BOTH DIRECTIONS AND SHIPS WRONG PIXELS. Two producers
write one `planet_rgb.tif`, and `freshness.done_marker` derives from the output alone, so they share
one completion marker. Each one's staleness question is then answered by the other's work: whichever
ran last leaves a raster newer than every source and every recipe the OTHER tracks, so that one
prints "fresh -> skip" and republishes the wrong producer's pixels under its own recipe. Nothing
raises, nothing is missing, and every other gate stays green.

The guards are therefore weighted toward the two ENTRY POINTS rather than the seam's own arithmetic.
The first version of this mechanism was correct in isolation and wrong in placement: the dispatcher
wrote the stamp, and `block_render.main` is a second shipped door that never reaches the dispatcher.
A unit test of the write function passed throughout.
"""

import dataclasses
import json

import pytest

from pipeline import bodies, freshness, planet_seam
from pipeline.look import palette
from pipeline.tile import block_render, producer_seam, shade_planet

_DECLARED_RASTERS = {"earth": frozenset(planet_seam.KNOWN_RASTERS),
                     "mars": frozenset({"heightfield"})}


@pytest.fixture
def raytraceable(tmp_path, monkeypatch):
    """A work directory `block_render.run` can reach its freshness question through, with no store,
    no block plan and no Blender. Returns the mosaic."""
    monkeypatch.setattr(block_render.planet_seam, "declared",
                        lambda body: _DECLARED_RASTERS[body.name])
    monkeypatch.setattr(block_render, "plan_blocks", lambda body, work: [])
    monkeypatch.setattr(block_render, "ensure_mosaic", lambda mosaic, body: None)
    for name in (shade_planet.HEIGHT_3857, shade_planet.OCEAN_3857, shade_planet.WATER_3857):
        (tmp_path / name).write_bytes(b"")
    (tmp_path / block_render.PARAMS_NAME).write_text(block_render.params(
        bodies.EARTH, _DECLARED_RASTERS["earth"], palette.look_for("earth"),
        block_render.rig_recipe(bodies.EARTH), []))
    return tmp_path / shade_planet.PLANET_RGB


def _composite_would_rebuild(work, mosaic):
    """What the composite producer DECIDES, declaring itself first exactly as `composite_planet` does.

    The declaration is part of the oracle rather than a step before it. The raytrace producer marks
    the mosaic done AFTER it declares, so its own marker is always newer than its own stamp — a
    reader that never declares can never see a switch, and an oracle that skips the declaration is
    measuring a sequence production never runs. What makes the switch visible is the NEXT producer's
    declaration moving the stamp past that marker.
    """
    producer_seam.declare(work, "composite")
    return freshness.is_stale(mosaic, *shade_planet.composite_deps(
        work, work / "hs.tif", work / "composite_params.json"))


class TestBothProducersNameTheStamp:
    """Naming it on one side detects nothing: the detection has to be symmetric."""

    def test_the_composite_names_it(self, tmp_path):
        deps = shade_planet.composite_deps(tmp_path, tmp_path / "hs.tif", tmp_path / "p.json")
        assert producer_seam.stamp_path(tmp_path) in deps

    def test_the_raytrace_names_it(self, tmp_path):
        deps = block_render.raytrace_deps(tmp_path, tmp_path / "r.json")
        assert producer_seam.stamp_path(tmp_path) in deps

    def test_it_is_the_same_path_on_both_sides(self, tmp_path):
        """One basename with one owner: two spellings would leave each producer watching its own
        file, which is the shape that cannot detect a switch in either direction."""
        composite = set(shade_planet.composite_deps(tmp_path, tmp_path / "hs.tif",
                                                    tmp_path / "p.json"))
        raytrace = set(block_render.raytrace_deps(tmp_path, tmp_path / "r.json"))
        assert producer_seam.stamp_path(tmp_path) in composite & raytrace


class TestTheStampIsADependencyRatherThanARestage:

    def test_an_unchanged_producer_does_not_move_the_mtime(self, tmp_path):
        """Which is what makes it a dependency rather than a restage: re-running an unchanged body
        must rebuild nothing, and `write_if_changed` is what guarantees that."""
        first = producer_seam.declare(tmp_path, "composite")
        before = first.stat().st_mtime_ns
        producer_seam.declare(tmp_path, "composite")
        assert first.stat().st_mtime_ns == before

    def test_a_changed_producer_does_move_it(self, tmp_path):
        """The positive control for the test above, and the behaviour the whole file exists for."""
        stamp = producer_seam.declare(tmp_path, "composite")
        before = stamp.read_text()
        assert producer_seam.declare(tmp_path, "raytrace").read_text() != before

    def test_a_producer_outside_the_vocabulary_is_refused(self, tmp_path):
        """A typo would otherwise be perfectly silent: it differs from whatever is on disk, so the
        raster restages once, looks correct, and leaves a stamp no dispatcher can ever match."""
        with pytest.raises(ValueError, match="unknown planet producer"):
            producer_seam.declare(tmp_path, "raytraced")
        assert not producer_seam.stamp_path(tmp_path).exists()

    def test_the_vocabulary_is_the_registry_s_and_not_a_second_list(self, tmp_path, subtests):
        """Derived from `bodies.PLANET_PRODUCERS`, so a widened vocabulary cannot leave this seam
        refusing a value the registry now accepts."""
        assert bodies.PLANET_PRODUCERS, "an empty vocabulary would make the loop below vacuous"
        for producer in bodies.PLANET_PRODUCERS:
            with subtests.test(producer=producer):
                assert json.loads(producer_seam.declare(tmp_path, producer).read_text()) == {
                    "producer": producer}


class TestNothingHasDeclaredYet:
    """The state every work directory is in until the first pass after this seam existed."""

    def test_an_undeclared_directory_answers_none_rather_than_raising(self, tmp_path):
        assert producer_seam.declared(tmp_path) is None

    def test_so_does_a_corrupt_stamp(self, tmp_path):
        producer_seam.stamp_path(tmp_path).write_text("{ this is not json")
        assert producer_seam.declared(tmp_path) is None

    def test_a_declared_one_answers_what_was_declared(self, tmp_path):
        producer_seam.declare(tmp_path, "raytrace")
        assert producer_seam.declared(tmp_path) == "raytrace"


class TestEveryDoorIntoAProducerDeclaresThatProducer:
    """THE PLACEMENT GUARD, and the reason this class is not a test of `declare`.

    `block_render.main` is a second shipped door into the raytrace producer — it is how one block is
    re-rendered for judging (`--only`, `--limit`) — and it calls `run` directly. While the DISPATCHER
    owned the stamp, that door left it saying whatever the last pass wrote, and a missing stamp is
    worse than a stale one: `freshness.newest_mtime` scores an absent path 0.0, so the dependency
    both recipes name contributes nothing at all and the mechanism is inert.
    """

    def test_the_raytrace_door_records_the_raytrace(self, raytraceable, tmp_path):
        producer_seam.declare(tmp_path, "composite")          # a composite pass ran first
        assert producer_seam.declared(tmp_path) == "composite", "the setup must really say composite"

        block_render.main(["--body", "earth", "--work", str(tmp_path)])

        assert producer_seam.declared(tmp_path) == "raytrace", (
            "a run through the raytrace producer's own CLI left the stamp on the previous "
            "producer, so the next composite pass republishes raytraced pixels as its own"
        )

    def test_it_declares_the_producer_that_RAN_not_the_one_the_body_asked_for(self, raytraceable,
                                                                             tmp_path, monkeypatch):
        """The two differ in exactly the case this exists for: `--only` re-renders one block of any
        body for judging, so raytraced bytes can land on a planet the registry calls composite.
        Recording the body's answer would leave the stamp agreeing with a registry the pixels
        disagree with — which is the state that reads as fresh.

        THE DIVERGENCE IS CONSTRUCTED RATHER THAN BORROWED. It used to read Earth's registered
        `"composite"`, which made the guard a hostage of which body happens to be composite today —
        and Earth's switch to raytrace turned it red for a reason that was not about the seam.
        """
        composited = dataclasses.replace(bodies.get("earth"), planet_producer="composite")
        monkeypatch.setitem(bodies.BODIES, "earth", composited)

        block_render.main(["--body", "earth", "--work", str(tmp_path)])
        assert producer_seam.declared(tmp_path) == "raytrace"

    def test_the_composite_then_sees_that_it_must_rebuild(self, raytraceable, tmp_path):
        """The same defect in the currency that ships. The first assertion is the positive control:
        without it a green result could come from the composite being stale for some other reason."""
        producer_seam.declare(tmp_path, "composite")
        raytraceable.write_bytes(b"composited pixels")
        freshness.mark_done(raytraceable)
        assert not _composite_would_rebuild(tmp_path, raytraceable), (
            "the setup must start from a composite that would SKIP, or the assertion below proves "
            "nothing about what the stamp detects"
        )

        block_render.main(["--body", "earth", "--work", str(tmp_path)])

        assert _composite_would_rebuild(tmp_path, raytraceable), (
            "the composite still says 'planet_rgb fresh -> skip composite' over a raster the "
            "raytrace producer just claimed"
        )
