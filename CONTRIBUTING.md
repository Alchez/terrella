# Contributing

Terrella is one person's project for learning how relief maps get made, published so it can be read, run and reused. Questions and issues are welcome. There is no promised review turnaround, and a large pull request that was not discussed first will probably sit, so open an issue before building anything substantial. Bug fixes, tests, documentation and macOS or Windows portability are all welcome as they come. Anything that adds a feature or replaces a subsystem should start as an issue: this is a learning project, and a pull request that hands over a piece the maintainer has not worked through yet defeats what it is for.

By opening a pull request you license your contribution under this project's MIT license, and confirm you have the right to do so.

## What runs without the imagery

No rendered asset or elevation tile is in git, so a clone gets the code and none of the output.

| To do this | You need | Costs |
| :-- | :-- | :-- |
| Run every check the project has | git, uv, pnpm | minutes |
| See the globe in a browser | the three tile archives for one body, downloaded | minutes, plus a few GB of disk |
| See the gallery too | a local render store, which nothing ships: the manifest and the hero images | the two rows below |
| Change how the globe's tiles look | the source data and the fused heightfield, an NVIDIA GPU and Blender: every tile block is raytraced | a night per body, then a re-cut and a deploy |
| Change how the gallery's renders look | the above, at 8K per country | days |

The first row runs on a fresh clone with nothing configured, and it is both test suites, the type checkers and the linters. The second is the cheap way to see something: the tile archives are published, so a globe needs a download rather than a render store. Everything below that needs the store itself, and since nothing ships one, the bottom two rows are how you get it.

## Getting a globe without rendering one

The three archives for a body are downloadable from [terrella.alchez.dev/archives](https://terrella.alchez.dev/archives/), which lists each one with its size. Earth is about 5 GB across relief, terrain and vectors; Mars is under 2 GB. Put them where `web/README.md` says the dev server looks and the globe runs off your own disk.

**Do not point a build at the production tile endpoint.** It is open and it will answer you, so nothing stops you, which is why this says so. Every tile is one worker request against a daily allowance for the whole account, shared with the live site: a few sessions of panning can spend the day for everybody, and there is nobody to notice but the maintainer. Downloading an archive costs the project nothing and is faster for you.

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

## Changing the pipeline without the render store

You can run almost all of it. Stage logic is tested against synthetic rasters built in a temp directory rather than against the store, so with no data at all the Python suite passes but for the skips named above, and the web suite loses nothing. Every one of those skips asks the same question: does the real source behave the way the synthetic fixture assumes.

What you cannot do is render, so the question that matters is whether your change costs a re-render. Two committed files answer most of it without a GPU, each compared against the code by a test.

- **`tests/render_fingerprint.json` records the settings** stages write beside their outputs: sun angles, colours, thresholds. It answers whether you moved a value.
- **`tests/pixel_baseline.json` records what the look layers compute**, by running the shipped producers on a small synthetic window and digesting the result. It answers whether you changed a calculation, which no record of settings can see: changing the sea-ice curve from a smoothstep to a straight line moves every sea-ice pixel on Earth by up to 20.3 DN of white and leaves the settings file byte-identical.

Either going red means a pass is owed, and the failure names what moved and points at the cost in PROCESS.md. Regenerate with `uv run python -m scripts.render_fingerprint --write` or `uv run python -m scripts.pixel_baseline --write`, and commit the result in the same change so the diff says what it costs.

**Green on both is a necessary condition and not a sufficient one**, and if your change is in one of the gaps below, say so in your pull request, because nothing here can check it for you.

- **The Blender rig.** `scene_build.py` is the one stage that imports `bpy`, and the ramps, the sun and the exposure live in it. Nothing on a machine without Blender sees a change there.
- **A rendered frame,** which cannot be compared at all: Cycles is not bit-deterministic, so two runs of unchanged code do not produce identical pixels.
- **Everything the pixel baseline has no fixture for yet.** It covers the look layers. `pipeline/fuse/`, which welds the land and sea-floor data into the heightfield everything is rendered from, records no settings and has no fixture; the same technique reaches it and nobody has written it. The 203-country hero lane is in the same position.

Two things follow, and neither is a formality. Reviewing a pipeline change means reading the arithmetic the gates do not reach, and they now say which part that is. And a change that alters the look needs a rendered frame the maintainer judges by eye, which is a conversation to have in an issue before you build it.

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
