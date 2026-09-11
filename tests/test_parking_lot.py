"""`FUTURE.md`'s index and its entries agree, and every entry a stranger could pick up says so.

WHY THIS EXISTS. The tag list is the whole of what answers "may I work on one of these":
`no-data-needed` runs on a fresh clone and the rest do not, per the file's own § *How this file is
organised*. That answer is a pointer into a list rather than a sentence, so the list has to be right
about itself, and an index row and its entry's stanza are two copies of one fact with nothing that
could make them disagree loudly.

WHAT WAS WRONG WHEN THIS WAS WRITTEN, so the shape is not re-derived later. Three entries disagreed
with their index rows. The damaging one was the display face, whose stanza carried `no-data-needed`
while its index row carried nothing: a reader filtering the index for what they could start today
found two of the three, and the file gave no sign. One entry carried no stanza at all against the
file's claim that every entry does, and two more said "maintainer-only" in prose where the tag was
the thing actually being read.

THE ANCHOR IS THE JOIN, not a prefix of the title. An index row's link target is a slug of the exact
heading, so matching on it is total rather than heuristic: a renamed heading breaks the anchor and is
caught here rather than silently pairing with the wrong entry, which a shared-prefix match does when
two entries open with the same four words (`Hero presentation:` opens two of them).

A STATE IS NOT A TAG, and only OPEN entries are held to carrying one. A BLOCKED entry's stanza names
the precondition, which is the honest answer to who can act on it (nobody, yet); an OBSERVED one's
next action is a measurement. Requiring a who-can-act tag there would put an invented answer where
the file currently says a true thing, so the scope of this check is the entries someone could pick up.
"""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FUTURE = ROOT / "FUTURE.md"

#: The vocabulary is defined in the file itself, in § *How this file is organised*. Reading it from
#: there rather than restating it is what stops this test becoming the second copy it exists to
#: forbid: a tag added to the prose and used nowhere, or used and never defined, both fail below.
VOCABULARY_BULLET = re.compile(r"^- \*\*Tags say who can act.*$", re.MULTILINE)

#: A tag as it is written on an index row or in a stanza. Deliberately not anchored to the `·`
#: separator, because two stanzas punctuate with a comma and a colon instead.
TAG = re.compile(r"(?<![\w-])((?:no-data-needed|needs-[a-z-]+|look-call|product|maintainer-only))(?![\w-])")

#: `- [Title](#anchor)`, the only line shape the index uses.
INDEX_ROW = re.compile(r"^- \[(?P<title>.+?)\]\(#(?P<anchor>[a-z0-9-]+)\)(?P<rest>.*)$")

#: What a state looks like at the head of a stanza. `MIXED` marks a container whose subsections carry
#: their own states, which is why it is here and why it is exempt from the tag check.
STATE = re.compile(r"^> \*\*(OPEN|BLOCKED|REJECTED|MIXED|OBSERVED, NOT ANALYSED)\*\*")


def slug(heading: str) -> str:
    """GitHub's anchor for a markdown heading: fold case, drop punctuation, spaces become hyphens."""
    kept = re.sub(r"[^\w\- ]", "", heading.lower().replace("_", ""))
    return kept.replace(" ", "-")


def defined_tags() -> set[str]:
    """Every tag the file's own organisation section defines."""
    bullet = VOCABULARY_BULLET.search(FUTURE.read_text(encoding="utf-8"))
    assert bullet, "FUTURE.md no longer defines its tag vocabulary, so nothing here has a referent"
    return set(TAG.findall(bullet.group(0)))


def parse() -> tuple[dict[str, set[str]], dict[str, tuple[str, str, set[str]]]]:
    """The index's tags per anchor, and each entry's heading, state and tags per anchor."""
    lines = FUTURE.read_text(encoding="utf-8").splitlines()
    index_at = next(number for number, line in enumerate(lines) if line == "## Index")
    body_at = next(number for number, line in enumerate(lines[index_at + 1 :], index_at + 1) if line.startswith("## "))

    index: dict[str, set[str]] = {}
    for line in lines[index_at:body_at]:
        row = INDEX_ROW.match(line)
        if row:
            index[row.group("anchor")] = set(TAG.findall(row.group("rest")))

    entries: dict[str, tuple[str, str, set[str]]] = {}
    for number, line in enumerate(lines[body_at:], body_at):
        if not line.startswith("## "):
            continue
        heading = line[3:]
        stanza = next((text for text in lines[number + 1 : number + 4] if text.startswith("> ")), "")
        state = STATE.match(stanza)
        entries[slug(heading)] = (heading, state.group(1) if state else "", set(TAG.findall(stanza)))
    return index, entries


def test_every_index_row_and_entry_find_each_other() -> None:
    """An index row is a link, so a renamed heading strands it, and a new entry can miss the index."""
    index, entries = parse()

    assert len(entries) > 25, f"the entry scan found only {len(entries)}; check the index/body split"
    assert len(index) > 25, f"the index scan found only {len(index)} rows; check the row pattern"

    stranded = sorted(anchor for anchor in index if anchor not in entries)
    assert not stranded, "index rows whose anchor reaches no heading:\n  " + "\n  ".join(stranded)

    unlisted = sorted(entries[anchor][0] for anchor in entries if anchor not in index)
    assert not unlisted, "entries the index does not carry:\n  " + "\n  ".join(unlisted)


def test_the_index_and_the_entry_carry_the_same_tags() -> None:
    """Two copies of who-can-act, and a reader filters on whichever they met first."""
    index, entries = parse()

    offenders = [
        f"{entries[anchor][0]}\n      index  {sorted(index[anchor]) or '(none)'}"
        f"\n      stanza {sorted(entries[anchor][2]) or '(none)'}"
        for anchor in entries
        if anchor in index and index[anchor] != entries[anchor][2]
    ]
    assert not offenders, (
        "FUTURE.md's index and its entries disagree about who can act, and a newcomer filtering the "
        "index for what they can start today reads the wrong list:\n    " + "\n    ".join(offenders)
    )


def test_every_entry_someone_could_pick_up_says_who_can_act() -> None:
    """`OPEN` is the state a stranger acts on, so it is the state that owes an answer."""
    _, entries = parse()

    stateless = sorted(heading for heading, state, _ in entries.values() if not state)
    assert not stateless, (
        "entries whose stanza names no state, against the file's own claim that every one does:"
        "\n  " + "\n  ".join(stateless)
    )

    silent = sorted(heading for heading, state, tags in entries.values() if state == "OPEN" and not tags)
    assert not silent, (
        "OPEN entries carrying no who-can-act tag, so the parking lot cannot answer the question it "
        "is pointed at to answer:\n  " + "\n  ".join(silent)
    )


def test_every_tag_in_use_is_one_the_file_defines() -> None:
    """A tag nobody defined reads as meaning something, and a defined one nobody uses reads as empty."""
    index, entries = parse()
    defined = defined_tags()

    used = {tag for tags in index.values() for tag in tags}
    used |= {tag for _, _, tags in entries.values() for tag in tags}

    assert not used - defined, (
        f"tags used but never defined in § How this file is organised: {sorted(used - defined)}"
    )
    assert not defined - used, (
        f"tags defined but carried by no entry, which reads as an empty promise: {sorted(defined - used)}"
    )
