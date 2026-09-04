#!/usr/bin/env bash
# Every gate this project holds at zero, in one command, and the only place the list lives.
#
# WHY IT EXISTS. The list used to be prose in three places: CLAUDE.md, `web/README.md`'s command
# table, and `.github/workflows/ci.yml`. It had already drifted. `check_blender_drift.sh` runs on
# every pull request and appeared in neither doc, so anyone following the written list ran seven
# gates while CI ran eight. The docs now point here, and CI calls this.
#
# CI CALLS IT ONE HALF PER JOB, which is what `--python` and `--web` are for. Its two jobs run
# concurrently on separate runners; putting the whole script in one job would serialise them for no
# gain. The same split is the useful local one: run `--web` while you are only touching the
# frontend. Setup steps stay CI's own, because installing a toolchain is not a gate.
#
# COVERAGE IS CI POLICY, NOT A GATE THIS SCRIPT OWNS. `PYTEST_ARGS=--cov` is how CI adds its
# ratchet (`fail_under` in pyproject.toml, pinned to the CI-visible baseline: ratchet up, never
# down). A contributor should not meet a project-wide coverage floor as a failure on their own
# change, so the bare run is the default here.
#
# NOTHING BELOW NEEDS THE DATA STORE, a GPU, or Blender. Every gate passes on a bare clone; what a
# clone cannot do is render. Data-bound tests skip themselves and name the artifact they wanted,
# which `uv run pytest -rs` prints.
#
# SO NO GATE HERE CAN SEE A PIXEL, and that is a standing limit rather than a gap to close. Green
# says the code is consistent, never that the render is right; the only evidence for a look is an
# arm's own render, judged. In particular there is no byte-identity gate on Earth's output and never
# has been, so do not cite one.
#
# Runs every gate even after one fails, because the first failure is rarely the only one, and
# reports them together with the command to re-run each. Exit status is 0 only if all passed.

set -uo pipefail
cd "$(dirname "$0")/.."

WANT_PYTHON=1
WANT_WEB=1
case "${1:-}" in
  --python) WANT_WEB=0 ;;
  --web)    WANT_PYTHON=0 ;;
  "")       ;;
  *) echo "usage: ${0##*/} [--python | --web]" >&2; exit 2 ;;
esac

FAILED=()
RERUN=()
TOTAL=0

run() {
  local label="$1"
  shift
  TOTAL=$((TOTAL + 1))
  printf '\n==> %s\n' "$label"
  if ! "$@"; then
    FAILED+=("$label")
    # Keep the command beside the label, so a failure ends with something runnable. Reporting only
    # "ruff failed" makes the reader reconstruct an invocation this file already knows.
    RERUN+=("$*")
  fi
}

echo "Running the gates. None of them need the data store, a GPU or Blender:"
echo "a fresh clone passes all of these."

if [ "$WANT_PYTHON" = 1 ]; then
  # No path argument, deliberately: [tool.pyright] sets `include` to pipeline + tests and excludes
  # experiments. It was once `pyright pipeline/`, which skipped tests/ entirely, so a type error in
  # a test passed CI while failing a local run.
  run "pyright" uv run pyright

  # No path argument and no `select`: the rule set is ruff's own default from [tool.ruff.lint], and
  # the scan follows .gitignore, so the data store and the venv are out without being named. After
  # pyright because the two overlap least at the top, and a type error is the more informative
  # first failure.
  run "ruff" uv run ruff check

  # palette.py and the two bpy scripts must stay importable under Blender's bundled 3.13 while the
  # venv runs 3.14. The shared file list lives inside that script, so this and CI cannot disagree
  # about which files are shared.
  run "blender drift" bash scripts/check_blender_drift.sh

  # `testpaths` in pyproject.toml points at tests/, which is why this needs no path, and why the
  # `cd` at the top is load-bearing: from anywhere else pytest collects nothing and exits 5, which
  # reads like a pass. PYTEST_ARGS is unquoted on purpose so CI can pass more than one flag.
  # shellcheck disable=SC2086
  run "pytest" uv run pytest -q ${PYTEST_ARGS:-}
fi

if [ "$WANT_WEB" = 1 ]; then
  if [ ! -d web/node_modules ]; then
    echo "web/node_modules is missing. Run 'pnpm install -C web' first, or every web gate" >&2
    echo "below fails for that one reason." >&2
    exit 2
  fi

  # TWO PROGRAMS, and `pnpm check` runs both. `astro check` excludes worker/ on purpose, because
  # @cloudflare/workers-types redefines fetch/Response and breaks the site's program, so the Worker
  # carries its own tsconfig. For a while nothing ran that second one and nothing would have
  # noticed: wrangler's esbuild strips types without checking them, so a deploy ships regardless.
  run "astro check + worker" pnpm -C web run check

  # The web counterpart to ruff: the type-checkers ask whether the types line up, oxlint asks
  # whether the code says what it means. No path argument, so it walks from web/ and follows
  # .gitignore, reaching the .astro pages and the Worker that `astro check` excludes.
  run "oxlint" pnpm -C web run lint

  # A vitest project whose `include` matches nothing is absent from the run rather than an error:
  # green, exit 0, files silently uncollected, and `passWithNoTests` cannot be set per project.
  # Kept out of the suite, because a guard inside it would be dropped by the same broken glob it
  # exists to catch.
  run "test collection" pnpm -C web run check:test-collection

  # The `browser` project launches a real chromium. `pnpm install` fetches the playwright package
  # but never its browser binaries, so without them the project cannot start and the run reports a
  # smaller pass count alongside an unhandled launch error rather than failing. CI installs them in
  # its own step; locally it is `pnpm -C web exec playwright install --only-shell chromium`, once.
  run "vitest" pnpm -C web test
fi

if [ ${#FAILED[@]} -eq 0 ]; then
  printf '\n==> all %d gates green\n' "$TOTAL"
  exit 0
fi

printf '\n==> %d of %d gates FAILED. Re-run just the one you are fixing:\n' \
  "${#FAILED[@]}" "$TOTAL" >&2
for i in "${!FAILED[@]}"; do
  printf '      %-22s %s\n' "${FAILED[$i]}" "${RERUN[$i]}" >&2
done
exit 1
