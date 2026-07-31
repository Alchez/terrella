// How many render-to-texture passes our layer order costs, once terrain is on.
//
// WHY THIS IS A MODULE AND NOT A COMMENT. With terrain enabled MapLibre does not draw style
// layers to the screen; it draws them into a texture per terrain tile, then drapes that texture
// over the mesh. It batches consecutive drapeable layers into one "stack" and allocates one RTT
// object per renderable terrain tile PER STACK — and at our declared sizes each of those is
// exactly 1 MiB (see rttPoolTrim.ts). So a single non-drapeable layer sitting in the middle of
// the order is not a style detail. It is a multiplier on GPU memory, and an invisible one: the
// map looks identical, nothing errors, and the only symptom is a card that fills faster.
//
// That is what `country-hit` was doing — a `circle` with `circle-opacity: 0` between the country
// fill and the border lines, splitting one run into two and costing a third of the pool to draw
// nothing. Moving it to the end fixed it. This module exists so the next layer added in the
// wrong place fails a test instead of quietly costing a third again.
//
// NOTHING HERE IS PUBLIC MAPLIBRE API. `LAYERS_TO_TEXTURES` is private to
// render/render_to_texture.ts, so the set below is a copy and the canary in this module's test
// file reads the shipped bundle to prove it still matches. If MapLibre ever starts draping
// `circle`, that canary fails and this whole precaution can be deleted.

/**
 * Layer types MapLibre renders into the terrain texture rather than straight to the screen.
 *
 * Mirrors `LAYERS_TO_TEXTURES` in the shipped bundle. Anything absent — `circle`, `symbol`,
 * `custom`, `heatmap`, `fill-extrusion` — interrupts a run.
 */
export const DRAPED_LAYER_TYPES: readonly string[] = [
  "background",
  "fill",
  "line",
  "raster",
  "hillshade",
  "color-relief",
];

export function isDraped(layerType: string): boolean {
  return DRAPED_LAYER_TYPES.includes(layerType);
}

/**
 * Number of RTT stacks a layer order produces — i.e. the multiplier on the RTT pool.
 *
 * A stack opens when a drapeable layer follows a non-drapeable one (or opens the style), and
 * runs until the next non-drapeable layer. Non-drapeable layers at either END are free: a
 * leading one has no run to split, and a trailing one terminates the last run rather than
 * starting a new one. That asymmetry is the whole reason moving a layer to the end is a saving
 * and moving it to the middle is a cost.
 */
export function drapeStackCount(layerTypes: readonly string[]): number {
  let stacks = 0;
  let previousWasDraped = false;
  for (const layerType of layerTypes) {
    const draped = isDraped(layerType);
    if (draped && !previousWasDraped) stacks += 1;
    previousWasDraped = draped;
  }
  return stacks;
}

/**
 * The globe's layer order, as types, in the sequence the page adds them.
 *
 * Written down because no single call site holds it — `space-floor`/`relief-base`/`relief` come
 * from the style literal, the caps from a dynamic import on `style.load`, and the country layers
 * from a fetch on first `idle`. A reader cannot see the order by reading any one of them, and it
 * is the ORDER that costs memory.
 *
 * `borders` are included because the toggle is persisted, so a returning visitor loads with them
 * on; they are `line` and therefore free. Kept as types rather than ids: the cost depends on
 * nothing else.
 */
export const GLOBE_LAYER_TYPES: readonly string[] = [
  "background", // space-floor
  "raster", // relief-base
  "raster", // relief
  "custom", // polar-cap-north
  "custom", // polar-cap-south
  "fill", // country-fill
  "line", // b-casing-solid   ) borders, when toggled on
  "line", // b-casing-dashed  )
  "line", // b-ink-solid      )
  "line", // b-ink-dashed     )
  "line", // country-hl-casing
  "line", // country-hl-line
  "circle", // country-hit — LAST on purpose; see addCountryHitTargets in globe.astro
];
