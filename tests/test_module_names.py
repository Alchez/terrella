"""The package's module boundaries: no name reads as another backwards, and no module holds two
stages that only ever shared a deleted third.

WHY THIS EXISTS. `profile/pass_cap.py` sized a planet pass's MEMORY CEILING while `tile/cap_pass.py`
rendered a body's POLAR CAPS, and the two names are the same two tokens in opposite orders. One
concept-word carrying two unrelated meanings is bad enough; spelling both arrangements makes every
grep for `cap_` and every reach for "the cap module" ambiguous, and `pass_cap`'s own docstring had to
name `cap_render` in its second sentence to say which `cap` it did not mean.

WHY REVERSALS ONLY, AND NOT THE WIDER FAMILY SPLIT. Eleven tokens appear in both first and last
position across this package (`block`, `borders`, `build`, `cap`, `country`, `mars`, `pass`,
`planet`, `prep`, `raster`, `render`), and most of those pairs are fine: `prep_block` beside
`block_render` reads as prepare-then-render on one subject. A guard over all eleven would be red for
names nobody intends to change, which is the shape of guard this repo has deleted before rather than
shipped. An exact reversal is the narrow case where the two names are mutually unreadable.

The polar meaning of `cap` wins by count: `cap_pass`, `cap_raytrace`, `cap_render`, `prep_cap`,
`caps.json` and `CAP_EDGE_LAT` all mean the disc, so a memory ceiling is the outlier that renames.
"""

from pathlib import Path

REPO = Path(__file__).resolve().parents[1]


def module_names() -> list[str]:
    """Every pipeline module's bare name, packages and `__init__` excluded."""
    return sorted(
        path.stem
        for path in (REPO / "pipeline").rglob("*.py")
        if path.stem != "__init__" and "test" not in path.parts
    )


def reversed_pairs(names: list[str]) -> list[tuple[str, str]]:
    """Names that are one another's tokens in the opposite order, each pair reported once."""
    by_tokens = {name: tuple(name.split("_")) for name in names if "_" in name}
    return sorted(
        (one, other)
        for one, one_tokens in by_tokens.items()
        for other, other_tokens in by_tokens.items()
        if one < other and one_tokens == other_tokens[::-1]
    )


def test_the_detector_finds_a_reversal_it_is_given() -> None:
    """The control. A guard that reports nothing is indistinguishable from a broken tokeniser."""
    planted = ["pass_cap", "cap_pass", "cap_render", "unrelated"]
    assert reversed_pairs(planted) == [("cap_pass", "pass_cap")]
    assert reversed_pairs(["cap_render", "prep_cap", "block_render"]) == []


def test_no_two_modules_are_token_reversals_of_each_other() -> None:
    found = reversed_pairs(module_names())
    assert not found, (
        f"module names that read as each other backwards: {found}. One concept-word cannot carry "
        "two meanings in one package; rename the outlier rather than disambiguating in a docstring")


def test_the_planet_warp_and_the_tile_cut_are_not_one_module() -> None:
    """They ran hours apart and shared only a subprocess helper, and one file held both.

    THE TEMPTATION IS TO PUT THEM BACK, because each is small and both say "planet" in the docstring.
    What held them together was a numpy composite shader between them: the warp was its input stage
    and the cut its output stage, so `shade_planet` was a name for the shader, not for either half.
    The shader is deleted. Re-merging them re-creates a module that can only be named for a hole,
    and the tell is that no `verb_object` name fits the result.
    """
    from pipeline import planet_warp
    from pipeline.tile import cut_tiles

    assert hasattr(planet_warp, "warp_inputs"), "the warp lives in pipeline.planet_warp"
    assert hasattr(cut_tiles, "build_tiles"), "the cut lives in pipeline.tile.cut_tiles"
    assert not hasattr(planet_warp, "build_tiles"), "the cut must not follow the warp back"
    assert not hasattr(cut_tiles, "warp_inputs"), "the warp must not follow the cut back"
