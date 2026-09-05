"""`split_prose` counts LINES THAT EXIST, so a ratio cannot be inflated by blank lines.

The instrument reports a ratio that decides which module gets worked on next, and it had no test.
It counted a docstring's span (`"\\n"` count plus one), which includes the blank lines BETWEEN its
paragraphs, while the code side counted only non-blank lines. So every paragraph break was charged
to prose and subtracted from code at the same time, and `max(live - prose, 1)` kept the result
positive rather than letting it go absurd. Across `pipeline/` that was 1,067 lines on both sides:
1.09 reported against 0.84 measured.
"""
from pathlib import Path

import pytest

from scripts.prose_report import by_target, split_prose

#: One docstring of three real lines with one paragraph break, then two lines of code.
PARAGRAPHED = '''"""One.

Two.
"""
first = 1
second = 2
'''


class TestABlankLineBelongsToNeitherSide:
    def test_a_paragraph_break_inside_a_docstring_is_not_prose(self):
        prose, _ = split_prose(PARAGRAPHED)
        assert prose == 3, "counted the blank line between two paragraphs as a line of English"

    def test_the_code_side_keeps_every_line_the_prose_side_did_not_take(self):
        prose, code = split_prose(PARAGRAPHED)
        assert code == 2
        assert prose + code == len([line for line in PARAGRAPHED.splitlines() if line.strip()])

    def test_a_comment_block_with_a_bare_hash_gap_counts_only_its_text(self):
        source = "# One.\n#\n# Two.\nvalue = 1\n"
        assert split_prose(source) == (3, 1), "a bare `#` is a line that exists and carries none"


class TestTheCountCannotSilentlyGoNegative:
    """The clamp is what hid the defect, so the arithmetic is pinned rather than the clamp."""

    def test_prose_never_exceeds_the_lines_that_exist(self, subtests):
        for path in sorted((Path(__file__).resolve().parents[1] / "pipeline").rglob("*.py")):
            source = path.read_text(encoding="utf-8")
            with subtests.test(module=path.name):
                prose, code = split_prose(source)
                live = len([line for line in source.splitlines() if line.strip()])
                assert prose + code == live, f"{path.name}: {prose} + {code} != {live} live lines"


class TestTheScanStillFindsProse:
    """A positive control: every assertion above passes on a scan that matched nothing."""

    def test_a_module_with_no_prose_reads_as_none(self):
        assert split_prose("a = 1\nb = 2\n") == (0, 2)

    def test_a_real_module_reads_as_mostly_prose(self):
        source = (Path(__file__).resolve().parents[1] / "pipeline" / "bodies.py").read_text()
        prose, code = split_prose(source)
        assert prose > code, "bodies.py is a constants file and has always read as prose-heavy"

    @pytest.mark.parametrize("source", [PARAGRAPHED, "# One.\nvalue = 1\n"])
    def test_by_target_attributes_the_same_lines_it_counts(self, source):
        assert sum(lines for lines, _ in by_target(source)) <= split_prose(source)[0]
