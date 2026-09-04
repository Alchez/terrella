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
defaults: a new stage must be a hard error at every row until each layer answers for it. A set would
let the rows that need it be edited and the rest inherit "not mine" unexamined — which is how the
block render would have inherited the composite's `sea_ice` back when its rig had no ice input at
all: a recorded layer no node could consume.

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
    #: THE THIRD STAGE. It shades the same Mercator grid the planet warp feeds, which makes copying
    #: the `in_planet` column the natural mistake. Today the two columns agree row for row — the rig
    #: paints every raster layer the warp stage prepares, `sea_ice` included — but the agreement is
    #: an answer per row and not a rule: `tests/test_bodies.py` pins it as literals so a new layer
    #: still answers here on purpose. It stayed a separate column when the second producer was
    #: deleted, because equal-today is not the same claim as equal-by-construction.
    in_block: bool
    #: The planet raster this layer cannot be computed without, or None.
    #:
    #: Held as a NAME rather than an imported constant so this module never imports `planet_seam`,
    #: which imports `bodies` beside us. Nothing at runtime spell-checks the string — the price of
    #: keeping that dependency one-way — so `tests/test_bodies.py` pins every one of them to
    #: `planet_seam.KNOWN_RASTERS`, a typo being otherwise silent in whichever direction it lands.
    requires_raster: str | None
    #: The file this layer is built into inside the body's own work directory, or None for a layer
    #: the planet tier never reads back from a raster. NOT `requires_raster` above, which names a
    #: raster the PLANET SEAM emits at a different tier and on another body's behalf.
    #:
    #: A LAYER FACT RATHER THAN A PRODUCER FACT, which is what keeps the planet tier's dependency
    #: list body-independent: it names every layer's raster whatever the planet declared, and its
    #: sibling `cap_render.cap_sources` names only what it opens. Independent of `in_planet` too,
    #: though the two agree on every row today — a planet layer answered by pure arithmetic would
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
#: NAMED FOR THE CLAIM, NOT FOR EARTH'S DATASET. `perennial_ice` was `snow`, which described the
#: source (NSIDC-0791 persistence) rather than what the layer asserts — the white that is there all
#: year. Earth's own south cap already stretched the old word past breaking, using it for
#: Antarctica's permanent ice SHEET, and Mars's residual cap is CO2 and water ice rather than
#: snowfall. A body-specific name is how a vocabulary grows one entry per planet for one concept.
#:
#: THE BASENAMES BELOW ARE SHIPPED AND MUST NOT BE TIDIED. Each is a dependency of the composite by
#: mtime, so renaming one restages Earth's whole pyramid to reproduce the pixels already on disk.
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
#: THE ONE ROW WHOSE RASTER IS READ BY ANOTHER LAYER'S PRODUCER, and it paints nothing of its own.
#: `perennial_ice` forces Antarctic land white by a latitude rule with no dataset behind it, and this
#: is the dataset that takes exposed rock back out from under that white — subtracted rather than
#: unioned, which is why it is outside `layer_producers.WHITE_UNION` and why its contribution is
#: None on every window.
#:
#: A LAYER ALL THE SAME, and not a fourth planet raster. Those three are the fused planet's own
#: outputs; this is a third-party vector burnt onto the grid as 0/1, which is exactly what `glaciers`
#: already is. The deciding argument is Mars: it simply omits the name from `surface_layers` and
#: `layers_off` records it off, where a planet raster would have made every `planet_seam.declared`
#: reader answer for a mask no body but Earth can have.
#:
#: EVERY STAGE COLUMN IS True BECAUSE ALL THREE RUN THE RULE — the tile composite, the block prep and
#: the south cap. A stage that subtracts rock and does not record the layer would keep its old output
#: looking fresh the day the layer was switched off.
ANTARCTIC_ROCK = Layer("antarctic_rock", in_planet=True, in_cap=True, in_block=True,
                       requires_raster=None, warped_basename="addrock_3857.tif")

LAYERS: tuple[Layer, ...] = (LAKE_DEPTH, PERENNIAL_ICE, GLACIERS, SEA_ICE, COASTLINE,
                             ANTARCTIC_ROCK)


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
PLANET_LAYERS = frozenset(layer.name for layer in LAYERS if layer.in_planet)
CAP_LAYERS = frozenset(layer.name for layer in LAYERS if layer.in_cap)
BLOCK_LAYERS = frozenset(layer.name for layer in LAYERS if layer.in_block)

def warped_for(vocabulary: frozenset[str]) -> tuple[Layer, ...]:
    """One stage's layers that have a file to read, as rows and IN `LAYERS` ORDER.

    ASKED PER STAGE BECAUSE THE ANSWER DIFFERS PER STAGE, which the three views above already say
    and which one shared tuple used to deny. Its predecessor filtered on `in_planet` and was read
    by the block prep, the block render's dependency list and `producers_for` alike. That agreed
    with the block's own view for every live row and disagreed with the cap's by two, so the cap
    could not use it and no test could see the disagreement.

    BOTH DIRECTIONS OF THE MISMATCH ARE SILENT, which is why the vocabulary is an argument rather
    than a default. A block-tier layer outside the composite is dropped from the only list the prep
    reads: declared, warped, and reaching no pixel, with its file unable to help because a path
    nobody names is not a dependency. A composite-only layer handed to the block tier is the same
    bug facing the other way, and the price is in the note above: switching it restages a render
    that cannot contain it.

    ORDER IS PART OF THE CONTRACT, not tidiness: the planet tier's dependency tuple has its contents
    pinned by a test, and `LAYERS` is written in the order that tuple has always had.
    """
    return tuple(layer for layer in LAYERS
                 if layer.warped_basename and layer.name in vocabulary)

#: Which planet raster each dependent layer needs, derived. Read by `planet_seam._require_coherent`.
#:
#: THESE ARE REAL DATA DEPENDENCIES, NOT BOOKKEEPING. `lake_depth` is zeroed off watermask class 2
#: (`lake_depth.lakes_only`), so a body declaring that layer with no watermask has nothing to zero
#: against and the painter would read `None` as a class code. `sea_ice` is gated on the ocean mask
#: where the alpha is built, so ice on a body with no ocean mask is blended against an all-False
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

    `vocabulary` is the CALLER'S stage view — `PLANET_LAYERS` or `CAP_LAYERS`, never
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
