"""Where the prose sits, per module and per documented thing.

AN INSTRUMENT, NOT A GATE, and that distinction is the whole design. A ratio threshold would fail on
modules that are legitimately almost all prose — a constants file is one value and the paragraph that
makes it safe to change — and a guard that cries wolf gets ignored and then deleted, which
`scripts/sabotage.py` already records as this repo's own experience. So this prints and returns 0.

WHAT IT IS ACTUALLY FOR. A per-comment rule cannot see a cross-comment property: the same concept
re-established at every field that touches it leaves each individual comment correct and the file
unreadable. `--by-target` is the view that shows it, because one concept explained four times reads
as four separate well-documented fields until you line them up.

    python -m scripts.prose_report                 # per module, worst first
    python -m scripts.prose_report --by-target pipeline/bodies.py
"""

import argparse
import io
import tokenize
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def split_prose(source: str) -> tuple[int, int]:
    """(prose lines, code lines) for one module. Docstrings count as prose, blanks count as neither."""
    prose = 0
    for token in tokenize.generate_tokens(io.StringIO(source).readline):
        if token.type == tokenize.COMMENT:
            prose += 1
        elif token.type == tokenize.STRING and token.line.strip().startswith(('"""', "'''", 'r"""')):
            prose += token.string.count("\n") + 1
    live = len([line for line in source.splitlines() if line.strip()])
    return prose, max(live - prose, 1)


def by_target(source: str) -> list[tuple[int, str]]:
    """Prose lines attributed to the code line each block precedes — the cross-comment view.

    Attribution is positional rather than semantic: a comment block belongs to the next line of real
    code under it, which is how Python's own `#:` convention reads. Good enough to show one concept
    told at four sites, which is the only question this view is asked.
    """
    blocks: list[tuple[int, str]] = []
    pending = 0
    for line in source.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith(("#", '"""', "'''")):
            pending += 1
            continue
        blocks.append((pending, stripped[:70]))
        pending = 0
    return sorted(blocks, reverse=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--by-target", metavar="MODULE",
                        help="attribute one module's prose to what it documents")
    parser.add_argument("--package", default="pipeline", help="package to sweep (default: pipeline)")
    parser.add_argument("--top", type=int, default=12, help="rows to print (default: 12)")
    args = parser.parse_args()

    if args.by_target:
        path = (ROOT / args.by_target).resolve()
        rows = by_target(path.read_text(encoding="utf-8"))
        print(f"{path.relative_to(ROOT)} — prose lines per documented thing\n")
        for count, code in rows[:args.top]:
            if count:
                print(f"  {count:4d}   {code}")
        print("\n  Same concept appearing against several targets is one concept without a home.")
        return 0

    total_prose = total_code = 0
    rows = []
    for path in sorted((ROOT / args.package).rglob("*.py")):
        prose, code = split_prose(path.read_text(encoding="utf-8"))
        total_prose += prose
        total_code += code
        rows.append((prose / code, prose, code, path.relative_to(ROOT)))

    print(f"{args.package}/: {total_prose} prose / {total_code} code "
          f"= {total_prose / total_code:.2f} lines of English per line of Python\n")
    for ratio, prose, code, relative in sorted(rows, reverse=True)[:args.top]:
        print(f"  {ratio:6.2f}x  {prose:5d} prose /{code:5d} code   {relative}")
    print("\n  A high ratio is a QUESTION, not a verdict: ask whether one concept is being"
          "\n  re-established at each site, or whether the file is genuinely that dense.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
