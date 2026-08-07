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
 *  where a median drifts with the data. */
export const MARS_MODAL_GROUND = "#BE885E";
