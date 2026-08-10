"""Generate Mars's named-feature index (src/lib/featureIndex.json) — the catalogue as data.

The globe already learns a feature's name, type, etymology and diameter from the vector tile under
the pointer. What a tile cannot answer is anything about a feature that is NOT under the pointer:
where Gale is when you have never seen it, or that it exists at all. That is this file — every named
feature in one list, so a search box has something to match against and a chosen name has somewhere
to fly to.

IT READS THE FOLDED LABEL ANCHORS, NOT THE DBF, AND THAT IS THE WHOLE REASON THIS IS SHORT. The
gazetteer's centres are east-positive 0-360 while its outlines span -180..+360.34, and every consumer
that mixes the two conventions loses the features crossing the seam. `features_geojson.label_points`
already folded them once and `fold_longitude` owns the arithmetic; reading the DBF here would make
this a SECOND place that knows how, free to drift. So the anchors are the source, and the only
transformation left is reshaping for the web.

THERE ARE NO BOUNDS HERE, BECAUSE THE FLY-TO TARGET IS A CENTRE AND A DIAMETER. Framing a feature
means choosing the zoom at which its diameter reads, which is the inverse of the rule
`featureTargeting` already applies to decide whether it can be pointed at — so both directions share
one notion of size, and a bounding box would introduce a second. It also keeps the seam out of this
file entirely: a scalar centre folds, a box straddling the seam does not.

A ZERO DIAMETER BECOMES NULL, MATCHING WHAT THE TILES DO. The gazetteer ships `0.000000000000000`
for two features (Xanthe Dorsa, Candor Chaos); the tile cut drops a falsy value, so `candidateFrom`
sees no diameter and calls them unpickable. Carrying a literal 0 here instead would make them
pickable-by-search and framed at zero kilometres — one catalogue disagreeing with itself about which
features have a size.

THE OUTPUT IS TRACKED IN GIT, WHICH `src/data/countries.json` IS NOT, AND THE DIFFERENCE IS WHAT THE
INPUT IS. The gallery manifest describes whichever heroes happen to be rendered on this machine, so
it cannot be committed without committing a machine's state. This index derives from an archive
pinned by member digest — the same bytes anywhere, changing only when the IAU adopts a name. Being
tracked is what lets `astro check` and the search tests run against the real 1,920 rows on a clean
checkout, with no absent-file branch in any consumer.

That is also why no recipe sidecar sits beside it: `tests/test_feature_index.py` regenerates the
index and compares it to the committed bytes, which catches a changed field list or a changed
rounding the way a recorded recipe would, and additionally catches the file being edited by hand.

Run from web/ with the *pipeline* venv (it imports pipeline.compose):
  ../.venv/bin/python scripts/gen_feature_index.py --out src/lib/featureIndex.json
"""

import argparse
import json
import sys
from pathlib import Path
from typing import Any

#: Decimal places of the diameter in km, i.e. metres. The gazetteer publishes fifteen, which is
#: noise dressed as precision and makes every regeneration a noisy diff. A quantisation rather than
#: a decision, the same distinction `features_geojson.COORDINATE_PRECISION` draws for vertices.
DIAMETER_PRECISION = 3


def record_from(anchor: dict[str, Any]) -> dict[str, Any]:
    """One label anchor as an index row.

    `longitude`/`latitude` are already folded and quantised by the producer upstream, so they are
    copied rather than recomputed — recomputing is how the two conventions get mixed again.
    """
    properties = anchor["properties"]
    longitude, latitude = anchor["geometry"]["coordinates"]
    diameter = float(properties.get("diameter") or 0.0)
    return {
        "name": properties["name"],
        "cleanName": properties["clean_name"],
        "type": properties["type"],
        "origin": properties["origin"],
        "diameterKm": round(diameter, DIAMETER_PRECISION) if diameter > 0 else None,
        "longitude": longitude,
        "latitude": latitude,
    }


def index_from(anchors: dict[str, Any]) -> list[dict[str, Any]]:
    """The whole index for a label-anchor collection, deduplicated and in its published order.

    THE GAZETTEER PUBLISHES ONE FEATURE TWICE. Both Bohar records sit in the `poly` layer and agree
    on every attribute the archive carries — name, code, type, diameter, centre, bounds, approval,
    quadrangle — so they are one crater entered twice rather than two things sharing a name. Two
    identical rows here would put "Bohar" in a search list twice with the same text under both, and
    leave a chooser to build for a choice that does not exist.

    COLLAPSED ON THE WHOLE ROW RATHER THAN ON THE NAME, which is the distinction that keeps this
    safe. Rows agreeing in every field are one feature and one survives; two features that genuinely
    shared a name would differ somewhere and both stay, at which point `featureIndex.test.ts` fails
    on the repeat and someone decides what a search list should show. Collapsing by name would make
    that silent, and the difference only shows up in an edition nobody has seen yet.

    SORTED BY NAME AND THEN BY POSITION so the output is a function of the data alone. The committed
    file is checked by regenerating it, which is only meaningful while nothing about the input's
    order can reach the output.
    """
    unique: dict[tuple[Any, ...], dict[str, Any]] = {}
    for anchor in anchors["features"]:
        record = record_from(anchor)
        unique.setdefault(tuple(sorted(record.items(), key=lambda item: item[0])), record)
    records = list(unique.values())
    records.sort(key=lambda row: (row["name"], row["longitude"], row["latitude"]))
    return records


def main() -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").split("\n")[0])
    parser.add_argument("--repo", type=Path, default=Path(__file__).resolve().parents[2],
                        help="pipeline repo (has the composed gazetteer)")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()

    sys.path.insert(0, str(args.repo))  # repo root: pipeline.compose uses pipeline.* imports
    from pipeline.compose import features_geojson

    if not features_geojson.LABELS.exists():
        sys.exit(f"missing {features_geojson.LABELS} — run "
                 f"pipeline.compose.features_geojson first")
    anchors = json.loads(features_geojson.LABELS.read_text(encoding="utf-8"))
    records = index_from(anchors)

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(records, indent=2, ensure_ascii=False) + "\n",
                        encoding="utf-8")
    sized = sum(1 for row in records if row["diameterKm"] is not None)
    print(f"wrote {args.out}: {len(records)} features, {sized} with a diameter")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
