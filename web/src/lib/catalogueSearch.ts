// Finding a place by typing at it — the half of a catalogue no pointer can reach.
//
// The globe answers what is under the pointer, which requires already knowing where to point. This
// answers the other question: a visitor who has heard of Olympus Mons, or who wants to see a crater
// and does not know one by name. No labels are drawn on either body, so this is the ONLY way a name
// enters the interface without being hunted for.
//
// IT RANKS `SearchEntry`, NOT A BODY'S OWN RECORD, which is the same trade `detailPanel.ts` makes
// one layer up: the card takes what it renders and each body owns the builder that produces it.
// Typed on Mars's `NamedFeature`, the ranking reached for `type` and `diameterKm` — an IAU
// descriptor and a crater width, neither of which a country has — so Earth could only have arrived
// by growing that record with fields meaning nothing on Mars, or by forking the matcher.
//
// WHAT A QUERY IS ALLOWED TO REACH IS THE NAME AND `terms`, and that second half is not a nicety.
// The IAU's classification splits cleanly: a crater is named for a person and never carries the word
// "crater", while every other kind carries its own Latin term inside the name — Olympus *Mons*,
// Hellas *Planitia*. So "mons" is answered by the names alone and "crater" is answered by nothing at
// all unless the kind is searchable. What a body must NOT put in `terms` is prose: Mars's etymology
// would turn a name search into a full-text search, where a query stops meaning "this place" and the
// result list stops being a list of destinations.
//
// IT TAKES THE CATALOGUE RATHER THAN IMPORTING IT, and that is a bundle constraint, not a taste.
// `Globe.astro` pulls `featureIndex` through a dynamic `import()` precisely so that Earth's visitors
// never download Martian place names — both bodies mount one component and therefore share one
// client chunk. A value import of an index from here would be reached statically by that shared
// component and would undo the split, silently and with every gate green.

/**
 * One row of a catalogue, as a search sees it: no field here names a body.
 *
 * THE SPLIT BETWEEN `alias` AND `terms` IS SHOWN-VERSUS-MATCHED, and it is the one thing a builder
 * can get subtly wrong. `alias` is displayed and never matched — folding already handles diacritics,
 * so the IAU's flattened spelling earns its place on screen rather than in the token set. `terms` is
 * matched and never displayed, so a body can make a kind or a region typeable without putting it in
 * front of a reader twice.
 */
export interface SearchEntry {
  /** What the row shows, and the key the page looks its own record up by. Unique in a catalogue. */
  name: string;
  /** A second spelling shown beside the name, or null. Explains a match; never causes one. */
  alias: string | null;
  /** The line under the name, already formatted by whoever owns the card's formatters. */
  descriptor: string;
  /** Further phrases a query term may prefix — a kind, a region. Tokenised here, never shown. */
  terms: string[];
  /**
   * Prominence, largest first, or `null` where the catalogue publishes none.
   *
   * IT IS THE PRODUCT WHEREVER THE CAP BITES. A one- or two-letter query matches most of Mars's
   * 1,919 features, so which handful survives the slice is the entire answer a visitor sees, and
   * alphabetical order would answer every broad query with whatever starts with an A. A catalogue
   * short enough that the cap shows a real page of it — Earth's 203 countries — passes `null` and
   * gets name order, which is honest rather than a proxy invented to fill this field.
   */
  weight: number | null;
}

/** A query's answer: the ranked page of it, and how many there were before the cap. */
export interface SearchResults {
  /** Best first, no longer than the requested limit. */
  matches: SearchEntry[];
  /** Every entry that matched, so a caller can say "10 of 160" rather than implying 10. */
  total: number;
}

export interface CatalogueSearch {
  /** The best `limit` entries for this query. An empty or punctuation-only query matches nothing. */
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

/** The tokens of an entry's extra phrases. Split on everything, because a phrase here is a list as
 *  often as it is a word — the IAU publishes its kinds as a singular/plural pair ("Crater, craters")
 *  and both spellings have to be typeable. */
function termTokens(terms: readonly string[]): string[] {
  const tokens = new Set<string>();
  for (const term of terms) {
    for (const token of foldForSearch(term).split(/[^a-z0-9]+/)) if (token) tokens.add(token);
  }
  return [...tokens];
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
/** `terms` had to answer for at least one of them. */
const TIER_TERMS = 1;

/** The query IS the name, ignoring case, marks and punctuation. */
const LEAD_EXACT = 0;
/** The name begins with the query. */
const LEAD_LEADING = 1;
/** The query reached a later word, or `terms`. */
const LEAD_ELSEWHERE = 2;

interface Indexed {
  entry: SearchEntry;
  nameTokens: string[];
  everyToken: string[];
  /** The name with case, marks, punctuation AND spaces gone — what `Lead` is decided against. */
  flatName: string;
}

interface Match {
  indexed: Indexed;
  tier: number;
  lead: number;
}

function everyTermPrefixes(terms: string[], tokens: string[]): boolean {
  return terms.every((term) => tokens.some((token) => token.startsWith(term)));
}

/**
 * Rank two matches. Tier, then where in the name the query landed, then `weight`.
 *
 * WEIGHT DESCENDING IS THE TIE-BREAK BECAUSE THE CAP MAKES IT THE PRODUCT — the reasoning, and what
 * a catalogue with nothing to weigh does instead, is on `SearchEntry.weight`. `null` sorts last, and
 * name order settles what is left so the list never reshuffles itself under an identical query.
 */
function byRelevance(first: Match, second: Match): number {
  if (first.tier !== second.tier) return first.tier - second.tier;
  if (first.lead !== second.lead) return first.lead - second.lead;
  const firstWeight = first.indexed.entry.weight ?? Number.NEGATIVE_INFINITY;
  const secondWeight = second.indexed.entry.weight ?? Number.NEGATIVE_INFINITY;
  if (firstWeight !== secondWeight) return secondWeight - firstWeight;
  return first.indexed.entry.name.localeCompare(second.indexed.entry.name);
}

/**
 * Build a matcher over a catalogue.
 *
 * The tokens are built ONCE, here, rather than per query: folding and splitting every name on each
 * keystroke is the only part of this that is not trivially cheap, and a search box calls `search`
 * on every one. Matching itself is a linear scan — the catalogue is small enough that an inverted
 * index would be a structure to keep correct in exchange for nothing measurable.
 */
export function createCatalogueSearch(catalogue: readonly SearchEntry[]): CatalogueSearch {
  const indexed: Indexed[] = catalogue.map((entry) => {
    const names = nameTokens(entry.name);
    return {
      entry,
      nameTokens: names,
      everyToken: [...new Set([...names, ...termTokens(entry.terms)])],
      flatName: foldForSearch(entry.name).replace(/[^a-z0-9]+/g, ""),
    };
  });

  function search(query: string, limit: number): SearchResults {
    const terms = queryTerms(query);
    if (terms.length === 0) return { matches: [], total: 0 };
    const flatQuery = terms.join("");

    const found: Match[] = [];
    for (const row of indexed) {
      const onName = everyTermPrefixes(terms, row.nameTokens);
      if (!onName && !everyTermPrefixes(terms, row.everyToken)) continue;
      const lead = !onName
        ? LEAD_ELSEWHERE
        : row.flatName === flatQuery
          ? LEAD_EXACT
          : row.flatName.startsWith(flatQuery)
            ? LEAD_LEADING
            : LEAD_ELSEWHERE;
      found.push({ indexed: row, tier: onName ? TIER_NAME : TIER_TERMS, lead });
    }

    found.sort(byRelevance);
    return {
      matches: found.slice(0, Math.max(0, limit)).map((match) => match.indexed.entry),
      total: found.length,
    };
  }

  return { search };
}
