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

/** `_srgb8(SEA_STOPS[4])` — the −3,800 m abyssal-plain stop, the tone most of the sea floor
 *  actually is. The globe's background layer, so an uncovered tile reads as deep ocean
 *  rather than as a hole to space. */
export const DEEP_SEA = "#47808F";
