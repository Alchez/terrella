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
import re
import shutil
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

# The mutation table holds broken spellings on purpose — a case that reintroduces a checkout-rooted
# data path has to write one out to be a case at all. Exempt from the join scan below only; it is
# still subject to the home-directory scans, where it has no such excuse.
JOIN_ALLOWED = LITERAL_ALLOWED | {
    Path("scripts/sabotage.py"),
}

# Modules that cannot be imported by anything but Blender's own interpreter. Named individually
# rather than skipped on ImportError, because a module that stopped importing for some OTHER reason
# would then be silently exempt from the probe below — and being unreachable is exactly the state in
# which a wrong path survives.
BPY_ONLY = ("pipeline.render.scene_build", "pipeline.render.scene_dump")

# Import every pipeline module with the store moved elsewhere, and report any module-level path that
# stayed behind. Deliberately NOT a text search: it reads the resolved value, so it is blind to how
# the path was spelled and cannot be evaded by a spelling nobody has thought of yet.
#
# IT READS ONLY THE SEGMENTS THE REPO CHOSE, which is the whole of `below`. An absolute path also
# carries the segments the MACHINE chose, and those are not ours to reason about: GitHub checks out
# to /home/runner/work/<repo>/<repo>, so a predicate over `value.parts` matched the runner's own
# `work` directory and reported all sixteen checkout-resident constants — `config/`, `web/public`,
# `blender/renders`, `paths.ROOT` itself — as data paths that had stayed behind. Every one of them
# was correct code. Taking the path relative to the checkout first asks the same question of the
# same values while leaving the machine's naming out of the answer.
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
        if not isinstance(value, Path) or value.is_relative_to(paths.DATA):
            continue
        below = (value.relative_to(paths.ROOT).parts
                 if value.is_relative_to(paths.ROOT) else value.parts)
        if {{"raw", "work"}} & set(below):
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


def run_probe(code: str, env_overrides: dict[str, str], cwd: Path = REPO_ROOT) -> str:
    """Run `python -c code` from a checkout with a controlled environment.

    `cwd` is what puts `pipeline` on the path, so it also decides what `paths.ROOT` resolves to —
    which is how one test below can ask the probe the same question from a differently-named
    checkout without moving this one.
    """
    env = {key: value for key, value in os.environ.items() if not key.startswith("MAPS_")}
    env.update(env_overrides)
    result = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        cwd=cwd,
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

    THEN IT WAS BLIND A FOURTH TIME, and in the opposite direction — a false POSITIVE rather than a
    false negative. Reading the absolute path's segments meant reading the machine's naming as well
    as the repo's, and CI checks out under a directory literally named `work`, so every one of the
    sixteen checkout-resident constants was reported as a data path left behind. Nothing in the code
    was wrong; the instrument was measuring the runner. The lesson generalises past this predicate:
    an environment-sensitive guard fails where it has never been run, so the reproduction has to
    BE that environment rather than resemble it.
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

    def test_the_probe_reads_the_repos_own_segments_and_not_the_machines(self, tmp_path):
        """The same question asked from a checkout whose own path carries a `work` directory.

        THIS IS THE CI CONDITION RATHER THAN AN ANALOGY: GitHub Actions checks out to
        `/home/runner/work/<repo>/<repo>`. A predicate over the absolute path's parts matched that
        `work` and named all sixteen checkout-resident constants, every one of them correct code,
        on a branch that was green on the machine it was written on.

        THE CHECKOUT IS COPIED RATHER THAN SYMLINKED because `paths.ROOT` resolves, so a link would
        land back on this checkout and the reproduction would quietly be testing nothing.

        The control is inline rather than a sibling test because it is specific to THIS copy: an
        empty assertion list is the pass condition, and a `copytree` that produced a tree the probe
        could not import would return exactly that. Planting an offender proves the probe reached
        the copy — the reported path has to be the copy's, not this checkout's.
        """
        checkout = tmp_path / "work" / "checkout"
        shutil.copytree(REPO_ROOT / "pipeline", checkout / "pipeline",
                        ignore=shutil.ignore_patterns("__pycache__"))
        store = {"MAPS_DATA": str(tmp_path / "elsewhere")}

        offenders = run_probe(STORE_PROBE, store, cwd=checkout)
        assert not offenders, (
            f"the probe reports offenders only because the checkout sits under a directory named "
            f"`work`:\n{offenders}\n— take the path relative to paths.ROOT first, so that only the "
            "segments this repository chose can decide the answer"
        )

        planted = STORE_PROBE.replace(
            "offenders = []",
            'import pipeline.bodies\n'
            'pipeline.bodies._PLANTED = paths.ROOT / "data/work/planted"\n'
            "offenders = []",
        )
        found = run_probe(planted, store, cwd=checkout)
        assert f"{checkout}/data/work/planted" in found, (
            f"the probe did not import the copied checkout, so the assertion above passed on an "
            f"empty tree rather than a clean one (saw: {found})"
        )

    def test_no_data_path_is_built_by_joining_onto_a_checkout_root(self):
        """The half the probe structurally cannot see: a path assembled INSIDE a function.

        There is no import-time value to read, so this one is a text scan after all — but a narrow
        one, aimed at a single shape rather than at machine-specificity in general. Anything joined
        onto a `data/`-prefixed literal is deriving the store from whatever root is to its left, and
        the roots to its left are checkouts.

        THE SCAN CATCHES PROSE THAT QUOTES THE SHAPE, and that is deliberate rather than a false
        positive: two comments in this repo described a deleted checkout-rooted default by
        reproducing it verbatim, which re-creates the needle a future scan has to sort through.
        Describe the old spelling, do not quote it.
        """
        joined = re.compile(r'/\s*(?:[rf]{1,2})?["\']data/')
        shell = re.compile(r"\)\s*/data/")  # a $(cd … pwd) checkout root, then straight into data/
        offenders: list[str] = []
        for relative in tracked_files():
            if relative.suffix not in CODE_SUFFIXES or relative in JOIN_ALLOWED:
                continue
            source_file = REPO_ROOT / relative
            if not source_file.exists():
                continue
            pattern = shell if relative.suffix == ".sh" else joined
            for number, line in enumerate(source_file.read_text().splitlines(), 1):
                if pattern.search(line):
                    offenders.append(f"{relative}:{number}")
        assert not offenders, (
            f"data paths joined onto a checkout root: {offenders} — derive them from "
            "pipeline.paths.DATA (or a helper that does), so MAPS_DATA relocates them"
        )

    def test_the_join_scan_can_see_a_violation(self):
        """The control: the pattern must match the shape it forbids, written out here on purpose."""
        joined = re.compile(r'/\s*(?:[rf]{1,2})?["\']data/')
        assert joined.search('WORK = ROOT / "data/work"')
        assert joined.search('out = ROOT / f"data/work/{slug}/render"')
        assert joined.search("shp = repo / 'data/raw/naturalearth'")
        assert not joined.search('DATA = paths.DATA / "work/borders"')  # the correct spelling
        assert not joined.search("  fuse_heightfield.py --outdir data/work/india")  # prose

    def test_the_probe_reaches_every_module_it_should(self, tmp_path):
        """The other half of the control: proof the walk covers the tree, not just that it can
        report. A probe narrowed to one package would pass both tests above forever.

        It swaps the predicate out BY TEXT, so every edit to the predicate lands here — which is
        why the excerpt is asserted before it is used. Without that, a substitution that missed
        would leave the probe reporting nothing at all and this test would fail claiming the walk
        no longer reaches `cap_render`, which is a true statement about the wrong thing.
        """
        predicate = (
            "if not isinstance(value, Path) or value.is_relative_to(paths.DATA):\n"
            "            continue\n"
            "        below = (value.relative_to(paths.ROOT).parts\n"
            "                 if value.is_relative_to(paths.ROOT) else value.parts)\n"
            '        if {"raw", "work"} & set(below):'
        )
        assert predicate in STORE_PROBE, (
            "the probe's predicate has changed and this control still holds the old text, so the "
            "substitution below would silently do nothing — copy the new predicate in here"
        )
        listing = STORE_PROBE.replace(
            predicate, "if attribute == '__name__':",
        ).replace('f"{module.name}.{attribute} = {value}"', "module.name")
        reached = set(run_probe(listing, {"MAPS_DATA": str(tmp_path / "elsewhere")}).split("\n"))
        for module in ("pipeline.tile.cap_render", "pipeline.compose.gen_spotlight",
                       "pipeline.frame.frame_country", "pipeline.acquire.download_gebco"):
            assert module in reached, f"{module} was never imported by the probe"
