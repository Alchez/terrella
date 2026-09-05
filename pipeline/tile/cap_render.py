"""Render the polar caps: sea ice + snow over real bathymetry, on AEQD grids reaching the pole.

Web-Mercator tiles die at ~85N (1/cos-phi sends the pole to infinity), so each pole is a
source-shaded polar raster drawn over the globe by a MapLibre custom layer (polarCaps.ts),
feathered into the tiles at the seam. Azimuthal-equidistant, centred on the pole, inscribed
circle at `grid.edge_lat`. Prepares the disc for `cap_raytrace`, which renders it, and writes
`cap_{north,south}_{px}.webp` un-flipped to web/public/caps/ — one file per CAP_RUNGS size —
beside `caps.json`, the contract the web layer fetches (edge_lat, feather ceiling, the rung
list), so no cap constant is hand-copied into TypeScript (see caps_manifest).

This is the shared half rather than a producer: the grid, the warps, the masks, the meridian
rotation, the coastline bake and the rung ladder. `cap_raytrace` renders through them, `prep_cap`
prepares through them.

Both poles share that machinery and source their inputs differently:
  - NORTH: the fused planet VRTs (height/ocean/water) + NSIDC-0791 snow persistence + OSI SAF sea
    ice. The whole cap is >80N, so snow_alpha's Mercator latitude ramp is CONSTANT here (reproduced
    with fixed high-latitude thresholds). Inland water via lake_depth.inland_water (NEVER
    watercode.astype(bool) -- that catches class-1 ocean and flat-fills the Arctic sea, the
    disc-glow bug).
  - SOUTH (Antarctica): the same fused planet VRTs, which reach -90 since the fill. Ocean ->
    bathymetry depth ramp + the SH half of the same sea-ice climatology. Snow is FORCED over
    Antarctic land rather than read per pixel (NSIDC-0791 does cover the continent and saturates
    over it, but 9-14% of that land is clustered fill that RGI region 19's peripheral polygons do
    not reach), via snow.antarctic_snow_mask, shared with the tile tier. The cap mirrors the north
    at `-CAP_EDGE_LAT` and the same feather, covering the last smeared Mercator sliver.

Two cap-specific twists vs the Mercator tiles:
  - the light azimuth rotates with longitude: the tiles light true-NW everywhere, and near the
    pole "NW" turns with the meridian, so the main sun is `AZ + grid.az_sign * lon` per pixel
    (meridian convergence in a polar azimuthal projection = longitude). The sign is -1 north and
    +1 south, the south's coming from its aspect y-flip;
  - SVF is left off (its residual is <1% at the pole). A scalar z-factor is fine: AEQD tangential
    distortion inside the edge latitude is small.

Freshness: each cap is guarded by a recipe sidecar (data/work/cap/cap_<name>_params.json, written by
`cap_raytrace.params`) plus source mtimes; a fresh cap skips. The pass tail invokes the cap pass,
which is what makes the guard run at all.

Usage: GDAL_CACHEMAX=512 uv run python -m pipeline.tile.cap_pass --body earth
       [--north | --south] [--force]
"""
import json
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import numpy as np
import rasterio
from pyproj import Transformer
from scipy.ndimage import (
    binary_dilation,
    gaussian_filter,
    map_coordinates,
    uniform_filter1d,
)

from pipeline import (
    block_plan,
    bodies,
    datasets,
    layers,
    naturalearth,
    planet_seam,
    progress,
    vector_raster,
)
from pipeline.look import (
    lake_depth,
    layer_producers,
    perennial_ice,
    seaice,
)
from pipeline.tile import terrain_rgb

CAP_PX = 8192          # square texture side (south is a bigger disc -> coarser per px). 8192 chosen
                       # by eye (crop A/B + /earth): visibly crisper coast/pack/sastrugi
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
CAP_EDGE_LAT = 82.0    # inscribed-circle latitude of the texture disc, north; the south mirrors it.
                       # The mesh spans this latitude to the pole and samples nothing outside the
                       # disc, so the ladder is
                       # |edge_lat| <= polarCaps.ts MESH_EDGE_LAT <= FEATHER_LO < `feather_hi_deg`.
                       # `test_the_cap_latitude_ladder_holds` is the only reader spanning both
                       # languages, so it is what stops half of it moving.
                       #
                       # It sets the fade's ceiling and the cap's sharpness in opposite directions,
                       # which is the trade that makes it 82. The disc spans this latitude to the
                       # pole, so raising it sharpens the texture (8192 over 8 degrees is 217 m/px,
                       # over 6 degrees 163) while lowering the widest feather that can exist, the
                       # fade being unable to begin equatorward of the disc. At 84 the widest
                       # feather is 1.05 degrees, measured moving 1.7 DN on the north and 3.3 on
                       # the south against the 3.05 that ships.
                       #
                       # Raising it alone cannot ship: polarCaps.ts's two constants must come up
                       # with it, and the ladder above refuses a half-move. Nor does raising CAP_PX
                       # buy a finer cap, Mars's disc already oversampling its 200 m source and
                       # polarCaps.ts's RINGS making the mesh the limit rather than this.
CAP_QUADRANT_SPLIT = 2
                       # Quadrants per edge: the disc renders as SPLIT x SPLIT frames, so 2 means
                       # four.
                       #
                       # A split rather than a resolution, because two numbers derive from it and
                       # must not disagree: each frame is CAP_PX // SPLIT pixels and the camera sees
                       # 1 / SPLIT of the plane, putting `ortho_scale` at 2.0 / SPLIT. Spelled
                       # separately, a frame could ask for a resolution its camera does not cover
                       # and the four pieces would overlap or leave a gap.
                       #
                       # Not 1: CAP_PX in a single frame is OOM-killed at the heavy-job cap,
                       # measured at both edge 82 and 84, where a quadrant peaks near 8 G.
CAP_FEATHER_MIN_DEG = 3.0
                       # The narrowest fade that may ship, in degrees of latitude.
                       #
                       # A floor rather than the value, the ordering ladder above being satisfied
                       # by a feather 0.05 degrees wide that reads as a hard-edged circle over the
                       # tiles. Width is what collapses silently when CAP_EDGE_LAT moves, every
                       # other rung still holding. 3.0 is judged on rendered views at both poles;
                       # 1.05 was judged and rejected.
CAP_MEASURE_BAND_DEGREES = 20.0
                       # Latitude kept either side of the pole when an INSTRUMENT crops a global
                       # raster before warping it onto a cap disc. Nothing shipped reads it and the
                       # two ice reproducers do, which is why it is one name rather than a copy
                       # each. It lives beside CAP_EDGE_LAT because that is what it has to clear:
                       # the disc is inscribed, so the square frame's CORNERS reach sqrt(2) times the
                       # colatitude, and a band narrower than that crops away frame the measurement
                       # then reads as nodata. test_cap_render pins the inequality, since the number
                       # is chosen and the thing it must clear is derived.
CAP_WEBP_QUALITY = 85  # gdal_translate WEBP quality — hero_variants' proven setting; rides in
                       # cap_recipe because the encoder changes the shipped pixels
CAP_ELEV_PX = 512      # elevation texture side; see cap_elev_asset for why there is only one size.
                       # Finer than the mesh that samples it, at every latitude AND at every cap
                       # edge: a ring is CAP_ELEV_PX / (2 * polarCaps.RINGS) = 1.6 texture pixels,
                       # a ratio the disc radius cancels out of, so the mesh stays the limit when
                       # CAP_EDGE_LAT moves. At the shipped edge that reads as 4.34 km/px.
                       # MUST divide CAP_PX exactly — write_cap_elevation box-means by the ratio.
# The AEQD sphere now comes from the body — see `Body.aeqd_radius_m`, which records why it is a
# separate field from the Mercator radius and from MapLibre's globe radius. The warning that used to
# live here lives there, beside the value it is about.
# The south-cap forced-snow latitude and toned sea-ice pair live in their shared homes so the tile
# tier applies the identical rule (one home per concept): `snow.antarctic_snow_mask`'s `lat_max`
# default, and seaice.SH_ICE_LO / seaice.SH_ICE_MAX_ALPHA (used by `south_grid` below).


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
    #: Which planet this cap belongs to. Required, so a second body cannot inherit Earth's sphere
    #: by omission — the AEQD radius below is what turns a texture radius into a latitude, and a
    #: wrong one produces a cap that projects perfectly and lands on the wrong parallel.
    body: bodies.Body
    coast_opacity: float = 0.55  # baked coastline strength over the cap RGB; 0 = skip
    coast_dilate: int = 1        # binary-dilation iterations -> ~3 px line at 4096 when 1
    ice_lo: "float | None" = None         # sea-ice threshold override; None -> seaice.ICE_LO
    ice_max_alpha: "float | None" = None  # sea-ice max opacity override; None -> seaice.ICE_MAX_ALPHA

    @property
    def aeqd(self) -> str:
        radius = self.body.aeqd_radius_m
        return (f"+proj=aeqd +lat_0={self.lat_0} +lon_0=0 "
                f"+a={radius} +b={radius} +units=m +no_defs")

    @property
    def edge_m(self) -> float:
        """Half-width of the square texture, in AEQD metres (radius of the inscribed circle)."""
        return self.body.aeqd_radius_m * float(np.radians(90.0 - abs(self.edge_lat)))


def north_grid(body: bodies.Body) -> CapGrid:
    """This body's north cap grid. A factory rather than a constant: a module-level grid would pin
    `body` at import and every caller downstream would inherit Earth."""
    return CapGrid(lat_0=90.0, edge_lat=CAP_EDGE_LAT, px=CAP_PX, name="north", az_sign=-1.0,
                   body=body)


def south_grid(body: bodies.Body) -> CapGrid:
    """This body's south cap grid.

    No baked coastline. The north needs one (Greenland's white ice sheet abuts the white Arctic
    pack and without a line they merge); here white ice sits on teal ocean, which separates itself,
    and a dark line reads as a cartoonish outline around the continent.

    The opacity is not derived from the body, and the two sea-ice overrides beside it are Earth look
    constants applied to whatever body is passed. Opacity says how strongly a line is drawn if one
    is drawn at all; whether this body has a coastline dataset lives in `Body.surface_layers`, where
    `bakes_coastline` reads it. Deriving one from the other records the same fact twice, as a 0.0
    here and as an entry in the recipe's `layers_off`.
    """
    return CapGrid(lat_0=-90.0, edge_lat=-CAP_EDGE_LAT, px=CAP_PX, name="south", az_sign=1.0,
                   body=body, coast_opacity=0.0, coast_dilate=0,
                   ice_lo=seaice.SH_ICE_LO, ice_max_alpha=seaice.SH_ICE_MAX_ALPHA)

# The coastline baked into the cap texture -- the land/sea line separating land snow from sea ice
# where MapLibre's Mercator vector borders can't reach the pole. It must be DARK, not the globe's
# white coast line: a white line vanishes between white snow and white ice. A muted steel-blue reads
# delicately on both whites without going harsh. Line strength/width are per-cap (CapGrid).
def coast_shp() -> Path:
    """The Natural Earth coastline, resolved on each call so a relocated store reaches it."""
    return naturalearth.layer("ne_10m_coastline")
COAST_RGB = (96, 122, 142)  # muted steel-blue


def bakes_coastline(grid: CapGrid) -> bool:
    """Whether this cap burns the land/sea line into its own pixels: look, then body, then disk.

    The look question answers silently, the south setting `coast_opacity=0.0`; the other two go
    through `layer_is_buildable`, which owns why the body is asked before the disk.

    One predicate, two callers: the render (which draws the line) and `cap_sources` (which makes it a
    freshness dependency). Those must agree, or a cap depends on a file it never opens.
    """
    if grid.coast_opacity <= 0.0:
        return False
    return layers.layer_is_buildable(grid.body, layers.COASTLINE, coast_shp(),
                                     "the cap ships with no land/sea line")


def cap_work_dir(body: bodies.Body) -> Path:
    """This body's cap intermediates: the AEQD warps, the render TIFs, the freshness sidecars.

    The body is in the path, which is why the sidecars here carry no body field: two paths are
    already two files, and the key would restage a full render for byte-identical pixels.
    """
    return bodies.work_dir(body, "cap")


def cap_render_dir(grid: CapGrid) -> Path:
    """The render directory the raytraced arm fills for one pole, under this body's cap work.

    One per pole and kept, unlike a block's, which `block_render` rmtrees after every frame: a pole
    is photographed `CAP_QUADRANT_SPLIT` squared times per azimuth off one set of masks.
    """
    return cap_work_dir(grid.body) / f"render_{grid.name}"


def caps_public_dir(body: bodies.Body) -> Path:
    """Where this body's cap textures are served from, a different root from `cap_work_dir`:
    published assets follow the checkout the site build reads, intermediates follow the relocatable
    data store. Earth's segment is empty, keeping `/caps/caps.json` the URL the frontend fetches."""
    return bodies.public_dir(body, "caps")


def cap_asset(grid: CapGrid, px: int) -> Path:
    """The served file for one rung. Every rung is size-suffixed, including the top one — an
    unsuffixed name would encode 'the big one' as a convention nothing checks."""
    return caps_public_dir(grid.body) / f"cap_{grid.name}_{px}.webp"


def cap_elev_asset(grid: CapGrid) -> Path:
    """The cap's elevation texture: one size, not a rung ladder. The colour rungs answer what a
    phone can resolve, and this is sampled by the cap mesh instead, coarser than this grid by 1.6x
    in rings and ~2.5x in sectors, so a ladder would ship bytes no vertex reads."""
    return caps_public_dir(grid.body) / f"cap_{grid.name}_elev.webp"


def cap_assets(grid: CapGrid) -> list[Path]:
    """Every rung this cap ships, ascending — the freshness gate's asset set.

    The elevation texture is deliberately not here: it is a sibling stage gated on the height warp
    alone, so folding it in would make an encoding change demand a full colour re-render."""
    return [cap_asset(grid, px) for px in CAP_RUNGS]


def cap_warp(grid: CapGrid, layer: str) -> Path:
    """One of this cap's AEQD source warps, named for the pole it belongs to.

    The `capN_`/`capS_` prefix derives from the grid rather than being spelled per call site: a
    literal that disagreed with it writes a file set half-labelled north and half south.
    """
    return cap_work_dir(grid.body) / f"cap{grid.name[0].upper()}_{layer}.tif"


def cap_height_warp(grid: CapGrid) -> Path:
    """The AEQD height warp both the colour disc and the elevation texture read."""
    return cap_warp(grid, "height")


def cap_elev_recipe(grid: CapGrid) -> str:
    """The elevation texture's own recipe sidecar — every writer records its own beside its output.

    Deliberately small: this product depends on the grid, the encoding, and nothing else. It carries
    no look constants at all, because a look change repaints the cap's colour without moving a
    single vertex."""
    return json.dumps({"grid": grid_recipe_fields(grid),
                       "elev": {"px": CAP_ELEV_PX,
                                "step": terrain_rgb.QUANTISATION_M,
                                "sea_clamp": terrain_rgb.SHIPPED_SEA_CLAMP,
                                "base_shift": terrain_rgb.BASE_SHIFT,
                                "format": "webp", "lossless": True}},
                      sort_keys=True, indent=2)


def write_cap_elevation(grid: CapGrid) -> Path:
    """Encode the cap's AEQD elevation as a terrain-RGB texture, for vertex displacement.

    The cap is a CUSTOM layer, and MapLibre never drapes custom layers onto the terrain mesh
    (`LAYERS_TO_TEXTURES` in render_to_texture.ts), so it cannot inherit displacement the way the
    tiles do — it has to carry its own. Without this the cap stays pinned at sea level while
    everything around it lifts, which is the flat bright disc at both poles.

    Encoding is imported from terrain_rgb, never restated. The cap and the tiles are both drawn
    across polarCaps.ts's alpha crossfade, so two surfaces at different heights there ghost against
    each other; identical step and sea treatment is what makes them coincide.

    Downsamples in metres and encodes after, never the reverse: interpolating encoded RGB is wrong
    wherever the low byte wraps, every 256*step metres, so a resampled encode invents cliffs. Same
    rule build_tiles states for the pyramid's overviews.

    True elevation, with no ramp toward the pole. `encode_array` refuses any positional term at all,
    which is what makes "identical encoding" mean identical heights rather than identical bytes: a
    writer that flattened its own metres near the pole would stand kilometres from the surface
    `polarCaps.ts` crossfades it against.
    """
    if CAP_PX % CAP_ELEV_PX:
        raise ValueError(f"CAP_ELEV_PX {CAP_ELEV_PX} must divide CAP_PX {CAP_PX}")
    warp = cap_height_warp(grid)
    if not warp.exists():
        _warp(grid, planet_seam.vrt_path(grid.body, "heightfield"), warp,
              "bilinear", "Float32")
    with rasterio.open(warp) as dataset:
        raw = dataset.read(1)
    heights = cap_heights(grid, raw)

    factor = CAP_PX // CAP_ELEV_PX
    metres = heights.reshape(CAP_ELEV_PX, factor, CAP_ELEV_PX, factor).mean(axis=(1, 3),
                                                                            dtype=np.float32)
    encoded = terrain_rgb.encode_array(metres, terrain_rgb.QUANTISATION_M,
                                       terrain_rgb.SHIPPED_SEA_CLAMP)

    tif = cap_work_dir(grid.body) / f"cap_{grid.name}_elev.tif"
    profile: dict[str, Any] = dict(driver="GTiff", width=CAP_ELEV_PX, height=CAP_ELEV_PX,
                                   count=3, dtype="uint8", photometric="RGB")
    with rasterio.open(tif, "w", **profile) as dataset:
        dataset.write(encoded)
    caps_public_dir(grid.body).mkdir(parents=True, exist_ok=True)
    # Lossless is not an encoder preference here: a lossy elevation texture decodes to plausible
    # bytes and therefore to wrong metres, silently — the same argument TILE_FORMATS makes.
    _run(["gdal_translate", "-q", "-of", "WEBP", "-co", "LOSSLESS=YES",
          str(tif), str(cap_elev_asset(grid))])
    return cap_elev_asset(grid)


def grid_recipe_fields(grid: CapGrid) -> dict:
    """The grid as a freshness recipe: its own fields, minus the body, plus the one body fact that
    can move a cap pixel.

    Not a bare `asdict`, which would inline the whole Body — `path_prefix`, `tile_max_zoom`,
    `map_units_per_pixel` — and restage every cap on an edit that cannot move a cap pixel. The body
    fields that can move one are named singly, here and in `cap_recipe`'s light block, so adding a
    registry field stays free until someone decides it is not.

    `aeqd_radius_m` is named because `asdict` cannot reach it: the projection string is a property
    rather than a field, so a change to it would leave both caps falsely fresh. Same untracked-input
    trap `block_render.params` closes one tier over.
    """
    fields = {key: value for key, value in asdict(grid).items() if key != "body"}
    fields["aeqd_radius_m"] = grid.body.aeqd_radius_m
    smooth = POLE_SMOOTH_BY_BODY.get(grid.body.name)
    # Conditional, on the `layers_off` idiom: a body whose altimetry reached its poles records
    # nothing and keeps the recipe it has. It belongs here rather than in the light block
    # — unlike `ground_scale`, this changes the heightfield itself, so the elevation texture reads it
    # too and must restage with it. `cap_heights` is the one place that applies it, for that reason.
    if smooth is not None:
        fields["pole_smooth"] = asdict(smooth)
    return fields


@dataclass(frozen=True)
class PoleSmooth:
    """How far a body's altimetry failed to reach its own pole, and how hard to smooth inside that.

    Not a cartographic preference: `interpolated_lat` is an orbit. Read the module note.
    """

    interpolated_lat: float
    angle_degrees: float
    isotropic_km: float
    taper_km: float


#: Mars only, and a fact about one spacecraft rather than about poles in general.
#:
#: MGS flew at 92.9 degrees inclination, so MOLA's nadir tracks reached no higher than 87.1. Measured
#: in the MOLA team's own COUNTS_PER_BIN raster, which interpolates nothing: inside that circle
#: **96.5% of bins hold no observation at all**, against 63.7% outside. Every pixel the blend shows
#: there is a spline's opinion about the space between a few off-nadir tracks, and at 20x
#: exaggeration it rendered as a starburst of ridges radiating from the pole.
#:
#: The strength is not "as much as looked good". Smoothing lands the polar interior's directional
#: anisotropy on **0.83**, which is the value undisturbed terrain shows further out on this same
#: cap — so the interior stops being distinguishable from real ground rather than merely looking
#: calmer.
#:
#: A body absent from here is smoothed not at all and records nothing in its recipe. Earth belongs
#: absent: its poles are not reconstructed from an altimeter that missed them.
POLE_SMOOTH_BY_BODY: dict[str, PoleSmooth] = {
    "mars": PoleSmooth(interpolated_lat=87.1, angle_degrees=30.0, isotropic_km=4.0,
                       taper_km=40.0),
}


def cap_heights(grid: CapGrid, raw: np.ndarray) -> np.ndarray:
    """The warped heightfield as every cap consumer must see it: nodata flattened, pole smoothed.

    One owner for both consumers: the rig displaces from this and the elevation texture encodes
    it, and they have to describe one surface.
    """
    heights = np.where(raw < -1e4, 0.0, raw).astype(np.float32)
    return smooth_interpolated_pole(grid, heights)


def _pole_weight(grid: CapGrid, smooth: PoleSmooth, scale: float) -> "tuple[np.ndarray, float]":
    """(strength per pixel, knee radius in px) — full inside the gap, zero outside it.

    The knee comes from the grid's OWN geometry rather than a radius constant: an azimuthal
    equidistant cap is linear in colatitude, so the interpolated boundary sits at a fixed fraction of
    the disc and follows `edge_lat` automatically if it ever moves again.

    A plateau rather than a cone: ramping from the pole outward puts almost no strength at the
    boundary, measured to be exactly where the artifact is strongest.
    """
    knee_px = (90.0 - smooth.interpolated_lat) / (90.0 - abs(grid.edge_lat)) * (grid.px / 2.0)
    taper_px = smooth.taper_km * 1000.0 / scale
    centre = (grid.px - 1) / 2.0
    axis = np.arange(grid.px, dtype=np.float32) - centre
    radius = np.hypot(axis[:, None], axis[None, :])
    t = np.clip((knee_px + taper_px / 2.0 - radius) / taper_px, 0.0, 1.0)
    return (t * t * (3.0 - 2.0 * t)).astype(np.float32), knee_px


def smooth_interpolated_pole(grid: CapGrid, heights: np.ndarray) -> np.ndarray:
    """Replace the interpolator's invented detail with the shape the data actually supports.

    Smoothed by a constant angle, because the artifact is radial: a spoke holds its angular width
    while its arc width grows with radius, so a filter of fixed arc length kills it near the pole
    and misses it further out. A constant-arc version leaves a visible ring.

    The isotropic pass afterwards is what takes the residual the angular pass cannot reach, since a
    boxcar in angle leaves structure aligned with its own window.
    """
    smooth = POLE_SMOOTH_BY_BODY.get(grid.body.name)
    if smooth is None:
        return heights

    scale = cap_ground_metres_per_px(grid)
    weight, knee_px = _pole_weight(grid, smooth, scale)
    outer = knee_px * 1.6  # cover the taper's outer half, which reaches past the knee
    centre = (grid.px - 1) / 2.0

    radii = np.arange(1.0, outer + 2.0, 1.0)
    n_theta = max(64, round(2.0 * np.pi * outer))
    theta = np.linspace(0.0, 2.0 * np.pi, n_theta, endpoint=False)
    rings = map_coordinates(
        heights, [centre - np.outer(radii, np.cos(theta)), centre + np.outer(radii, np.sin(theta))],
        order=1, mode="nearest")
    window = max(3, round(smooth.angle_degrees / 360.0 * n_theta))
    rings = uniform_filter1d(rings, window, axis=1, mode="wrap")

    axis = np.arange(grid.px, dtype=np.float32) - centre
    row, column = axis[:, None] * np.ones_like(axis)[None, :], np.ones_like(axis)[:, None] * axis
    radius = np.hypot(row, column)
    inside = radius <= outer
    angle = np.mod(np.arctan2(column[inside], -row[inside]), 2.0 * np.pi)
    flat = map_coordinates(
        rings, [np.clip(radius[inside] - radii[0], 0.0, len(radii) - 1.0),
                angle / (2.0 * np.pi) * n_theta], order=1, mode="wrap")

    angular = heights.copy()
    angular[inside] = flat
    blended = heights * (1.0 - weight) + angular * weight
    isotropic = gaussian_filter(blended, smooth.isotropic_km * 1000.0 / scale)
    return (blended * (1.0 - weight) + isotropic * weight).astype(np.float32)




def served_url(asset: Path) -> str:
    """The URL a served asset is fetched at, derived from where it was written.

    Not `f"/caps/{asset.name}"`: Earth's path segment is empty so basename and URL coincide, while
    a nesting body would have its whole texture set advertised one directory up, every rung a 404.
    """
    return "/" + asset.relative_to(bodies.public_root()).as_posix()


def feather_hi_deg() -> float:
    """The latitude where the cap goes fully opaque, as an absolute value.

    Derived from where Mercator tiles stop rather than chosen: the fade hides the handover, so a
    ceiling above the grid edge would fade over emptiness.
    """
    return block_plan.MERCATOR_LATITUDE_LIMIT_DEG


def feather_is_wide_enough(feather_lo: float, feather_hi: float) -> bool:
    """Whether this pair leaves a fade at least `CAP_FEATHER_MIN_DEG` wide."""
    return abs(feather_hi) - abs(feather_lo) >= CAP_FEATHER_MIN_DEG


def caps_manifest(body: bodies.Body) -> str:
    """The pipeline->web contract, served beside the textures as caps.json.

    polarCaps.ts used to hand-copy `edge_lat` (as texEdgeLat) and the ±84 feather ceiling
    (the old Mercator plug boundary) as literals — the same copy-drift species as the
    hero/tile colour constants. The web layer now FETCHES this file, so the pipeline is the
    single author of every value it renders into the textures; only frontend aesthetics
    (featherLo, mesh extent) stay web-side.

    `rungs` replaced the old single `url`/`px` pair rather than joining it: two homes for
    'which texture is shipped' is the very drift this contract exists to prevent."""
    return json.dumps({
        grid.name: {"rungs": [{"px": px, "url": served_url(cap_asset(grid, px))}
                              for px in CAP_RUNGS],
                    "edge_lat": grid.edge_lat,
                    "feather_hi": feather_hi,
                    # The displacement texture, its size, and the step needed to decode it. All
                    # three ship here rather than as web-side literals for the same reason edge_lat
                    # does: the pipeline encoded these bytes, so the pipeline states how to read
                    # them. `elev_px` also makes the manifest uniform — every colour rung already
                    # publishes its own `px`, and the elevation texture was the one this contract
                    # named without saying how big it was, which left the web unable to check that
                    # its mesh is coarser than what it samples.
                    "elev_url": served_url(cap_elev_asset(grid)),
                    "elev_px": CAP_ELEV_PX,
                    "elev_step": terrain_rgb.QUANTISATION_M}
        # Signed per pole, because the shader compares |lat| but the manifest describes a hemisphere.
        for grid, feather_hi in ((north_grid(body), feather_hi_deg()),
                                 (south_grid(body), -feather_hi_deg()))
    }, sort_keys=True, indent=2)


def cap_sources(grid: CapGrid, rasters: frozenset[str]) -> list[Path]:
    """The source files whose change must re-render this cap. Constants ride in the raytrace
    recipe; these are the mtime dependencies.

    Only the files this body's cap actually opens. A source listed for a layer the body does not
    have is not merely noise: `cap_is_fresh` requires every source to exist and to be older than
    the oldest rung, so listing Earth's sea-ice climatology for a body that paints no sea ice ties
    that body's caps to the mtime of a file whose contents can never reach a pixel of them. The
    layer's own absence is tracked in `cap_recipe` instead, where turning it off restages once.
    """
    sources = [planet_seam.vrt_path(grid.body, raster)
               for raster in planet_seam.PLANET_RASTERS if raster in rasters]
    if layers.SEA_ICE.name in grid.body.surface_layers:
        sources.append(Path(datasets.seaice_frequency()))
    if layers.ANTARCTIC_ROCK.name in grid.body.surface_layers:
        # Beside `sea_ice` rather than inside the ice producer's own list, which is a correctness
        # boundary: `_cap_perennial_ice` requires every source a producer declares to exist, so a
        # rock entry there would let an undownloaded GeoPackage switch off the forced Antarctic
        # white. Here it is only an mtime, so a re-burn restages the cap and an absence cannot.
        #
        # No pole test, deliberately. Only the south opens the file, so listing it for the north
        # over-tracks by one mtime, a spare re-render at worst. The alternative writes "only
        # Antarctica has Antarctic rock" a second time, outside the registry key that already says
        # it, and under-tracking is the direction that is silent.
        sources.append(datasets.addrock_gpkg())
    if layers.PERENNIAL_ICE.name in grid.body.surface_layers:
        # Asked of the producer rather than spelled out here. A pole test plus Earth's NetCDF would
        # be two of Earth's facts written down as though they were the layer's: that only the north
        # reads a file, and which file. Earth's south genuinely reads none, and a body grading its
        # ice off its own rasters reads several.
        sources.extend(perennial_ice.cap_ice(grid.body, grid.name).sources())
    if bakes_coastline(grid):
        sources.append(coast_shp())
    return sources


def cap_is_fresh(recipe: str, assets: list[Path], sidecar: Path, sources: list[Path]) -> bool:
    """True only when EVERY shipped rung exists, was rendered under exactly this recipe, and is
    newer than every source; anything missing reads stale, failing toward re-rendering rather than
    toward trusting.

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


def cap_ground_metres_per_px(grid: CapGrid) -> float:
    """Ground metres one cap pixel spans, not the AEQD map metres `edge_m` is measured in. The rule
    beside this file owns the two units and why Earth cannot show the difference."""
    return (2.0 * grid.edge_m / grid.px) * bodies.ground_metres_per_aeqd_unit(grid.body)


def cap_reference_grid(grid: CapGrid) -> tuple[int, int, tuple[float, float, float, float]]:
    """This cap's warp target as `(width, height, bounds)`, so a cached raster can be asked which
    disc it covers.

    It cannot tell two bodies apart: every cap AEQD is Earth-sphered, so two planets inscribe the
    identical square and only the work dir separates them.
    """
    edge = grid.edge_m
    return grid.px, grid.px, (-edge, -edge, edge, edge)


def _burn(grid: CapGrid, source: Path, name: str, must_draw: "str | None") -> np.ndarray:
    """Rasterize one vector source onto this cap's AEQD grid; return it as a boolean mask.

    The reproject-then-burn is `vector_raster.burn_onto_grid`, whose module note holds why those are
    one act. Same shape as `_bake_coastline`'s call, which is the reason this is an exposure of an
    existing capability rather than a new one.
    """
    edge = grid.edge_m
    work = cap_work_dir(grid.body)
    burnt = vector_raster.burn_onto_grid(
        source, grid.aeqd, (-edge, -edge, edge, edge), grid.px, grid.px,
        projected=work / f"cap_{grid.name}_{name}_aeqd.gpkg",
        out=work / f"cap_{grid.name}_{name}.tif", must_draw=must_draw)
    with rasterio.open(burnt) as dataset:
        return dataset.read(1) != 0


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


#: The bearing `azimuth_delta` is a delta FROM: the tile side's north-west convention, which the
#: cap's light turns away from as the meridians converge.
#:
#: Owned here because the cap is its only subject. The raytraced disc reads it through the rig,
#: which is handed `index * azimuth_step()` on top of it, so nothing in this process consults the
#: value while it still carries the meaning of the law below: the shape a constant with no reader
#: and no home ends up wrong in.
BASE_AZIMUTH = 315.0


def azimuth_delta(grid: CapGrid, longitude: np.ndarray) -> np.ndarray:
    """How far this disc's light turns from `BASE_AZIMUTH`, at each pixel's longitude.

    Cycles takes one sun direction per frame, so the disc renders as a ring of rigidly rotated
    passes and this decides which two a pixel falls between. One expression, because a rendered
    pass and the blend that samples it must agree on the bearing.
    """
    return grid.az_sign * longitude


def _bake_coastline(grid: CapGrid, rgb: np.ndarray) -> None:
    """Blend the coastline as a subtle dark line over the cap RGB, in place. No-op when the cap opts
    out (`coast_opacity <= 0`, e.g. the south, where white ice on teal ocean self-separates).

    The reproject-then-burn is `vector_raster.burn_onto_grid`, whose module note holds why those are
    one act; a small dilation makes it a ~3 px line rather than a 1 px thread at 4096.
    """
    if not bakes_coastline(grid):
        return
    edge = grid.edge_m
    work = cap_work_dir(grid.body)
    coast_tif = vector_raster.burn_onto_grid(
        coast_shp(), grid.aeqd, (-edge, -edge, edge, edge), grid.px, grid.px,
        projected=work / f"cap_{grid.name}_coast_aeqd.gpkg",
        out=work / f"cap_{grid.name}_coast.tif",
        # A cap that bakes the line has already passed `bakes_coastline`, so the body declares the
        # layer and the shapefile is there. An empty burn past that gate is the projection.
        must_draw=f"{grid.body.name}'s {grid.name} cap coastline")
    with rasterio.open(coast_tif) as dataset:
        line = dataset.read(1) != 0
    if grid.coast_dilate:
        line = binary_dilation(line, iterations=grid.coast_dilate)
    for band in range(3):
        blended = rgb[band][line] * (1.0 - grid.coast_opacity) + COAST_RGB[band] * grid.coast_opacity
        rgb[band][line] = np.rint(blended).astype("uint8")


def write_cap_rungs(grid: CapGrid, tif: Path) -> Path:
    """Downsample one rendered disc into every `CAP_RUNGS` size and return the top rung's path.

    Public because the ladder is not the renderer's: whatever produces a disc hands it here, so the
    encoder, the quality and the resampling stay in one place.
    """
    caps_public_dir(grid.body).mkdir(parents=True, exist_ok=True)
    for px in CAP_RUNGS:
        # -outsize on the render TIF, so every rung is the same picture at a different scale;
        # gdal_translate's average resampling supersamples (4:1 at the 4096 rung).
        size = ["-outsize", str(px), str(px), "-r", "average"] if px != grid.px else []
        _run(["gdal_translate", "-q", "-of", "WEBP", "-co", f"QUALITY={CAP_WEBP_QUALITY}",
              *size, str(tif), str(cap_asset(grid, px))])
    return cap_asset(grid, grid.px)


def finish_disc(grid: CapGrid, rgb: np.ndarray) -> Path:
    """Everything between a disc's finished pixels and its served rungs.

    Public and shared for `write_cap_rungs`' reason, one step earlier: the served disc's last three
    acts belong in one place rather than to whichever caller reaches them.
    """
    # The land/sea line, so the ice sheet reads distinct from sea ice at the pole.
    _bake_coastline(grid, rgb)
    tif = cap_work_dir(grid.body) / f"cap_{grid.name}.tif"
    profile: dict[str, Any] = dict(driver="GTiff", width=grid.px, height=grid.px, count=3,
                                   dtype="uint8", photometric="RGB")
    with rasterio.open(tif, "w", **profile) as dataset:
        dataset.write(rgb)
    return write_cap_rungs(grid, tif)


def _cap_sea_ice(grid: CapGrid, ocean: np.ndarray, consequence: str) -> "np.ndarray | None":
    """This cap's sea-ice alpha, or None when the body has no sea ice — shared by both poles.

    One home because both poles warp the same climatology. The two renderers differ only in their
    `ice_lo` / `ice_max_alpha` overrides, which ride on the grid; writing the gate out twice is how
    a fix reaches one pole and not the other.

    Gated here, because this is where the alpha is made. The disc's own ocean mask is the only one
    on this grid, and a consumer-side gate lets a prep ship an ungated alpha that paints land
    white and flattens it. `tests/test_sea_ice_gate.py` holds the law for both
    producers. None rather than a zero array on the way out: the painter takes `ice_a=None` and
    skips the blend entirely, where zeros would run it and multiply the whole disc by nothing.
    """
    if not layers.layer_is_buildable(grid.body, layers.SEA_ICE, Path(datasets.seaice_frequency()),
                                     consequence):
        return None
    ice_raw = _warp(grid, datasets.seaice_frequency(), cap_warp(grid, "seaice"),
                    "bilinear", "Float32", srcnodata=seaice.ICE_FILL)
    # No latitude term in ice_alpha -> valid on an AEQD grid. The south's fainter, pulled-in fringe
    # comes from the grid's seaice.SH_ICE_* overrides, not from a second code path.
    return seaice.gated_alpha(
        seaice.ice_alpha(seaice.unpack_seaice(ice_raw),
                         ice_lo=grid.ice_lo, ice_max_alpha=grid.ice_max_alpha), ocean)


#: What the cap loses when the outcrop cannot be burnt — the cap tier's `WARP_CONSEQUENCE` entry.
#:
#: Its own sentence rather than the tile one, on `WARP_CONSEQUENCE`'s rule that a consequence is per
#: (layer, stage): the tiles lose rock across the whole continent, this disc loses the fifth of it
#: that sits below −81.
ROCK_CONSEQUENCE = "Antarctic outcrop stays under the forced white on this disc"


def _cap_exclusion(grid: CapGrid, layer: layers.Layer) -> "np.ndarray | None":
    """The mask for one layer this pole declared as an exclusion, or None if it cannot be built.

    A hard error on an undeclared layer, because there is no honest default. A producer naming a
    layer this function has no burn recipe for is a registry that has outgrown its renderer, and the
    silent answer — None, meaning "nothing to exclude" — renders as white over ground the
    declaration says is bare.
    """
    if layer is not layers.ANTARCTIC_ROCK:
        raise KeyError(
            f"{grid.body.name}'s {grid.name} cap declares {layer.name} as a white exclusion and "
            f"this renderer has no burn for it; known: {layers.ANTARCTIC_ROCK.name}")
    return _cap_rock(grid)


def _cap_rock(grid: CapGrid) -> "np.ndarray | None":
    """This cap's exposed-rock mask, or None: asked of the body first and then of the disk.

    Only ever reached from Earth's south, because only that key declares the rock in its
    `CapIce.exclusions`. So the `must_draw` claim is safe: Antarctic outcrop genuinely reaches this
    disc (19.9% of it lies at or below −81), and an empty burn here is a broken projection rather
    than an honest fact about the ground.

    None on either gate, never zeros. The rule this feeds must be able to tell "no rock layer" from
    "no rock", and `snow.antarctic_snow_mask` is built to give today's answer exactly for the first.
    """
    if not layers.layer_is_buildable(grid.body, layers.ANTARCTIC_ROCK,
                                     datasets.addrock_gpkg(), ROCK_CONSEQUENCE):
        return None
    return _burn(grid, datasets.addrock_gpkg(), "addrock",
                 f"SCAR ADD rock outcrop must reach the {grid.name} cap disc")


def _cap_perennial_ice(grid: CapGrid, ocean: np.ndarray, water: np.ndarray, latitude: np.ndarray,
                       consequence: str) -> "tuple[np.ndarray, tuple[Any, Any] | None]":
    """This cap's perennial-ice alpha, from the producer this body registered for this pole.

    One home because both poles ask the same question, exactly as `_cap_sea_ice` does, and here the
    two answers are a NetCDF warp and a latitude rule.

    The disk half asks the producer for its sources, never a module constant, so a body is gated on
    its own data rather than on Earth's. `all(...)` over an empty tuple is True, which is what lets
    Earth's south — latitude and land, no file — pass on the body's declaration alone, with no
    special case.

    Zeros rather than None on the way out, unlike the sea-ice twin: the painter takes `snow_a` as a
    required array and blends it, so an all-zero alpha is the arithmetic saying no pixel is ice,
    where None would be a different function signature."""
    if not (layers.body_declares_layer(grid.body, layers.PERENNIAL_ICE, consequence)
            and all(layers.layer_is_buildable(grid.body, layers.PERENNIAL_ICE, source, consequence)
                    for source in perennial_ice.cap_ice(grid.body, grid.name).sources())):
        return np.zeros((grid.px, grid.px), dtype=np.float32), None
    inputs = perennial_ice.CapIceInputs(
        land=~(ocean | water),  # the tile tier's land definition
        latitude=latitude,
        warp=lambda source, name, resampling, dtype, srcnodata=None: _warp(
            grid, source, cap_warp(grid, name), resampling, dtype, srcnodata),
        burn=lambda source, name, must_draw: _burn(grid, source, name, must_draw),
        ground_metres_per_px=cap_ground_metres_per_px(grid),
    )
    producer = perennial_ice.cap_ice(grid.body, grid.name)
    # Folded by the tile tier's own function, with a one-entry union. The cap has a single white
    # producer, so the maximum is arithmetically a no-op here and the fold is not: it applies the
    # exclusions, and it makes "the two tiers agree across the crossfade" a consequence of shared
    # code rather than a sentence in a docstring.
    # Shaped from the answer rather than from `grid.px`, which would be a second source of truth
    # for something the producer has just stated.
    answer = producer.alpha(inputs)
    alpha, _ = layer_producers.fold_white(
        {layers.PERENNIAL_ICE.name: answer}, answer.shape,
        exclusions={layer.name: mask for layer in producer.exclusions()
                    if (mask := _cap_exclusion(grid, layer)) is not None})
    return alpha, producer.paint()


def _announce(grid: CapGrid, raster: str, consequence: str) -> None:
    """Say what was skipped and what follows from it, the way the layer gates do. Both masks
    announce separately, since a body can switch off one and keep the other."""
    progress.stage(f"{grid.body.name}'s planet stage emitted no {raster} -> "
                   f"{grid.name} cap: {consequence}")


def _cap_masks(grid: CapGrid, rasters: frozenset[str],
               shape: tuple[int, int]) -> tuple[np.ndarray, np.ndarray]:
    """This cap's land/sea and inland-water selectors, warped when the planet has them.

    All-false rather than an all-zero raster on disk, which is the decision the whole planet seam
    turns on. A sea-less body could be handed a synthesised mask and nothing here would change, but
    a file of zeros cannot be told apart from one produced by measuring the planet's oceans and
    finding none, and it would be the only body fact in this project written as a
    fabricated dataset. Derived here from the seam's declaration, it is arithmetic with a premise.

    Gated per raster, not as a pair: Phase 2's chosen shoreline contour gives Mars an ocean mask
    while it still has no inland water, and that combination must not need a code change.

    Both are plain boolean selectors, so all-False means every pixel takes the land ramp — which is
    the answer, not a degraded stand-in for one.
    """
    if "oceanmask" in rasters:
        ocean = _warp(grid, planet_seam.vrt_path(grid.body, "oceanmask"),
                      cap_warp(grid, "ocean"), "near", "Byte") != 0
    else:
        _announce(grid, "oceanmask", "every pixel takes the land ramp")
        ocean = np.zeros(shape, dtype=bool)
    if "watermask" in rasters:
        water = lake_depth.inland_water(
            _warp(grid, planet_seam.vrt_path(grid.body, "watermask"),
                  cap_warp(grid, "water"), "near", "Byte"))
    else:
        _announce(grid, "watermask", "no lake or river is drawn")
        water = np.zeros(shape, dtype=bool)
    return ocean, water


