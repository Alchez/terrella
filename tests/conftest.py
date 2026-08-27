"""Shared oracles for the composite tests, and the one guard that has to be suite-wide."""

import math
from pathlib import Path

import pytest

from pipeline import bodies, planet_seam
from pipeline.tile import cap_render, shade

#: The REAL served root, resolved once while `paths.ROOT` still points at this checkout.
#:
#: Deliberately bound at import, which is the exact shape `bodies.public_root` exists to avoid — and
#: here it is the requirement rather than the bug. A guard that re-resolved the root per call would
#: follow a test's redirect into `tmp_path` and go blind at precisely the moment it is needed, since
#: a test that redirects is the one that believes it is isolated.
REAL_PUBLIC_ROOT = bodies.public_root()


def _served_tree() -> dict[Path, tuple[int, int]]:
    """Every served file with its size and mtime. Absent tree reads as empty, so a clean clone
    (where `web/public/caps/` is gitignored and may not exist) measures the same as a built one."""
    if not REAL_PUBLIC_ROOT.exists():
        return {}
    return {path: (path.stat().st_size, path.stat().st_mtime_ns)
            for path in REAL_PUBLIC_ROOT.rglob("*") if path.is_file()}


@pytest.fixture(autouse=True)
def the_suite_never_writes_into_the_served_tree():
    """No test may add to or modify anything under `web/public/`.

    OR ELSE it ships. That directory is the site's build input, so a stray artifact is copied into
    `web/dist/` by the next `astro build` and deployed — and `web/.gitignore` covers `public/caps/`,
    so `git status` stays clean the whole way. This ran unnoticed until a 324-byte `cap_tiny_elev.webp`
    was found sitting in a built `dist/`.

    Function-scoped rather than session-scoped so the failure NAMES the test that wrote the file;
    the tree is small (tens of files) and the walk does not measurably move the suite.

    It fails open if the session dies mid-run, which is the accepted cost of a backstop: the
    contract itself is pinned by `test_bodies.py`, and the two root-redirecting fixtures in
    `test_cap_render.py` assert their own isolation. This catches the case those cannot — a test
    that reaches the served tree without redirecting anything at all.
    """
    before = _served_tree()
    yield
    after = _served_tree()
    added = sorted(path for path in after if path not in before)
    touched = sorted(path for path in after if path in before and after[path] != before[path])
    if not added and not touched:
        return
    # ONLY the added files are cleaned up, so one leaking test does not turn every later test red.
    # A file that already existed is REPORTED AND LEFT: it is a real shipped asset, and deleting a
    # cap texture to tidy a test failure would cost a ~14 GB re-render.
    for path in added:
        path.unlink(missing_ok=True)
    named = ", ".join(str(path.relative_to(REAL_PUBLIC_ROOT)) for path in added + touched)
    pytest.fail(f"this test wrote into the SERVED tree, which ships to web/dist/ and deploys: "
                f"{named}. Point the write at tmp_path — and if the fixture already redirects "
                f"paths.ROOT, check every root derived from it is read at call time.")


def write_planet_vrt(path: Path, grid: tuple[int, int] = (3600, 3600),
                     bounds: tuple[float, float, float, float] = (-180.0, -90.0, 180.0, 90.0),
                     ) -> None:
    """Write a stand-in planet VRT carrying a real grid, the way a producer's `gdalbuildvrt` would.

    ONE OWNER BECAUSE TWO SUITES FABRICATE THESE. `planet_seam.declare` reads a GeoTransform now, to
    refuse rasters whose pixels straddle each other, so `<VRTDataset/>` stopped being enough — and it
    stopped being enough in `test_relief_scan` as well as in `test_planet_seam`, which is how a
    second copy of this string would have been born. Change the shape here and both go red together.

    Written as XML rather than built with `gdalbuildvrt` because these back no real files: the point
    is the grid a declaration is checked against, and a real VRT would need real chunks to index.
    """
    west, south, east, north = bounds
    width, height = grid
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f'<VRTDataset rasterXSize="{width}" rasterYSize="{height}">'
        f"<GeoTransform>{west}, {(east - west) / width}, 0.0, "
        f"{north}, 0.0, {-(north - south) / height}</GeoTransform>"
        f"</VRTDataset>")


#: What each body's planet producer really declares, keyed by body name.
#:
#: A LITERAL, because there is nothing to derive it from: `planet_seam.declared` reads the producer's
#: own declaration off a disk that a fresh clone does not have, so the set is a production fact
#: rather than a registry answer.
#:
#: SUITE-WIDE RATHER THAN PER-FILE, because three test modules have now walked into the same trap
#: independently. A store read passes on the maintainer's box and goes red in CI, so it is invisible
#: exactly where it is written, and each module discovered it separately and wrote its own copy.
#: `tests/test_planet_seam.py` holds this table against the real declarations.
DECLARED_RASTERS = {
    "earth": frozenset(planet_seam.KNOWN_RASTERS),
    # `relabel_mars` declares the heightfield alone: Mars has no sea, so no mask classifies one.
    "mars": frozenset({"heightfield"}),
}


def declare_planet_rasters(monkeypatch) -> dict[str, frozenset[str]]:
    """Answer the planet seam from `DECLARED_RASTERS` rather than from this machine's store, and
    return the table for a caller that wants the set rather than the substitution.

    THE MODE THIS SUITE IS ACTUALLY RUN IN BY ANYONE BUT THE MAINTAINER. Patches the module
    attribute, not one importer's view of it, so every consumer in the process is answered.
    """
    monkeypatch.setattr(planet_seam, "declared", lambda body: DECLARED_RASTERS[body.name])
    return DECLARED_RASTERS


def hillshade_for_light(light: float) -> float:
    """The hillshade DN whose post-`apply_ambient_floor` light is exactly `light`.

    A test that wants a pixel to land on a known light used to write `flat * light`,
    because the ambient floor was a `np.clip` and therefore an identity everywhere above
    `ambient`. Since `ambient_knee` went to 0.30 the floor is a softplus,
    which sits strictly ABOVE its input -- about +5% at the top of the range, enough to
    push a lake off `WATER_RGB` and to shove the snow window's upper end into saturation
    where a curve knob can no longer move it. Both read as the knob being broken.

    Inverting the floor analytically keeps those tests pinned to their stated intent under
    any future `ambient` / `ambient_knee`, instead of re-tuning constants each time.
    """
    flat = 255.0 * math.sin(math.radians(shade.KNOBS["alt"]))
    ambient, knee = shade.KNOBS["ambient"], shade.KNOBS["ambient_knee"]
    if knee <= 0.0:
        return flat * light
    if light <= ambient:
        raise ValueError(f"light {light} is at or below the ambient floor {ambient}; "
                         "the softplus never reaches it, so no hillshade DN produces it")
    return flat * (ambient + knee * math.log(math.expm1((light - ambient) / knee)))


def cap_ground_metres_per_px_from_ground_radius(grid: cap_render.CapGrid) -> float:
    """The ground metres one cap pixel spans, derived without the projection it is drawn on.

    THE ORACLE FOR `cap_render.cap_ground_metres_per_px`, and it is one because the AEQD sphere
    CANCELS. Production reaches the answer as `2 * edge_m / px` times the AEQD-to-ground ratio, and
    `edge_m` is itself `aeqd_radius_m * colatitude` — so the radius the cap is drawn on divides out
    and what is left mentions only the body's own size. Recomputing it this way is a second answer
    rather than the production expression retyped, which is what lets one comparison catch a dropped
    ratio, an inverted one and a doubled one alike.

    Shared rather than written at each guard because a test that reads the function it is guarding
    is not a guard at all: drop the ratio and a caller which asks `cap_ground_metres_per_px` how wide
    its own pixels are gets a consistent pair of wrong numbers, and every distance it draws still
    measures correct against them. Both guards therefore have to aim with this, and a second copy of
    it could be corrected in one place and left wrong in the other.
    """
    return (2.0 * grid.body.ground_radius_m
            * math.radians(90.0 - abs(grid.edge_lat)) / grid.px)
