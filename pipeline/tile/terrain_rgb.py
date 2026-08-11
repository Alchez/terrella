"""Terrain-RGB elevation tiles — the Tier-3 displacement source.

Sibling of `shade_planet.py`, and deliberately NOT part of it: that module cuts *colour*, this
one cuts *elevation*. They share one input (`height_3857.tif`), one tiling scheme, and the
stage-freshness primitives, which live in `pipeline/freshness.py` and belong to neither stage.
Nothing about the LOOK crosses over. MapLibre consumes this as a second `raster-dem` source with
its own `maxzoom`, so the two pyramids need not be the same depth.

THE ONE TRAP THIS MODULE EXISTS TO AVOID
----------------------------------------
Elevation packed into RGB is not an image. The value is `R*256 + G - 32768`, so the green byte
WRAPS every 256 metres — and interpolating across a wrap invents a 256 m cliff. That makes every
smooth resampler wrong on this data: `average`, `cubic`, `bilinear`, `lanczos` all mix bytes.
`shade_planet.tile_cut` uses `cubic` for both the cut and its overviews, which is correct for
colour and catastrophic here.

So the pyramid is built **per zoom, from elevation downsampled in elevation space**, and each
zoom is cut on its own with `nearest` (a no-op at 1:1). Nothing ever resamples encoded bytes.

ENCODING
--------
Mapzen terrarium with the blue channel zeroed: `elevation = R*256 + G - 32768`, one metre per
step. Blue carries terrarium's 1/256 m fraction, which at 305 m/px is pure noise — measured 2.5x
larger for information the grid cannot hold, so it is written as a constant and compresses away.

`step` widens that to `R*256*step + G*step - 32768`, which MapLibre reads as `encoding: "custom"`
with `redFactor = 256*step, greenFactor = step, blueFactor = 0, baseShift = 32768`. At `step = 1`
this is bit-for-bit standard terrarium, so the default needs no custom fields at all.

FRESHNESS
---------
Two guards, because this stage has two kinds of output and they fail differently.

The elevation chain is stamped with `.done` markers rather than tested with `exists()`, per
`freshness.is_stale`. This stage is where that rule was paid for: a BigTIFF crash left a
full-sized, freshly-stamped, half-written `elev_z8.tif` on disk, and an existence test would have
built the entire pyramid on top of it, silently, since a truncated float32 raster reads as a very
flat planet rather than as an error.

The pyramid itself is cut into a staging dir and swapped, and keyed on the master's marker plus
`terrain_params.json`. The recipe is the load-bearing half: the variant DIRECTORY name carries
only sea treatment, step and feather, so without a sidecar a `--format` or `--max-zoom` change is
invisible to every guard and to anyone reading the store.
"""

import argparse
import json
import shutil
import subprocess
from pathlib import Path

import numpy as np
import rasterio

from pipeline import bodies, mercator
from pipeline.freshness import (
    done_marker,
    is_stale,
    mark_done,
    write_if_changed,
)
from pipeline.raster_io import GTIFF_CREATE, band_window, row_bands

TILE_SIZE = 512

#: Terrarium's zero point. Elevation `e` at quantisation `step` stores as `(e + 32768) / step`.
BASE_SHIFT = 32768.0

#: Metres per encoded level, and the sea treatment, for everything this project ships. Module
#: constants rather than bare argparse defaults because they are no longer read only here: the polar
#: caps carry their own elevation texture and MUST encode identically, or cap and tiles displace to
#: different heights across the alpha crossfade and ghost against each other. Two spellings of one
#: number is the copy-drift that bit the hero/tile colour constants four times.
#: 8 m is the ratified knee (0.49x the archive; the error lands in mountains, not on plains) and
#: bathymetry is ratified over sea-clamping, so the sea displaces rather than reading as a wall.
#:
#: SHIPPED_SEA_CLAMP NAMES WHAT IS ON THE WIRE, and `--sea` now derives its default from it rather
#: than restating one. It restated the opposite for a while, so the bare command rebuilt a pyramid
#: the live one had not been cut with — the trap this constant existed to warn about, closed by
#: making the two the same fact. Do not spell the default out again.
#:
#: The clamp stops being a look question entirely on a body with no sea: every point below zero
#: there is real ground, and flattening it deletes the deepest basin on the planet.
QUANTISATION_M = 8.0
SHIPPED_SEA_CLAMP = False

#: Delivery codecs, as (GDAL driver, creation options). BOTH ARE LOSSLESS AND MUST STAY SO — a
#: lossy tile decodes to plausible bytes and therefore to wrong metres, with nothing to see. This
#: is purely an entropy-coder choice over identical pixels: lossless WebP measured 0.66x PNG over
#: 40 real z6 tiles (3.08 -> 2.04 MB) and round-tripped byte-exact, so it is a free third of the
#: archive on top of whatever `--step` buys.
TILE_FORMATS = {
    "png": ("PNG", ["ZLEVEL=9"]),
    "webp": ("WEBP", ["LOSSLESS=YES"]),
}

#: Latitude band over which encoded elevation ramps to zero, so the tiles flatten into the polar
#: caps. The caps are a CUSTOM layer and MapLibre does not drape custom layers onto the terrain
#: mesh (`LAYERS_TO_TEXTURES` in render_to_texture.ts), so displaced tiles under an undisplaced
#: cap would open a geometric seam — worst in the south, where this band is 2-3 km of Antarctic
#: ice. `polarCaps.ts` feathers its alpha over the same latitudes; this is the geometric twin.
FEATHER_LAT_LO = 78.0
FEATHER_LAT_HI = 85.0

def _run(cmd) -> None:
    subprocess.run([str(part) for part in cmd], check=True)


def grid_size(zoom: int) -> int:
    """Pixel width of the whole world at `zoom`, for 512 px tiles."""
    return TILE_SIZE * 2**zoom


def master_zoom_for(body: bodies.Body) -> int:
    """Native grid zoom of this body's `height_3857.tif` — 512 px x 2^n — and so the deepest
    terrain zoom there is to cut.

    DERIVED RATHER THAN STORED, because the chain that makes deriving safe already has two owners
    and a third copy of the number is exactly the drift they exist to prevent. `shade_planet` warps
    the master at `body.map_units_per_pixel` and rebuilds it whenever the raster's own pixel size
    disagrees, so the file matches the field; `test_bodies` then pins that field against
    `tile_max_zoom` relationally, at a tolerance that admits Earth's rounded value and cannot admit
    a factor of two.

    IT USED TO BE A MODULE CONSTANT HOLDING EARTH'S CEILING, and the reason that was dangerous
    rather than merely wrong is that `build` does ARITHMETIC with it: the master is halved by
    `2 ** (master_zoom - max_zoom)`. Against a body whose master is one level shallower, Earth's
    number asks for a factor of two where the answer is one — which raises nothing, reads as a
    normal run, and emits a pyramid at half the resolution its own recipe claims.
    """
    return body.tile_max_zoom


def out_under_body(body: bodies.Body, out: Path) -> Path:
    """`out` resolved, having checked it lands in THIS body's terrain stage. Raises if it does not.

    The variant directory below the stage is operator-named, so the destination cannot be derived —
    but it can be bounded, and the bound is the failure worth catching. Pointing a Mars cut at
    Earth's tree writes Martian elevation into the directory the packer reads for Earth, and the
    tiles look exactly like tiles.

    Earth's empty `path_prefix` is why the bound is the STAGE directory rather than the body's
    root: `data/work` contains every planet's tree, so a containment test one level up would pass
    for both bodies and guard nothing. `data/work/planet_terrain` and `data/work/mars/planet_terrain`
    contain neither the other.
    """
    stage = bodies.work_dir(body, "planet_terrain").resolve()
    resolved = out.resolve()
    if resolved != stage and stage not in resolved.parents:
        raise SystemExit(f"--out {out} is not under {body.name}'s terrain stage ({stage}) — a cut "
                         f"written outside it lands in another planet's tree, or somewhere the "
                         f"packer will never look")
    return resolved


def master_grid_mismatch(master: Path, master_zoom: int) -> str | None:
    """Why `master` is not the 512 x 2^`master_zoom` grid it was declared to be, or None.

    The declaration comes from the body and this is where it meets the artifact, which is the one
    check that can catch the failure above. Everything downstream of a wrong `master_zoom` succeeds:
    the downsample runs, every zoom encodes, every tile writes, and the recipe beside them records
    the ceiling that was asked for rather than the one that was cut.

    A STRING RATHER THAN AN ASSERT so the caller decides what to do with it, and so a test can read
    the sentence instead of matching an exception's text.
    """
    with rasterio.open(master) as raster:
        width, height = raster.width, raster.height
    expected = grid_size(master_zoom)
    if width == expected and height == expected:
        return None
    return (f"{master} is {width}x{height}, not the {expected}x{expected} grid of a "
            f"{TILE_SIZE}px tile at z{master_zoom} — the descent would resample by the wrong "
            f"factor and emit a pyramid at the wrong resolution without failing")


def row_latitudes(row0: int, row1: int, height: int, north: float, south: float) -> np.ndarray:
    """Latitude (degrees) at the centre of each raster row in [row0, row1).

    Rows are inverse-Mercator projected rather than linearly interpolated: latitude is not linear
    in y, and the whole point of the feather is that it lands on the right parallels.
    """
    rows = np.arange(row0, row1, dtype=np.float64) + 0.5
    y = north - rows * (north - south) / height
    return mercator.latitude_at(y, mercator.WEB_MERCATOR_RADIUS_M)


def feather_factor(latitudes: np.ndarray) -> np.ndarray:
    """1.0 equatorward of FEATHER_LAT_LO, 0.0 poleward of FEATHER_LAT_HI, smoothstep between.

    Smoothstep rather than linear because this multiplies GEOMETRY: a linear ramp leaves a slope
    discontinuity at each end of the band, and a crease in a displacement mesh is visible in a way
    a crease in an alpha ramp is not.
    """
    span = np.clip(
        (FEATHER_LAT_HI - np.abs(latitudes)) / (FEATHER_LAT_HI - FEATHER_LAT_LO), 0.0, 1.0)
    return span * span * (3.0 - 2.0 * span)


#: Source rows held in memory at once by `downsample_elevation`. Budgeted on the SOURCE side, not
#: the output side: a band of N output rows reads `N * factor` source rows, so a fixed output band
#: silently scales peak RAM with the downsample factor — at the master's width, 256 output rows at
#: factor 64 would be 8.6 GB, against a 12 G cap. 2048 master rows is ~1.07 GB.
SOURCE_ROW_BUDGET = 2048


def downsample_elevation(src: Path, dst: Path, factor: int, band_rows: int | None = None) -> None:
    """Box-mean `src` down by an integer `factor`, in metres — never in encoded bytes.

    Streams full-width bands so peak RAM is bounded by SOURCE_ROW_BUDGET source rows rather than by
    the raster: the master is 131072^2 float32 (46 GB), which no cgroup cap here would hold.
    """
    if band_rows is None:
        band_rows = max(1, SOURCE_ROW_BUDGET // factor)
    with rasterio.open(src) as source:
        out_height = source.height // factor
        out_width = source.width // factor
        # BIGTIFF is required past z6 and cannot be left to the default. A classic TIFF caps at
        # 4 GB, and this sink is float32: z7 is 65536^2 = 17.2 GB raw and z8 is 131072^2 = 68.7 GB,
        # so both die mid-write with "Maximum TIFF file size exceeded" after burning the whole
        # descent. z6 only survives because deflate lands it at 3.4 GB — 4.29 GB raw, i.e. already
        # inside 20% of a hard failure. IF_SAFER rather than YES so small levels stay classic.
        profile = source.profile | GTIFF_CREATE | {
            "height": out_height, "width": out_width, "dtype": "float32", "count": 1,
            "bigtiff": "IF_SAFER",
            "transform": source.transform * source.transform.scale(factor, factor)}
        with rasterio.open(dst, "w", **profile) as sink:
            for out0, out1 in row_bands(out_height, band_rows):
                block = source.read(
                    1, window=band_window(source.width, out0 * factor, out1 * factor))
                block = np.nan_to_num(block.astype(np.float32), nan=0.0)
                rows = block.reshape(out1 - out0, factor, out_width, factor)
                sink.write(rows.mean(axis=(1, 3), dtype=np.float32),
                           1, window=band_window(out_width, out0, out1))


def encode_array(elevation: np.ndarray, step: float, sea_clamp: bool,
                 latitudes: np.ndarray | None = None) -> np.ndarray:
    """Pack metres into the (3, h, w) uint8 terrarium-with-zero-blue form described in the header.

    `sea_clamp` raises everything below zero to zero — land rises out of a smooth sphere, which is
    what a physical relief globe does, and what stops a continental shelf reading as a cliff wall.
    It is also most of the archive: an abyssal tile measured 162 KiB carrying real bathymetry and
    1.5 KiB flat.
    """
    metres = np.nan_to_num(elevation.astype(np.float64), nan=0.0)
    if sea_clamp:
        metres = np.maximum(metres, 0.0)
    if latitudes is not None:
        metres = metres * feather_factor(latitudes)[:, None]
    packed = np.clip(np.round((metres + BASE_SHIFT) / step), 0, 65535).astype(np.uint16)
    return np.stack([(packed >> 8).astype(np.uint8), (packed & 0xFF).astype(np.uint8),
                     np.zeros(packed.shape, np.uint8)])


def decode_array(encoded: np.ndarray, step: float) -> np.ndarray:
    """Inverse of `encode_array`, in the exact form MapLibre applies it (dem_data.ts `unpack`).

    Written so the oracle is an independent statement of the decode rather than a rearrangement of
    the encode: it multiplies out the same factors the style would carry.
    """
    red, green, blue = (band.astype(np.float64) for band in encoded)
    return red * (256.0 * step) + green * step + blue * 0.0 - BASE_SHIFT


def encode_raster(elev_tif: Path, dst: Path, step: float, sea_clamp: bool,
                  feather: bool = True, band_rows: int = 512) -> None:
    """Encode a whole elevation raster to a 3-band Byte GTiff, streaming by row band."""
    with rasterio.open(elev_tif) as source:
        north, south = source.bounds.top, source.bounds.bottom
        # Same 4 GB ceiling as the elevation sink above: three uint8 bands at z8 is 51.5 GB raw.
        profile = source.profile | GTIFF_CREATE | {
            "dtype": "uint8", "count": 3, "nodata": None, "bigtiff": "IF_SAFER"}
        with rasterio.open(dst, "w", **profile) as sink:
            for row0, row1 in row_bands(source.height, band_rows):
                window = band_window(source.width, row0, row1)
                latitudes = (row_latitudes(row0, row1, source.height, north, south)
                             if feather else None)
                sink.write(encode_array(source.read(1, window=window), step, sea_clamp, latitudes),
                           window=window)


def cut_zoom(src: Path, staging: Path, zoom: int, tile_format: str = "png") -> None:
    """Cut exactly one zoom from a source already on that zoom's grid.

    `nearest` everywhere: at 1:1 it is a copy, and it is the only resampler that cannot mix the
    encoded bytes (see the module header). `--min-zoom == --max-zoom` means no overview level is
    ever generated from tiles — each zoom comes from its own correctly-downsampled elevation.
    """
    driver, creation_options = TILE_FORMATS[tile_format]
    co = [argument for option in creation_options for argument in ("--co", option)]
    _run(["gdal", "raster", "tile", f"--min-zoom={zoom}", f"--max-zoom={zoom}",
          f"--tile-size={TILE_SIZE}", "--resampling=nearest", "--overview-resampling=nearest",
          "--convention=xyz", f"--format={driver}", *co, "--webviewer=none",
          str(src), str(staging)])


def terrain_params(max_zoom: int, step: float, sea_clamp: bool, feather: bool,
                   tile_format: str) -> str:
    """The cut's own settings, recorded beside the pyramid as its freshness dependency.

    Everything listed alters the emitted bytes and nothing outside it does — the master and the
    output dir are `is_stale`'s own arguments, not settings. The polar feather latitudes and the
    terrarium zero point are in here because they are module CONSTANTS: they have no other file to
    move an mtime, so editing one would otherwise restage nothing while changing every tile.
    """
    driver, creation_options = TILE_FORMATS[tile_format]
    return json.dumps({
        "max_zoom": max_zoom,
        "step": step,
        "sea_clamp": sea_clamp,
        "feather": feather,
        "tile_size": TILE_SIZE,
        "format": driver,
        "creation_options": creation_options,
        "base_shift": BASE_SHIFT,
        "feather_lat_lo": FEATHER_LAT_LO,
        "feather_lat_hi": FEATHER_LAT_HI,
    }, sort_keys=True, indent=2)


def terrain_params_path(out: Path) -> Path:
    """Where the cut's recipe is recorded, beside the pyramid it describes."""
    return out / "terrain_params.json"


def tiles_are_fresh(out: Path, master: Path) -> bool:
    """True if the live pyramid is current: present, non-empty, and stamped newer than BOTH the
    master it descends from and the recipe that describes it.

    Keyed off the master's `.done` marker, never its `.tif` — GDAL and rasterio both stamp a target
    at write-start, which is the trap `is_stale` exists to avoid. The non-empty test rejects a
    half-swapped directory, and a missing master marker is treated as "cannot know" rather than
    "fresh", so an unstamped source always re-cuts.
    """
    live = out / "tiles"
    return (live.is_dir() and any(live.iterdir())
            and done_marker(master).exists()
            and not is_stale(live, done_marker(master), terrain_params_path(out)))


def elevation_source(work: Path, zoom: int, master: Path, master_zoom: int) -> Path:
    """The elevation raster for `zoom` — THE MASTER ITSELF at its native zoom.

    `height_3857.tif` is already 512 x 2^`master_zoom`, so "downsampling" to that zoom is a box-mean
    by a factor of 1: the identity. Materialising it wrote a 47 GB byte-for-value copy of a file
    already on disk, on every build, and the only transform it applied was NaN -> 0, which
    `encode_array` applies again regardless. Verified over six windows from Everest to the Pacific
    abyss at max |master - copy| of exactly 0.0000 m, with shifted-window controls differing by
    240-1660 m so the comparison could actually fail.
    """
    return master if zoom == master_zoom else work / f"elev_z{zoom}.tif"


def build(out: Path, max_zoom: int, step: float, sea_clamp: bool, feather: bool,
          master: Path, master_zoom: int, work: Path | None = None,
          keep_intermediates: bool = False, tile_format: str = "png") -> Path:
    """Build a complete z0..max_zoom terrain-RGB pyramid under `out`, returning the tile dir.

    The elevation chain is built once at `max_zoom` and halved from there, so the expensive read of
    the 46 GB master happens exactly once no matter how many zooms are cut. `work` is separable
    from `out` for the same reason: two encodings of the same planet (sea clamped vs bathymetry)
    differ only after the elevation exists, so the second variant must not pay for it again.

    `tile_format` deliberately does NOT appear in the intermediate name: the encoded raster is
    identical whatever codec the tiles are written in, so re-cutting a built variant into another
    lossless format costs one encode pass, not another descent from the master.

    Recipe-gated in the usual order — see `freshness.write_if_changed`, and the module header's
    FRESHNESS section for what each of this stage's two guards catches.

    EVERY CUT IS A CLEAN FULL CUT into `tiles_new`, swapped over `tiles` only on success, with one
    generation of rollback at `tiles_old`. GDAL writes each tile in place, so a run killed mid-cut
    leaves truncated files; re-cutting from empty is the price of never trusting a partial tile.
    """
    out.mkdir(parents=True, exist_ok=True)
    write_if_changed(terrain_params_path(out),
                     terrain_params(max_zoom, step, sea_clamp, feather, tile_format))
    tiles = out / "tiles"
    if tiles_are_fresh(out, master):
        print(f"terrain tiles fresh -> skip cut ({tiles})", flush=True)
        return tiles

    work = work or out / "work"
    work.mkdir(parents=True, exist_ok=True)
    variant = f"{'sea0' if sea_clamp else 'bathy'}_s{step:g}{'' if feather else '_nofeather'}"

    top = elevation_source(work, max_zoom, master, master_zoom)
    if top != master and is_stale(top, done_marker(master)):
        factor = 2 ** (master_zoom - max_zoom)
        print(f"downsample master /{factor} -> {grid_size(max_zoom)}^2 ...", flush=True)
        downsample_elevation(master, top, factor)
        mark_done(top)

    staging = out / "tiles_new"
    if staging.exists():
        shutil.rmtree(staging)   # a partial from a prior mid-cut crash: never resume over it
    staging.mkdir(parents=True)

    for zoom in range(max_zoom, -1, -1):
        level = elevation_source(work, zoom, master, master_zoom)
        if zoom < max_zoom:
            parent = elevation_source(work, zoom + 1, master, master_zoom)
            if is_stale(level, done_marker(parent)):
                downsample_elevation(parent, level, 2)
                mark_done(level)
        encoded = work / f"rgb_{variant}_z{zoom}.tif"
        encode_raster(level, encoded, step, sea_clamp, feather)
        print(f"z{zoom}: encoded {grid_size(zoom)}^2 -> cutting ...", flush=True)
        cut_zoom(encoded, staging, zoom, tile_format)
        if not keep_intermediates:
            encoded.unlink()

    if tiles.exists():
        previous = out / "tiles_old"
        if previous.exists():
            shutil.rmtree(previous)
        tiles.rename(previous)
    staging.rename(tiles)
    mark_done(tiles)
    print(f"tiles live -> {tiles} (previous kept at {out / 'tiles_old'})", flush=True)
    return tiles


def build_parser() -> argparse.ArgumentParser:
    """The CLI, separable from `main` so its defaults are assertable without running a cut.

    `cap_ladder` and `pack_pmtiles` split theirs for the same reason: the interesting properties
    here are what happens when a flag is OMITTED, and that is unreachable through a function whose
    next statement reads a 46 GB raster.
    """
    ap = argparse.ArgumentParser(description=__doc__)
    # REQUIRED, WITH NO DEFAULT, exactly as shade_planet's is and for the same reason: a pass that
    # assumes Earth because nobody said otherwise does not fail, it emits a complete and plausible
    # pyramid for the wrong planet. Here it decides four things at once — the master, where the
    # output lands, the ceiling cut to, and the descent's factor.
    ap.add_argument("--body", required=True,
                    help=f"which planet this cut is for ({', '.join(sorted(bodies.BODIES))})")
    # STILL REQUIRED, AND DELIBERATELY NOT DEFAULTED TO THE STAGE DIRECTORY. The live pyramid sits
    # one level further down, in an operator-named variant directory (`<sea><step><format>`), and
    # that name is a choice rather than a derivation — the module header records that the name
    # carries only part of the recipe, which is why the sidecar exists. A default would therefore
    # not have pointed at the live pyramid: it would have built a second one beside it, found the
    # first "missing", and left the packer reading whichever the operator remembered.
    # It is checked against the body instead, below, which is the half that was actually unsafe.
    ap.add_argument("--out", type=Path, required=True,
                    help="pyramid root, under this body's planet_terrain dir (tiles/ inside)")
    ap.add_argument("--work", type=Path, default=None,
                    help="elevation-chain dir; share it across variants to read the master once")
    ap.add_argument("--master", type=Path, default=None)
    ap.add_argument("--max-zoom", type=int, default=None)
    ap.add_argument("--step", type=float, default=QUANTISATION_M,
                    help="metres per encoded level")
    # DEFAULTS TO WHAT IS ON THE WIRE, which it did not: the choice defaulted to "clamp" while the
    # shipped recipe records the opposite, so the bare command rebuilt a pyramid that was not the
    # live one. Deriving it from SHIPPED_SEA_CLAMP is what makes the two agree by construction —
    # and the clamp is not merely a look question on a body with no sea, where every point below
    # zero is real ground and flattening it deletes the deepest basin on the planet.
    ap.add_argument("--sea", choices=["clamp", "bathy"],
                    default="clamp" if SHIPPED_SEA_CLAMP else "bathy",
                    help="clamp: sea flattened to 0; bathy: seafloor displaced too")
    ap.add_argument("--no-feather", action="store_true",
                    help="skip the polar ramp (only for isolating the cap seam)")
    ap.add_argument("--format", choices=sorted(TILE_FORMATS), default="webp",
                    help="delivery codec; both lossless, webp is ~0.67x png")
    ap.add_argument("--keep-intermediates", action="store_true")
    return ap


def main() -> None:
    args = build_parser().parse_args()
    body = bodies.BODIES[args.body]
    master = args.master or bodies.work_dir(body, "planet_tiles") / "height_3857.tif"
    out = out_under_body(body, args.out)
    native = master_zoom_for(body)
    # THE ONE PLACE THE DECLARATION MEETS THE ARTIFACT. Every failure a wrong `native` causes is
    # silent downstream — see `master_grid_mismatch` — so it is checked here, before the descent
    # that would encode it into every tile and into the recipe beside them.
    mismatch = master_grid_mismatch(master, native)
    if mismatch:
        raise SystemExit(mismatch)

    tiles = build(out, args.max_zoom if args.max_zoom is not None else native,
                  args.step, args.sea == "clamp",
                  not args.no_feather, master, native, args.work, args.keep_intermediates,
                  args.format)
    count = sum(1 for _ in tiles.rglob(f"*.{args.format}"))
    size = sum(path.stat().st_size for path in tiles.rglob(f"*.{args.format}"))
    print(f"{count} tiles, {size / 1e9:.2f} GB -> {tiles}", flush=True)


if __name__ == "__main__":
    main()
