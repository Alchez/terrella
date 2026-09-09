# How `pipeline/` is laid out

Where a module goes in the pipeline package, and why only one corner of it is grouped by planet. `pipeline/__init__.py` points here and does not restate any of it. Running the pipeline is [`pipeline.md`](pipeline.md); adding a body is [`adding-a-body.md`](adding-a-body.md).

Four kinds of thing live in the package, and which one a module is decides where it sits.

- **A sub-package holds stages that run.** Most are named for the step they perform, in roughly the order the data moves: `acquire` fetches published data, `fuse` welds land and sea into one heightfield, `frame` resolves a country into render parameters, `tile` cuts the raster pyramids, `compose` assembles the delivered vectors and image variants. `render` is the hero rig, one country into one Cycles image. Two are named for what they hold instead of for a step, `look` and `profile`.
- **A law or a seam at the top level of `pipeline/` is something more than one stage reads**: `mercator.py` owns the projection and the body radii, `raster_io.py` the windowed read. Reaching for a new one is a claim that a second reader exists, and the test is: change one copy, what goes red? Nothing red means it does not belong at the top level yet.
- **An entry point also sits at the top level, and the reader test above does not apply to it**, its reader count being zero by construction. `batch.py` is the runner and the documented way in.
- **A helper at the top level is reached for by a test or a hand-run probe, and by no stage.** `verify.py` is the one, a raster comparison built so that a check cannot quietly pass. It is not `profile/`, which measures what a run cost; this measures whether the output is what it should be.

**`look/` and `render/` are the pair most easily confused.** `look/` is what a surface is painted with and how it is lit, read by both rigs. `render/` is the hero rig plus `render_seam.py`, which names the files a render directory holds and is read by `batch`, `compose/`, `look/` and `tile/` as well. The dependency otherwise runs one way, `render` onto `look`, and a cycle between them means a module sits on the wrong side. `profile/` is instrumentation and produces nothing the site serves.

**No stage package is grouped by planet, and `acquire/` is the one exception.** Bodies are data and stages are code: a stage never branches on which body it holds, it reads a field. A dataset is the opposite, belonging to exactly one planet and to no other, which is why `acquire/earth/` and `acquire/mars/` are legitimate and `fuse/earth/` would not be. `install_geotools.sh` stays above them because it fetches a tool rather than a dataset.

What a planet is, has and requires is declared rather than filed, in three places:

- `bodies.Body`, its geometry and its exaggeration.
- `Body.surface_layers` against the `layers.Layer` vocabulary, which surfaces it has.
- `look/layer_producers.py` with `look/perennial_ice.py`, who builds each of those for it.

No field carries a default, so every one is a hard error until a new body answers for it. **Extending the `acquire/` grouping upward is the tempting shape**, and it states the same thing where nothing can check it: a body that had not answered would look like a body with fewer files, which is a defect a directory listing cannot report.

Each sub-package's own `__init__.py` states what that package holds, so the tree is readable from inside as well as from here.
