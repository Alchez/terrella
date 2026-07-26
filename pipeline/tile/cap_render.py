#!/usr/bin/env python3
"""Render the polar caps: sea ice + snow over real bathymetry, on AEQD grids reaching the pole.

Web-Mercator tiles die at ~85N (1/cos-phi sends the pole to infinity), so each pole is a
source-shaded polar raster drawn over the globe by a MapLibre custom layer (polarCaps.ts),
feathered into the tiles at the seam. Azimuthal-equidistant, centred on the pole, inscribed
circle at `grid.edge_lat`. Runs the one shared `shade.composite` and writes
`cap_{north,south}_{px}.webp` un-flipped to web/public/caps/ — one file per CAP_RUNGS size —
beside `caps.json`, the contract the web layer fetches (edge_lat, feather ceiling, the rung
list), so no cap constant is hand-copied into TypeScript (see caps_manifest).

Both poles share the projection/warp/coastline machinery but source their inputs differently:
  - NORTH: the fused planet VRTs (height/ocean/water) + NSIDC-0791 snow persistence + OSI SAF sea
    ice. The whole cap is >78N, so snow_alpha's Mercator latitude ramp is CONSTANT here (reproduced
    with fixed high-latitude thresholds). Inland water via lake_depth.inland_water (NEVER
    watercode.astype(bool) -- that caught class-1 ocean and flat-filled the Arctic sea, the
    disc-glow bug).
  - SOUTH (Antarctica): the same fused planet VRTs (they reach -90 since the fill;
    GEBCO-direct sourcing died the same day -- it shaded ~2.5 DN darker than the tiles and read as
    an interior ring). Ocean -> bathymetry depth ramp + the SH half of the same sea-ice climatology.
    Snow is FORCED over Antarctic land, not read from a dataset (NSIDC-0791 is NH-only, RGI region
    19 is excluded), via snow.antarctic_snow_mask (shared with the tile composite). Since the
    pyramid carries Antarctica itself, the cap mirrors the north exactly (edge_lat -78, feathered
    81..84 over interior ice) and only covers the last smeared Mercator sliver.

Two cap-specific twists vs the Mercator tiles:
  - the light azimuth rotates with longitude: the tiles light true-NW everywhere, and near the
    pole "NW" turns with the meridian, so the main sun is `AZ + grid.az_sign * lon` per pixel
    (meridian convergence in a polar azimuthal projection = longitude). The sign flips between the
    north (-1, verified) and south (+1, from the south-aspect y-flip -- verify on the crop);
  - SVF is left off (its residual is <1% at the pole). A scalar z-factor is fine: AEQD tangential
    distortion inside the edge latitude is small.

Freshness: each cap is guarded by a recipe sidecar (data/work/cap/cap_<name>_params.json, built on
shade_planet.composite_params so caps restage exactly when the tile look does) plus source mtimes;
a fresh cap skips. shade_planet's pass tail invokes this module, so the guard actually runs — with
nothing invoking it, both caps once sat a full day stale against the look they feather into.

Usage: GDAL_CACHEMAX=512 uv run python -m pipeline.tile.cap_render [--north | --south] [--force]
"""
import argparse
import json
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import numpy as np
import rasterio
from pyproj import Transformer
from scipy.ndimage import binary_dilation

from pipeline import paths
from pipeline.render import hillshade, lake_depth, seaice, snow
from pipeline.tile import shade
from pipeline.tile.shade import KNOBS
from pipeline.tile.shade_planet import (ALT, AZ, CAP_NORTH, CAP_SOUTH, EXAG, PLANET,
                                        composite_params)

ROOT = paths.ROOT
WORK = ROOT / "data/work/cap"
CAPS_DIR = ROOT / "web/public/caps"  # production home (was dev-assets/ behind ?polarspike)
CAP_PX = 8192          # square texture side (south is a bigger disc -> coarser per px). 8192 chosen
                       # by Rohan (crop A/B + /globe): visibly crisper coast/pack/sastrugi
                       # at deep pole zoom; 3.2+2.1 MB WebP
CAP_RUNGS = (1024, 2048, 4096, CAP_PX)  # shipped texture sizes, ascending; the largest IS the render
                       # grid and every smaller rung is DOWNSAMPLED from it, never rendered natively.
                       # That is deliberate: coast_dilate is measured in pixels, so a native 4096
                       # render would bake a coastline twice as wide relative to the disc.
                       # Downsampling reproduces exactly what a phone already saw (polarCaps.ts
                       # canvas-downscaled the 8192 to its MOBILE_CAP_BUDGET_PX rung) -- so every
                       # rung is a pure payload cut, no look change, supersampled rather than 1:1.
                       # 1024 + 2048 added, when polarCaps started picking a rung from the
                       # cap's PROJECTED on-screen size: the untouched default camera paints the cap
                       # at 110 CSS px, so the 8192 was a 74x linear oversupply for every visitor who
                       # never zooms to a pole. Measured both caps: 162 KB / 570 KB / 1.7 MB / 5.1 MB.
CAP_WEBP_QUALITY = 85  # gdal_translate WEBP quality — hero_variants' proven setting; rides in
                       # cap_recipe because the encoder changes the shipped pixels
SPHERE_R = 6371000.0   # spherical AEQD radius; the frontend's linear-colatitude UV assumes a sphere
# The south-cap forced-snow latitude and toned sea-ice pair moved to their shared homes so the tile
# composite applies the identical rule (one home per concept): snow.antarctic_snow_mask's lat_max=-60,
# and seaice.SH_ICE_LO / seaice.SH_ICE_MAX_ALPHA (used by the SOUTH grid below).


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
SOUTH = CapGrid(lat_0=-90.0, edge_lat=-78.0, px=CAP_PX, name="south", az_sign=1.0,
                coast_opacity=0.0, coast_dilate=0,
                ice_lo=seaice.SH_ICE_LO, ice_max_alpha=seaice.SH_ICE_MAX_ALPHA)

# The coastline baked into the cap texture -- the land/sea line separating land snow from sea ice
# where MapLibre's Mercator vector borders can't reach the pole. It must be DARK, not the globe's
# white coast line: a white line vanishes between white snow and white ice. A muted steel-blue reads
# delicately on both whites without going harsh. Line strength/width are per-cap (CapGrid).
COAST_SHP = ROOT / "data/raw/naturalearth/ne_10m_coastline/ne_10m_coastline.shp"
COAST_RGB = (96, 122, 142)  # muted steel-blue


def cap_asset(grid: CapGrid, px: int) -> Path:
    """The served file for one rung. Every rung is size-suffixed, including the top one — an
    unsuffixed name would encode 'the big one' as a convention nothing checks."""
    return CAPS_DIR / f"cap_{grid.name}_{px}.webp"


def cap_assets(grid: CapGrid) -> list[Path]:
    """Every rung this cap ships, ascending — the freshness gate's asset set."""
    return [cap_asset(grid, px) for px in CAP_RUNGS]


def cap_recipe(grid: CapGrid) -> str:
    """Everything a cap's pixels depend on besides the source rasters, serialised for the
    freshness sidecar. Reuses shade_planet.composite_params — ONE recipe home — so any look change
    that restages the tile composite also restages the caps: exactly the coupling whose absence let
    once let both caps sit stale against the tiles they feather into, the north −6.7 DN
    adrift. `fill_strength` is listed explicitly because
    composite_params filters it out as hillshade-stage — for the tiles it rides in hs_params.json,
    but the caps have no hillshade sidecar, so it must ride here."""
    return json.dumps({"grid": asdict(grid),
                       "light": {"az": AZ, "alt": ALT, "exag": EXAG,
                                 "fill_azimuth": hillshade.FILL_AZIMUTH,
                                 "fill_altitude": hillshade.FILL_ALTITUDE,
                                 "fill_strength": KNOBS["fill_strength"]},
                       "coast_rgb": list(COAST_RGB),
                       "asset": {"format": "webp", "quality": CAP_WEBP_QUALITY,
                                 "rungs": list(CAP_RUNGS)},
                       "composite": json.loads(composite_params({}))},
                      sort_keys=True, indent=2)


def caps_manifest() -> str:
    """The pipeline->web contract, served beside the textures as caps.json.

    polarCaps.ts used to hand-copy `edge_lat` (as texEdgeLat) and the ±84 feather ceiling
    (shade_planet's Mercator plug boundary) as literals — the same copy-drift species as the
    hero/tile colour constants. The web layer now FETCHES this file, so the pipeline is the
    single author of every value it renders into the textures; only frontend aesthetics
    (featherLo, mesh extent) stay web-side.

    `rungs` replaced the old single `url`/`px` pair rather than joining it: two homes for
    'which texture is shipped' is the very drift this contract exists to prevent."""
    return json.dumps({
        grid.name: {"rungs": [{"px": px, "url": f"/caps/{cap_asset(grid, px).name}"}
                              for px in CAP_RUNGS],
                    "edge_lat": grid.edge_lat,
                    "feather_hi": feather_hi}
        for grid, feather_hi in ((NORTH, CAP_NORTH), (SOUTH, CAP_SOUTH))
    }, sort_keys=True, indent=2)


def cap_sources(grid: CapGrid) -> list[Path]:
    """The source files whose change must re-render this cap — composite_deps' sibling. Constants
    ride in cap_recipe; these are the mtime dependencies."""
    sources = [PLANET / "planet_heightfield.vrt", PLANET / "planet_oceanmask.vrt",
               PLANET / "planet_watermask.vrt", Path(seaice.SEAICE_SRC)]
    if grid.name == "north":
        sources.append(Path(snow.SP_NC))  # the south's snow is FORCED, not read from a dataset
    if grid.coast_opacity > 0.0:
        sources.append(COAST_SHP)
    return sources


def cap_is_fresh(recipe: str, assets: list[Path], sidecar: Path, sources: list[Path]) -> bool:
    """True only when EVERY shipped rung exists, was rendered under exactly this recipe, and is
    newer than every source; anything missing reads stale (fail toward re-rendering, never toward
    trusting). Unguarded outputs rot: the DEM mosaics, the 3857 warps and both caps have each
    failed exactly this way.

    All rungs, not just the top one: a rung added to CAP_RUNGS whose file does not exist yet must
    read stale even though the render itself is current. The comparison uses the OLDEST rung, so a
    half-written rung set cannot pass on the strength of its newest member."""
    if not (all(asset.exists() for asset in assets)
            and sidecar.exists() and sidecar.read_text() == recipe):
        return False
    oldest = min(asset.stat().st_mtime for asset in assets)
    return all(source.exists() and source.stat().st_mtime < oldest for source in sources)


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
    # No pole special-case: the rotating azimuth's pinwheel wash at the exact pole is quenched by
    # `shade.KNOBS["ice_relief_damp"]` (the pack conceals the shading that fed the wash). The
    # colat-3 flat taper that used to sit here was measured retirable at damp 0.75 and deleted:
    # pole std 6.16 < surrounding annulus 6.70, no disc-edge ring step.
    return hillshade.combine_fill(shaded, fill, KNOBS["fill_strength"], ALT)


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
    """Shared composite + coastline bake + WebP write for either pole. SVF off, measured:
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
    CAPS_DIR.mkdir(parents=True, exist_ok=True)
    for px in CAP_RUNGS:
        # -outsize on the render TIF, so every rung is the SAME picture at a different scale;
        # gdal_translate's average resampling supersamples (4:1 at the 4096 rung).
        size = ["-outsize", str(px), str(px), "-r", "average"] if px != grid.px else []
        _run(["gdal_translate", "-q", "-of", "WEBP", "-co", f"QUALITY={CAP_WEBP_QUALITY}",
              *size, str(tif), str(cap_asset(grid, px))])
    return cap_asset(grid, grid.px)


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
    """South (Antarctica) cap from the fused planet VRTs + the SH half of the sea-ice climatology.

    Re-sourced from GEBCO-direct when the Antarctica fill pushed the planet VRTs
    to -90: the cap now shades the SAME fused heightfield and masks as the tiles, so the tone across
    the -84 cap<->tile crossfade agrees by construction (the GEBCO cap measured ~2.5 DN darker than
    the tiles it feathered into -- the visible interior ring). Snow is FORCED over Antarctic land
    (no SH snow dataset, no RGI region 19), exactly as the tile composite does.
    """
    WORK.mkdir(parents=True, exist_ok=True)
    grid = SOUTH
    height = _warp(grid, PLANET / "planet_heightfield.vrt", WORK / "capS_height.tif", "bilinear", "Float32")
    ocean_raw = _warp(grid, PLANET / "planet_oceanmask.vrt", WORK / "capS_ocean.tif", "near", "Byte")
    watercode = _warp(grid, PLANET / "planet_watermask.vrt", WORK / "capS_water.tif", "near", "Byte")
    ice_raw = _warp(grid, seaice.SEAICE_SRC, WORK / "capS_seaice.tif",
                    "bilinear", "Float32", srcnodata=seaice.ICE_FILL)

    heights = np.where(height < -1e4, 0.0, height).astype(np.float32)  # DEM nodata -> flat, as hillshade does
    ocean = ocean_raw != 0
    water = lake_depth.inland_water(watercode)
    longitude, latitude = _lonlat_grid(grid)
    hillshade_dn = _shade(grid, heights, longitude)

    land = ~(ocean | water)                            # the tile composite's land definition
    snow_a = snow.antarctic_snow_mask(land, latitude)  # Antarctica = permanent ice -> forced white
    ice_a = seaice.ice_alpha(seaice.unpack_seaice(ice_raw),  # fainter, pulled-in fringe (seaice.SH_ICE_*)
                             ice_lo=grid.ice_lo, ice_max_alpha=grid.ice_max_alpha)
    return _write_cap(grid, heights, ocean, water, snow_a, ice_a, hillshade_dn)


def main() -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").split("\n")[0])
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--north", action="store_true", help="render only the north cap")
    group.add_argument("--south", action="store_true", help="render only the south cap")
    parser.add_argument("--force", action="store_true",
                        help="render even when the freshness sidecar says the cap is current")
    args = parser.parse_args()

    for wanted, grid, render in ((not args.south, NORTH, render_cap_north),
                                 (not args.north, SOUTH, render_cap_south)):
        if not wanted:
            continue
        recipe = cap_recipe(grid)
        sidecar = WORK / f"cap_{grid.name}_params.json"
        if not args.force and cap_is_fresh(recipe, cap_assets(grid), sidecar, cap_sources(grid)):
            print(f"cap {grid.name} fresh -> skip", flush=True)
            continue
        print(f"wrote {render()}", flush=True)
        sidecar.write_text(recipe)  # written AFTER the render, so a crash leaves the cap stale
    CAPS_DIR.mkdir(parents=True, exist_ok=True)
    (CAPS_DIR / "caps.json").write_text(caps_manifest() + "\n")  # the web contract, always current
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
