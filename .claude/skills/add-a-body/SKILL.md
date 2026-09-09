---
name: add-a-body
description: Adding a third body (a moon or another planet) to Terrella, or changing a per-body seam. Load when registering a new body, when a change has to answer for every body rather than one, or when a compile error or a named raise arrives because a body has not answered. Carries the order the rehearsals run in and the four escape hatches that silence those errors while shipping another planet's answer.
---

# Adding a body

`docs/adding-a-body.md` is the checklist: what to answer, where it goes, and what happens if you skip it. Read it first. This skill carries only what that section is not, the order to work in and the ways a body-addition pass goes wrong while every gate stays green.

## Rehearse before acquiring anything

Both halves of the seam answer out of module-level tables, so the entire registry surface can be walked before a byte of data exists. Do this first; it is under an hour and it is the only part that gets cheaper by being early.

- **Python**: put your body's numbers into `tests/test_third_body_dry_run.py`, which registers a Mars-like body from one `dataclasses.replace` and walks it through every per-body registry. **Its population is derived by source scan and asserted set-equal to what it probes**, so a registry nobody thought about is red rather than skipped.
- **TypeScript**: add your slug to the `BodySlug` union in `web/src/lib/bodies.ts`, run `pnpm -C web run check`, read the list, revert the union. The compiler enumerates every `Record<BodySlug, …>` at once, and it reaches sites a `Record<BodySlug` grep cannot: `archiveIndex.ts` fails on a template-literal key.

Neither rehearsal reaches the group with no seam (a ramp, an ice white, a cryosphere rule, a gazetteer, a page, credits, archives, a deploy). That boundary is honest, not a gap to close.

## The four escape hatches

Every one of these silences a real error and ships a plausible planet wearing another body's answer. They are what a pass reaches for under pressure, because the error goes away and the gates go green.

- **`Partial<Record<BodySlug, …>>` instead of a total record.** Silences the compile error and gives the new body silent absence. `terrainSource.RATIFIED_TERRAIN_EXAGGERATION` is the one legitimate instance and it is legitimate for a stated reason: the exaggeration has to be ratified by eye, and a flat globe is better than displacement nobody has looked at. **Absence is only safe where absence is the designed answer and something says so.**
- **An optional field or an index signature on `BodyDescriptor`.** `bodies.ts` states this in its own header: both turn "adding a planet is a compile error until it answers" into silent inheritance, and the diff that adds the field then looks complete.
- **A fallback to Earth in a registry lookup.** `palette.look_for`'s docstring calls it "the tempting kindness". A body nobody registered then renders a plausible pyramid in Earth's colours with every gate passing, which was true of this repo until `test_third_body_dry_run.py` existed. **A named raise listing the known bodies is the required shape.**
- **A blanket in `paintedLayers.ts`.** That file is a consent ledger, not a render setting, so a blanket means inherited *approval*: a new body arrives pre-approved for layers on pixels the maintainer has never seen. Every entry names its bodies one by one. `paintedLayers.test.ts` goes red on both the blanket and on a body no entry mentions.

## Two refusals that look like gaps

- **`featureOverlay.ts` is Mars's and `countryHighlight.ts` is Earth's, and neither generalises the other.** Earth's stack filters to the hero manifest and hit-tests against fat per-island circles baked into the archive; Mars's archive can answer neither. **A third body with named features writes its own sibling** against the shared transport (`vectorTiles.ts`) and role vocabulary (`sourceLayers.ts`). Widening either module is the wrong move and both say so in their own text.
- **`acquire/` is grouped by planet and no other package is, which is a distinction to keep rather than a migration half done.** A dataset belongs to exactly one body (`attribution.SOURCES` is flat for that reason), so a third body writes `acquire/<slug>/` and nothing else moves. **A stage is the opposite**: no stage module compares a body against a literal, every one reads a field, and a directory has no equivalent of a hard error, so a body that had not answered would look like a body with fewer files. → HISTORY, *a per-body split of `pipeline/` is declined* for the stage half, and *the acquirers are grouped by body* for the exception.

## The precondition that decides the producer

It is not resolution. Mars's producer is a few lines because `fuse/relabel_mars.py` declares a published lon/lat raster to be EPSG:4326 and resamples nothing, **and that is honest only on a true sphere**. Over an ellipsoidal grid the same declaration shifts every latitude silently, a geodetic latitude on one figure being a different angle on another. `download_mars_dem.assert_grid` is that check written down and is the first thing to run against a candidate source. Nothing here records whether the Moon, Venus or Titan passes it.

## Before calling it done

- **A number ratified by eye is Rohan's call, not a default.** The ramp, the ice white and the terrain exaggeration all reach the globe, and nothing visible ships unratified.
- **Do not price the work off Mars.** The month Mars cost went on making the seams body-agnostic, which is paid and inherited, so it does not transfer. `PROCESS.md`'s planet columns price a body's *pass*, never its arrival.
