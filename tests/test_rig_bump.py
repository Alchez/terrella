"""The terrain is displaced and bumped: the diced mesh is the geometry and casts the shadows, and each
pixel is shaded from the height image's own slope.

No gate here renders, so this holds the rig's value and the one line that applies it; whether the
result looks right was judged on rendered blocks.
"""

import ast
import importlib
import sys
import types
from pathlib import Path

import pytest

BUILDER = Path(__file__).resolve().parents[1] / "pipeline" / "render" / "scene_build.py"


@pytest.fixture(scope="module")
def scene_build():
    """`scene_build` with bpy stubbed, the same import the sync suite uses, removed afterwards."""
    stubbed = "bpy" not in sys.modules
    if stubbed:
        sys.modules["bpy"] = types.ModuleType("bpy")
    try:
        yield importlib.import_module("pipeline.render.scene_build")
    finally:
        if stubbed:
            del sys.modules["bpy"]


def displacement_method_writes(source: str) -> list[tuple[str, str]]:
    """Every write to a `displacement_method` attribute, as (enclosing function, value's source).

    An assignment, however nested its target, and a `setattr` naming the attribute.
    """
    writes = []
    for function in ast.walk(ast.parse(source)):
        if not isinstance(function, ast.FunctionDef):
            continue
        for node in ast.walk(function):
            if isinstance(node, (ast.Assign, ast.AnnAssign)):
                targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                if node.value is not None and any(
                        isinstance(part, ast.Attribute) and part.attr == "displacement_method"
                        for target in targets for part in ast.walk(target)):
                    writes.append((function.name, ast.unparse(node.value)))
            elif (isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "setattr"
                  and len(node.args) == 3 and isinstance(node.args[1], ast.Constant)
                  and node.args[1].value == "displacement_method"):
                writes.append((function.name, ast.unparse(node.args[2])))
    return writes


def test_the_terrain_is_displaced_and_bumped(scene_build):
    method = scene_build.RIG.displacement_method
    assert method == "BOTH", (
        f"RIG.displacement_method is {method!r}. 'DISPLACEMENT' shades from the diced mesh, which rounds "
        f"off relief a pixel or two wide; 'BUMP' drops the displaced geometry and every shadow it casts. "
        f"'BOTH' keeps the mesh for geometry and shades each pixel from the heights.")


def test_the_builder_puts_the_rig_s_method_on_the_terrain_material():
    """A material Blender makes is bump-only until told otherwise, so a builder that stopped writing
    the method would render flat ground shaded as relief, with no shadows and nothing raised."""
    writes = displacement_method_writes(BUILDER.read_text(encoding="utf-8"))
    assert writes == [("build_material", "RIG.displacement_method")], writes


def test_the_scan_sees_every_way_of_writing_the_method():
    written = (
        "def a():\n"
        "    mat.displacement_method = 'BUMP'\n"
        "def b():\n"
        "    (x, materials[0].displacement_method) = (1, RIG.displacement_method)\n"
        "def c():\n"
        "    setattr(mat, 'displacement_method', method)\n"
        "def d():\n"
        "    print(mat.displacement_method)\n"
    )
    assert displacement_method_writes(written) == [
        ("a", "'BUMP'"), ("b", "(1, RIG.displacement_method)"), ("c", "method")]
