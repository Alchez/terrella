// Mars's named features as data — the catalogue a tile cannot answer for.
//
// The vector tiles describe whatever is under the pointer, which is everything the globe needs
// while a visitor is pointing at something. This is the other half: every IAU name at once, so a
// feature can be found without first being seen, and a chosen one has a centre to fly to.
// `scripts/gen_feature_index.py` writes it and holds the reasoning for what it carries.
//
// TRACKED, SO THERE IS NO ABSENT CASE TO HANDLE — this is where it parts company with `manifest.ts`
// next door, whose JSON describes one machine's render store and is gitignored, and which therefore
// spends a `@ts-ignore` and a cast through `any` to type-check without it. This file's JSON is
// always on disk, so the import is ordinary and the assertion below is the only unchecked step.
//
// NAME IS A KEY HERE, AND ONLY BECAUSE THE PRODUCER MADE IT ONE. The gazetteer enters Bohar twice,
// identically, and `gen_feature_index.py` collapses rows that agree in every field — so a lookup by
// name is safe today and the tiles' `promoteId: "name"` addresses one crater whether it meets one
// polygon or two. It stays safe only while no edition publishes two DIFFERENT features under one
// name; the test asserts that rather than assuming it, because the failure would otherwise be a
// search result quietly missing.

import RECORDS from "./featureIndex.json";

export interface NamedFeature {
  /** The IAU name, as published. Also the tiles' `promoteId`, hence the feature-state id. */
  name: string;
  /** The IAU's own diacritic-free form, for matching what a visitor can actually type. */
  cleanName: string;
  /** The IAU descriptor term, e.g. `"Crater, craters"` — plural because the gazetteer pairs them. */
  type: string;
  /** The IAU's etymology. Populated for every feature, and the whole content of Mars's card. */
  origin: string;
  /**
   * The IAU diameter in km, or null where the gazetteer publishes a zero.
   *
   * A WIDTH on an areal feature and a LENGTH on a linear one — `featureTargeting.FeatureCandidate`
   * carries the same field with the same ambiguity, and states what it costs.
   */
  diameterKm: number | null;
  /** Folded to -180..180 by the producer. The gazetteer's own numbers are east-positive 0-360. */
  longitude: number;
  latitude: number;
}

// TypeScript infers the JSON's real shape, so this assertion is checked and not a rubber stamp —
// measured, by planting each failure: a field this interface names and the file lacks (a rename, a
// drop, a changed type) is an error here. What it CANNOT see is the mirror — a field the file
// carries and this interface omits converts silently — and it sees nothing about values at all. An
// unfolded longitude, a diameter in metres, a mis-sorted array: every one type-checks. That half is
// `featureIndex.test.ts`'s, and it is the half that would actually reach a visitor.
export const featureIndex = RECORDS as NamedFeature[];

const byName = new Map(featureIndex.map((feature) => [feature.name, feature]));

/**
 * The feature this name belongs to, or null.
 *
 * THE POINTER ANSWERS WITH A NAME AND THE CAMERA NEEDS A PLACE, and nothing in a tile closes that
 * gap: `features_geojson.CARRIED_FIELDS` leaves the centres out on purpose, so that a folded
 * geometry never travels beside an unfolded longitude. A clipped tile geometry cannot supply one
 * either — it is whatever survived the cut, not the feature. So a hit test can say WHAT was picked
 * and only this can say WHERE it is.
 *
 * Every name a tile can produce has a row here, because both sides are cut from the same two
 * gazetteer layers and the cutter drops a feature with no name — `tests/test_feature_index.py`
 * holds the two sets against each other rather than trusting that. Null is still the honest return:
 * the caller is handed an arbitrary string, and a lookup that threw would turn a stale name into a
 * broken globe instead of a click that does nothing.
 */
export function featureNamed(name: string): NamedFeature | null {
  return byName.get(name) ?? null;
}
