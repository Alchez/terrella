"""pipeline/paths.py — the single home for machine-specific filesystem roots.

Two guarantees under test:
- the env seams work: MAPS_DATA / MAPS_BLENDER override the defaults, and the
  defaults are repo-relative (DATA) or the documented install path (BLENDER);
- the seam stays single-home, under two scans that catch two different spellings
  of the same drift: no module outside paths.py re-grows its own `Path.home()`
  root, and no tracked *runnable* file carries an absolute home-directory
  literal. The second scan exists because the first never looked for it — CI
  caught `run_pass.sh` hardcoding a checkout path four times, which made every
  preflight test pass locally and fail on any other machine.

The override tests run in a subprocess because the constants bind at import
time — reloading modules in-process would leak state between tests.
"""

import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

# Files allowed to call Path.home(). paths.py is the seam itself (BLENDER's
# default install path is genuinely home-rooted).
HOME_ALLOWED = {
    Path("pipeline/paths.py"),
}

# Tracked file types that are RUN rather than read: a machine-specific path in
# one of these breaks another checkout. Prose is deliberately out of scope —
# HISTORY.md records real paths as evidence, and editing the archive to satisfy
# a scan would corrupt the record it exists to keep.
CODE_SUFFIXES = {".py", ".sh", ".ts", ".astro", ".toml", ".yml", ".yaml", ".json", ".conf"}

# This file necessarily contains the pattern it searches for.
LITERAL_ALLOWED = {
    Path("tests/test_paths.py"),
}


def tracked_files() -> list[Path]:
    """Repo-relative paths of everything git tracks — i.e. everything that ships."""
    listing = subprocess.run(
        ["git", "ls-files", "-z"],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
        check=True,
    )
    return [Path(name) for name in listing.stdout.split("\0") if name]


def run_probe(code: str, env_overrides: dict[str, str]) -> str:
    """Run `python -c code` from the repo root with a controlled environment."""
    env = {key: value for key, value in os.environ.items() if not key.startswith("MAPS_")}
    env.update(env_overrides)
    result = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
        env=env,
        check=True,
    )
    return result.stdout.strip()


class TestDefaults:
    def test_data_defaults_to_repo_data_dir(self):
        output = run_probe("from pipeline.paths import DATA; print(DATA)", {})
        assert output == str(REPO_ROOT / "data")

    def test_root_is_the_repo_root(self):
        output = run_probe("from pipeline.paths import ROOT; print(ROOT)", {})
        assert output == str(REPO_ROOT)

    def test_blender_defaults_to_documented_install(self):
        output = run_probe("from pipeline.paths import BLENDER; print(BLENDER)", {})
        assert output == str(Path.home() / "software/blender-5.1.2-linux-x64/blender")


class TestEnvOverrides:
    def test_maps_data_overrides(self, tmp_path):
        output = run_probe(
            "from pipeline.paths import DATA; print(DATA)",
            {"MAPS_DATA": str(tmp_path / "elsewhere")},
        )
        assert output == str(tmp_path / "elsewhere")

    def test_maps_blender_overrides(self, tmp_path):
        output = run_probe(
            "from pipeline.paths import BLENDER; print(BLENDER)",
            {"MAPS_BLENDER": str(tmp_path / "blender-custom/blender")},
        )
        assert output == str(tmp_path / "blender-custom/blender")

    def test_override_does_not_move_root(self, tmp_path):
        """ROOT is source-tree-derived, never env-driven: repo outputs (web/public)
        must stay in the checkout even when the data store moves elsewhere."""
        output = run_probe(
            "from pipeline.paths import ROOT; print(ROOT)",
            {"MAPS_DATA": str(tmp_path)},
        )
        assert output == str(REPO_ROOT)


class TestSingleHome:
    def test_no_path_home_outside_the_seam(self):
        """The drift guard: any new Path.home() root outside paths.py fails here,
        with the fix in the message."""
        offenders: list[str] = []
        for source_file in sorted((REPO_ROOT / "pipeline").rglob("*.py")):
            relative = source_file.relative_to(REPO_ROOT)
            if relative in HOME_ALLOWED:
                continue
            if "Path.home()" in source_file.read_text():
                offenders.append(str(relative))
        assert not offenders, (
            f"Path.home() roots outside pipeline/paths.py: {offenders} — "
            "derive from pipeline.paths (DATA / ROOT / BLENDER) instead"
        )

    def test_no_home_directory_literal_in_tracked_code(self):
        """The spelling Path.home() misses. An absolute home path written as a
        string is the same drift with none of the syntax, and it is invisible
        until the file runs somewhere else — which, for a harness script, may be
        only ever on CI."""
        offenders: list[str] = []
        for relative in tracked_files():
            if relative.suffix not in CODE_SUFFIXES or relative in LITERAL_ALLOWED:
                continue
            source_file = REPO_ROOT / relative
            if not source_file.exists():  # tracked but deleted in the working tree
                continue
            for number, line in enumerate(source_file.read_text().splitlines(), 1):
                if "/home/" in line:
                    offenders.append(f"{relative}:{number}")
        assert not offenders, (
            f"machine-specific home paths in tracked code: {offenders} — derive the "
            'root from the file\'s own location (pipeline.paths in Python, $(dirname "$0") '
            "in shell) and let MAPS_DATA relocate the data store"
        )
