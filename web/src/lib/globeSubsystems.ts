import { BODIES, type BodySlug } from "./bodies";
import { PUBLISHED } from "./tileAddress";
import { tileUrlTemplate } from "./assetBase";
import { VECTOR_PRODUCT, type VectorProduct } from "./sourceLayers";

/**
 * What one body's globe draws, beyond the relief raster every globe draws.
 *
 * WHY THIS IS A MODULE AND NOT FIVE `&&`s IN THE PAGE. The five answers below are consumed at five
 * different moments — module scope, `style.load`, the first `idle`, a click, and the tier ladder's
 * runtime downgrade — and they have to be the SAME answers each time. Written inline, each site
 * spells its own condition, and the spellings drift in the direction nobody sees: a globe that
 * fetches a `caps.json` for a body with no caps gets a 404 the console swallows, and one that skips
 * a layer Earth publishes just looks like slow loading. Written here, they are one expression with
 * a test, and `?bare` stops being a special case — a body that publishes only relief and a visitor
 * asking to see only relief want exactly the same globe.
 *
 * THE BODY IS ASKED BEFORE THE URL, and the order is the point rather than a style. Absence is not
 * a statement: an archive that does not answer cannot distinguish "this planet has none" from "the
 * upload has not landed", so nothing here probes for a layer and infers from what it finds. The
 * registry says what exists; the flags only take things away.
 *
 * `?bare` DELIBERATELY DOES NOT TOUCH TERRAIN, which is why one field below reads differently from
 * the rest. The flag isolates the raster baseline from the things drawn OVER it — caps, vectors,
 * borders, highlight. Terrain is not over the raster; it is the raster given a third dimension, so
 * `?bare&terrain=2` is a combination worth being able to ask for, and stripping it here would
 * silently delete a diagnostic.
 */
export interface GlobeSubsystems {
  /** The two azimuthal-equidistant polar textures that repair the Mercator projection above ~85°.
   *  Off does NOT leave a hole: MapLibre stretches the top tile row over the gap, so the pole
   *  becomes `shade_planet.CAP_RGB`, a flat pale disc that reads as a decision rather than a
   *  defect. That is why this is a repair every body wants and not a layer only Earth needs. */
  polarCaps: boolean;
  /** The terrain-RGB displacement layer. Publishing the pyramid is necessary but not sufficient —
   *  the tier ladder and `?terrain=` still decide whether it is switched on for this visit. */
  terrain: boolean;
  /** Which vector overlay this globe draws, or null where it draws none.
   *
   *  NOT A BOOLEAN, AND THAT IS THE SECOND BODY'S DOING. This was `countries`, derived from
   *  `PUBLISHED[body].vector` alone — which read correctly while Earth was the only planet cutting
   *  vectors and inverted the moment Mars published: the flag turned true for Mars and the globe
   *  would have added style layers naming `country_fill`, a name Mars's archive does not hold.
   *  MapLibre paints an unmatched `source-layer` as EMPTY, so the symptom is a globe that draws
   *  nothing and reports nothing. The archive says which product is in it; this passes that answer
   *  through to the one place that has to branch on it. */
  vectorProduct: VectorProduct | null;
  /** The white boundary overlay, which is its own GeoJSON download rather than part of the
   *  vector pyramid — hence its own answer, and not one derived from `countries`. */
  borders: boolean;
  /** The in-globe hero panel a country click opens. Requires the `countries` product, since a click
   *  is hit-tested against that pyramid and there is no other route into the panel; the registry
   *  holds that rule, and `bodies.test.ts` enforces it. */
  heroes: boolean;
}

/**
 * Resolve what this globe draws, from the registry and then the URL.
 *
 * `flags` is the page's own `URLSearchParams`, taken as an argument rather than read from
 * `location` so this is a pure function of its inputs — which is what lets a test ask what Mars
 * draws without a Mars page existing yet.
 */
export function globeSubsystems(body: BodySlug, flags: URLSearchParams): GlobeSubsystems {
  const descriptor = BODIES[body];
  const published = PUBLISHED[body];
  const bare = flags.has("bare");
  return {
    // `?nocaps` predates `?bare` and stays its own flag: it isolates the caps alone, which is how
    // the black-disc-on-context-restore bug was cornered.
    polarCaps: descriptor.rendersPolarCaps && !bare && !flags.has("nocaps"),
    terrain: published.terrain !== null,
    vectorProduct: published.vector !== null && !bare ? VECTOR_PRODUCT[body] : null,
    borders: descriptor.hasBorders && !bare,
    heroes: descriptor.hasHeroes && !bare,
  };
}

/**
 * Does this body light anything under the pointer at all?
 *
 * ASKED BY THE LAYOUT, WHICH HAS NO MAP, so it cannot go through {@link globeSubsystems} — that
 * function answers for one page load and takes the URL flags, and a control's EXISTENCE must not
 * depend on a diagnostic query string. The hover paint hangs off the vector overlay on both bodies,
 * so publishing a vector archive is exactly the condition.
 *
 * A BUTTON FOR SOMETHING A BODY DOES NOT HAVE IS THE FAILURE THIS PREVENTS, and the registry is the
 * only thing that can see it. Both bodies publish vectors today, so this reads `true` twice — the
 * point is that a third body publishing only relief gets no dead control rather than one that
 * toggles nothing and reports nothing. Same rule the borders button follows.
 */
export function hasHoverHighlight(body: BodySlug): boolean {
  return PUBLISHED[body].vector !== null;
}

/** The tile URL templates a globe draws from. `null` where this body publishes no such pyramid. */
export interface GlobeTileAddresses {
  /** Always present. A globe with no relief is not a globe, so a body missing it is an error. */
  relief: string;
  terrain: string | null;
  vector: string | null;
}

/**
 * Build the addresses, asking the registry before building any of them.
 *
 * THIS IS HERE RATHER THAN IN THE PAGE BECAUSE OF WHAT IT USED TO DO. `tileUrlTemplate` THROWS for
 * a layer the body does not publish, and the page called it three times unconditionally, at module
 * scope — so a body publishing only relief threw before a map existed, and the globe was a blank
 * page with one line in a console nobody has open on a phone. Moved here it is a pure function of a
 * slug, which is what lets a test ask for Mars's addresses today, with no Mars globe to load.
 *
 * Relief stays eager and is allowed to throw: it is the one archive every globe must have, so its
 * absence is a real error and belongs beside the declaration that names it.
 */
export function globeTileAddresses(body: BodySlug, drawn: GlobeSubsystems): GlobeTileAddresses {
  return {
    relief: tileUrlTemplate(body, "relief"),
    terrain: drawn.terrain ? tileUrlTemplate(body, "terrain") : null,
    vector: drawn.vectorProduct !== null ? tileUrlTemplate(body, "vector") : null,
  };
}
