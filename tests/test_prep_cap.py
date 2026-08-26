"""The cap prep: fill a render directory the rig can photograph, and declare it as its OWN stage.

`prep_block`'s sibling, and the tests mirror that one's concerns because the failures are the same
shape. What differs is the geometry: a block is a rectangle of the Mercator grid photographed 1:1,
where a cap is a square AEQD plane photographed one QUADRANT at a time, so the numbers that reach
the rig are not the plane's.

THE STAGE IS THE FIRST SUBJECT. The arm that proved this renderer declared itself as `prep`, because
`render_seam.KNOWN_STAGES` is closed and refused anything else — its own comment says production
must add a stage rather than borrow one. A borrowed stage is not a cosmetic lie: `declared` unions
every stage's images, so two preps writing under one name cannot be told apart by anything that
reads the declaration back.
"""

import dataclasses
import json
from pathlib import Path

import numpy as np
import pytest

from pipeline import bodies, paths, planet_seam
from pipeline.acquire import download_add_rock
from pipeline.look import seaice, snow
from pipeline.render import prep_cap, render_seam
from pipeline.tile import cap_render

#: A planet whose seam emitted all three rasters — what Earth declares.
WHOLE_PLANET = planet_seam.KNOWN_RASTERS

EARTH = bodies.EARTH


def _small(grid: cap_render.CapGrid, px: int = 8) -> cap_render.CapGrid:
    """The same grid at a size a unit test can write.

    THE SHRINK IS WHY NO ASSERTION BELOW INDEXES WITH `CAP_PX`. A production constant used to slice
    a shrunken fixture selects nothing, and `np.all` over an empty selection is True — an assertion
    that passes having touched no pixel. Bounds come off `array.shape` here for that reason.
    """
    return dataclasses.replace(grid, px=px)


@pytest.fixture
def prepped(monkeypatch, tmp_path):
    """Drive the REAL prep with only its gdalwarp edge recorded, and hand back the directory.

    `cap_render._warp` is the boundary — it shells out to gdalwarp — so it is replaced. Everything
    between it and the declaration is the real code, which is what makes the declaration's contents
    an assertion about the prep rather than about this fixture.

    Every Earth source is redirected onto a file that EXISTS, reproducing the build box where each
    is one global path present whatever planet is being rendered; `_drive_cap` in
    `tests/test_cap_render.py` holds the full argument for why that is the honest fixture.
    """
    monkeypatch.setattr(paths, "DATA", tmp_path / "data")
    monkeypatch.setattr(paths, "ROOT", tmp_path / "checkout")
    present = tmp_path / "an-earth-dataset-this-box-already-has"
    present.write_text("")
    monkeypatch.setattr(snow, "SP_NC", str(present))
    monkeypatch.setattr(seaice, "SEAICE_SRC", str(present))
    monkeypatch.setattr(cap_render, "COAST_SHP", present)

    def fake_warp(grid, src, out, resampling, dtype, srcnodata=None):
        layer = Path(out).stem.split("_", 1)[1]
        if layer == "ocean":
            # HALF SEA AND HALF LAND. A disc that is all ocean leaves the forced Antarctic patch no
            # land to paint, and one that is all land leaves the gated ice alpha nowhere to survive;
            # this prep writes both masks, so it needs both to exist.
            sea = np.zeros((grid.px, grid.px), dtype=np.float32)
            sea[:, : grid.px // 2] = 1.0
            return sea
        if layer == "seaice":
            return np.full((grid.px, grid.px), 9000.0, dtype=np.float32)
        return np.zeros((grid.px, grid.px), dtype=np.float32)

    monkeypatch.setattr(cap_render, "_warp", fake_warp)

    def fake_burn(grid, source, name, must_draw):
        """`_burn` is the OTHER boundary, and the south is why this fixture needs it.

        That disc burns the SCAR outcrop, so an unpatched run reads whether this box holds a 206 MB
        download and shells out to a real ogr2ogr inside a unit test — and on a stand-in file it
        raises `NothingBurnt`, which is the burn reporting a fixture rather than a defect.
        """
        return np.zeros((grid.px, grid.px), dtype=bool)

    monkeypatch.setattr(cap_render, "_burn", fake_burn)
    monkeypatch.setattr(download_add_rock, "GPKG", present)

    def run(pole: str = "north", body: bodies.Body = EARTH) -> Path:
        grid = _small(cap_render.north_grid(body) if pole == "north"
                      else cap_render.south_grid(body))
        outdir = tmp_path / f"render_{pole}"
        prep_cap.cut(grid, WHOLE_PLANET, outdir)
        return outdir

    return run


def _stages(outdir: Path) -> dict:
    return json.loads(render_seam.declaration_path(outdir).read_text())["stages"]


class TestTheCapStageIsItsOwn:
    """The stage a cap prep declares under is a fact about which producer filled the directory."""

    def test_the_declaration_names_the_cap_stage(self, prepped):
        assert render_seam.CAP in _stages(prepped())

    def test_it_does_not_borrow_another_prep_s_stage(self, prepped):
        """The arm declared `prep`, and that is the state this replaces.

        Asserted against BOTH other preps rather than just the borrowed one, because the defect is
        "a cap wearing someone else's name" and which name it wore is incidental.
        """
        stages = _stages(prepped())
        for borrowed in (render_seam.PREP, render_seam.BLOCK):
            assert borrowed not in stages, (
                f"the cap prep declared itself as {borrowed!r}; `declared` unions images across "
                f"stages, so nothing reading this back could tell the two preps apart")

    def test_every_stage_constant_is_in_the_vocabulary(self):
        """`KNOWN_STAGES` derives from `STAGE_TOOL`, so a mapping entry added without a constant
        beside it makes a stage declarable only by a string literal — greppable by nobody.

        THIS CANNOT SEE THE OTHER DIRECTION and that is not an oversight: a constant whose value is
        outside the vocabulary is filtered out by the membership test below, so an assertion here
        could never fail on one. `declare` refuses that at run time, and the derivation is what
        removed the gate-time hole rather than this test.
        """
        named = {value for name, value in vars(render_seam).items()
                 if name.isupper() and isinstance(value, str) and value in render_seam.KNOWN_STAGES}
        assert named == set(render_seam.KNOWN_STAGES), (
            f"in the vocabulary with no constant naming them: "
            f"{sorted(set(render_seam.KNOWN_STAGES) - named)}")

    def test_every_stage_names_a_tool_that_exists(self):
        """The mapping's whole job is to name the right module in a message read at a bad moment.

        A name it carries is only worth trusting if the file is there, and this is the half that
        rots: a prep gets renamed and the message keeps sending readers to the old spelling. A
        deliberately wrong but EXISTING mapping is not catchable here, and nothing pretends it is.
        """
        root = Path(__file__).resolve().parents[1] / "pipeline"
        assert render_seam.STAGE_TOOL, "an empty mapping would make the loop below vacuous"
        for stage, tool in sorted(render_seam.STAGE_TOOL.items()):
            assert list(root.rglob(tool)), f"{stage} names {tool}, which is not under pipeline/"


class TestTheFrameDescribesOneQuadrantOfTheDisc:
    """Where the plane and the photographed rectangle differ, and each reaches the rig separately.

    THE REAL GRID, NOT THE SHRUNKEN ONE. `write_frame` reads nothing off disk, so it can be asked
    about the production geometry directly — and it must be, because every number here is a fact
    about `CAP_PX` and the quadrant split rather than about whatever a fixture chose.
    """

    @pytest.fixture
    def frame(self, tmp_path):
        prep_cap.write_frame(cap_render.north_grid(EARTH), tmp_path)
        return json.loads((tmp_path / "frame.json").read_text())

    def test_the_render_resolution_is_one_quadrant(self, frame):
        edge = cap_render.CAP_PX // cap_render.CAP_QUADRANT_SPLIT
        assert (frame["res_x"], frame["res_y"]) == (edge, edge), (
            "the camera is photographing the whole disc in one frame, which is the shape that was "
            "OOM-killed at the 16 G cap")

    def test_the_plane_is_the_whole_disc(self, frame):
        """The other half of the three-widths trap: the heightfield is the PLANE, so a frame that
        described the plane as one quadrant would ask the rig for a texture that does not exist."""
        assert (frame["width_px"], frame["height_px"]) == (cap_render.CAP_PX, cap_render.CAP_PX)

    def test_the_ortho_scale_is_what_the_quadrant_camera_requires(self, frame):
        """1.0 is not a coincidence and it is not free. The plane is 2.0 Blender units across, so a
        camera seeing `1 / SPLIT` of it has `ortho_scale = 2.0 / SPLIT`, and the quadrant camera
        offsets by half an `ortho_scale` to centre on its own quarter. At any other value the four
        frames overlap or leave a gap, and a stitched disc with a one-pixel gap reads as a render
        artefact rather than as a wrong number.
        """
        assert frame["ortho_scale"] == pytest.approx(2.0 / cap_render.CAP_QUADRANT_SPLIT)

    def test_the_projection_is_the_grid_s_own(self, frame):
        """Read off `CapGrid.aeqd` rather than rebuilt here. A second spelling of the proj string
        would project perfectly and land the disc on the wrong parallel."""
        assert frame["dst_crs"] == cap_render.north_grid(EARTH).aeqd

    def test_the_two_poles_do_not_share_a_frame(self, tmp_path):
        north, south = tmp_path / "n", tmp_path / "s"
        north.mkdir()
        south.mkdir()
        prep_cap.write_frame(cap_render.north_grid(EARTH), north)
        prep_cap.write_frame(cap_render.south_grid(EARTH), south)
        assert (north / "frame.json").read_text() != (south / "frame.json").read_text()


class TestWhatTheCapPrepWrites:
    def test_it_declares_the_masks_the_rig_reads(self, prepped):
        """Existence is not re-asserted here: `render_seam.declare` refuses to name an image that
        is not on disk, so a declaration that came back at all has already paid for that."""
        declared = _stages(prepped())[render_seam.CAP]
        assert set(declared) >= {render_seam.HEIGHTFIELD, render_seam.OCEANMASK,
                                 render_seam.INLANDLAKE, render_seam.RIVER}

    def test_it_writes_no_rowscale_and_that_absence_is_declared(self, prepped):
        """AEQD is equidistant from its centre by construction, so there is nothing to correct.

        THE DECLARATION IS WHAT MAKES THE ABSENCE A STATEMENT. A column of ones would be a
        fabricated dataset; a missing file with a stage record beside it is the honest form, and it
        is the one `render_seam` exists to carry.
        """
        outdir = prepped()
        assert render_seam.ROWSCALE not in _stages(outdir)[render_seam.CAP]
        assert not (outdir / render_seam.ROWSCALE).exists()

    def test_the_painted_masks_carry_their_colour(self, prepped):
        """The rig cannot ask a body for a white; the prep resolves it and declares it here.

        THE PAINTED SET IS ASSERTED NON-EMPTY FIRST. A loop over whichever masks happen to be
        present passes trivially on a fixture that produced neither, which is the shape this
        module's ice stand-in was written to avoid in the first place.
        """
        outdir = prepped()
        painted = set(_stages(outdir)[render_seam.CAP]) & render_seam.PAINTED_IMAGES
        assert painted, "this fixture wrote no painted mask, so the assertion below reaches nothing"
        for image in sorted(painted):
            sunlit, shadowed = render_seam.paint_for(outdir, image)
            assert len(sunlit) == 3 and len(shadowed) == 3

    def test_the_recipe_sits_beside_the_output(self, prepped):
        """Every writer records its recipe beside its output, because existence cannot see a
        settings change."""
        recipe = json.loads((prepped() / prep_cap.RECIPE_NAME).read_text())
        assert recipe["body"] == EARTH.name
        assert recipe["pole"] == "north"
        assert recipe["exaggeration"] == EARTH.exaggeration

    def test_the_south_declares_its_own_pole(self, prepped):
        assert json.loads((prepped("south") / prep_cap.RECIPE_NAME).read_text())["pole"] == "south"
