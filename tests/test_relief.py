"""Tests for relief/shading geometry helpers.

`mercator_zfactor` is the correction that lets a single hillshade look consistent
across latitude on a Web Mercator grid: Mercator preserves shape (so slope aspect is
already right) but inflates horizontal scale by 1/cos(lat), which flattens computed
slopes toward the poles. Scaling the vertical exaggeration by 1/cos(lat) restores the
hero's physical exaggeration at every latitude.
"""

import itertools
import math

import pytest

from pipeline.look import relief


class TestMercatorZFactor:
    def test_equator_is_base_exaggeration(self):
        assert relief.mercator_zfactor(0.0, 15.0) == pytest.approx(15.0)

    def test_sixty_degrees_doubles(self):
        # cos(60) = 0.5, so the z-factor must double to hold physical relief
        assert relief.mercator_zfactor(60.0, 15.0) == pytest.approx(30.0)

    def test_symmetric_north_south(self):
        assert relief.mercator_zfactor(-40.0, 15.0) == pytest.approx(
            relief.mercator_zfactor(40.0, 15.0))

    def test_increases_with_latitude(self):
        zs = [relief.mercator_zfactor(lat, 15.0) for lat in (0, 20, 40, 60, 80)]
        assert zs == sorted(zs)
        assert all(later > earlier for earlier, later in itertools.pairwise(zs))

    def test_matches_closed_form(self):
        for lat in (12.3, 25.0, 47.5, 71.0):
            assert relief.mercator_zfactor(lat, 15.0) == pytest.approx(
                15.0 / math.cos(math.radians(lat)))
