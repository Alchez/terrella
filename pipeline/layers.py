"""What a surface layer IS, and which stages read it — one table, and the views derived from it.

A LAYER IS SOMETHING THE RENDER PAINTS OVER THE HEIGHTFIELD. Snow, glaciers, sea ice, lake
bathymetry, the coastline. Whether a given planet HAS one is a body fact (`Body.surface_layers`);
what the set of possible ones is, and which stage reads which, is a pipeline fact and lives here.

NOT `planet_seam`'S RASTERS, and the two must not be merged. Those are the heightfield and the masks
that classify it, produced by a different tier and answering a different question — `planet_seam`'s
own docstring holds that argument, and one word for both concepts is how a reader concludes that one
guard covers the other.

WHY A TABLE RATHER THAN THREE FROZENSETS. The stage vocabularies were three hand-kept sets that had
to agree: a layer added to the whole one and forgotten in a stage's is one a body can declare and
nothing will ever build, and a name in a stage's set that is not in the whole one appears in that
stage's `layers_off` for every body alike. Both are silent. One row per layer makes the agreement
structural, and the split itself is still pinned against literals in `tests/test_bodies.py`, because
a table can hold a wrong column as easily as two sets can disagree.

STAGE MEMBERSHIP IS A FIELD PER STAGE, NOT A SET OF NAMES, for the reason `bodies.Body` carries no
defaults: a fourth stage must be a hard error at every row until each layer answers for it. A set
would let the rows that need it be edited and the rest inherit "not mine" unexamined.

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
    #: Read by the Mercator tile composite (`tile/shade_planet.py`).
    in_composite: bool
    #: Read by the polar cap render (`tile/cap_render.py`).
    in_cap: bool
    #: The planet raster this layer cannot be computed without, or None.
    #:
    #: Held as a NAME rather than an imported constant so this module never imports `planet_seam`,
    #: which imports `bodies` beside us. Nothing at runtime spell-checks the string — the price of
    #: keeping that dependency one-way — so `tests/test_bodies.py` pins every one of them to
    #: `planet_seam.KNOWN_RASTERS`, a typo being otherwise silent in whichever direction it lands.
    requires_raster: str | None


#: Every layer the pipeline knows, and the whole vocabulary `Body.surface_layers` may draw from.
#:
#: Each comes from a dataset describing exactly one planet — Earth — which is why membership is a
#: body fact and not, as it looks, a question of whether a file happens to be on disk: every source
#: is a module constant at a fixed global path shared by every body. `layer_is_buildable` below is
#: what keeps that ordering honest.
#:
#: NAMED FOR THE CLAIM, NOT FOR EARTH'S DATASET. `perennial_ice` was `snow`, which described the
#: source (NSIDC-0791 persistence) rather than what the layer asserts — the white that is there all
#: year. Earth's own south cap already stretched the old word past breaking, using it for
#: Antarctica's permanent ice SHEET, and Mars's residual cap is CO2 and water ice rather than
#: snowfall. A body-specific name is how a vocabulary grows one entry per planet for one concept.
LAKE_DEPTH = Layer("lake_depth", in_composite=True, in_cap=False, requires_raster="watermask")
PERENNIAL_ICE = Layer("perennial_ice", in_composite=True, in_cap=True, requires_raster=None)
GLACIERS = Layer("glaciers", in_composite=True, in_cap=False, requires_raster=None)
SEA_ICE = Layer("sea_ice", in_composite=True, in_cap=True, requires_raster="oceanmask")
COASTLINE = Layer("coastline", in_composite=False, in_cap=True, requires_raster=None)

LAYERS: tuple[Layer, ...] = (LAKE_DEPTH, PERENNIAL_ICE, GLACIERS, SEA_ICE, COASTLINE)


#: The whole vocabulary, as names.
SURFACE_LAYERS = frozenset(layer.name for layer in LAYERS)

#: The layers each stage reads, derived — never hand-kept, and never equal to each other.
#:
#: THE SPLIT IS LOAD-BEARING, which is the whole reason two views exist: each stage records the
#: layers it is MISSING in its own freshness recipe, so turning one off restages it — something file
#: mtimes cannot do, because an unbuilt raster scores 0.0 and is therefore silently not a dependency.
#: Recording a layer a stage never reads inverts the trap instead of closing it: switching the
#: coastline would restage a 46 GB tile composite that cannot contain one. The tiles bake no coast
#: (it is a vector overlay the client draws) and the caps composite no lake bathymetry and no
#: glaciers (`depth=None`, persistence-only snow). Over- and under-tracking are both silent.
COMPOSITE_LAYERS = frozenset(layer.name for layer in LAYERS if layer.in_composite)
CAP_LAYERS = frozenset(layer.name for layer in LAYERS if layer.in_cap)

#: Which planet raster each dependent layer needs, derived. Read by `planet_seam._require_coherent`.
#:
#: THESE ARE REAL DATA DEPENDENCIES, NOT BOOKKEEPING. `lake_depth` is zeroed off watermask class 2
#: (`lake_depth.lakes_only`), so a body declaring that layer with no watermask has nothing to zero
#: against and the composite would read `None` as a class code. `sea_ice` is gated on the ocean mask
#: inside `shade.composite`, so ice on a body with no ocean mask is blended against an all-False
#: selector and paints nothing at all — a layer that is switched on, costs a warp, and cannot reach
#: a pixel. Both are incoherent rather than merely empty, which is why `planet_seam` refuses them
#: where the two facts first meet rather than letting one surface as a `TypeError` in a worker.
LAYER_REQUIRES_RASTER: dict[str, str] = {
    layer.name: layer.requires_raster for layer in LAYERS if layer.requires_raster is not None}


def layers_off(body: bodies.Body, vocabulary: frozenset[str]) -> list[str]:
    """Which of `vocabulary` this body does NOT have, sorted — one stage's freshness record.

    THE LAYERS THAT ARE OFF, NEVER THE ONES THAT ARE ON, and that asymmetry is load-bearing rather
    than stylistic. Earth declares every layer, so its list is empty and the caller's conditional
    record writes nothing at all, leaving a 46 GB composite and a 14 GB cap render byte-identical.
    Recording the layers that are ON would put a list into Earth's recipe for the first time and
    restage the planet to produce the pixels already sitting there.

    `vocabulary` is the CALLER'S stage view — `COMPOSITE_LAYERS` or `CAP_LAYERS`, never
    `SURFACE_LAYERS` — so that a stage records only what it actually reads. See those two for why a
    shared vocabulary here would trade one silent freshness bug for another.
    """
    return sorted(vocabulary - body.surface_layers)


def body_declares_layer(body: bodies.Body, layer: Layer, consequence: str) -> bool:
    """Whether this body has `layer` at all — the body half of the gate, on its own.

    SPLIT OUT BECAUSE ONE RULE HAS NO DATASET BEHIND IT. The forced Antarctic land-ice patch is pure
    latitude-and-land arithmetic (`snow.antarctic_snow_mask`), so there is no file whose absence
    could ever switch it off — on a sea-less body it would simply whiten every piece of land below
    60 degrees south. It rides the `perennial_ice` layer, and this is what lets it ask that question
    with the same words and the same printed consequence as the four layers that do read a file.
    """
    if layer.name not in body.surface_layers:
        print(f"{body.name} declares no {layer.name} layer -> skipped ({consequence})", flush=True)
        return False
    return True


def layer_is_buildable(body: bodies.Body, layer: Layer, source: Path, consequence: str) -> bool:
    """Whether this body's `layer` can be warped — asked of the BODY first, then of the disk.

    THE ORDER IS THE POINT, and it is structural here rather than a convention: the body half is a
    separate function and this one calls it first. Each of these sources is a module constant at a
    fixed global path, so `source.exists()` answers "have we downloaded Earth's data" for every
    planet alike. Asking it first would let a second body pass the check on Earth's file and paint
    Earth's cryosphere onto its own grid — at the same latitudes, so it renders as a perfectly
    plausible planet.

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
