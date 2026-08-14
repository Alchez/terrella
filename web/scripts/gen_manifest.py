"""Generate the Tier-1 gallery manifest (src/data/countries.json).

Bridges the render pipeline to the frontend: it reads the in-scope country list
(and proper display names) from the pipeline's country_config, then scans the
hero WebP variant store to see which countries have been rendered and at what
sizes. Re-run it after a render + hero_variants pass to refresh the gallery.

It also carries the other spellings of each country, which is the one payload
field derived from neither the config nor the store — see `search_terms`.

Run from web/ with the *pipeline* venv (it imports country_config → geopandas/rasterio);
--repo defaults to the checkout this script lives in:
  ../.venv/bin/python scripts/gen_manifest.py --out src/data/countries.json
"""

import argparse
import json
import re
import sys
from collections.abc import Sequence
from pathlib import Path


def variant_sizes(variants_dir: Path, slug: str) -> list[int]:
    """Long-edge sizes present for a slug, e.g. [1920, 3840, 7680]."""
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


def border_sizes(variants_dir: Path, slug: str) -> list[int]:
    """Long-edge sizes of the standalone border layer, e.g. [1920, 7680]."""
    sizes = []
    for p in variants_dir.glob(f"{slug}-border-*.png"):
        m = re.fullmatch(rf"{re.escape(slug)}-border-(\d+)\.png", p.name)
        if m:
            sizes.append(int(m.group(1)))
    return sorted(set(sizes))


def spotlight_sizes(variants_dir: Path, slug: str) -> list[int]:
    """Long-edge sizes of the subject-spotlight overlay (dims neighbours + strokes
    the subject boundary), e.g. [1920, 3840, 7680]."""
    sizes = []
    for p in variants_dir.glob(f"{slug}-spotlight-*.webp"):
        m = re.fullmatch(rf"{re.escape(slug)}-spotlight-(\d+)\.webp", p.name)
        if m:
            sizes.append(int(m.group(1)))
    return sorted(set(sizes))


def aspect_of(variants_dir: Path, slug: str, sizes: list[int]) -> float:
    """width/height from the LARGEST variant (accurate framing, no layout shift).

    Read off the largest rather than the smallest because aspect feeds both the CSS
    `aspect-ratio` and the srcset w-descriptors, and a 640-wide variant quantises the ratio ~12x
    more coarsely than the native one. It used to read sizes[0] because the ladder's floor was
    1920; adding rungs beneath that would have silently coarsened every country's framing.
    """
    if not sizes:
        return 1.5
    import rasterio
    with rasterio.open(variants_dir / f"{slug}-{sizes[-1]}.webp") as im:
        return round(im.width / im.height, 4)


def country_row(slug: str, resolved: dict, record: dict, variants_dir: Path) -> dict:
    """One country as the manifest publishes it — the payload's whole per-country contract.

    A function rather than a literal inside the loop because these keys are HALF of a contract whose
    other half is `Country` in `web/src/lib/manifest.ts`, and neither language can check the other:
    the JSON is gitignored, so `astro check` type-checks consumers against an interface no build ever
    compares to a real file. The lockstep the header there asks for is a test, and a test needs a
    callable that yields the keys without a render store behind it.
    """
    sizes = variant_sizes(variants_dir, slug)
    border = border_sizes(variants_dir, slug)
    spotlight = spotlight_sizes(variants_dir, slug)
    return dict(
        slug=slug,
        name=resolved["admin"],
        continent=str(record.get("CONTINENT", "")),
        searchTerms=search_terms(record, resolved["admin"], resolved.get("also", ())),
        # Authored (w,s,e,n) EPSG:4326 hero frame — the globe's fly-to target.
        # Same framing as the hero renders, so overrides (France→metropolitan,
        # US/Chile/Russia) already fix the far-flung multipolygon cases that a
        # raw country bbox would frame badly.
        bbox=[round(v, 5) for v in resolved["frame"]],
        aspect=aspect_of(variants_dir, slug, sizes),
        sizes=sizes,
        native=sizes[-1] if sizes else None,
        rendered=bool(sizes),
        hasBorder=bool(border),
        borderSizes=border,
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

    variants_dir = args.repo / "blender/renders/variants"
    cfg = load_config()
    _sf, rows = load_ne_rows()
    scope = build_scope(cfg, rows)
    records = records_by_admin(naturalearth.layer("ne_10m_admin_0_countries"))

    countries = []
    for slug in sorted(scope):
        r = resolve(slug, scope[slug], cfg)
        if r is None:              # antimeridian-deferred (Kiribati)
            continue
        countries.append(country_row(slug, r, records.get(r["admin"], {}), variants_dir))

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
