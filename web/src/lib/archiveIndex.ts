// What the downloads page lists, as data rather than as template frontmatter.
//
// SEPARATE FROM THE PAGE SO A GUARD CAN REACH IT. The first version of this lived in
// `archives.astro` and its test scanned the source for the word `ARCHIVED`, which the import line
// satisfies on its own: emptying the superseded list left that test green. A function returning
// rows is something a test can call and count.

import { ARCHIVE_BASE, TILE_BASE } from "./assetBase";
import { BODIES, type BodyDescriptor, type BodySlug } from "./bodies";
import CREDITS from "../data/attributions.json";
import { TERRAIN_QUANTISATION_M, terrainDecodeExpression } from "./terrainSource";
import {
  ARCHIVED,
  PUBLISHED,
  tilePathTemplate,
  type ArchivedCut,
  type LayerId,
} from "./tileAddress";

/** What each pyramid holds, in a visitor's words. The pipeline's `attribution.describe` says the
 *  same thing inside the file; this is the longer form, for someone deciding what to download.
 *
 *  TAKES THE BODY, because `vector` is a role rather than a content: the same layer is countries on
 *  one planet and named features on another. The archive's own copy names both, since it is read
 *  away from any page that has said which planet it is about; here the section heading above the
 *  card has already said, so a card that mentions the other one is describing a file it is not. */
const LAYER_ROLE: Record<LayerId, (body: BodyDescriptor) => string> = {
  // Relief bakes the vertical stretch into its pixels and terrain below does not, which decides
  // whether a downloaded file can be measured. No elevation key on the site carries the metres to
  // undo it, so a card omitting this leaves the imagery reading as survey.
  relief: (body) =>
    `Shaded relief imagery, the pixels the globe draws. Heights are drawn at ` +
    `${body.bakedExaggeration}x, so this is a picture rather than a measurement.`,
  // Not "Terrain-RGB", which is Mapbox's format and decodes these bytes to six-figure metres
  // without erroring. The channel order is Terrarium's; the step is ours.
  terrain: () =>
    `Elevation in Terrarium channel order, quantised to ${TERRAIN_QUANTISATION_M} m steps. ` +
    "Real metres: the exaggeration is applied when it is drawn, not baked in here.",
  vector: (body) => `Vector geometry: the ${body.catalogue.plural} the globe draws and labels.`,
};

/** One dataset an archive owes a credit to, as the card lists it. */
export interface ArchiveSource {
  name: string;
  href: string;
  role: string;
  license: string;
}

export interface ArchiveRow {
  layer: LayerId;
  role: string;
  key: string;
  href: string;
  size: string;
  zooms: string;
  /** The credit inside the file, verbatim: what a downloader reproduces. */
  credit: string;
  /** The same obligation as a list, which is what a reader deciding on a download is asking. */
  sources: ArchiveSource[];
  /** How to turn this archive's pixels into what they encode, or null where they are the thing. */
  decode: string | null;
  tiles: string;
}

export interface ArchiveWorld {
  slug: BodySlug;
  label: string;
  current: ArchiveRow[];
  superseded: (ArchivedCut & { href: string })[];
}

/** Decimal GB and MB, because that is what a download manager and a bucket both report. */
export function humanSize(bytes: number): string {
  return bytes >= 1e9 ? `${(bytes / 1e9).toFixed(2)} GB` : `${(bytes / 1e6).toFixed(1)} MB`;
}

/** Every archive in the bucket, grouped by body.
 *
 *  BOTH REGISTRIES. `PUBLISHED` is what the site serves and `ARCHIVED` is what it used to; a
 *  re-cut moves an object from the first to the second, so an index built from `PUBLISHED` alone
 *  loses a row on the day a cut ships and describes half of what is downloadable.
 */
export function archiveIndex(): ArchiveWorld[] {
  return Object.values(BODIES).map((body) => ({
    slug: body.slug,
    label: body.label,
    current: (Object.keys(LAYER_ROLE) as LayerId[])
      .map((layer) => ({ layer, archive: PUBLISHED[body.slug][layer] }))
      .filter((row): row is { layer: LayerId; archive: NonNullable<typeof row.archive> } =>
        row.archive !== null,
      )
      .map(({ layer, archive }) => {
        const { credit, sources } = CREDITS.archives[`${body.slug}/${layer}`];
        return {
          layer,
          role: LAYER_ROLE[layer](body),
          key: archive.objectKey,
          href: `${ARCHIVE_BASE}${archive.objectKey}`,
          size: humanSize(archive.bytes),
          zooms: `z${archive.minZoom} to z${archive.maxZoom}`,
          credit,
          sources,
          // Elevation is the only layer whose pixels are a number rather than a picture, so it is
          // the only one a downloader can silently get wrong.
          decode: layer === "terrain" ? terrainDecodeExpression() : null,
          tiles: `${TILE_BASE}${tilePathTemplate(body.slug, layer)}`,
        };
      }),
    superseded: ARCHIVED.filter((cut) => cut.body === body.slug).map((cut) =>
      Object.assign({ href: `${ARCHIVE_BASE}${cut.key}` }, cut),
    ),
  }));
}
