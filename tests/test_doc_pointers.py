"""Every pointer from code into a markdown doc still lands where it says it does.

WHY THIS EXISTS. Docs carry what code cannot say — a licence's citation obligation, a multi-page
geometry derivation, a colour judged by eye — so a module that needs one of those points at it
rather than restating it. That trades a DRIFT risk (two copies silently disagreeing) for a DANGLING
one (a pointer that stops resolving), and only the second is mechanically checkable. This checks it.

THE THREE ORIGINAL DEFECTS, so the shape is not re-derived later. `tile/shade.py` cited `ART.md:56`
and `ART.md:90`, both of which had become blank lines, and `look/hillshade.py` cited `ART.md:63` for
a claim about the sun's locked azimuth while that line had become a table row about the sea colour
ramp. The third is the one that matters: it still resolved to a real, plausible line, so following it
yielded a wrong association with no signal, where a blank line at least announces itself.

WHICH IS WHY LINE CITATIONS ARE BANNED RATHER THAN VALIDATED. Nothing can check that line 63 is
still ABOUT what the citer thinks; a heading can be checked, and a heading survives the edit that
moves it. ART.md took 42 commits in three months carrying 95 heading changes, so this is the live
case rather than a hypothetical.

MATCHING IS A SHARED PREFIX, and that is what removes the need for a citation delimiter. The
citation format is prose, so `§ Fill sun — TILES demands (tune the pair...` has no marker saying
where the heading name ends, and the heading it names carries a tail of its own,
`Fill sun — TILES (KNOBS["fill_strength"], tile/shade.py)`. Neither string contains the other, so
containment in either direction rejects every real citation in the repo. What they share is the
FRONT. A citation therefore resolves when the longest opening run it shares with any heading is
achieved by exactly ONE of them, which is also what lets a heading whose tail was edited keep
resolving: the tails are where these headings actually change, because they embed file paths and
those move.

HOW THIS DIVIDES FROM `test_repo_integrity.test_no_reference_to_a_file_a_clone_will_not_have`,
which came first and owns a different axis. That one forbids citing what does not ship, from an
enumerated list of working documents and scratch directories. This one asks the general form of the
same question — does the named document reach a fresh clone at all, by being TRACKED — and then the
part an enumeration cannot reach: whether the SECTION named inside it still exists. A file present
locally but untracked passes an existence check on the author's machine and fails in CI, so tracked
is the test rather than `is_file`.

PROSE IS OUT OF SCOPE, on `tests/test_paths.py`'s reasoning for the same choice. A doc quoting
another doc's old heading is a record, and editing a record to satisfy a scan corrupts the thing it
exists to keep.
"""

import re
import subprocess
from functools import cache
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

#: Where code lives. A pointer in one of these is followed by someone reading the code.
SCANNED_ROOTS = ("pipeline", "scripts", "web/scripts")

#: `.md` not followed by another word character, so `hashlib.md5()` and a `.tif.md5` sidecar are not
#: mistaken for documents. Both appear in the acquire modules.
DOC_REFERENCE = re.compile(r"((?:docs/)?[A-Za-z][\w-]*\.md)(?![\w])")

#: A citation that names a line. Banned outright: see the module note.
LINE_CITATION = re.compile(r"[A-Za-z][\w-]*\.md:\d+")

#: The section half of a citation, `FILE.md § Some Heading`. The trailing run is deliberately
#: generous because prose may continue straight on from it; bidirectional matching sorts it out.
SECTION_CITATION = re.compile(r"((?:docs/)?[A-Za-z][\w-]*\.md)\s*§\s*(.{4,120})")

#: A heading line in a markdown file.
HEADING = re.compile(r"^#+\s+(.*?)\s*$", re.MULTILINE)

#: Below this, a shared opening is a stray letter rather than a word. It bounds the SMALLEST legal
#: citation, `§ Snow`; what rejects a vague one is uniqueness, in `identifies_a_heading`.
MIN_OPENING_CHARS = 4

#: This file necessarily contains the patterns it searches for.
SELF = Path("tests/test_doc_pointers.py")

#: Not scanned, for the reason `test_repo_integrity.CITATION_EXEMPT` gives and owns: a mutation
#: table holds its needles verbatim, so it names unfollowable pointers without shipping one.
EXEMPT = {Path("scripts/sabotage.py")}


def scanned_files() -> list[Path]:
    """Every Python file under a scanned root, repo-relative, minus this file and the exemptions."""
    found: list[Path] = []
    for root in SCANNED_ROOTS:
        found.extend(sorted((REPO_ROOT / root).rglob("*.py")))
    paths = [p.relative_to(REPO_ROOT) for p in found]
    return [p for p in paths if p != SELF and p not in EXEMPT]


@cache
def tracked() -> frozenset[str]:
    """Every path git tracks, which is what a fresh clone actually receives."""
    listing = subprocess.run(
        ["git", "ls-files"], cwd=REPO_ROOT, capture_output=True, text=True, check=True
    )
    return frozenset(listing.stdout.splitlines())


def flattened(path: Path) -> str:
    """One line of text per file, comment markers removed.

    A citation may wrap across two comment lines or two docstring lines, and a per-line scan reads
    the fragment before the break as the whole heading name. `pipeline/__init__.py` wraps its own,
    and a per-line version of this check passed it only because `How` happens to prefix the real
    heading, which is a pass by accident rather than by validation.
    """
    lines = (REPO_ROOT / path).read_text().splitlines()
    return " ".join(line.lstrip().lstrip("#").strip() for line in lines)


def headings_of(document: Path) -> list[str]:
    """Every heading in a markdown file, in document order."""
    return HEADING.findall(document.read_text())


def shared_opening(cited: str, heading: str) -> str:
    """The run `cited` and `heading` share from the front, never ending inside a word.

    Backing off to a word boundary is what stops a coincidental partial word counting as a match: a
    citation of a since-renamed `Fill sun` against a heading `Fill light` shares `Fill ` and would
    otherwise score five characters of agreement it has not got.
    """
    size = 0
    while size < min(len(cited), len(heading)) and cited[size] == heading[size]:
        size += 1
    inside_word = (size < len(cited) and cited[size].isalnum()) or (
        size < len(heading) and heading[size].isalnum()
    )
    if inside_word:
        while size and cited[size - 1].isalnum():
            size -= 1
    return cited[:size].strip()


def identifies_a_heading(cited: str, headings: list[str]) -> bool:
    """Whether `cited` names exactly one of `headings`.

    UNIQUENESS IS THE BAR, not a length. A word count was tried first and rejected on a real case:
    it takes two words to tell ART.md's `Fill sun — TILES` from its `Fill sun — shadow floor`, but
    that same rule refuses the one-word `Borders`, which names its section perfectly well. What a
    citation owes is that it picks out one section, so that is what gets asserted — the LONGEST
    shared opening must be achieved by a single heading. `Fill sun` alone is then correctly refused
    for being ambiguous rather than for being short.
    """
    openings = [shared_opening(cited, heading) for heading in headings]
    longest = max((len(opening) for opening in openings), default=0)
    if longest < MIN_OPENING_CHARS:
        return False
    return sum(1 for opening in openings if len(opening) == longest) == 1


def resolve(name: str) -> Path | None:
    """The markdown file a citation names, tried at the repo root and under `docs/`.

    Resolution is against what git TRACKS rather than what is on disk, so a document that exists
    only on the author's machine does not let a pointer pass here and fail in a clone.
    """
    for relative in (name, f"docs/{name}"):
        if relative in tracked():
            return REPO_ROOT / relative
    return None


def test_no_pointer_cites_a_line_number() -> None:
    """A line citation cannot be validated and had already gone wrong at all three of its sites."""
    offenders = [
        f"{path}: {match}"
        for path in scanned_files()
        for match in LINE_CITATION.findall((REPO_ROOT / path).read_text())
    ]
    assert not offenders, (
        "cite a heading, not a line — `ART.md § Fill sun`, never `ART.md:56`:\n  "
        + "\n  ".join(offenders)
    )


def test_every_document_a_pointer_names_reaches_a_clone() -> None:
    """A pointer at a document git does not track asserts an explanation a reader cannot open."""
    offenders = [
        f"{path}: {name}"
        for path in scanned_files()
        for name in sorted(set(DOC_REFERENCE.findall((REPO_ROOT / path).read_text())))
        if resolve(name) is None
    ]
    assert not offenders, (
        "pointer names a document that no clone will have — state the fact inline instead:\n  "
        + "\n  ".join(offenders)
    )


def test_every_section_citation_lands_on_a_heading() -> None:
    """`FILE.md § Heading` names a real heading, by shared opening. See the module note."""
    offenders = []
    for path in scanned_files():
        for name, cited in SECTION_CITATION.findall(flattened(path)):
            document = resolve(name)
            if document is None:
                continue  # the test above owns this failure
            if not identifies_a_heading(cited, headings_of(document)):
                offenders.append(f"{path}: {name} § {cited[:60]}")
    assert not offenders, (
        "section citation matches no heading in the document it names:\n  " + "\n  ".join(offenders)
    )


def test_the_scan_reaches_the_pointers_it_claims_to_cover() -> None:
    """A positive control: prove the scan finds real citations rather than an empty set.

    Without this, every assertion above passes on a scan that silently matched nothing — a glob
    typo, a moved root, a regex that stopped compiling to what it used to. The counts are lower
    bounds rather than exact, so ordinary editing does not turn this into a chore.
    """
    documents, sections = set(), 0
    for path in scanned_files():
        if path == SELF:
            continue
        documents |= set(DOC_REFERENCE.findall((REPO_ROOT / path).read_text()))
        sections += len(SECTION_CITATION.findall(flattened(path)))

    assert len(scanned_files()) > 50, "the file scan found almost nothing; check SCANNED_ROOTS"
    assert {"ART.md", "ATTRIBUTIONS.md"} <= documents, f"expected pointers missing: {documents}"
    assert sections >= 3, f"expected several section citations, found {sections}"
