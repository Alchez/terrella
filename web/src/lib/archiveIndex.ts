// What the downloads page lists, as data rather than as template frontmatter.
//
// SEPARATE FROM THE PAGE SO A GUARD CAN REACH IT. The first version of this lived in
// `archives.astro` and its test scanned the source for the word `ARCHIVED`, which the import line
// satisfies on its own: emptying the superseded list left that test green. A function returning
// rows is something a test can call and count.

import { ARCHIVE_BASE, TILE_BASE } from "./assetBase";
import { BODIES, type BodyDescriptor, type BodySlug } from "./bodies";
import CREDITS from "../data/attributions.json";
import BUNDLES from "../data/downloads.json";
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

/** What every card on the page carries, whatever kind of file it offers. */
interface ArchiveCard {
  heading: string;
  role: string;
  key: string;
  href: string;
  size: string;
  /** The credit inside the file, verbatim: what a downloader reproduces. */
  credit: string;
  /** The same obligation as a list, which is what a reader deciding on a download is asking. */
  sources: ArchiveSource[];
}

export interface ArchiveRow extends ArchiveCard {
  layer: LayerId;
  zooms: string;
  /** How to turn this archive's pixels into what they encode, or null where they are the thing. */
  decode: string | null;
  tiles: string;
}

/** A zip of images the site also offers one at a time, each carrying its credit inside it. */
export interface BundleRow extends ArchiveCard {
  images: number;
  sha256: string;
}

export interface ArchiveWorld {
  slug: BodySlug;
  label: string;
  current: ArchiveRow[];
  bundles: BundleRow[];
  superseded: (ArchivedCut & { href: string })[];
}

/** One bundle as `pipeline/compose/downloads.py bundle` records it. */
export interface BundleRecord {
  key: string;
  bytes: number;
  sha256: string;
  /** Each image the bundle holds, by name, with its size in bytes. */
  images: Record<string, number>;
  /** The source keys every image in it was rendered from. */
  sources: string[];
  /** The credit each image carries inside it, verbatim. */
  credit: string;
}

const BUNDLE_RECORDS: Partial<Record<BodySlug, BundleRecord>> = BUNDLES;

/** One source as the registry's cards draw it, refused if the registry has no such key. */
export function sourceCard(key: string): ArchiveSource {
  const card = (CREDITS.sources as Record<string, ArchiveSource | undefined>)[key];
  if (card === undefined) throw new Error(`attributions.json has no source ${key}`);
  return card;
}

/** A body's country maps bundle as its card lists it, credited as the images inside it are. */
function bundleRows(body: BodyDescriptor): BundleRow[] {
  const record = BUNDLE_RECORDS[body.slug];
  if (!record) return [];
  return [
    {
      heading: "Country maps",
      role:
        "Every country's image at the full size it was rendered, as WebP, with its credit inside " +
        "each file. A PNG copy of each, for print, is on its country's page.",
      key: record.key,
      href: `${ARCHIVE_BASE}${record.key}`,
      size: humanSize(record.bytes),
      images: Object.keys(record.images).length,
      sha256: record.sha256,
      credit: record.credit,
      sources: record.sources.map((key) => sourceCard(key)),
    },
  ];
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
          heading: `${layer.charAt(0).toUpperCase()}${layer.slice(1)}`,
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
    bundles: bundleRows(body),
    superseded: ARCHIVED.filter((cut) => cut.body === body.slug).map((cut) =>
      Object.assign({ href: `${ARCHIVE_BASE}${cut.key}` }, cut),
    ),
  }));
}
