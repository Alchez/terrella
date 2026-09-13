"""downloads: a country's two download files carry its credit inside them, and nothing else moves.

What the stamp writes is read back by readers that are not this module: Pillow for the WebP
container, GDAL for the PNG's packet and for both files' pixels, and ElementTree for the fields.
"""

import hashlib
import json
import os
import re
import stat
import struct
import subprocess
import sys
import time
import xml.etree.ElementTree as ET
import zipfile
import zlib
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import urlsplit

import numpy as np
import pytest
import rasterio
from conftest import write_hero_master
from PIL import Image

from pipeline import attribution, bodies
from pipeline.compose import downloads, hero_variants

pytestmark = pytest.mark.filterwarnings("ignore::rasterio.errors.NotGeoreferencedWarning")

REPO_ROOT = Path(__file__).resolve().parents[1]
SLUG = "tiny"
TITLE = "Tiny"
OTHER = "wee"
OTHER_TITLE = "Wee"
WIDTH, HEIGHT = 64, 48

#: The published namespaces, from the XMP, Dublin Core, IPTC and Creative Commons specifications.
NAMESPACES = {
    "x": "adobe:ns:meta/",
    "rdf": "http://www.w3.org/1999/02/22-rdf-syntax-ns#",
    "dc": "http://purl.org/dc/elements/1.1/",
    "photoshop": "http://ns.adobe.com/photoshop/1.0/",
    "xmpRights": "http://ns.adobe.com/xap/1.0/rights/",
    "cc": "http://creativecommons.org/ns#",
}
XML_LANG = "{http://www.w3.org/XML/1998/namespace}lang"
#: What the XMP specification says a packet opens and closes with, so a scanner can find it.
PACKET_HEADER = '<?xpacket begin="\N{BYTE ORDER MARK}" id="W5M0MpCehiHzreSzNTczkc9d"?>'.encode()
PACKET_TRAILER = b'<?xpacket end="w"?>'


def pillow_packet(path: Path) -> bytes | None:
    """The XMP packet Pillow reads out of a WebP, through the libwebp it bundles.

    Pillow rather than GDAL, which reads the PNG half: GDAL's WebP driver looks for the draft
    container's `META` chunk under bit 0x08, so it cannot see a packet written to the current spec.
    """
    with Image.open(path) as image:
        return image.info.get("xmp")


def write_master(path: Path, seed: int, alpha: int = 255, zlevel: int = 6) -> None:
    write_hero_master(path, WIDTH, HEIGHT, seed, alpha, zlevel)


def encode_full_size(master: Path, out: Path) -> None:
    """The full-size WebP as the store holds it, written by the variant writer itself."""
    hero_variants.make_variant(master, True, WIDTH, hero_variants.quality_for(WIDTH), out)


def pixels(path: Path) -> np.ndarray:
    with rasterio.Env(GDAL_PAM_ENABLED="NO"), rasterio.open(path) as dataset:
        return dataset.read()


def gdal_packet(path: Path) -> str | None:
    with rasterio.Env(GDAL_PAM_ENABLED="NO"), rasterio.open(path) as dataset:
        return dataset.tags(ns="xml:XMP").get("xml:XMP")


def riff_chunks(path: Path) -> list[tuple[bytes, bytes]]:
    data = path.read_bytes()
    found, position = [], 12
    while position < len(data):
        tag, size = struct.unpack("<4sI", data[position:position + 8])
        found.append((tag, data[position + 8:position + 8 + size]))
        position += 8 + size + (size & 1)
    return found


def png_chunks(path: Path) -> list[tuple[bytes, bytes]]:
    data = path.read_bytes()
    found, position = [], 8
    while position < len(data):
        size, tag = struct.unpack(">I4s", data[position:position + 8])
        found.append((tag, data[position:position + 12 + size]))
        position += 12 + size
    return found


def identity(path: Path) -> tuple[int, int, int]:
    """What a rewrite changes even when it writes the same bytes: the inode, the time, the size."""
    status = path.stat()
    return status.st_ino, status.st_mtime_ns, status.st_size


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.fixture
def store(tmp_path: Path) -> SimpleNamespace:
    heroes, variants = tmp_path / "heroes", tmp_path / "variants"
    heroes.mkdir()
    variants.mkdir()
    master = heroes / f"{SLUG}.png"
    write_master(master, seed=0)
    webp = variants / f"{SLUG}-{WIDTH}.webp"
    encode_full_size(master, webp)
    return SimpleNamespace(master=master, variants=variants, webp=webp,
                           png=variants / f"{SLUG}-{WIDTH}.png")


def description(packet: bytes) -> ET.Element:
    root = ET.fromstring(packet)
    assert root.tag == f"{{{NAMESPACES['x']}}}xmpmeta"
    found = root.findall("rdf:RDF/rdf:Description", NAMESPACES)
    assert len(found) == 1
    return found[0]


def fields(packet: bytes) -> dict[str, ET.Element]:
    prefix = {uri: name for name, uri in NAMESPACES.items()}
    named = {}
    for element in description(packet):
        uri, local = element.tag[1:].split("}")
        named[f"{prefix[uri]}:{local}"] = element
    return named


def lang_alt(element: ET.Element) -> str | None:
    items = element.findall("rdf:Alt/rdf:li", NAMESPACES)
    assert [item.get(XML_LANG) for item in items] == ["x-default"]
    return items[0].text


class TestThePacket:
    def test_it_is_a_packet_a_scanner_can_find(self):
        packet = downloads.xmp_packet(TITLE)
        assert packet.startswith(PACKET_HEADER)
        assert packet.rstrip().endswith(PACKET_TRAILER)

    def test_it_carries_exactly_the_nine_fields(self):
        assert set(fields(downloads.xmp_packet(TITLE))) == {
            "dc:title", "dc:creator", "dc:rights", "photoshop:Credit", "xmpRights:Marked",
            "xmpRights:WebStatement", "xmpRights:UsageTerms", "cc:license", "cc:attributionName",
        }

    def test_both_credit_fields_are_the_hero_credit(self):
        named = fields(downloads.xmp_packet(TITLE))
        credit = attribution.for_hero(bodies.EARTH)
        assert lang_alt(named["dc:rights"]) == credit
        assert named["photoshop:Credit"].text == credit

    def test_it_names_the_country_and_the_publisher(self):
        named = fields(downloads.xmp_packet(TITLE))
        assert lang_alt(named["dc:title"]) == TITLE
        creators = named["dc:creator"].findall("rdf:Seq/rdf:li", NAMESPACES)
        assert [creator.text for creator in creators] == [attribution.PUBLISHER]
        assert named["cc:attributionName"].text == attribution.PUBLISHER

    def test_it_states_the_licence(self):
        named = fields(downloads.xmp_packet(TITLE))
        assert named["xmpRights:Marked"].text == "True"
        licence = named["cc:license"].get(f"{{{NAMESPACES['rdf']}}}resource")
        assert licence == attribution.OUTPUT_LICENCE_URL
        terms = lang_alt(named["xmpRights:UsageTerms"])
        assert terms is not None
        assert attribution.OUTPUT_LICENCE in terms and attribution.OUTPUT_LICENCE_URL in terms

    def test_the_terms_page_it_names_carries_the_anchor(self):
        statement = fields(downloads.xmp_packet(TITLE))["xmpRights:WebStatement"].text
        assert statement is not None
        address = urlsplit(statement)
        assert f"{address.scheme}://{address.netloc}" == attribution.SITE_URL
        assert address.fragment, "a statement with no fragment lands on the top of the page"
        page = REPO_ROOT / "web/src/pages" / f"{address.path.strip('/')}.astro"
        source = re.sub(r"\{/\*.*?\*/\}|<!--.*?-->", "", page.read_text(), flags=re.DOTALL)
        assert re.search(rf'<\w+[^>]*\sid="{re.escape(address.fragment)}"', source), (
            f"{page.name} has no element with id={address.fragment!r}")

    def test_a_title_is_escaped_rather_than_read_as_markup(self):
        title = 'Trinidad & Tobago <"quoted">'
        assert lang_alt(fields(downloads.xmp_packet(title))["dc:title"]) == title


class TestTheWebP:
    def test_pillow_reads_the_packet_from_the_stamped_file(self, store):
        packet = downloads.xmp_packet(TITLE)
        assert downloads.stamp_webp(store.webp, packet)
        with Image.open(store.webp) as image:
            assert image.size == (WIDTH, HEIGHT)
            assert image.info.get("xmp") == packet
        assert downloads.webp_packet(store.webp) == packet

    def test_the_pixels_and_the_bitstream_are_untouched(self, store):
        before = pixels(store.webp)
        (frame,) = [payload for tag, payload in riff_chunks(store.webp) if tag == b"VP8 "]
        downloads.stamp_webp(store.webp, downloads.xmp_packet(TITLE))
        assert [tag for tag, _ in riff_chunks(store.webp)] == [b"VP8X", b"VP8 ", b"XMP "]
        assert [payload for tag, payload in riff_chunks(store.webp) if tag == b"VP8 "] == [frame]
        assert np.array_equal(pixels(store.webp), before)

    def test_an_unstamped_file_has_no_packet(self, store):
        assert downloads.webp_packet(store.webp) is None

    def test_stamping_again_writes_nothing(self, store):
        packet = downloads.xmp_packet(TITLE)
        downloads.stamp_webp(store.webp, packet)
        before = identity(store.webp)
        assert not downloads.stamp_webp(store.webp, packet)
        assert identity(store.webp) == before

    def test_a_changed_credit_replaces_the_packet_rather_than_adding_one(self, store):
        downloads.stamp_webp(store.webp, downloads.xmp_packet("Before"))
        after = downloads.xmp_packet("After")
        assert downloads.stamp_webp(store.webp, after)
        assert pillow_packet(store.webp) == after
        assert [tag for tag, _ in riff_chunks(store.webp)].count(b"XMP ") == 1

    def test_an_interrupted_stamp_leaves_the_file_as_it_was(self, store, monkeypatch):
        before = digest(store.webp)

        def interrupted(source, target):
            raise OSError("interrupted")

        monkeypatch.setattr(downloads.os, "replace", interrupted)
        with pytest.raises(OSError, match="interrupted"):
            downloads.stamp_webp(store.webp, downloads.xmp_packet(TITLE))
        assert digest(store.webp) == before
        assert sorted(path.name for path in store.variants.iterdir()
                      if not path.name.endswith(".aux.xml")) == [store.webp.name]

    @pytest.mark.parametrize("shape", ["lossless", "alpha", "trailing bytes"])
    def test_a_container_it_does_not_know_is_refused_and_left_alone(self, store, shape):
        if shape == "lossless":
            store.webp.unlink()
            subprocess.run(["gdal_translate", "-q", "-of", "WEBP", "-co", "LOSSLESS=YES",
                            str(store.master), str(store.webp)], check=True)
        elif shape == "alpha":
            write_master(store.master, seed=0, alpha=128)
            store.webp.unlink()
            encode_full_size(store.master, store.webp)
        else:
            with store.webp.open("ab") as handle:
                handle.write(b"\0\0")
        before = digest(store.webp)
        with pytest.raises(downloads.UnknownContainer):
            downloads.stamp_webp(store.webp, downloads.xmp_packet(TITLE))
        assert digest(store.webp) == before


class TestThePng:
    def test_gdal_reads_the_packet_from_the_copy(self, store):
        packet = downloads.xmp_packet(TITLE)
        assert downloads.copy_png(store.master, store.png, packet)
        assert gdal_packet(store.png) == packet.decode()
        assert downloads.png_packet(store.png) == packet

    def test_the_copy_is_the_master_plus_one_chunk_before_its_pixels(self, store):
        downloads.copy_png(store.master, store.png, downloads.xmp_packet(TITLE))
        tags = [tag for tag, _ in png_chunks(store.png)]
        assert tags[:2] == [b"IHDR", b"iTXt"]
        assert tags.index(b"iTXt") < tags.index(b"IDAT")
        without = b"".join(chunk for tag, chunk in png_chunks(store.png) if tag != b"iTXt")
        assert store.png.read_bytes()[:8] + without == store.master.read_bytes()
        assert np.array_equal(pixels(store.png), pixels(store.master))

    def test_the_master_is_never_written(self, store):
        before = (digest(store.master), identity(store.master))
        downloads.copy_png(store.master, store.png, downloads.xmp_packet(TITLE))
        downloads.copy_png(store.master, store.png, downloads.xmp_packet("Changed"))
        assert (digest(store.master), identity(store.master)) == before

    def test_a_master_has_no_packet(self, store):
        assert downloads.png_packet(store.master) is None

    def test_copying_again_writes_nothing(self, store):
        packet = downloads.xmp_packet(TITLE)
        downloads.copy_png(store.master, store.png, packet)
        before = identity(store.png)
        assert not downloads.copy_png(store.master, store.png, packet)
        assert identity(store.png) == before

    def test_a_changed_credit_recopies(self, store):
        downloads.copy_png(store.master, store.png, downloads.xmp_packet("Before"))
        after = downloads.xmp_packet("After")
        assert downloads.copy_png(store.master, store.png, after)
        assert gdal_packet(store.png) == after.decode()

    def test_a_rerendered_master_is_recopied_even_at_the_same_length(self, store):
        write_master(store.master, seed=0, zlevel=0)
        packet = downloads.xmp_packet(TITLE)
        downloads.copy_png(store.master, store.png, packet)
        length = store.master.stat().st_size
        write_master(store.master, seed=1, zlevel=0)
        assert store.master.stat().st_size == length, "the fixture must defeat a length check"
        assert downloads.copy_png(store.master, store.png, packet)
        assert np.array_equal(pixels(store.png), pixels(store.master))

    @pytest.mark.parametrize("shape", ["text chunk", "already stamped"])
    def test_a_master_it_does_not_know_is_refused(self, store, shape):
        if shape == "text chunk":
            titled = store.master.with_name("titled.png")
            subprocess.run(["gdal_translate", "-q", "-of", "PNG", "-co", "TITLE=probe",
                            str(store.master), str(titled)], check=True)
            os.replace(titled, store.master)
        else:
            downloads.copy_png(store.master, store.png, downloads.xmp_packet(TITLE))
            os.replace(store.png, store.master)
        with pytest.raises(downloads.UnknownContainer):
            downloads.copy_png(store.master, store.png, downloads.xmp_packet(TITLE))
        assert not store.png.exists()


class TestTheCountry:
    def test_it_stamps_the_full_size_webp_and_copies_the_master_beside_it(self, store):
        packet = downloads.xmp_packet(TITLE)
        assert downloads.stamp_country(store.master, store.variants, TITLE) == [store.webp,
                                                                                  store.png]
        assert pillow_packet(store.webp) == packet
        assert gdal_packet(store.png) == packet.decode()

    def test_a_second_pass_writes_nothing(self, store):
        downloads.stamp_country(store.master, store.variants, TITLE)
        assert downloads.stamp_country(store.master, store.variants, TITLE) == []

    def test_a_country_without_its_full_size_webp_stops_before_copying(self, store):
        store.webp.unlink()
        with pytest.raises(FileNotFoundError, match="hero_variants"):
            downloads.stamp_country(store.master, store.variants, TITLE)
        assert not store.png.exists()


class TestWhatAPassWouldStamp:
    def test_nothing_once_the_country_is_stamped(self, store):
        downloads.stamp_country(store.master, store.variants, TITLE)
        assert downloads.unstamped(store.master, store.variants, TITLE) == []

    def test_both_files_before_it_is(self, store):
        assert downloads.unstamped(store.master, store.variants, TITLE) == [store.webp, store.png]

    def test_both_files_when_they_carry_another_name(self, store):
        downloads.stamp_country(store.master, store.variants, "Before")
        assert downloads.unstamped(store.master, store.variants, TITLE) == [store.webp, store.png]

    def test_the_copy_alone_once_its_master_has_changed(self, store):
        downloads.stamp_country(store.master, store.variants, TITLE)
        later = store.master.stat().st_mtime_ns + 1_000_000_000
        os.utime(store.master, ns=(later, later))
        assert downloads.unstamped(store.master, store.variants, TITLE) == [store.png]


def local_headers(path: Path) -> list[dict]:
    """Each zip entry's local header and data, read by hand rather than by `zipfile`, which wrote
    them."""
    data = path.read_bytes()
    entries, position = [], 0
    while data[position:position + 4] == b"PK\x03\x04":
        (flags, method, dos_time, dos_date, crc, compressed, size, name_length,
         extra_length) = struct.unpack("<2xHHHHIIIHH", data[position + 4:position + 30])
        start = position + 30 + name_length + extra_length
        entries.append(dict(name=data[position + 30:position + 30 + name_length].decode(),
                            flags=flags, method=method, dos_time=dos_time, dos_date=dos_date,
                            crc=crc, compressed=compressed, size=size,
                            data=data[start:start + compressed]))
        position = start + compressed
    assert data[position:position + 4] == b"PK\x01\x02", "entries end where the directory begins"
    return entries


@pytest.fixture
def stamped(store) -> SimpleNamespace:
    """Two countries as a stamp pass leaves them."""
    other = store.master.with_name(f"{OTHER}.png")
    write_master(other, seed=1)
    encode_full_size(other, store.variants / f"{OTHER}-{WIDTH}.webp")
    titles = {SLUG: TITLE, OTHER: OTHER_TITLE}
    for master in (store.master, other):
        downloads.stamp_country(master, store.variants, titles[master.stem])
    return SimpleNamespace(masters=[store.master, other], variants=store.variants, titles=titles,
                           webps=[store.webp, store.variants / f"{OTHER}-{WIDTH}.webp"],
                           out=store.variants.parent / "archives" / "bundle.zip")


class TestTheBundle:
    def test_it_holds_the_credit_file_then_each_full_size_webp_under_its_store_name(self, stamped):
        downloads.write_bundle(stamped.webps, stamped.out)
        with zipfile.ZipFile(stamped.out) as archive:
            assert archive.namelist() == [downloads.README, *(webp.name for webp in stamped.webps)]
            for webp in stamped.webps:
                assert archive.read(webp.name) == webp.read_bytes()

    def test_every_entry_is_stored_and_dated_the_zip_formats_first_instant(self, stamped):
        downloads.write_bundle(stamped.webps, stamped.out)
        entries = local_headers(stamped.out)
        assert [entry["name"] for entry in entries] == [downloads.README,
                                                        *(webp.name for webp in stamped.webps)]
        for entry in entries:
            # Method 0 is stored; 0x21 and 0 are 1980-01-01 00:00 in DOS date and time; no flag
            # means the CRC and sizes sit in this header rather than in a descriptor after the data.
            assert (entry["method"], entry["dos_date"], entry["dos_time"], entry["flags"]) == (
                0, 0x21, 0, 0)
            assert entry["compressed"] == entry["size"] == len(entry["data"])
            assert entry["crc"] == zlib.crc32(entry["data"])

    def test_every_entry_unpacks_as_a_file_anyone_can_read(self, stamped):
        downloads.write_bundle(stamped.webps, stamped.out)
        with zipfile.ZipFile(stamped.out) as archive:
            for entry in archive.infolist():
                mode = entry.external_attr >> 16
                assert stat.S_ISREG(mode) and mode & 0o444 == 0o444, (entry.filename, oct(mode))

    def test_a_rebuild_is_byte_identical_whatever_the_clock_the_files_and_their_order(
            self, stamped, monkeypatch):
        downloads.write_bundle(stamped.webps, stamped.out)
        for webp in stamped.webps:
            os.utime(webp, ns=(2_000_000_000 * 10**9, 2_000_000_000 * 10**9))
            webp.chmod(0o600)
        monkeypatch.setattr(time, "time", lambda: 2_000_000_000.0)
        again = stamped.out.with_name("again.zip")
        downloads.write_bundle(stamped.webps[::-1], again)
        assert digest(again) == digest(stamped.out)

    def test_the_credit_file_gives_the_count_the_hero_credit_and_where_the_terms_are(self, stamped):
        downloads.write_bundle(stamped.webps, stamped.out)
        with zipfile.ZipFile(stamped.out) as archive:
            text = archive.read(downloads.README).decode()
        assert re.search(rf"\b{len(stamped.webps)} images\b", text)
        assert attribution.for_hero(bodies.EARTH) in text
        assert downloads.WEB_STATEMENT in text

    def test_its_record_is_what_the_file_holds(self, stamped):
        downloads.write_bundle(stamped.webps, stamped.out)
        assert downloads.bundle_record(stamped.out) == {
            "key": downloads.BUNDLE_KEY,
            "bytes": stamped.out.stat().st_size,
            "sha256": digest(stamped.out),
            "images": {webp.name: webp.stat().st_size for webp in stamped.webps},
        }

    def test_an_interrupted_rebuild_leaves_the_last_bundle_whole(self, stamped, monkeypatch):
        downloads.write_bundle(stamped.webps, stamped.out)
        before = digest(stamped.out)

        def interrupted(source, target):
            raise OSError("interrupted")

        monkeypatch.setattr(downloads.os, "replace", interrupted)
        with pytest.raises(OSError, match="interrupted"):
            downloads.write_bundle(stamped.webps[:1], stamped.out)
        assert digest(stamped.out) == before
        assert [path.name for path in stamped.out.parent.iterdir()] == [stamped.out.name]

    def test_a_webp_without_its_credit_is_refused_by_name(self, stamped):
        encode_full_size(stamped.masters[1], stamped.webps[1])
        with pytest.raises(downloads.Unstamped) as refusal:
            downloads.bundle_webps(stamped.masters, stamped.variants, stamped.titles)
        message = str(refusal.value)
        assert stamped.webps[1].name in message and stamped.webps[0].name not in message
        assert "downloads stamp" in message

    def test_a_webp_carrying_another_countrys_name_is_refused(self, stamped):
        downloads.stamp_webp(stamped.webps[1], downloads.xmp_packet(TITLE))
        with pytest.raises(downloads.Unstamped, match=re.escape(stamped.webps[1].name)):
            downloads.bundle_webps(stamped.masters, stamped.variants, stamped.titles)

    def test_a_country_without_its_full_size_webp_is_refused(self, stamped):
        stamped.webps[1].unlink()
        with pytest.raises(FileNotFoundError, match="hero_variants"):
            downloads.bundle_webps(stamped.masters, stamped.variants, stamped.titles)


class TestTheBundleCommand:
    @pytest.fixture
    def root(self, stamped, monkeypatch) -> Path:
        """Where the command writes, with the store and the scope it reads redirected to `stamped`."""
        root = stamped.variants.parent
        monkeypatch.setattr(downloads, "HEROES", stamped.masters[0].parent)
        monkeypatch.setattr(downloads, "VARIANTS", stamped.variants)
        monkeypatch.setattr(downloads, "ARCHIVES", root / "archives")
        monkeypatch.setattr(downloads, "RECORD", root / "downloads.json")
        monkeypatch.setattr(downloads, "country_titles", lambda: stamped.titles)
        monkeypatch.setattr(sys, "argv", ["downloads.py", "bundle"])
        return root

    def test_it_writes_the_bundle_and_the_record_the_site_reads(self, root):
        assert downloads.main() == 0
        bundle = root / "archives" / downloads.BUNDLE_KEY
        assert json.loads((root / "downloads.json").read_text()) == {
            "earth": downloads.bundle_record(bundle)}

    def test_it_writes_nothing_while_a_webp_lacks_its_credit(self, stamped, root):
        encode_full_size(stamped.masters[1], stamped.webps[1])
        with pytest.raises(SystemExit, match=re.escape(stamped.webps[1].name)):
            downloads.main()
        assert not (root / "archives").exists() and not (root / "downloads.json").exists()
