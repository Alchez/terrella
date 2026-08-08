import { BODIES, type BodySlug } from "./bodies";
import { PUBLISHED } from "./tileAddress";
import { tileUrlTemplate } from "./assetBase";

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
  /** The country vector pyramid: hit-testing, the hover chip, the highlight outline. */
  countries: boolean;
  /** The white boundary overlay, which is its own GeoJSON download rather than part of the
   *  countries pyramid — hence its own answer, and not one derived from `countries`. */
  borders: boolean;
  /** The in-globe hero panel a country click opens. Requires `countries`, since a click is
   *  hit-tested against that pyramid and there is no other route into the panel; the registry holds
   *  that rule, and `bodies.test.ts` enforces it. */
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
    countries: published.countries !== null && !bare,
    borders: descriptor.hasBorders && !bare,
    heroes: descriptor.hasHeroes && !bare,
  };
}

/** The tile URL templates a globe draws from. `null` where this body publishes no such pyramid. */
export interface GlobeTileAddresses {
  /** Always present. A globe with no relief is not a globe, so a body missing it is an error. */
  relief: string;
  terrain: string | null;
  countries: string | null;
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
    countries: drawn.countries ? tileUrlTemplate(body, "countries") : null,
  };
}
