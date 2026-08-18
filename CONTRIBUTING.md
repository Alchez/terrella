# Contributing

Terrella is one person's project for learning how relief maps get made, published so it can be read,
run and reused. Questions and issues are welcome. There is no promised review turnaround, and a large
pull request that was not discussed first will probably sit, so open an issue before building
anything substantial.

## What runs without the imagery

No rendered asset or elevation tile is in git, so a clone gets the code and none of the output. That
matters less than it sounds:

| To do this | You need | Costs |
| :-- | :-- | :-- |
| Run every check the project has | git, uv, pnpm | minutes |
| See the site in a browser | a local render store: the gallery manifest, hero images, three tile archives | an overnight render |
| Change how the maps look | the above, plus an NVIDIA GPU and Blender | days |

Only the last row needs hardware. The first is the entire test suite for both halves of the project,
the type checkers and the linters, and it passes on a fresh clone with nothing configured. If you are
fixing a bug, adding a test, tightening types or working on the tile server, that is the row you are
in, and you are not missing anything.

## Setup

```sh
git clone https://github.com/Alchez/terrella.git
cd terrella
uv sync              # Python: builds .venv from uv.lock
pnpm install -C web  # frontend: also applies a vendored MapLibre patch, explained in web/README.md
./scripts/check.sh
```

Node 22.12 or newer. pnpm's version is pinned in `web/package.json` and `uv sync` pins the Python
side from the lockfile, so neither is a choice you have to make.

## One command for every check

`./scripts/check.sh`, from the repo root. It runs every gate this project holds at zero, and it keeps
going after a failure so you see all of them at once instead of the first. When something fails it
prints the command to re-run just that gate, so you can iterate on one without paying for the rest.

Pass `--python` or `--web` to run one half. CI uses the same two halves, one per job, so what you run
locally is what will run on your pull request.

CI runs the same set on every pull request. Skipping it locally moves the failure later rather than
avoiding it.

## Tests that skip themselves

Some tests read source data that is not in git. Those skip rather than fail, and each one names the
artifact it wanted:

```sh
uv run pytest -rs
```

Skips there are expected on any machine without the data store, and the reasons are how you tell an
expected one from a broken setup. A failure is a different thing and is worth reporting.

## What is verified, and where

Linux. CI runs Ubuntu, and the render pipeline expects a Blender tarball at a fixed path. macOS and
Windows are neither tested nor knowingly supported, so treat them as unknown rather than broken. If
you get either working, that is worth an issue.

## Where the reasoning lives

`CLAUDE.md` is the standing brief: how the system is built, and which questions are settled. Read it
before proposing an architectural change, because several of the obvious ideas have been tried and
reverted, and it says which ones.

It does not carry everything. Much of the reasoning behind a given decision is not in this repository
at all, so when you cannot tell whether something has already been considered, open an issue and ask
instead of guessing. That is a far cheaper question than a rejected pull request.

Aesthetic decisions are in `ART.md`, measured stage runtimes in `PROCESS.md`, parked ideas in
`FUTURE.md`, and the frontend's own conventions in `web/README.md`. Anything that changes what the
site looks like is a judgement the maintainer makes by eye, so raise it before building it.

## Licences

Code is MIT. The rendered imagery is CC BY-SA 4.0, and the upstream data carries its own terms.
`ATTRIBUTIONS.md` has the required credit strings.
