"""pack_pmtiles: the XYZ tile directory -> MBTiles bridge (blobs moved, never re-encoded).

`pmtiles convert` reads only MBTiles
dir -> MBTiles -> convert), and the one real trap is the row flip: MBTiles stores
TMS rows (origin bottom-left) while our pyramid is XYZ (origin top-left,
`gdal raster tile --convention=xyz`). A silent flip error would serve a
vertically mirrored planet, so the flip and the byte-fidelity both get pinned.
"""

import sqlite3

import pytest

from pipeline.tile.pack_pmtiles import pack_directory, tms_row


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


def make_pyramid(root, tiles, suffix=".png"):
    """Write fake tiles {(z, x, y): payload} in the z/x/y.<suffix> layout."""
    for (zoom, col, row), payload in tiles.items():
        tile_path = root / str(zoom) / str(col) / f"{row}{suffix}"
        tile_path.parent.mkdir(parents=True, exist_ok=True)
        tile_path.write_bytes(payload)


class TestPackDirectory:
    TILES = {(0, 0, 0): b"z0-root", (1, 0, 0): b"z1-nw", (1, 1, 1): b"z1-se"}

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
    TILES = {(0, 0, 0): b"z0-root", (1, 0, 0): b"z1-nw", (1, 1, 1): b"z1-se"}

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
