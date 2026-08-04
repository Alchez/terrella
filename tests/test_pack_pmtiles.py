"""pack_pmtiles: the XYZ tile directory -> MBTiles bridge (blobs moved, never re-encoded).

`pmtiles convert` reads only MBTiles
dir -> MBTiles -> convert), and the one real trap is the row flip: MBTiles stores
TMS rows (origin bottom-left) while our pyramid is XYZ (origin top-left,
`gdal raster tile --convention=xyz`). A silent flip error would serve a
vertically mirrored planet, so the flip and the byte-fidelity both get pinned.
"""

import sqlite3
import sys
from typing import ClassVar

import pytest

from pipeline import bodies, paths
from pipeline.tile import pack_pmtiles
from pipeline.tile.pack_pmtiles import (
    default_out,
    default_tiles,
    pack_directory,
    tms_row,
)


class TestTmsRow:
    def test_flip_at_each_zoom(self):
        assert tms_row(0, 0) == 0                # the single z0 tile is its own mirror
        assert tms_row(1, 0) == 1
        assert tms_row(1, 1) == 0
        assert tms_row(8, 0) == 255              # top XYZ row -> bottom TMS row
        assert tms_row(8, 255) == 0              # the Antarctica row (z8 y=255)

    def test_flip_is_an_involution(self):
        for zoom, row in ((3, 5), (8, 100), (5, 0)):
            assert tms_row(zoom, tms_row(zoom, row)) == row


class TestTheBodyChoosesTheTree:
    """Where a pack reads and writes is the BODY's question, and it had no way to ask it.

    Both defaults used to be literals joined onto the checkout, so a pack was Earth-only twice over:
    it could not address a second planet's pyramid, and it bypassed the `MAPS_DATA` seam that every
    other stage of the tile chain honours. The two defects share one fix, because `bodies.work_dir`
    answers both at once.
    """

    def test_earths_defaults_are_exactly_where_the_shipped_pyramid_already_lives(self, subtests):
        """The characterisation half: Earth's paths must not move by one byte.

        A pyramid is cut, packed and converted at these paths and the archive on R2 came from them.
        A default that resolved anywhere else would not fail — it would pack an empty tree, or pack
        nothing and report success against a directory nobody is writing.
        """
        with subtests.test("tiles"):
            assert default_tiles(bodies.EARTH) == paths.DATA / "work/planet_tiles/tiles"
        with subtests.test("out"):
            assert default_out(bodies.EARTH) == paths.DATA / "work/planet_tiles/planet.mbtiles"

    def test_mars_nests_under_its_own_prefix(self, subtests):
        """The generalisation is unverified until a non-default body runs through it: Earth's
        prefix is empty, so Earth passes whether or not the body is consulted at all."""
        with subtests.test("tiles"):
            assert default_tiles(bodies.MARS) == paths.DATA / "work/mars/planet_tiles/tiles"
        with subtests.test("out"):
            assert default_out(bodies.MARS) == paths.DATA / "work/mars/planet_tiles/planet.mbtiles"

    def test_the_defaults_follow_a_relocated_store(self, monkeypatch, tmp_path):
        """The seam this closes, asserted rather than assumed. Read at CALL time, not bound at
        import, which is what lets a test move the store at all — the module constants these
        replaced could only ever name the checkout they were imported from."""
        monkeypatch.setattr(paths, "DATA", tmp_path / "elsewhere")
        assert default_tiles(bodies.EARTH) == tmp_path / "elsewhere/work/planet_tiles/tiles"
        assert default_out(bodies.MARS) == tmp_path / "elsewhere/work/mars/planet_tiles/planet.mbtiles"

    def test_the_body_is_required_with_no_default(self, monkeypatch):
        """No fallback to Earth. Packing the wrong planet's directory is not a loud failure: it
        finds tiles, packs them, and writes a complete archive under the other body's name."""
        monkeypatch.setattr(sys, "argv", ["pack_pmtiles"])
        with pytest.raises(SystemExit):
            pack_pmtiles.main()

    def test_an_unknown_body_raises_through_the_registry(self, monkeypatch):
        """The registry owns the error, so the message names the bodies that do exist."""
        monkeypatch.setattr(sys, "argv", ["pack_pmtiles", "--body", "Mars"])  # a real body, miscased
        with pytest.raises(KeyError, match="unknown body"):
            pack_pmtiles.main()

    def test_the_body_selects_the_paths_main_actually_packs(self, monkeypatch):
        """The helpers above could both be right while `main` still called neither."""
        packed: list[tuple] = []
        monkeypatch.setattr(pack_pmtiles, "pack_directory",
                            lambda tiles, out, name: packed.append((tiles, out, name)))
        monkeypatch.setattr(sys, "argv", ["pack_pmtiles", "--body", "mars"])
        pack_pmtiles.main()
        assert packed[0][0] == default_tiles(bodies.MARS)
        assert packed[0][1] == default_out(bodies.MARS)

    def test_an_explicit_path_still_wins(self, monkeypatch, tmp_path):
        """`--tiles`/`--out` are how the terrain pyramid is packed from a sibling directory, so the
        body chooses the DEFAULT and never overrides what an operator said."""
        packed: list[tuple] = []
        monkeypatch.setattr(pack_pmtiles, "pack_directory",
                            lambda tiles, out, name: packed.append((tiles, out, name)))
        monkeypatch.setattr(sys, "argv", ["pack_pmtiles", "--body", "earth",
                                          "--tiles", str(tmp_path / "bathy/tiles"),
                                          "--out", str(tmp_path / "terrain.mbtiles")])
        pack_pmtiles.main()
        assert packed[0][0] == tmp_path / "bathy/tiles"
        assert packed[0][1] == tmp_path / "terrain.mbtiles"


class TestTheArchiveNameIsNotTheBodys:
    """`--name` must NOT become body-derived, and this is where that decision is kept.

    It reads `{site}-{layer}` already — the terrain pyramid packs as `terrella-terrain` from the
    same code — so the body is carried by the PATH, exactly as every recipe sidecar carries it.
    Deriving it here would be actively expensive: the name lands in the MBTiles metadata,
    `pmtiles convert` copies it into the archive header, and the header is inside the SHA-256 that
    becomes the tile token in the URL. A cosmetic tidy would therefore change every tile URL the
    site serves and orphan every warm browser cache.
    """

    def _default_name_for(self, monkeypatch, body: str) -> str:
        packed: list[tuple] = []
        monkeypatch.setattr(pack_pmtiles, "pack_directory",
                            lambda tiles, out, name: packed.append((tiles, out, name)))
        monkeypatch.setattr(sys, "argv", ["pack_pmtiles", "--body", body])
        pack_pmtiles.main()
        return packed[0][2]

    def test_the_default_name_does_not_vary_with_the_body(self, monkeypatch):
        assert self._default_name_for(monkeypatch, "earth") == \
               self._default_name_for(monkeypatch, "mars")

    def test_the_default_name_is_the_one_the_shipped_archive_carries(self, monkeypatch):
        """Pinned to the literal, because "unchanged across bodies" is also satisfied by changing
        it for both — and that ships the same broken URLs."""
        assert self._default_name_for(monkeypatch, "earth") == "terrella-relief"


def make_pyramid(root, tiles, suffix=".png"):
    """Write fake tiles {(z, x, y): payload} in the z/x/y.<suffix> layout."""
    for (zoom, col, row), payload in tiles.items():
        tile_path = root / str(zoom) / str(col) / f"{row}{suffix}"
        tile_path.parent.mkdir(parents=True, exist_ok=True)
        tile_path.write_bytes(payload)


class TestPackDirectory:
    TILES: ClassVar[dict[tuple[int, int, int], bytes]] = {
        (0, 0, 0): b"z0-root", (1, 0, 0): b"z1-nw", (1, 1, 1): b"z1-se"}

    def test_blobs_land_flipped_and_byte_identical(self, tmp_path):
        make_pyramid(tmp_path / "tiles", self.TILES)
        out = tmp_path / "planet.mbtiles"
        count = pack_directory(tmp_path / "tiles", out, name="test")
        assert count == 3
        with sqlite3.connect(out) as db:
            rows = dict(((z, x, y), bytes(blob)) for z, x, y, blob in db.execute(
                "SELECT zoom_level, tile_column, tile_row, tile_data FROM tiles"))
        assert rows[(0, 0, 0)] == b"z0-root"
        assert rows[(1, 0, 1)] == b"z1-nw"       # XYZ y=0 -> TMS row 1
        assert rows[(1, 1, 0)] == b"z1-se"       # XYZ y=1 -> TMS row 0
        assert len(rows) == 3

    def test_metadata_carries_the_contract(self, subtests, tmp_path):
        """Subtests over one pack: the setup builds a pyramid and writes sqlite, so re-running it
        per field would be wasteful, and a regression in `pack_directory` corrupts several fields
        at once. This reports every broken key from a single build."""
        make_pyramid(tmp_path / "tiles", self.TILES)
        out = tmp_path / "planet.mbtiles"
        pack_directory(tmp_path / "tiles", out, name="test")
        with sqlite3.connect(out) as db:
            metadata = dict(db.execute("SELECT name, value FROM metadata"))
        with subtests.test("format"):
            assert metadata["format"] == "png"
        with subtests.test("name"):
            assert metadata["name"] == "test"
        with subtests.test("minzoom"):
            assert metadata["minzoom"] == "0"
        with subtests.test("maxzoom is derived from what is actually present"):
            assert metadata["maxzoom"] == "1"
        with subtests.test("bounds reach the post-Antarctica pyramid floor"):
            assert "-85.05" in metadata["bounds"]

    def test_final_name_means_complete(self, tmp_path):
        """Interrupted packs must not leave a plausible .mbtiles behind (the .tmp +
        replace convention every pipeline writer follows)."""
        make_pyramid(tmp_path / "tiles", self.TILES)
        out = tmp_path / "planet.mbtiles"
        pack_directory(tmp_path / "tiles", out, name="test")
        assert not out.with_name(out.name + ".tmp").exists()

    def test_missing_directory_fails_loudly(self, tmp_path):
        with pytest.raises(SystemExit):
            pack_directory(tmp_path / "absent", tmp_path / "out.mbtiles", name="test")

    def test_unique_index_exists(self, tmp_path):
        """The MBTiles spec's tile_index — pmtiles convert relies on unique z/x/y."""
        make_pyramid(tmp_path / "tiles", self.TILES)
        out = tmp_path / "planet.mbtiles"
        pack_directory(tmp_path / "tiles", out, name="test")
        with sqlite3.connect(out) as db:
            indexes = [row[0] for row in db.execute(
                "SELECT name FROM sqlite_master WHERE type='index'")]
        assert any("tile" in name for name in indexes)


class TestEncodingIsReadOffTheDirectory:
    """The declared `format` must be derived from the files packed, never assumed.

    The glob (`*.png`) and the metadata (`"png"`) used to be two independent spellings
    of one fact. A reader trusts that metadata to pick a decoder, so a pyramid cut as WebP under a
    `"png"` label is not a cosmetic error — it is an archive nothing can display.
    """
    TILES: ClassVar[dict[tuple[int, int, int], bytes]] = {
        (0, 0, 0): b"z0-root", (1, 0, 0): b"z1-nw", (1, 1, 1): b"z1-se"}

    def _format_of(self, tmp_path):
        out = tmp_path / "planet.mbtiles"
        pack_directory(tmp_path / "tiles", out, name="test")
        with sqlite3.connect(out) as db:
            return dict(db.execute("SELECT name, value FROM metadata"))["format"]

    def test_webp_pyramid_declares_webp(self, tmp_path):
        make_pyramid(tmp_path / "tiles", self.TILES, suffix=".webp")
        assert self._format_of(tmp_path) == "webp"

    def test_png_pyramid_still_declares_png(self, tmp_path):
        """The control: detection must not have simply moved the hardcoding to a new value."""
        make_pyramid(tmp_path / "tiles", self.TILES, suffix=".png")
        assert self._format_of(tmp_path) == "png"

    def test_webp_blobs_are_still_moved_untouched(self, tmp_path):
        """Detection changes the label, not the bytes — the archive must stay byte-identical."""
        make_pyramid(tmp_path / "tiles", self.TILES, suffix=".webp")
        out = tmp_path / "planet.mbtiles"
        pack_directory(tmp_path / "tiles", out, name="test")
        with sqlite3.connect(out) as db:
            blob = db.execute("SELECT tile_data FROM tiles WHERE zoom_level=0").fetchone()[0]
        assert bytes(blob) == b"z0-root"

    def test_mixed_encodings_fail_loudly(self, tmp_path):
        """One PMTiles archive declares ONE tile type, so a half-swapped pyramid must not pack."""
        make_pyramid(tmp_path / "tiles", self.TILES, suffix=".png")
        make_pyramid(tmp_path / "tiles", {(2, 0, 0): b"stray"}, suffix=".webp")
        with pytest.raises(SystemExit, match="mixes tile encodings"):
            pack_directory(tmp_path / "tiles", tmp_path / "out.mbtiles", name="test")

    def test_non_tile_files_are_not_packed(self, tmp_path):
        """`.aux.xml` sidecars and viewer leftovers share the leaf dirs; only image suffixes count."""
        make_pyramid(tmp_path / "tiles", self.TILES, suffix=".png")
        (tmp_path / "tiles" / "0" / "0" / "0.png.aux.xml").write_text("<PAMDataset/>")
        out = tmp_path / "planet.mbtiles"
        assert pack_directory(tmp_path / "tiles", out, name="test") == 3

    def test_a_directory_holding_no_tiles_fails_loudly(self, tmp_path):
        """Present but empty of images — with a suffix filter this would otherwise pack silently."""
        (tmp_path / "tiles" / "0" / "0").mkdir(parents=True)
        (tmp_path / "tiles" / "0" / "0" / "0.png.aux.xml").write_text("<PAMDataset/>")
        with pytest.raises(SystemExit, match="holds no tiles"):
            pack_directory(tmp_path / "tiles", tmp_path / "out.mbtiles", name="test")
