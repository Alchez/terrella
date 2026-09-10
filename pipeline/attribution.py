"""Every dataset this project publishes from, and who has to be told about it.

One owner for facts that had four copies. `ATTRIBUTIONS.md` narrates them, `aboutContent.ts` drew
cards from its own list, the licence sweep kept a third list of which were obligations, and the
archive credits were a fourth. Nothing derived from anything, and they had drifted: SCAR ADD is
CC-BY and named required in ATTRIBUTIONS.md, and appeared nowhere in the site source; the IAU
gazetteer names every Mars feature a visitor can click and was not on the page either.

`datasets.py` says a dataset's source and licence are ATTRIBUTIONS.md's and restating them is a
second copy. That still holds for the PROSE, which is what a person reads. What moved here is the
structured half, because a markdown table cannot be imported by a stage that stamps an archive or
by a page that renders a card. The document is now checked against this rather than trusted.

Python owns it and TypeScript imports what `web/scripts/gen_attributions.py` emits, on
`tileTokens.json`'s precedent: the pipeline must have these in Python to stamp an archive, the site
must have them in TypeScript to draw a card, and only one of those directions can generate.

WHAT AN ARCHIVE OWES IS DERIVED, NOT LISTED. A vector archive is geometry and touches no elevation
data; a terrain archive encodes elevation and nothing else; a relief archive shades the surface
layers its body declares. `body.surface_layers & layers.BLOCK_LAYERS` is what a relief cut actually
bakes, so a layer switched on or off moves the credit with it.
"""

from dataclasses import dataclass, field

from pipeline import bodies, layers


@dataclass(frozen=True)
class Source:
    """One dataset, and everything the three consumers need to say about it.

    Every field required except `page_note`, on `bodies.Body`'s reasoning: a source added without
    an answer for one of them is a card with a blank line or an archive crediting nobody.
    """

    name: str
    href: str
    #: What it does here, as a visitor reads it on the card.
    role: str
    #: The badge, and it names the LICENCE rather than the data centre that serves the file:
    #: NSIDC-0791 is public domain and OSI SAF is CC-BY 4.0, and both arrive from NSIDC.
    licence: str
    #: The credit itself, quoted wherever a publisher states an exact form. This string is what
    #: reaches an archive, so it carries no page-relative wording.
    notice: str
    #: Licence-REQUIRED rather than courtesy. Only these are asserted, because a check that claims
    #: an obligation the publisher does not state fails for reasons that are not legal ones.
    #: Nothing here returns the whole marked set: an archive credits per layer and a card per body,
    #: and the only thing wanting all of them is a guard, which needs each source's name for its
    #: message and a literal list beside it so a derivation that produced nothing cannot pass.
    obligation: bool
    #: A sentence the About card adds after the citation and an archive has no use for, either
    #: because it points at the page ("see the note below") or because it is context a downloader
    #: reading raw metadata cannot act on.
    page_note: str = ""

    def page_attribution(self) -> str:
        """What the About card prints: the citation, plus the page's own sentence if it has one."""
        return f"{self.notice} {self.page_note}".strip()


#: Every dataset, keyed by the name the composition tables below use.
#:
#: Flat rather than per body because no source serves two planets, so a body key would be a second
#: place to answer a question `CREDITS` already answers.
SOURCES: dict[str, Source] = {
    "glo30": Source(
        name="Copernicus DEM GLO-30",
        href="https://dataspace.copernicus.eu/explore-data/data-collections/"
             "copernicus-contributing-missions/collections-description/COP-DEM",
        role="Land elevation",
        licence="Copernicus",
        # Article 6(b) requires this exact wording for adapted data. Quoted, never paraphrased.
        notice="produced using Copernicus WorldDEM-30 © DLR e.V. 2010-2014 and © Airbus Defence "
               "and Space GmbH 2014-2018 provided under COPERNICUS by the European Union and ESA; "
               "all rights reserved",
        obligation=True,
    ),
    "gebco": Source(
        name="GEBCO 2026 Grid",
        href="https://www.gebco.net",
        role="Bathymetry",
        licence="Public domain",
        notice="Reproduced from the GEBCO_2026 Grid, GEBCO Compilation Group (2026).",
        obligation=False,
    ),
    "globathy": Source(
        name="GLOBathy",
        href="https://springernature.figshare.com/collections/"
             "GLOBathy_the_Global_Lakes_Bathymetry_Dataset/5243309",
        role="Lake depth",
        licence="CC0",
        notice="Lake depth from GLOBathy: Khazaei, B., Read, L.K., Casali, M., Sampson, K.M., "
               "Yates, D.N. (2022), GLOBathy, the Global Lakes Bathymetry Dataset, Scientific "
               "Data 9, 36 (doi:10.1038/s41597-022-01132-9).",
        obligation=False,
        page_note="Public-domain dedication (CC0). Depth is modelled; see the Lake depth note "
                  "below.",
    ),
    "worldcover": Source(
        name="ESA WorldCover 2021",
        href="https://esa-worldcover.org",
        role="Snow / ice mask",
        licence="CC-BY 4.0",
        notice="© ESA WorldCover project 2021 / Contains modified Copernicus Sentinel data "
               "(2021) processed by ESA WorldCover consortium.",
        obligation=True,
    ),
    "snow_persistence": Source(
        name="NSIDC-0791 Snow Persistence",
        href="https://nsidc.org/data/nsidc-0791",
        role="Snow persistence",
        licence="Public domain",
        notice="Snow persistence from the MODIS/Terra Global Annual Snow-Cover Climatology "
               "(NSIDC-0791), NASA NSIDC DAAC (doi:10.5067/9R1AM6NNZLTV).",
        obligation=False,
        page_note="Water years 2001-2023.",
    ),
    "rgi": Source(
        name="RGI 7.0 Glaciers",
        href="https://nsidc.org/data/nsidc-0770/versions/7",
        role="Glaciers",
        licence="CC-BY 4.0",
        notice="RGI 7.0 Consortium (2023), Randolph Glacier Inventory 7.0 "
               "(doi:10.5067/F6JMOVY5NAVZ), CC-BY 4.0.",
        obligation=True,
        page_note="NSIDC-0770 v7.",
    ),
    "addrock": Source(
        name="SCAR ADD Antarctic rock outcrop",
        href="https://data.bas.ac.uk/items/178ec50d-1ffb-42a4-a4a3-1145419da2bb/",
        role="Exposed rock, subtracted from the Antarctic white",
        licence="CC-BY 4.0",
        notice="Gerrish, L. (2020). Automatically extracted rock outcrop dataset for Antarctica "
               "(7.3) [Data set]. UK Polar Data Centre, Natural Environment Research Council, UK "
               "Research & Innovation. https://doi.org/10.5285/178ec50d-1ffb-42a4-a4a3-1145419da2bb",
        obligation=True,
    ),
    "seaice": Source(
        name="OSI SAF Sea Ice (OSI-450-a)",
        href="https://osi-saf.eumetsat.int/products/osi-450-a",
        role="Sea ice",
        licence="CC-BY 4.0",
        notice="Sea-ice climatology derived from the OSI SAF Global sea ice concentration "
               "climate data record 1978–2020 (v3.0, 2022), OSI-450-a, EUMETSAT Ocean and Sea Ice "
               "Satellite Application Facility (doi:10.15770/EUM_SAF_OSI_0013).",
        obligation=True,
        page_note="Reduced to a 1991-2020 annual ice-frequency climatology.",
    ),
    "naturalearth": Source(
        name="Natural Earth",
        href="https://www.naturalearthdata.com",
        role="Borders & coastlines",
        licence="Public domain",
        notice="Made with Natural Earth (naturalearthdata.com).",
        obligation=False,
    ),
    "mars_dem": Source(
        name="MOLA / HRSC Blended DEM",
        href="https://astrogeology.usgs.gov/search/map/"
             "mars_mgs_mola_mex_hrsc_blended_dem_global_200m",
        role="Surface elevation",
        # The publisher's own words, not our reading of them. The share-alike half is why the whole
        # site's output licence is BY-SA.
        licence="MOLA CC0 · HRSC CC BY-SA 3.0 IGO",
        notice="Fergason, R. L, Hare, T. M., & Laura, J. (2018). HRSC and MOLA Blended Digital "
               "Elevation Model at 200m v2. Astrogeology PDS Annex, U.S. Geological Survey.",
        obligation=True,
        page_note="MOLA flew on NASA's Mars Global Surveyor and HRSC on ESA's Mars Express; HRSC "
                  "covers 44% of the planet, MOLA the rest.",
    ),
    "mars_sim3292": Source(
        name="Geologic Map of Mars (SIM 3292)",
        href="https://pubs.usgs.gov/sim/3292/",
        role="Where the permanent polar ice is",
        licence="Public domain · cite authors",
        notice="K.L. Tanaka, J.A. Skinner, Jr., J.M. Dohm, R.P. Irwin, III, E.J. Kolb, C.M. "
               "Fortezzo, Thomas Platz, G.G. Michael, and T.M. Hare, 2014, Geologic Map of Mars, "
               "Scale 1:20,000,000, U.S. Geological Survey Scientific Investigations Map SIM 3292, "
               "http://pubs.usgs.gov/sim/3292",
        obligation=True,
    ),
    "mars_viking": Source(
        name="Viking colour mosaic",
        href="https://astrogeology.usgs.gov/search/map/"
             "mars_viking_colorized_global_mosaic_925m",
        role="How bright each part of the ice is, and the planet's hue",
        licence="Public domain",
        notice="U.S. Geological Survey Astrogeology Science Center, Viking Global Color Mosaic "
               "925m.",
        obligation=False,
        page_note="Built for albedo rather than for relief, which is why the ice grades against it.",
    ),
    "mars_nomenclature": Source(
        name="IAU Gazetteer of Planetary Nomenclature",
        href="https://planetarynames.wr.usgs.gov/",
        role="Every named feature the globe draws",
        licence="Public domain",
        notice="IAU/USGS Gazetteer of Planetary Nomenclature, U.S. Geological Survey Astrogeology "
               "Science Center (https://planetarynames.wr.usgs.gov/).",
        obligation=False,
    ),
}


@dataclass(frozen=True)
class BodyCredits:
    """Which sources a body uses, and where each one ends up.

    Split by DESTINATION rather than listed once, because that is the question an archive asks: a
    terrain cut owes the heightfield and nothing else. The page asks the other question and takes
    the union, so a source reachable from no field here appears on no card either.
    """

    #: The elevation model every raster archive of this body encodes or shades.
    heightfield: tuple[str, ...]
    #: Per surface layer, the sources a relief cut bakes when the body declares that layer. Keyed
    #: by `layers.SURFACE_LAYERS` names and pinned against what the body actually paints.
    painted: dict[str, tuple[str, ...]]
    #: The geometry behind this body's vector pyramid.
    vector: tuple[str, ...]
    #: Used by the hero renders and by no tile archive, so it reaches the page and nothing else.
    heroes: tuple[str, ...] = ()
    #: Disclaimers this body's own licences oblige, rendered under its cards.
    legal: tuple[str, ...] = field(default_factory=tuple)


#: Copernicus Article 6(c). Article 6(d) forbids implying endorsement, which is why no card claims
#: any, and this sentence sits under Earth's sources rather than in a site-wide block: it is about
#: WorldDEM-30, and only Earth is built from it.
#: No trailing stop: this is quoted from the licence through ATTRIBUTIONS.md, which ends the
#: sentence outside its quotation marks. Each consumer punctuates it.
COPERNICUS_LIABILITY = ("The organisations in charge of the Copernicus programme by law or by "
                        "delegation do not incur any liability for any use of the Copernicus "
                        "WorldDEM-30")

CREDITS: dict[str, BodyCredits] = {
    "earth": BodyCredits(
        # WorldCover is here and not only under `heroes`, which is where believing the standing
        # brief put it. OpenTopography serves the withheld GLO-30 tiles as DEM with no watermask,
        # so `fuse/build_void_wbm.py` synthesises one from WorldCover class 80 and
        # `build_mosaics.sh` globs it into the WBM mosaic that `fuse_heightfield` reads. It is
        # CC-BY, so every Earth raster archive owes it a notice.
        heightfield=("glo30", "gebco", "worldcover"),
        painted={
            "lake_depth": ("globathy",),
            "perennial_ice": ("snow_persistence",),
            "glaciers": ("rgi",),
            "sea_ice": ("seaice",),
            "antarctic_rock": ("addrock",),
        },
        vector=("naturalearth",),
        heroes=("worldcover",),
        legal=(f"{COPERNICUS_LIABILITY}.",),
    ),
    "mars": BodyCredits(
        heightfield=("mars_dem",),
        painted={"perennial_ice": ("mars_sim3292", "mars_viking")},
        vector=("mars_nomenclature",),
    ),
}

#: Every published pyramid, whichever stage cuts it. The same vocabulary as `LayerId` in
#: `web/src/lib/tileAddress.ts`, which is the site's copy and which a guard holds this equal to: a
#: name spelled in two languages is where "they happen to agree" stops being checkable by either.
ARCHIVE_LAYERS = ("relief", "terrain", "vector")

#: The subset `tile/pack_pmtiles.py` builds. `compose/vector_cut.py` cuts the third straight to
#: PMTiles with ogr2ogr, so the packer's `--layer` must not offer it.
RASTER_LAYERS = ("relief", "terrain")

#: What this archive is and what a recipient may do with it, before any input credit. The
#: pipeline's only copy of the site hostname; the site's own copies are under `web/`.
TERRELLA = ("Terrella (https://terrella.alchez.dev), CC BY-SA 4.0 "
            "(https://creativecommons.org/licenses/by-sa/4.0/).")

#: What each pyramid holds, in the words a stranger holding the file needs. The layer name alone is
#: this project's vocabulary rather than anyone else's, and `vector` is a role that means countries
#: on one planet and named features on another, which is why the archive's own `name` still says
#: which. Nothing here names a zoom or an encoding: those are their own keys in the same blob.
LAYER_CONTENTS = {
    "relief": "shaded relief imagery",
    "terrain": "elevation encoded as Terrain-RGB",
    "vector": "vector geometry drawn as an overlay",
}


def painted_layers(body: bodies.Body) -> frozenset[str]:
    """The surface layers a relief cut of this body bakes in.

    The block render is what shades a tile, so its column is the one that decides, and the
    coastline is absent from it: the tiles bake no coast, the client draws it as a vector.
    """
    return body.surface_layers & layers.BLOCK_LAYERS


def keys_for(body: bodies.Body, layer: str) -> tuple[str, ...]:
    """The source keys one archive of this body and layer owes a credit to."""
    if layer not in ARCHIVE_LAYERS:
        raise ValueError(f"{layer!r} is not an archive layer ({', '.join(ARCHIVE_LAYERS)})")
    credits = CREDITS[body.name]
    if layer == "vector":
        return credits.vector
    if layer == "terrain":
        return credits.heightfield
    painted = (key for name in sorted(painted_layers(body)) for key in credits.painted[name])
    return (*credits.heightfield, *painted)


def for_archive(body: bodies.Body, layer: str) -> str:
    """The `attribution` an archive of this body and layer carries inside its own bytes."""
    keys = keys_for(body, layer)
    lines = [TERRELLA, *(SOURCES[key].notice for key in keys)]
    # Follows the DEM rather than the body: Earth's vector archive is Natural Earth geometry with
    # no WorldDEM-30 in it, and carried this sentence until the module printed itself.
    if "glo30" in keys:
        lines.insert(2, COPERNICUS_LIABILITY)
    return " ".join(line if line.endswith(".") else f"{line}." for line in lines)


def describe(body: bodies.Body, layer: str) -> str:
    """The `description` an archive of this body and layer carries, saying what the file holds.

    Derived, with no authored half and no date. An authored sentence is what `ARCHIVED[].note` in
    `tileAddress.ts` already carries, and it belongs there rather than here for two reasons: it
    describes a cut against the one it replaced, which is not knowable when the bytes are written,
    and bytes cannot be corrected afterwards without a re-cut, a re-upload and two Worker deploys.
    A timestamp is refused on top of that: it would make two packs of one pyramid differ, and
    reproducible bytes are what proves a re-pack moved no tile.
    """
    if layer not in ARCHIVE_LAYERS:
        raise ValueError(f"{layer!r} is not an archive layer ({', '.join(ARCHIVE_LAYERS)})")
    return f"{body.name.title()} {LAYER_CONTENTS[layer]}, from the Terrella pipeline."


def on_the_page(body: bodies.Body) -> tuple[Source, ...]:
    """Every source this body's imagery is built from, in card order.

    The UNION of every destination, which is what makes the page's list derived rather than a
    fourth hand-kept copy: a source this body uses anywhere gets a card, and one it uses nowhere
    cannot get one. Both directions were wrong before this, in the same file.
    """
    credits = CREDITS[body.name]
    ordered = [*credits.heightfield,
               *(key for name in sorted(credits.painted) for key in credits.painted[name]),
               *credits.vector, *credits.heroes]
    seen: dict[str, None] = dict.fromkeys(ordered)
    return tuple(SOURCES[key] for key in seen)


def main() -> int:
    """Print what every archive would carry, so a change is reviewable without cutting one."""
    for name, body in sorted(bodies.BODIES.items()):
        for layer in ARCHIVE_LAYERS:
            credit = for_archive(body, layer)
            print(f"\n=== {name}/{layer} ({len(credit)} chars) ===\n{credit}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
