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
# Prose records real paths as evidence, and editing a record to satisfy a scan
# would corrupt the thing it exists to keep.
CODE_SUFFIXES = {".py", ".sh", ".ts", ".astro", ".toml", ".yml", ".yaml", ".json", ".conf"}

# This file necessarily contains the pattern it searches for.
LITERAL_ALLOWED = {
    Path("tests/test_paths.py"),
}

# Modules that cannot be imported by anything but Blender's own interpreter. Named individually
# rather than skipped on ImportError, because a module that stopped importing for some OTHER reason
# would then be silently exempt from the probe below — and being unreachable is exactly the state in
# which a wrong path survives.
BPY_ONLY = ("pipeline.render.scene_build", "pipeline.render.scene_dump")

# Import every pipeline module with the store moved elsewhere, and report any module-level path that
# stayed behind. Deliberately NOT a text search: it reads the resolved value, so it is blind to how
# the path was spelled and cannot be evaded by a spelling nobody has thought of yet.
STORE_PROBE = f"""
import importlib, pkgutil
from pathlib import Path
from pipeline import paths
offenders = []
for module in pkgutil.walk_packages([str(paths.ROOT / "pipeline")], "pipeline."):
    if module.name in {BPY_ONLY!r}:
        continue
    loaded = importlib.import_module(module.name)
    for attribute, value in vars(loaded).items():
        if (isinstance(value, Path) and {{"raw", "work"}} & set(value.parts)
                and not value.is_relative_to(paths.DATA)):
            offenders.append(f"{{module.name}}.{{attribute}} = {{value}}")
print("\\n".join(sorted(set(offenders))))
"""


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


class TestSharedDatasetsHaveOneHome:
    """A dataset two modules share must be spelled once, and a scan is the only thing that can say so.

    THESE COLLAPSES HAVE NO OTHER GUARD, which is why they get one here. Every duplicate spelling
    resolved to the identical path — that is what made seven of them accumulate unnoticed — so no
    behavioural test can tell one copy from four. Only counting the spellings can.

    The pattern they came from: a dataset stays single-homed while ONE module owns it, and
    duplicates the moment it is shared, because `paths.py` owns a machine root and
    `bodies.work_dir` owns a per-body stage directory, and nothing owned a shared dataset. Natural
    Earth reached eight spellings that way; `work/borders` reached three, across two writers and
    the reader between them.
    """

    def scan(self, needle: str, allowed: set[Path]) -> list[str]:
        """Walks the tree rather than `git ls-files`, deliberately: a scan that reads the index
        cannot see a file that has not been staged yet, and a brand-new module is exactly where a
        fresh duplicate spelling appears."""
        offenders = []
        sources = [*(REPO_ROOT / "pipeline").rglob("*.py"),
                   *(REPO_ROOT / "web/scripts").glob("*.py")]
        for source_file in sorted(sources):
            relative = source_file.relative_to(REPO_ROOT)
            if relative in allowed:
                continue
            for number, line in enumerate(source_file.read_text().splitlines(), 1):
                if needle in line:
                    offenders.append(f"{relative}:{number}")
        return offenders

    def test_the_natural_earth_directory_is_spelled_once(self):
        offenders = self.scan("raw/naturalearth", {Path("pipeline/naturalearth.py")})
        assert not offenders, (
            f"a second spelling of the Natural Earth directory: {offenders} — "
            "use pipeline.naturalearth.DIR, or naturalearth.layer(name) for a shapefile"
        )

    def test_the_layer_name_is_never_doubled_by_hand(self):
        """The `<layer>/<layer>.shp` join, which five call sites used to write out longhand."""
        offenders = [hit for name in ("ne_10m_admin_0_countries", "ne_10m_coastline",
                                      "ne_10m_admin_0_boundary_lines_land")
                     for hit in self.scan(f"{name}/{name}", {Path("pipeline/naturalearth.py")})]
        assert not offenders, (
            f"a hand-written layer/layer.shp join: {offenders} — use naturalearth.layer(name)"
        )

    def test_the_borders_work_dir_is_spelled_once(self):
        """Two writers and a reader; a literal here is how one of the three drifts alone."""
        offenders = self.scan('"work/borders"', set())
        assert not offenders, (
            f"a literal borders work dir: {offenders} — "
            'use bodies.work_dir(bodies.EARTH, "borders")'
        )

    def test_the_scans_can_see_a_violation(self):
        """The control, and it is load-bearing: all three assertions above pass on an empty list,
        which is equally what a scan reading the wrong file set returns. Dropping the allowlist must
        surface the one site that legitimately holds the spelling."""
        unfiltered = self.scan("raw/naturalearth", set())
        assert any(hit.startswith("pipeline/naturalearth.py") for hit in unfiltered), (
            "the scan cannot find the directory even in the module that defines it — it is "
            f"reading nothing, and every assertion in this class is vacuous (saw: {unfiltered})"
        )


class TestTheStoreIsWhereTheStoreIs:
    """Every module-level data path must live inside `paths.DATA`, checked by RUNNING.

    THE TWO SCANS ABOVE ARE SPELLING-HUNTERS, AND THIS SEAM HAS NOW BEEN BLIND THREE TIMES — each
    time to a spelling nobody had thought to search for, and each time it was found by running the
    code somewhere else rather than by a scan. The migration that created `paths.py` swept
    `Path.home()` and only `Path.home()`; an absolute home literal in a shell script survived it and
    was caught by CI on a foreign checkout; a `ROOT / "data/..."` join survived both and was caught
    by a worktree verification. Three generations of one guard, none of which could see the next
    spelling.

    So this one does not read source at all. It moves the store, imports everything, and reads the
    RESOLVED values — which makes it blind to spelling by construction and therefore incapable of
    being blind to a spelling. What it cannot see is a path built inside a function; that half is a
    source scan, because there is no import-time value to look at.
    """

    def test_no_module_path_stays_behind_when_the_store_moves(self, tmp_path):
        offenders = run_probe(STORE_PROBE, {"MAPS_DATA": str(tmp_path / "elsewhere")})
        assert not offenders, (
            f"module paths anchored outside MAPS_DATA:\n{offenders}\n"
            "— join them onto pipeline.paths.DATA (or bodies.work_dir for a body's own tree), "
            "not onto paths.ROOT, which is the CHECKOUT and does not move"
        )

    def test_the_probe_can_see_an_offender(self, tmp_path):
        """The control, and it is not optional here: an empty result is this test's PASS condition,
        and a probe that silently imported nothing would produce exactly that. It plants one bad
        path in a real pipeline module's namespace and requires the probe to name it."""
        planted = STORE_PROBE.replace(
            "offenders = []",
            'import pipeline.bodies\n'
            'pipeline.bodies._PLANTED = paths.ROOT / "data/work/planted"\n'
            "offenders = []",
        )
        found = run_probe(planted, {"MAPS_DATA": str(tmp_path / "elsewhere")})
        assert "pipeline.bodies._PLANTED" in found

    def test_the_probe_reaches_every_module_it_should(self, tmp_path):
        """The other half of the control: proof the walk covers the tree, not just that it can
        report. A probe narrowed to one package would pass both tests above forever."""
        listing = STORE_PROBE.replace(
            'if (isinstance(value, Path) and {"raw", "work"} & set(value.parts)\n'
            "                and not value.is_relative_to(paths.DATA)):",
            "if attribute == '__name__':",
        ).replace('f"{module.name}.{attribute} = {value}"', "module.name")
        reached = set(run_probe(listing, {"MAPS_DATA": str(tmp_path / "elsewhere")}).split("\n"))
        for module in ("pipeline.tile.cap_render", "pipeline.compose.gen_spotlight",
                       "pipeline.frame.frame_country", "pipeline.acquire.download_gebco"):
            assert module in reached, f"{module} was never imported by the probe"
