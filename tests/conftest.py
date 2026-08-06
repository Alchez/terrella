"""Shared oracles for the composite tests, and the one guard that has to be suite-wide."""

import math
from pathlib import Path

import pytest

from pipeline import bodies
from pipeline.tile import shade

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
