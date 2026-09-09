# Adding a body

What a moon or another planet has to answer for before it can be drawn, and what nothing will ask it for. Mars is the only body ever added here. Where the code lives is [`pipeline-layout.md`](pipeline-layout.md); running a pass is [`pipeline.md`](pipeline.md).

Three groups below, separated by **whether anything will tell you that you skipped it** rather than by difficulty. Making the seams body-agnostic was the expensive part and it is done, so what is left is answering for your body at each one, plus a last group with no seam to answer at.

The groups are re-derivable rather than maintained by hand: the first is every total registry keyed by body, which `Record<BodySlug` under `web/src` and the `_BY_BODY` registries under `pipeline/` enumerate between them.

**Rehearse with a body that does not exist, which needs no data at all.** Both halves of the first group answer out of a module-level table, so the whole of it can be walked before a byte is acquired.

- **Python**: `tests/test_third_body_dry_run.py` registers a Mars-like body from one `dataclasses.replace` and walks it through every registry. A `Body` is a frozen dataclass of scalars, so no raster is involved. Put your own numbers in it and the suite names what is unanswered.
- **TypeScript**: add your slug to the `BodySlug` union in `web/src/lib/bodies.ts` and run `pnpm -C web run check`. Every `Record<BodySlug, …>` fails at once and the compiler prints the list. Revert the union afterwards.

**Refuses to run until you answer it.** Half-adding a body is not possible here, which is what each of these being total buys.

| Answer | Where | If you skip it |
| :-- | :-- | :-- |
| every field, no defaults | `bodies.Body` | hard error; a hierarchy is refused for the same reason |
| the rasters emitted, declared last | `planet_seam.PLANET_RASTERS` | consumers refuse to run, and only the heightfield is mandatory |
| the look | `palette.LOOK_BY_BODY` | named raise listing the known bodies |
| a producer per declared surface layer | `layer_producers.PRODUCER_BY_BODY_LAYER` | named raise carrying the body and layer |
| cap ice per pole, if that layer is declared | `perennial_ice.CAP_ICE_BY_BODY` | named raise |
| credits per archive layer | `attribution.CREDITS`, regenerated into `web/src/data/attributions.json` | `KeyError` in Python, then an implicit-any index error in `archiveIndex.ts` |
| the slug, then chrome colours | `BodySlug`, then `bodies.ts` | compile error at every `Record<BodySlug, …>` at once |
| About content | `aboutContent.ts` | compile error |
| published archives | `tileAddress.ts` | compile error |
| vector product and roles | `sourceLayers.ts` | compile error |

**Absence is the default, and what differs is whether anything says so.** These are the ones to walk deliberately, and they are why this is a list rather than a tickbox: skip one and it still renders, and a render that is wrong looks like a render.

- **`paintedLayers.ts` is a consent ledger, so a new body starts with nothing approved.** Every entry names its bodies one by one, and a body in none of them paints nothing, which is the right default for a planet whose pixels nobody has seen. `paintedLayers.test.ts` announces a body that appears in no entry, so the absence stays a prompt rather than an oversight.
- **`cap_render.POLE_SMOOTH_BY_BODY` is read with `.get`**, so a body absent from it is smoothed not at all. Earth belongs absent, its poles not being reconstructed from an altimeter that missed them, so a third body's absence is a decision rather than an omission.
- **`terrainSource.RATIFIED_TERRAIN_EXAGGERATION` is a `Partial` record**, the one deliberate hole in the `Record<BodySlug, …>` scheme, so a body it does not name gets a flat globe and no compile error. The exaggeration has to be ratified by eye, and shipping displacement nobody has looked at is the worse failure.
- **`featureOverlay.ts` is Mars's and `countryHighlight.ts` is Earth's, and neither is a generalisation of the other**, which each states in its own text: Earth's stack filters to the hero manifest and hit-tests against fat per-island circles baked into the archive, and Mars's archive can answer neither. They share the transport and the role vocabulary, held by `vectorTiles.ts` and `sourceLayers.ts`. **A third body with named features writes its own sibling against those two** rather than widening either.

**No seam at all, and this is the unbounded group.** Nothing below asks, and nothing below is a registry:

- A colour ramp and an ice white, ratified by eye rather than derived.
- A cryosphere rule, if it has one.
- A vector layer, and a gazetteer if it is to carry labels.
- Its own page, and credits carrying each source's own licence terms.
- Archives, and a deploy.

**The rehearsal above reaches none of this**, which is the boundary of what a dataless walk buys. **How much a third body inherits here is unmeasured**, nobody having tried one, and `PROCESS.md`'s two planet columns do not answer it either: they price a body's pass, never its arrival. → HISTORY, *the second body's page*.

**One precondition decides which producer you need, and it is not resolution.** Earth's is a 648-cell fusion of two datasets; Mars's is `fuse/relabel_mars.py`, a few lines that declare a published lon/lat raster to be EPSG:4326 and resample nothing.

- **That relabel is honest only on a true sphere.** Declaring EPSG:4326 over a grid on an ellipsoid shifts every latitude silently, a geodetic latitude on one figure being a different angle on another.
- **`download_mars_dem.assert_grid` is the check written down**, and it is the first thing to run against a candidate source.
- **Whether the Moon, Venus or Titan passes it is not recorded here**, none having been tried.
