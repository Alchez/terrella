"""The GWL_FCS30 acquisition fetches the record it is pinned to, under the licence it is pinned to.

Offline: `preflight` is the pure half `main` calls on the fetched record, and `fetch_archive` runs
against a stubbed download.
"""

import hashlib

import pytest

from pipeline import datasets, paths
from pipeline.acquire.earth import download_gwl


def _record() -> dict:
    """The record in Zenodo's own API shape, listing exactly the pin."""
    return {"metadata": {"license": {"id": download_gwl.LICENCE}},
            "files": [{"key": name, "size": size, "checksum": f"md5:{md5}",
                       "links": {"self": download_gwl.content_url(name)}}
                      for name, (size, md5) in download_gwl.ARCHIVES.items()]}


class TestThePreflight:
    def test_the_pinned_record_passes(self):
        download_gwl.preflight(_record())

    def test_a_changed_licence_stops_the_run(self):
        record = _record()
        record["metadata"]["license"]["id"] = "cc-by-nc-4.0"
        with pytest.raises(SystemExit, match="cc-by-nc-4.0"):
            download_gwl.preflight(record)

    def test_an_archive_whose_bytes_moved_is_refused_by_name(self):
        record = _record()
        record["files"][3]["checksum"] = "md5:" + "0" * 32
        with pytest.raises(SystemExit, match=record["files"][3]["key"]):
            download_gwl.preflight(record)

    def test_an_archive_the_record_no_longer_lists_is_refused_by_name(self):
        record = _record()
        gone = record["files"].pop(5)["key"]
        with pytest.raises(SystemExit, match=gone):
            download_gwl.preflight(record)

    def test_an_archive_the_pin_does_not_name_is_refused(self):
        """A longitude band the pin lacks would never be fetched, and nothing downstream could tell."""
        record = _record()
        record["files"].append({"key": "GWL_FCS30_2020_W180.zip", "size": 1,
                                "checksum": "md5:" + "1" * 32})
        with pytest.raises(SystemExit, match="W180"):
            download_gwl.preflight(record)


class TestAFreshArchiveIsChecked:
    @pytest.fixture
    def store(self, monkeypatch, tmp_path):
        monkeypatch.setattr(paths, "DATA", tmp_path)
        datasets.gwl().mkdir(parents=True)
        return tmp_path

    @staticmethod
    def _lands(monkeypatch, payload: bytes) -> None:
        def download(url, dest, **_):
            dest.write_bytes(payload)
            return "ok"
        monkeypatch.setattr(download_gwl, "download_one", download)

    def test_the_published_bytes_are_kept(self, monkeypatch, store):
        name, payload = next(iter(download_gwl.ARCHIVES)), b"the archive"
        monkeypatch.setitem(download_gwl.ARCHIVES, name,
                            (len(payload), hashlib.md5(payload).hexdigest()))
        self._lands(monkeypatch, payload)
        assert download_gwl.fetch_archive(name, verify_existing=False) == "ok"
        assert (store / "raw" / "gwl_fcs30" / name).read_bytes() == payload

    def test_wrong_bytes_are_removed_so_a_rerun_fetches_them_again(self, monkeypatch, store):
        """`download_one` resumes on `exists()`, so a bad archive left in place is never refetched."""
        name = next(iter(download_gwl.ARCHIVES))
        self._lands(monkeypatch, b"not the archive")
        assert download_gwl.fetch_archive(name, verify_existing=False).startswith("failed")
        assert not (store / "raw" / "gwl_fcs30" / name).exists()
