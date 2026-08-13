"""run_pass.sh's memory cap and its preflight: size the cap from the body, then refuse a box that
cannot back it.

The cgroup cap kills the job instead of the box, but only if the box actually has the memory
behind it. Capping at 16 G with 9 G available does not protect anything — it relocates the OOM
to the most expensive possible moment, hours in, after every completed stage has been paid for.

**The cap is the BODY's**, which is what makes the two halves interact. 16 G is Earth's number,
set by the polar cap render the pass ends with; a body that renders no caps never reaches that
stage, so on it the 16 G is unbacked and the preflight would refuse a pass the box could have run.
`pipeline/profile/pass_cap.py` derives it and holds the measurements; these tests drive the real
script, so what they pin is the WIRING — that the shell asks, and that the answer reaches the
cgroup argument and the refusal message rather than a constant reaching them.

MEMINFO points at a fixture and PREFLIGHT_ONLY is set, so both branches are observable without
launching a multi-hour pass. The abort branch is the point: a guard that has never been seen to
fire is indistinguishable from one that passed.
"""

import dataclasses
import subprocess
from pathlib import Path

import pytest

from pipeline import bodies
from pipeline.profile import pass_cap

SCRIPT = Path(__file__).resolve().parents[1] / "pipeline" / "profile" / "run_pass.sh"
GIB_IN_KIB = 1024 * 1024

#: A body that renders no polar caps — the resolver's OTHER branch, and synthetic on purpose.
#:
#: The registry used to supply one: Mars rendered no caps while its ramps were unratified, and every
#: test below took its negative instance from that row. Ratifying the ramps turned the caps on and
#: took the branch away with them, which is the failure mode worth naming — a guard whose only
#: negative instance is a live registry field stops testing anything the day that field changes, and
#: says nothing while it happens. Built off Earth so every unrelated field is a real planet's.
CAPLESS = dataclasses.replace(bodies.EARTH, name="capless", path_prefix="capless",
                              renders_polar_caps=False)


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
    """Earth throughout, because Earth is the body whose cap these numbers were measured against.

    Every call names it: `--body` is required by the wrapper now, and a shared default here would
    hide which planet each figure belongs to at exactly the moment they stopped being one number.
    """

    def test_aborts_when_available_is_below_the_cap(self, tmp_path):
        meminfo = write_meminfo(tmp_path / "meminfo", 9 * GIB_IN_KIB)
        result = run_preflight(meminfo, "--body", "earth")
        assert result.returncode == 1
        assert "ABORT" in result.stderr
        assert "9.0 GiB is available" in result.stderr

    def test_the_message_names_the_cap_and_the_way_out(self, tmp_path):
        """An abort that does not say what to do is a wall, not a guard."""
        meminfo = write_meminfo(tmp_path / "meminfo", 4 * GIB_IN_KIB)
        result = run_preflight(meminfo, "--body", "earth")
        assert "capped at 16 G" in result.stderr
        assert "ALLOW_LOW_MEMORY=1" in result.stderr

    def test_proceeds_when_available_clears_the_cap(self, tmp_path):
        meminfo = write_meminfo(tmp_path / "meminfo", 20 * GIB_IN_KIB)
        result = run_preflight(meminfo, "--body", "earth")
        assert result.returncode == 0
        assert "memory preflight" in result.stdout
        assert "20.0 GiB available" in result.stdout

    def test_exactly_at_the_cap_is_allowed(self, tmp_path):
        """The comparison is <, not <=: a box with exactly the cap free can run."""
        meminfo = write_meminfo(tmp_path / "meminfo", 16 * GIB_IN_KIB)
        assert run_preflight(meminfo, "--body", "earth").returncode == 0

    def test_allow_low_memory_overrides_deliberately(self, tmp_path):
        meminfo = write_meminfo(tmp_path / "meminfo", 2 * GIB_IN_KIB)
        result = run_preflight(meminfo, "--body", "earth", ALLOW_LOW_MEMORY="1")
        assert result.returncode == 0

    def test_an_unreadable_meminfo_aborts_rather_than_assuming_headroom(self, tmp_path):
        """Fail toward refusing, never toward trusting — the freshness guards' own rule."""
        blank = tmp_path / "meminfo"
        blank.write_text("MemTotal: 30408000 kB\n")  # no MemAvailable line
        result = run_preflight(blank, "--body", "earth")
        assert result.returncode == 1
        assert "cannot verify" in result.stderr


class TestBothRunLabelsAreGuarded:
    @pytest.mark.parametrize("args,label", [((), "pass"), (("--tiles",), "tiles")])
    def test_each_run_label_carries_the_bodys_cap_and_the_check(self, tmp_path, args, label):
        """Earth wants 16 G under both labels — the caps stage ends the shade pass, and the tiler's
        per-worker block cache makes the tiling run ask for the same. Neither may start without it.
        """
        meminfo = write_meminfo(tmp_path / "meminfo", 3 * GIB_IN_KIB)
        result = run_preflight(meminfo, "--body", "earth", *args)
        assert result.returncode == 1
        assert f"the {label} run is capped at 16 G" in result.stderr


class TestTheCapReachesTheCgroup:
    """The WIRING, driven through the real script rather than asserted about `pass_cap` alone.

    A unit test on the resolver cannot see the failure this closes: the shell used to hold the
    number itself, so a correct resolver that nothing called would leave every pass at Earth's 16 G
    and every assertion in the class below would still pass.

    THE SECOND NUMBER COMES FROM `MEMORY_CAP_OVERRIDE_GIB` RATHER THAN FROM A SECOND BODY, and that
    is forced rather than chosen. `pass_cap` runs in a SUBPROCESS, so `CAPLESS` cannot reach it and
    a registry monkeypatch is invisible here; once both registered bodies rendered caps, the
    resolver answered 16 for every planet and no invocation could distinguish "the shell used the
    number it was handed" from "the shell holds a 16". The override makes the number an input, which
    is what these tests need and what the registry can no longer supply.
    """

    def test_a_lower_cap_runs_on_a_box_that_refuses_earths(self, tmp_path):
        """The whole point, at the one memory figure where the two answers disagree.

        14 GiB backs a 12 G cap and not Earth's 16 G, so one fixture shows both that the cap moved
        and that it did not simply go slack — a guard weakened for everyone would admit both arms,
        and this asserts it admits exactly one.
        """
        meminfo = write_meminfo(tmp_path / "meminfo", 14 * GIB_IN_KIB)
        lowered = run_preflight(meminfo, "--body", "earth", "--tiles",
                                MEMORY_CAP_OVERRIDE_GIB="12")
        standing = run_preflight(meminfo, "--body", "earth", "--tiles")
        assert lowered.returncode == 0, lowered.stderr
        assert "14.0 GiB available >= 12 G cap" in lowered.stdout
        assert standing.returncode == 1
        assert "capped at 16 G" in standing.stderr

    def test_the_cgroup_argument_carries_the_resolved_cap_not_a_constant(self, tmp_path):
        """The refusal message and `MemoryMax` read the same shell variable, so pinning the message
        pins what the scope would have been given. Checked on the refusing branch because that is
        the only place the number is printed without launching a real pass."""
        meminfo = write_meminfo(tmp_path / "meminfo", 1 * GIB_IN_KIB)
        refusal = run_preflight(meminfo, "--body", "earth", MEMORY_CAP_OVERRIDE_GIB="12")
        assert "capped at 12 G" in refusal.stderr

    def test_the_override_is_announced_rather_than_silent(self, tmp_path):
        """A cap nobody named is the failure `pass_cap`'s own note refuses, so the branch that can
        produce one has to say it did. The body's own number is printed beside it, because "12 G"
        alone cannot tell a reader whether the override changed anything."""
        meminfo = write_meminfo(tmp_path / "meminfo", 20 * GIB_IN_KIB)
        result = run_preflight(meminfo, "--body", "earth", MEMORY_CAP_OVERRIDE_GIB="12")
        assert "memory cap overridden: 12 G instead of this body's 16 G" in result.stdout

    def test_the_resolver_still_runs_when_the_override_is_set(self, tmp_path):
        """The ordering, asserted rather than trusted. Read as `${OVERRIDE:-$(pass_cap ...)}` the
        override would skip the resolver, and with it the `--body` contract the wrapper enforces —
        so an operator with the variable exported would quietly get a pass that never named a body.
        """
        meminfo = write_meminfo(tmp_path / "meminfo", 20 * GIB_IN_KIB)
        result = run_preflight(meminfo, "--tiles", MEMORY_CAP_OVERRIDE_GIB="12")
        assert result.returncode != 0
        assert "--body" in result.stderr
        assert "memory preflight" not in result.stdout

    def test_a_nonsense_override_aborts_rather_than_evaluating_to_zero(self, tmp_path):
        """Bash reads a non-numeric value as 0 in the comparison below, so an unvalidated override
        does not fail — it makes every box clear every cap, and the preflight stops being a check
        while still printing that it passed."""
        meminfo = write_meminfo(tmp_path / "meminfo", 1 * GIB_IN_KIB)
        result = run_preflight(meminfo, "--body", "earth", MEMORY_CAP_OVERRIDE_GIB="12G")
        assert result.returncode == 1
        assert "not a whole number of GiB" in result.stderr
        assert "memory preflight" not in result.stdout

    def test_an_omitted_body_is_refused_before_the_scope_opens(self, tmp_path):
        """It was refused inside Python before, after a cgroup scope had already been opened. The
        wrapper's header has always called `--body` required; asking for the cap is what finally
        makes that true at the wrapper."""
        meminfo = write_meminfo(tmp_path / "meminfo", 20 * GIB_IN_KIB)
        result = run_preflight(meminfo, "--tiles")
        assert result.returncode != 0
        assert "--body" in result.stderr
        assert "memory preflight" not in result.stdout

    def test_an_unknown_body_is_refused_rather_than_defaulted(self, tmp_path):
        """A case variant of a real body: the realistic miss, and one that can never become valid."""
        meminfo = write_meminfo(tmp_path / "meminfo", 20 * GIB_IN_KIB)
        result = run_preflight(meminfo, "--body", "Mars")
        assert result.returncode != 0
        assert "memory preflight" not in result.stdout


class TestTheCapResolver:
    """Both branches, one from the registry and one from `CAPLESS`.

    The pair is what makes the resolver falsifiable: a version that ignored its argument and returned
    a constant satisfies either test alone, and fails the moment two bodies disagreeing on the one
    field it reads are asked in the same suite.
    """

    def test_earth_gets_the_cap_render_headroom(self):
        assert pass_cap.pass_memory_cap_gib(bodies.EARTH) == pass_cap.CAP_RENDERING_GIB

    def test_a_capless_body_gets_the_standing_cap(self):
        assert pass_cap.pass_memory_cap_gib(CAPLESS) == pass_cap.STANDING_GIB

    def test_the_two_numbers_actually_differ(self):
        """Anti-vacuity: both assertions above pass if the constants collapse to one value, and so
        does the script — every pass would just run at whichever number survived."""
        assert pass_cap.CAP_RENDERING_GIB > pass_cap.STANDING_GIB

    def test_the_standing_cap_is_the_projects_own(self):
        """12 G is not a number chosen here. It is what every heavy job in this repo runs under,
        and the pass was raised above it for the caps stage alone."""
        assert pass_cap.STANDING_GIB == 12

    @pytest.mark.parametrize("slug", sorted(bodies.BODIES))
    def test_every_registered_body_resolves(self, slug):
        assert pass_cap.pass_memory_cap_gib(bodies.get(slug)) > 0

    def test_the_argv_path_reads_the_body_through_the_passs_own_parser(self, monkeypatch):
        """`--out` is accepted here only because the pass accepts it; a parser private to this
        module would have to grow every flag separately, which is the drift sharing one avoids.

        `CAPLESS` is put in the registry rather than passed as an object because THIS path takes a
        name: `cap_for_argv` parses argv and resolves through `bodies.get`, so a capless body only
        reaches the resolver if the registry can answer for it.
        """
        monkeypatch.setitem(bodies.BODIES, CAPLESS.name, CAPLESS)
        assert pass_cap.cap_for_argv(["--body", "capless", "--tiles", "--out", "/x"]) == 12
        assert pass_cap.cap_for_argv(["--body", "earth"]) == 16
