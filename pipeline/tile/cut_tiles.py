"""Cut a body's finished colour raster into 512px WebMercatorQuad tiles.

Tiles run z0 to THIS BODY's ceiling, the body saying so rather than this module, and there is no
overview step because `gdal raster tile` never reads them (see `build_tiles`).

THIS IS THE SECOND OF THE TWO PLANET STAGES AND IT IS NOT AN ENTRY POINT. `tile/planet_pass.py`
owns the sequence; `planet_warp.py` is the other end, and it runs hours earlier. The two lived in
one module called `shade_planet` because a windowed numpy composite stood between them and they
were its input and output stages. That shader is deleted, and with it the only thing the two halves
had in common.

The cut skips if its output is FRESH -- present, non-empty, and stamped newer than both the raster
that feeds it and the recipe that describes it (`tiles_are_fresh`). An exists()-only guard cannot
tell "built" from "still correct".

    python -m pipeline.tile.planet_pass --body earth            # produce only
    python -m pipeline.tile.planet_pass --body earth --tiles    # + cut tiles
"""

import json
import subprocess
from pathlib import Path
from typing import TypedDict

from pipeline import bodies, progress
from pipeline.freshness import done_marker, is_stale, mark_done, write_if_changed


def _run(cmd):
    subprocess.run([str(part) for part in cmd], check=True)


#: The shaded colour raster the tile cut reads, whatever produced it.
#:
#: NAMED HERE BECAUSE THE WRITER AND THE READERS ARE DIFFERENT MODULES. `tile.block_render` renders
#: it block by block, while the tile cut, the freshness marker and the publish all key on this one
#: basename — so it is exactly the kind of spelling a writer would otherwise copy. It was named here
#: when the raster had two producers, and one owner is still right with one.
PLANET_RGB = "planet_rgb.tif"


class TileCut(TypedDict):
    """Every setting of the tile cut that changes the bytes GDAL writes.

    A TypedDict for the reason `Knobs` is one: it is consumed both as a command line and as a JSON
    freshness record, and a plain dict would infer `str | int | bool` for every value, so a typo'd
    key or a quality read as a string would only surface as a wrong pyramid.
    """
    format: str
    quality: int
    tile_size: int
    min_zoom: int
    max_zoom: int
    resampling: str
    overview_resampling: str
    convention: str
    skip_blank: bool


# WebP q95 replaced PNG. Measured on 73 tiles sampled proportionally across all nine
# zooms: q95 is 20.0% of PNG byte-weighted, and z8 -- three quarters of the pyramid -- is the
# cheapest at 14.8%, so the aggregate is conservative. The archive goes ~16 GB -> ~3.2 GB and the
# Worker's single R2 read per cold tile drops with it (~380 ms -> ~80 ms, it is bandwidth-bound).
def tile_cut(body: bodies.Body) -> TileCut:
    """This body's cut settings — eight encoder facts that are the same everywhere, and its ceiling.

    A FUNCTION RATHER THAN A CONSTANT because exactly one of these keys belongs to the planet.
    `max_zoom` was a literal 8 here, which is Earth's ceiling and nobody else's, and it is the
    second of the two constants that survived the body parameterisation by having no field to be
    bridged to. The other seven are properties of the encoder and the tile scheme, so they stay
    written once here rather than being copied onto every body — a body answers for what differs
    about it, not for what does not.

    Earth's result is the same dict the constant held, so `tile_params` still serialises the exact
    bytes beside the live pyramid and the cut does not restage.
    """
    return TileCut(format="WEBP", quality=95, tile_size=512, min_zoom=0,
                   max_zoom=body.tile_max_zoom,
                   resampling="cubic", overview_resampling="cubic", convention="xyz",
                   skip_blank=True)


def tile_params(body: bodies.Body) -> str:
    """The tile cut's own settings, recorded as the live pyramid's dependency.

    This stage used to key freshness off `planet_rgb` ALONE, which meant the cut was the
    one stage that could not see its own recipe: changing the output format left `tiles_are_fresh`
    true, so the PNG->WebP switch would have silently shipped the old pyramid. Everything in
    the cut alters the emitted bytes, and nothing outside it does — the input raster and the output
    directory are `is_stale`'s own arguments, not settings.

    The BODY is not recorded here and must not be: each body writes this file into its own work
    tree, so the recipe is already body-specific by location, and adding the name would restage
    Earth's entire pyramid the day a second planet existed for no pixel change at all.
    """
    return json.dumps(tile_cut(body), sort_keys=True, indent=2)


def tile_params_path(out: Path) -> Path:
    """Where the cut's recipe is recorded, beside the pyramid it describes."""
    return out / "tile_params.json"


def _tile_cmd(planet_tif: Path, staging: Path, body: bodies.Body) -> list[str]:
    """The `gdal raster tile` invocation that cuts this body's 512px tiles into `staging`.

    Built FROM `tile_cut` rather than from literals, so the command and the freshness record cannot
    disagree about what was cut — the same one-fact-one-spelling rule pack_pmtiles now follows for
    the tile encoding.

    `--overview-resampling=cubic` pins what is otherwise an UNDOCUMENTED default -- identified by
    elimination: unset, it silently inherits `--resampling`. This is byte-identical to
    today and is what built the verified 07-14 pyramid, so it is a pin, not a change. z0-7 carry
    most of the globe's zoomed-out surface; they should not ride on a default GDAL may alter.

    `--webviewer=none`: the default is `all`, which emits leaflet/openlayers/mapml/stac files into
    the pyramid. We serve our own MapLibre page, and they would ride into PMTiles.

    NO `--resume` (removed): GDAL skips existing files by existence without reading them,
    so a truncated tile from a mid-write kill would survive a resume. build_tiles instead removes
    any partial staging dir and cuts clean every time -- see its docstring.
    """
    cut = tile_cut(body)
    cmd = ["gdal", "raster", "tile",
           f"--min-zoom={cut['min_zoom']}", f"--max-zoom={cut['max_zoom']}",
           f"--tile-size={cut['tile_size']}",
           f"--resampling={cut['resampling']}",
           f"--overview-resampling={cut['overview_resampling']}",
           f"--convention={cut['convention']}",
           f"--format={cut['format']}", "--co", f"QUALITY={cut['quality']}"]
    if cut["skip_blank"]:
        cmd.append("--skip-blank")
    return [*cmd, "--webviewer=none", str(planet_tif), str(staging)]


def tiles_are_fresh(planet_tif: Path, out: Path) -> bool:
    """True if the live pyramid is current: present, non-empty, and stamped newer than BOTH the
    raster that feeds it and the recipe that describes it.

    Keyed off `planet_rgb`'s `.done` marker, NOT the `.tif` (GDAL stamps its target at write-start,
    the trap `is_stale` exists to avoid). `is_stale(live, ...)` stats only `tiles/` + `tiles.done` +
    the two input markers -- never a 62k-tile walk (the dir is the OUTPUT, not a walked input). The
    non-empty + marker-exists checks reject a half-swapped empty dir or a missing raster stamp.

    tile_params.json joined the key. A missing one scores 0.0 in `newest_mtime` and so
    cannot make a pyramid look stale on its own; build_tiles writes it through `write_if_changed`
    before asking, which is what makes a settings change -- and only a settings change -- restage.
    """
    live = out / "tiles"
    return (live.is_dir() and any(live.iterdir())
            and done_marker(planet_tif).exists()
            and not is_stale(live, done_marker(planet_tif), tile_params_path(out)))


def build_tiles(planet_tif: Path, out: Path, body: bodies.Body):
    """Cut this body's 512px tiles into a staging dir, then swap over the live tiles.

    Fresh-guarded like every other stage (`tiles_are_fresh`): a re-run whose `planet_rgb` AND
    `tile_params.json` are unchanged skips the ~4:19 cut entirely. This used to be the one
    unguarded stage -- the staging dir is renamed away on success, so `--resume` always started from
    empty and the cut re-ran in full every time. The completion stamp is `tiles.done`, touched only
    after the swap.

    Recipe-gated in the usual order — see `freshness.write_if_changed`.

    EVERY CUT IS A CLEAN FULL CUT: the staging dir is removed first and `--resume` is not passed
    (see `_tile_cmd`). GDAL writes each tile in place, so a worker killed mid-write leaves a
    truncated file that an existence-only `--resume` would keep; re-cutting from empty (~4:19) is
    the cheap price of never trusting a partial tile. The one-generation rollback stays at
    `tiles_old`.

    THERE IS NO gdaladdo STEP, deliberately. `gdal raster tile` builds each low zoom from the tiles
    it just generated, never from the source's overviews -- proven by tiling one raster
    with and without them for byte-identical output at identical wall time. The overviews this
    function used to build cost ~3 min and ~4 GB appended to the master, for nothing. The
    note that justified them credited a confounded fix: materialising the 194-source VRT
    to a GTiff was the real speed-up; the overviews rode along on the same commit untested.
    """
    cut = tile_cut(body)
    write_if_changed(tile_params_path(out), tile_params(body))
    if tiles_are_fresh(planet_tif, out):
        progress.stage("tiles fresh -> skip cut")
        return
    staging = out / "tiles_new"
    if staging.exists():
        _run(["rm", "-rf", str(staging)])   # a partial from a prior mid-cut crash: never resume over it
    progress.stage(f"cutting z{cut['min_zoom']}-{cut['max_zoom']} {cut['tile_size']}px tiles "
                   f"-> {staging} ...")
    _run(_tile_cmd(planet_tif, staging, body))
    live = out / "tiles"
    if live.exists():
        old = out / "tiles_old"
        if old.exists():
            _run(["rm", "-rf", str(old)])
        live.rename(old)
    staging.rename(live)
    mark_done(live)
    progress.stage(f"tiles live -> {live} (previous kept at {out / 'tiles_old'})")
