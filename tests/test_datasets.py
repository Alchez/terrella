"""The raw-store registry: one home for a layout that was spelled at twenty-two of its readers."""

import inspect
import re

import pytest

from pipeline import datasets, paths

#: Every public accessor, DERIVED from the module rather than listed here. A list would go short
#: exactly when the registry grows, which is the failure this module exists to stop repeating.
ACCESSORS = [
    function for name, function in inspect.getmembers(datasets, inspect.isfunction)
    if not name.startswith("_") and function.__module__ == datasets.__name__
]


class TestTheRegistryResolvesAtCallTime:
    """The property that makes these functions and not the constants they replaced.

    A module-level `SOMEWHERE = DATA / "x"` resolves once at import, so a store redirected
    afterwards moves some of a module's paths and not others, silently.
    """

    def test_a_redirected_store_moves_every_entry(self, monkeypatch, tmp_path):
        """IN-PROCESS, which is the condition a constant survives. `MAPS_DATA` set before launch
        is not a test of this: a constant resolves under the new root then too, and looks right."""
        before = [accessor() for accessor in ACCESSORS]
        monkeypatch.setattr(paths, "DATA", tmp_path / "elsewhere")
        after = [accessor() for accessor in ACCESSORS]
        assert all(new.is_relative_to(tmp_path / "elsewhere") for new in after)
        assert all(new != old for new, old in zip(after, before, strict=True))

    def test_only_the_root_moves_and_not_the_layout(self, monkeypatch, tmp_path):
        """The control on the arm above, which every path merely DIFFERING would also satisfy —
        including an accessor that had started returning nonsense."""
        before = [accessor().relative_to(paths.DATA) for accessor in ACCESSORS]
        monkeypatch.setattr(paths, "DATA", tmp_path / "elsewhere")
        after = [accessor().relative_to(paths.DATA) for accessor in ACCESSORS]
        assert after == before


class TestTheRegistryIsWhatItClaims:
    def test_the_enumeration_found_the_accessors(self):
        """The control for every derived test here: all of them pass over an empty list."""
        assert len(ACCESSORS) >= 20, f"only {len(ACCESSORS)} accessors found"

    def test_no_two_accessors_name_one_location(self):
        """The defect this module replaced, re-created inside it: two names for one location is
        the same drift with a shorter blast radius, since a layout change edits one and not both."""
        located = [accessor() for accessor in ACCESSORS]
        duplicated = sorted({str(place) for place in located if located.count(place) > 1})
        assert not duplicated, f"two accessors name one location: {duplicated}"

    def test_nothing_escapes_the_raw_store(self):
        """A `..` or an absolute segment would resolve outside the store while still reading as an
        ordinary entry, and would then be written to on the next acquire run.

        RESOLVED BEFORE COMPARING, and that is the whole assertion. `is_relative_to` is LEXICAL:
        `<store>/raw/../worldcover` starts with `<store>/raw` as a sequence of parts, so the
        unresolved form answers True to the one input this exists to reject. Mutation caught it.
        """
        root = (paths.DATA / "raw").resolve()
        for accessor in ACCESSORS:
            assert accessor().resolve().is_relative_to(root), f"{accessor.__name__} escapes raw/"


class TestEveryLineSaysWhatWritesIt:
    """The docstrings are a contributor's route from a missing file to the command that makes it,
    so a renamed acquirer must not leave them pointing at a script that is gone.

    NOT A CHECK THAT THE PROSE IS TRUE, which nothing can do: it checks that every path it names
    exists, and that an entry claiming no acquirer is one this repo really has no script for.
    """

    ACQUIRER = re.compile(r"`(acquire/[\w.]+)`")

    def test_every_named_acquirer_exists(self):
        missing = []
        for accessor in ACCESSORS:
            for named in self.ACQUIRER.findall(accessor.__doc__ or ""):
                if not (paths.ROOT / "pipeline" / named).exists():
                    missing.append(f"{accessor.__name__} -> {named}")
        assert not missing, f"accessors naming a script that is not there: {missing}"

    def test_every_accessor_names_an_acquirer_or_says_there_is_none(self):
        """Set equality in effect: an entry that names neither is one nobody has ruled on, and a
        contributor hitting its missing file has nowhere to go."""
        silent = [accessor.__name__ for accessor in ACCESSORS
                  if not self.ACQUIRER.search(accessor.__doc__ or "")
                  and "NO ACQUIRER" not in (accessor.__doc__ or "")]
        assert not silent, f"accessors saying nothing about what writes them: {silent}"

    @pytest.mark.parametrize("accessor_name", ["snow_persistence", "worldcover"])
    def test_the_manual_datasets_really_have_no_script(self, accessor_name):
        """The other direction, and the one that rots quietly: if someone writes the acquirer, this
        docstring becomes a lie that sends a contributor to download by hand for no reason."""
        stem = accessor_name.split("_")[0]
        scripts = [path.name for path in (paths.ROOT / "pipeline/acquire").iterdir()
                   if stem in path.name.lower() and path.suffix in {".py", ".sh"}]
        assert not scripts, f"{accessor_name} now has an acquirer ({scripts}); drop NO ACQUIRER"
