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

## Delete by FILE, never by directory

A scratch root is not one thing: it is heavy data sitting beside the only copy of the instruments
that produced it. A sweep found ~40 `.py` and `.sh` files under `~/terrella-scratch/` that
`git ls-files` could not match anywhere in the repo, in the same directories as 45 GiB of
reclaimable rasters and tile trees.

- **Match the data by extension and size, then read the manifest before deleting it.** A find
  expression is the only form that can be reviewed for what it does NOT match; `rm -rf` on the
  directory cannot be reviewed at all.
- **Verify the manifest against what should have been excluded**, not only against what it caught:
  count the scripts, the judged images and the protected roots in it, and require zero.
- **Guard a bulk delete with a deny list, and check the list against the built manifest rather than
  against the find expression.** Guarding the expression asserts what was intended; guarding the
  manifest asserts what was produced, and the two differ exactly when a find is wrong.
- **A deny entry ending in `/` is a directory prefix; one without it is an exact path.** Matching
  every entry as a substring makes the entry for `planet.pmtiles` refuse `planet.pmtiles.old`, a
  different file one character shorter. Over-refusing is the safe direction and is still a bug,
  because it makes the list unreadable about what it protects.
- **Give the guard a selftest that feeds it a protected path and requires a non-zero exit**, and run
  it before every apply. A guard nobody has seen fail is decoration.
- **Watch for the tier that reads as empty when it is really broken.** A tier function ending in
  `[ -e "$f" ] && echo "$f"` returns non-zero once its last path is gone, and under `pipefail` plus
  `set -e` that stops the whole script after the first tier with exit 0 and no error. It looks
  exactly like "nothing left to reclaim".
- **Enumerate the bodies.** A tier that lists an artifact for Earth and forgets Mars leaves half the
  dead thing behind, and the omission is invisible in a listing that shows only what it found.

## Afterwards

Re-measure `INVENTORY.md`, and record the pass in the decision archive rather than in the storage
map. The map states current truth; the reasons a pass took what it took belong with the other
decisions.

**Re-measuring is not a sweep of every row: staleness concentrates in three shapes, and checking
those first finds most of it.**

- **A row outliving a deleted producer.** When a producer is deleted, grep the map for its outputs
  the same day. A row can go on reading "Keep: fresh" about a file that nothing writes and nothing
  reads, and its size is usually large, because producers that get deleted wrote big things.
- **A store that moved one level deeper than the row looks.** "Reclaimed" can mean "reclaimed from
  the path the row names", which is not the same claim.
- **"Transient by design" describing a run that SUCCEEDS.** Bridge formats and scratch directories
  are absent after a clean run and present after every other kind.

## The gap worth knowing about

`INVENTORY.md` maps `data/` and nothing else. Scratch roots outside the repo are invisible to it, so
a reclaim there is a judgement rather than a lookup, and there is no rule that reaches them yet.
