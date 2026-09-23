"""The files a country's image is downloaded as, each carrying its credit inside it: the two its
page offers, and one zip of every country's WebP that the Archives page offers.

A country's full-size WebP is stamped in place, and its PNG master is copied beside it as
`<slug>-<native>.png`, so both are in the store the site serves as `heroes/`, and the master itself
is never written. Both carry one XMP packet: the WebP as an `XMP ` chunk in an extended container,
the PNG as an `iTXt` chunk ahead of its pixels. Neither file's pixel data is touched.

A file is current when its own packet is the one this run would write, and a copy is current only
while its master is the one it was copied from, so a changed credit or a re-render restamps and a
second pass writes nothing. Anything but the container shapes this writes and reads is refused.

The bundle stores the credit file and every stamped full-size WebP, by name and dated the zip
format's first instant, so a rebuild of unchanged files is byte-identical. It writes the record the
Archives page and the deploy preflight read.

Usage:
  downloads.py stamp                  # every hero in blender/renders/heroes/
  downloads.py stamp --only nepal     # one (or a comma list)
  downloads.py bundle                 # every stamped full-size WebP, in one zip
"""

import argparse
import hashlib
import json
import os
import shutil
import stat
import struct
import sys
import zipfile
import zlib
from pathlib import Path
from xml.sax.saxutils import escape, quoteattr

from pipeline import attribution, bodies, paths
from pipeline.compose import hero_variants
from pipeline.frame import country_config

HEROES = hero_variants.HEROES
VARIANTS = hero_variants.VARIANTS

#: The zip of every country's full-size WebP, as the archives host keys it.
BUNDLE_KEY = f"{bodies.EARTH.name}/country-maps-webp-v1.zip"
#: The bundle's local copy sits under this at its key.
ARCHIVES = paths.ROOT / "blender/renders/archives"
#: The bundle's record, committed for the Archives page and read by the deploy preflight.
RECORD = paths.ROOT / "web/src/data/downloads.json"
#: The bundle's credit file, its first entry.
README = "README.txt"
#: The zip format's first instant, which every entry carries so that a rebuild is byte-identical.
ZIP_EPOCH = (1980, 1, 1, 0, 0, 0)

#: Where a file's terms are explained: About's section on using this work.
WEB_STATEMENT = f"{attribution.SITE_URL}/about/#using-this-work"

#: The VP8X bit saying an `XMP ` chunk follows, libwebp's `XMP_FLAG`.
XMP_FLAG = 0x04
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
#: The keyword an `iTXt` chunk carries an XMP packet under, then its empty compression and language
#: fields: the packet itself is never compressed.
XMP_KEYWORD = b"XML:com.adobe.xmp\0\0\0\0\0"


class UnknownContainer(ValueError):
    """A file whose chunks are not a shape this module writes or reads."""


class Unstamped(ValueError):
    """Full-size WebPs without the credit a stamp pass would give them."""


def xmp_packet(title: str) -> bytes:
    """The packet both of one country's download files carry: what the image is, who made it, and
    the credit and licence every copy owes."""
    credit = escape(attribution.for_hero(bodies.EARTH))
    terms = escape(f"This work is licensed under {attribution.OUTPUT_LICENCE}. To view a copy of "
                   f"this license, visit {attribution.OUTPUT_LICENCE_URL}")
    publisher = escape(attribution.PUBLISHER)
    return f"""<?xpacket begin="\N{BYTE ORDER MARK}" id="W5M0MpCehiHzreSzNTczkc9d"?>
<x:xmpmeta xmlns:x="adobe:ns:meta/">
 <rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#">
  <rdf:Description rdf:about=""
    xmlns:dc="http://purl.org/dc/elements/1.1/"
    xmlns:photoshop="http://ns.adobe.com/photoshop/1.0/"
    xmlns:xmpRights="http://ns.adobe.com/xap/1.0/rights/"
    xmlns:cc="http://creativecommons.org/ns#">
   <dc:title><rdf:Alt><rdf:li xml:lang="x-default">{escape(title)}</rdf:li></rdf:Alt></dc:title>
   <dc:creator><rdf:Seq><rdf:li>{publisher}</rdf:li></rdf:Seq></dc:creator>
   <dc:rights><rdf:Alt><rdf:li xml:lang="x-default">{credit}</rdf:li></rdf:Alt></dc:rights>
   <photoshop:Credit>{credit}</photoshop:Credit>
   <xmpRights:Marked>True</xmpRights:Marked>
   <xmpRights:WebStatement>{escape(WEB_STATEMENT)}</xmpRights:WebStatement>
   <xmpRights:UsageTerms><rdf:Alt><rdf:li xml:lang="x-default">{terms}</rdf:li></rdf:Alt></xmpRights:UsageTerms>
   <cc:license rdf:resource={quoteattr(attribution.OUTPUT_LICENCE_URL)}/>
   <cc:attributionName>{publisher}</cc:attributionName>
  </rdf:Description>
 </rdf:RDF>
</x:xmpmeta>
<?xpacket end="w"?>""".encode()


def replace_atomically(target: Path, content: bytes, mtime_ns: int | None = None) -> None:
    """Write `content` as `target` in one rename, so an interruption leaves the old file whole."""
    staging = target.with_name(target.name + ".tmp")
    try:
        staging.write_bytes(content)
        if mtime_ns is not None:
            os.utime(staging, ns=(mtime_ns, mtime_ns))
        os.replace(staging, target)
    finally:
        staging.unlink(missing_ok=True)


def riff_chunk(tag: bytes, payload: bytes) -> bytes:
    return tag + struct.pack("<I", len(payload)) + payload + b"\0" * (len(payload) & 1)


def riff_chunks(path: Path) -> list[tuple[bytes, int, int]]:
    """Each chunk of a WebP as (tag, payload offset, payload length), read by seeking."""
    size = path.stat().st_size
    with path.open("rb") as handle:
        riff, declared, form = struct.unpack("<4sI4s", handle.read(12))
        if (riff, form) != (b"RIFF", b"WEBP") or declared + 8 != size:
            raise UnknownContainer(f"{path}: not a whole RIFF WebP")
        chunks, position = [], 12
        while position < size:
            handle.seek(position)
            header = handle.read(8)
            if len(header) < 8:
                raise UnknownContainer(f"{path}: truncated chunk at byte {position}")
            tag, length = struct.unpack("<4sI", header)
            chunks.append((tag, position + 8, length))
            position += 8 + length + (length & 1)
        if position != size:
            raise UnknownContainer(f"{path}: last chunk overruns the file")
    return chunks


def vp8_size(path: Path, offset: int) -> tuple[int, int]:
    """The width and height a lossy VP8 key frame declares in its header."""
    with path.open("rb") as handle:
        handle.seek(offset)
        header = handle.read(10)
    if header[3:6] != b"\x9d\x01\x2a":
        raise UnknownContainer(f"{path}: VP8 chunk does not open on a key frame")
    width, height = struct.unpack("<HH", header[6:10])
    return width & 0x3FFF, height & 0x3FFF


def vp8x_payload(width: int, height: int) -> bytes:
    return bytes([XMP_FLAG, 0, 0, 0]) + (width - 1).to_bytes(3, "little") + \
        (height - 1).to_bytes(3, "little")


def read_webp(path: Path) -> tuple[tuple[int, int], bytes | None]:
    """The VP8 chunk's span and the packet a WebP carries, None when it carries none.

    Knows two shapes: the simple container a lossy encode writes, and the extended one this module
    writes around it. Anything else is refused.
    """
    chunks = riff_chunks(path)
    tags = [tag for tag, _, _ in chunks]
    if tags == [b"VP8 "]:
        _, offset, length = chunks[0]
        return (offset - 8, 8 + length + (length & 1)), None
    if tags == [b"VP8X", b"VP8 ", b"XMP "]:
        (_, header_at, header_length), (_, offset, length), (_, packet_at, packet_length) = chunks
        with path.open("rb") as handle:
            handle.seek(header_at)
            header = handle.read(header_length)
            handle.seek(packet_at)
            packet = handle.read(packet_length)
        if header == vp8x_payload(*vp8_size(path, offset)):
            return (offset - 8, 8 + length + (length & 1)), packet
    raise UnknownContainer(f"{path}: chunks {[tag.decode() for tag in tags]}, where a full-size "
                           "WebP is one lossy VP8 chunk, alone or stamped")


def webp_packet(path: Path) -> bytes | None:
    """The packet a full-size WebP carries, None when it carries none."""
    return read_webp(path)[1]


def stamp_webp(path: Path, packet: bytes) -> bool:
    """Carry `packet` inside the WebP at `path`, leaving its VP8 chunk byte for byte. True when the
    file was rewritten, False when it already carried this packet."""
    (start, span), existing = read_webp(path)
    if existing == packet:
        return False
    with path.open("rb") as handle:
        handle.seek(start)
        frame = handle.read(span)
    body = b"WEBP" + riff_chunk(b"VP8X", vp8x_payload(*vp8_size(path, start + 8))) + frame + \
        riff_chunk(b"XMP ", packet)
    replace_atomically(path, b"RIFF" + struct.pack("<I", len(body)) + body)
    return True


def png_chunk(tag: bytes, payload: bytes) -> bytes:
    return struct.pack(">I", len(payload)) + tag + payload + \
        struct.pack(">I", zlib.crc32(tag + payload))


def packet_chunk(packet: bytes) -> bytes:
    return png_chunk(b"iTXt", XMP_KEYWORD + packet)


def png_packet(path: Path) -> bytes | None:
    """The packet a PNG carries in the chunk after its header, None when it carries none."""
    with path.open("rb") as handle:
        head = handle.read(8 + 25 + 8)
        if head[:8] != PNG_SIGNATURE or head[12:16] != b"IHDR":
            raise UnknownContainer(f"{path}: not a PNG opening on its header")
        length, tag = struct.unpack(">I4s", head[33:41])
        if tag != b"iTXt":
            return None
        payload = handle.read(length)
    return payload[len(XMP_KEYWORD):] if payload.startswith(XMP_KEYWORD) else None


def check_master(master: Path, data: bytes) -> None:
    """Refuse a master that is anything but a header, its pixel data and its end."""
    tags, position = [], 8
    while position < len(data):
        length, tag = struct.unpack(">I4s", data[position:position + 8])
        if not tags or tags[-1] != tag:
            tags.append(tag)
        position += 12 + length
    if (data[:8] != PNG_SIGNATURE or data[8:16] != struct.pack(">I4s", 13, b"IHDR")
            or tags != [b"IHDR", b"IDAT", b"IEND"] or position != len(data)):
        raise UnknownContainer(f"{master}: chunk runs {[tag.decode() for tag in tags]}, where a "
                               "master is IHDR, IDAT, IEND")


def copy_is_current(master: Path, out: Path, packet: bytes) -> bool:
    """Whether `out` is a copy of `master` as it is now, carrying `packet`.

    The copy takes its master's modification time, which is what ties it to one render: a re-render
    moves the master's and the copy stops being current.
    """
    if not out.exists():
        return False
    source, current = master.stat(), out.stat()
    return (current.st_size == source.st_size + len(packet_chunk(packet))
            and current.st_mtime_ns == source.st_mtime_ns and png_packet(out) == packet)


def copy_png(master: Path, out: Path, packet: bytes) -> bool:
    """Copy `master` to `out` with `packet` inserted ahead of its pixels. True when the copy was
    written, False when it was already current."""
    if copy_is_current(master, out, packet):
        return False
    chunk = packet_chunk(packet)
    source = master.stat()
    data = master.read_bytes()
    check_master(master, data)
    header_end = 8 + 25
    replace_atomically(out, data[:header_end] + chunk + data[header_end:], source.st_mtime_ns)
    return True


def png_size(master: Path) -> tuple[int, int]:
    with master.open("rb") as handle:
        head = handle.read(24)
    if head[:8] != PNG_SIGNATURE or head[12:16] != b"IHDR":
        raise UnknownContainer(f"{master}: not a PNG opening on its header")
    width, height = struct.unpack(">II", head[16:24])
    return width, height


def full_size_files(master: Path, variants: Path) -> tuple[Path, Path]:
    """One country's two download files: its full-size WebP, which must exist, and the copy of its
    master beside it."""
    native = max(png_size(master))
    webp = variants / f"{master.stem}-{native}.webp"
    if not webp.exists():
        raise FileNotFoundError(f"{webp} is missing: run pipeline.compose.hero_variants first")
    return webp, variants / f"{master.stem}-{native}.png"


def stamp_country(master: Path, variants: Path, title: str) -> list[Path]:
    """Stamp one country's full-size WebP and copy its master beside it. Returns what it wrote."""
    webp, png = full_size_files(master, variants)
    packet = xmp_packet(title)
    written = [webp] if stamp_webp(webp, packet) else []
    if copy_png(master, png, packet):
        written.append(png)
    return written


def unstamped(master: Path, variants: Path, title: str) -> list[Path]:
    """The files a stamp pass would write for one country: each one not carrying `title`'s packet,
    and a copy made from an earlier render of its master."""
    webp, png = full_size_files(master, variants)
    packet = xmp_packet(title)
    stale = []
    if webp_packet(webp) != packet:
        stale.append(webp)
    if not copy_is_current(master, png, packet):
        stale.append(png)
    return stale


def bundle_webps(masters: list[Path], variants: Path, titles: dict[str, str]) -> list[Path]:
    """Every country's full-size WebP, refused while any lacks the credit for its country."""
    webps, unstamped = [], []
    for master in masters:
        webp, _ = full_size_files(master, variants)
        if webp_packet(webp) != xmp_packet(titles[master.stem]):
            unstamped.append(webp.name)
        webps.append(webp)
    if unstamped:
        raise Unstamped(f"{', '.join(unstamped)} without the credit for their country: run "
                        "python -m pipeline.compose.downloads stamp first")
    return webps


def readme(count: int) -> bytes:
    """The bundle's credit file: what it holds, the credit each image carries, and the terms."""
    return (f"{attribution.PUBLISHER} country maps: {count} images, one per country, each at the "
            "full size it was rendered and named for the country and its long edge in pixels.\n\n"
            "Each image carries this credit inside it, as XMP:\n\n"
            f"{attribution.for_hero(bodies.EARTH)}\n\n"
            f"Terms of use: {WEB_STATEMENT}\n"
            f"PNG copies for print are on each country's page at {attribution.SITE_URL}.\n"
            ).encode()


def zip_entry(name: str, size: int) -> zipfile.ZipInfo:
    """A stored entry carrying nothing of the moment, the system or the file mode it was written
    with."""
    entry = zipfile.ZipInfo(name, ZIP_EPOCH)
    entry.compress_type = zipfile.ZIP_STORED
    entry.create_system = 3
    entry.external_attr = (stat.S_IFREG | 0o644) << 16
    entry.file_size = size
    return entry


def write_bundle(webps: list[Path], out: Path) -> None:
    """Write the credit file, then `webps` by name, into one zip at `out` in one rename."""
    out.parent.mkdir(parents=True, exist_ok=True)
    staging = out.with_name(out.name + ".tmp")
    try:
        with zipfile.ZipFile(staging, "w") as archive:
            credit = readme(len(webps))
            archive.writestr(zip_entry(README, len(credit)), credit)
            for webp in sorted(webps, key=lambda path: path.name):
                entry = zip_entry(webp.name, webp.stat().st_size)
                with webp.open("rb") as source, archive.open(entry, "w") as target:
                    shutil.copyfileobj(source, target, 1 << 24)
        os.replace(staging, out)
    finally:
        staging.unlink(missing_ok=True)


def bundle_record(out: Path) -> dict:
    """The record of the bundle at `out`: its key, then, read back from the file, its bytes and
    their SHA-256 and the bytes of each image."""
    with out.open("rb") as handle:
        sha256 = hashlib.file_digest(handle, "sha256").hexdigest()
    with zipfile.ZipFile(out) as archive:
        images = {entry.filename: entry.file_size for entry in archive.infolist()
                  if entry.filename != README}
    return {"key": BUNDLE_KEY, "bytes": out.stat().st_size, "sha256": sha256, "images": images}


def build_bundle(masters: list[Path], titles: dict[str, str]) -> int:
    """Bundle every country's full-size WebP and write the record, refusing an unstamped one."""
    try:
        webps = bundle_webps(masters, VARIANTS, titles)
    except Unstamped as refusal:
        sys.exit(f"refusing to bundle: {refusal}")
    out = ARCHIVES / BUNDLE_KEY
    write_bundle(webps, out)
    record = bundle_record(out)
    previous = json.loads(RECORD.read_text()) if RECORD.exists() else {}
    RECORD.write_text(json.dumps({bodies.EARTH.name: record}, indent=2) + "\n")
    changed = previous.get(bodies.EARTH.name, {}).get("sha256") != record["sha256"]
    print(f"{out}: {len(webps)} images, {record['bytes']:,} bytes, "
          f"{'changed' if changed else 'unchanged'}; recorded in {RECORD}", flush=True)
    return 0


def country_titles() -> dict[str, str]:
    """Every hero country's display name, the one its page is headed with."""
    config = country_config.load_config()
    _shapes, rows = country_config.load_ne_rows()
    scope = country_config.build_scope(config, rows)
    titles = {}
    for slug in country_config.hero_slugs(scope):
        resolved = country_config.resolve(slug, scope[slug], config)
        if resolved is not None:
            titles[slug] = resolved["name"]
    return titles


def main() -> int:
    parser = argparse.ArgumentParser(description="The credit inside each country's download files.")
    commands = parser.add_subparsers(dest="command", required=True)
    stamp = commands.add_parser("stamp", help="stamp every full-size WebP and copy every master "
                                              "beside it, both carrying the credit")
    stamp.add_argument("--only", help="comma-separated slugs (default: every hero)")
    commands.add_parser("bundle", help="zip every stamped full-size WebP with the credit file, and "
                                       "write the record the site reads")
    args = parser.parse_args()

    masters = sorted(HEROES.glob("*.png"))
    if not masters:
        sys.exit(f"no heroes to {args.command} in {HEROES}")
    if args.command == "stamp" and args.only:
        wanted = set(args.only.split(","))
        masters = [master for master in masters if master.stem in wanted]
        if not masters:
            sys.exit(f"no hero in {HEROES} matches --only {args.only}")
    titles = country_titles()
    if args.command == "bundle":
        return build_bundle(masters, titles)
    written = 0
    for master in masters:
        for path in stamp_country(master, VARIANTS, titles[master.stem]):
            print(f"  {path.name}", flush=True)
            written += 1
    print(f"complete: {written} written, {2 * len(masters) - written} already current", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
