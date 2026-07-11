#!/usr/bin/env python3
"""Phase 2 step-B prototype: approximate the Cycles hero look with a cheap raster
composite, to judge whether the raster path can be the tiled-globe base before we
commit to a planet-wide run.

Recipe = gdaldem color-relief (hypsometric albedo) x gdaldem hillshade (directional
relief) x our own horizon_svf (valley/AO occlusion), snow whitened into the albedo.
Runs on one country's AEA render grid — the exact grid Blender displaced — so the
output overlays 1:1 on blender/renders/heroes/<slug>.png for a fair side-by-side.

    tile_recipe.py --render-dir data/work/switzerland/render_1s \
        --hero blender/renders/heroes/switzerland.png \
        --out data/work/switzerland/tile_proto

Nothing here is production: colours mirror scene_build.py rather than importing it
(scene_build is a bpy module). If the recipe graduates, the ramp arrays move to a
shared constants module (the single-source-of-truth the plan calls for).
"""

import argparse
import json
import math
import subprocess
import sys
from pathlib import Path

import numpy as np
import rasterio
from rasterio.enums import Resampling
from scipy.ndimage import zoom

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "pipeline"))
from sky_view import horizon_svf  # noqa: E402  reuse the production SVF verbatim

# Hero colour ramp — mirror of scene_build.py (linear RGB, EASE interpolation,
# Standard view transform so linear->sRGB is the only encode). Land 0..6000 m,
# sea -3000..0 m.
LAND_STOPS = [
    (0.000, (0.814847, 0.693872, 0.527115)),
    (0.083, (0.679543, 0.412543, 0.270498)),
    (0.250, (0.617207, 0.313989, 0.215861)),
    (0.500, (0.584079, 0.417885, 0.309469)),
    (0.750, (0.715694, 0.584078, 0.445201)),
    (1.000, (0.814847, 0.715694, 0.577580)),
]
SEA_STOPS = [
    (0.000, (0.274677, 0.571125, 0.558340)),
    (0.100, (0.201556, 0.479320, 0.479320)),
    (0.220, (0.138432, 0.381326, 0.412543)),
    (0.380, (0.093059, 0.291771, 0.341914)),
    (0.620, (0.063010, 0.215861, 0.274677)),
    (1.000, (0.042311, 0.155926, 0.205079)),
]
WATER_RGB = (152, 197, 200)  # 98C5C8 — flat inland lake/river teal (scene_build WATER_RGBA)
SNOW_RGB = (232, 241, 246)   # E8F1F6 — glacial blue-white (scene_build SNOW_RGBA)


def _smoothstep(t: float) -> float:
    """Blender's EASE (ease-in-out) blend between two ramp stops."""
    return t * t * (3.0 - 2.0 * t)


def _lin2srgb(c: np.ndarray) -> np.ndarray:
    c = np.clip(c, 0.0, 1.0)
    return np.where(c <= 0.0031308, 12.92 * c, 1.055 * np.power(c, 1 / 2.4) - 0.055)


def _ramp_color(pos: float, stops) -> list[float]:
    """EASE-interpolated linear RGB at pos in [0,1]."""
    for (p0, c0), (p1, c1) in zip(stops, stops[1:]):
        if pos <= p1:
            t = 0.0 if p1 == p0 else (pos - p0) / (p1 - p0)
            f = _smoothstep(min(1.0, max(0.0, t)))
            return [c0[i] + (c1[i] - c0[i]) * f for i in range(3)]
    return list(stops[-1][1])


def write_ramp(path: Path, kind: str, step: float = 25.0) -> None:
    """gdaldem colour-relief file for ONE surface, densely sampled so linear
    interpolation reproduces the EASE ramp.

    'sea' maps depth (-3000..0) and clamps elevations >=0 to the shallowest teal;
    'land' maps elevation (0..6000) and clamps <=0 to the coast sand. Land vs sea is
    chosen later by the ocean MASK, so each ramp only needs to be right on its own
    side — which keeps the coastline crisp instead of smearing sand into a shallow
    shelf where the depth wobbles around zero."""
    rows = []
    if kind == "sea":
        e = -3000.0
        while e <= 0.0 + 1e-6:  # sea ramp position = -e/3000
            q = min(1.0, max(0.0, -e / 3000.0))
            rows.append((e, _lin2srgb(np.array(_ramp_color(q, SEA_STOPS))) * 255))
            e += step
    else:
        e = 0.0
        while e <= 6000.0 + 1e-6:  # land ramp position = e/6000
            p = min(1.0, max(0.0, e / 6000.0))
            rows.append((e, _lin2srgb(np.array(_ramp_color(p, LAND_STOPS))) * 255))
            e += step
    with open(path, "w") as fh:
        for elev, rgb in rows:
            fh.write(f"{elev:.2f} {int(round(rgb[0]))} {int(round(rgb[1]))} {int(round(rgb[2]))}\n")
        fh.write("nv 0 0 0\n")


def run(cmd: list[str]) -> None:
    subprocess.run(cmd, check=True, capture_output=True)


def save_png(arr: np.ndarray, path: Path) -> None:
    """Write an (3,H,W) uint8 array to PNG via a temp GTiff + gdal_translate."""
    _, h, w = arr.shape
    tmp = path.with_suffix(".tmp.tif")
    with rasterio.open(tmp, "w", driver="GTiff", height=h, width=w, count=3,
                       dtype="uint8") as o:
        o.write(arr)
    run(["gdal_translate", "-q", "-of", "PNG", str(tmp), str(path)])
    tmp.unlink()
    aux = path.with_suffix(path.suffix + ".aux.xml")
    if aux.exists():
        aux.unlink()


def load_rgb(path: Path, target_h: int) -> np.ndarray:
    with rasterio.open(path) as d:
        w = round(d.width * target_h / d.height)
        return d.read([1, 2, 3], out_shape=(3, target_h, w),
                      resampling=Resampling.average).astype("uint8")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--render-dir", type=Path, required=True)
    ap.add_argument("--hero", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--az", type=float, default=315.0)
    ap.add_argument("--alt", type=float, default=45.0)
    ap.add_argument("--multidirectional", action=argparse.BooleanOptionalAction, default=False,
                    help="multi-azimuth hillshade (softer, but greys the high country); default is the hero's single NW sun")
    ap.add_argument("--snow-floor", type=float, default=0.78,
                    help="minimum light on snow so glaciated peaks stay bright on steep slopes")
    ap.add_argument("--exposure", type=float, default=1.30,
                    help="brights gain anchored at the shadow floor (blows lit/flat areas bright like the hero's sun, shadows hold); land only")
    ap.add_argument("--ambient", type=float, default=0.50,
                    help="shadow floor (mimics the dim SE fill); 0 = full black")
    ap.add_argument("--hi", type=float, default=1.30,
                    help="lit-slope dodge cap; >1 brightens sun-facing slopes toward white")
    ap.add_argument("--saturation", type=float, default=1.18,
                    help="chroma boost on the rock albedo toward the hero's richer register")
    ap.add_argument("--warmth", type=float, default=0.06,
                    help="warm cast on rock (Cycles' warm bounce a neutral multiply misses)")
    ap.add_argument("--svf-strength", type=float, default=0.20)
    ap.add_argument("--svf-threshold", type=float, default=0.45)
    ap.add_argument("--sea-shade", type=float, default=0.26,
                    help="ocean shading strength vs land (0 = flat/calm sea, 1 = full hillshade)")
    ap.add_argument("--sea-lift", type=float, default=1.08,
                    help="ocean brightness centre (land flat = 1.0); keep < clipping so the shelf stays pale teal, not white")
    ap.add_argument("--sea-saturation", type=float, default=0.90,
                    help="ocean chroma vs the raw sea ramp; a touch <1 softens but keeps the shallow->deep gradient")
    args = ap.parse_args()

    rd, out = args.render_dir, args.out
    out.mkdir(parents=True, exist_ok=True)
    hf = rd / "heightfield_aea.tif"
    frame = json.loads((rd / "frame.json").read_text())
    exag = frame["displacement_scale"] * frame["extent_w_m"] / 2.0
    print(f"vertical exaggeration (from frame.json) = {exag:.2f}x", flush=True)

    # 1. albedo — land and sea coloured by SEPARATE ramps, composited later by the
    # ocean MASK (not the elevation sign). A single elevation ramp smears the coast:
    # on a shallow shelf the depth wobbles around 0, mixing sand and teal into a
    # diffuse band. The hero selects sea vs land by the mask, so the coastline is crisp.
    land_ramp = out / "ramp_land.txt"
    sea_ramp = out / "ramp_sea.txt"
    write_ramp(land_ramp, "land")
    write_ramp(sea_ramp, "sea")
    land_tif = out / "color_land.tif"
    sea_tif = out / "color_sea.tif"
    run(["gdaldem", "color-relief", str(hf), str(land_ramp), str(land_tif)])
    run(["gdaldem", "color-relief", str(hf), str(sea_ramp), str(sea_tif)])

    # 2. hillshade, exaggerated to match the displaced geometry. Multidirectional
    # (default) lights from several azimuths -> softer on the steep high terrain a
    # single NW sun crushes to shadow; also the tile recipe the plan specifies.
    hs_tif = out / "hillshade.tif"
    hs_cmd = ["gdaldem", "hillshade", str(hf), str(hs_tif), "-z", f"{exag:.4f}",
              "-alt", str(args.alt), "-compute_edges"]
    hs_cmd += ["-multidirectional"] if args.multidirectional else ["-az", str(args.az)]
    run(hs_cmd)

    with rasterio.open(land_tif) as c:
        land_color = c.read([1, 2, 3]).astype(float)
    _, H, W = land_color.shape
    with rasterio.open(sea_tif) as c:
        sea_color = c.read([1, 2, 3]).astype(float)
    # ocean MASK decides land vs sea (crisp coastline), not the elevation sign.
    with rasterio.open(rd / "oceanmask_aea.tif") as d:
        ocean = d.read(1, out_shape=(H, W), resampling=Resampling.nearest) != 0
    # land: warmth + chroma push (a rock effect); sea: desaturate toward the hero's
    # soft pastel shelf-sea. Each ramp is already correct on its own side.
    lum = 0.299 * land_color[0] + 0.587 * land_color[1] + 0.114 * land_color[2]
    warmed = lum[None] + (land_color - lum[None]) * args.saturation
    warm = np.array([1.0, 1.0 - 0.5 * args.warmth, 1.0 - args.warmth]).reshape(3, 1, 1)
    warmed = np.clip(warmed * warm, 0, 255)
    sea_lum = 0.299 * sea_color[0] + 0.587 * sea_color[1] + 0.114 * sea_color[2]
    sea = np.clip(sea_lum[None] + (sea_color - sea_lum[None]) * args.sea_saturation, 0, 255)
    color = np.where(ocean[None], sea, warmed)
    with rasterio.open(hs_tif) as h:
        hs = h.read(1).astype(float)
    # normalise so flat ground (hillshade = 255*sin(alt)) reads as full brightness;
    # only slopes deviate, floored at `ambient` so shadows keep the fill glow.
    flat = 255.0 * math.sin(math.radians(args.alt))
    light = np.clip(hs / flat, args.ambient, args.hi)

    # 3. valley/AO occlusion from our horizon SVF (reduced res, upsampled)
    with rasterio.open(hf) as d:
        sw = max(1, round(d.width / max(d.width, d.height) * 2200))
        sh = max(1, round(d.height / max(d.width, d.height) * 2200))
        z = d.read(1, out_shape=(sh, sw), resampling=Resampling.average).astype(float)
        mpp = (d.bounds.right - d.bounds.left) / sw
    z = np.nan_to_num(np.where(z < -500, np.nan, z), nan=0.0)
    svf = horizon_svf(z, mpp)
    occ = 1.0 - (svf - svf.min()) / (svf.max() - svf.min() + 1e-6)
    burn = args.svf_strength * np.clip(
        (occ - args.svf_threshold) / (1 - args.svf_threshold), 0, 1) ** 1.4
    svf_factor = np.clip(np.asarray(zoom(1.0 - burn, (H / sh, W / sw), order=1)), 0, 1)

    # 4. snow whitened into the albedo (before shading, like the hero)
    snow_mask = np.zeros((H, W), bool)
    snow = rd / "snowmask_aea.png"
    if snow.exists():
        with rasterio.open(snow) as s:
            sm = s.read(1, out_shape=(H, W), resampling=Resampling.nearest).astype(float) / 255.0
        snow_rgb = np.array(SNOW_RGB, float).reshape(3, 1, 1)
        color = color * (1 - sm) + snow_rgb * sm
        snow_mask = sm > 0.5

    # 5. inland water — flat WATER_RGB over lakes + rivers (hero paints these, over snow)
    water = np.zeros((H, W), bool)
    for name in ("inlandlake_aea.png", "river_aea.png"):
        p = rd / name
        if p.exists():
            with rasterio.open(p) as d:
                water |= d.read(1, out_shape=(H, W), resampling=Resampling.nearest) > 127
    if water.any():
        color = np.where(water[None], np.array(WATER_RGB, float).reshape(3, 1, 1), color)

    # flat water (sea + lakes/rivers) stays even: no SVF, gentle light floor
    svf_factor = np.where(ocean | water, 1.0, svf_factor)
    light = np.where(water, np.clip(light, 0.85, args.hi), light)
    # sea floor: much gentler shading than land + a slight exposure lift, so shelf
    # seas read calm/pale like the hero instead of harsh hillshaded GEBCO noise.
    light = np.where(ocean, args.sea_lift + (light - 1.0) * args.sea_shade, light)
    # snow keeps its brightness on steep slopes (soft GI does this in the hero) so
    # glaciated peaks glow instead of crushing to grey.
    light = np.where(snow_mask, np.maximum(light, args.snow_floor), light)
    # land exposure anchored at the shadow floor — the hero's strong sun blows large
    # flat/lit pale areas (Tibet, the Gangetic plain) bright while alpine shadows stay
    # deep. A flat multiply would lift shadows too and wash out mountainous countries.
    light = np.where(ocean | water, light,
                     args.ambient + (light - args.ambient) * args.exposure)

    composite = np.clip(color * (light * svf_factor), 0, 255).astype("uint8")
    save_png(composite, out / "composite.png")

    # side-by-side vs the Cycles hero, both at a viewable height
    th = 1500
    comp_s = load_rgb(out / "composite.png", th)
    hero_s = load_rgb(args.hero, th)
    w = min(comp_s.shape[2], hero_s.shape[2])
    gap = np.full((3, th, 20), 255, np.uint8)
    sbs = np.concatenate([comp_s[:, :, :w], gap, hero_s[:, :, :w]], axis=2)
    save_png(sbs, out / "compare.png")
    print("wrote composite.png + compare.png (left = raster recipe, right = Cycles hero)",
          flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
