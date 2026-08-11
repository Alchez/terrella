// Finding a Martian feature by typing at it — the half of the catalogue no pointer can reach.
//
// The globe answers what is under the pointer, which requires already knowing where to point. This
// answers the other question: a visitor who has heard of Olympus Mons, or who wants to see a crater
// and does not know one by name. No labels are drawn on this body, so this is the ONLY way a name
// enters the interface without being hunted for.
//
// WHAT A QUERY IS ALLOWED TO REACH IS THE NAME AND THE DESCRIPTOR, and the descriptor half is not a
// nicety. The IAU's classification splits cleanly: a crater is named for a person and never carries
// the word "crater", while every other kind carries its own Latin term inside the name — Olympus
// *Mons*, Hellas *Planitia*. So "mons" is answered by the names alone and "crater" is answered by
// nothing at all unless the descriptor is searchable. The etymology is deliberately NOT searchable:
// it would turn a name search into a full-text search, where a query stops meaning "this place" and
// the result list stops being a list of destinations.
//
// IT TAKES THE CATALOGUE RATHER THAN IMPORTING IT, and that is a bundle constraint, not a taste.
// `Globe.astro` pulls `featureIndex` through a dynamic `import()` precisely so that Earth's visitors
// never download Martian place names — both bodies mount one component and therefore share one
// client chunk. A value import of the index from here would be reached statically by that shared
// component and would undo the split, silently and with every gate green. `import type` is erased,
// so the shape may be named; the array may not be fetched.

import type { NamedFeature } from "./featureIndex";

/** A query's answer: the ranked page of it, and how many there were before the cap. */
export interface SearchResults {
  /** Best first, no longer than the requested limit. */
  matches: NamedFeature[];
  /** Every feature that matched, so a caller can say "10 of 160" rather than implying 10. */
  total: number;
}

export interface FeatureSearch {
  /** The best `limit` features for this query. An empty or punctuation-only query matches nothing. */
  search(query: string, limit: number): SearchResults;
}

/**
 * A string reduced to what a comparison should see: lower case, no diacritics.
 *
 * DO NOT "SIMPLIFY" THIS TO `normalize("NFD").replace(/\p{M}/gu, "")` — that is the whole function
 * except for the first step, and dropping it is silent. `ł` is a distinct letter rather than an `l`
 * carrying a combining mark, so NFD has nothing to decompose and leaves it standing; a visitor
 * typing the obvious ASCII spelling of a name containing one then matches nothing, and every other
 * name in the catalogue keeps working. The catalogue's own coverage is asserted in the test.
 *
 * Punctuation survives here on purpose. It is the tokeniser's business, and it needs to see it.
 */
export function foldForSearch(text: string): string {
  return text
    .replace(/ł/g, "l")
    .replace(/Ł/g, "L")
    .normalize("NFD")
    .replace(/\p{M}/gu, "")
    .toLowerCase();
}

/** Everything a query term may prefix, for one whitespace-separated word.
 *
 *  BOTH READINGS OF A PUNCTUATED WORD ARE KEPT, because the two are wanted by different queries and
 *  neither implies the other: joining reaches `Koval'sky` from "kovalsky" and `Airy-0` from "airy0",
 *  splitting reaches `Al-Qahira Vallis` from "qahira". A single rule here would answer one of those
 *  and quietly lose the other. */
function wordTokens(word: string): string[] {
  const joined = word.replace(/[^a-z0-9]+/g, "");
  return joined ? [joined, ...word.split(/[^a-z0-9]+/).filter(Boolean)] : [];
}

/** The tokens of a whole published name. */
function nameTokens(name: string): string[] {
  const tokens = new Set<string>();
  for (const word of foldForSearch(name).split(/\s+/)) {
    for (const token of wordTokens(word)) tokens.add(token);
  }
  return [...tokens];
}

/** The tokens of an IAU descriptor term, which the gazetteer publishes as a singular/plural pair —
 *  so both spellings of the kind are typeable. */
function descriptorTokens(type: string): string[] {
  return [
    ...new Set(
      foldForSearch(type)
        .split(/[^a-z0-9]+/)
        .filter(Boolean),
    ),
  ];
}

/**
 * A typed query split into the terms every one of which must match.
 *
 * Splitting on punctuation as well as whitespace is what lets a visitor type a name the way it is
 * published — "koval'sky" becomes the two terms the tokeniser already holds, and "kovalsky" stays
 * the one term it also holds.
 */
export function queryTerms(query: string): string[] {
  return foldForSearch(query)
    .split(/[^a-z0-9]+/)
    .filter(Boolean);
}

// How well a match answers the query, ascending — the first two columns of the sort. Plain numbers
// rather than an `enum`, which is the one TypeScript construct this build cannot erase per-file.
/** Every term reached the name. */
const TIER_NAME = 0;
/** The kind had to answer for at least one term. */
const TIER_DESCRIPTOR = 1;

/** The query IS the name, ignoring case, marks and punctuation. */
const LEAD_EXACT = 0;
/** The name begins with the query. */
const LEAD_LEADING = 1;
/** The query reached a later word, or the descriptor. */
const LEAD_ELSEWHERE = 2;

interface Entry {
  feature: NamedFeature;
  nameTokens: string[];
  everyToken: string[];
  /** The name with case, marks, punctuation AND spaces gone — what `Lead` is decided against. */
  flatName: string;
}

interface Match {
  entry: Entry;
  tier: number;
  lead: number;
}

function everyTermPrefixes(terms: string[], tokens: string[]): boolean {
  return terms.every((term) => tokens.some((token) => token.startsWith(term)));
}

/**
 * Rank two matches. Tier, then where in the name the query landed, then SIZE.
 *
 * DIAMETER DESCENDING IS THE TIE-BREAK BECAUSE THE CAP MAKES IT THE PRODUCT. A one- or two-letter
 * query matches most of the catalogue, so which handful survives the slice is the entire answer a
 * visitor sees — and alphabetical order would answer every broad query with whatever happens to
 * start with an A. Size is the only prominence signal this index carries, and on a map the large
 * thing is the one being looked for. `null` sorts last: the gazetteer publishes no size for it, so
 * there is nothing to claim, and name order settles the rest so the list never reshuffles itself.
 */
function byRelevance(first: Match, second: Match): number {
  if (first.tier !== second.tier) return first.tier - second.tier;
  if (first.lead !== second.lead) return first.lead - second.lead;
  const firstSize = first.entry.feature.diameterKm ?? Number.NEGATIVE_INFINITY;
  const secondSize = second.entry.feature.diameterKm ?? Number.NEGATIVE_INFINITY;
  if (firstSize !== secondSize) return secondSize - firstSize;
  return first.entry.feature.name.localeCompare(second.entry.feature.name);
}

/**
 * Build a matcher over a catalogue.
 *
 * The tokens are built ONCE, here, rather than per query: folding and splitting every name on each
 * keystroke is the only part of this that is not trivially cheap, and a search box calls `search`
 * on every one. Matching itself is a linear scan — the catalogue is small enough that an inverted
 * index would be a structure to keep correct in exchange for nothing measurable.
 */
export function createFeatureSearch(features: readonly NamedFeature[]): FeatureSearch {
  const entries: Entry[] = features.map((feature) => {
    const names = nameTokens(feature.name);
    return {
      feature,
      nameTokens: names,
      everyToken: [...new Set([...names, ...descriptorTokens(feature.type)])],
      flatName: foldForSearch(feature.name).replace(/[^a-z0-9]+/g, ""),
    };
  });

  function search(query: string, limit: number): SearchResults {
    const terms = queryTerms(query);
    if (terms.length === 0) return { matches: [], total: 0 };
    const flatQuery = terms.join("");

    const found: Match[] = [];
    for (const entry of entries) {
      const onName = everyTermPrefixes(terms, entry.nameTokens);
      if (!onName && !everyTermPrefixes(terms, entry.everyToken)) continue;
      const lead = !onName
        ? LEAD_ELSEWHERE
        : entry.flatName === flatQuery
          ? LEAD_EXACT
          : entry.flatName.startsWith(flatQuery)
            ? LEAD_LEADING
            : LEAD_ELSEWHERE;
      found.push({ entry, tier: onName ? TIER_NAME : TIER_DESCRIPTOR, lead });
    }

    found.sort(byRelevance);
    return {
      matches: found.slice(0, Math.max(0, limit)).map((match) => match.entry.feature),
      total: found.length,
    };
  }

  return { search };
}
