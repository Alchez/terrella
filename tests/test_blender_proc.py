"""Every Blender launch stages Cycles' temporaries on the data store, never on tmpfs.

A MEMORY GUARD RATHER THAN A TIDINESS ONE, and the mechanism is worth stating because the fix looks
cosmetic. `/tmp` is tmpfs on this project's render box, so a Cycles tile buffer staged there is held
in RAM rather than on disk. Blender removes its temp directory only on a CLEAN exit, and the cgroup
cap exists precisely to KILL a runaway render, so the protection is what strands the file. Nothing
reclaims it afterwards either: tmpfs is not charged to the render's cgroup, so the memory limit
cannot see the leak its own kill produced.

The per-block figure and the incident behind this live in PROCESS.md § Memory and in HISTORY.
"""

import subprocess
from pathlib import Path

import pytest

from pipeline import paths
from pipeline.render import blender_proc

REPO_ROOT = Path(__file__).resolve().parents[1]


class TestTheTempRootIsNeverTmpfs:
    def test_it_sits_under_the_data_store(self):
        assert blender_proc.env()["TMPDIR"].startswith(str(paths.DATA))

    def test_it_is_not_the_system_temp_directory(self):
        """The whole defect in one assertion. `/tmp` is the default Blender inherits when nothing
        says otherwise, and it is the value this module exists to displace."""
        tmpdir = blender_proc.env()["TMPDIR"]
        assert not tmpdir.startswith("/tmp/"), tmpdir
        assert tmpdir != "/tmp"

    def test_the_directory_is_created_rather_than_merely_named(self, monkeypatch, tmp_path):
        """A TMPDIR that does not exist is not an error anywhere in the chain: Blender falls back to
        the system temp directory and renders perfectly, which restores the defect in silence. The
        directory existing is therefore part of the fix and not a convenience."""
        monkeypatch.setattr(paths, "DATA", tmp_path / "store")
        named = Path(blender_proc.env()["TMPDIR"])
        assert named.is_dir(), f"{named} was named but not created"

    def test_it_follows_a_relocated_data_store(self, monkeypatch, tmp_path):
        """The portability seam: a contributor whose store is elsewhere must not get this box's
        path, and must not silently get tmpfs either."""
        monkeypatch.setattr(paths, "DATA", tmp_path / "elsewhere")
        assert blender_proc.env()["TMPDIR"].startswith(str(tmp_path / "elsewhere"))

    def test_the_rest_of_the_environment_survives(self, monkeypatch):
        """TMPDIR is added to the environment, never substituted for it. Blender needs the caller's
        PATH, HOME and GPU variables; an env of one key renders on the wrong device or not at all."""
        monkeypatch.setenv("TERRELLA_PROBE", "kept")
        assert blender_proc.env()["TERRELLA_PROBE"] == "kept"

    def test_extra_keys_are_layered_on_top(self):
        """`batch` needs its venv-first PATH as well as this TMPDIR, and must not have to choose."""
        assert blender_proc.env(PATH="/probe/bin")["PATH"] == "/probe/bin"
        assert blender_proc.env(PATH="/probe/bin")["TMPDIR"].startswith(str(paths.DATA))


class TestTheLauncherIsWhatCarriesIt:
    def test_run_hands_blender_the_temp_root(self, monkeypatch):
        seen: dict[str, object] = {}

        def fake(command, **kwargs):
            seen.update(kwargs)
            return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

        monkeypatch.setattr(blender_proc.subprocess, "run", fake)
        blender_proc.run(["blender", "-b"])
        assert seen["env"]["TMPDIR"].startswith(str(paths.DATA))  # pyright: ignore[reportIndexIssue]

    def test_run_keeps_the_launch_shape_both_callers_depended_on(self, monkeypatch):
        """The extraction must not quietly change how a failed render is reported. Both callers read
        `returncode`, `stdout` and `stderr` off the result and raise their own message from them, so
        a launcher that stopped capturing, or that raised on a non-zero exit, would turn a diagnosed
        block failure into a bare traceback in the middle of a night."""
        seen: dict[str, object] = {}

        def fake(command, **kwargs):
            seen.update(kwargs)
            return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

        monkeypatch.setattr(blender_proc.subprocess, "run", fake)
        blender_proc.run(["blender"])
        assert seen["capture_output"] is True
        assert seen["text"] is True
        assert seen["check"] is False
        assert seen["cwd"] == paths.ROOT


#: Every module that names the Blender binary. Compared against a set DERIVED from the source,
#: because the failure this module guards against is a launch site nobody remembered; a hand-kept
#: scope would go stale in exactly the case that matters.
EXPECTED_NAMERS = frozenset({
    "pipeline/frame/country_config.py",   # builds the hero command; `batch` executes it
    "pipeline/tile/block_render.py",      # the raytraced planet, one Blender per block
    "pipeline/tile/cap_raytrace.py",      # the polar cap frames
})


class TestNoLauncherIsMissedWhenAFOURTHIsAdded:
    def _namers(self) -> set[str]:
        found = set()
        for source in sorted((REPO_ROOT / "pipeline").rglob("*.py")):
            if source.name in {"paths.py", "blender_proc.py"}:
                continue
            text = source.read_text(encoding="utf-8")
            stripped = "\n".join(line for line in text.splitlines()
                                 if not line.lstrip().startswith("#"))
            if "paths.BLENDER" in stripped or "BLENDER = paths.BLENDER" in stripped:
                found.add(str(source.relative_to(REPO_ROOT)))
        return found

    def test_the_set_of_modules_naming_the_blender_binary_is_the_known_one(self):
        found = self._namers()
        assert found == EXPECTED_NAMERS, (
            f"the set of modules that name the Blender binary has changed:\n"
            f"  added:   {sorted(found - EXPECTED_NAMERS)}\n"
            f"  removed: {sorted(EXPECTED_NAMERS - found)}\n"
            "Every launch must stage Cycles' temporaries off tmpfs — route the new one through "
            "`pipeline/render/blender_proc.py` (or `blender_proc.env()` if it shells out), then "
            "add it here.")

    def test_the_scan_actually_found_them(self):
        """The extractor is the second thing that can be vacuous: a scan returning nothing satisfies
        the set assertion above only when EXPECTED is also empty, but a scan that silently found one
        would still read as agreement if the list were trimmed to match. Pin the count."""
        assert len(self._namers()) == 3


class TestTheTwoDirectCallersGoThroughIt:
    """Not `blender_proc` in isolation: these assert the SHIPPING call reaches it.

    The monkeypatch is installed on `blender_proc`, so a caller that went back to invoking
    `subprocess.run` itself would not be intercepted and would try to launch real Blender. That is
    the failure mode this shape exists to make loud.
    """

    def test_block_render_launches_through_the_shared_launcher(self):
        from pipeline.tile import block_render
        source = Path(block_render.__file__).read_text(encoding="utf-8")
        assert "blender_proc.run(" in source
        assert "subprocess.run(blender_command" not in source

    def test_cap_raytrace_launches_through_the_shared_launcher(self):
        from pipeline.tile import cap_raytrace
        source = Path(cap_raytrace.__file__).read_text(encoding="utf-8")
        assert "blender_proc.run(" in source
        assert "subprocess.run(\n        blender_command" not in source


class TestTheHeroSweepCarriesItToo:
    def test_the_stage_environment_names_the_temp_root(self):
        """`batch` cannot use the launcher — its stages are shell strings, and only one of them is
        Blender — so it takes the environment instead. It is the LARGEST buffer of the three: the
        8K hero is the stage `batch`'s own memory gate is sized for, and that gate is defeated by
        exactly the tmpfs it would otherwise fill."""
        from pipeline import batch
        assert batch.stage_env()["TMPDIR"].startswith(str(paths.DATA))

    def test_the_stage_environment_keeps_its_venv_first_path(self):
        """The reason `batch` had an env at all. Losing it sends every stage to the system python."""
        import sys

        from pipeline import batch
        assert batch.stage_env()["PATH"].startswith(str(Path(sys.executable).parent))


@pytest.mark.parametrize("relative", ["pipeline/tile/block_render.py",
                                      "pipeline/tile/cap_raytrace.py"])
def test_no_caller_spells_its_own_launch_flags(relative):
    """One owner for the launch shape. Two identical `subprocess.run(..., cwd=..., capture_output=
    True, text=True, check=False)` calls is the shape that let one of them acquire an env and the
    other not."""
    source = (REPO_ROOT / relative).read_text(encoding="utf-8")
    assert "capture_output=True" not in source, (
        f"{relative} spells the launch flags itself; they belong to blender_proc.run")
