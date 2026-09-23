import type { Country } from "./manifest";

/** Whether a country has its own page and gallery card: every one but a place the globe and its
 *  search carry alone. A hero not yet rendered still has its page. */
export function hasOwnPage(country: Country): boolean {
  return !country.listedOnly;
}
