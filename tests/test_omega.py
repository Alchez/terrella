"""OMEGA's acquisition and its PDS3 extract — one stage pair over one shared subject, the label.

BOTH MODULES IN ONE FILE BECAUSE THE LABEL IS ONE SUBJECT. `download_omega` proves the label
describes the product the ice was measured on; `extract_omega` derives the grid from that same
label and cross-checks it. Splitting them would put the parser's tests in one file and the
consumer's contradiction-checks in another, which is exactly the arrangement that lets the two
drift.

Everything here is synthetic and reads no production file, so the suite passes under
`MAPS_DATA=<empty dir>` as CI runs it. The real product is verified by `--verify`, which hashes it
against the publisher's own manifest — a check no test can make without shipping 207 MB.
"""

import numpy as np
import pytest

from pipeline import bodies
from pipeline.acquire import download_omega, extract_omega

#: The real label's structure, trimmed to the keys anything reads. Values match the shipped product,
#: so a test that passes here is making a statement about the product rather than about a fixture.
LABEL = """
OBJECT                              = IMAGE
  LINES                             = 7200
  LINE_SAMPLES                      = 14400
  SAMPLE_TYPE                       = LSB_INTEGER
  SAMPLE_BITS                       = 16
  OFFSET                            = 5.2414565669e-01
  SCALING_FACTOR                    = 1.4522365285e-05
  MISSING_CONSTANT                  = -32768
END_OBJECT                          = IMAGE
OBJECT                              = IMAGE_MAP_PROJECTION
  MAP_PROJECTION_TYPE               = "SIMPLE CYLINDRICAL"
  A_AXIS_RADIUS                     = 3396.0 <KM>
  B_AXIS_RADIUS                     = 3396.0 <KM>
  C_AXIS_RADIUS                     = 3396.0 <KM>
  MAP_RESOLUTION                    = 40.0 <PIXEL/DEGREE>
  MAXIMUM_LATITUDE                  = 90.0 <DEGREE>
  MINIMUM_LATITUDE                  = -90.0 <DEGREE>
  WESTERNMOST_LONGITUDE             = -180.0 <DEGREE>
  EASTERNMOST_LONGITUDE             = 180.0 <DEGREE>
  LINE_PROJECTION_OFFSET            = 3600.5
  SAMPLE_PROJECTION_OFFSET          = 7200.5
END_OBJECT                          = IMAGE_MAP_PROJECTION
"""

#: The manifest as PUBLISHED: backslashes and uppercase hex, generated on Windows in 2014.
MANIFEST = (
    "65330649064C2D87B5BA33740A4E8FD6  mexomg_2000\\browse\\albedo\\albedo_r1080_equ_map.lbl\n"
    "3D61D54A2FDA024CB27FB837694BD552  mexomg_2000\\data\\albedo\\albedo_r1080_equ_map.img\n"
    "9CAA0E027FF40587983CBAC123859C3D  mexomg_2000\\data\\albedo\\albedo_r1080_equ_map.lbl\n"
)


class TestTheManifestIsReadInItsOwnDialect:
    def test_backslash_paths_and_uppercase_hex_are_understood(self):
        digests = download_omega.parse_manifest(MANIFEST)
        assert digests["albedo_r1080_equ_map.img"] == download_omega.MD5[
            "albedo_r1080_equ_map.img"]

    def test_a_posix_lowercase_reading_would_find_NOTHING(self):
        """The anti-vacuity, and the reason the parser exists at all. A parser splitting on `/` and
        comparing uppercase hex matches no entry — and finding nothing reads exactly like a product
        the archive does not carry, so the failure would be diagnosed in the wrong place."""
        naive = {line.split()[1].rsplit("/", 1)[-1]: line.split()[0]
                 for line in MANIFEST.splitlines() if line.strip()}
        assert "albedo_r1080_equ_map.img" not in naive
        assert all(key.startswith("mexomg_2000\\") for key in naive)

    def test_a_ragged_line_is_skipped_rather_than_crashing(self):
        assert download_omega.parse_manifest("garbage\n\n" + MANIFEST)[
            "albedo_r1080_equ_map.img"].startswith("3d61")


class TestTheServedManifestIsTheSecondOracle:
    def test_the_published_digests_match_what_is_pinned(self):
        download_omega.assert_manifest(MANIFEST)  # must not exit

    def test_a_republished_product_is_refused(self):
        with pytest.raises(SystemExit) as raised:
            download_omega.assert_manifest(MANIFEST.replace("3D61D54A", "0000DEAD"))
        assert "re-measuring" in str(raised.value)

    def test_a_product_missing_from_the_volume_is_refused(self):
        stripped = "\n".join(line for line in MANIFEST.splitlines()
                             if "data\\albedo\\albedo_r1080_equ_map.img" not in line)
        with pytest.raises(SystemExit) as raised:
            download_omega.assert_manifest(stripped)
        assert "reorganised" in str(raised.value)


class TestTheLabelIsParsedRatherThanAssumed:
    def test_units_and_quotes_are_stripped(self):
        label = download_omega.parse_label(LABEL)
        assert label["A_AXIS_RADIUS"] == "3396.0"
        assert label["MAP_PROJECTION_TYPE"] == "SIMPLE CYLINDRICAL"

    def test_a_duplicate_key_with_a_different_value_raises(self):
        """A flat parse is only safe because the real label has no duplicate data keys. If one
        appeared, one value would silently shadow the other."""
        with pytest.raises(ValueError):
            download_omega.parse_label(LABEL + "\n  MAP_RESOLUTION = 20.0\n")

    def test_the_real_shape_is_accepted(self):
        download_omega.assert_label(LABEL)  # must not exit

    def test_an_ellipsoid_is_refused_because_the_relabel_would_shift_latitudes(self):
        """The load-bearing check. `-a_srs EPSG:4326` is an identity on the angles only for a true
        sphere; on an ellipsoid it moves every latitude and nothing downstream could tell."""
        with pytest.raises(SystemExit) as raised:
            download_omega.assert_label(LABEL.replace("C_AXIS_RADIUS                     = 3396.0",
                                                      "C_AXIS_RADIUS                     = 3376.0"))
        assert "TRUE SPHERE" in str(raised.value)

    def test_a_regridded_product_is_refused(self):
        with pytest.raises(SystemExit):
            download_omega.assert_label(LABEL.replace("MAP_RESOLUTION                    = 40.0",
                                                      "MAP_RESOLUTION                    = 20.0"))

    def test_OMEGAs_sphere_is_NOT_held_to_the_DEMs_radius(self):
        """The guard against copying `download_mars_dem.assert_grid` wholesale.

        That acquirer requires its product's sphere to equal `bodies.MARS.ground_radius_m`, because
        every Martian ground metre divides by that number and it was taken FROM the DEM. OMEGA is
        published on a 3396.0 km sphere — 190 m smaller — and nothing here converts albedo to
        metres, so the equality check would refuse a correct product. Both being spheres, the two
        graticules coincide exactly and the difference costs nothing.
        """
        radius_m = float(download_omega.parse_label(LABEL)["A_AXIS_RADIUS"]) * 1000.0
        assert radius_m != bodies.MARS.ground_radius_m
        assert abs(radius_m - bodies.MARS.ground_radius_m) == pytest.approx(190.0)
        download_omega.assert_label(LABEL)  # and it is accepted anyway


class TestTheAcquirersOwnWiring:
    def test_every_pinned_product_is_one_the_module_fetches(self):
        assert set(download_omega.MD5) == set(download_omega.PRODUCTS)

    def test_the_urls_name_the_host_the_data_cannot(self):
        """A PDS product records nothing about where it came from, which is the gap this closes."""
        for url in (download_omega.manifest_url(),
                    download_omega.product_url("albedo_r1080_equ_map.img")):
            assert url.startswith(download_omega.HOST)
            assert download_omega.VOLUME in url

    def test_the_recipe_records_the_host_volume_and_digests(self):
        recipe = download_omega.build_recipe()
        for needle in (download_omega.HOST, download_omega.VOLUME, download_omega.MANIFEST,
                       download_omega.MD5["albedo_r1080_equ_map.img"]):
            assert needle in recipe


class TestTheGridIsDerivedTwiceAndMustAgree:
    def test_the_real_label_derives_the_shipped_grid(self):
        grid = extract_omega.grid_from_label(download_omega.parse_label(LABEL))
        assert grid["resolution"] == 40.0
        assert 1.0 / grid["resolution"] == 0.025
        assert (grid["west"], grid["north"]) == (-180.0, 90.0)

    def test_a_bounding_box_disagreeing_with_the_projection_offsets_is_refused(self):
        """The half-pixel trap, which is invisible in the image and wrong at every sample. Either
        derivation alone would accept this; only the comparison sees it."""
        with pytest.raises(SystemExit) as raised:
            extract_omega.grid_from_label(download_omega.parse_label(
                LABEL.replace("LINE_PROJECTION_OFFSET            = 3600.5",
                              "LINE_PROJECTION_OFFSET            = 3600.0")))
        assert "different grids" in str(raised.value)

    def test_a_line_count_disagreeing_with_the_latitude_span_is_refused(self):
        with pytest.raises(SystemExit):
            extract_omega.grid_from_label(download_omega.parse_label(
                LABEL.replace("LINES                             = 7200",
                              "LINES                             = 7000")))


class TestTheFillIsMaskedBeforeItIsScaled:
    def test_missing_counts_become_nodata_and_the_rest_scale(self):
        grid = extract_omega.grid_from_label(download_omega.parse_label(LABEL))
        raw = np.array([[-32768, 0, 10000]], dtype="<i2")
        albedo = extract_omega.unpack(raw, grid)
        assert albedo[0, 0] == extract_omega.NODATA
        assert albedo[0, 1] == pytest.approx(grid["offset"], rel=1e-6)
        assert albedo[0, 2] == pytest.approx(grid["offset"] + 10000 * grid["scaling"], rel=1e-6)

    def test_scaling_the_fill_first_would_hide_it(self):
        """Why the comparison is on raw counts: scaled, the fill is an ordinary negative float that
        no range check downstream would question, and it sits inside no obvious sentinel band."""
        grid = extract_omega.grid_from_label(download_omega.parse_label(LABEL))
        scaled_fill = grid["missing"] * grid["scaling"] + grid["offset"]
        assert -1.0 < scaled_fill < 1.0
        assert scaled_fill != extract_omega.NODATA
