#!/usr/bin/env python3
"""Compute a country's render frame from its Natural Earth bounding box.

The frame is the lon/lat window every downstream stage shares: the fusion
window (fuse_heightfield --bounds), the projection center (render_prep
--frame), and therefore the extent of the finished hero. Rule: take the
country's whole-geometry bbox from ne_10m_admin_0_countries, pad every side
by --pad-pct of the larger span, and round outward to 0.1 degree so frames
are tidy to quote and diff. Formula rationale: docs/framing-math.md.

Prints the padded frame as "W S E N" for pasting into the downstream CLIs —
the batch runner will automate that handoff; for now it is a human step.

Known limitation (accepted until the per-country override item): the bbox
spans the country's every polygon, so far-flung territories explode the
frame — France reaches French Guiana, the Netherlands reaches Curaçao.
Compact countries are unaffected. Antimeridian crossers (Fiji, Russia, NZ)
are wrong for the same reason and are their own Phase 1 line item.

Usage:
  frame_country.py --country Nepal
  frame_country.py --country "Sri Lanka" --pad-pct 8
"""

import argparse
import math
import sys
from pathlib import Path

import shapefile

NE_DIR = Path(__file__).resolve().parent.parent / "data/raw/naturalearth"


def country_bbox(shp_path, name):
    """Whole-geometry bbox (W, S, E, N) of the ADMIN-matched country."""
    sf = shapefile.Reader(str(shp_path))
    candidates = []
    for sr in sf.iterShapeRecords():
        if sr.record is None or sr.shape is None:  # spec allows null shapes
            continue
        rec = sr.record.as_dict()
        if "ADMIN" not in rec:
            sys.exit(f"ADMIN field missing in {shp_path.name}; "
                     f"fields are {list(rec)}")
        admin = str(rec["ADMIN"])
        if admin.lower() == name.lower():
            return admin, tuple(sr.shape.bbox)
        if name.lower() in admin.lower():
            candidates.append(admin)
    hint = f"; close matches: {candidates}" if candidates else ""
    sys.exit(f"no ADMIN == {name!r} in {shp_path.name}{hint}")


def pad_frame(bbox, pad_pct):
    """Pad all sides by pad_pct of the larger span; round outward to 0.1°,
    clamped to the world. The clamp matters near the edges: an island at
    179.9°E pads to 180.1° and would cross the antimeridian (Tuvalu)."""
    w, s, e, n = bbox
    pad = pad_pct / 100.0 * max(e - w, n - s)
    return (max(-180.0, math.floor((w - pad) * 10) / 10),
            max(-90.0, math.floor((s - pad) * 10) / 10),
            min(180.0, math.ceil((e + pad) * 10) / 10),
            min(90.0, math.ceil((n + pad) * 10) / 10))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--country", required=True,
                    help="ADMIN name in ne_10m_admin_0_countries "
                         "(case-insensitive)")
    ap.add_argument("--ne-dir", type=Path, default=NE_DIR)
    ap.add_argument("--pad-pct", type=float, default=5.0)
    args = ap.parse_args()

    shp = args.ne_dir / "ne_10m_admin_0_countries/ne_10m_admin_0_countries.shp"
    admin, bbox = country_bbox(shp, args.country)
    frame = pad_frame(bbox, args.pad_pct)
    print(f"country: {admin}")
    print(f"bbox:    W {bbox[0]:.4f}  S {bbox[1]:.4f}  "
          f"E {bbox[2]:.4f}  N {bbox[3]:.4f}")
    print(f"spans:   lon {bbox[2] - bbox[0]:.2f}°  lat {bbox[3] - bbox[1]:.2f}°"
          f"  (pad = {args.pad_pct:g}% of the larger)")
    print(f"frame:   {frame[0]:g} {frame[1]:g} {frame[2]:g} {frame[3]:g}")


if __name__ == "__main__":
    main()
