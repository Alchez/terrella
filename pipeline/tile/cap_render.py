#!/usr/bin/env python3
"""Render the polar caps: sea ice + snow over real bathymetry, on AEQD grids reaching the pole.

Web-Mercator tiles die at ~85N (1/cos-phi sends the pole to infinity), so each pole is a
source-shaded polar raster drawn over the globe by a MapLibre custom layer (polarCapSpike.ts),
feathered into the tiles at the seam. Azimuthal-equidistant, centred on the pole, inscribed
circle at `grid.edge_lat` (MUST equal polarCapSpike.ts TEX_EDGE_LAT for that cap). Runs the one
shared `shade.composite` and writes `cap_{north,south}.png` un-flipped to web/public/dev-assets/.

Both poles share the projection/warp/coastline machinery but source their inputs differently:
  - NORTH: the fused planet VRTs (height/ocean/water) + NSIDC-0791 snow persistence + OSI SAF sea
    ice. The whole cap is >78N, so snow_alpha's Mercator latitude ramp is CONSTANT here (reproduced
    with fixed high-latitude thresholds). Inland water via lake_depth.inland_water (NEVER
    watercode.astype(bool) -- that caught class-1 ocean and flat-filled the Arctic sea, the
    2026-07-19 disc-glow bug).
  - SOUTH (Antarctica): the fused planet stops at -60 (`--skip-south -60`), so the continent is
    read from GEBCO DIRECT (ice-surface elevation, reaches -90). Land/ocean is the GEBCO 0 m
    threshold: >=0 = the ice sheet + floating shelves (freeboard is positive) -> force snow white;
    <0 = Southern Ocean -> bathymetry depth ramp + the SH half of the same sea-ice climatology.
    Snow is FORCED over Antarctic land, not read from a dataset (NSIDC-0791 is NH-only, RGI region
    19 is excluded), and gated to lat < SNOW_LAT_MAX_S so any continent tips / sub-Antarctic islands
    intruding into the disc corners (which the frontend feathers out anyway) are not painted white.

Two cap-specific twists vs the Mercator tiles:
  - the light azimuth rotates with longitude: the tiles light true-NW everywhere, and near the
    pole "NW" turns with the meridian, so the main sun is `AZ + grid.az_sign * lon` per pixel
    (meridian convergence in a polar azimuthal projection = longitude). The sign flips between the
    north (-1, verified) and south (+1, from the south-aspect y-flip -- verify on the crop);
  - SVF is left off (its residual is <1% at the pole). A scalar z-factor is fine: AEQD tangential
    distortion inside the edge latitude is small.

Usage: GDAL_CACHEMAX=512 uv run python -m pipeline.tile.cap_render [--north | --south]  (default: both)
"""
import argparse
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import rasterio
from pyproj import Transformer
from scipy.ndimage import binary_dilation

from pipeline.render import hillshade, lake_depth, seaice, snow
from pipeline.tile import shade
from pipeline.tile.shade import KNOBS
from pipeline.tile.shade_planet import ALT, AZ, EXAG, PLANET

ROOT = Path.home() / "projects/maps"
WORK = ROOT / "data/work/cap"
DEV_ASSETS = ROOT / "web/public/dev-assets"
GEBCO = ROOT / "data/raw/gebco/gebco_2026_global.vrt"  # ice-surface elevation, reaches -90 (south cap)
CAP_PX = 4096          # square texture side (south is a bigger disc -> coarser per px; tunable, bump for prod)
SPHERE_R = 6371000.0   # spherical AEQD radius; the frontend's linear-colatitude UV assumes a sphere
SNOW_LAT_MAX_S = -60.0  # south: force ice only over land below this (excludes sub-Antarctic land in the corners)
POLE_TAPER_COLAT = 3.0  # deg: within this colatitude the AEQD light azimuth (AZ + lon) sweeps 360 deg as
                        # the meridians converge, washing relief into a pinwheel disc at the exact pole;
                        # ramp the relief to flat inside it so there is no hard-edged wheel
# South-cap sea ice: fainter + pulled in vs the global (Arctic) strength. Antarctica is a continent
# RINGED by a mostly-seasonal belt, so the full-strength climatology reads as a bright halo; a
# translucent, tighter fringe lets the bathymetry show through and keeps the continent clean. South
# ONLY -- the north cap keeps the globals (the Arctic pack IS the subject). Tuned 2026-07-20.
CAP_S_ICE_LO = 0.62         # vs seaice.ICE_LO 0.55 -- pull the seasonal fringe in
CAP_S_ICE_MAX_ALPHA = 0.55  # vs seaice.ICE_MAX_ALPHA 0.85 -- more translucent over the bathymetry


@dataclass(frozen=True)
class CapGrid:
    """One pole's AEQD render grid. `edge_lat` is the inscribed-circle latitude (frontend TEX_EDGE_LAT
    MUST match it); `az_sign` is the sign of the longitude term in the per-pixel light azimuth.
    `coast_opacity`/`coast_dilate` tune the baked coastline (0 opacity = skip it entirely)."""
    lat_0: float
    edge_lat: float
    px: int
    name: str
    az_sign: float
    coast_opacity: float = 0.55  # baked coastline strength over the cap RGB; 0 = skip
    coast_dilate: int = 1        # binary-dilation iterations -> ~3 px line at 4096 when 1
    ice_lo: "float | None" = None         # sea-ice threshold override; None -> seaice.ICE_LO
    ice_max_alpha: "float | None" = None  # sea-ice max opacity override; None -> seaice.ICE_MAX_ALPHA

    @property
    def aeqd(self) -> str:
        return (f"+proj=aeqd +lat_0={self.lat_0} +lon_0=0 "
                f"+a={SPHERE_R} +b={SPHERE_R} +units=m +no_defs")

    @property
    def edge_m(self) -> float:
        """Half-width of the square texture, in AEQD metres (radius of the inscribed circle)."""
        return SPHERE_R * float(np.radians(90.0 - abs(self.edge_lat)))


NORTH = CapGrid(lat_0=90.0, edge_lat=78.0, px=CAP_PX, name="north", az_sign=-1.0)
# South: NO baked coastline. The north NEEDS it (Greenland's white ice sheet abuts the white Arctic
# pack -- without a line they merge), but on the south white ice sits on teal ocean, which already
# separates itself; a dark line there just reads as a cartoonish outline around the continent.
SOUTH = CapGrid(lat_0=-90.0, edge_lat=-55.0, px=CAP_PX, name="south", az_sign=1.0,
                coast_opacity=0.0, coast_dilate=0,
                ice_lo=CAP_S_ICE_LO, ice_max_alpha=CAP_S_ICE_MAX_ALPHA)

# The coastline baked into the cap texture -- the land/sea line separating land snow from sea ice
# where MapLibre's Mercator vector borders can't reach the pole. It must be DARK, not the globe's
# white coast line: a white line vanishes between white snow and white ice. A muted steel-blue reads
# delicately on both whites without going harsh. Line strength/width are per-cap (CapGrid).
COAST_SHP = ROOT / "data/raw/naturalearth/ne_10m_coastline/ne_10m_coastline.shp"
COAST_RGB = (96, 122, 142)  # muted steel-blue


def _run(cmd):
    subprocess.run([str(part) for part in cmd], check=True, capture_output=True)


def _warp(grid: CapGrid, src, out: Path, resampling: str, dtype: str, srcnodata=None) -> np.ndarray:
    """gdalwarp one 4326 source onto this cap's AEQD grid; return band 1."""
    edge = grid.edge_m
    cmd = ["gdalwarp", "-overwrite", "-q", "-t_srs", grid.aeqd,
           "-te", str(-edge), str(-edge), str(edge), str(edge),
           "-ts", str(grid.px), str(grid.px), "-r", resampling, "-ot", dtype,
           "-co", "TILED=YES", "-co", "COMPRESS=DEFLATE"]
    if srcnodata is not None:
        cmd += ["-srcnodata", str(srcnodata), "-dstnodata", str(srcnodata)]
    _run([*cmd, str(src), str(out)])
    with rasterio.open(out) as dataset:
        return dataset.read(1)


def _lonlat_grid(grid: CapGrid) -> tuple[np.ndarray, np.ndarray]:
    """True (longitude, latitude) in degrees at each AEQD pixel centre, via an exact AEQD->4326
    transform. row 0 is the +y (pole-up) top of the image. lon drives the per-pixel light azimuth;
    lat gates the south's forced-ice mask."""
    cell = 2 * grid.edge_m / grid.px
    xs = -grid.edge_m + (np.arange(grid.px) + 0.5) * cell
    ys = grid.edge_m - (np.arange(grid.px) + 0.5) * cell
    xx, yy = np.meshgrid(xs, ys)
    lon, lat = Transformer.from_crs(grid.aeqd, "EPSG:4326", always_xy=True).transform(xx, yy)
    return np.asarray(lon, dtype=np.float32), np.asarray(lat, dtype=np.float32)


def _shade(grid: CapGrid, heights: np.ndarray, longitude: np.ndarray) -> np.ndarray:
    """Combined light (main + fill) with the per-pixel longitude-rotated azimuth. heights get a
    1-row edge halo top+bottom (hillshade_array wraps columns itself; the wrapped seam sits in the
    unused corners past the edge latitude)."""
    cell = 2 * grid.edge_m / grid.px
    haloed = np.pad(heights, ((1, 1), (0, 0)), mode="edge")
    main_az = (AZ + grid.az_sign * longitude).astype(np.float32)
    fill_az = (hillshade.FILL_AZIMUTH + grid.az_sign * longitude).astype(np.float32)
    shaded = hillshade.hillshade_array(haloed, cell, EXAG, ALT, main_az)
    fill = hillshade.hillshade_array(haloed, cell, EXAG, hillshade.FILL_ALTITUDE, fill_az)
    rotating = hillshade.combine_fill(shaded, fill, KNOBS["fill_strength"], ALT)

    # Near the pole the rotating azimuth (AZ + az_sign*lon) sweeps 360 deg over a few pixels as the
    # meridians converge, washing the directional relief into a pinwheel disc with a hard edge. Ramp
    # the relief to the local flat level inside POLE_TAPER_COLAT so both the wheel and its edge vanish;
    # the pole is a near-flat ice dome, so a soft featureless spot reads true. (A fixed-azimuth blend
    # was tried to keep texture, but the fixed/rotating shades anti-correlate into petal interference
    # -- worse than a clean flat dome.)
    colat = _colatitude(grid)
    inner = colat < POLE_TAPER_COLAT
    if not inner.any():
        return rotating
    t = np.clip(colat[inner] / POLE_TAPER_COLAT, 0.0, 1.0)
    weight = t * t * (3.0 - 2.0 * t)  # smoothstep: 0 at the pole, 1 at the taper edge
    flat_dn = float(np.median(rotating[inner]))  # the local ambient level under the wash
    result = rotating.copy()
    result[inner] = flat_dn + (rotating[inner] - flat_dn) * weight
    return result


def _colatitude(grid: CapGrid) -> np.ndarray:
    """Colatitude (deg from the pole) at each AEQD pixel centre. The AEQD radius is exactly
    SPHERE_R * colatitude, so distance-from-centre converts straight to degrees."""
    cell = 2 * grid.edge_m / grid.px
    xs = -grid.edge_m + (np.arange(grid.px) + 0.5) * cell
    ys = grid.edge_m - (np.arange(grid.px) + 0.5) * cell
    xx, yy = np.meshgrid(xs, ys)
    return np.degrees(np.hypot(xx, yy) / SPHERE_R)


def _bake_coastline(grid: CapGrid, rgb: np.ndarray) -> None:
    """Blend the coastline as a subtle dark line over the cap RGB, in place. No-op when the cap opts
    out (`coast_opacity <= 0`, e.g. the south, where white ice on teal ocean self-separates).

    ne_10m_coastline is 4326, so reproject to AEQD (gdal_rasterize does not reproject) before burning
    it onto the cap grid; a small dilation makes it a ~3 px line rather than a 1 px thread at 4096.
    """
    if grid.coast_opacity <= 0.0:
        return
    edge = grid.edge_m
    coast_aeqd = WORK / f"cap_{grid.name}_coast_aeqd.gpkg"
    coast_tif = WORK / f"cap_{grid.name}_coast.tif"
    _run(["ogr2ogr", "-overwrite", "-t_srs", grid.aeqd, str(coast_aeqd), str(COAST_SHP)])
    _run(["gdal_rasterize", "-q", "-burn", "1", "-init", "0", "-ot", "Byte",
          "-te", str(-edge), str(-edge), str(edge), str(edge),
          "-ts", str(grid.px), str(grid.px), str(coast_aeqd), str(coast_tif)])
    with rasterio.open(coast_tif) as dataset:
        line = dataset.read(1) != 0
    if grid.coast_dilate:
        line = binary_dilation(line, iterations=grid.coast_dilate)
    for band in range(3):
        blended = rgb[band][line] * (1.0 - grid.coast_opacity) + COAST_RGB[band] * grid.coast_opacity
        rgb[band][line] = np.rint(blended).astype("uint8")


def _write_cap(grid: CapGrid, heights: np.ndarray, ocean: np.ndarray, water: np.ndarray,
               snow_a: np.ndarray, ice_a: np.ndarray, hillshade_dn: np.ndarray) -> Path:
    """Shared composite + coastline bake + PNG write for either pole. SVF off (measured 2026-07-20:
    the tiles' ocean SVF is thresholded out over flat seafloor, so a cap SVF pass changes the ocean
    sub-perceptibly and does not close the cap<->tile seam -- the seam is projection/DEM, not SVF)."""
    occ = np.zeros((grid.px, grid.px), dtype=np.float32)  # occ below threshold -> no SVF burn
    rgb = shade.composite(heights, ocean, water, snow_a, hillshade_dn, occ, occ.shape,
                          (grid.px, grid.px), depth=None, ice_a=ice_a)
    _bake_coastline(grid, rgb)  # the land/sea line, so ice sheet reads distinct from sea ice at the pole

    tif = WORK / f"cap_{grid.name}.tif"
    profile: dict[str, Any] = dict(driver="GTiff", width=grid.px, height=grid.px, count=3,
                                   dtype="uint8", photometric="RGB")
    with rasterio.open(tif, "w", **profile) as dataset:
        dataset.write(rgb)
    DEV_ASSETS.mkdir(parents=True, exist_ok=True)
    out_png = DEV_ASSETS / f"cap_{grid.name}.png"
    _run(["gdal_translate", "-q", "-of", "PNG", str(tif), str(out_png)])
    return out_png


def render_cap_north() -> Path:
    """North cap from the fused planet VRTs + snow persistence + sea ice."""
    WORK.mkdir(parents=True, exist_ok=True)
    grid = NORTH
    height = _warp(grid, PLANET / "planet_heightfield.vrt", WORK / "capN_height.tif", "bilinear", "Float32")
    ocean_raw = _warp(grid, PLANET / "planet_oceanmask.vrt", WORK / "capN_ocean.tif", "near", "Byte")
    watercode = _warp(grid, PLANET / "planet_watermask.vrt", WORK / "capN_water.tif", "near", "Byte")
    sp_raw = _warp(grid, f'NETCDF:"{snow.SP_NC}":{snow.SP_VAR}', WORK / "capN_sp.tif",
                   "bilinear", "Float32", srcnodata=snow.SP_FILL)
    ice_raw = _warp(grid, seaice.SEAICE_SRC, WORK / "capN_seaice.tif",
                    "bilinear", "Float32", srcnodata=seaice.ICE_FILL)

    heights = np.where(height < -1e4, 0.0, height).astype(np.float32)  # DEM nodata -> flat, as hillshade does
    ocean = ocean_raw != 0
    water = lake_depth.inland_water(watercode)
    longitude, _lat = _lonlat_grid(grid)
    hillshade_dn = _shade(grid, heights, longitude)

    # Snow alpha: the whole cap is >CAP_EDGE_LAT (78) > snow.RAMP_LAT_HI (63), so snow_alpha's
    # latitude ramp is CONSTANT here -- reproduce it with the fixed high-latitude thresholds rather
    # than snow_alpha, whose per-row latitude is Mercator-specific and wrong on an AEQD grid.
    persistence = snow.unpack_persistence(sp_raw)
    low = snow.RAMP_LOW_MAX
    high = low + snow.RAMP_BAND
    fraction = np.clip((persistence - low) / (high - low), 0.0, 1.0)
    snow_a = fraction * fraction * (3.0 - 2.0 * fraction)  # float64, as before the N/S refactor

    ice_a = seaice.ice_alpha(seaice.unpack_seaice(ice_raw),  # no latitude term -> valid on AEQD
                             ice_lo=grid.ice_lo, ice_max_alpha=grid.ice_max_alpha)
    return _write_cap(grid, heights, ocean, water, snow_a, ice_a, hillshade_dn)


def render_cap_south() -> Path:
    """South (Antarctica) cap from GEBCO-direct height + the SH half of the sea-ice climatology.

    Land/ocean is the GEBCO 0 m threshold (ice-surface is positive over the grounded sheet AND the
    floating shelves); snow is FORCED over Antarctic land (no SH snow dataset, no RGI region 19).
    """
    WORK.mkdir(parents=True, exist_ok=True)
    grid = SOUTH
    height = _warp(grid, GEBCO, WORK / "capS_height.tif", "bilinear", "Float32", srcnodata=-32767)
    ice_raw = _warp(grid, seaice.SEAICE_SRC, WORK / "capS_seaice.tif",
                    "bilinear", "Float32", srcnodata=seaice.ICE_FILL)

    heights = np.where(height < -1e4, 0.0, height).astype(np.float32)  # GEBCO nodata (-32767) -> flat
    ocean = heights < 0.0                                # <0 = Southern Ocean; >=0 = ice sheet + shelves
    water = np.zeros_like(ocean)                         # no inland-water layer south of -60
    longitude, latitude = _lonlat_grid(grid)
    hillshade_dn = _shade(grid, heights, longitude)

    land = heights >= 0.0
    snow_a = (land & (latitude < SNOW_LAT_MAX_S)).astype(np.float32)  # Antarctica = permanent ice -> white
    ice_a = seaice.ice_alpha(seaice.unpack_seaice(ice_raw),  # fainter, pulled-in fringe (CAP_S_ICE_*)
                             ice_lo=grid.ice_lo, ice_max_alpha=grid.ice_max_alpha)
    return _write_cap(grid, heights, ocean, water, snow_a, ice_a, hillshade_dn)


def main() -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").split("\n")[0])
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--north", action="store_true", help="render only the north cap")
    group.add_argument("--south", action="store_true", help="render only the south cap")
    args = parser.parse_args()

    if not args.south:
        print(f"wrote {render_cap_north()}", flush=True)
    if not args.north:
        print(f"wrote {render_cap_south()}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
