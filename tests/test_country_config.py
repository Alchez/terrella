"""Tests for the country_config resolver — the config → per-country params layer.

resolve/build_scope/load_config take their data as arguments (or a config path
we can point at a fixture), so the whole resolution path runs on synthetic
countries with NO external data (Natural Earth, GLO-30, GEBCO). The invariants
here are the ones the pipeline's 'fail loudly' contract depends on: bad config
aborts, and every resolved frame stays inside the world.
"""
import pytest

from pipeline.frame import country_config as cc


# ---- pure helpers -----------------------------------------------------------

def test_slugify_strips_nonalphanumeric_and_lowercases():
    assert cc.slugify("Sri Lanka") == "srilanka"
    assert cc.slugify("United States of America") == "unitedstatesofamerica"
    assert cc.slugify("Côte d'Ivoire") == "ctedivoire"  # non-ASCII letters drop


def test_fmt_frame_uses_g_format():
    assert cc.fmt_frame((79.6, 25.9, 88.6, 30.9)) == "79.6 25.9 88.6 30.9"
    assert cc.fmt_frame((180.0, -9.0, 180.0, -5.0)) == "180 -9 180 -5"


# ---- fixtures ---------------------------------------------------------------

DEFAULTS = {"pad_pct": 5.0, "hero_long_edge": 7680,
            "warp_long_edge": 8192, "fusion": "auto"}


def _cfg(countries=None, exclude=None, include=None):
    return {"defaults": dict(DEFAULTS),
            "scope": {"exclude": exclude or [], "include": include or []},
            "countries": countries or {}}


def _rows():
    return [
        {"admin": "Nepal", "sov": "Nepal", "bbox": (80.0, 26.0, 88.0, 30.0), "idx": 0},
        {"admin": "France", "sov": "France", "bbox": (-5.0, 41.0, 10.0, 51.0), "idx": 1},
        {"admin": "Somaliland", "sov": "Somalia", "bbox": (42.0, 8.0, 49.0, 11.0), "idx": 2},
    ]


# ---- load_config validation (the fail-loudly contract) ----------------------

VALID_TOML = """
[defaults]
pad_pct = 5.0
hero_long_edge = 7680
warp_long_edge = 8192
fusion = "auto"

[scope]
exclude = []
include = []

[countries.france]
frame = [-5.9, 40.6, 10.3, 51.9]
"""


def _point_config_at(tmp_path, monkeypatch, toml_text):
    path = tmp_path / "countries.toml"
    path.write_text(toml_text)
    monkeypatch.setattr(cc, "CONFIG_PATH", path)


def test_load_config_accepts_valid(tmp_path, monkeypatch):
    _point_config_at(tmp_path, monkeypatch, VALID_TOML)
    cfg = cc.load_config()
    assert cfg["countries"]["france"]["frame"] == [-5.9, 40.6, 10.3, 51.9]


@pytest.mark.parametrize("bad_block, needle", [
    ('[countries.x]\nbogus = 1\n', "unknown keys"),
    ('[countries.x]\nstatus = "weird"\n', "unknown status"),
    ('[countries.x]\nframe = [10, 20, 5, 30]\n', "malformed frame"),  # W > E
    ('[countries.x]\nframe = [1, 2, 3, 4]\nstatus = "antimeridian"\n', "contradict"),
    ('[nonsense]\nx = 1\n', "unknown top-level"),
])
def test_load_config_rejects_bad(tmp_path, monkeypatch, bad_block, needle):
    _point_config_at(tmp_path, monkeypatch, VALID_TOML + "\n" + bad_block)
    with pytest.raises(SystemExit) as exc:
        cc.load_config()
    assert needle in str(exc.value)


# ---- build_scope ------------------------------------------------------------

def test_build_scope_keeps_strict_selectors():
    scope = cc.build_scope(_cfg(), _rows())
    assert set(scope) == {"nepal", "france"}  # Somaliland: admin != sov, not strict
    assert scope["nepal"]["admin"] == "Nepal"


def test_build_scope_honours_exclude_and_include():
    scope = cc.build_scope(_cfg(exclude=["France"], include=["Somaliland"]), _rows())
    assert "france" not in scope
    assert "somaliland" in scope


def test_build_scope_rejects_unknown_include():
    with pytest.raises(SystemExit):
        cc.build_scope(_cfg(include=["Atlantis"]), _rows())


# ---- resolve ----------------------------------------------------------------

def test_resolve_shapes_a_full_result(subtests):
    # One resolve() call, several independent facts about its output. subtests
    # (pytest 9.0) reports each so a change to resolve() shows ALL broken
    # properties at once, not just the first — better diagnostics than a chain
    # of asserts. (Parametrized cases below stay parametrized: there each input
    # deserves its own collected, named test item, which subtests wouldn't give.)
    row = _rows()[0]  # Nepal, no override
    resolved = cc.resolve("nepal", row, _cfg())
    assert resolved is not None  # hard precondition — the subtests describe its shape

    with subtests.test("frame is the padded bbox"):
        assert resolved["frame"] == cc.pad_frame(row["bbox"], DEFAULTS["pad_pct"])
    with subtests.test("frame not overridden"):
        assert resolved["frame_overridden"] is False
    with subtests.test("fusion resolved to a concrete step"):
        assert resolved["fusion"] in ("1s", "3s")
    with subtests.test("aspect is positive"):
        assert resolved["aspect"] > 0
    with subtests.test("warp and hero are (width, height)"):
        assert len(resolved["warp"]) == 2 and len(resolved["hero"]) == 2


def test_resolve_override_wins_over_computed_frame():
    cfg = _cfg(countries={"france": {"frame": [-5.9, 40.6, 10.3, 51.9]}})
    resolved = cc.resolve("france", _rows()[1], cfg)
    assert resolved is not None
    assert resolved["frame_overridden"] is True
    assert resolved["frame"] == (-5.9, 40.6, 10.3, 51.9)


def test_resolve_antimeridian_status_returns_none():
    cfg = _cfg(countries={"nepal": {"status": "antimeridian"}})
    assert cc.resolve("nepal", _rows()[0], cfg) is None


def test_resolve_unmarked_antimeridian_bbox_aborts():
    row = {"admin": "Wrap", "sov": "Wrap", "bbox": (-180.0, -20.0, 180.0, -10.0), "idx": 9}
    with pytest.raises(SystemExit):
        cc.resolve("wrap", row, _cfg())


@pytest.mark.parametrize("row", _rows(), ids=lambda r: r["admin"])
def test_resolve_frame_stays_in_the_world(row):
    resolved = cc.resolve(cc.slugify(row["admin"]), row, _cfg())
    assert resolved is not None
    west, south, east, north = resolved["frame"]
    assert -180.0 <= west < east <= 180.0
    assert -90.0 <= south < north <= 90.0


# ---- main_part_fraction (far-flung detection) -------------------------------

class _FakeShape:
    def __init__(self, points, parts):
        self.points = points
        self.parts = parts


class _FakeReader:
    def __init__(self, shape):
        self._shape = shape

    def shape(self, idx):
        return self._shape


def test_main_part_fraction_single_part_fills_its_bbox():
    square = _FakeShape(points=[(0.0, 0.0), (0.0, 1.0), (1.0, 1.0), (1.0, 0.0)],
                        parts=[0])
    row = {"idx": 0, "bbox": (0.0, 0.0, 1.0, 1.0)}
    assert cc.main_part_fraction(_FakeReader(square), row) == pytest.approx(1.0)


def test_main_part_fraction_flags_a_far_flung_speck():
    # a mainland at the origin + a tiny distant speck; the whole-geometry bbox
    # spans both, so the main part covers only a sliver of a bbox axis.
    points = [(0.0, 0.0), (0.0, 1.0), (1.0, 1.0), (1.0, 0.0),          # mainland
              (50.0, 30.0), (50.0, 30.01), (50.01, 30.01), (50.01, 30.0)]  # speck
    shape = _FakeShape(points=points, parts=[0, 4])
    row = {"idx": 0, "bbox": (0.0, 0.0, 50.01, 30.01)}
    assert cc.main_part_fraction(_FakeReader(shape), row) < cc.FAR_FLUNG_FRACTION
