"""Structural integrity of every tracked text file — the guard for bulk-edit corruption.

WHY THIS EXISTS
---------------
A repo-wide regex intended to strip trailing citations was written with an unbounded tail
(`[^\\n]*?(?=$)` — "eat to end of line"). It described where a match STARTED and never where it
had to STOP, so on any line where the citation sat mid-sentence it took the rest of the line with
it. Thirty files were rewritten before a single byte was reviewed. Four distinct kinds of damage
came out of one bug:

  1. a `*/` that lived on a stripped line, which silently commented out the REST OF THE FILE —
     `terrainSource.ts` lost every export below the wound and produced 10 type errors;
  2. closing `|` clipped off three markdown table rows;
  3. sentences truncated mid-clause in prose;
  4. an unbalanced backtick left a code span open across the remainder of a document.

Every existing gate ran clean before this was noticed, because `pyright`, `pytest` and
`astro check` cannot see prose, and the type errors only surfaced once the comment wound happened
to swallow an export. **The lesson is that a text transform needs a text oracle**, and this is it:
cheap, mechanical invariants that hold for every file in the repo whether or not any test reads it.

It cannot catch a truncated sentence that stays grammatical — nothing mechanical can. It catches
every damage class above except (3), which is the part that silently changes what the code MEANS.

A fifth check was written and DELETED rather than shipped: "no line ends in a severed connective".
Measured against the real repo it fired **463 times on a trailing `(` alone** and 96 on `[`, because
that is simply how a wrapped call is written; even the narrow `→`/`·`/`§` form had 6 hits, all
legitimate prose wraps. A guard that cries wolf gets ignored and then deleted, so it was deleted
here instead — the honest coverage statement is that severed PROSE is caught by review against a
baseline, not by this file.
"""

import re
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]

# Text formats where these invariants are meaningful. Lockfiles and generated JSON are excluded:
# they are machine-written and their delimiters are not prose.
CHECKED_SUFFIXES = {".md", ".py", ".ts", ".astro", ".sh", ".toml", ".css", ".mmd"}
EXCLUDED = {"web/pnpm-lock.yaml", "uv.lock"}


def tracked_text_files() -> list[Path]:
    """Every tracked file we hold to these invariants, plus CLAUDE.md when it is not yet staged."""
    listing = subprocess.run(
        ["git", "ls-files"], cwd=REPO, capture_output=True, text=True, check=True
    ).stdout.split()
    # PLAN.md and HISTORY.md are deliberately NOT tracked, which means git cannot recover them and
    # cannot show what a bulk edit did to them. They therefore need these invariants MORE than the
    # tracked files, not less — included when present, silently absent on a clone.
    names = set(listing) | {"CLAUDE.md", "PLAN.md", "HISTORY.md"}
    return [
        REPO / name
        for name in sorted(names)
        if name not in EXCLUDED
        and Path(name).suffix in CHECKED_SUFFIXES
        and (REPO / name).is_file()
    ]


FILES = tracked_text_files()


def with_suffix(*suffixes: str) -> list[Path]:
    """The subset a check applies to, selected at COLLECTION time rather than skipped in the body.

    The difference is diagnostic, not cosmetic. Skipping inside the test produced 652 no-op skips
    in CI — four fifths of the matrix — and they buried the 13 skips that carry real information
    (the data-bound and GDAL-version tests a reader is supposed to notice). A signal that fires
    constantly trains the eye to skip the one time it mattered.
    """
    return [path for path in FILES if path.suffix in suffixes]


BLOCK_COMMENT_FILES = with_suffix(".ts", ".astro", ".css")
DECLARATION_FILES = with_suffix(".ts", ".astro")
TABLE_FILES = with_suffix(".md")
FENCE_FILES = with_suffix(".md", ".mmd")

# Files whose job is to NAME the forbidden pattern, plus the unshipped working documents
# themselves. Held as one visible list rather than four `pytest.skip` calls scattered through the
# body, so the exemptions can be audited in one place.
#
# `.gitignore` is deliberately absent: its suffix is "" (a leading dot with no extension), so it is
# never in CHECKED_SUFFIXES and never collected. It carried a skip branch here that could not
# execute — a guard clause for a case that never arrives reads as coverage and is not.
CITATION_EXEMPT = {
    "PLAN.md",                  # the working documents ARE the archive; they cite each other
    "HISTORY.md",
    "test_repo_integrity.py",   # a guard must state the pattern it forbids
    "sabotage.py",              # a mutation table must hold the needle verbatim
}
CITATION_FILES = [path for path in FILES if path.name not in CITATION_EXEMPT]

# The investigation directories under gitignored `data/` — prototypes, scouts, and their notes.
# A clone has none of them, so citing a file inside one is the same unfollowable pointer as citing
# a working document, and it reached committed code six times before this line existed.
#
# NAMED RATHER THAN PATTERNED, WHICH IS MEASURED AND NOT PREFERENCE. The obvious generalisation —
# "a path segment under `data/` beginning with an underscore" — fires 32 times on this repo, on
# `node_modules/`, `_astro/`, `_tiles/planet.pmtiles` and `ne_10m_coastline/`: the underscore prefix
# marks GENERATED OUTPUT here far more often than it marks scratch, and those references are all
# legitimate. A guard that cries wolf gets ignored and then deleted, as the module note records.
#
# The trailing slash is load-bearing: it distinguishes a path being CITED from the same bare name
# being passed as a directory-name argument, which `scripts/measure_viking_levels.py` legitimately
# does.
SCRATCH_DIRS = r"_ice_ab/|_ice_levels/|_ice_scout/|_viking_scout/|_crism_scout/"

CHECK_GROUPS = {
    "BLOCK_COMMENT_FILES": BLOCK_COMMENT_FILES,
    "DECLARATION_FILES": DECLARATION_FILES,
    "TABLE_FILES": TABLE_FILES,
    "FENCE_FILES": FENCE_FILES,
    "CITATION_FILES": CITATION_FILES,
}


def ids(paths: list[Path]) -> list[str]:
    return [str(path.relative_to(REPO)) for path in paths]


def test_no_check_is_vacuous() -> None:
    """Every check must have files to check.

    Selecting at collection time buys quiet runs and costs a failure mode: `parametrize` over an
    EMPTY list collects zero tests and reports success. A suffix typo would silently retire a
    check while the suite stayed green — the exact shape of guard this file exists to prevent.
    """
    empty = sorted(name for name, group in CHECK_GROUPS.items() if not group)
    assert not empty, (
        f"{empty} selected no files, so the corresponding check(s) ran against nothing and "
        f"passed vacuously. A suffix filter stopped matching."
    )


def block_comment_spans(source: str) -> tuple[list[tuple[int, str]], int | None]:
    """Every real block comment as (start line, body), plus the line of one left unclosed.

    ONE parser, used by both checks. The first version of the swallowed-declaration check used a
    separate `/\\*.*?\\*/` regex and immediately produced false positives on `//` comments that
    happen to contain the characters — two parsers for one construct is two chances to be wrong.
    """
    spans: list[tuple[int, str]] = []
    line, index, opened_at, start = 1, 0, None, 0
    in_block = in_line = False
    quote: str | None = None
    while index < len(source):
        char = source[index]
        pair = source[index:index + 2]
        if char == "\n":
            line += 1
            in_line = False
            # A `"` or `'` string cannot contain a raw newline in JS/TS, so arriving here still
            # "inside" one means the opening quote was never a string at all. In practice it is a
            # quote character inside a REGEX literal — `/data-body="([^"]+)"/` opens, closes and
            # opens again — which this parser deliberately does not model, because telling a regex
            # from a division needs the grammar.
            #
            # DROPPING THE BAD GUESS HERE IS WHAT KEEPS IT LOCAL. Left standing, the phantom quote
            # runs until some later line happens to contain the same character, and every `/*` in
            # between is invisible — so the parser reports an unclosed comment at a line whose only
            # crime is being the first `/*` it could finally see. That is how this was found: a new
            # test title with an apostrophe in it was blamed for a regex ninety lines above.
            if quote in ('"', "'"):
                quote = None
        elif in_line:
            pass
        elif in_block:
            if pair == "*/":
                spans.append((opened_at or line, source[start:index]))
                in_block, opened_at = False, None
                index += 2
                continue
        elif quote:
            if char == "\\":
                index += 2
                continue
            if char == quote:
                quote = None
        elif pair == "/*":
            in_block, opened_at, start = True, line, index + 2
            index += 2
            continue
        elif pair == "//":
            in_line = True
            index += 2
            continue
        elif char in "\"'`":
            quote = char
        index += 1
    return spans, opened_at


def test_a_quote_inside_a_regex_literal_does_not_swallow_the_rest_of_the_file() -> None:
    """The parser's own blind spot, bounded to the line that has it.

    It does not model regex literals, and it cannot cheaply: telling `/x/` from a division needs the
    grammar. So a regex holding quote characters — `/data-body="([^"]+)"/` opens one, closes it and
    opens another — leaves the scanner believing a string is open. What matters is not that the
    guess is wrong but that it EXPIRES: a `"` string cannot span a line in JS, so the newline ends
    it.

    Left standing instead, the phantom runs to whatever line next contains that character, every
    `/*` in between reads as ordinary text, and the first one it can finally see is reported as an
    unclosed comment. The blame lands on a line that is perfectly correct — which is exactly what
    happened, ninety lines downstream, to a test title whose only fault was an apostrophe.
    """
    source = 'const styled = /:root\\[data-body="([^"]+)"\\]/g;\nconst path = "a/*b";\n'
    spans, opened_at = block_comment_spans(source)
    assert opened_at is None
    assert spans == []


@pytest.mark.parametrize("path", BLOCK_COMMENT_FILES, ids=ids(BLOCK_COMMENT_FILES))
def test_block_comments_are_closed(path: Path) -> None:
    """No block comment runs to end of file.

    This is the one that hurt: an unclosed block comment does not fail to parse, it swallows
    everything after it. The file still compiles; the declarations below simply cease to exist,
    and the error surfaces somewhere else entirely as "has no exported member".
    """
    _, opened_at = block_comment_spans(path.read_text(encoding="utf-8"))
    assert opened_at is None, (
        f"{path.name}: block comment opened at line {opened_at} is never closed — everything "
        f"below it is silently commented out."
    )


# A doc comment never contains a top-level declaration. If one does, a `*/` went missing upstream
# and the comment has swallowed real code — which is the damage that actually happened here and
# which the end-of-file check above CANNOT see, because the next comment's terminator closes the
# wound and the file still parses. Found by mutation-testing this file against the real corruption.
SWALLOWED = re.compile(
    r"^\s*(?:export|import|function|class|interface|enum)\s|^(?:const|let|var|type)\s", re.MULTILINE)


@pytest.mark.parametrize("path", DECLARATION_FILES, ids=ids(DECLARATION_FILES))
def test_no_block_comment_swallows_a_declaration(path: Path) -> None:
    """No block comment contains a top-level declaration.

    The signature of a deleted `*/`. `terrainSource.ts` lost two terminators to a bulk edit and
    the comments below them ate `export const TERRAIN_MAX_ZOOM` and `export const
    TERRAIN_TILE_SIZE`; nothing failed to parse, and the error surfaced ten call sites away as
    "has no exported member".
    """
    spans, _ = block_comment_spans(path.read_text(encoding="utf-8"))
    offenders = [
        (line, found.group(0).strip())
        for line, body in spans
        if (found := SWALLOWED.search(body))
    ]
    assert not offenders, (
        f"{path.name}: block comment at line {offenders[0][0]} contains a declaration "
        f"({offenders[0][1]!r}) — a closing '*/' is missing above it and real code is commented out."
    )


@pytest.mark.parametrize("path", TABLE_FILES, ids=ids(TABLE_FILES))
def test_markdown_table_rows_are_terminated(path: Path) -> None:
    """A row that starts with `|` ends with `|`.

    A clipped trailing pipe merges the last cell into the row's rendering and silently drops a
    column — invisible in a diff read quickly, and invisible to every other gate.
    """
    offenders = [
        (number, line)
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1)
        if line.startswith("|") and not line.rstrip().endswith("|")
    ]
    assert not offenders, f"{path.name}: unterminated table row(s) at " + ", ".join(
        f"line {number}" for number, _ in offenders
    )


@pytest.mark.parametrize("path", FENCE_FILES, ids=ids(FENCE_FILES))
def test_code_fences_are_balanced(path: Path) -> None:
    """``` fences pair up, so a document cannot end mid-code-block."""
    fences = sum(
        1 for line in path.read_text(encoding="utf-8").splitlines() if line.lstrip().startswith("```")
    )
    assert fences % 2 == 0, f"{path.name}: {fences} code fences — one is unclosed"


@pytest.mark.parametrize("path", CITATION_FILES, ids=ids(CITATION_FILES))
def test_no_reference_to_a_file_a_clone_will_not_have(path: Path) -> None:
    """Tracked files must not cite the working documents or the scratch dirs, none of which ship.

    A pointer a reader cannot follow is worse than no pointer: it asserts that an explanation
    exists somewhere reachable. The exemptions live in CITATION_EXEMPT above; none of them ships
    an unfollowable pointer to a reader, they only describe one.

    THE SCRATCH HALF HAS A SHARPER FAILURE THAN THE DOCUMENTS HALF. A working document is merely
    absent from a clone; a prototype script can also STOP RUNNING while the sentence pointing at it
    stays fluent. Two of the six that triggered this rule imported a module deleted with OMEGA, so
    they were dead for their own author and read as reachable anyway. Where such a script owns
    something shipped code depends on, the fix is to track it — `scripts/measure_viking_levels.py`
    is that promotion — and not to reword the pointer.
    """
    source = path.read_text(encoding="utf-8")
    unreachable = re.findall(
        r"HISTORY\.md|HISTORY §|HISTORY 20\d\d|PLAN\.md|PLAN §|see PLAN|claude-personal"
        rf"|{SCRATCH_DIRS}", source
    )
    assert not unreachable, (
        f"{path.name} cites {sorted(set(unreachable))}, which no clone will have. "
        f"State the fact inline instead of pointing at it."
    )
