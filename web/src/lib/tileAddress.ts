// The address of a tile: one grammar for every body, every layer and every cut.
//
// THE SHAPE IS FIXED AND THE VOCABULARY IS NOT. Every tile URL is exactly six segments:
//
//     {body}/{layer}/{token}/{z}/{x}/{y}.{ext}
//     earth/relief/3f9c1ab2/5/17/11.webp
//
// Adding a planet, a layer or a re-cut adds a WORD to one of the first three segments; it never
// changes the shape. That is the whole design, and it is what makes exclusivity structural instead
// of argued: two archives cannot share an address, because the address names its archive. The
// arrangement it replaces had a bare relief path, a `terrain/` prefix and a `countries/` prefix,
// and its correctness rested on the observation that no prefix was a prefix of another — true, but
// a property that has to be re-checked by hand every time a word is added.
//
// WHY THE BODY IS IN THE PATH AT ALL. Two bodies' pyramids are byte-comparable nonsense for each
// other: Mars terrain served at an Earth address does not 404, it displaces the globe by plausible
// metres. This is the same failure that made `terrain/` mandatory once both raster pyramids became
// WebP, one axis out.
//
// WHY THE TOKEN IS IN THE PATH. Tiles ship `immutable, max-age=31536000`, and a zone purge cannot
// reach a browser cache — so for a re-cut to be seen, THE URL MUST CHANGE. The token is the only
// thing in the address that can carry that, and it is per layer so that re-cutting 10 MB of country
// geometry does not re-fetch 3 GB of relief.
//
// WHAT THE TOKEN IS DERIVED FROM, AND WHY NOT THE RECIPE. It is a prefix of the SHA-256 of the
// archive's own bytes, computed by scripts/gen_tile_tokens.ts and committed in
// ../data/tileTokens.json. Hashing the cut's recipe sidecar was the obvious alternative and is
// wrong: `tile_params.json` records format, quality and zoom range, so a look change re-shades the
// composite, re-cuts every tile, and leaves that file byte-identical — the token would hold still
// through exactly the re-cut it exists to announce. The bytes cannot lie about themselves.
//
// PARSING IS GRAMMAR, NOT POLICY. `parseTileAddress` checks that a token is well-FORMED, never that
// it is current. A visitor holding a minute-old page must keep getting tiles while a deploy lands,
// and the archive a request resolves to does not depend on its token — so an old address serves the
// same object under a different cache key, which is exactly the behaviour that makes the token
// safe to change.

import type { BodySlug } from "./bodies";
import {
  COUNTRIES_MAX_ZOOM,
  COUNTRIES_MIN_ZOOM,
  parseCountriesTilePath,
} from "./countryTiles";
import {
  RELIEF_MAX_ZOOM,
  RELIEF_MIN_ZOOM,
  TILE_CONTENT_TYPE,
  TILE_EXTENSION,
  describeTileTypeMismatch,
  parseTilePath,
} from "./reliefTiles";
import {
  TERRAIN_CONTENT_TYPE,
  TERRAIN_MAX_ZOOM,
  TERRAIN_MIN_ZOOM,
  TERRAIN_TILE_EXTENSION,
  describeTerrainTileTypeMismatch,
  parseTerrainTilePath,
} from "./terrainSource";
import {
  VECTOR_CONTENT_TYPE,
  VECTOR_TILE_EXTENSION,
  describeVectorTileTypeMismatch,
} from "./vectorTiles";
// Beside this module rather than in src/data/, which LOOKS like its home and is gitignored: the
// repo's root `data/` pattern is unanchored, so it matches a directory of that name at any depth.
// A committed file has to live somewhere git will actually keep it.
import TOKENS from "./tileTokens.json";

/** Every pyramid the site knows how to draw, named by the ROLE it plays on a globe.
 *
 *  PICTURE, HEIGHTS, ANNOTATIONS — and role rather than product is the decision here. `countries`
 *  named what was inside Earth's one vector archive, which read as a layer name only because Earth
 *  was the only body publishing vectors; Mars's archive holds craters and will hold geologic units,
 *  and `multiLayer` already says a body's vector products share ONE archive. So a product name here
 *  would have to lie on the second planet, and again on the second product. What is inside an
 *  archive is per body and lives in sourceLayers.ts.
 *
 *  ONE VOCABULARY FOR THE WHOLE STACK — the URL segment, the work-tree lookup and the token file
 *  all spell a layer this way. A second spelling anywhere is a second concept to keep in step. */
export type LayerId = "relief" | "terrain" | "vector";

/** A tile URL is always this many segments. Stated as a constant because it is the invariant the
 *  grammar rests on, and a test pins it against the parser. */
export const TILE_PATH_SEGMENTS = 6;

/** Hex characters of SHA-256 kept in the address. Eight is ~4.3 billion values against a handful of
 *  archives ever cut, and short enough that a tile URL stays readable in a network panel. */
export const TOKEN_LENGTH = 8;

/** What is true of a layer on EVERY body: how its tiles are encoded, and what a miss means.
 *
 *  Every field is imported from the module that already owns it rather than restated here. This
 *  registry composes the three tile contracts; it does not become a fourth copy of them. */
export interface TileLayer {
  /** Tile encoding, as a bare extension. Documents and labels the bytes — it is deliberately NOT
   *  the discriminator, because a re-cut is allowed to change a codec and correctness may not
   *  depend on that. The layer segment discriminates. */
  extension: string;
  contentType: string;
  /** Reports an archive whose header disagrees with `extension`. */
  describeTileTypeMismatch: (archiveExtension: string) => string | null;
  /** What an absent tile MEANS here: 404 where the pyramid is complete and a hole is a packaging
   *  fault, 204 where it is sparse and a hole is just ocean. */
  missingTileStatus: 404 | 204;
  /** Whether one archive may hold several named layers. TRUE only for vector pyramids, where MVT
   *  carries layers inside each tile — which is why every one of a body's vector products belongs
   *  in ONE archive, and why two raster products can never share one. */
  multiLayer: boolean;
}

/** The layer contracts. A `Record` over the union, so a fourth pyramid is a compile error here
 *  rather than an `undefined` that resolves to a path spelled "undefined". */
export const LAYERS: Record<LayerId, TileLayer> = {
  relief: {
    extension: TILE_EXTENSION,
    contentType: TILE_CONTENT_TYPE,
    describeTileTypeMismatch,
    missingTileStatus: 404,
    multiLayer: false,
  },
  terrain: {
    extension: TERRAIN_TILE_EXTENSION,
    contentType: TERRAIN_CONTENT_TYPE,
    describeTileTypeMismatch: describeTerrainTileTypeMismatch,
    missingTileStatus: 404,
    multiLayer: false,
  },
  vector: {
    extension: VECTOR_TILE_EXTENSION,
    contentType: VECTOR_CONTENT_TYPE,
    describeTileTypeMismatch: describeVectorTileTypeMismatch,
    // The one sparse role: most of Earth is ocean holding no country, and most of Mars is ground no
    // name reaches. A miss here is ordinary rather than a packaging fault.
    missingTileStatus: 204,
    multiLayer: true,
  },
};

/** One body's cut of one layer, as published.
 *
 *  This is the per-BODY half — everything here can differ between planets while the layer contract
 *  above stays the same. */
export interface PublishedArchive {
  /** The R2 object key, recorded rather than derived.
   *
   *  DELIBERATELY NOT `{body}/{layer}-v{N}.pmtiles`. The keys carry the history of what has been
   *  uploaded (`planet-v2.pmtiles` is the WebP cut that replaced a PNG one), and renaming them
   *  means copying 5.7 GB into a bucket with under a gigabyte of headroom. A field costs one line
   *  and lets each key be tidied the next time that archive is re-cut anyway. */
  objectKey: string;
  /** Cache-busting segment; see the module note. Generated, never typed by hand. */
  token: string;
  /** Leaf directories in this archive — the third term in what it costs the tile Worker's
   *  directory cache, after one entry for the header and one for the root.
   *
   *  Recorded here because the Worker sizes that cache by SUMMING over everything published, and a
   *  cache one entry short evicts on alternating requests while reporting nothing: a resolved
   *  directory that falls out costs a gunzip and a deserialize, not an R2 read. Generated from the
   *  archive alongside the token, for the reason the hand tally deserves no trust — it was wrong,
   *  recording terrain's 22 leaves as 21. */
  indexLeaves: number;
  /** Where THIS BODY's copy of the two zooms below lives, quoted into the message a server logs
   *  when an archive's header disagrees with them.
   *
   *  PER BODY RATHER THAN PER LAYER, because a ceiling follows each planet's own source data: the
   *  entries below variously import a browser constant and restate a pipeline one, so there is no
   *  single module a layer could name for every planet. It sat on `TileLayer` first, where a Mars
   *  drift sent the reader to `reliefTiles.ts` — Earth's file, holding a number Mars deliberately
   *  does not use. */
  zoomConstants: string;
  minZoom: number;
  maxZoom: number;
}

/** Which cuts exist, per body.
 *
 *  `null` means "this body does not publish this layer" and is a required answer, not an omission —
 *  a `Partial` record here would let a new body inherit silence for a layer nobody considered, and
 *  a new layer appear published on every planet at once. Mars will carry `null` for its vectors
 *  until they are cut. */
export const PUBLISHED: Record<BodySlug, Record<LayerId, PublishedArchive | null>> = {
  earth: {
    relief: {
      objectKey: "planet-v2.pmtiles",
      token: TOKENS.earth.relief.token,
      indexLeaves: TOKENS.earth.relief.indexLeaves,
      zoomConstants: "RELIEF_MIN_ZOOM/RELIEF_MAX_ZOOM in web/src/lib/reliefTiles.ts",
      minZoom: RELIEF_MIN_ZOOM,
      maxZoom: RELIEF_MAX_ZOOM,
    },
    terrain: {
      objectKey: "terrain-v1.pmtiles",
      token: TOKENS.earth.terrain.token,
      indexLeaves: TOKENS.earth.terrain.indexLeaves,
      zoomConstants: "TERRAIN_MIN_ZOOM/TERRAIN_MAX_ZOOM in web/src/lib/terrainSource.ts",
      minZoom: TERRAIN_MIN_ZOOM,
      maxZoom: TERRAIN_MAX_ZOOM,
    },
    // THE OBJECT KEY KEEPS ITS OLD NAME ON PURPOSE. `objectKey` is recorded rather than derived
    // precisely so a rename of the layer word costs nothing in R2 — renaming the object would mean
    // copying it into a bucket with under a gigabyte of headroom, for no byte change.
    vector: {
      objectKey: "countries-v1.pmtiles",
      token: TOKENS.earth.vector.token,
      indexLeaves: TOKENS.earth.vector.indexLeaves,
      zoomConstants: "COUNTRIES_MIN_ZOOM/COUNTRIES_MAX_ZOOM in web/src/lib/countryTiles.ts",
      minZoom: COUNTRIES_MIN_ZOOM,
      maxZoom: COUNTRIES_MAX_ZOOM,
    },
  },
  // MARS PUBLISHES RELIEF AND NOTHING ELSE, and the two remaining nulls are answers rather than
  // omissions — the record forces this body to answer for every layer, so nothing can be forgotten
  // into existence later. `parseTileAddress` refuses a Mars terrain or vector URL without touching
  // storage, and `archiveFor` throws rather than borrowing Earth's pyramid.
  //
  // NAMING A KEY HERE COMMITS TO AN UPLOAD. The deploy preflight refuses on any published object the
  // bucket does not hold, so this entry and the R2 upload land together or not at all.
  mars: {
    // `-v2` BECAUSE THE BYTES CHANGED, NEVER AN OVERWRITE OF `-v1`. A warm Worker isolate caches
    // directory byte OFFSETS, and offsets from one cut against another's bytes serve a corrupt tile
    // with a 200 — so a re-cut takes a new key, as Earth's `planet-v2` did. It also makes the deploy
    // preflight the thing that catches an un-uploaded archive: it checks EXISTENCE, so reusing the
    // key would let a deploy answer z7 requests out of the z6 object and report itself clean.
    relief: {
      objectKey: "mars/relief-v2.pmtiles",
      token: TOKENS.mars.relief.token,
      indexLeaves: TOKENS.mars.relief.indexLeaves,
      // The one entry that names no browser module, which is the whole reason this field is per
      // body: Mars's ceiling is a pipeline number, so the reader has to be sent past the registry.
      zoomConstants:
        "minZoom/maxZoom in PUBLISHED.mars.relief, restating MARS.tile_max_zoom in pipeline/bodies.py",
      // NOT `RELIEF_MIN_ZOOM`/`RELIEF_MAX_ZOOM`, which are Earth's answer to a per-planet question:
      // a ceiling is about each body's own data rather than about the scheme. These restate
      // `pipeline/bodies.py`'s `MARS.tile_max_zoom`, and the copy is held honest twice over — by
      // `tests/test_bodies.py`, which reads this record against the cut on every suite, and at
      // runtime by the dev server reading the archive's own header.
      minZoom: 0,
      maxZoom: 7,
    },
    terrain: null,
    vector: null,
  },
};

/** One parsed tile request. */
export interface TileAddress {
  body: BodySlug;
  layer: LayerId;
  /** As requested. Well-formed, not necessarily current — see the module note.
   *
   *  NULL when the request came in under the legacy grammar, which has no token at all. A null here
   *  is the one honest answer: filling in the current token would claim the request named something
   *  it did not, and the whole point of the migration is being able to see which shape asked. */
  token: string | null;
  z: number;
  x: number;
  y: number;
}

const TILE_PATH_PATTERN = new RegExp(
  String.raw`^\/?([a-z][a-z0-9]*)\/([a-z][a-z0-9]*)\/([0-9a-f]{${TOKEN_LENGTH}})\/` +
    String.raw`(\d{1,2})\/(\d{1,7})\/(\d{1,7})\.([a-z0-9]+)$`,
);

/** Layer words this grammar still accepts under a spelling it no longer mints. TEMPORARY, and it
 *  goes the same way the legacy grammar below does.
 *
 *  WHY IT HAS TO EXIST AT ALL: the token compiles into the SITE bundle while the tile Worker is a
 *  separate deploy, so for the window between the two — and for every page a visitor already has
 *  open, whose URLs are `immutable` for a year — requests keep arriving spelled the old way. A
 *  Worker that refused them would blank the countries on a live globe rather than paint a stale
 *  name. Accept both, ship the site second, delete this once `addressedLayerWord` stops reporting
 *  the old spelling in production.
 *
 *  It maps a WORD to a layer and nothing else. The archive, the token and the zoom range are the
 *  registry's, so an aliased request resolves to exactly the tile the current spelling would. */
const RENAMED_LAYER_WORDS: Record<string, LayerId | undefined> = { countries: "vector" };

/** The layer word an addressed path SPELLS, or null where it is not an addressed path.
 *
 *  A server compares this against the layer the request RESOLVED to, and a difference is a client
 *  built before the rename. That comparison is the only signal for when `RENAMED_LAYER_WORDS` can
 *  be deleted — an aliased request is served correctly and silently, which is exactly what makes it
 *  safe and exactly what makes it invisible. Same argument as the legacy grammar's own latch. */
export function addressedLayerWord(pathname: string): string | null {
  return TILE_PATH_PATTERN.exec(pathname)?.[2] ?? null;
}

/** Parse a tile path into an address, or null if it is not one.
 *
 *  Null covers every rejection, and every rejection is answerable without touching storage: an
 *  unknown body or layer, a body that does not publish that layer, an extension that is not the
 *  layer's, a zoom outside the cut, an address outside the 2^z grid. A tile server must be able to
 *  refuse a typo without range-reading a multi-gigabyte object. */
export function parseTileAddress(pathname: string): TileAddress | null {
  const match = TILE_PATH_PATTERN.exec(pathname);
  if (!match) return null;
  const [, bodySlug, layerId, token, zoom, column, row, extension] = match;
  // Unreachable: every group in TILE_PATH_PATTERN is mandatory, so a match yields all seven. Stated
  // as a check rather than a non-null assertion because the Worker compiles this file under
  // `noUncheckedIndexedAccess`, where the destructure is `string | undefined` — and an assertion
  // would go on silencing it the day someone makes a group optional and one really can be absent.
  if (!bodySlug || !layerId || !token || !zoom || !column || !row || !extension) return null;
  if (!(bodySlug in PUBLISHED)) return null;
  const body = bodySlug as BodySlug;
  const layer = layerId in LAYERS ? (layerId as LayerId) : RENAMED_LAYER_WORDS[layerId];
  if (!layer) return null;
  if (extension !== LAYERS[layer].extension) return null;
  const published = PUBLISHED[body][layer];
  if (!published) return null;
  const z = Number(zoom);
  const x = Number(column);
  const y = Number(row);
  if (z < published.minZoom || z > published.maxZoom) return null;
  const gridSize = 2 ** z;
  if (x >= gridSize || y >= gridSize) return null;
  return { body, layer, token, z, x, y };
}

/** Describe a disagreement between what an archive's own header says it covers and what the
 *  registry advertises, or null when they agree.
 *
 *  HERE RATHER THAN AT THE CALL SITE, because the call site is `astro.config.ts` and nothing
 *  imports a config. This replaced three `assert*ZoomRange` functions that lived in the three layer
 *  modules for exactly that reason — they were testable and a check buried in the config is not.
 *  Returning a string rather than throwing matches `describeTileTypeMismatch` next door, and lets
 *  each server pick its own severity: the dev server throws, the Worker logs and 404s.
 *
 *  IT ASKS THE REGISTRY, NOT A MODULE CONSTANT, because a ceiling follows each body's own source
 *  data — so `RELIEF_MIN_ZOOM` and its two siblings are Earth's answer to a per-planet question,
 *  and checking another body against them refuses a correct pyramid. */
export function describeArchiveHeaderMismatch(
  body: BodySlug,
  layer: LayerId,
  header: { minZoom: number; maxZoom: number },
): string | null {
  const published = archiveFor(body, layer);
  if (header.minZoom === published.minZoom && header.maxZoom === published.maxZoom) return null;
  return (
    `PMTiles archive for ${body}/${layer} covers z${header.minZoom}-z${header.maxZoom}, but ` +
    `PUBLISHED.${body}.${layer} in src/lib/tileAddress.ts says z${published.minZoom}-` +
    `z${published.maxZoom}. Update the registry to match the re-cut pyramid, or re-cut it. ` +
    `A disagreement is silent either way: a shallower archive stops sharpening (204 on the sparse ` +
    `countries pyramid, which is indistinguishable from ocean), and a deeper one is never asked ` +
    `for, which looks exactly like the extra levels having no effect.`
  );
}

/** Look one body's cut of a layer up, or throw.
 *
 *  NO FALLBACK, for the reason both registries give: a caller that quietly borrowed Earth's archive
 *  because a body does not publish this layer would serve a complete, plausible, wrong planet. */
export function archiveFor(body: BodySlug, layer: LayerId): PublishedArchive {
  // The body lookup is defensive even though it is typed: the argument reaches here from a URL
  // segment and from `data-body`, neither of which the type system has ever seen.
  const published = PUBLISHED[body]?.[layer];
  if (!published) {
    throw new Error(`${body} publishes no ${layer} pyramid`);
  }
  return published;
}

// ── The legacy grammar ───────────────────────────────────────────────────────────────────────────
//
// Everything below this line is temporary, and it is one function plus its tests to delete. It
// exists because the site and the tile Worker deploy separately: a visitor holding a page built
// before the switch keeps asking for the shape that page was built with, and their globe should not
// go blank while the two halves roll. Once production has served no legacy request for a day, this
// half goes, and `resolveTileRequest` collapses into `parseTileAddress`.

/** What an untokened path means. Production has only ever served one planet, so a legacy address is
 *  Earth's by definition — not by default. The distinction matters: this is a statement about what
 *  those URLs already are, and it cannot become a fallback for a body that fails to parse. */
const LEGACY_BODY: BodySlug = "earth";

/** The optional version segment the Worker has always tolerated and ignored.
 *
 *  It was the pre-token answer to the same question this scheme now answers per layer: a re-cut
 *  needed a new base URL, because a zone purge cannot reach a browser cache. Anchored, and it must
 *  stay anchored — `/5/v2/1/2.webp` with an unanchored strip becomes `/5/1/2.webp`, a perfectly
 *  valid tile served under an address nobody ever minted. */
const LEGACY_VERSION_PREFIX = /^\/v\d+\//;

/** Parse the shapes production serves today: `{z}/{x}/{y}.webp` and the two prefixed variants. */
function parseLegacyTilePath(pathname: string): TileAddress | null {
  const path = pathname.replace(LEGACY_VERSION_PREFIX, "/");
  const relief = parseTilePath(path);
  if (relief) return { body: LEGACY_BODY, layer: "relief", token: null, ...relief };
  const terrain = parseTerrainTilePath(path);
  if (terrain) return { body: LEGACY_BODY, layer: "terrain", token: null, ...terrain };
  const countries = parseCountriesTilePath(path);
  // The legacy PREFIX keeps its own spelling — it is a statement about URLs production already
  // served, not a name we get to revise — and maps to the role that serves them now.
  if (countries) return { body: LEGACY_BODY, layer: "vector", token: null, ...countries };
  return null;
}

/** Resolve a tile request under either grammar — what a SERVER should call.
 *
 *  The addressed form is tried first, so the legacy parsers can never shadow it. They could not
 *  anyway (each requires either a leading zoom or its own literal prefix, and a body slug is
 *  neither), but the order makes that independent of their internals rather than dependent on them.
 *
 *  The version-prefix strip deliberately applies only to the legacy branch. Nothing has ever been
 *  served under `/v<N>/`, and the token now does that job properly — so tolerating it in front of an
 *  addressed path would be inventing a second way to spell one tile. */
export function resolveTileRequest(pathname: string): TileAddress | null {
  return parseTileAddress(pathname) ?? parseLegacyTilePath(pathname);
}

// ── End of the legacy grammar ────────────────────────────────────────────────────────────────────

/** The path portion of a tile URL, with MapLibre's placeholders left in place.
 *
 *  Built from the same registry the parser reads, so the address we ASK for and the address we
 *  ACCEPT cannot drift across a re-cut, a new layer or a new planet. */
export function tilePathTemplate(body: BodySlug, layer: LayerId): string {
  const { token } = archiveFor(body, layer);
  return `${body}/${layer}/${token}/{z}/{x}/{y}.${LAYERS[layer].extension}`;
}
