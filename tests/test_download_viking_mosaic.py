"""The Viking mosaic acquisition recipe, checked without the network and without the 761 MiB file.

WHAT IS ACTUALLY TESTABLE HERE. The mosaic must not be fetched to run a test, so the pins cannot be
compared against the real raster. Two things can still be checked honestly:

  - the pins against EACH OTHER, through facts about the product — it is uncompressed 8-bit RGB
    striped one row per band-row, and its pixel size is the publisher's declared 64.05264 px/degree
    on Mars's own sphere. Those are independent oracles rather than restatements: a transposed digit
    in any single constant breaks the arithmetic with the others;
  - the CHECKING LOGIC against synthetic rasters and a fake host, which is what will actually run,
    and which must reject the NEAR-misses rather than only the absurd ones.

The near-miss that matters most here is the ellipsoid. This product's two detached PDS labels
declare a polar radius of 3376200 while the GeoTIFF declares an unflattened sphere, so an edition
published on the labels' figure is a plausible future rather than an invented one — and it would
shift latitudes through the EPSG:4326 relabel without erroring anywhere.
"""

import hashlib
import math
import urllib.request
from typing import Any

import numpy as np
import pytest
import rasterio
from rasterio.crs import CRS
from rasterio.transform import from_origin

from pipeline import bodies, paths
from pipeline.acquire import download_viking_mosaic as viking

#: The published CRS: SimpleCylindrical metres on the unflattened Mars sphere.
MARS_SPHERE_CRS = CRS.from_proj4("+proj=eqc +R=3396190 +units=m +no_defs")
#: The labels' own figure, and the reason `assert_grid` checks the semi-MINOR axis at all. A
#: triaxial Mars is what `PolarRadius = 3376200` describes, and it is 0.6% off in latitude.
MARS_ELLIPSOID_CRS = CRS.from_proj4("+proj=eqc +a=3396190 +b=3376200 +units=m +no_defs")
#: The 3,389,500 m spherical MEAN — the other number published for "the radius of Mars", 0.2% out.
MARS_MEAN_SPHERE_CRS = CRS.from_proj4("+proj=eqc +R=3389500 +units=m +no_defs")


def _write_mosaic(path, *, width=8, height=4, count=3, dtype="uint8", nodata=0.0,
                  crs=MARS_SPHERE_CRS, pixel_metres=viking.EXPECTED_PIXEL_METRES):
    """A synthetic stand-in carrying the real contract at a writable size.

    The transform is built FROM the pixel size rather than from bounds, because the pixel size is
    one of the pinned fields and a bounds-derived transform would silently satisfy it at any width.
    """
    profile: dict[str, Any] = dict(driver="GTiff", width=width, height=height, count=count,
                                   dtype=dtype, nodata=nodata, crs=crs,
                                   transform=from_origin(-10669931.18, 5334965.59,
                                                         pixel_metres, pixel_metres))
    with rasterio.open(path, "w", **profile) as dataset:
        for band in range(1, count + 1):
            dataset.write(np.zeros((height, width), dtype=dtype), band)
    return path


@pytest.fixture
def tiny(tmp_path, monkeypatch):
    """Shrink the grid contract to something writable, leaving every other pin real."""
    monkeypatch.setattr(viking, "EXPECTED_WIDTH", 8)
    monkeypatch.setattr(viking, "EXPECTED_HEIGHT", 4)
    return tmp_path / "mosaic.tif"


class TestThePinsAgreeWithEachOther:
    def test_the_grid_and_the_byte_count_describe_one_uncompressed_striped_rgb_raster(self):
        """The relational pin that needs no file: the mosaic is uncompressed and striped one row per
        band-row, so its byte count accounts for itself down to the header.

        Pixels are width x height x bands at one byte each. The remainder is the per-strip directory
        that layout costs — 4 bytes of classic-TIFF offset plus 4 of byte count, per strip, with one
        strip per row per band — leaving only a small header. That is what makes four separately
        typed constants un-driftable: a transposed digit in the width, the height, the band count or
        the byte count breaks the arithmetic, and none of them could catch it alone.
        """
        pixels = viking.EXPECTED_WIDTH * viking.EXPECTED_HEIGHT * viking.EXPECTED_BANDS
        strip_directory = viking.EXPECTED_HEIGHT * viking.EXPECTED_BANDS * 8
        header = viking.EXPECTED_BYTES - pixels - strip_directory
        assert 0 < header < 65536, (
            f"pixels {pixels:,} + strip directory {strip_directory:,} leaves {header:,} bytes "
            f"against a pinned {viking.EXPECTED_BYTES:,} — that is not a TIFF header, so one of the "
            f"pins is wrong or the mosaic is no longer uncompressed one-row-per-strip 8-bit RGB"
        )

    def test_the_pixel_size_is_the_publishers_scale_on_mars_own_sphere(self):
        """Ties the pinned pixel size to the registry's radius through the publisher's own declared
        `Scale`, which is 64.05264 pixels/degree in both detached labels.

        An INDEPENDENT oracle rather than a restatement: `EXPECTED_PIXEL_METRES` was read off the
        GeoTIFF's transform and this number was read off the labels, so agreeing to five decimals
        means the metre figure, the label and `bodies.MARS.ground_radius_m` all describe one grid.
        """
        metres_per_degree = 2.0 * math.pi * bodies.MARS.ground_radius_m / 360.0
        pixels_per_degree = metres_per_degree / viking.EXPECTED_PIXEL_METRES
        assert pixels_per_degree == pytest.approx(64.05264, abs=1e-5)

    def test_the_width_spans_the_full_range_of_longitude_at_that_pixel_size(self):
        """The width pin and the pixel size pin must describe one whole planet. A raster that failed
        this would be a crop or a resample wearing the global product's name."""
        implied = 2.0 * math.pi * bodies.MARS.ground_radius_m / viking.EXPECTED_PIXEL_METRES
        assert viking.EXPECTED_WIDTH == pytest.approx(implied, abs=1)

    def test_the_rows_span_the_full_range_of_latitude(self):
        """Half the columns, to within the half-row a pole-to-pole grid falls short by. A width and
        height pair failing this would have non-square pixels, which the scale check cannot survive.
        """
        assert viking.EXPECTED_HEIGHT == pytest.approx(viking.EXPECTED_WIDTH / 2, abs=1)


class _FakeResponse:
    def __init__(self, headers=None, body=b""):
        self.headers = headers or {}
        self._body = body

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _serve(monkeypatch, *, size, modified, digest, sidecar_name=viking.MOSAIC_NAME):
    """Fake the host, dispatching on URL so the HEAD and the checksum GET can disagree."""
    def fake_urlopen(request, *args, **kwargs):
        if request.full_url.endswith(".md5"):
            return _FakeResponse(body=f"{digest}  {sidecar_name}\n".encode("ascii"))
        return _FakeResponse(headers={"Content-Length": str(size), "Last-Modified": modified})

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)


class TestThePreflightRefusesADriftedEdition:
    """USGS republishes mosaics IN PLACE under the same filename, so same-name is not same-bytes and
    the preflight is the only check that runs before ~761 MiB is committed to."""

    def test_the_pinned_edition_passes(self, monkeypatch):
        _serve(monkeypatch, size=viking.EXPECTED_BYTES,
               modified=viking.EXPECTED_LAST_MODIFIED, digest=viking.EXPECTED_MD5)
        viking.preflight()  # must not raise

    def test_a_changed_size_aborts(self, monkeypatch):
        _serve(monkeypatch, size=viking.EXPECTED_BYTES + 2,
               modified=viking.EXPECTED_LAST_MODIFIED, digest=viking.EXPECTED_MD5)
        with pytest.raises(SystemExit) as caught:
            viking.preflight()
        assert "republished" in str(caught.value)

    def test_a_re_upload_of_the_same_bytes_still_aborts(self, monkeypatch):
        _serve(monkeypatch, size=viking.EXPECTED_BYTES,
               modified="Thu, 01 Jan 2026 00:00:00 GMT", digest=viking.EXPECTED_MD5)
        with pytest.raises(SystemExit) as caught:
            viking.preflight()
        assert "Last-Modified" in str(caught.value)

    def test_a_rerender_that_keeps_the_size_and_the_date_is_still_caught(self, monkeypatch):
        """THE CASE A SIZE-AND-DATE PIN CANNOT SEE, and the whole reason this product's acquirer is
        keyed on a digest where the Mars DEM's is not. A re-render that preserves the byte count is
        exactly what an uncompressed fixed-grid raster produces — every edition of this mosaic is
        797,888,177 bytes whatever the pixels say — so size is nearly uninformative here."""
        _serve(monkeypatch, size=viking.EXPECTED_BYTES,
               modified=viking.EXPECTED_LAST_MODIFIED, digest="0" * 32)
        with pytest.raises(SystemExit) as caught:
            viking.preflight()
        assert "md5" in str(caught.value)

    def test_a_checksum_sidecar_describing_another_product_aborts_saying_so(self, monkeypatch):
        """A rotted URL must not read as a republished mosaic. The sidecar names its own subject, so
        the name is checked before the digest is believed."""
        _serve(monkeypatch, size=viking.EXPECTED_BYTES, modified=viking.EXPECTED_LAST_MODIFIED,
               digest=viking.EXPECTED_MD5, sidecar_name="Mars_Viking_MDIM21_ClrMosaic_global_232m.tif")
        with pytest.raises(SystemExit) as caught:
            viking.preflight()
        assert "does not describe this product" in str(caught.value)


class TestTheGridContractIsCheckedOnTheRasterItself:
    def test_the_published_grid_passes(self, tiny):
        viking.assert_grid(_write_mosaic(tiny))  # must not raise

    @pytest.mark.parametrize("field,kwargs", [
        ("width", {"width": 9}),
        ("height", {"height": 5}),
        ("band count", {"count": 1}),
        ("dtype", {"dtype": "uint16"}),
        ("nodata", {"nodata": 255.0}),
    ])
    def test_each_part_of_the_contract_is_actually_checked(self, tiny, field, kwargs):
        """One case per field, because a check covering four of five reads as covering all of them —
        and the missing one is discovered as a wrong-looking pole."""
        with pytest.raises(SystemExit) as caught:
            viking.assert_grid(_write_mosaic(tiny, **kwargs))
        assert field in str(caught.value)

    def test_a_resampled_edition_is_refused(self, tiny):
        """The pixel size is pinned separately from the width because a crop and a resample move
        different constants, and only one of them changes the filter the ice is graded through."""
        with pytest.raises(SystemExit) as caught:
            viking.assert_grid(_write_mosaic(tiny, pixel_metres=463.0))
        assert "m/px" in str(caught.value)

    def test_an_ellipsoidal_edition_is_refused_and_the_message_names_the_labels(self, tiny):
        """THE CHECK THIS FUNCTION EXISTS FOR, and the one a reader of the PDS labels would remove.
        Both detached labels declare a polar radius of 3376200; the GeoTIFF declares a sphere. An
        edition published on the labels' figure would relabel to EPSG:4326, warp and render without
        a word, shifting latitudes by up to 0.6% of the radius on the way."""
        with pytest.raises(SystemExit) as caught:
            viking.assert_grid(_write_mosaic(tiny, crs=MARS_ELLIPSOID_CRS))
        message = str(caught.value)
        assert "ELLIPSOID" in message
        assert "3376200" in message.replace(".0", "")

    def test_a_source_on_the_mean_sphere_is_refused_though_it_is_only_0_2_percent_out(self, tiny):
        """`bodies.MARS.ground_radius_m` is what every Martian ground metre divides by; the mean
        sphere is the other published radius for Mars and would pass every other check here."""
        with pytest.raises(SystemExit) as caught:
            viking.assert_grid(_write_mosaic(tiny, crs=MARS_MEAN_SPHERE_CRS))
        message = str(caught.value)
        assert "3389500" in message.replace(".0", "")
        assert str(int(bodies.MARS.ground_radius_m)) in message.replace(".0", "")

    def test_a_geographic_source_is_refused_because_consumers_warp_out_of_metres(self, tiny):
        """The mirror of the Mars DEM's check, and it points the other way: that product is degrees
        and this one is metres, so the same mistake has opposite signs on the two Mars rasters."""
        geographic = CRS.from_proj4("+proj=longlat +R=3396190 +no_defs")
        with pytest.raises(SystemExit) as caught:
            viking.assert_grid(_write_mosaic(tiny, crs=geographic))
        assert "PROJECTED" in str(caught.value)


class TestTheDigestIsCheckedAgainstTheBytesOnDisk:
    def test_a_matching_file_passes_and_returns_its_digest(self, tmp_path, monkeypatch):
        path = tmp_path / "mosaic.tif"
        path.write_bytes(b"the published bytes")
        digest = hashlib.md5(path.read_bytes()).hexdigest()
        monkeypatch.setattr(viking, "EXPECTED_MD5", digest)
        assert viking.assert_digest(path) == digest

    def test_a_truncated_file_aborts_and_says_not_to_re_pin(self, tmp_path, monkeypatch):
        """A half-written file cannot reach its final name through `download_one`, but it can arrive
        any number of other ways — a copy, a restore, an interrupted `cp`. The message steers to
        deletion rather than re-pinning because re-pinning is what makes it permanent."""
        path = tmp_path / "mosaic.tif"
        path.write_bytes(b"the published byte")
        monkeypatch.setattr(viking, "EXPECTED_MD5",
                            hashlib.md5(b"the published bytes").hexdigest())
        with pytest.raises(SystemExit) as caught:
            viking.assert_digest(path)
        assert "re-run rather than re-pinning" in str(caught.value)


class TestTheRecipeDownloadsNothingByAccident:
    def test_check_stops_after_the_preflight(self, monkeypatch):
        """`--check` is what makes this module runnable before the download is authorised at all."""
        calls: list[str] = []
        monkeypatch.setattr(viking, "preflight", lambda *a, **k: calls.append("preflight"))
        monkeypatch.setattr(viking, "download_one",
                            lambda *a, **k: calls.append("download") or "ok")
        monkeypatch.setattr("sys.argv", ["download_viking_mosaic", "--check"])
        assert viking.main() == 0
        assert calls == ["preflight"], f"--check reached {calls}"

    def test_the_mosaic_path_follows_a_relocated_data_store(self, tmp_path, monkeypatch):
        """Resolved at call time, not frozen at import: `MAPS_DATA` moves the whole data store, and
        a module-level join would leave 761 MiB landing back inside the checkout."""
        monkeypatch.setattr(paths, "DATA", tmp_path / "elsewhere")
        monkeypatch.setattr(viking, "DATA_DIR", paths.DATA / "raw/mars")
        assert viking.mosaic_path().parent.is_relative_to(tmp_path)

    def test_the_atomic_download_is_imported_rather_than_restated(self):
        """One home for "stream to .part, size-check, atomically rename". Restating it is how a
        half-written file acquires a final name on one code path and not the other."""
        from pipeline import fetch
        assert viking.download_one is fetch.download_one

    def test_the_product_taken_is_the_925_metre_colour_mosaic_and_not_a_finer_one(self):
        """An anti-redo guard with teeth. The two MDIM 2.1 products sit in the same directory, are
        five times finer, and are both high-pass filtered to remove the regional albedo this module
        exists to supply — so 'upgrading' the URL is a plausible future edit that no other test here
        would notice."""
        assert viking.MOSAIC_NAME == "Mars_Viking_ClrMosaic_global_925m.tif"
        assert "MDIM21" not in viking.MOSAIC_URL
        assert viking.MOSAIC_URL.endswith(f"/{viking.MOSAIC_NAME}")
