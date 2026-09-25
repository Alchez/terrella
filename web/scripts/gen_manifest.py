"""Generate the Tier-1 gallery manifest (src/data/countries.json).

Bridges the render pipeline to the frontend. It takes the in-scope countries and their display
names from the pipeline's country_config, each country's continent and other spellings from its
Natural Earth row and the config's `also` (see `search_terms`), and from the render store which
countries are rendered, at what sizes, and what their download files are.

Re-run it after the publish steps docs/pipeline.md lists before it. It refuses to write while a
rendered country has stale files, and names them and what fixes each.

Run from web/ with the pipeline's venv, since country_config needs rasterio and pyshp; --repo
defaults to the checkout this script lives in:
  ../.venv/bin/python scripts/gen_manifest.py --out src/data/countries.json
"""

import argparse
import json
import re
import sys
from collections.abc import Sequence
from pathlib import Path


def variant_sizes(variants_dir: Path, slug: str) -> list[int]:
    """Long-edge sizes of a slug's hero WebPs on disk, ascending."""
    sizes = []
    for p in variants_dir.glob(f"{slug}-*.webp"):
        m = re.fullmatch(rf"{re.escape(slug)}-(\d+)\.webp", p.name)
        if m:
            sizes.append(int(m.group(1)))
    return sorted(set(sizes))


def records_by_admin(shp: Path) -> dict:
    """ADMIN -> the whole attribute row, from the Natural Earth countries shapefile.

    Takes the shapefile rather than deriving it, because `--repo` is the CHECKOUT and Natural Earth
    lives in the DATA store — two roots that are equal by default and diverge the moment `MAPS_DATA`
    is set. The caller has the pipeline on its path by then and asks the pipeline where its own
    vectors are.

    The whole row rather than the one column each caller wants: two readers of this shapefile is
    two passes and two places to name a column, and `country_config.load_ne_rows` already keeps the
    four fields the frame stages need. Everything the manifest reads off Natural Earth reads it here.
    """
    import shapefile
    reader = shapefile.Reader(str(shp))
    out = {}
    for record in reader.iterRecords():
        fields = record.as_dict()
        out[str(fields.get("ADMIN"))] = fields
    return out


#: Natural Earth's null in a text column — the string, not the number it reads as.
NE_NULL = "-99"

#: The columns holding a spelling a visitor might type, in the order they reach `searchTerms`.
#:
#: THE ISO COLUMNS ARE THE `_EH` VARIANTS ON PURPOSE. Natural Earth's bare `ISO_A2`/`ISO_A3` hold
#: NE_NULL wherever a code is contested or the row is not the ISO entity — France and Norway among
#: them, so "FR" and "NOR" would have matched nothing at all — and where the two columns disagree it
#: is the bare one that carries a worldview: Taiwan reads `CN-TW` there against `TW` here. The test
#: pins both halves of that, because a plausible "simplification" back to the bare pair is silent.
#:
#: `NAME_EN` LOOKS REDUNDANT BESIDE `NAME` AND IS NOT. It disagrees for four countries and two of
#: those are what a visitor actually types: Cabo Verde is "Cape Verde" here, which is still the
#: ordinary English spelling a decade after the rename, and Vatican is "Vatican City" — and that
#: query returns NOTHING without this column, because every term must match and no token in
#: "Vatican" is prefixed by "city".
SEARCH_FIELDS = ("NAME", "NAME_LONG", "NAME_EN", "FORMAL_EN", "NAME_ALT", "ABBREV",
                 "ISO_A2_EH", "ISO_A3_EH")


def search_terms(record: dict, name: str, also: Sequence[str] = ()) -> list[str]:
    """Other spellings of one country — matched by a query, never shown to a reader.

    TWO SOURCES, AND WHICH ONE A NAME BELONGS TO IS DECIDED BY WHETHER NATURAL EARTH PUBLISHES IT.
    The columns are the rule "a way this country is written down": short, long and English names,
    the formal name, the alternative, the abbreviation and the two ISO codes. They cost nothing to
    keep current — a re-cut brings whatever the publisher now says. `also` is authored in
    `config/countries.toml` and nothing refreshes it, so it earns its entries one at a time.

    THE SPLIT WAS MEASURED, NOT ASSUMED. Ten former or partial names were found returning nothing,
    and a sweep of all 137 text columns placed each: only "Burma" has a column home at all
    (`NAME_CIAWF`), and that column is a SORT KEY — it publishes "Korea, South", which nobody types.
    Türkiye and Holland exist only inside 150-string language columns. The remaining seven —
    persia, ceylon, siam, zaire, rhodesia, formosa, england — are in no column anywhere. So
    widening this tuple could never have been the mechanism, whatever it was widened to.

    Deduped by exact string against the display name and against each other, first spelling winning,
    so the order is the field order then `also`, and re-running on unchanged data rewrites unchanged
    bytes. Folding is deliberately NOT done here: the matcher owns it, and a second implementation
    of it in another language would drift where nothing could see.
    """
    terms: list[str] = []
    for value in [str(record.get(field, "")).strip() for field in SEARCH_FIELDS] + \
            [str(value).strip() for value in also]:
        if value and value != NE_NULL and value != name and value not in terms:
            terms.append(value)
    return terms


def spotlight_sizes(variants_dir: Path, slug: str) -> list[int]:
    """Long-edge sizes of a slug's Focus overlays on disk, ascending."""
    sizes = []
    for p in variants_dir.glob(f"{slug}-spotlight-*.webp"):
        m = re.fullmatch(rf"{re.escape(slug)}-spotlight-(\d+)\.webp", p.name)
        if m:
            sizes.append(int(m.group(1)))
    return sorted(set(sizes))


def aspect_of(variants_dir: Path, slug: str, sizes: list[int]) -> float:
    """width/height from the LARGEST variant (accurate framing, no layout shift).

    Read off the largest rather than the smallest because aspect feeds both the CSS `aspect-ratio`
    and the srcset w-descriptors, and a 640-wide variant quantises the ratio ~12x more coarsely
    than the native one.
    """
    if not sizes:
        return 1.5
    import rasterio
    with rasterio.open(variants_dir / f"{slug}-{sizes[-1]}.webp") as im:
        return round(im.width / im.height, 4)


class StaleFiles(Exception):
    """A rendered country with stale files, as `stale_files` defines them."""


#: What rewrites each kind of file, as a refusal names it.
REDO_LADDER = "python -m pipeline.compose.hero_variants --only {slug} --force"
REDO_OVERLAYS = "python -m pipeline.compose.gen_spotlight --only {slug} --force"
REDO_STAMP = "python -m pipeline.compose.downloads stamp --only {slug}"
REDO_RENDER = "`python -m pipeline.batch`, which records what a hero is rendered from"


def stale_files(renders: Path, slug: str, name: str, native: int) -> str | None:
    """The refusal for a rendered country with stale files, naming them and the steps that fix them
    in order, or None when it has none.

    Stale is a rung or overlay older than the master, which holds an earlier render; a file that is
    none of those the master's ladder and stamp produce, left from a render at another size; a
    full-size WebP without the master's shape; and a download file without the credit for `name`.
    A master with no record of its sources, or one rendered since, is refused before any of those,
    since nothing can be stamped for it.
    """
    import rasterio

    from pipeline import attribution
    from pipeline.compose import downloads, hero_variants
    variants = renders / "variants"
    master = renders / "heroes" / f"{slug}.png"
    try:
        attribution.hero_record(master)
    except attribution.HeroRecordError as unstated:
        return f"{slug}: {unstated}; fix: render it through {REDO_RENDER}"
    shape = downloads.png_size(master)
    produced = set(hero_variants.rungs_for(*shape))
    rendered = master.stat().st_mtime_ns
    leftover, older, older_overlays = [], [], []
    for path in sorted(variants.glob(f"{slug}-*")):
        named = re.fullmatch(rf"{re.escape(slug)}-(spotlight-)?(\d+)\.(webp|png)", path.name)
        if named is None:
            continue
        overlay, size, extension = named.group(1), int(named.group(2)), named.group(3)
        if size not in produced or (extension == "png" and size != max(shape)):
            leftover.append(path.name)
        elif extension == "webp" and path.stat().st_mtime_ns < rendered:
            (older_overlays if overlay else older).append(path.name)

    webp = variants / f"{slug}-{native}.webp"
    with rasterio.open(webp) as image:
        reshaped = webp.name not in leftover and (image.width, image.height) != shape
    reladdered = bool(older) or reshaped
    unstamped = [] if reladdered else downloads.unstamped(master, variants, name)

    problems, fixes = [], []
    if leftover:
        problems.append(f"{', '.join(leftover)} match nothing its master produces")
        fixes.append(f"delete {' '.join(leftover)} from {variants}")
    if older or older_overlays:
        problems.append(f"{', '.join(older + older_overlays)} older than its master")
    if reshaped:
        problems.append(f"{webp.name} is not its master's image")
    if unstamped:
        problems.append(f"{' and '.join(path.name for path in unstamped)} not current")
    if reladdered:
        fixes.append(REDO_LADDER.format(slug=slug))
    if older_overlays:
        fixes.append(REDO_OVERLAYS.format(slug=slug))
    if reladdered or unstamped:
        fixes.append(REDO_STAMP.format(slug=slug))
    return f"{slug}: {'; '.join(problems)}; fix: {', then '.join(fixes)}" if problems else None


def download_files(renders: Path, slug: str, name: str, native: int) -> dict:
    """The full-size files a rendered country's page offers for download, as that page states them,
    refused with `stale_files`' reason when it gives one."""
    import rasterio

    from pipeline.compose import downloads
    stale = stale_files(renders, slug, name, native)
    if stale:
        raise StaleFiles(stale)
    master = renders / "heroes" / f"{slug}.png"
    webp, png = downloads.full_size_files(master, renders / "variants")
    with rasterio.open(webp) as image:
        width, height = image.width, image.height
    return dict(width=width, height=height,
                webpBytes=webp.stat().st_size, pngBytes=png.stat().st_size)


def hero_sources(renders: Path, slug: str) -> list[str]:
    """The source keys a rendered country's hero was rendered from, as its record states them."""
    from pipeline import attribution
    return list(attribution.hero_record(renders / "heroes" / f"{slug}.png"))


def country_row(slug: str, resolved: dict, record: dict, renders: Path) -> dict:
    """One country as the manifest publishes it — the payload's whole per-country contract.

    A function rather than a literal inside the loop because these keys are HALF of a contract whose
    other half is `Country` in `web/src/lib/manifest.ts`, and neither language can check the other:
    the JSON is gitignored, so `astro check` type-checks consumers against an interface no build ever
    compares to a real file. The lockstep the header there asks for is a test, and a test needs a
    callable that yields the keys without a render store behind it.
    """
    variants_dir = renders / "variants"
    sizes = variant_sizes(variants_dir, slug)
    spotlight = spotlight_sizes(variants_dir, slug)
    listed_only = not resolved["has_hero"]
    if listed_only and sizes:
        raise ValueError(f"{slug}: listed_only in config/countries.toml, yet the store holds hero "
                         f"variants {sizes}; delete them or move the row to include")
    return dict(
        slug=slug,
        name=resolved["name"],
        admin=resolved["admin"],
        continent=str(record.get("CONTINENT", "")),
        searchTerms=search_terms(record, resolved["admin"], resolved.get("also", ())),
        # The hero's frame, (w, s, e, n) in EPSG:4326, which the globe flies to and the gallery
        # centres on. It carries every frame override in `config/countries.toml`, so a far-flung
        # country flies to the part its hero shows.
        bbox=[round(v, 5) for v in resolved["frame"]],
        aspect=aspect_of(variants_dir, slug, sizes),
        sizes=sizes,
        native=sizes[-1] if sizes else None,
        rendered=bool(sizes),
        listedOnly=listed_only,
        download=download_files(renders, slug, resolved["name"], sizes[-1]) if sizes else None,
        heroSources=hero_sources(renders, slug) if sizes else [],
        hasSpotlight=bool(spotlight),
        spotlightSizes=spotlight,
    )


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", type=Path, default=Path(__file__).resolve().parents[2],
                    help="pipeline repo (has country_config + the asset store)")
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()

    sys.path.insert(0, str(args.repo))  # repo root: country_config uses pipeline.* imports
    from pipeline import naturalearth
    from pipeline.frame.country_config import (
        build_scope,
        load_config,
        load_ne_rows,
        resolve,
    )

    renders = args.repo / "blender/renders"
    cfg = load_config()
    _sf, rows = load_ne_rows()
    scope = build_scope(cfg, rows)
    records = records_by_admin(naturalearth.layer("ne_10m_admin_0_countries"))

    countries, refused = [], []
    for slug in sorted(scope):
        r = resolve(slug, scope[slug], cfg)
        if r is None:              # antimeridian-deferred (Kiribati)
            continue
        try:
            countries.append(country_row(slug, r, records.get(r["admin"], {}), renders))
        except StaleFiles as refusal:
            refused.append(str(refusal))
    if refused:
        sys.exit(f"refusing to write {args.out}: {len(refused)} rendered countries have stale "
                 "files\n  " + "\n  ".join(refused))

    payload = dict(
        count=len(countries),
        rendered=sum(c["rendered"] for c in countries),
        countries=countries,
    )
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, indent=2) + "\n")
    print(f"wrote {args.out}: {payload['count']} countries, "
          f"{payload['rendered']} rendered")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
