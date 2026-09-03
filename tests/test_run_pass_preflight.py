"""run_pass.sh's memory cap and its preflight: size the cap from the body, then refuse a box that
cannot back it.

The cgroup cap kills the job instead of the box, but only if the box actually has the memory
behind it. Capping at 16 G with 9 G available does not protect anything — it relocates the OOM
to the most expensive possible moment, hours in, after every completed stage has been paid for.

**The cap is the BODY's**, which is what makes the two halves interact. 16 G is Earth's number,
set by the polar cap render the pass ends with; a body that renders no caps never reaches that
stage, so on it the 16 G is unbacked and the preflight would refuse a pass the box could have run.
`pipeline/profile/pass_memory.py` derives it and holds the measurements; these tests drive the real
script, so what they pin is the WIRING — that the shell asks, and that the answer reaches the
cgroup argument and the refusal message rather than a constant reaching them.

MEMINFO points at a fixture and STOP_AFTER names how far to run, so both branches are observable
without launching a multi-hour pass. The abort branch is the point: a guard that has never been
seen to fire is indistinguishable from one that passed.

MAPS_DATA points at a tmp dir on every call, which is a correctness requirement rather than tidiness:
`STOP_AFTER=logs` runs far enough to prepare and rotate this run's log, and without the redirect
that is the real store's `_profile_pass/pass.log` being rotated by the test suite.
"""

import dataclasses
import re
import subprocess
from pathlib import Path

import pytest

from pipeline import bodies
from pipeline.profile import pass_memory

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "pipeline" / "profile" / "run_pass.sh"
PASS_MEMORY_SOURCE = REPO / "pipeline" / "profile" / "pass_memory.py"
PROCESS = REPO / "PROCESS.md"
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
    """Drive the real script, stopping at the preflight unless a caller says otherwise.

    MAPS_DATA defaults beside the meminfo fixture, which is already a tmp_path in every caller, so
    no invocation here can reach the real store.
    """
    return subprocess.run(
        ["bash", str(SCRIPT), *args],
        capture_output=True, text=True,
        env={"PATH": "/usr/bin:/bin", "MEMINFO": str(meminfo), "STOP_AFTER": "preflight",
             "MAPS_DATA": str(meminfo.parent / "store"), **env_overrides},
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
        """Earth wants 16 G under both labels — the caps stage ends the planet pass, and the tiler's
        per-worker block cache makes the tiling run ask for the same. Neither may start without it.
        """
        meminfo = write_meminfo(tmp_path / "meminfo", 3 * GIB_IN_KIB)
        result = run_preflight(meminfo, "--body", "earth", *args)
        assert result.returncode == 1
        assert f"the {label} run is capped at 16 G" in result.stderr


class TestTheCapReachesTheCgroup:
    """The WIRING, driven through the real script rather than asserted about `pass_memory` alone.

    A unit test on the resolver cannot see the failure this closes: the shell used to hold the
    number itself, so a correct resolver that nothing called would leave every pass at Earth's 16 G
    and every assertion in the class below would still pass.

    THE SECOND NUMBER COMES FROM `MEMORY_CAP_OVERRIDE_GIB` RATHER THAN FROM A SECOND BODY, and that
    is forced rather than chosen. `pass_memory` runs in a SUBPROCESS, so `CAPLESS` cannot reach it and
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
        """A cap nobody named is the failure `pass_memory`'s own note refuses, so the branch that can
        produce one has to say it did. The body's own number is printed beside it, because "12 G"
        alone cannot tell a reader whether the override changed anything."""
        meminfo = write_meminfo(tmp_path / "meminfo", 20 * GIB_IN_KIB)
        result = run_preflight(meminfo, "--body", "earth", MEMORY_CAP_OVERRIDE_GIB="12")
        assert "memory cap overridden: 12 G instead of this body's 16 G" in result.stdout

    def test_the_shell_and_the_resolver_name_the_same_module(self):
        """The one coupling in this harness that nothing checked, and it is silent when it breaks.

        `run_pass.sh` forwards its argv to a module, and `pass_memory` parses that SAME argv with that
        module's parser to size the cap. Point them at different modules and nothing raises: the cap
        is resolved from one grammar and the pass run under another, so a flag one accepts and the
        other does not either aborts the wrapper on a valid invocation or resolves a cap for a body
        the pass never sees. The script's header spent this whole arc naming a module it had stopped
        invoking, which is how long a prose-only version of this claim survives.
        """
        invoked = set(re.findall(r"-m (pipeline\.[a-z_.]+)", SCRIPT.read_text()))
        assert pass_memory.__name__ in invoked, "the script stopped asking the resolver; re-read it"
        assert invoked - {pass_memory.__name__} == {pass_memory.planet_pass.__name__}, (
            f"run_pass.sh forwards its argv to {sorted(invoked - {pass_memory.__name__})}, and "
            f"pass_memory sizes it by parsing that same argv with "
            f"{pass_memory.planet_pass.__name__}"
        )

    def test_the_resolver_still_runs_when_the_override_is_set(self, tmp_path):
        """The ordering, asserted rather than trusted. Read as `${OVERRIDE:-$(pass_memory ...)}` the
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


class TestEveryRunsLogIsKept:
    """The raytrace producer resumes across nights, so the pass's log has to survive one.

    Rohan's requirement, and it is a correctness one rather than tidiness: the box will not be free
    for 22 consecutive hours, so the record of which blocks failed is spread over several runs. The
    script used to open the log with `: >`, which meant every night but the last was destroyed by
    the act of continuing.
    """

    @staticmethod
    def _profile_dir(meminfo: Path) -> Path:
        """Where `run_pass.sh` puts a non-`--tiles` run's instruments, under the redirected store."""
        return meminfo.parent / "store" / "work" / "_profile_pass"

    def _run_to_the_log(self, meminfo: Path):
        return run_preflight(meminfo, "--body", "earth", STOP_AFTER="logs")

    def test_a_prior_runs_log_survives_the_next_run(self, tmp_path):
        meminfo = write_meminfo(tmp_path / "meminfo", 20 * GIB_IN_KIB)
        profile = self._profile_dir(meminfo)
        profile.mkdir(parents=True)
        (profile / "pass.log").write_text("r03c07 FAILED (1 in a row): blender exited with -11\n")

        assert self._run_to_the_log(meminfo).returncode == 0
        rotated = sorted(profile.glob("pass-*.log"))
        assert len(rotated) == 1, f"expected one rotated log, found {rotated}"
        assert "r03c07 FAILED" in rotated[0].read_text()

    def test_this_runs_log_starts_empty(self, tmp_path):
        """The other half: keeping the record must not mean every night reading last night's.

        A watcher counts LINES into this file and starts at zero, so a log carrying four nights
        would have it report night one's stages as this night's the moment it is pointed at it.
        """
        meminfo = write_meminfo(tmp_path / "meminfo", 20 * GIB_IN_KIB)
        profile = self._profile_dir(meminfo)
        profile.mkdir(parents=True)
        (profile / "pass.log").write_text("last night\n")

        self._run_to_the_log(meminfo)
        assert (profile / "pass.log").read_text() == ""

    def test_a_first_run_rotates_nothing(self, tmp_path):
        """Anti-vacuity in the other direction: an unconditional rotation would leave an empty
        `pass-*.log` beside every run, and the glob above would stop meaning "a night happened"."""
        meminfo = write_meminfo(tmp_path / "meminfo", 20 * GIB_IN_KIB)
        assert self._run_to_the_log(meminfo).returncode == 0
        assert list(self._profile_dir(meminfo).glob("pass-*.log")) == []
        assert (self._profile_dir(meminfo) / "pass.log").exists()

    def test_stopping_at_the_preflight_touches_no_log_at_all(self, tmp_path):
        """`STOP_AFTER=preflight` is the no-side-effects stop, and every other test in this file
        relies on that: they run against the real script with the real store redirected, and a
        preflight that created directories would be doing work a check must not do."""
        meminfo = write_meminfo(tmp_path / "meminfo", 20 * GIB_IN_KIB)
        assert run_preflight(meminfo, "--body", "earth").returncode == 0
        assert not self._profile_dir(meminfo).exists()


class TestTheCapResolver:
    """Both branches, one from the registry and one from `CAPLESS`.

    The pair is what makes the resolver falsifiable: a version that ignored its argument and returned
    a constant satisfies either test alone, and fails the moment two bodies disagreeing on the one
    field it reads are asked in the same suite.
    """

    def test_earth_gets_the_cap_render_headroom(self):
        assert pass_memory.limit_gib(bodies.EARTH) == pass_memory.CAP_RENDERING_GIB

    def test_a_capless_body_gets_the_standing_cap(self):
        assert pass_memory.limit_gib(CAPLESS) == pass_memory.STANDING_GIB

    def test_the_two_numbers_actually_differ(self):
        """Anti-vacuity: both assertions above pass if the constants collapse to one value, and so
        does the script — every pass would just run at whichever number survived."""
        assert pass_memory.CAP_RENDERING_GIB > pass_memory.STANDING_GIB

    def test_no_pass_is_capped_above_the_ratified_ceiling(self):
        """The one relationship between these constants that is a POLICY rather than a measurement.

        CLAUDE.md ratifies one heavy job at a time under 16 G with no exemptions, and `HEAVY_JOB_GIB`
        is that number. A body whose measured stages wanted more would not simply get more: it would
        be a pass running outside the policy, which is a decision rather than a constant. Nothing
        checked it, and `CAP_RENDERING_GIB` has sat exactly at the ceiling since the caps stage
        pushed it there, so the next body to need headroom would take it silently.
        """
        assert pass_memory.CAP_RENDERING_GIB <= pass_memory.HEAVY_JOB_GIB
        assert pass_memory.STANDING_GIB <= pass_memory.HEAVY_JOB_GIB

    def test_the_standing_cap_is_not_the_projects_own_number(self):
        """WRITTEN AS THE INVERSE OF THE CLAIM IT REPLACES, because that claim read as settled.

        The test here used to assert `STANDING_GIB == 12` and justify it as *"what every heavy job
        in this repo runs under"*. That was true of an older ceiling and is not true of this one:
        the project's heavy-job number is `HEAVY_JOB_GIB`, four GiB higher, and 12 is a measurement
        off Mars's own stages. Pinning a real constant to a justification that has moved is worse
        than pinning nothing, because the number then looks derived when it is orphaned.
        """
        assert pass_memory.STANDING_GIB != pass_memory.HEAVY_JOB_GIB

    def test_every_figure_the_module_argues_from_is_one_PROCESS_still_carries(self, subtests):
        """`pass_memory`'s docstring is a SECOND COPY of PROCESS.md's measurements, and this is what
        makes the copy go red instead of quietly aging.

        The copy has to exist: the module is where someone reads why the cap is 16, and a pointer
        alone does not survive being read at 3 a.m. under an OOM. What it must not do is drift, and
        it already had twice over -- it argued from Earth's composite at 10.55 GiB and Mars at
        4.01 GiB, both of which PROCESS had retired in the section it points at, so a reader
        checking the source of the number found a different one and no sign of the disagreement.

        Retired figures stay in scope on purpose: naming one as retired is exactly as much a claim
        about PROCESS as citing it, and the retraction is the sentence most likely to be dropped.
        """
        figures = set(re.findall(r"\d+\.\d+ Gi?B", PASS_MEMORY_SOURCE.read_text()))
        assert len(figures) >= 8, f"only {figures} found; this scan is broken, not the module"
        process = PROCESS.read_text()
        for figure in sorted(figures):
            with subtests.test(figure):
                assert figure in process, (
                    f"pass_memory argues from {figure}, which PROCESS.md no longer carries anywhere"
                )

    def test_that_scan_can_actually_miss_one(self):
        """The positive control. Every figure in the module happens to be current, which is the
        state where a scan that found nothing and a scan that checked nothing look identical."""
        assert "999.99 GiB" not in PROCESS.read_text()
        assert re.findall(r"\d+\.\d+ Gi?B", "sized off 999.99 GiB plus headroom") == ["999.99 GiB"]

    @pytest.mark.parametrize("slug", sorted(bodies.BODIES))
    def test_every_registered_body_resolves(self, slug):
        assert pass_memory.limit_gib(bodies.get(slug)) > 0

    def test_the_argv_path_reads_the_body_through_the_passs_own_parser(self, monkeypatch):
        """`--out` is accepted here only because the pass accepts it; a parser private to this
        module would have to grow every flag separately, which is the drift sharing one avoids.

        `CAPLESS` is put in the registry rather than passed as an object because THIS path takes a
        name: `limit_for_argv` parses argv and resolves through `bodies.get`, so a capless body only
        reaches the resolver if the registry can answer for it.
        """
        monkeypatch.setitem(bodies.BODIES, CAPLESS.name, CAPLESS)
        assert pass_memory.limit_for_argv(["--body", "capless", "--tiles", "--out", "/x"]) == 12
        assert pass_memory.limit_for_argv(["--body", "earth"]) == 16


#: A cap spelled into prose: an integer, `G`, and the noun within reach. `GB`/`GiB` are excluded
#: because those are MEASUREMENTS, which belong in prose and are checked against PROCESS elsewhere.
CAP_IN_PROSE = re.compile(r"\b\d{1,2}\s?G\b(?!i?B)(?=[^.]{0,40}\b(?:cap|rule)\b)")


class TestNoModuleSpellsTheHeavyJobCapItself:
    """`HEAVY_JOB_GIB` is a RATIFIED POLICY with one owner, and prose that spells its value is a
    second copy that nothing can make go red.

    THIS WAS FOUND BY THE ROT, NOT BY THE RULE, WHICH IS THE POINT. Four comments still said `12 G`
    long after the policy moved to 16, and were logged as a four-site cleanup. The scan says eight:
    the other four say `16 G` and read as correct today, which is exactly the state the first four
    were in before the policy moved. A list of the sites that have already rotted is not the set.

    The fix is never to retype the number. A comment names `pass_memory.HEAVY_JOB_GIB`, which is
    true whatever the policy is, and a measurement against the cap keeps its own measured figure.
    """

    def candidates(self):
        """Every file that could spell the cap: the pipeline outside its owner, plus CLAUDE.md.

        CLAUDE.md IS IN SCOPE AND IS THE COPY THAT MATTERS MOST. It is the standing brief every
        session and every contributor reads, so a number spelled there outranks the same number in
        a module nobody opens — and it drifted exactly the way the eight code sites did, still
        claiming "no exemptions" against a lane that exempts five of its seven stages by design.
        """
        for path in sorted(REPO.joinpath("pipeline").rglob("*")):
            if path.suffix in {".py", ".sh"} and path.relative_to(REPO).parts[1] != "profile":
                yield path
        yield REPO / "CLAUDE.md"

    def scanned(self) -> list[tuple[str, int, str]]:
        found = []
        for path in self.candidates():
            for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                if CAP_IN_PROSE.search(line):
                    found.append((str(path.relative_to(REPO)), number, line.strip()))
        return found

    def test_no_module_outside_the_owner_spells_the_cap(self):
        spelled = self.scanned()
        assert not spelled, "prose spelling the heavy-job cap instead of naming it:\n  " + "\n  ".join(
            f"{path}:{number}: {line[:90]}" for path, number, line in spelled)

    def test_the_scan_can_actually_find_one(self):
        """The positive control, because a regex that matched nothing would pass the assertion above
        for the wrong reason, and this scan has already been wrong once in exactly that way."""
        assert CAP_IN_PROSE.search("OOM-killed at the 16 G cap, so the plane")
        assert CAP_IN_PROSE.search("under the standing 12 G cgroup cap")

    def test_the_scan_leaves_measurements_alone(self):
        """A measured peak is not the policy, and `pass_memory`'s own figures are checked elsewhere
        against PROCESS. Catching those here would push real numbers out of prose."""
        assert not CAP_IN_PROSE.search("a quadrant peaks near 8 G. -> HISTORY")
        assert not CAP_IN_PROSE.search("wants 17.0 GB, which dies loudly")
        assert not CAP_IN_PROSE.search("RGI 7.0 G regional shapefiles, every published region")
