// Colours the PIPELINE owns, restated for the browser.
//
// pipeline/render/palette.py is the single source of truth for the hypsometric ramps, and it
// holds them in LINEAR RGB — the space the Cycles shader and the tile compositor both work in.
// Nothing here can import that, so each value below is the 8-bit sRGB encoding of a named stop,
// hand-copied and pinned by tests/test_palette.py::TestSharedConstants, which recomputes it
// through palette._srgb8 and fails if this file drifts.
//
// That guard is not ceremony. WATER_RGB drifted ~15% brighter than the sea surface it was
// supposed to match, for exactly this reason: a copied colour with nothing comparing it back.
// Anything added here needs a line in that test in the same edit.

// These are AUTHORED stops, not shipped pixels: `shade.KNOBS` resaturates land 1.18 and warms it
// 0.06, so `#784F3C` ships as `#814D35`.
//
// The chrome ACCENTS live in `bodies.ts`, not here. Deriving them from stops was tried, measured
// against the shipped ramp, and reverted — do not retry it.

/** `_srgb8(SEA_STOPS[4])` — the −3,800 m abyssal-plain stop, the tone most of the sea floor
 *  actually is. The globe's background layer, so an uncovered tile reads as deep ocean
 *  rather than as a hole to space. */
export const DEEP_SEA = "#47808F";

/** `_srgb8(SEA_STOPS[5])` — the −6,000 m trench floor. Earth's light-scheme accent, which had been
 *  hand-typed in `bodies.ts` while equalling this stop exactly: right by luck, and unguarded. */
export const TRENCH_FLOOR = "#3A6E7D";

/** `_srgb8(MARS_LAND_STOPS[3])` — the +655 m stop the ramp names the modal elevation, so it is the
 *  tone most of Mars is. Mars's `space-floor`, on the rule that gives Earth `DEEP_SEA`: a missing
 *  tile must read as more of this planet. The `#6b3a2a` it replaced was darker than any Mars tile.
 *
 *  The named stop rather than the ramp at the measured median: a stop pins with one `_srgb8` line
 *  where a median drifts with the data.
 *
 *  AUTHORED, LIKE EVERY OTHER CONSTANT ABOVE, WHICH IS WHY IT DIFFERS FROM `MARS_RAMP`'s 0.550
 *  ENTRY (`#C6824F`). Both are correct for their own job: this one is a flat backdrop that no
 *  compositor ever touches, while the ramp below has to match pixels that went through one. */
export const MARS_MODAL_GROUND = "#BE885E";

/** One hypsometric ramp stop, as the legend draws it: where it sits on the ramp, and its colour. */
export interface RampStop {
  /** Position along the ramp, 0 at its low end and 1 at its high end. */
  at: number;
  /** 8-bit sRGB, `#RRGGBB`. */
  hex: string;
}

/** Mars's elevation ramp, for the legend that claims a colour means a height.
 *
 * THESE ARE COMPOSITED COLOURS AND THE CONSTANTS ABOVE ARE NOT, which is the whole reason this is
 * a separate export rather than six more `_srgb8` lines. `shade.composite` resaturates land by
 * `KNOBS["saturation"]` 1.18 and warms it by `KNOBS["warmth"]` 0.06 on the way to a tile, so the
 * authored stop `#784F3C` is never a colour anything paints. A legend built from authored stops
 * would state a correspondence the map does not keep — which is the one thing a legend exists to
 * get right.
 *
 * WHAT IS DELIBERATELY *NOT* IN THEM IS LIGHT. `composite` also multiplies by a hillshade, an
 * ambient term and an exposure, and those vary per pixel with the terrain — so no single swatch
 * can carry them and the honest legend shows the ramp with the light left off. `palette.py`
 * annotates its first stop as shipping `#804D35`, about 2% brighter than the `#7E4B33` here,
 * because that annotation samples FLAT LIT GROUND: it is a reading off the map, not the ramp.
 *
 * Earth has no counterpart here because its ramp is still the hand-written gradient in
 * `global.css`. That copy is older than this file and equally unpinned; moving it here is worth
 * doing and is not this change.
 *
 * `tests/test_palette.py::test_web_mars_ramp_matches_the_composited_stops` recomputes every entry
 * from `MARS_LAND_STOPS` through `shade.KNOBS` and fails on drift in either. */
export const MARS_RAMP: readonly RampStop[] = [
  { at: 0.0, hex: "#7E4B33" }, // ~-6,000 m, the deepest basin floors
  { at: 0.15, hex: "#965A3F" }, // ~-4,185 m, lowland plains
  { at: 0.35, hex: "#B46D44" }, // ~-1,765 m, the northern lowlands
  { at: 0.55, hex: "#C6824F" }, // ~  +655 m, just above the areoid — the modal elevation
  { at: 0.78, hex: "#D19D68" }, // ~+3,438 m, southern highlands
  { at: 1.0, hex: "#D7B98D" }, // ~+6,100 m, Tharsis and the volcanic summits
];

/** A ramp as a `linear-gradient(...)` value. One writer, so a second legend cannot spell it
 *  differently — and the stops stay data, which is what lets the test above pin them. */
export function rampGradient(stops: readonly RampStop[]): string {
  const points = stops.map((stop) => `${stop.hex} ${(stop.at * 100).toFixed(2)}%`);
  return `linear-gradient(90deg, ${points.join(", ")})`;
}
