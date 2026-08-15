"""`freshness.recorded_json` — the one predicate every stage's sidecar comparison goes through.

Its own module because `freshness.py` is general and belongs to no stage, and because this helper
replaced SEVEN hand-written spellings across five modules: two acquirers, one render stage and
three composers. Their individual regression tests live beside each stage and prove the call site
uses this; what is proved here is the contract they all now depend on.

THE PROPERTY UNDER TEST IS "ANSWERS RATHER THAN RAISES", and every case is a different way of not
being a recipe. That framing is the correction: the predicate this replaced named the same property
in its docstring and tested only unparseable bytes, so a document that parsed into the wrong shape
walked through the guard and raised in the caller.
"""

import json

import pytest

from pipeline import freshness


class TestARecipeThatCannotBeReadIsNotARecipe:
    def test_a_real_object_comes_back_unchanged(self, tmp_path):
        """The control. Every assertion below is satisfied by a function that returns None always,
        and this is the one that is not."""
        recipe = {"simplification": 2.0, "zoom": [0, 8], "nested": {"a": [1, 2]}}
        path = tmp_path / "recipe.json"
        path.write_text(json.dumps(recipe), encoding="utf-8")
        assert freshness.recorded_json(path) == recipe

    def test_a_missing_file_is_None_without_the_caller_checking_first(self, tmp_path):
        """`OSError` covers absence, so no call site needs its own `.exists()` — and the four that
        had one were each spelling that check differently."""
        assert freshness.recorded_json(tmp_path / "never-written.json") is None

    def test_a_directory_in_place_of_the_file_is_None(self, tmp_path):
        """`IsADirectoryError` is an `OSError`; a stage whose sidecar path collided with a directory
        would otherwise raise from inside a freshness question."""
        (tmp_path / "recipe.json").mkdir()
        assert freshness.recorded_json(tmp_path / "recipe.json") is None

    def test_a_truncated_write_is_None(self, tmp_path):
        path = tmp_path / "recipe.json"
        path.write_text('{"simplification": 2.0, "zo', encoding="utf-8")
        assert freshness.recorded_json(path) is None

    def test_bytes_that_are_not_utf8_are_None(self, tmp_path):
        """`UnicodeDecodeError` subclasses `ValueError`, so one `except` covers both halves of
        'unreadable' — but only if nobody narrows it back to `JSONDecodeError`."""
        path = tmp_path / "recipe.json"
        path.write_bytes(b"\xff\xfe\x00\x01 not text")
        assert freshness.recorded_json(path) is None

    @pytest.mark.parametrize("literal", ["5", "-1.5", '"a string"', "[]", "[1, 2, 3]", "null",
                                         "true"])
    def test_valid_json_that_is_not_an_OBJECT_is_None(self, literal, tmp_path):
        """The half the old spellings missed. Each of these parses; none is a recipe. A list reaches
        `.items()` or `["features"]` and raises `AttributeError`/`TypeError`, a string indexes
        without raising at all, and `null` compares equal to nothing."""
        path = tmp_path / "recipe.json"
        path.write_text(literal, encoding="utf-8")
        assert freshness.recorded_json(path) is None

    def test_an_empty_object_is_returned_and_NOT_None(self, tmp_path):
        """`{}` is a usable object, and the distinction matters: it must reach the caller so the
        caller's own comparison rejects it. Folding it into None here would move a stage's decision
        into this helper, where the recipe it should be compared against is not known."""
        path = tmp_path / "recipe.json"
        path.write_text("{}", encoding="utf-8")
        assert freshness.recorded_json(path) == {}

    def test_None_never_equals_a_recipe_which_is_how_call_sites_use_it(self, tmp_path):
        """The idiom every converted site now reads as: `recorded_json(p) == recipe()`. It is only
        correct because None compares unequal to a dict, so an absent sidecar is stale rather than
        an error — this pins the property that lets the `.exists()` checks be deleted."""
        assert freshness.recorded_json(tmp_path / "gone.json") != {"simplification": 2.0}
