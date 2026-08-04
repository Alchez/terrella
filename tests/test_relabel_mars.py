"""Mars's planet producer: one CRS relabel, and the claim that it moves nothing.

THE CLAIM UNDER TEST IS "IDENTITY ON THE ANGLES". The blend is lon/lat degrees on an unflattened
sphere of 3,396,190 m and we declare that grid to be EPSG:4326 — every pixel keeps the longitude and
latitude it already had, and only the label naming which body those angles belong to changes. That
is cheap to assert and expensive to get wrong: a relabel that resampled, shifted the geotransform or
reinterpreted the axes would produce a Mars that projects perfectly and sits on the wrong parallels,
which no later stage could detect.

DRIVEN AGAINST A SYNTHETIC MARS-SPHERE RASTER, deliberately, because the real blend is 10.6 GiB and
is not on this box. A stand-in cannot prove anything about the published file's CONTENT — that is
`download_mars_dem.assert_grid`'s job, and the test at the bottom holds `main` to calling it — but
the relabel is a metadata operation, so a 4x2 raster exercises exactly the same code path GDAL runs
on the full mosaic.
"""

import subprocess
from typing import Any

import numpy as np
import pytest
import rasterio
from rasterio.crs import CRS
from rasterio.transform import from_bounds

from pipeline import bodies, paths, planet_seam
from pipeline.acquire import download_mars_dem
from pipeline.fuse import relabel_mars

#: The source's own CRS: degrees on Mars's IAU 2015 sphere, unflattened. PROJ serialises an
#: unflattened body as `+R=`, which is why `assert_grid` reads the ellipsoid rather than `a`.
MARS_SPHERE = f"+proj=longlat +R={bodies.MARS.ground_radius_m} +no_defs"

WIDTH, HEIGHT = 4, 2


@pytest.fixture
def blend(tmp_path, monkeypatch):
    """A tiny stand-in for the published mosaic, on Mars's own sphere, with distinct pixel values."""
    monkeypatch.setattr(paths, "DATA", tmp_path)
    source = tmp_path / "blend.tif"
    profile: dict[str, Any] = dict(driver="GTiff", width=WIDTH, height=HEIGHT, count=1, dtype="int16",
                   crs=CRS.from_proj4(MARS_SPHERE), nodata=-32768,
                   transform=from_bounds(-180.0, -90.0, 180.0, 90.0, WIDTH, HEIGHT))  # pyright: ignore[reportCallIssue] — rasterio untyped
    with rasterio.open(source, "w", **profile) as dataset:  # pyright: ignore[reportCallIssue] — rasterio untyped
        dataset.write(np.arange(WIDTH * HEIGHT, dtype="int16").reshape(HEIGHT, WIDTH), 1)
    return source


class TestTheRelabelIsAnIdentity:
    def test_the_output_is_declared_epsg_4326(self, blend):
        vrt = relabel_mars.relabel(blend)
        with rasterio.open(vrt) as dataset:
            assert dataset.crs.to_epsg() == 4326

    def test_the_source_is_left_on_its_own_sphere(self, blend):
        """A relabel that edited the source in place would make the operation unrepeatable and
        destroy the one artifact `assert_grid` checks against."""
        relabel_mars.relabel(blend)
        with rasterio.open(blend) as dataset:
            assert dataset.crs.to_dict()["R"] == pytest.approx(bodies.MARS.ground_radius_m)

    def test_not_one_angle_moves(self, blend):
        """THE claim. Same geotransform, same size — so the longitude and latitude of every pixel
        centre are the numbers they already were, and only the body label changed."""
        with rasterio.open(blend) as source:
            before = (source.transform, source.width, source.height)
        with rasterio.open(relabel_mars.relabel(blend)) as after:
            assert (after.transform, after.width, after.height) == before

    def test_not_one_pixel_moves(self, blend):
        """Nothing is resampled, so the values come back bit-identical rather than merely close."""
        with rasterio.open(blend) as source:
            expected = source.read(1)
        with rasterio.open(relabel_mars.relabel(blend)) as after:
            assert np.array_equal(after.read(1), expected)
            assert after.dtypes[0] == "int16"

    def test_the_nodata_sentinel_survives(self, blend):
        """Pinned because it is the one metadata difference from Earth's fused heightfield, and the
        first z6 render is where it would show up as unexplained deep blue."""
        with rasterio.open(relabel_mars.relabel(blend)) as after:
            assert after.nodata == -32768

    def test_no_copy_of_the_raster_is_made(self, blend):
        """A VRT REFERENCES the mosaic rather than containing it — which matters because the
        published file is 10.6 GiB and uncompressed. Asserted by finding the source path inside the
        index, not by comparing sizes: the XML is fixed overhead and outweighs a 4x2 raster."""
        vrt = relabel_mars.relabel(blend)
        assert vrt.suffix == ".vrt"
        assert blend.name in vrt.read_text()
        assert "<SourceFilename" in vrt.read_text()


class TestWhatMarsDeclares:
    def test_it_declares_a_heightfield_and_nothing_else(self, blend, monkeypatch):
        """No ocean mask, no water mask — not empty ones, none at all. A raster of zeros could not
        be told apart from one produced by measuring Mars's oceans and finding none."""
        monkeypatch.setattr(download_mars_dem, "blend_path", lambda: blend)
        monkeypatch.setattr(download_mars_dem, "assert_grid", lambda path: None)
        assert relabel_mars.main() == 0
        assert planet_seam.declared(bodies.MARS) == frozenset({"heightfield"})

    def test_the_declaration_is_written_after_the_raster_it_names(self, blend, monkeypatch):
        monkeypatch.setattr(download_mars_dem, "blend_path", lambda: blend)
        monkeypatch.setattr(download_mars_dem, "assert_grid", lambda path: None)
        relabel_mars.main()
        assert (planet_seam.vrt_path(bodies.MARS, "heightfield").stat().st_mtime
                <= planet_seam.declaration_path(bodies.MARS).stat().st_mtime)

    def test_a_second_run_replaces_nothing(self, blend, monkeypatch):
        """The VRT's mtime gates a 3857 warp, so re-running the producer must not restage Mars."""
        monkeypatch.setattr(download_mars_dem, "blend_path", lambda: blend)
        monkeypatch.setattr(download_mars_dem, "assert_grid", lambda path: None)
        relabel_mars.main()
        vrt = planet_seam.vrt_path(bodies.MARS, "heightfield")
        import os
        os.utime(vrt, (0, 0))
        relabel_mars.main()
        assert vrt.stat().st_mtime == 0


class TestTheGridIsCheckedBeforeAnythingIsWritten:
    def test_a_missing_blend_stops_before_the_relabel(self, tmp_path, monkeypatch):
        monkeypatch.setattr(paths, "DATA", tmp_path)
        monkeypatch.setattr(download_mars_dem, "blend_path", lambda: tmp_path / "never-downloaded")
        with pytest.raises(SystemExit, match="download_mars_dem"):
            relabel_mars.main()
        assert not planet_seam.declaration_path(bodies.MARS).exists()

    def test_the_published_grid_is_verified_before_the_vrt_is_written(self, blend, monkeypatch):
        """THE ORDER IS THE POINT. The relabel is only honest while the source really is a sphere in
        degrees; on an ellipsoid the identical declaration silently shifts every latitude. So the
        check that sees that must run BEFORE anything is written, not after."""
        order: list[str] = []
        monkeypatch.setattr(download_mars_dem, "blend_path", lambda: blend)
        monkeypatch.setattr(download_mars_dem, "assert_grid",
                            lambda path: order.append("assert_grid"))
        monkeypatch.setattr(relabel_mars, "relabel",
                            lambda source: (order.append("relabel"),
                                            planet_seam.vrt_path(bodies.MARS, "heightfield"))[1])
        with pytest.raises(FileNotFoundError):  # the stubbed relabel wrote no VRT to declare
            relabel_mars.main()
        assert order == ["assert_grid", "relabel"]

    def test_a_source_that_is_not_a_sphere_is_refused_by_the_real_check(self, tmp_path):
        """Not a stub: `assert_grid` is driven for real against an ellipsoidal source, because that
        is the precondition the relabel's honesty rests on and the one nothing downstream can see."""
        ellipsoidal = tmp_path / "wgs84.tif"
        profile: dict[str, Any] = dict(driver="GTiff", width=WIDTH, height=HEIGHT, count=1, dtype="int16",
                       crs="EPSG:4326", nodata=-32768,
                       transform=from_bounds(-180.0, -90.0, 180.0, 90.0, WIDTH, HEIGHT))  # pyright: ignore[reportCallIssue] — rasterio untyped
        with rasterio.open(ellipsoidal, "w", **profile) as dataset:  # pyright: ignore[reportCallIssue] — rasterio untyped
            dataset.write(np.zeros((HEIGHT, WIDTH), dtype="int16"), 1)
        with pytest.raises(SystemExit):
            download_mars_dem.assert_grid(ellipsoidal)


def test_gdal_translate_is_available():
    """The producer shells out, so a missing tool must fail here rather than as a confusing
    `check=True` traceback mid-run."""
    assert subprocess.run(["gdal_translate", "--version"],
                          capture_output=True, check=False).returncode == 0
