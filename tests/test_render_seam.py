"""What a render directory declares it holds, and the inference the declaration replaces.

The failure this closes has no symptom of its own: a prep that measured no snow and a prep that died
before writing the snow mask leave the same directory, and the rig renders the second one as a
snowless scene with every gate green. So the guards below are almost all about the difference
between "this stage ran and produced nothing" and "this stage did not run".
"""

import ast
import json
import re
from pathlib import Path

import pytest

from pipeline import render_files
from pipeline.render import render_seam

PIPELINE_ROOT = Path(__file__).resolve().parent.parent / "pipeline"


def _dir(tmp_path, *images):
    """A render directory holding `images` as real (empty) files, declared by nobody yet."""
    render_dir = tmp_path / "render"
    render_dir.mkdir()
    for image in images:
        (render_dir / image).write_bytes(b"")
    return render_dir


def _imports_the_rig(source: Path) -> bool:
    """True if this module imports anything under `pipeline.render` in any spelling."""
    for node in ast.walk(ast.parse(source.read_text())):
        if isinstance(node, ast.Import):
            if any(alias.name.startswith("pipeline.render") for alias in node.names):
                return True
        elif isinstance(node, ast.ImportFrom):
            if (node.module or "").startswith("pipeline.render"):
                return True
            if node.module == "pipeline" and any(alias.name == "render" for alias in node.names):
                return True
    return False


def test_no_look_module_imports_the_rig():
    """`look/__init__.py` states this as a law, and a filename constant is not an exception to it.

    Both rigs read `look/`, so an import in this direction puts a module on the wrong side of the
    seam. The names a render directory holds are `render_files`, which is at the top level for the
    five packages that read it.
    """
    look = sorted((PIPELINE_ROOT / "look").glob("*.py"))
    assert look, "the look package scan matched nothing"
    offenders = sorted(str(source.relative_to(PIPELINE_ROOT.parent))
                       for source in look if _imports_the_rig(source))
    assert offenders == [], (
        "a look module imports the hero rig, which the package forbids:\n  " + "\n  ".join(offenders)
    )


class TestAnEmptyRecordIsAStatement:
    """The whole point of the module, and the one case a directory listing cannot express."""

    def test_a_stage_that_produced_nothing_is_distinguishable_from_one_that_never_ran(self, tmp_path):
        ran = _dir(tmp_path, render_files.HEIGHTFIELD)
        render_seam.declare(ran, render_seam.PREP, [render_files.HEIGHTFIELD])
        render_seam.declare(ran, render_seam.SNOW, [])
        stages = json.loads(render_seam.declaration_path(ran).read_text())["stages"]
        assert stages[render_seam.SNOW] == [], "an empty list is the statement 'I found no snow'"
        assert render_seam.LAKE not in stages, "a stage that never ran must leave no record at all"

    def test_both_read_back_as_no_snow_which_is_why_the_record_and_not_the_union_carries_it(
            self, tmp_path):
        """The union cannot tell them apart, and is not supposed to — the RECORD is where the
        difference lives, so a caller that needs it asks for the stages rather than the images."""
        ran = _dir(tmp_path, render_files.HEIGHTFIELD)
        render_seam.declare(ran, render_seam.PREP, [render_files.HEIGHTFIELD])
        render_seam.declare(ran, render_seam.SNOW, [])
        assert render_files.SNOWMASK not in render_seam.declared(ran)


class TestADeclarationIsCheckedAgainstDisk:
    def test_naming_an_image_that_is_not_there_is_refused(self, tmp_path):
        render_dir = _dir(tmp_path, render_files.HEIGHTFIELD)
        with pytest.raises(FileNotFoundError, match=render_files.SNOWMASK):
            render_seam.declare(render_dir, render_seam.SNOW, [render_files.SNOWMASK])

    def test_an_unknown_image_is_a_typo_and_not_an_absence(self, tmp_path):
        render_dir = _dir(tmp_path, render_files.HEIGHTFIELD, "heightfeild.tif")
        with pytest.raises(ValueError, match="unknown render input"):
            render_seam.declare(render_dir, render_seam.PREP, ["heightfeild.tif"])

    def test_an_unknown_stage_is_refused(self, tmp_path):
        render_dir = _dir(tmp_path, render_files.HEIGHTFIELD)
        with pytest.raises(ValueError, match="unknown stage"):
            render_seam.declare(render_dir, "warp", [render_files.HEIGHTFIELD])


class TestTheChainResumesWithoutErasingItself:
    def test_re_running_one_stage_leaves_the_others_standing(self, tmp_path):
        """`batch.py` resumes a country mid-chain, so a stage rewriting the whole file would drop
        the stages behind it and turn a resume into a silently thinner declaration."""
        render_dir = _dir(tmp_path, render_files.HEIGHTFIELD, render_files.SNOWMASK,
                          render_files.LAKEDEPTH)
        render_seam.declare(render_dir, render_seam.PREP, [render_files.HEIGHTFIELD])
        render_seam.declare(render_dir, render_seam.SNOW, [render_files.SNOWMASK])
        render_seam.declare(render_dir, render_seam.LAKE, [render_files.LAKEDEPTH])
        render_seam.declare(render_dir, render_seam.SNOW, [render_files.SNOWMASK])
        assert render_seam.declared(render_dir) == {
            render_files.HEIGHTFIELD, render_files.SNOWMASK, render_files.LAKEDEPTH}


class TestAnUnfilledDirectoryIsNotAnEmptyOne:
    def test_no_declaration_at_all_raises_rather_than_returning_nothing(self, tmp_path):
        """The `planet_seam` rule one tier down: an empty answer is a statement about the region,
        a missing file is a statement about the pipeline, and the two must not share a value."""
        with pytest.raises(FileNotFoundError, match="no stage has declared"):
            render_seam.declared(_dir(tmp_path, render_files.HEIGHTFIELD))

    def test_a_directory_whose_optional_stages_spoke_but_whose_prep_did_not_still_raises(
            self, tmp_path):
        """The case a per-stage record makes possible and a single sealing write does not: snow ran
        and found nothing, and the heightfield is missing because the FIRST stage died."""
        render_dir = _dir(tmp_path)
        render_seam.declare(render_dir, render_seam.SNOW, [])
        with pytest.raises(FileNotFoundError, match="stages that have spoken"):
            render_seam.declared(render_dir)

    def test_the_error_names_the_stages_that_did_speak(self, tmp_path):
        render_dir = _dir(tmp_path)
        render_seam.declare(render_dir, render_seam.SNOW, [])
        with pytest.raises(FileNotFoundError, match=render_seam.SNOW):
            render_seam.declared(render_dir)


class TestTheVocabularyIsTheRigsOwn:
    def test_the_named_images_are_exactly_the_whole_vocabulary(self):
        """Named rather than counted, because the count is what rotted last time: this class's
        previous name said "the mandatory four and the optional three" and stayed green through
        sea ice landing, since a test name is prose and prose does not assert."""
        assert render_files.KNOWN_IMAGES == {
            render_files.HEIGHTFIELD, render_files.OCEANMASK, render_files.INLANDLAKE,
            render_files.RIVER, render_files.SNOWMASK, render_files.LAKEDEPTH, render_files.SEAICE,
            render_files.ROWSCALE}


def _docstring_nodes(tree: ast.Module) -> set[int]:
    """The `id()`s of every docstring constant, so the scan below can pass over prose."""
    doc_nodes: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Module | ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef):
            body = node.body
            if (body and isinstance(body[0], ast.Expr)
                    and isinstance(body[0].value, ast.Constant)
                    and isinstance(body[0].value.value, str)):
                doc_nodes.add(id(body[0].value))
    return doc_nodes


class TestTheSpellingsHaveOneOwner:
    """Every module takes the render-directory filenames from `render_files` rather than spelling
    them, so a rename is one edit and a reintroduced literal fails here instead of at render time.

    Two owners, and the scan skips both: `render_files` for the images and `render_seam` for the
    declaration it writes beside them.

    Docstrings are exempt: prose naming a file describes it, and cannot silently disagree with a
    `Path` the way a second load-bearing literal can. Comments never reach the AST at all.
    """

    OWNERS = ("render_files.py", "render_seam.py")

    def test_no_pipeline_module_spells_a_render_filename(self):
        owned = sorted(render_files.KNOWN_IMAGES
                       | {render_files.OCEANMASK_TIF, render_files.WATERMASK,
                          render_seam.DECLARATION_NAME})
        # a name at the start of the string or after a path separator is one of ours; the same
        # characters as the TAIL of a longer basename, as a prefixed sibling like
        # `planet_oceanmask` would be, are a different file in a different vocabulary
        spells = re.compile("(^|/)(" + "|".join(re.escape(name) for name in owned) + ")")
        modules = sorted(PIPELINE_ROOT.rglob("*.py"))
        found = {module.name for module in modules} & set(self.OWNERS)
        assert found == set(self.OWNERS), \
            f"an owner left the scanned tree, so the scan is checking nothing: {found}"
        offenders = []
        for module in modules:
            if module.name in self.OWNERS:
                continue
            tree = ast.parse(module.read_text())
            docstrings = _docstring_nodes(tree)
            for node in ast.walk(tree):
                if (isinstance(node, ast.Constant) and isinstance(node.value, str)
                        and id(node) not in docstrings
                        and spells.search(node.value)):
                    offenders.append(f"{module.relative_to(PIPELINE_ROOT.parent)}"
                                     f":{node.lineno}: {node.value!r}")
        assert offenders == [], \
            "spell it in render_files and import it:\n" + "\n".join(offenders)
