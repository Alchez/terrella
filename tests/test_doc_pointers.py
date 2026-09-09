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

#: A comment naming the test that guards the code it sits beside. Same trade as a document pointer,
#: and the same half is checkable: the name either resolves to a test or it does not.
TEST_CITATION = re.compile(r"\btest_[A-Za-z0-9_]{6,}")

#: A cited name wrapped across two lines leaves a trailing underscore before the break, which
#: `flattened` turns into `_ `. No identifier ends in an underscore and no prose puts a space after
#: one, so rejoining here is unambiguous, where joining on any break would fuse a name to the next
#: sentence. Both wrapped citations in `pipeline/` name tests that exist.
WRAPPED_NAME = re.compile(r"_\s+(?=[A-Za-z0-9_])")

#: Below this, a shared opening is a stray letter rather than a word. It bounds the SMALLEST legal
#: citation, `§ Snow`; what rejects a vague one is uniqueness, in `identifies_a_heading`.
MIN_OPENING_CHARS = 4

#: This file necessarily contains the patterns it searches for.
SELF = Path("tests/test_doc_pointers.py")

#: Not scanned, for the reason `test_repo_integrity.CITATION_EXEMPT` gives and owns: a mutation
#: table holds its needles verbatim, so it names unfollowable pointers without shipping one.
EXEMPT = {Path("scripts/sabotage.py")}

#: A path a doc names, in the other direction from every check above. Code extensions only: a doc
#: naming a `.json` or a `.tif` is a claim about an OUTPUT, which lives under gitignored `data/`
#: where absence is the normal state and proves nothing. Unbackticked too, because two of the
#: original defects were heading tails, `Fill sun — TILES (..., tile/shade.py)`.
CODE_PATH = re.compile(
    r"(?<![\w/.-])([A-Za-z0-9_][A-Za-z0-9_./-]*\.(?:py|ts|tsx|astro|sh|mjs))(?![\w-])"
)

#: What a doc says when it names a gone module ON PURPOSE. Taken from the sites already doing it:
#: CLAUDE.md's producer-seam note, PROCESS.md's two superseded rows, the prose-pass skill.
DELETION_MARKER = re.compile(r"deleted|superseded|orphan", re.IGNORECASE)

#: `FUTURE.md` names modules nobody has written yet and tooling outside the checkout, both by
#: design; requiring either to resolve would make the parking lot unwritable.
NAMES_WHAT_DOES_NOT_EXIST_YET = {Path("FUTURE.md")}

#: The ratified decision-archive pointer is `→ HISTORY, *the heading*`. The archive is gitignored,
#: so the heading is the whole of what a reader outside this checkout can follow, and a bare
#: pointer names nothing. The suffixed spelling is the clone check's to reject, not this one's.
ARCHIVE_POINTER = re.compile(r"\bHISTORY\b(?!\.md)(?!\s*,\s*\*[^*]{4,}\*)(.{0,40})")


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


def scanned_docs() -> list[Path]:
    """Every tracked markdown and diagram file whose paths are claims about the current tree."""
    named = (Path(name) for name in tracked() if name.endswith((".md", ".mmd")))
    return sorted(doc for doc in named if doc not in NAMES_WHAT_DOES_NOT_EXIST_YET and doc != SELF)


def names_a_tracked_file(token: str) -> bool:
    """Whether a doc's path token reaches a file, by full path or by basename.

    Basenames count because docs name `palette.py` far more often than they spell its directory,
    and a bare name that matches nothing is the defect either way.
    """
    name = token.lstrip("./")
    return name in tracked() or any(path.endswith(f"/{name}") for path in tracked())


def unfollowable_archive_pointers(text: str) -> list[str]:
    """Every decision-archive pointer in `text` that names no heading."""
    return [f"{match.group(0)}".strip() for match in ARCHIVE_POINTER.finditer(text)]


def test_every_module_a_doc_names_still_exists() -> None:
    """A doc naming a gone module points a reader at a file, which outranks merely stale prose.

    `ART.md` said `shade.py` held `LAKE_CURVE` when the constant had moved to `look/lake_depth.py`,
    which its own lever table already said, and gave three tuning recipes for a `--knob` flag the
    same file states twice was removed with the compositor. Nothing could go red: every check above
    follows code pointing at a document, and this is a document pointing at code.
    """
    offenders = [
        f"{doc}:{lineno}: {token}"
        for doc in scanned_docs()
        for lineno, line in enumerate((REPO_ROOT / doc).read_text().splitlines(), 1)
        if not DELETION_MARKER.search(line)
        for token in CODE_PATH.findall(line)
        if not names_a_tracked_file(token)
    ]
    assert not offenders, (
        "doc names a module that is not in the tree — point at its new home, or say on the same "
        "line that it is gone:\n  " + "\n  ".join(offenders)
    )


def test_a_decision_archive_pointer_names_its_heading() -> None:
    """A bare `→ HISTORY` resolves for the author and for nobody else.

    THE SYNTHETIC PAIR IS THE WHOLE PROOF, and it is not decoration. All three pointers in the tree
    are already in the ratified form, so the repo scan below cannot go red today and a green from it
    alone would say nothing about whether the pattern separates the two forms at all.
    """
    assert unfollowable_archive_pointers("the reasoning is in HISTORY, which you cannot open")
    assert not unfollowable_archive_pointers("→ HISTORY, *the caps raytrace at edge 84*, measured")

    offenders = [
        f"{path}: {pointer}"
        for path in scanned_files()
        for pointer in unfollowable_archive_pointers(flattened(path))
    ]
    assert not offenders, (
        "decision-archive pointer names no heading, so it is unfollowable from a clone — write "
        "`→ HISTORY, *the heading*`:\n  " + "\n  ".join(offenders)
    )


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


@cache
def known_test_names() -> frozenset[str]:
    """Every name a citation may legally resolve to: a test module, or a test function inside one.

    Both forms are cited in the tree and both are followable by grep, so both count.
    """
    names: set[str] = set()
    for path in sorted((REPO_ROOT / "tests").rglob("test_*.py")):
        names.add(path.stem)
        names.update(re.findall(r"^\s*def (test_\w+)", path.read_text(), re.MULTILINE))
    return frozenset(names)


def test_every_test_a_comment_names_still_exists() -> None:
    """A comment saying which test stops a mistake is worthless when the test was renamed under it.

    `cap_pass.py` named `test_the_shade_pass_hands_its_own_body_down_to_the_cap_pass` after the
    shade pass became the planet pass and the test went with it, so the one line telling a reader
    what holds `--body` required pointed at nothing.
    """
    offenders = [
        f"{path}: {name}"
        for path in scanned_files()
        for name in sorted(set(TEST_CITATION.findall(WRAPPED_NAME.sub("_", flattened(path)))))
        if name not in known_test_names()
    ]
    assert not offenders, (
        "comment names a test that does not exist — grep tests/ for the current name:\n  "
        + "\n  ".join(offenders)
    )


def docs_that_name_tests() -> list[Path]:
    """Every tracked markdown, `FUTURE.md` included.

    The parking lot is exempt from the path checks above because it names modules nobody has
    written yet. A test name is the opposite kind of citation: it names the guard that already
    covers a case, so there is nothing forward-looking for the exemption to protect.
    """
    return sorted(Path(name) for name in tracked() if name.endswith(".md") and Path(name) != SELF)


def test_every_test_a_doc_names_still_exists() -> None:
    """The same citation, one population over: a doc naming the guard that covers a case.

    `FUTURE.md`'s audit list named `test_exaggeration_is_shared` for months after the mutation case
    it belonged to was deleted, and the scan above could not reach it, its population being code.
    """
    offenders = [
        f"{path}: {name}"
        for path in docs_that_name_tests()
        for name in sorted(set(TEST_CITATION.findall(WRAPPED_NAME.sub("_", flattened(path)))))
        if name not in known_test_names()
    ]
    assert not offenders, (
        "a doc names a test that does not exist — grep tests/ for the current name:\n  "
        + "\n  ".join(offenders)
    )


#: A skill and the doc it routes to, where the skill must stay a strict subset. Both fire on one
#: task, so nothing can cut them apart by trigger and both fill up; the doc is the copy a clone
#: reads without a skill loader, so it is the one that owns the facts.
ROUTED_SKILLS = {".claude/skills/add-a-body/SKILL.md": "docs/adding-a-body.md"}

BACKTICKED = re.compile(r"`([A-Za-z_][A-Za-z0-9_./]*)`")


def test_a_routing_skill_names_nothing_its_doc_does_not() -> None:
    """A skill that grows its own facts is a second copy nothing holds to the first.

    These two reached 17 shared identifiers out of the skill's 22 with no guard between them, and
    the four it held alone were facts rather than procedure.
    """
    offenders = []
    for skill_path, doc_path in ROUTED_SKILLS.items():
        skill = BACKTICKED.findall((REPO_ROOT / skill_path).read_text())
        assert skill, f"{skill_path} names no identifiers; the scan matched nothing"
        doc = set(BACKTICKED.findall((REPO_ROOT / doc_path).read_text()))
        offenders += [f"{skill_path}: `{name}` is in no {doc_path}" for name in sorted(set(skill) - doc)]
    assert not offenders, (
        "a routing skill names what its doc does not, so the fact has no owner:\n  "
        + "\n  ".join(offenders)
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

    cited_tests = {
        name
        for path in scanned_files()
        for name in TEST_CITATION.findall(WRAPPED_NAME.sub("_", flattened(path)))
    }
    assert len(cited_tests) >= 20, f"expected many test citations, found {len(cited_tests)}"
    assert len(known_test_names()) > 100, "the test-name collector found almost nothing"

    named_modules = {
        token for doc in scanned_docs() for token in CODE_PATH.findall((REPO_ROOT / doc).read_text())
    }
    assert len(scanned_docs()) > 20, "the doc scan found almost nothing; check the tracked listing"
    assert len(named_modules) >= 100, f"expected many modules named in docs, found {len(named_modules)}"
