"""run_pass.sh's memory preflight: refuse to start a pass the box cannot back.

The cgroup cap kills the job instead of the box, but only if the box actually has the memory
behind it. Capping at 16 G with 9 G available does not protect anything — it relocates the OOM
to the most expensive possible moment, hours in, after every completed stage has been paid for.
The pass cap moved 12 G → 16 G because the pass ends by rendering the polar caps
(~14 GB, inheriting the scope's cgroup), so the headroom question became a real one.

These drive the real script with MEMINFO pointed at a fixture and PREFLIGHT_ONLY set, so both
branches are observable without launching a multi-hour pass. The abort branch is the point: a
guard that has never been seen to fire is indistinguishable from one that passed.
"""

import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "pipeline" / "profile" / "run_pass.sh"
GIB_IN_KIB = 1024 * 1024


def write_meminfo(path: Path, available_kib: int) -> Path:
    """A /proc/meminfo stand-in carrying one MemAvailable line, as the kernel formats it."""
    path.write_text(
        "MemTotal:       30408000 kB\n"
        "MemFree:         6000000 kB\n"
        f"MemAvailable:   {available_kib} kB\n"
        "Buffers:          100000 kB\n"
    )
    return path


def run_preflight(meminfo: Path, *args: str, **env_overrides: str):
    return subprocess.run(
        ["bash", str(SCRIPT), *args],
        capture_output=True, text=True,
        env={"PATH": "/usr/bin:/bin", "MEMINFO": str(meminfo), "PREFLIGHT_ONLY": "1",
             **env_overrides},
        check=False,  # a refusing preflight is what most of these tests are asserting about
    )


class TestPreflightBlocksAnUnbackedCap:
    def test_aborts_when_available_is_below_the_cap(self, tmp_path):
        meminfo = write_meminfo(tmp_path / "meminfo", 9 * GIB_IN_KIB)
        result = run_preflight(meminfo)
        assert result.returncode == 1
        assert "ABORT" in result.stderr
        assert "9.0 GiB is available" in result.stderr

    def test_the_message_names_the_cap_and_the_way_out(self, tmp_path):
        """An abort that does not say what to do is a wall, not a guard."""
        meminfo = write_meminfo(tmp_path / "meminfo", 4 * GIB_IN_KIB)
        result = run_preflight(meminfo)
        assert "capped at 16 G" in result.stderr
        assert "ALLOW_LOW_MEMORY=1" in result.stderr

    def test_proceeds_when_available_clears_the_cap(self, tmp_path):
        meminfo = write_meminfo(tmp_path / "meminfo", 20 * GIB_IN_KIB)
        result = run_preflight(meminfo)
        assert result.returncode == 0
        assert "memory preflight" in result.stdout
        assert "20.0 GiB available" in result.stdout

    def test_exactly_at_the_cap_is_allowed(self, tmp_path):
        """The comparison is <, not <=: a box with exactly the cap free can run."""
        meminfo = write_meminfo(tmp_path / "meminfo", 16 * GIB_IN_KIB)
        assert run_preflight(meminfo).returncode == 0

    def test_allow_low_memory_overrides_deliberately(self, tmp_path):
        meminfo = write_meminfo(tmp_path / "meminfo", 2 * GIB_IN_KIB)
        result = run_preflight(meminfo, ALLOW_LOW_MEMORY="1")
        assert result.returncode == 0

    def test_an_unreadable_meminfo_aborts_rather_than_assuming_headroom(self, tmp_path):
        """Fail toward refusing, never toward trusting — the freshness guards' own rule."""
        blank = tmp_path / "meminfo"
        blank.write_text("MemTotal: 30408000 kB\n")  # no MemAvailable line
        result = run_preflight(blank)
        assert result.returncode == 1
        assert "cannot verify" in result.stderr


class TestBothRunLabelsAreGuarded:
    @pytest.mark.parametrize("args,label", [((), "pass"), (("--tiles",), "tiles")])
    def test_each_run_label_carries_the_same_16g_cap_and_check(self, tmp_path, args, label):
        """The shade pass joined the tiling run at 16 G — both now render the polar caps' worth
        of memory, and neither may start without it."""
        meminfo = write_meminfo(tmp_path / "meminfo", 3 * GIB_IN_KIB)
        result = run_preflight(meminfo, *args)
        assert result.returncode == 1
        assert f"the {label} run is capped at 16 G" in result.stderr
