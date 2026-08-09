/** The vector tile-transport contract — what is true of ANY body's vector pyramid.
 *
 *  Sibling of reliefTiles.ts and terrainSource.ts, and a sibling rather than a generalisation for
 *  the same reason those two stay separate from each other: this one is MVT where they are WebP, it
 *  is legitimately SPARSE where they are complete, and its tiles carry named source-layers where a
 *  raster tile carries pixels. Folding them together would put a "which archive am I" branch in the
 *  files whose job is to have no branches.
 *
 *  WHAT IS DELIBERATELY NOT HERE: which layers are inside a tile, how deep the pyramid was cut, and
 *  which producer wrote it. Those are per body, and a second body is what made the difference
 *  visible — this file was extracted out of countryTiles.ts, where the transport read as Earth's by
 *  association because nothing else in the module was anybody else's. Earth's answers stayed there.
 *
 *  Like both siblings this is dependency-free and free of `import.meta.env`, because it is imported
 *  from the browser, the Astro dev server (plain Node, before Vite env exists) and the tile Worker.
 */

/** Mapbox Vector Tile. The archive stores these gzipped, but nothing downstream sees that:
 *  `PMTiles.getZxy` decompresses against the header's `tileCompression` before returning, and
 *  both tile servers read through it. So the wire carries plain protobuf and no `Content-Encoding`
 *  is involved — which is what keeps R2's undocumented encoding passthrough out of this path. */
export const VECTOR_TILE_EXTENSION = "mvt";
export const VECTOR_CONTENT_TYPE = "application/x-protobuf";

/** Describe a VECTOR_TILE_EXTENSION/archive disagreement, or null when they match.
 *
 *  The failure it catches is a route having been pointed at a RASTER archive: a WebP tile served as
 *  `application/x-protobuf` fails to parse in MapLibre's worker, and the visible result is a globe
 *  with nothing drawn — indistinguishable from a source-layer typo, from an empty archive, and from
 *  a filter that matches nothing.
 *
 *  IT NAMES NO ARCHIVE AND NO PRODUCER, and that is the constraint of living on `TileLayer`: one
 *  function answers for every body, so the sentence cannot claim which pyramid is wrong or which
 *  script cut it. Both callers already have the archive key and prefix it onto the line. */
export function describeVectorTileTypeMismatch(archiveExtension: string): string | null {
  if (archiveExtension === `.${VECTOR_TILE_EXTENSION}`) return null;
  const declared = archiveExtension || "an encoding this pmtiles build cannot name";
  return (
    `This archive stores ${declared} tiles, but the globe requests ` +
    `.${VECTOR_TILE_EXTENSION}. Update VECTOR_TILE_EXTENSION in src/lib/vectorTiles.ts to match ` +
    `the re-cut pyramid, whose source of truth is the pipeline stage that packed it.`
  );
}
