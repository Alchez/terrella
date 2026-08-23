"""The RGI acquisition's one decision: which of the published regions reach the merge.

WHY THIS FILE EXISTS AT ALL. A region that never arrives is INVISIBLE everywhere downstream. The
burn has no polygons there, `glacier_3857.tif` is a valid file of the right size, every freshness
check passes, and the map draws glacierised land on the bare-ground ramp. That is not a hypothetical
failure mode: region 19 was filtered out at this call for the whole life of the tile layer, and what
it cost was the Sub-Antarctic islands — 482 km2 of ice rendered as ground, of which the South
Sandwich group is 242 km2 that NSIDC-0791 also has no observation for, so nothing else could have
covered it.

So the claim here is completeness, and it is asserted against a DERIVED set rather than a listed
one: the region numbers parsed out of the filenames must cover 1..REGION_COUNT with no gaps. A
hand-kept list of expected regions would go stale the same way the filter did.

Offline: `shp_urls` is the pure half `resource_urls` calls after the fetch, so these run against the
shipping selection without a network round trip.
"""

import pytest

from pipeline.acquire import download_rgi

#: The filenames IHP-WINS actually serves, verified against the portal. Region 19's is the one that
#: was dropped, and it is deliberately not last in the list — a filter keyed to position rather than
#: to name would survive a fixture that only ever put it at the end.
REGION_NAMES = [
    "01_alaska", "02_western_canada_usa", "03_arctic_canada_north", "04_arctic_canada_south",
    "05_greenland_periphery", "06_iceland", "07_svalbard_jan_mayen", "08_scandinavia",
    "09_russian_arctic", "10_north_asia", "19_subantarctic_antarctic_islands",
    "11_central_europe", "12_caucasus_middle_east", "13_central_asia", "14_south_asia_west",
    "15_south_asia_east", "16_low_latitudes", "17_southern_andes", "18_new_zealand",
]
BASE = "https://ihp-wins.unesco.org/dataset/rgi/resource/rgi2000-v7.0-g-"


def _resources(names=None):
    """A CKAN resource list in the portal's own shape, plus the non-SHP rows it also serves."""
    rows = [{"url": f"{BASE}{name}.zip", "format": "SHP"} for name in (names or REGION_NAMES)]
    rows += [{"url": f"{BASE}doc.pdf", "format": "PDF"},
             {"url": f"{BASE}readme.txt", "format": None}]
    return rows


def _regions(urls):
    return sorted(int(url.rsplit("-g-", 1)[1][:2]) for url in urls)


class TestEveryPublishedRegionReachesTheMerge:
    """The completeness claim, stated as the outcome a missing region has downstream."""

    def test_no_region_is_dropped_in_transit(self):
        """The instrument's own falsifier as well as the claim: if the region parse found nothing,
        `shp_urls` would raise and every test below would pass for the wrong reason."""
        urls = download_rgi.shp_urls(_resources())
        assert _regions(urls) == list(range(1, download_rgi.REGION_COUNT + 1))

    def test_the_antarctic_region_is_one_of_them(self):
        """THE CONCRETE CASE THAT SHIPPED WRONG, named rather than left to the range above.

        Region 19 is safe to carry only because `layer_producers.WHITE_EXCLUSIONS` takes the rock
        outcrop out AFTER the union folds. Before that it was a second whitener landing on the very
        pixels the exclusion exists to clear, so this assertion and that one hold each other up.
        """
        urls = download_rgi.shp_urls(_resources())
        assert any("19_subantarctic" in url for url in urls), "the Sub-Antarctic islands went missing"

    def test_the_portal_s_non_shapefile_rows_are_still_left_out(self):
        """Completeness is about REGIONS, not about taking everything the portal lists."""
        urls = download_rgi.shp_urls(_resources())
        assert len(urls) == len(REGION_NAMES)
        assert all(url.endswith(".zip") for url in urls)

    def test_a_region_missing_from_the_portal_is_refused_rather_than_merged_short(self):
        """The anti-redo guard. A short list must fail HERE, where the cause is visible, instead of
        one stage away as an empty patch of map that every freshness check calls current."""
        short = [name for name in REGION_NAMES if not name.startswith("19_")]
        with pytest.raises(RuntimeError, match="19"):
            download_rgi.shp_urls(_resources(short))

    def test_a_renamed_filename_is_refused_too(self):
        """The region number is read out of the NAME, so a portal rename is indistinguishable from a
        missing region — and both must be loud. Failing toward 'refuse' is the point: the quiet
        alternative is a merge that silently covers less of the planet than it did yesterday."""
        renamed = [name.replace("07_", "07a_") for name in REGION_NAMES]
        with pytest.raises(RuntimeError, match="7"):
            download_rgi.shp_urls(_resources(renamed))
