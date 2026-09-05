"""What a surface layer is, and which stages read it: one table, and the views derived from it.

A layer is something the render paints over the heightfield. Snow, glaciers, sea ice, lake
bathymetry, the coastline. Whether a given planet has one is a body fact (`Body.surface_layers`);
what the set of possible ones is, and which stage reads which, is a pipeline fact and lives here.
Not `planet_seam`'s rasters, and the two must not be merged: the rule beside this file holds the
three vocabularies apart, and one word for two concepts is how a reader concludes that one guard
covers the other.

A table rather than three frozensets, because hand-kept sets have to agree and fail silently when
they do not: a layer added to the whole one and forgotten in a stage's is one a body can declare and
nothing will ever build, and a name in a stage's set that is not in the whole one appears in that
stage's `layers_off` for every body alike. One row per layer makes the agreement structural, and the
split is still pinned against literals in `tests/test_bodies.py`, because a table can hold a wrong
column as easily as two sets can disagree.

Stage membership is a field per stage and not a set of names, for the reason `bodies.Body` carries
no defaults: a new stage must be a hard error at every row until each layer answers for it. A set
would let the rows that need it be edited and the rest inherit "not mine" unexamined, which is how a
stage inherits a layer its rig has no input for: recorded, and consumable by no node.

    from pipeline import layers
    if layers.layer_is_buildable(body, layers.SEA_ICE, source, "bathymetry bare at the poles"): ...
"""

from dataclasses import dataclass
from pathlib import Path

from pipeline import bodies


@dataclass(frozen=True)
class Layer:
    """One optional thing the render paints over the heightfield, and who reads it.

    Frozen, and every field required — see the module note. A `Layer` is a pipeline fact and says
    nothing about any planet; `Body.surface_layers` is where a body answers for it.
    """

    #: The vocabulary word. The one spelling: call sites pass the `Layer`, never the string.
    name: str
    #: Read by the planet warp (`planet_warp.py`), which lands it on the 3857 grid.
    in_planet: bool
    #: Read by the polar cap pass (`tile/cap_pass.py`), whichever arm it dispatches to.
    in_cap: bool
    #: Read by the raytraced block render (`render/scene_build.py`, staged by the block prep).
    #:
    #: The third stage, and it shades the same Mercator grid the planet warp feeds, which makes
    #: copying the `in_planet` column the natural mistake. The two columns agree row for row today,
    #: the rig painting every raster layer the warp stage prepares, but that is an answer per row
    #: and not a rule: `tests/test_bodies.py` pins it as literals so a new layer still answers here,
    #: equal-today not being the same claim as equal-by-construction.
    in_block: bool
    #: The planet raster this layer cannot be computed without, or None.
    #:
    #: Held as a name rather than an imported constant so this module never imports `planet_seam`,
    #: which imports `bodies` beside us. Nothing at runtime spell-checks the string, which is the
    #: price of keeping that dependency one-way, so `tests/test_bodies.py` pins every one of them to
    #: `planet_seam.KNOWN_RASTERS`, a typo being otherwise silent in whichever direction it lands.
    requires_raster: str | None
    #: The file this layer is built into inside the body's own work directory, or None for a layer
    #: the planet tier never reads back from a raster. Not `requires_raster` above, which names a
    #: raster the planet seam emits at a different tier and on another body's behalf.
    #:
    #: A layer fact rather than a producer fact, which is what keeps the planet tier's dependency
    #: list body-independent: it names every layer's raster whatever the planet declared, where its
    #: sibling `cap_render.cap_sources` names only what it opens. Independent of `in_planet` too,
    #: though the two agree on every row today: a planet layer answered by pure arithmetic would
    #: carry None here, so deriving either column from the other loses that case silently.
    warped_basename: str | None

    def warped_in(self, work: Path) -> Path:
        """This layer's built raster inside one body's work directory — the one place they join.

        Only meaningful for a row `warped_for` returns, and the assertion is that filter restated where a
        type checker can see it rather than a condition anything is expected to reach.
        """
        assert self.warped_basename is not None, f"{self.name} builds no raster"
        return work / self.warped_basename


#: Every layer the pipeline knows, and the whole vocabulary `Body.surface_layers` may draw from.
#:
#: Each comes from a dataset describing exactly one planet — Earth — which is why membership is a
#: body fact and not, as it looks, a question of whether a file happens to be on disk: every source
#: is a module constant at a fixed global path shared by every body. `layer_is_buildable` below is
#: what keeps that ordering honest.
#:
#: Named for the claim and not for Earth's dataset: `perennial_ice` asserts the white that is there
#: all year, where a name like `snow` describes one source and already stretches past breaking on
#: Antarctica's permanent ice sheet and on Mars's residual cap of CO2 and water ice. A
#: body-specific name is how a vocabulary grows one entry per planet for one concept.
#:
#: The basenames below are shipped and must not be tidied. Each is a dependency by mtime, so
#: renaming one restages Earth's whole pyramid to reproduce the pixels already on disk.
LAKE_DEPTH = Layer("lake_depth", in_planet=True, in_cap=False, in_block=True,
                   requires_raster="watermask", warped_basename="lakedepth_3857.tif")
PERENNIAL_ICE = Layer("perennial_ice", in_planet=True, in_cap=True, in_block=True,
                      requires_raster=None, warped_basename="snow_persistence_3857.tif")
GLACIERS = Layer("glaciers", in_planet=True, in_cap=False, in_block=True,
                 requires_raster=None, warped_basename="glacier_3857.tif")
SEA_ICE = Layer("sea_ice", in_planet=True, in_cap=True, in_block=True,
                requires_raster="oceanmask", warped_basename="seaice_3857.tif")
COASTLINE = Layer("coastline", in_planet=False, in_cap=True, in_block=False,
                  requires_raster=None, warped_basename=None)
#: The one row whose raster is read by another layer's producer, and it paints nothing of its own:
#: `perennial_ice` forces Antarctic land white by a latitude rule with no dataset behind it, and
#: this is the dataset that takes exposed rock back out from under that white, subtracted rather
#: than unioned, which is why it sits outside `layer_producers.WHITE_UNION` and its contribution is
#: None on every window. A layer all the same rather than a fourth planet raster, on the rule beside
#: this file: Mars omits the name from `surface_layers` and `layers_off` records it off, where a
#: planet raster would make every `planet_seam.declared` reader answer for a mask only Earth has.
#:
#: Every stage column is True because all three run the rule: the planet warp, the block prep and
#: the south cap. A stage that subtracts rock and does not record the layer would keep its old
#: output looking fresh the day the layer was switched off.
ANTARCTIC_ROCK = Layer("antarctic_rock", in_planet=True, in_cap=True, in_block=True,
                       requires_raster=None, warped_basename="addrock_3857.tif")

LAYERS: tuple[Layer, ...] = (LAKE_DEPTH, PERENNIAL_ICE, GLACIERS, SEA_ICE, COASTLINE,
                             ANTARCTIC_ROCK)


#: The whole vocabulary, as names.
SURFACE_LAYERS = frozenset(layer.name for layer in LAYERS)

#: The layers each stage reads, derived — never hand-kept, and never equal to each other.
#:
#: The split is load-bearing, which is the whole reason two views exist: each stage records the
#: layers it is missing in its own freshness recipe, so turning one off restages it, which file
#: mtimes cannot do because an unbuilt raster scores 0.0 and is silently not a dependency.
#: Recording a layer a stage never reads inverts the trap instead of closing it: switching the
#: coastline would restage a 46 GB tile pass that cannot contain one. The tiles bake no coast (it is
#: a vector overlay the client draws) and the caps draw no lake bathymetry and no glaciers
#: (`depth=None`, persistence-only snow). Over- and under-tracking are both silent.
PLANET_LAYERS = frozenset(layer.name for layer in LAYERS if layer.in_planet)
CAP_LAYERS = frozenset(layer.name for layer in LAYERS if layer.in_cap)
BLOCK_LAYERS = frozenset(layer.name for layer in LAYERS if layer.in_block)

def warped_for(vocabulary: frozenset[str]) -> tuple[Layer, ...]:
    """One stage's layers that have a file to read, as rows and in `LAYERS` order.

    Asked per stage because the answer differs per stage, which the three views above already say
    and which one shared tuple denies. A tuple filtered on `in_planet` and shared by the block prep,
    the block render's dependency list and `producers_for` agrees with the block's own view for
    every live row and disagrees with the cap's by two, so the cap cannot use it and no test sees
    the disagreement.

    Both directions of the mismatch are silent, which is why the vocabulary is an argument rather
    than a default. A block-tier layer left out of the planet vocabulary is dropped from the only
    list the prep reads: declared, warped, and reaching no pixel, with its file unable to help
    because a path nobody names is not a dependency. A planet-only layer handed to the block tier is
    the same bug facing the other way, priced as the note above: switching it restages a render that
    cannot contain it.

    Order is part of the contract rather than tidiness: the planet tier's dependency tuple has its
    contents pinned by a test, and `LAYERS` is written in that tuple's order.
    """
    return tuple(layer for layer in LAYERS
                 if layer.warped_basename and layer.name in vocabulary)

#: Which planet raster each dependent layer needs, derived. Read by `planet_seam._require_coherent`.
#:
#: These are real data dependencies and not bookkeeping. `lake_depth` is zeroed off watermask class
#: 2 (`lake_depth.lakes_only`), so a body declaring that layer with no watermask has nothing to zero
#: against and the painter reads `None` as a class code. `sea_ice` is gated on the ocean mask where
#: the alpha is built, so ice on a body with no ocean mask is blended against an all-False selector
#: and paints nothing at all: a layer switched on, costing a warp, reaching no pixel. Both are
#: incoherent rather than merely empty, which is why `planet_seam` refuses them where the two facts
#: first meet rather than letting one surface as a `TypeError` in a worker.
LAYER_REQUIRES_RASTER: dict[str, str] = {
    layer.name: layer.requires_raster for layer in LAYERS if layer.requires_raster is not None}


def layers_off(body: bodies.Body, vocabulary: frozenset[str]) -> list[str]:
    """Which of `vocabulary` this body does NOT have, sorted — one stage's freshness record.

    The layers that are off, never the ones that are on, and the asymmetry is load-bearing. Earth
    declares every layer, so its list is empty and the caller's conditional record writes nothing at
    all, leaving a 46 GB tile pass and a 14 GB cap render byte-identical. Recording the layers that
    are on would put a list into Earth's recipe for the first time and restage the planet to produce
    the pixels already sitting there.

    `vocabulary` is the CALLER'S stage view — `PLANET_LAYERS` or `CAP_LAYERS`, never
    `SURFACE_LAYERS` — so that a stage records only what it actually reads. See those two for why a
    shared vocabulary here would trade one silent freshness bug for another.
    """
    return sorted(vocabulary - body.surface_layers)


def body_declares_layer(body: bodies.Body, layer: Layer, consequence: str) -> bool:
    """Whether this body has `layer` at all — the body half of the gate, on its own.

    Split out because one rule has no dataset behind it: the forced Antarctic land-ice patch is pure
    latitude-and-land arithmetic (`snow.antarctic_snow_mask`), so no file's absence can switch it
    off, and on a sea-less body it would whiten every piece of land below 60 degrees south. It rides
    the `perennial_ice` layer, and this is what lets it ask that question with the same words and
    the same printed consequence as the four layers that do read a file.
    """
    if layer.name not in body.surface_layers:
        print(f"{body.name} declares no {layer.name} layer -> skipped ({consequence})", flush=True)
        return False
    return True


def layer_is_buildable(body: bodies.Body, layer: Layer, source: Path, consequence: str) -> bool:
    """Whether this body's `layer` can be warped: asked of the body first, then of the disk.

    The order is the point, and it is structural rather than a convention, the body half being a
    separate function this one calls first. Each of these sources is a module constant at a fixed
    global path, so `source.exists()` answers "have we downloaded Earth's data" for every planet
    alike. Asking it first lets a second body pass the check on Earth's file and paint Earth's
    cryosphere onto its own grid, at the same latitudes, rendering as a perfectly plausible planet.

    Both branches print, and each states the consequence rather than only the cause: a skipped layer
    is a look decision, and a pass that goes quiet about one is a pass whose output cannot be read
    back. Returning False rather than raising keeps a partial build legal, which is what makes the
    layers switchable at all.
    """
    if not body_declares_layer(body, layer, consequence):
        return False
    if not source.exists():
        print(f"no {source.name} -> {layer.name} skipped ({consequence})", flush=True)
        return False
    return True
