"""Every `AGENTS.md` in the repo reaches a Claude Code session.

The root has a `CLAUDE.md`, so by default Claude Code reads a nested `AGENTS.md` only when a
`CLAUDE.md` imports it, and this repo keeps that import beside the file. Without it the file is
written for an agent and read by none.
"""

import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]


def agents_files() -> list[Path]:
    """Every `AGENTS.md` a commit would hold, staged or not."""
    listing = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard"],
        cwd=REPO, capture_output=True, text=True, check=True,
    ).stdout.splitlines()
    return [REPO / name for name in listing
            if Path(name).name == "AGENTS.md" and (REPO / name).is_file()]


def imports_agents_md(claude_md: Path) -> bool:
    """True when the file holds `@AGENTS.md` as a line of its own, the only shape Claude Code expands."""
    return claude_md.is_file() and any(
        line.strip() == "@AGENTS.md" for line in claude_md.read_text().splitlines()
    )


def test_every_agents_md_is_imported_by_the_claude_md_beside_it(subtests) -> None:
    found = agents_files()
    assert found, "No AGENTS.md was found, so this guard checked nothing; delete it if that is intended."
    for agents_md in found:
        with subtests.test(path=str(agents_md.relative_to(REPO))):
            claude_md = agents_md.with_name("CLAUDE.md")
            assert imports_agents_md(claude_md), (
                f"{claude_md.relative_to(REPO)} does not import `@AGENTS.md` on a line of its own, "
                f"so no Claude Code session in this repo reads {agents_md.relative_to(REPO)}"
            )
