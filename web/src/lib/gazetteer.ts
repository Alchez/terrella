// The two things every gazetteer listing does, wherever it is rendered.
//
// BOTH BODIES PUBLISH ONE, AND THEY AGREE ON EVERYTHING EXCEPT WHAT A ROW IS. Earth's is an overlay
// over the gallery, 204 countries linking to their own pages; Mars's is a whole page, 1,919 named
// features linking to the IAU. What is common is smaller than either page and drifts silently: how
// a position reads, and how a list becomes lettered sections with a rail above them.
//
// IT IS HERE BECAUSE THE SECOND CALLER WAS ABOUT TO COPY IT. `index.astro` held both as local
// arrow functions, correct where they sat — which is exactly the shape this repo has been bitten by
// before. The trigger question is "change one copy, what goes red?", and for a hemisphere letter or
// a bucketing rule the answer was nothing at all: two listings would simply start disagreeing about
// how the same planet is written down.

/** A position as a gazetteer writes it: `"14° S, 56° E"`, whole degrees with a hemisphere letter.
 *
 *  ZERO IS NORTH AND EAST, which is a choice rather than a fact — a point exactly on the equator or
 *  the prime meridian has no hemisphere, and something has to be printed. `>= 0` puts it in the
 *  positive one, matching the sign convention the data itself uses. */
export function formatPosition(latitude: number, longitude: number): string {
  const northSouth = `${Math.round(Math.abs(latitude))}° ${latitude >= 0 ? "N" : "S"}`;
  const eastWest = `${Math.round(Math.abs(longitude))}° ${longitude >= 0 ? "E" : "W"}`;
  return `${northSouth}, ${eastWest}`;
}

/** The centre of a `[west, south, east, north]` box, for a caller that has an extent and not a
 *  point. Earth's manifest publishes bounds; Mars's index publishes the IAU's own adopted centre,
 *  which is why only one body needs this step. */
export function boundsCentre(bounds: readonly number[]): { latitude: number; longitude: number } {
  const [west, south, east, north] = bounds as [number, number, number, number];
  return { latitude: (south + north) / 2, longitude: (west + east) / 2 };
}

/**
 * A sorted list as lettered sections, in the order the letters appear.
 *
 * TAKES THE SORTED LIST AND DOES NOT SORT, so the caller's collation is the one that ships. Both
 * pages sort with `localeCompare` before calling; sorting again here would either repeat that or,
 * worse, quietly impose a different order than the one the caller reasoned about.
 *
 * `initial` IS SUPPLIED BY THE CALLER RATHER THAN TAKEN FROM A FIELD, because the two bodies letter
 * on different strings: Earth on the country's name, Mars on `cleanName`, so that Belén files under
 * B on a page whose visitor may only be able to type "Belen".
 */
export function byInitial<Entry>(
  sorted: readonly Entry[],
  initial: (entry: Entry) => string,
): Map<string, Entry[]> {
  const groups = new Map<string, Entry[]>();
  for (const entry of sorted) {
    const letter = initial(entry).toUpperCase();
    const bucket = groups.get(letter);
    if (bucket) bucket.push(entry);
    else groups.set(letter, [entry]);
  }
  return groups;
}
