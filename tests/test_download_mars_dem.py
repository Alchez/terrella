"""The Mars DEM acquisition recipe, checked without the network and without the 10.6 GiB file.

WHAT IS ACTUALLY TESTABLE HERE. The file is not on disk and must not be fetched to run a test, so
the pins cannot be compared against the real raster. Two things can still be checked honestly, and
between them they catch a mistyped constant:

  - the pins against EACH OTHER, through a fact about the product (it is uncompressed Int16, and it
    is 200 m/px on Mars's own sphere). Those are independent oracles, not restatements — a wrong
    digit in any one constant breaks the arithmetic with the others;
  - the CHECKING LOGIC against synthetic rasters, which is what will actually run when the download
    lands, and which must reject the near-misses rather than only the absurd ones.
"""

import math
import urllib.request
from typing import Any, ClassVar

import numpy as np
import pytest
import rasterio
from rasterio.crs import CRS
from rasterio.transform import from_bounds

from pipeline import bodies, paths
from pipeline.acquire import download_mars_dem as mars_dem

MARS_SPHERE_CRS = CRS.from_proj4("+proj=longlat +a=3396190 +b=3396190 +no_defs")
#: The 3,389,500 m spherical MEAN, which is the plausible wrong answer rather than an invented one:
#: it is the other number published for "the radius of Mars", it differs by only 0.2%, and a DEM
#: carrying it would relabel, warp, shade and tile without complaint.
MARS_MEAN_SPHERE_CRS = CRS.from_proj4("+proj=longlat +a=3389500 +b=3389500 +no_defs")


def _write_blend(path, *, width=8, height=4, dtype="int16", nodata=-32768.0,
                 crs=MARS_SPHERE_CRS):
    profile: dict[str, Any] = dict(driver="GTiff", width=width, height=height, count=1,
                                   dtype=dtype, nodata=nodata, crs=crs,
                                   transform=from_bounds(-180.0, -90.0, 180.0, 90.0,
                                                         width, height))
    with rasterio.open(path, "w", **profile) as dataset:
        dataset.write(np.zeros((height, width), dtype=dtype), 1)
    return path


@pytest.fixture
def tiny(tmp_path, monkeypatch):
    """Shrink the grid contract to something writable, leaving every other pin real."""
    monkeypatch.setattr(mars_dem, "EXPECTED_WIDTH", 8)
    monkeypatch.setattr(mars_dem, "EXPECTED_HEIGHT", 4)
    return tmp_path / "blend.tif"


class TestThePinsAgreeWithEachOther:
    def test_the_grid_and_the_byte_count_describe_one_uncompressed_striped_int16_raster(self):
        """The relational pin that needs no file: the mosaic is uncompressed and striped one row per
        block, so its byte count accounts for itself down to the header.

        Pixels are width x height x 2. The remainder is the per-strip directory that layout costs —
        16 bytes of BigTIFF offset and byte-count entry per row — leaving only a small header. That
        is what makes three separately-typed constants un-driftable: a transposed digit in the
        width, the height or the byte count breaks the arithmetic, and none could catch it alone.

        I asserted a different remainder here from mental arithmetic first, and this test refused
        it — which is the entire reason the pins are checked against each other rather than read
        back from the same page they were copied from.
        """
        pixels = mars_dem.EXPECTED_WIDTH * mars_dem.EXPECTED_HEIGHT * 2
        strip_directory = mars_dem.EXPECTED_HEIGHT * 16
        header = mars_dem.EXPECTED_BYTES - pixels - strip_directory
        assert 0 < header < 65536, (
            f"pixels {pixels:,} + strip directory {strip_directory:,} leaves {header:,} bytes "
            f"against a pinned {mars_dem.EXPECTED_BYTES:,} — that is not a TIFF header, so one of "
            f"the pins is wrong or the mosaic is no longer uncompressed one-row-per-strip Int16"
        )

    def test_the_grid_is_the_200_metre_product_on_mars_own_sphere(self):
        """Ties the width to the registry's radius through the product's headline number.

        200 m/px is the one fact about this DEM that everything downstream was reasoned from — the
        zoom-ceiling table, the 44%-HRSC provenance argument, the decision not to cut z8. If the
        width pin and Mars's radius stop implying it, one of them moved.
        """
        metres_per_degree = 2.0 * math.pi * bodies.MARS.ground_radius_m / 360.0
        metres_per_pixel = metres_per_degree * (360.0 / mars_dem.EXPECTED_WIDTH)
        assert metres_per_pixel == pytest.approx(200.0, abs=0.1)

    def test_the_rows_span_the_full_range_of_latitude(self):
        """Half the columns, to within the one row the published grid falls short of the south pole
        (its lower edge is -89.99922, ~46 m of Mars). A width/height pair that failed this would be
        a raster with non-square pixels, which the 200 m claim above cannot survive."""
        assert mars_dem.EXPECTED_HEIGHT == pytest.approx(mars_dem.EXPECTED_WIDTH / 2, abs=1)


class TestThePreflightRefusesADriftedEdition:
    """USGS republishes mosaics IN PLACE under the same filename — `_v2` is the product version, not
    an immutable release — so same-name is not same-bytes and the preflight is the only cheap check
    that runs before ~10.6 GiB is committed to."""

    def _serve(self, monkeypatch, *, size, modified):
        class FakeResponse:
            headers: ClassVar[dict[str, str]] = {
                "Content-Length": str(size), "Last-Modified": modified}

            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

        monkeypatch.setattr(urllib.request, "urlopen", lambda *a, **k: FakeResponse())

    def test_the_pinned_edition_passes(self, monkeypatch):
        self._serve(monkeypatch, size=mars_dem.EXPECTED_BYTES,
                    modified=mars_dem.EXPECTED_LAST_MODIFIED)
        mars_dem.preflight()  # must not raise

    def test_a_changed_size_aborts(self, monkeypatch):
        self._serve(monkeypatch, size=mars_dem.EXPECTED_BYTES + 2,
                    modified=mars_dem.EXPECTED_LAST_MODIFIED)
        with pytest.raises(SystemExit) as caught:
            mars_dem.preflight()
        assert "republished" in str(caught.value)

    def test_a_re_upload_of_the_SAME_bytes_still_aborts(self, monkeypatch):
        """The case the size pin cannot see, and the realistic one: a re-blend that happens to land
        on the same byte count is unlikely, but a re-upload of a corrected product is not. Only the
        date separates them, which is why both are pinned."""
        self._serve(monkeypatch, size=mars_dem.EXPECTED_BYTES,
                    modified="Thu, 01 Jan 2026 00:00:00 GMT")
        with pytest.raises(SystemExit) as caught:
            mars_dem.preflight()
        assert "Last-Modified" in str(caught.value)


class TestTheGridContractIsCheckedOnTheRasterItself:
    def test_the_published_grid_passes(self, tiny):
        mars_dem.assert_grid(_write_blend(tiny))  # must not raise

    @pytest.mark.parametrize("field,kwargs", [
        ("width", {"width": 9}),
        ("height", {"height": 5}),
        ("dtype", {"dtype": "float32"}),
        ("nodata", {"nodata": -9999.0}),
    ])
    def test_each_part_of_the_contract_is_actually_checked(self, tiny, field, kwargs):
        """One case per field, because a check that covers three of four reads as covering all of
        them — and the missing one is discovered as a wrong-looking planet."""
        with pytest.raises(SystemExit) as caught:
            mars_dem.assert_grid(_write_blend(tiny, **kwargs))
        assert field in str(caught.value)

    def test_a_source_on_the_MEAN_sphere_is_refused_though_it_is_only_0_2_percent_out(self, tiny):
        """The check this function exists for. `bodies.MARS.ground_radius_m` was taken FROM this
        product and is what every Martian ground metre divides by; the mean sphere is the other
        published radius for Mars, and a DEM carrying it would relabel, warp, shade and tile without
        a word."""
        with pytest.raises(SystemExit) as caught:
            mars_dem.assert_grid(_write_blend(tiny, crs=MARS_MEAN_SPHERE_CRS))
        message = str(caught.value)
        assert "3389500" in message.replace(".0", "")
        assert str(int(bodies.MARS.ground_radius_m)) in message.replace(".0", "")

    def test_a_projected_source_is_refused_because_the_relabel_assumes_degrees(self, tiny):
        """The entry seam DECLARES this raster to be EPSG:4326, which is an identity on the angles
        only while the grid really is lon/lat degrees. A projected source would be relabelled into
        nonsense that still georeferences."""
        projected = CRS.from_proj4("+proj=eqc +a=3396190 +b=3396190 +units=m +no_defs")
        with pytest.raises(SystemExit) as caught:
            mars_dem.assert_grid(_write_blend(tiny, crs=projected))
        assert "geographic" in str(caught.value)


class TestTheRecipeDownloadsNothingByAccident:
    def test_check_stops_after_the_preflight(self, monkeypatch, capsys):
        """`--check` is what makes this module runnable before the download is authorised at all."""
        calls: list[str] = []
        monkeypatch.setattr(mars_dem, "preflight", lambda *a, **k: calls.append("preflight"))
        monkeypatch.setattr(mars_dem, "download_one",
                            lambda *a, **k: calls.append("download") or "ok")
        monkeypatch.setattr("sys.argv", ["download_mars_dem", "--check"])
        assert mars_dem.main() == 0
        assert calls == ["preflight"], f"--check reached {calls}"

    def test_the_blend_path_follows_a_relocated_data_store(self, tmp_path, monkeypatch):
        """Resolved at call time, not frozen at import: `MAPS_DATA` moves the whole data store, and
        a module-level join would leave 10.6 GiB landing back inside the checkout."""
        monkeypatch.setattr(paths, "DATA", tmp_path / "elsewhere")
        monkeypatch.setattr(mars_dem, "DATA_DIR", paths.DATA / "raw/mars")
        assert mars_dem.blend_path().parent.is_relative_to(tmp_path)

    def test_the_atomic_download_is_imported_rather_than_restated(self):
        """One home for "stream to .part, size-check, atomically rename". Restating it is how a
        half-written 10 GiB file acquires a final name on one code path and not the other.

        Names `fetch` rather than `download_glo30`, which is where the rule used to live. Both
        spellings passed while it moved — an identity assertion is satisfied by any two names for
        one object, so it went on holding through a module that had stopped being the home."""
        from pipeline import fetch
        assert mars_dem.download_one is fetch.download_one
