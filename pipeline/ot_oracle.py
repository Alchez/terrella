"""Pull an OpenTopography Global DEM clip as an independent fusion oracle.

Our heightfield is GLO-30 land fused with GEBCO bathymetry (fuse_heightfield.py).
Nothing else in the pipeline checks that blend against reality, so a bad clamp at
the shelf or a bathymetry misregistration would render as a plausible-but-wrong
coastline. This helper fetches an *independent* reference over the same frame the
pipeline fuses, so the two can be compared (values, and — eyeballed in QGIS — the
coastline). It is a dev/QA tool, never part of a production sweep.

Reference datasets worth pulling (via the OpenTopography Global DEM API):
  SRTM15Plus      Tozer 2019 fused land+bathymetry, ~15" — the canonical
                  land/sea-fusion oracle; best on COASTS (checks our shelf blend)
  GEBCOIceTopo    GEBCO 2024 ice-surface bathymetry, ~500" — cross-check our GEBCO
  GEBCOSubIceTopo GEBCO sub-ice/bedrock (Antarctica, Greenland differ from IceTopo)
  COP90           GLO-90 — the void-fallback DEM (prototyped for the S. Caucasus);
                  present where GLO-30 Public is withheld, so a same-family check
Any of the API's 17 demtypes is accepted (--dataset); the four above are the ones
that actually tell us something about our fusion.

Per-request area caps are the API's own (getGlobalDem), enforced here so we fail
with the number rather than eating a 400. The API key comes from
OPENTOPOGRAPHY_API_KEY (env), else a .env at the repo root or the frontend worktree.

Idempotent: refuses to overwrite an existing clip; --force or delete it to redo.

Usage:
  ot_oracle.py --country srilanka                       # SRTM15+ over the fused frame
  ot_oracle.py --country armenia --dataset COP90        # GLO-90 over the void
  ot_oracle.py --bounds 79 5 82 10 --dataset GEBCOIceTopo --out /tmp/gebco.tif
"""

import argparse
import math
import os
import shutil
import sys
import urllib.error
import urllib.parse
from pathlib import Path

import rasterio

from pipeline import fetch, paths
from pipeline.frame.country_config import country_work_dir

#: The CHECKOUT, read for one thing only: the gitignored `.env` holding the API key. The clips this
#: writes are DATA and come from `country_work_dir`, which follows `MAPS_DATA`.
ROOT = paths.ROOT
API = "https://portal.opentopography.org/API/globaldem"

# The 17 global rasters the API serves; the commented ones are the useful oracles.
DATASETS = [
    "SRTMGL3", "SRTMGL1", "SRTMGL1_E", "AW3D30", "AW3D30_E",
    "SRTM15Plus",       # land+bathy fusion oracle
    "NASADEM", "COP30",
    "COP90",            # void-fallback DEM
    "EU_DTM", "GEDI_L3",
    "GEBCOIceTopo", "GEBCOSubIceTopo",  # bathymetry cross-check
    "CA_MRDEM_DTM", "CA_MRDEM_DSM", "ANADEM", "GEDTM30",
]

# Per-request area caps (km^2) from the API spec; everything else is the default.
CAP_DEFAULT = 450_000
CAPS = {
    "SRTMGL3": 4_050_000, "COP90": 4_050_000,
    "SRTM15Plus": 125_000_000,
    "GEBCOIceTopo": 125_000_000, "GEBCOSubIceTopo": 125_000_000,
    "GEDI_L3": 500_000_000,
}


def load_api_key() -> str:
    """Env first, then a .env at the repo root or the sibling frontend worktree."""
    if key := os.environ.get("OPENTOPOGRAPHY_API_KEY"):
        return key.strip()
    for env in (ROOT / ".env", ROOT.parent / "maps-frontend/.env"):
        if env.exists():
            for line in env.read_text().splitlines():
                if line.strip().startswith("OPENTOPOGRAPHY_API_KEY="):
                    return line.split("=", 1)[1].strip().strip("\"'")
    sys.exit("no OPENTOPOGRAPHY_API_KEY — export it or put it in a .env "
             "(repo root or the frontend worktree)")


def bbox_area_km2(west: float, south: float, east: float, north: float) -> float:
    """Rough cos-lat rectangle area — enough to enforce the API's caps."""
    mid = math.radians((south + north) / 2)
    return abs(east - west) * 111.320 * math.cos(mid) * abs(north - south) * 110.574


def resolve_frame(slug: str) -> tuple:
    """The exact frame the pipeline fuses for this country (via country_config)."""
    import pipeline.frame.country_config as cc
    cfg = cc.load_config()
    _sf, rows = cc.load_ne_rows()
    scope = cc.build_scope(cfg, rows)
    if slug not in scope:
        sys.exit(f"no country with slug {slug!r} in scope (see country_config --all)")
    resolved = cc.resolve(slug, scope[slug], cfg)
    if resolved is None:
        sys.exit(f"{slug} is antimeridian-skipped — pass --bounds instead")
    return tuple(resolved["frame"])


def download_clip(dataset: str, frame: tuple, out: Path, key: str) -> None:
    """Download the clip to out (crash-safe via a .tmp sibling)."""
    west, south, east, north = frame
    query = urllib.parse.urlencode(dict(
        demtype=dataset, south=south, north=north, west=west, east=east,
        outputFormat="GTiff", API_Key=key))
    tmp = out.with_name(out.name + ".tmp")
    try:
        # key is in the URL — never log it
        with fetch.open_url(f"{API}?{query}", timeout=600) as resp, \
             open(tmp, "wb") as out_file:
            shutil.copyfileobj(resp, out_file)
    except urllib.error.HTTPError as ex:
        body = ex.read().decode("utf-8", "replace")[:400]
        tmp.unlink(missing_ok=True)
        sys.exit(f"OpenTopography API HTTP {ex.code}: {body}")
    with open(tmp, "rb") as probe_file:
        magic = probe_file.read(2)
    if magic not in (b"II", b"MM"):  # not a TIFF — an error slipped through as 200
        body = tmp.read_text("utf-8", "replace")[:400]
        tmp.unlink(missing_ok=True)
        sys.exit(f"not a GeoTIFF — server said: {body}")
    os.replace(tmp, out)


def summarize(path: Path, label: str) -> None:
    with rasterio.open(path) as ds:
        values = ds.read(1, masked=True)
        px = f"{ds.width}x{ds.height}"
        print(f"  {label:22} {px:>11}  min {values.min():8.1f}  "
              f"max {values.max():8.1f}  mean {values.mean():8.1f} m")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    group = ap.add_mutually_exclusive_group(required=True)
    group.add_argument("--country", help="slug per the countries.toml rule")
    group.add_argument("--bounds", nargs=4, type=float, metavar=("W", "S", "E", "N"))
    ap.add_argument("--dataset", default="SRTM15Plus", choices=DATASETS,
                    help="reference dataset (default: SRTM15Plus)")
    ap.add_argument("--out", type=Path,
                    help="output path (default: data/work/<slug>/oracle/<dataset>.tif; "
                         "required with --bounds)")
    ap.add_argument("--force", action="store_true", help="overwrite an existing clip")
    args = ap.parse_args()

    frame = resolve_frame(args.country) if args.country else tuple(args.bounds)
    out = args.out or (country_work_dir(args.country) / "oracle" / f"{args.dataset}.tif")
    if args.bounds is not None and args.out is None:
        ap.error("--bounds needs --out")

    cap = CAPS.get(args.dataset, CAP_DEFAULT)
    area = bbox_area_km2(*frame)
    if area > cap:
        sys.exit(f"frame is {area:,.0f} km^2 — over the {args.dataset} "
                 f"per-request cap of {cap:,} km^2; clip a sub-region with --bounds")

    if out.exists() and not args.force:
        sys.exit(f"{out} exists — --force or delete it to redo")
    out.parent.mkdir(parents=True, exist_ok=True)

    fr = " ".join(f"{value:g}" for value in frame)
    print(f"{args.dataset} over [{fr}]  ({area:,.0f} km^2, cap {cap:,})", flush=True)
    download_clip(args.dataset, frame, out, load_api_key())
    print(f"wrote {out}", flush=True)

    print("\nvalues (reference vs our fusion, if present):")
    summarize(out, f"oracle {args.dataset}")
    if args.country:
        for hf in sorted(country_work_dir(args.country).glob("heightfield_*.tif")):
            summarize(hf, f"fusion {hf.stem.split('_')[-1]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
