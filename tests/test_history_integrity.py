"""HISTORY.md — the archive is only useful if its index and its ordering can be trusted.

CLAUDE.md states three rules about this file, all of which have been broken at least once:

- **the index is added in the same edit as the entry.** An index that lags is worse than none,
  because it looks complete — and the real failure mode of a 57k-token log is not cost, it is
  not knowing an entry exists;
- **entries are cited by heading, never line number**, so every citation is an anchor link that
  has to resolve. Newest-first means every new entry shifts every line below it;
- **the log is newest-first.** A 07-24 entry was once filed above the 07-25 block and had to be
  moved by script.

Prose could not enforce any of them; these three tests can, and CI runs them. Deliberately no
allow-list: an entry that genuinely should not be indexed does not exist.
"""

import re
from datetime import date
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
HISTORY = REPO_ROOT / "HISTORY.md"

# Decision-log entries are level-3 headings; so are the index's topic sections, which is why
# the dated prefix — not the heading level — is what identifies an entry.
ENTRY_HEADING = re.compile(r"^### (?P<title>(?P<date>\d{4}-\d{2}-\d{2})\b.*)$", re.MULTILINE)
ANY_HEADING = re.compile(r"^#{2,3} (?P<title>.+)$", re.MULTILINE)
INPAGE_LINK = re.compile(r"\]\((#[^)]+)\)")


def github_anchor(heading: str) -> str:
    """GitHub's slug: lowercase, drop everything that is not word/space/hyphen, spaces to
    hyphens. Em-dashes and colons vanish in place, which is why a heading reads `--` in its
    own anchor."""
    slug = re.sub(r"[^\w\s-]", "", heading.strip().lower())
    return "#" + slug.replace(" ", "-")


def history_text() -> str:
    return HISTORY.read_text(encoding="utf-8")


def test_every_citation_resolves_to_a_heading() -> None:
    """No dangling `→ HISTORY § ...` link. A broken anchor is a citation to nothing."""
    text = history_text()
    anchors = {github_anchor(match.group("title")) for match in ANY_HEADING.finditer(text)}
    broken = sorted({link for link in INPAGE_LINK.findall(text) if link not in anchors})
    assert not broken, (
        f"{len(broken)} in-page link(s) resolve to no heading:\n  "
        + "\n  ".join(broken)
        + "\nAnchors are derived from the heading text — re-generate the link after any retitle."
    )


def test_every_entry_appears_in_the_index() -> None:
    """The rule that is easiest to forget: the index line ships with the entry, not after it."""
    text = history_text()
    linked = set(INPAGE_LINK.findall(text))
    missing = [
        match.group("title")
        for match in ENTRY_HEADING.finditer(text)
        if github_anchor(match.group("title")) not in linked
    ]
    assert not missing, (
        f"{len(missing)} entr(y/ies) are absent from the topical index:\n  "
        + "\n  ".join(title[:100] for title in missing)
        + "\nAdd the index line under its topic section in the SAME edit as the entry."
    )


def test_the_decision_log_is_newest_first() -> None:
    """Same-day entries compare equal, which is fine — only a true inversion fails."""
    text = history_text()
    dated = [
        (date.fromisoformat(match.group("date")), match.group("title"))
        for match in ENTRY_HEADING.finditer(text)
    ]
    inversions = [
        f"{earlier_title[:70]}… ({earlier}) sits above {later_title[:70]}… ({later})"
        for (earlier, earlier_title), (later, later_title) in zip(dated, dated[1:])
        if earlier < later
    ]
    assert not inversions, (
        f"{len(inversions)} out-of-order entr(y/ies) — the log is newest-first:\n  "
        + "\n  ".join(inversions)
    )
