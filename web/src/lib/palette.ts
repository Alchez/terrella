// Colours the PIPELINE owns, restated for the browser.
//
// pipeline/look/palette.py is the single source of truth for the hypsometric ramps, and it
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

/** `_srgb8(MARS_LOOK.land.stop_at(655))` — the +655 m stop the ramp names the modal elevation, so
 *  it is the
 *  tone most of Mars is. Mars's `space-floor`, on the rule that gives Earth `DEEP_SEA`: a missing
 *  tile must read as more of this planet. The `#6b3a2a` it replaced was darker than any Mars tile.
 *
 *  The named stop rather than the ramp at the measured median: a stop pins with one `_srgb8` line
 *  where a median drifts with the data.
 *
 *  AUTHORED, LIKE EVERY OTHER CONSTANT ABOVE, AND IT NOW AGREES WITH `MARS_RAMP`'s 0.550 ENTRY
 *  RATHER THAN DIFFERING FROM IT. The two were `#BE885E` here against `#C6824F` there for as long
 *  as Mars composited, because a flat backdrop no compositor touches and a ramp matching pixels
 *  that went through one are different jobs. Mars raytraces now, so the ramp stopped going through
 *  one and the two jobs happen to have the same answer — a coincidence of producer, not a
 *  duplication to collapse. */
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
 * THE RULE IS "WHATEVER MARS'S PRODUCER PAINTS", AND THE ANSWER MOVED ONCE ALREADY. A legend
 * states that a colour means a height, so it has to carry the colour the TILES carry — not the
 * colour the stops are authored as, and not whichever of the two was right when it was written.
 * These were the COMPOSITED stops while `MARS.planet_producer` was `"composite"`, because
 * `shade.composite` resaturates land by `KNOBS["saturation"]` 1.18 and warms it by
 * `KNOBS["warmth"]` 0.06 on the way to a tile. Mars raytraces now and the rig applies neither, so
 * the authored stop IS what ships and these are the authored stops. They were left composited
 * across that switch and drew up to 16 DN of blue away from the map for as long as that lasted.
 *
 * WHAT IS DELIBERATELY *NOT* IN THEM IS LIGHT. A tile is also multiplied by terms that vary per
 * pixel — a hillshade, an ambient, an exposure under the composite; a whole Cycles solve under the
 * raytrace — so no single swatch can carry them and the honest legend shows the ramp with the
 * light left off. `palette.py` annotates its first stop as shipping `#804D35`, which samples FLAT
 * LIT GROUND: a reading off the map, not the ramp.
 *
 * Earth's ramp is declared beside the legend that draws it, in `aboutContent.ts`, because it is
 * hand-authored rather than derived and so has no constants here to answer to. That module's
 * `EARTH_RAMP` says why, and its stops are NOT this rule applied to Earth.
 *
 * RATIFIED AT THE FURTHER OF THE TWO, KNOWINGLY, AND DO NOT "FIX" IT BACK. Measured against the
 * shipped raster over six windows from -61.6 to +48.9 latitude and 16.2M flat-ground pixels, these
 * authored stops sit ~11 DN from what the tiles actually draw and the composited ones they replaced
 * sat ~8. The old key was closer BY ACCIDENT: its chroma chain happened to point the same way as
 * the raytracer's tone map, and that coincidence dies at the next look change. What a legend states
 * is the ramp, and under this producer the ramp IS these stops — the ~7% that remains is light,
 * which no swatch has ever carried. Reverting on the distance alone re-hand-copies the key from a
 * producer Mars does not use, which is the state that let it rot silently for the whole arc.
 *
 * `tests/test_palette.py::test_web_mars_ramp_matches_what_mars_actually_ships` recomputes every
 * entry from `MARS_LAND_STOPS` through `MARS.planet_producer`, and fails on drift in the stops,
 * the producer, or a knob the producer in force reads. */
export const MARS_RAMP: readonly RampStop[] = [
  { at: 0.0, hex: "#5D3C2D" }, // ~-8,600 m, below Mars's measured floor so nothing clips
  { at: 0.17687075, hex: "#784F3C" }, // ~-6,000 m, p1 of the heightfield
  { at: 0.30034014, hex: "#8F5F49" }, // ~-4,185 m, lowland plains
  { at: 0.46496599, hex: "#AC7351" }, // ~-1,765 m, the northern lowlands
  { at: 0.62959184, hex: "#BE885E" }, // ~  +655 m, just above the areoid — the modal elevation
  { at: 0.81891156, hex: "#CBA378" }, // ~+3,438 m, southern highlands
  { at: 1.0, hex: "#D4BF9D" }, // ~+6,100 m, Tharsis and the volcanic summits
];

/** A ramp as a `linear-gradient(...)` value. One writer, so a second legend cannot spell it
 *  differently — and the stops stay data, which is what lets the test above pin them. */
export function rampGradient(stops: readonly RampStop[]): string {
  const points = stops.map((stop) => `${stop.hex} ${(stop.at * 100).toFixed(2)}%`);
  return `linear-gradient(90deg, ${points.join(", ")})`;
}
