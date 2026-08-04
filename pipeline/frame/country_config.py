#!/usr/bin/env python3
"""Resolve config/countries.toml into per-country pipeline parameters.

The config is the committed source of truth for scope (which Natural Earth
admin-0 rows get heroes), frame overrides, and resolution/fusion knobs.
This resolver is read-only glue between it and the stages:

  --country <slug>   one country: frame, projected aspect, warp/hero sizes,
                     fusion choice, data preflights (GLO-30 tiles held?
                     GEBCO window covers the frame? committed pin?), and
                     the exact stage commands to run.
  --emit-pin         with --country: copy config/frames/<slug>.json into
                     data/work/<slug>/render/frame.json. render_prep never
                     overwrites an existing frame.json, so the emitted pin
                     wins — the existing pinning mechanism, unchanged.
  --all              audit table over the whole scope; the batch runner's
                     future input and today's verification oracle.

Sizes printed here are previews: render_prep derives the real grid from the
warped raster and writes frame.json, which stays authoritative (integer
grids vs float aspects — the hero resolution may differ by a pixel). The
fusion choice however IS decided here: "auto" picks 1" source iff the 3"
mosaic would need upsampling to fill the warp grid (3" pixels across the
frame < warp width).

Fail-loudly stance: unknown config keys, unresolvable names, a bbox that
touches both antimeridian edges without a status marker, and a frame
outside the held GEBCO window are errors, not warnings — a typo that
silently reverts to a default renders a wrong hero, not a crash.

Scope, slug, and per-key semantics are documented in countries.toml.

Usage:
  country_config.py --country bhutan
  country_config.py --country india --emit-pin
  country_config.py --all
"""

import argparse
import difflib
import filecmp
import math
import re
import shutil
import sys
import tomllib
from pathlib import Path

import numpy as np
import rasterio
import shapefile
from rasterio.warp import transform_bounds

from pipeline import bodies, naturalearth, paths
from pipeline.acquire.download_glo30 import (TILE_LIST, in_extent,
                                             parse_tile_name, tile_files)
from pipeline.frame.frame_country import pad_frame
from pipeline.fuse.fuse_heightfield import GEBCO
from pipeline.render.render_prep import aea_crs

#: The CHECKOUT. Both paths below are TRACKED config, so they follow the repo and not the data
#: store — the one place in this module where `paths.ROOT` is the right root.
ROOT = paths.ROOT
CONFIG_PATH = ROOT / "config/countries.toml"
PIN_DIR = ROOT / "config/frames"
BLENDER = paths.BLENDER


def country_work_dir(slug: str) -> Path:
    """Everything the hero pipeline builds for one country, in the data store.

    THE HOME FOR A CONCEPT THAT HAD NINE SPELLINGS across five modules — the stage list that
    prints the pipeline, the runner that executes it, the pruner that reclaims it, the oracle that
    validates it, and the two overlay passes that read its render dir. Every one of them was
    correct, because each resolved to the same directory on a machine with `MAPS_DATA` unset; the
    duplication is invisible until it isn't.

    Routed through `bodies.work_dir` rather than composed here, so a country's tree sits under the
    same root as every other per-body stage and nests automatically if a second body ever grows
    regions of its own. Earth's prefix is empty, so today this is exactly `<store>/work/<slug>`.
    """
    return bodies.work_dir(bodies.EARTH, slug)


def country_render_dir(slug: str) -> Path:
    """The warp/render subdirectory `render_prep` fills and the hero stages read.

    Named because it is the argument five commands pass to each other — the point where a typo
    stops being a wrong path and starts being a stage silently reading an empty directory.
    """
    return country_work_dir(slug) / "render"

DEFAULT_KEYS = {"pad_pct", "hero_long_edge", "warp_long_edge", "fusion",
                "sky_view_strength", "resolution_floor_m"}
COUNTRY_KEYS = {"admin", "frame", "hero_long_edge", "fusion", "status", "notes",
                "sky_view_strength", "resolution_floor_m"}
FUSION_RES = {"1s": 1, "3s": 3}
FAR_FLUNG_FRACTION = 0.25  # main part below this share of a bbox axis


def slugify(admin: str) -> str:
    """countries.toml slug rule: lowercase, non-alphanumerics stripped."""
    return re.sub(r"[^a-z0-9]", "", admin.lower())


def _valid_strength(value) -> bool:
    """sky_view_strength must be a plain number in [0, 1] (reject bool)."""
    return (isinstance(value, (int, float)) and not isinstance(value, bool)
            and 0.0 <= value <= 1.0)


def _valid_floor(value) -> bool:
    """resolution_floor_m must be a plain number in [0, 1000] m (reject bool)."""
    return (isinstance(value, (int, float)) and not isinstance(value, bool)
            and 0.0 <= value <= 1000.0)


def load_config() -> dict:
    """Parse countries.toml; reject unknown keys and malformed values."""
    if not CONFIG_PATH.exists():
        sys.exit(f"{CONFIG_PATH} not found")
    cfg = tomllib.loads(CONFIG_PATH.read_text())
    bad = []
    if extra := set(cfg) - {"defaults", "scope", "countries"}:
        bad.append(f"unknown top-level tables: {sorted(extra)}")
    if extra := set(cfg.get("defaults", {})) - DEFAULT_KEYS:
        bad.append(f"[defaults]: unknown keys {sorted(extra)}")
    if (sv := cfg.get("defaults", {}).get("sky_view_strength")) is not None \
            and not _valid_strength(sv):
        bad.append("[defaults]: sky_view_strength must be a number in [0, 1]")
    if (rf := cfg.get("defaults", {}).get("resolution_floor_m")) is not None \
            and not _valid_floor(rf):
        bad.append("[defaults]: resolution_floor_m must be a number in [0, 1000]")
    if extra := set(cfg.get("scope", {})) - {"exclude", "include"}:
        bad.append(f"[scope]: unknown keys {sorted(extra)}")
    for slug, tbl in cfg.get("countries", {}).items():
        where = f"[countries.{slug}]"
        if extra := set(tbl) - COUNTRY_KEYS:
            bad.append(f"{where}: unknown keys {sorted(extra)}")
        if (status := tbl.get("status")) not in (None, "antimeridian"):
            bad.append(f"{where}: unknown status {status!r}")
        if (fusion := tbl.get("fusion")) not in (None, *FUSION_RES):
            bad.append(f"{where}: fusion must be one of {sorted(FUSION_RES)}")
        if (sv := tbl.get("sky_view_strength")) is not None \
                and not _valid_strength(sv):
            bad.append(f"{where}: sky_view_strength must be a number in [0, 1]")
        if (rf := tbl.get("resolution_floor_m")) is not None \
                and not _valid_floor(rf):
            bad.append(f"{where}: resolution_floor_m must be a number in [0, 1000]")
        if "frame" in tbl:
            if tbl.get("status") == "antimeridian":
                bad.append(f"{where}: frame + antimeridian status contradict")
            west, south, east, north = tbl["frame"]
            if not (-180 <= west < east <= 180 and -90 <= south < north <= 90):
                bad.append(f"{where}: malformed frame {tbl['frame']}")
    if bad:
        sys.exit(f"{CONFIG_PATH.name} is invalid:\n  " + "\n  ".join(bad))
    return cfg


def load_ne_rows():
    """One pass over the NE shapefile: (admin, sovereignt, bbox, shape index).

    The Reader is returned too and kept open: geometry (polygon parts for
    the far-flung check) is re-read lazily by index, so --country never
    pays for parsing the whole world's rings."""
    shp = naturalearth.layer("ne_10m_admin_0_countries")
    if not shp.exists():
        sys.exit(f"{shp} not found — run pipeline/acquire/download_naturalearth.sh")
    sf = shapefile.Reader(str(shp))
    rows = []
    for idx, sr in enumerate(sf.iterShapeRecords()):
        if sr.record is None or sr.shape is None:
            continue
        rec = sr.record.as_dict()
        rows.append(dict(admin=str(rec["ADMIN"]), sov=str(rec["SOVEREIGNT"]),
                         bbox=tuple(sr.shape.bbox), idx=idx))
    return sf, rows


def build_scope(cfg, rows) -> dict[str, dict]:
    """slug -> NE row for every in-scope country, cross-validated loudly."""
    by_admin = {row["admin"]: row for row in rows}
    strict = {row["admin"] for row in rows if row["admin"] == row["sov"]}
    bad = []
    for name in cfg["scope"]["exclude"]:
        if name not in strict:
            bad.append(f"exclude {name!r}: not a strict-selector ADMIN")
    for name in cfg["scope"]["include"]:
        if name not in by_admin:
            bad.append(f"include {name!r}: no such ADMIN")
        elif name in strict:
            bad.append(f"include {name!r}: already passes the strict selector")
    # Only valid includes join the scope; an unknown one is already recorded in
    # `bad` above and must reach the clean sys.exit below, not KeyError here.
    admins = ((strict - set(cfg["scope"]["exclude"]))
              | {name for name in cfg["scope"]["include"] if name in by_admin})
    # hand-picked slugs: [countries.<slug>] admin = "..." binds slug -> ADMIN
    bound = {slug: tbl["admin"] for slug, tbl in cfg.get("countries", {}).items()
             if "admin" in tbl}
    for slug, admin in bound.items():
        if admin not in admins:
            bad.append(f"[countries.{slug}]: admin {admin!r} is not in scope")
    scope = {}
    rebound = {a: s for s, a in bound.items()}
    for admin in sorted(admins):
        slug = rebound.get(admin, slugify(admin))
        if slug in scope:
            bad.append(f"slug collision: {slug!r} from {admin!r} "
                       f"and {scope[slug]['admin']!r}")
        scope[slug] = by_admin[admin]
    for slug in cfg.get("countries", {}):
        if slug not in scope:
            bad.append(f"[countries.{slug}]: slug matches no in-scope country")
    if bad:
        sys.exit(f"{CONFIG_PATH.name} vs Natural Earth:\n  " + "\n  ".join(bad))
    return scope


def resolve(slug: str, row: dict, cfg: dict) -> dict | None:
    """All derived parameters for one country; None if antimeridian-skipped."""
    defaults, tbl = cfg["defaults"], cfg.get("countries", {}).get(slug, {})
    if tbl.get("status") == "antimeridian":
        return None
    west, south, east, north = row["bbox"]
    # A frame override is authoritative, so a raw bbox that spans 180 (the
    # country has parts on both sides) is fine — the override frame does not.
    if "frame" not in tbl and west <= -179.99 and east >= 179.99:
        sys.exit(f"{slug}: bbox spans the antimeridian but countries.toml "
                 f"has no status marker — mark it or add a frame override")
    frame = tuple(tbl["frame"]) if "frame" in tbl \
        else pad_frame(row["bbox"], defaults["pad_pct"])
    left, bottom, right, top = transform_bounds(
        "EPSG:4326", aea_crs(frame), *frame, densify_pts=64)
    aspect = (top - bottom) / (right - left)  # projected h/w
    warp_long = defaults["warp_long_edge"]
    warp_w = round(warp_long / aspect) if aspect > 1 else warp_long
    hero_long = tbl.get("hero_long_edge", defaults["hero_long_edge"])
    hero = (round(hero_long / aspect), hero_long) if aspect > 1 \
        else (hero_long, round(hero_long * aspect))
    fusion = tbl.get("fusion", defaults["fusion"])
    src_px_3s = round((frame[2] - frame[0]) * 1200)  # 3"/px = 1200 px/degree
    if fusion == "auto":
        fusion = "1s" if src_px_3s < warp_w else "3s"
    pin = PIN_DIR / f"{slug}.json"
    sky_view_strength = tbl.get("sky_view_strength",
                                defaults["sky_view_strength"])
    resolution_floor_m = tbl.get("resolution_floor_m",
                                 defaults["resolution_floor_m"])
    return dict(
        slug=slug, admin=row["admin"], frame=frame,
        frame_overridden="frame" in tbl, notes=tbl.get("notes"),
        aspect=aspect, extent_w_m=right - left,
        warp=(warp_w, round(warp_w * aspect)), hero=hero,
        hero_long_overridden="hero_long_edge" in tbl, hero_long=hero_long,
        fusion=fusion, fusion_overridden="fusion" in tbl, src_px_3s=src_px_3s,
        sky_view_strength=sky_view_strength,
        sky_view_strength_overridden="sky_view_strength" in tbl,
        resolution_floor_m=resolution_floor_m,
        resolution_floor_m_overridden="resolution_floor_m" in tbl,
        pin=pin if pin.exists() else None,
    )


def main_part_fraction(sf, row) -> float:
    """Smaller-axis bbox share of the largest polygon part vs the whole bbox.

    Shoelace area in degrees, cos(lat)-weighted so a high-latitude part is
    not inflated relative to the mainland. Below FAR_FLUNG_FRACTION the
    whole-bbox frame is mostly empty ocean — informational under the
    whole-bbox policy; the catastrophic ones carry frame overrides."""
    shape = sf.shape(row["idx"])
    pts = np.asarray(shape.points)
    starts = list(shape.parts) + [len(pts)]
    best_area, best_bb = -1.0, (0.0, 0.0, 0.0, 0.0)
    for start, end in zip(starts, starts[1:]):
        x_coords, y_coords = pts[start:end, 0], pts[start:end, 1]
        area = 0.5 * abs(np.sum(
            x_coords * np.roll(y_coords, -1) - np.roll(x_coords, -1) * y_coords))
        area *= math.cos(math.radians(float(y_coords.mean())))
        if area > best_area:
            best_area = area
            best_bb = (x_coords.min(), y_coords.min(),
                       x_coords.max(), y_coords.max())
    west, south, east, north = row["bbox"]
    best_west, best_south, best_east, best_north = best_bb
    return min((best_east - best_west) / (east - west),
               (best_north - best_south) / (north - south))


def fmt_frame(frame) -> str:
    return " ".join(f"{value:g}" for value in frame)


def preflight_glo30(frame):
    """(tiles needed, tiles missing) per the bucket's land-tile index.

    tileList.txt lists land tiles only, so ocean cells never count as
    missing; a needed tile is held iff both its DEM and WBM files exist."""
    if not TILE_LIST.exists():
        sys.exit(f"{TILE_LIST} not found — run python -m pipeline.acquire.download_glo30 "
                 f"once (any extent) to fetch the bucket index")
    needed = [name for name in TILE_LIST.read_text().split()
              if in_extent(*parse_tile_name(name), frame)]
    missing = [name for name in needed
               if not all(dest.exists() for _, dest in tile_files(name))]
    return needed, missing


def preflight_gebco(frame) -> str | None:
    """None if the GEBCO mosaic covers the frame, else the failure."""
    if not GEBCO.exists():
        return f"{GEBCO} not found — run python -m pipeline.acquire.download_gebco"
    with rasterio.open(GEBCO) as gebco:
        bounds = gebco.bounds
    west, south, east, north = frame
    if (bounds.left <= west and bounds.bottom <= south
            and east <= bounds.right and north <= bounds.top):
        return None
    def fmt(value):  # geotiff transforms carry float noise: -7.1e-15 for 0
        return f"{round(value, 6) + 0.0:g}"
    return (f"frame outside the GEBCO mosaic "
            f"({fmt(bounds.left)}..{fmt(bounds.right)}E "
            f"{fmt(bounds.bottom)}..{fmt(bounds.top)}N) — "
            f"a frame reaching past ±180° needs the antimeridian item")


def stage_commands(resolved: dict) -> list[str]:
    """The exact pipeline for one resolved country, in run order."""
    fr = fmt_frame(resolved["frame"])
    tag = f"{FUSION_RES[resolved['fusion']]}s"
    # ABSOLUTE, from the store. These strings are handed to `subprocess` with `cwd` set to the
    # checkout, so a relative `data/work/…` resolved against the checkout no matter where the store
    # actually was — which put stage 3 in the incoherent position of READING its mosaics through
    # `MAPS_DATA` and WRITING its output beside the source tree. The checkout-relative paths further
    # down (`pipeline/…`, `blender/…`) stay relative on purpose: those really are checkout paths.
    work = country_work_dir(resolved["slug"])
    rd = country_render_dir(resolved["slug"])
    prep = (f"python -m pipeline.render.render_prep --heightfield {work}/heightfield_{tag}.tif"
            f" --mask {work}/oceanmask_{tag}.tif"
            f" --watermask {work}/watermask_{tag}.tif"
            f" --frame {fr} --outdir {rd} --width {resolved['warp'][0]}"
            f" --floor-m {resolved['resolution_floor_m']}")
    if resolved["hero_long_overridden"]:
        prep += f" --hero-long-edge {resolved['hero_long']}"
    return [
        f"python -m pipeline.acquire.download_glo30 --extent {fr}",
        "bash pipeline/fuse/build_mosaics.sh",
        f"python -m pipeline.fuse.fuse_heightfield --bounds {fr}"
        f" --res-arcsec {FUSION_RES[resolved['fusion']]} --outdir {work}",
        prep,
        f"python -m pipeline.render.snow_mask --render-dir {rd}",
        f"python -m pipeline.render.lake_mask --render-dir {rd}",
        f"{BLENDER} -b --python pipeline/render/scene_build.py --"
        f" --render-dir {rd} --out blender/{resolved['slug']}_hero.blend"
        f" --render blender/renders/heroes/{resolved['slug']}.png",
    ]


def print_country(sf, scope, cfg, slug: str, emit_pin: bool) -> int:
    if slug not in scope:
        hints = difflib.get_close_matches(slug, scope, n=3, cutoff=0.5)
        by_admin = {row["admin"].lower(): other_slug
                    for other_slug, row in scope.items()}
        if slug.lower() in by_admin:
            hints = [by_admin[slug.lower()]]
        hint = f"; did you mean {', '.join(hints)}?" if hints else ""
        sys.exit(f"no country with slug {slug!r} in scope{hint}")
    row = scope[slug]
    resolved = resolve(slug, row, cfg)
    if resolved is None:
        print(f"{row['admin']} is marked status=antimeridian — a deferred "
              f"special-case with no representative non-crossing frame "
              f"(see countries.toml notes); skipping resolution")
        return 0

    src = "override (countries.toml)" if resolved["frame_overridden"] \
        else f"computed (bbox + {cfg['defaults']['pad_pct']:g}% pad)"
    print(f"country: {resolved['admin']}  (slug: {slug})")
    print(f"frame:   {fmt_frame(resolved['frame'])}   [{src}]")
    if resolved["notes"]:
        print(f"notes:   {resolved['notes']}")
    print(f"aspect:  {resolved['aspect']:.3f} h/w (projected)")
    print(f"warp:    {resolved['warp'][0]} x {resolved['warp'][1]} px"
          f"  (~{resolved['extent_w_m'] / resolved['warp'][0]:.0f} m/px)")
    print(f"hero:    {resolved['hero'][0]} x {resolved['hero'][1]} px  (preview — "
          f"frame.json is authoritative)")
    fsrc = "override" if resolved["fusion_overridden"] else \
        (f"auto: {resolved['src_px_3s']} 3\" px across < warp {resolved['warp'][0]}"
         if resolved["fusion"] == "1s" else
         f"auto: {resolved['src_px_3s']} 3\" px across >= warp {resolved['warp'][0]}")
    print(f"fusion:  {resolved['fusion']}  [{fsrc}]")
    print(f"pin:     {resolved['pin'] if resolved['pin'] else 'none committed'}")
    if not resolved["frame_overridden"]:
        frac = main_part_fraction(sf, row)
        if frac < FAR_FLUNG_FRACTION:
            print(f"WARNING: far-flung — main landmass spans {frac:.0%} of a "
                  f"bbox axis; whole-bbox policy applies (add a frame "
                  f"override in countries.toml if catastrophic)")

    print("\ndata preflights:")
    needed, missing = preflight_glo30(resolved["frame"])
    state = "all held" if not missing else f"{len(missing)} MISSING (stage 1 fetches)"
    print(f"  GLO-30: {len(needed)} land tiles in frame — {state}")
    gebco_err = preflight_gebco(resolved["frame"])
    print(f"  GEBCO:  {'window covers the frame' if not gebco_err else gebco_err}")

    if emit_pin:
        print()
        do_emit_pin(slug, resolved)

    print("\nstages (repo root, venv active):")
    print("  0. (once per machine, skips if data present) "
          "bash pipeline/acquire/download_naturalearth.sh && "
          "python -m pipeline.acquire.download_gebco")
    if gebco_err:
        print("     ^ complete the bootstrap above; then this country resolves"
              if "download_gebco" in gebco_err else
              f"     (this frame still won't fuse: {gebco_err})")
        return 1
    for index, cmd in enumerate(stage_commands(resolved), 1):
        print(f"  {index}. {cmd}")
    return 0


def do_emit_pin(slug: str, resolved: dict):
    dest = country_render_dir(slug) / "frame.json"
    if not resolved["pin"]:
        sys.exit(f"no committed pin at {PIN_DIR / f'{slug}.json'}")
    if dest.exists():
        if filecmp.cmp(resolved["pin"], dest, shallow=False):
            print(f"pin already emitted: {dest} is byte-identical")
            return
        sys.exit(f"{dest} exists and DIFFERS from the committed pin — "
                 f"reconcile by hand (is the pin stale, or the workdir?)")
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(resolved["pin"], dest)
    print(f"pin emitted: {resolved['pin']} -> {dest}")


def print_all(sf, scope, cfg) -> int:
    header = (f"{'slug':28} {'frame':28} {'h/w':>6} {'hero':>11} "
              f"{'warp':>11} {'fus':3} flags")
    print(header)
    print("-" * len(header))
    counts = dict(resolved=0, skipped=0, pins=0, overrides=0, far_flung=0)
    for slug in sorted(scope):
        resolved = resolve(slug, scope[slug], cfg)
        if resolved is None:
            print(f"{slug:28} {'SKIP: antimeridian':28}")
            counts["skipped"] += 1
            continue
        counts["resolved"] += 1
        flags = []
        if resolved["frame_overridden"]:
            counts["overrides"] += 1
            flags.append("override")
        else:
            frac = main_part_fraction(sf, scope[slug])
            if frac < FAR_FLUNG_FRACTION:
                counts["far_flung"] += 1
                flags.append(f"far-flung {frac:.0%}")
        if resolved["pin"]:
            counts["pins"] += 1
            flags.append("pin")
        if resolved["fusion_overridden"]:
            flags.append("fusion!")
        print(f"{slug:28} {fmt_frame(resolved['frame']):28} {resolved['aspect']:6.2f} "
              f"{resolved['hero'][0]:>5}x{resolved['hero'][1]:<5} "
              f"{resolved['warp'][0]:>5}x{resolved['warp'][1]:<5} {resolved['fusion']:3} "
              f"{' '.join(flags)}")
    print(f"\n{len(scope)} in scope: {counts['resolved']} resolved, "
          f"{counts['skipped']} antimeridian-skipped; "
          f"{counts['overrides']} frame overrides, {counts['pins']} pinned, "
          f"{counts['far_flung']} far-flung (informational)")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--country", help="slug per the countries.toml rule")
    ap.add_argument("--emit-pin", action="store_true",
                    help="copy config/frames/<slug>.json into the workdir")
    ap.add_argument("--all", action="store_true", help="audit table")
    args = ap.parse_args()
    if args.all == bool(args.country):
        ap.error("exactly one of --country / --all")
    if args.emit_pin and not args.country:
        ap.error("--emit-pin needs --country")

    cfg = load_config()
    sf, rows = load_ne_rows()
    scope = build_scope(cfg, rows)
    if args.all:
        return print_all(sf, scope, cfg)
    return print_country(sf, scope, cfg, args.country, args.emit_pin)


if __name__ == "__main__":
    sys.exit(main())
