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

// EVERY VALUE HERE IS THE AUTHORED STOP, NOT THE SHIPPED PIXEL, and that is the contract rather
// than an oversight: `shade.KNOBS` resaturates land by 1.18 and warms it by 0.06 before a tile is
// written, so chrome taken from a stop sits a touch cooler than the tiles beside it. Tracking the
// shipped tone instead would mean re-deriving these through the compositor, which would put a UI
// colour downstream of every look knob — and the authored stop is the only value this file's guard
// can recompute. Both bodies do it the same way, so the offset is consistent rather than a drift.

/** `_srgb8(SEA_STOPS[4])` — the −3,800 m abyssal-plain stop, the tone most of the sea floor
 *  actually is. The globe's background layer, so an uncovered tile reads as deep ocean
 *  rather than as a hole to space. */
export const DEEP_SEA = "#47808F";

/** `_srgb8(SEA_STOPS[5])` — the −6,000 m trench floor, the sea ramp's dark extreme, and Earth's
 *  light-scheme accent. It had been hand-typed into `bodies.ts` while equalling this stop exactly:
 *  a copy that happens to be right is still the WATER_RGB shape, since nothing compared it back. */
export const TRENCH_FLOOR = "#3A6E7D";

/** `_srgb8(MARS_LAND_STOPS[0])` — the −6,000 m basin floor, the Mars ramp's dark extreme, and its
 *  light-scheme accent for the reason `TRENCH_FLOOR` is Earth's: an accent on a light ground has to
 *  be the dark end of something, and the map is the something. */
export const MARS_BASIN_FLOOR = "#784F3C";

/** `_srgb8(MARS_LAND_STOPS[3])` — the +655 m stop the ramp's own comment names the modal elevation,
 *  so it is the tone most of Mars actually is. Mars's `space-floor`, on the rule that makes Earth's
 *  `DEEP_SEA`: what shows through a missing tile must read as more of this planet. Deliberately the
 *  named stop rather than the ramp evaluated at the measured median — same colour to the eye, and a
 *  stop is pinnable by one `_srgb8` line where a median is a number that drifts with the data. */
export const MARS_MODAL_GROUND = "#BE885E";

/** `_srgb8(MARS_LAND_STOPS[5])` — Tharsis and the volcanic summits, the Mars ramp's light extreme,
 *  and its dark-scheme accent.
 *
 *  NO EARTH COUNTERPART, and the asymmetry is a decision rather than a gap: Earth's dark accent is
 *  `#7cb8b8`, which is not `SEA_STOPS[0]` and was picked by eye over it. Mars's light extreme
 *  happened to work where Earth's did not, so Mars is the more derived of the two bodies here. */
export const MARS_SUMMITS = "#D4BF9D";
