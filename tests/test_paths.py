"""pipeline/paths.py — the single home for machine-specific filesystem roots.

Two guarantees under test:
- the env seams work: MAPS_DATA / MAPS_BLENDER override the defaults, and the
  defaults are repo-relative (DATA) or the documented install path (BLENDER);
- the seam stays single-home: a source scan proves no module outside paths.py
  re-grows its own `Path.home()` root (the drift that made the repo
  machine-specific in the first place).

The override tests run in a subprocess because the constants bind at import
time — reloading modules in-process would leak state between tests.
"""

import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

# Files allowed to call Path.home(). paths.py is the seam itself (BLENDER's
# default install path is genuinely home-rooted). snow_mask.py is TEMPORARY:
# it is part of the hero-look surface frozen for the 2026-07-23 sea-sync sweep
# — remove it from this list (and migrate the file) once the sweep ratifies.
HOME_ALLOWED = {
    Path("pipeline/paths.py"),
    Path("pipeline/render/snow_mask.py"),  # frozen until sweep ratification
}


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
        with the fix in the message. experiments/ is out of production scope."""
        offenders: list[str] = []
        for source_file in sorted((REPO_ROOT / "pipeline").rglob("*.py")):
            relative = source_file.relative_to(REPO_ROOT)
            if relative.parts[1] == "experiments" or relative in HOME_ALLOWED:
                continue
            if "Path.home()" in source_file.read_text():
                offenders.append(str(relative))
        assert not offenders, (
            f"Path.home() roots outside pipeline/paths.py: {offenders} — "
            "derive from pipeline.paths (DATA / ROOT / BLENDER) instead"
        )
