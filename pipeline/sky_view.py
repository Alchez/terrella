#!/usr/bin/env python3
"""Post-render sky-view-factor shading: add topographic depth to a finished hero.

The Cycles render lights terrain with one sun, so subtle relief (drainage,
valleys, low-relief countries) reads flat. This computes a horizon-based
sky-view factor (openness) from the warped heightfield and *burns* it into the
hero — darkening genuinely-occluded valleys while leaving open ground at its
rendered brightness (no dodge, so flat countries never wash out to "desert",
and the scene neither dims nor grains the way an in-scene Cycles AO does).

Land only (via the ocean mask); the sea keeps its rendered bathymetry shading.
Runs after scene_build (batch.py calls it on the .tmp.png before promoting),
so it is applied exactly once per render — never twice (no compounding).

Openness is computed at a reduced resolution and upsampled: SVF is smooth, so
this is visually identical to full-res at a fraction of the cost (~seconds).

Usage:
  sky_view.py --render-dir data/work/nepal/render \
      --hero blender/renders/heroes/nepal.png     # overwrites the hero
  sky_view.py --render-dir ... --hero raw.png --out shaded.png --strength 0.38
"""

import argparse
import os
import warnings
from pathlib import Path
from typing import Any

import numpy as np
import rasterio
from rasterio.enums import Resampling
from scipy.ndimage import zoom

warnings.filterwarnings("ignore")


def horizon_svf(z: np.ndarray, m_per_px: float, n_dir: int = 16,
                max_px: int = 42, exag: float = 22.0) -> np.ndarray:
    """Sky-view factor 0..1 (1 = fully open sky, lower = occluded/valley).

    For n_dir azimuths, march out to max_px pixels tracking the max horizon
    elevation angle; SVF = 1 - mean sin(horizon angle). `exag` is a sensitivity
    lever so low-relief terrain still produces usable occlusion (the burn below
    re-normalises per country, so the absolute scale only shapes the falloff)."""
    z = z * exag
    acc = np.zeros_like(z)
    for k in range(n_dir):
        az = 2.0 * np.pi * k / n_dir
        dy, dx = np.sin(az), np.cos(az)
        mh = np.full_like(z, -1e9)
        for d in range(1, max_px):
            zi = np.roll(np.roll(z, -int(round(dy * d)), 0), -int(round(dx * d)), 1)
            np.maximum(mh, (zi - z) / (d * m_per_px), out=mh)
        acc += 1.0 - np.sin(np.arctan(np.clip(mh, 0, None)))
    return acc / n_dir


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--render-dir", type=Path, required=True,
                    help="dir with heightfield_aea.tif + oceanmask_aea.tif")
    ap.add_argument("--hero", type=Path, required=True, help="rendered hero PNG")
    ap.add_argument("--out", type=Path, help="output (default: overwrite --hero)")
    ap.add_argument("--strength", type=float, default=0.38,
                    help="max valley darkening (0..1); ~0.38 is the tuned default")
    ap.add_argument("--threshold", type=float, default=0.45,
                    help="only darken occlusion above this (keeps open ground clean)")
    ap.add_argument("--svf-long", type=int, default=2200,
                    help="SVF compute resolution (upsampled to the hero)")
    args = ap.parse_args()
    out = args.out or args.hero

    hf_path = args.render_dir / "heightfield_aea.tif"
    om_path = args.render_dir / "oceanmask_aea.tif"

    with rasterio.open(args.hero) as h:
        hero = h.read()                      # (bands, H, W) uint8
        prof: dict[str, Any] = h.profile
    _, H, W = hero.shape

    # openness at reduced res, from the warped heightfield
    with rasterio.open(hf_path) as d:
        sw = max(1, round(d.width / max(d.width, d.height) * args.svf_long))
        sh = max(1, round(d.height / max(d.width, d.height) * args.svf_long))
        hf = d.read(1, out_shape=(sh, sw), resampling=Resampling.average).astype(float)
        m_per_px = (d.bounds.right - d.bounds.left) / sw
    hf = np.nan_to_num(np.where(hf < -500, np.nan, hf), nan=0.0)
    svf = horizon_svf(hf, m_per_px)
    occ = 1.0 - (svf - svf.min()) / (svf.max() - svf.min() + 1e-6)   # 0 open .. 1 occluded
    # burn-only: darken above threshold, open ground untouched
    burn = args.strength * np.clip((occ - args.threshold) / (1 - args.threshold), 0, 1) ** 1.4
    up = np.asarray(zoom(1.0 - burn, (H / sh, W / sw), order=1))     # upsample to hero
    factor = np.clip(up, 0.0, 1.0)

    # land only — the ocean mask (1 = ocean) resampled to the hero grid
    with rasterio.open(om_path) as d:
        land = d.read(1, out_shape=(H, W), resampling=Resampling.nearest) == 0

    f = np.where(land, factor, 1.0)[None, :, :]                      # (1,H,W)
    n = min(3, hero.shape[0])                                        # RGB, keep alpha
    hero[:n] = np.clip(hero[:n].astype(float) * f, 0, 255).astype("uint8")

    tmp = out.with_name(out.name + ".tmp")
    with rasterio.open(tmp, "w", **prof) as o:
        o.write(hero)
    aux = out.with_name(out.name + ".aux.xml")
    if (tmp_aux := tmp.with_name(tmp.name + ".aux.xml")).exists():
        os.replace(tmp_aux, aux)
    os.replace(tmp, out)
    print(f"sky_view: shaded {out.name} (strength {args.strength}, "
          f"{int(land.mean() * 100)}% land)", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
