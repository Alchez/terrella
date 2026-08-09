/** What is INSIDE one body's vector archive, by the role each named layer plays.
 *
 *  MVT carries several named layers per tile, so a body's vector products all travel in one
 *  archive — and which names are in there is the one thing about a vector pyramid that is neither
 *  transport (vectorTiles.ts, identical everywhere) nor address (tileAddress.ts). It is per body,
 *  and until a second planet cut vectors there was nothing to say so.
 *
 *  THE FAILURE THIS EXISTS TO CATCH IS SILENT AT EVERY LAYER. MapLibre renders a layer whose
 *  `source-layer` matches nothing as EMPTY — no error, no warning, no network difference — so a
 *  name that disagrees with the cutter produces a globe that draws nothing and says nothing. The
 *  writers are Python (`compose/countries_pmtiles.py`, `compose/features_pmtiles.py`), which no
 *  type system here reaches; `tests/test_source_layers.py` reads THIS FILE and compares it against
 *  both, so the seam fails loudly in CI instead of quietly on screen.
 */

import type { BodySlug } from "./bodies";

/** The jobs a named layer can do inside a vector archive.
 *
 *  A ROLE, not a layer name: `fill` is `country_fill` on Earth and `feature_fill` on Mars, and the
 *  code that styles a wash wants the role. Adding a role here is deliberately a hard error at every
 *  body below, on `PUBLISHED`'s rule — a role a planet was never asked about is a role somebody
 *  silently inherits. */
export type VectorRole = "fill" | "outline" | "hit" | "line" | "label";

/** Every body's answer for every role. `null` means "this archive has no such layer" and is a
 *  REQUIRED answer rather than an omission, so a new role cannot appear on every planet at once.
 *
 *  The two bodies disagree in both directions, which is the point: Earth carries a fat invisible
 *  hit target and no linework, Mars carries valles that have no interior to fill and the IAU's own
 *  label anchors, and neither shape could have been read off the other. */
export const SOURCE_LAYERS: Record<BodySlug, Record<VectorRole, string | null>> = {
  earth: {
    fill: "country_fill",
    outline: "country_outline",
    // One fat invisible target per polygon part, because a 176-atoll nation is unhittable
    // otherwise. Mars has no equivalent yet — its hit-testing is still to be designed.
    hit: "country_hit",
    line: null,
    label: null,
  },
  mars: {
    fill: "feature_fill",
    outline: "feature_outline",
    hit: null,
    // The two Earth has no use for. `line` is the valles and rupes, which are drawn features with
    // no interior; `label` is the gazetteer's own adopted centres, which a polygon centroid cannot
    // supply for a crescent and a line cannot supply at all.
    line: "feature_line",
    label: "feature_label",
  },
};

/** One body's layer name for one role, or null where its archive has no such layer.
 *
 *  Reads the record rather than letting a caller index it, so "this body has no hit layer" arrives
 *  as a null a caller must handle instead of an `undefined` that stringifies into a style spec and
 *  renders empty. */
export function sourceLayer(body: BodySlug, role: VectorRole): string | null {
  return SOURCE_LAYERS[body][role];
}

/** One body's layer name for a role its archive MUST carry, throwing where it does not.
 *
 *  THE THROW IS THE POINT, and it is what the literal imports this replaced gave for free. A name
 *  that arrives `null` reaches a style spec as `undefined`, and MapLibre answers an unaddressable
 *  `source-layer` by firing an ErrorEvent and RETURNING — no throw, no paint, nothing in the
 *  network panel. That is how the vector arm's hover shipped dead for a night. A caller that knows
 *  the layer has to exist says so here, and finds out at build time on the page's own smoke test
 *  rather than by looking at a globe that draws nothing. */
export function requireSourceLayer(body: BodySlug, role: VectorRole): string {
  const name = SOURCE_LAYERS[body][role];
  if (name === null) {
    throw new Error(
      `${body} publishes no ${role} source-layer, but something asked for one — either the archive ` +
        `gained that layer and SOURCE_LAYERS was not told, or the caller must handle its absence`,
    );
  }
  return name;
}

/** Every layer name in one body's archive, in role order — what a packer or a test enumerates. */
export function namedLayers(body: BodySlug): string[] {
  return Object.values(SOURCE_LAYERS[body]).filter((name): name is string => name !== null);
}
