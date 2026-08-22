---
name: reclaim-pass
description: Reclaiming disk from pipeline intermediates, experiment scratch or superseded worktrees. Load when asked to free space, clean up, or decide whether an artifact is still needed. Carries what may be deleted, what must be kept, and the order of operations that stops a reclaim from destroying the evidence behind a decision.
---

# Reclaiming disk

`INVENTORY.md` is the storage map: current sizes, what each store feeds, and which are reclaimable.
Read it first, and re-measure it afterwards. That is its maintenance contract, and a reclaim that
leaves it stale has moved the problem rather than solved it.

## The rule that decides almost every case

**The finding is the product; the pixels are not.** An experiment's outputs may be reclaimed as soon
as its decision is recorded, because the decision is what the work was for. Reclaim the rebuilt
delivery artifacts (tile trees, archives, mosaics) and keep:

- the scripts, so the arm can be run again,
- the judged images, which are the evidence behind the decision,
- the source rasters an arm was derived from, so the comparison rebuilds without a full pipeline run,
- the logs.

That combination usually turns a multi-gigabyte arc into a couple of hundred megabytes without
destroying anything a future reader would want.

## Before deleting anything

- **Size the need first.** Check `df` before proposing a reclaim. If the disk is not tight, hygiene rather than space is the motive, and the argument for deleting rebuilt artifacts is much weaker than the argument for removing a superseded runnable path.
- **A superseded worktree is a hazard rather than a saving.** It is a runnable copy of the pipeline with modified look code, and running the wrong one produces plausible output. Save its uncommitted diff to a file first, then remove it. The bytes are irrelevant; the ambiguity is the point.
- **Check for scripts and tracked files before removing a `work/` directory.** `ls` it for `.py` and `.sh`, and check `git ls-files`.
- **Deletion under gitignored `data/` is permanent.** There is no backup tier under it by design, so the decision has to be right the first time.

## Afterwards

Re-measure `INVENTORY.md`, and record the pass in the decision archive rather than in the storage
map. The map states current truth; the reasons a pass took what it took belong with the other
decisions.

## The gap worth knowing about

`INVENTORY.md` maps `data/` and nothing else. Scratch roots outside the repo are invisible to it, so
a reclaim there is a judgement rather than a lookup, and there is no rule that reaches them yet.
