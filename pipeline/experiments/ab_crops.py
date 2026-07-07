"""Cut matched Route A / Route B crop pairs plus a 2K preview of Route A.

Same AEA->pixel mapping as overlay_borders.py: ortho scale spans the larger
render dimension, plane is 2 units wide, pixels square, frame centered.
"""
import numpy as np
import pyproj
import rasterio
from rasterio.enums import Resampling

R = "/home/rohan/projects/maps/data/work/india/render"
ROUTE_A = "/home/rohan/projects/maps/blender/renders/india_water_8k_0001.png"
ROUTE_B = f"{R}/overlay/hydro_composited_8k.png"
ORTHO_SCALE, PLANE_WIDTH_UNITS, CROP = 2.06, 2.0, 900
SITES = {"tibet_lakes": (88.0, 31.5), "ganges": (82.5, 25.5),
         "brahmaputra": (91.0, 26.3)}

with rasterio.open(f"{R}/heightfield_aea.tif") as src:
    b, crs = src.bounds, src.crs

imgs = {}
for tag, path in (("A", ROUTE_A), ("B", ROUTE_B)):
    with rasterio.open(path) as f:
        imgs[tag] = f.read()[:3]  # (3, H, W)
        w, h = f.width, f.height

units_per_px = ORTHO_SCALE / max(w, h)
m_per_px = units_per_px * (b.right - b.left) / PLANE_WIDTH_UNITS
cx, cy = (b.left + b.right) / 2.0, (b.bottom + b.top) / 2.0
fwd = pyproj.Transformer.from_crs("EPSG:4326", crs, always_xy=True)

for name, (lon, lat) in SITES.items():
    x, y = fwd.transform(lon, lat)
    col = int(w / 2.0 + (x - cx) / m_per_px)
    row = int(h / 2.0 - (y - cy) / m_per_px)
    r0, c0 = row - CROP // 2, col - CROP // 2
    halves = [imgs[t][:, r0:r0 + CROP, c0:c0 + CROP] for t in ("A", "B")]
    divider = np.full((3, CROP, 8), 255, dtype=np.uint8)
    pair = np.concatenate([halves[0], divider, halves[1]], axis=2)
    out = f"{R}/overlay/ab_water_{name}.png"
    with rasterio.open(out, "w", driver="PNG", width=pair.shape[2],
                       height=CROP, count=3, dtype="uint8") as f:
        f.write(pair)
    print(f"wrote {out}")

with rasterio.open(ROUTE_A) as f:
    pw = 2048
    ph = round(f.height * pw / f.width)
    small = f.read(out_shape=(f.count, ph, pw), resampling=Resampling.average)
with rasterio.open(f"{R}/overlay/india_water_8k_preview2k.png", "w",
                   driver="PNG", width=pw, height=ph, count=small.shape[0],
                   dtype="uint8") as f:
    f.write(small)
print("wrote preview2k")
