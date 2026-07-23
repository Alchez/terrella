"""bucket_preflight's 24 h stamp: verify the bucket once per day, not per country.

The batch runner invokes download_glo30 once per country, and an unstamped
preflight repeats three S3 HEADs + three full-tile md5s every time (~3-6 s x204
per walk). The preflight exists to catch bucket *edition swaps* — month-scale
events — so a passing check is stamped to preflight_ok.json and reused for
PREFLIGHT_TTL_HOURS. The stamp must never mask a failure: a mismatch aborts
without stamping, and an absent/expired/malformed/future-dated stamp re-verifies.
"""

import hashlib
import json
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from pipeline.acquire import download_glo30

TILE_NAME = "Copernicus_DSM_COG_10_N40_00_E010_00_DEM"


class FakeResponse:
    """Just enough of an HTTP response for bucket_preflight's ETag read."""

    def __init__(self, etag: str):
        self.headers = {"ETag": f'"{etag}"'}

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


@pytest.fixture
def store(tmp_path, monkeypatch):
    """A DATA_DIR holding one fake tile whose md5 the fake bucket can echo."""
    monkeypatch.setattr(download_glo30, "DATA_DIR", tmp_path)
    (tmp_path / "dem").mkdir()
    (tmp_path / "dem" / f"{TILE_NAME}.tif").write_bytes(b"fake tile bytes")
    return tmp_path


def held_md5(store: Path) -> str:
    return hashlib.md5((store / "dem" / f"{TILE_NAME}.tif").read_bytes()).hexdigest()


def arm_bucket(monkeypatch, etag: str) -> list[str]:
    """Fake urlopen answering every HEAD with `etag`; returns the list of URLs hit."""
    calls: list[str] = []

    def fake_urlopen(request, timeout=0):
        calls.append(request.full_url)
        return FakeResponse(etag)

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    return calls


def refuse_network(monkeypatch) -> None:
    def no_network(request, timeout=0):
        raise AssertionError(f"unexpected network hit: {request.full_url}")

    monkeypatch.setattr(urllib.request, "urlopen", no_network)


def write_stamp(store: Path, age_hours: float) -> None:
    checked = datetime.now(timezone.utc) - timedelta(hours=age_hours)
    (store / "preflight_ok.json").write_text(json.dumps(
        {"checked_utc": checked.isoformat(timespec="seconds"), "tiles": []}))


def stamp_age_seconds(store: Path) -> float:
    stamp = json.loads((store / "preflight_ok.json").read_text())
    checked = datetime.fromisoformat(stamp["checked_utc"])
    return (datetime.now(timezone.utc) - checked).total_seconds()


class TestStampWriting:
    def test_no_stamp_verifies_and_stamps(self, store, monkeypatch):
        calls = arm_bucket(monkeypatch, held_md5(store))
        download_glo30.bucket_preflight()
        assert len(calls) == 1  # one held tile -> the 3-sample dedups to 1 HEAD
        stamp = json.loads((store / "preflight_ok.json").read_text())
        assert stamp["tiles"] == [TILE_NAME]
        assert stamp_age_seconds(store) < 60.0

    def test_mismatch_aborts_without_stamp(self, store, monkeypatch):
        arm_bucket(monkeypatch, "0000deadbeef0000")
        with pytest.raises(SystemExit):
            download_glo30.bucket_preflight()
        assert not (store / "preflight_ok.json").exists()

    def test_no_held_tiles_never_stamps(self, tmp_path, monkeypatch):
        """Nothing verified -> nothing to cache (and the check is a no-op anyway)."""
        monkeypatch.setattr(download_glo30, "DATA_DIR", tmp_path)
        refuse_network(monkeypatch)
        download_glo30.bucket_preflight()
        assert not (tmp_path / "preflight_ok.json").exists()


class TestStampReuse:
    def test_fresh_stamp_skips_network(self, store, monkeypatch, capsys):
        write_stamp(store, age_hours=0.5)
        refuse_network(monkeypatch)
        download_glo30.bucket_preflight()
        assert "cached ok" in capsys.readouterr().out

    def test_stale_stamp_reverifies(self, store, monkeypatch):
        write_stamp(store, age_hours=download_glo30.PREFLIGHT_TTL_HOURS + 1.0)
        calls = arm_bucket(monkeypatch, held_md5(store))
        download_glo30.bucket_preflight()
        assert len(calls) == 1
        assert stamp_age_seconds(store) < 60.0  # rewritten, not reused

    def test_future_stamp_reverifies(self, store, monkeypatch):
        """A stamp from the future (clock skew, restored backup) is not trusted."""
        write_stamp(store, age_hours=-2.0)
        calls = arm_bucket(monkeypatch, held_md5(store))
        download_glo30.bucket_preflight()
        assert len(calls) == 1

    def test_malformed_stamp_reverifies(self, store, monkeypatch):
        (store / "preflight_ok.json").write_text("not json {")
        calls = arm_bucket(monkeypatch, held_md5(store))
        download_glo30.bucket_preflight()
        assert len(calls) == 1
        assert stamp_age_seconds(store) < 60.0
