"""The batch runner's render stage: the hero lands at its final path atomically, and nothing runs
after the render."""

import inspect
import subprocess
from pathlib import Path

import pytest

from pipeline import attribution, batch
from pipeline.render import render_seam

SLUG = "nepal"
FINAL = f"blender/renders/heroes/{SLUG}.png"


def fake_stages(_resolved):
    """The stages as the batch indexes them, the render last and naming its output as the real one
    does."""
    return [f"stage-{index}" for index in range(batch.RENDER_STAGE)] + [f"fake-render --render {FINAL}"]


class Recorder:
    """Stands in for `subprocess.run`: records each command, and has the render write the file its
    `--render` names, relative to the working directory the batch hands it."""

    def __init__(self, render_returncode):
        self.commands: list[str] = []
        self.render_returncode = render_returncode

    def __call__(self, command, *, shell, cwd, env, check):
        self.commands.append(command)
        words = command.split()
        if "--render" in words:
            written = Path(cwd) / words[words.index("--render") + 1]
            written.parent.mkdir(parents=True, exist_ok=True)
            written.write_bytes(b"rendered")
        return subprocess.CompletedProcess(command, self.render_returncode if "--render" in words else 0)


#: What each hero stage declared it read in the fixture's render directory.
DECLARED = {render_seam.PREP: ["glo30", "gebco"], render_seam.SNOW: ["rgi"],
            render_seam.LAKE: ["globathy"]}


def declare_stages(render_dir: Path, sources: dict[str, list[str]]) -> None:
    """A render directory whose three hero stages declared no images and these sources."""
    render_dir.mkdir(parents=True, exist_ok=True)
    for stage in attribution.HERO_STAGES:
        render_seam.declare(render_dir, stage, [])
        if stage in sources:
            render_seam.declare_sources(render_dir, stage, sources[stage])


@pytest.fixture
def runner(tmp_path, monkeypatch):
    # `FAIL_LOG` is derived from `ROOT` at import, so redirecting `ROOT` alone would leave a failure
    # logged into the checkout. The render directory lives under the data store, not `ROOT`.
    monkeypatch.setattr(batch, "ROOT", tmp_path)
    monkeypatch.setattr(batch, "FAIL_LOG", tmp_path / "batch_failures.jsonl")
    monkeypatch.setattr(batch, "stage_commands", fake_stages)
    monkeypatch.setattr(batch, "stage_env", dict)
    monkeypatch.setattr(batch, "wait_for_mem", lambda floor: True)
    render_dir = tmp_path / "work" / SLUG / "render"
    monkeypatch.setattr(batch, "country_render_dir", lambda slug: tmp_path / "work" / slug / "render")

    def run(render_returncode, sources=DECLARED):
        declare_stages(render_dir, sources)
        recorder = Recorder(render_returncode)
        monkeypatch.setattr(batch.subprocess, "run", recorder)
        outcome = batch.run_country(SLUG, {}, through="render", force=False, dry=False, cap_gib=16.0,
                                    use_cap=False, floor=0.0, clean=False)
        return outcome, recorder.commands

    return run


def test_the_render_writes_beside_the_hero_and_is_moved_into_place(tmp_path, runner):
    outcome, commands = runner(0)
    assert outcome == "ok"
    assert len(commands) == batch.RENDER_STAGE + 1, f"one process per stage and none after: {commands}"
    render = commands[-1].split()
    written = Path(render[render.index("--render") + 1])
    assert written != Path(FINAL), "the render wrote the hero in place, so a killed render leaves a partial one"
    assert written.parent == Path(FINAL).parent and written.suffix == ".png"
    assert (tmp_path / FINAL).read_bytes() == b"rendered"
    assert not (tmp_path / written).exists()
    assert sorted(path.name for path in (tmp_path / FINAL).parent.iterdir()) == [
        f"{SLUG}.png", attribution.hero_record_path(tmp_path / FINAL).name]


def test_the_hero_is_recorded_as_built_from_what_its_stages_declared(tmp_path, runner):
    outcome, _ = runner(0)
    assert outcome == "ok"
    assert attribution.hero_record(tmp_path / FINAL) == ("glo30", "gebco", "rgi", "globathy")


def test_a_stage_with_no_declared_sources_stops_the_country_before_the_render(tmp_path, runner):
    """A mask an earlier version wrote would be credited with what today's version reads, so the
    country stops rather than spending a render on a hero it cannot credit."""
    outcome, commands = runner(0, {render_seam.PREP: ["glo30"], render_seam.LAKE: ["globathy"]})
    assert outcome == f"FAIL@{batch.RENDER_STAGE} (sources)"
    assert len(commands) == batch.RENDER_STAGE, f"the render ran: {commands}"
    assert not (tmp_path / FINAL).exists()


def test_a_failed_render_leaves_neither_the_hero_nor_its_temporary(tmp_path, runner):
    outcome, _ = runner(1)
    assert outcome == f"FAIL@{batch.RENDER_STAGE} (error)"
    heroes = tmp_path / Path(FINAL).parent
    assert not heroes.exists() or not any(heroes.iterdir()), sorted(heroes.iterdir())


def test_the_batch_renders_only_the_countries_that_get_a_hero():
    """A `listed_only` country has no hero, so a batch walking the whole scope would render one
    anyway and the next manifest would publish it."""
    source = inspect.getsource(batch.main)
    assert "slugs = hero_slugs(scope)" in source
    assert "sorted(scope)" not in source
