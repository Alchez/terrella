"""Emit the site's copy of the credits from the pipeline's registry (src/data/attributions.json).

The language boundary, crossed the only direction it can be: a stage that stamps an archive must
have these in Python, a card that renders one must have them in TypeScript, and the pipeline is the
side that can generate. `tileTokens.json` is the same arrangement.

COMMITTED, unlike `countries.json` beside it. That one is derived from the render store and a clone
cannot rebuild it; this one is derived from source code alone, so leaving it out would make the
site unbuildable from a checkout for no reason.

Run from web/ with the pipeline venv:
  ../.venv/bin/python scripts/gen_attributions.py --out src/data/attributions.json
"""

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from pipeline import attribution, bodies  # noqa: E402


def payload() -> dict:
    """Per body: the cards in order, and the disclaimers its own licences oblige.

    `archives` is for a caller that must stamp a `.pmtiles` without a Python interpreter, so it
    cannot call the composer. Keyed `{body}/{layer}`, the pair every archive address is built from.
    """
    return {
        "archives": {
            f"{name}/{layer}": attribution.for_archive(body, layer)
            for name, body in sorted(bodies.BODIES.items())
            for layer in attribution.ARCHIVE_LAYERS
        },
        "bodies": {
            name: {
                "sources": [
                    {
                        "name": source.name,
                        "href": source.href,
                        "role": source.role,
                        "license": source.licence,
                        "attribution": source.page_attribution(),
                    }
                    for source in attribution.on_the_page(body)
                ],
                "legal": list(attribution.CREDITS[name].legal),
            }
            for name, body in sorted(bodies.BODIES.items())
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").split("\n")[0])
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    args.out.write_text(json.dumps(payload(), indent=2, ensure_ascii=False) + "\n",
                        encoding="utf-8")
    written = payload()
    cards = sum(len(body["sources"]) for body in written["bodies"].values())
    print(f"wrote {args.out} ({cards} source cards across {len(written['bodies'])} bodies, "
          f"{len(written['archives'])} archive credits)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
