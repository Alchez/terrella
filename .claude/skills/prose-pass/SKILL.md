---
name: prose-pass
description: Cutting a module's comments and docstrings back to what the code cannot say for itself. Load when asked to reduce prose in a file, when a docstring is longer than the body it documents, or before writing a long one. Carries the order the checks run in, why that order is itself the finding, and the defect classes each one turns up.
---

# Cutting a module's prose

`python -m scripts.prose_report` ranks modules by prose against code, and `--by-target` attributes one module's prose to the thing each block precedes. Both are instruments rather than gates. A high ratio is a question, not a verdict: it asks whether one concept is being re-established at several sites, and the answer is sometimes that the file is genuinely dense.

## Two checks before deleting anything

- **Grep `scripts/sabotage.py` for needles anchored in this file's prose.** A needle is matched verbatim, so deleting a sentence a case quotes makes the harness report SKIP rather than go red, minutes into a run nobody is watching.
- **Grep `tests/` for any figure you mean to remove.** A number in prose is legitimate exactly when one copy is executable. Removing a block count from a docstring turned a guard red, correctly: a test pins that figure in two files because three docstrings once carried a value that had drifted by 4x.

## The four checks, in this order

The order is itself a finding. The fourth check is unreadable until the third has run.

1. **Predict the yield from the past-tense tells.** Grep the file's comments and docstrings for `used to`, `previously`, `no longer`, `earlier version`, `before that`, `had been`, `which was`. Zero hits means the file is dense rather than repetitive and the pass will find little. Forty means most of what is there is history. This separates the two cases in a way the ratio does not: one module at 1.20x had nothing left to cut while another at 2.75x had a third of itself in narration.
   - **It under-predicts on a constants block or a registry, which have no changes to narrate.** What those accumulate instead is the measurement behind each value, in the present tense and invisible to any tense grep: a census, a fitted exponent, an arithmetic derivation, a store size. `bodies.py` returned zero tells and still gave back 31 lines. On that shape, read the numbers instead of grepping the verbs.
2. **Check `.claude/rules/` for a doc whose frontmatter lists this file.** A path-scoped rule loads whenever the file is opened, so anything it already owns is a second copy. One rule owned seven of its five files' concepts, and the recipe derivation alone had three copies inside a single module. Replace each with what the code is plus one pointer: "the rule beside this file owns X".
3. **Lowercase every all-caps lead-in.** Emphasis by shouting is a tic rather than a signal, and lowercasing usually shortens the sentence, the shout having been doing the work the words should. A run of two or more consecutive all-caps English words, outside backticks and outside `SNAKE_CASE` identifiers, is the shape to look for.
4. **Scan the prose for retired symbol names.** Extract every `[A-Z][A-Z0-9_]{3,}` token from the file's comments and docstrings and ask whether it is assigned anywhere in the package. Nine dead names have turned up this way, most left behind when constants moved into a dataclass, and `SUN_ROTATION` alone survived in three separate files. This only works after step 3, and the cost of the wrong order is measured: on `snow.py` the scan returned 70 tokens before lowercasing, about 55 of them ordinary English in capitals, and 12 after, every one an acronym or a live constant.
   - **A module name is a symbol too, and a deleted one points at more than stale prose.** `snow.py` said *"the region path (shade.py) calls this"* in two docstrings; `shade.py` was deleted, and both functions saying it turned out to have no caller left. Resolve a cited caller before believing the citation, and resolve it by parsing `module.name` attribute access rather than by grepping the bare name, which counts every other module's identically named helper.

## What stays and what goes

`CLAUDE.md` states the bound, and the test for a sentence is whether it would sit comfortably in a decision-archive entry. In practice the same shapes recur.

Goes, every time:

- The measurement behind a decision. The rejection stays, phrased as the temptation and its consequence; the DN figures, the timings and the census counts are the archive's.
- Prose about prose. A docstring narrating what an earlier version of itself claimed is the purest case, and one module had two paragraphs of it.
- A second copy of a guard. If a test fails on the mistake, the comment restating it is not a belt and braces, it is a copy free to disagree.
- A restatement of the error message a few lines below. One docstring's closing two sentences were the `ValueError`'s own text.

Stays:

- What the code is, including the units, the ownership map, and which of two similar numbers this one is.
- The anti-redo, and it names the temptation rather than the prohibition: say what the rejected thing was, why re-adding it looks right, and what breaks.
- The silent-failure clause. "This renders as a plausible wrong planet" is why a reader should care, and no test carries it.

## Where prose hides that is not a docstring

- **`help=` strings in an argparse parser.** One flag told a reader the run "declares no producer" when no run declares one at all. These reach a user, so they rot louder than a comment.
- **Comment blocks stacked above a statement they do not describe.** Attribution is positional, so a paragraph about a mechanism that has been deleted keeps sitting above whatever line moved up under it. Grep the API a comment names before believing the comment.
- **A figure repeated in the same file.** Two comments eighty lines apart gave the same grid's floor as -3,565 m and -2,967 m. Neither was executable, so nothing could catch it.
