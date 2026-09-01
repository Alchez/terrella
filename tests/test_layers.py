"""The surface-layer vocabulary itself: the three stage views, and the warped set each one gets.

`test_layer_producers.py` is about who paints what. This is one level under it, about which layers a
stage is even shown, which is the question a producer never gets to ask.

THE TABLE'S OWN DOCTRINE IS THAT THE THREE VIEWS ARE NEVER EQUAL, and `WARPED_LAYERS` used to be
the place that quietly denied it: one composite-shaped tuple, read by the block prep, the block
render's dependency list and `producers_for`. It agreed with the block's own view for every live
layer, so nothing could go red, and it disagreed with the cap's by two rows -- which is why the cap
never read it and why the coincidence was only ever about one tier.
"""
import dataclasses

import pytest

from pipeline import layers


def _layer(name: str, **overrides) -> layers.Layer:
    """A row with a warped raster behind it, since a row without one is never in a warped set."""
    base = layers.Layer(name, in_planet=False, in_cap=False, in_block=False,
                        requires_raster=None, warped_basename=f"{name}_3857.tif")
    return dataclasses.replace(base, **overrides) if overrides else base


class TestEachStageIsShownTheWarpedLayersItsOwnVocabularyNames:
    def test_the_caps_warped_set_is_genuinely_smaller_than_the_composites(self):
        """THE LIVE PROOF THAT THE DISTINCTION IS NOT HYPOTHETICAL, and the reason a single shared
        tuple was wrong even while every consumer agreed with it. The cap composites no lake
        bathymetry and no glaciers, so two of the composite's five rows are not its to warp."""
        composite = [layer.name for layer in layers.warped_for(layers.PLANET_LAYERS)]
        cap = [layer.name for layer in layers.warped_for(layers.CAP_LAYERS)]
        assert set(cap) < set(composite)
        assert set(composite) - set(cap) == {"lake_depth", "glaciers"}

    def test_a_warped_layer_outside_the_composite_still_reaches_its_own_stage(self, monkeypatch):
        """THE DEFECT, and no live row exhibits it: the set was filtered on `in_planet`, so a
        layer belonging to the block tier and not to the composite was dropped from the only list
        the block prep reads. It would be declared, cost a warp, and reach no pixel, with the file
        on disk unable to help because a path nobody names is not a dependency.

        Both directions are checked, because over-tracking is the same bug facing the other way and
        the table's own comment already names its price: a composite-only row must NOT appear in the
        block's set, or switching it restages a 46 GB render that cannot contain it.
        """
        block_only = _layer("block_only", in_block=True)
        composite_only = _layer("composite_only", in_planet=True)
        monkeypatch.setattr(layers, "LAYERS", (*layers.LAYERS, block_only, composite_only))
        block = {layer.name for layer in layers.warped_for(frozenset({"block_only"}))}
        assert block == {"block_only"}
        assert "composite_only" not in block

    def test_a_row_with_no_warped_raster_is_never_returned(self, monkeypatch):
        """`coastline` is the live one: in the cap's vocabulary, with no file behind it. A stage
        asking for its warped layers is asking what to READ, so a row with nothing to read is not a
        member however loudly its vocabulary claims it."""
        assert "coastline" in layers.CAP_LAYERS
        assert "coastline" not in {layer.name for layer in layers.warped_for(layers.CAP_LAYERS)}
        bare = dataclasses.replace(_layer("bare"), in_block=True, warped_basename=None)
        monkeypatch.setattr(layers, "LAYERS", (*layers.LAYERS, bare))
        assert "bare" not in {layer.name for layer in layers.warped_for(frozenset({"bare"}))}

    def test_the_tables_order_survives_the_filter(self):
        """ORDER IS PART OF THE CONTRACT rather than tidiness: the planet tier's deps are a tuple a
        test pins, and `LAYERS` is written in the order that tuple has always had. A filter that
        preserves membership and loses order breaks the dependency list without changing its set."""
        for vocabulary in (layers.PLANET_LAYERS, layers.CAP_LAYERS, layers.BLOCK_LAYERS):
            selected = [layer.name for layer in layers.warped_for(vocabulary)]
            assert selected == [layer.name for layer in layers.LAYERS
                                if layer.name in selected]

    def test_an_unknown_name_in_a_vocabulary_is_simply_absent(self):
        """A vocabulary is a set of names and nothing checks it against the table, so the filter has
        to answer rather than raise: `layers_off` already leans on a name meaning nothing here."""
        assert layers.warped_for(frozenset({"no_such_layer"})) == ()


class TestTheCompositeShapedTupleIsGone:
    def test_no_module_offers_a_warped_set_that_is_not_asked_for_a_vocabulary(self):
        """The retirement, pinned. `WARPED_LAYERS` was importable and composite-shaped, so the next
        consumer to want "the layers with a raster" would reach for it and inherit the composite's
        answer for their own tier, which is exactly how the block tier got it."""
        assert not hasattr(layers, "WARPED_LAYERS"), (
            "WARPED_LAYERS is back; a stage-agnostic warped set is the defect, not the fix")

    def test_the_replacement_refuses_to_be_called_without_one(self):
        with pytest.raises(TypeError):
            layers.warped_for()  # pyright: ignore[reportCallIssue]
