"""`scripts.who_reads` — the lookup that executes a producer's source declarations.

WHY IT IS TESTED AT ALL, being an instrument that prints and gates nothing. Two of its properties
are not cosmetic. It CALLS functions in this package, so a widening of what it is willing to call is
a script that writes to the store while answering a question about it; and it reports a blind spot
by counting it, so a scan that silently stops finding a family shrinks the count and reads as better
coverage. Both fail quietly, which is what earns them a test.

The synthetic modules below are built so a text search cannot find the path they declare — that is
the control for the whole tool, since a grep is what it replaces.
"""

import importlib.util
from pathlib import Path
from types import ModuleType

import pytest

from pipeline.render import layer_producers, perennial_ice
from scripts import who_reads


def _load(tmp_path: Path, name: str, source: str) -> ModuleType:
    """Import `source` as a real module on disk, since the scans read `__file__` back."""
    path = tmp_path / f"{name}.py"
    path.write_text(source, encoding="utf-8")
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


COMPUTED = '''
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

STEM = "wid"


def _unit(suffix: str) -> Path:
    return Path("/store") / f"{STEM}{suffix}.json"


def _computed() -> tuple[Path, ...]:
    return tuple(_unit(suffix) for suffix in ("get", "ening"))


@dataclass(frozen=True)
class Producer:
    sources: Callable[[], tuple[Path, ...]]


ANY_NAME_AT_ALL = {("body", "layer"): Producer(sources=_computed)}
'''


class TestACallableDeclarationIsExecutedRatherThanRead:
    def test_a_source_no_grep_could_find_is_reported(self, tmp_path):
        """THE CONTROL FOR THE WHOLE TOOL. `widget.json` is assembled from a prefix and a suffix, so
        it appears nowhere in the module's text and a search for it returns the file that declares
        it zero times. Executing the declaration is the only way to reach the answer."""
        module = _load(tmp_path, "computed", COMPUTED)
        assert "widget.json" not in COMPUTED, "the control is void if the name is greppable"
        declared = who_reads.declarations([module])
        assert [entry.path for entry in declared] == [Path("/store/widget.json"),
                                                      Path("/store/widening.json")]

    def test_the_registry_is_found_by_shape_and_not_by_name(self, tmp_path):
        """A third body's registry is answered without editing the script, which is the whole reason
        the two that exist are written alike. `ANY_NAME_AT_ALL` is the assertion."""
        module = _load(tmp_path, "shaped", COMPUTED)
        assert who_reads.declarations([module])[0].producer.endswith(
            "ANY_NAME_AT_ALL[('body', 'layer')]")

    def test_the_declaration_carries_the_line_it_sits_on(self, tmp_path):
        """Half the real `sources` callables are lambdas, whose `__name__` is `<lambda>` for every
        one of them; `module.py:lineno` is the only identity that separates two of those."""
        module = _load(tmp_path, "located", COMPUTED)
        assert who_reads.declarations([module])[0].declared_at.endswith(":13")

    def test_a_dict_of_things_that_are_not_producers_declares_nothing(self, tmp_path):
        """The scan visits every module-level dict there is, so anything without a zero-argument
        `sources` has to fall straight through rather than raise."""
        module = _load(tmp_path, "plain", "LOOKUP = {'a': 1, 'b': 'two', 'c': None}\n")
        assert who_reads.declarations([module]) == []


class TestTheRealRegistriesAreReadWhole:
    """A round trip against production, written as a PROPERTY so that adding a body does not edit
    this file — the values are the registries' business, the reachability is this script's."""

    @pytest.mark.parametrize("registry", [perennial_ice.CAP_ICE_BY_BODY,
                                          layer_producers.PRODUCER_BY_BODY_LAYER])
    def test_every_path_a_producer_declares_comes_back(self, registry):
        modules, _ = who_reads.load_package()
        found = {entry.path for entry in who_reads.declarations(modules)}
        for producer in registry.values():
            assert set(producer.sources()) <= found


class TestNothingIsCalledSpeculatively:
    """The safety half. A widened filter here is a lookup that writes to the store it is describing,
    and the writers are excluded today only by taking an argument, which is luck and not a property.
    """

    WRITERS = '''
from pathlib import Path

CALLED = []


def write_thing() -> Path:
    CALLED.append("write_thing")
    return Path("/store/written.tif")


def thing_path(unit: str) -> Path:
    CALLED.append("thing_path")
    return Path("/store") / unit


def broken_path() -> Path:
    raise RuntimeError("no store here")


def good_path() -> Path:
    return Path("/store/good.tif")
'''

    def test_a_producer_that_returns_its_output_path_is_never_run(self, tmp_path):
        """`write_unit`, `_write_cap` and `render_cap_north` all annotate `-> Path` and all write.
        The return annotation alone does not separate them from an accessor; the name does."""
        module = _load(tmp_path, "writers", self.WRITERS)
        _found, uncalled = who_reads.accessors(module)
        assert vars(module)["CALLED"] == []
        assert ("writers.write_thing()", "not named as an accessor") in uncalled

    def test_an_accessor_needing_an_argument_is_reported_rather_than_guessed_at(self, tmp_path):
        module = _load(tmp_path, "writers2", self.WRITERS)
        _found, uncalled = who_reads.accessors(module)
        assert ("writers2.thing_path()", "takes an argument") in uncalled

    def test_an_accessor_that_raises_is_reported_and_the_run_continues(self, tmp_path):
        """A lookup that dies on one bad accessor answers nothing about the other sixty modules."""
        module = _load(tmp_path, "writers3", self.WRITERS)
        found, uncalled = who_reads.accessors(module)
        assert [naming.path for naming in found] == [Path("/store/good.tif")]
        assert any(where == "writers3.broken_path()" and "RuntimeError" in reason
                   for where, reason in uncalled)


class TestAnAncestorIsOrientationAndNotAnAnswer:
    """`names` and `covers` differ by exactly one direction, and the difference is the report's
    legibility: every path in the store sits under `paths.DATA`, so admitting ancestors as answers
    prints the same dozen rows for any file and buries the one that is about this file."""

    TARGET = Path("/store/mars/sim3292/lapc.json")

    def test_a_containing_directory_does_not_NAME_the_file(self):
        assert not who_reads.names(who_reads.Naming(Path("/store"), "d.DATA", True), self.TARGET)

    def test_the_path_itself_names_it(self):
        assert who_reads.names(who_reads.Naming(self.TARGET, "d.UNIT", True), self.TARGET)

    def test_a_binding_INSIDE_the_target_names_it_because_deleting_a_directory_reaches_it(self):
        naming = who_reads.Naming(self.TARGET, "d.UNIT", True)
        assert who_reads.names(naming, Path("/store/mars"))

    def test_a_declared_DIRECTORY_covers_a_file_beneath_it(self):
        """`freshness.newest_mtime` recurses into a directory, so a chunk under a VRT's directory
        moves that producer's gate exactly as the directory does."""
        assert who_reads.covers(Path("/store/mars"), self.TARGET)
        assert who_reads.covers(self.TARGET, Path("/store/mars"))

    def test_only_the_DEEPEST_container_is_offered_for_orientation(self):
        namings = [who_reads.Naming(Path(where), where, True)
                   for where in ("/store", "/store/mars", "/store/mars/sim3292")]
        assert [naming.where for naming in who_reads.inside(namings, self.TARGET)] == [
            "/store/mars/sim3292"]

    def test_one_row_per_PATH_and_not_per_binding(self):
        """A root is re-derived under its own name in module after module, so a file with no closer
        container would otherwise be announced once per spelling of `DATA`."""
        namings = [who_reads.Naming(Path("/store"), where, True)
                   for where in ("c.DATA", "a.DATA", "b.DATA")]
        assert [naming.where for naming in who_reads.inside(namings, self.TARGET)] == ["a.DATA"]

    def test_the_target_itself_is_not_offered_as_its_own_container(self):
        """It is already printed under NAMED BY, and a row repeated in two sections reads as two
        findings."""
        assert who_reads.inside([who_reads.Naming(self.TARGET, "d.UNIT", True)], self.TARGET) == []


class TestTheModuleViewIsWhatAHookCanHandOver:
    """`--module` is the form the `Read` hook injects, so its silence is load-bearing: a signal that
    fires on every module trains the eye to skip the one module where it mattered."""

    def test_a_file_in_the_package_resolves_to_its_dotted_name(self):
        assert who_reads.module_name(
            who_reads.ROOT / "pipeline/render/viking_luma.py") == "pipeline.render.viking_luma"

    @pytest.mark.parametrize("relative", ["scripts/who_reads.py", "web/package.json",
                                          "tests/test_who_reads.py"])
    def test_a_file_outside_the_package_resolves_to_nothing(self, relative):
        """The hook declines on this rather than on a path prefix of its own, so the two cannot
        disagree about what counts as a pipeline module."""
        assert who_reads.module_name(who_reads.ROOT / relative) is None

    def test_a_module_naming_no_store_path_prints_NOTHING(self, capsys):
        """The control for the hook's silence. `freshness` is general and belongs to no stage."""
        who_reads.module_view("pipeline.freshness", [], [], [])
        assert capsys.readouterr().out == ""

    def test_a_module_owning_only_a_gate_still_speaks(self, capsys):
        """Owning a private freshness predicate is itself the finding — it is the route by which a
        file no producer declares is nonetheless watched."""
        who_reads.module_view("m", [], [], ["m"])
        assert "OWNS is_fresh()" in capsys.readouterr().out

    def test_a_re_derived_root_is_named_but_not_expanded(self, capsys):
        """A root contains every declared source there is, so expanding it answers any module with
        the same rows — the ancestor noise `names` keeps out of the path lookup, arriving by the one
        constant per module that re-derives the checkout."""
        root = who_reads.store_root()
        namings = [who_reads.Naming(root.parent, "m.ROOT", True)]
        declared = [who_reads.Declaration(root / "raw/a.tif", "m.REG[('x',)]", "m.py:1")]
        who_reads.module_view("m", namings, declared, [])
        printed = capsys.readouterr().out
        assert "a re-derived root" in printed and "restages" not in printed

    def test_one_producer_is_named_ONCE_per_path_it_covers(self, capsys):
        """A directory covers several of a producer's own files, and the same producer printed once
        per file inside it reads as several producers restaging."""
        root = who_reads.store_root()
        namings = [who_reads.Naming(root / "raw/unit", "m.DATA_DIR", True)]
        declared = [who_reads.Declaration(root / "raw/unit/a.json", "m.REG[('x',)]", "m.py:1"),
                    who_reads.Declaration(root / "raw/unit/b.json", "m.REG[('x',)]", "m.py:1")]
        who_reads.module_view("m", namings, declared, [])
        assert capsys.readouterr().out.count("restages") == 1


class TestTheBlindSpotIsSizedRatherThanDescribed:
    def test_no_module_is_dropped_without_being_counted(self):
        """The failure this forbids is the quiet one: a module that will not import, skipped in
        silence, lets the report answer 'nothing names that file' about a file it never looked for.
        Stated as a total rather than by naming the `bpy` pair, so installing bpy is not a failure.
        """
        modules, failed = who_reads.load_package()
        on_disk = len(list(who_reads.ROOT.glob(f"{who_reads.PACKAGE}/**/*.py")))
        assert len(modules) + len(failed) == on_disk

    def test_a_module_gating_itself_is_named_as_unread(self, tmp_path):
        """A stage comparing its own recipe is watching its sources by a route this script does not
        read, so 'no producer declares it' must not be printed as 'nothing rebuilds'."""
        module = _load(tmp_path, "gated", "def is_fresh() -> bool:\n    return True\n")
        assert who_reads.private_gate(module) == "gated"

    def test_a_module_with_no_predicate_of_its_own_is_not_counted(self, tmp_path):
        """The count is only honest if it discriminates — `freshness` itself owns `is_stale` and no
        `is_fresh`, and a scan matching anything freshness-shaped would report every module."""
        module = _load(tmp_path, "ungated", "def is_stale() -> bool:\n    return True\n")
        assert who_reads.private_gate(module) is None
