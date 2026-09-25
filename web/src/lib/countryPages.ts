import CREDITS from "../data/attributions.json";
import { type ArchiveSource, sourceCard } from "./archiveIndex";
import type { Country } from "./manifest";

/** Whether a country has its own page and gallery card: every one but a place the globe and its
 *  search carry alone. A hero not yet rendered still has its page. */
export function hasOwnPage(country: Country): boolean {
  return !country.listedOnly;
}

/** The datasets a country page credits under its image: what its hero was rendered from, then what
 *  its Focus layer draws, once each. None for a country with no image. */
export function imageSources(country: Country): ArchiveSource[] {
  if (!country.rendered) return [];
  const focus = country.hasSpotlight ? CREDITS.heroes.earth.focus : [];
  return [...new Set([...country.heroSources, ...focus])].map((key) => sourceCard(key));
}
