# Contributing

Terrella is one person's project for learning how relief maps get made, published so it can be read, run and reused. Questions and issues are welcome. There is no promised review turnaround, and a large pull request that was not discussed first will probably sit, so open an issue before building anything substantial. Bug fixes, tests, documentation and macOS or Windows portability are all welcome as they come. Anything that adds a feature or replaces a subsystem should start as an issue: this is a learning project, and a pull request that hands over a piece the maintainer has not worked through yet defeats what it is for.

By opening a pull request you license your contribution under this project's MIT license, and confirm you have the right to do so.

## What runs without the imagery

No rendered asset or elevation tile is in git, so a clone gets the code and none of the output.

| To do this | You need | Costs |
| :-- | :-- | :-- |
| Run every check the project has | git, uv, pnpm | minutes |
| See the site in a browser | a local render store, which nothing ships: the gallery manifest, hero images, three tile archives | the two rows below |
| Change how the globe's tiles look | the source data and the fused heightfield, an NVIDIA GPU and Blender: every tile block is raytraced | a night per body, then a re-cut and a deploy |
| Change how the gallery's renders look | the above, at 8K per country | days |

The first row runs on a fresh clone with nothing configured, and it is both test suites, the type checkers and the linters. Everything under it needs the render store, and since nothing ships one, the bottom two rows are how you get the second.

## Setup

```sh
git clone https://github.com/Alchez/terrella.git
cd terrella
uv sync              # Python: builds .venv from uv.lock
pnpm install -C web  # frontend: also applies a vendored MapLibre patch, explained in web/README.md
./scripts/check.sh
```

Node 22.12 or newer. pnpm and the Python toolchain are pinned by `web/package.json` and the lockfile.

## Platforms

Linux only, so far. CI runs Ubuntu, and the render pipeline expects a Blender tarball at a fixed path. macOS and Windows are untested rather than known-broken, so getting either working is worth an issue.

## One command for every check

`./scripts/check.sh` from the repo root runs every gate this project holds at zero. It keeps going after a failure so you see all of them at once, and prints the command to re-run just the one you are fixing. Pass `--python` or `--web` for one half, which is how CI runs them: one per job.

## Tests that skip themselves

Some tests read source data that is not in git. Those skip rather than fail, and `uv run pytest -rs` names the artifact each one wanted, which is how you tell an expected skip from a broken setup. A failure is a different thing and is worth reporting.

## Changing how it looks, without being able to render it

You can run almost all of the pipeline: stage logic is tested against synthetic rasters in a temp directory rather than against the render store. What you cannot do is render, so the question a reviewer needs answered is whether your change moves pixels.

Part of that is answered without a GPU. `tests/curve_fingerprint.json` holds every pure transform in `pipeline/look/` sampled over a fixed domain, computed from the code alone.

- **The samples move**: the test fails and names the transforms whose output changed. If that was deliberate, regenerate with `uv run python -m scripts.curve_fingerprint --write` and commit the result in the same change, so the diff says what the change costs.
- **The samples do not move**: nothing in that registry computes differently. That is not the same as leaving the output alone, and the difference is worth stating in your pull request. A change to how a transform is called, to the Blender shader graph, or to anything under `pipeline/fuse/`, moves pixels and moves no sample here.

Two things follow. Reviewing a look change means reading the arithmetic, because no gate covers the parts listed above. And a change that alters what the globe looks like needs a rendered frame the maintainer judges by eye, which is a conversation worth having in an issue before you build it.

## AI-assisted contributions

AI coding tools are welcome. This project was largely built with them, so this is about review, not purity.

- **You can explain and defend it, or it gets closed**, however it was produced.
- **Disclose assistance beyond single-line autocomplete**, and name the tool. It costs you nothing in review.
- **Write your own issue text and PR descriptions.** Spelling, grammar and translation tools are fine; lean hard against generated prose. The description is how a reviewer learns what you understood, and a generated one tells them nothing at the same reading cost.
- **Generated code still carries its provenance**, which is the work the licence line above is doing.

Adapted from MapLibre's AI policy, which this project follows when contributing upstream.

## Where the reasoning lives

`CLAUDE.md` is the standing brief: how the system is built, and which questions are settled. Read it before proposing an architectural change, because several of the obvious ideas have been tried and reverted and it says which ones. The README's *Read next* indexes everything else.

Two more places carry what only matters sometimes, and both are tracked so you get them in a clone. `.claude/rules/` holds notes that load when a matching file is opened, such as the tile Worker's constraints when you open Worker code. `.claude/skills/` holds notes that load when a matching task starts, such as driving Blender or acquiring a source dataset. They exist so `CLAUDE.md` can stay short enough to be read: a topic lives in exactly one of the three, and moves between them rather than being copied. If you are working by hand rather than with an agent, read them as ordinary documents; the README indexes them.

It does not carry everything, and much of the reasoning behind a decision is not in this repository at all. When you cannot tell whether an idea has already been considered, `FUTURE.md` is the place to look: it holds the ideas that were analysed and parked, and the ones that were tried and rejected, each with the record of why. When it does not answer you, open an issue and ask: that is a far cheaper question than a rejected pull request. Anything that changes what the site looks like is a judgement the maintainer makes by eye, so raise it before building it.
