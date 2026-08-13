import { describe, it, expect } from "vitest";
import { readFileSync } from "node:fs";
import { boundsCentre, byInitial, formatPosition } from "./gazetteer";
import { featureIndex } from "./featureIndex";

const WEB_ROOT = new URL("../../", import.meta.url).pathname;
const LITE = readFileSync(`${WEB_ROOT}src/pages/mars/lite.astro`, "utf8");
const GALLERY = readFileSync(`${WEB_ROOT}src/pages/index.astro`, "utf8");

describe("a position reads the way a gazetteer writes one", () => {
  it("takes the hemisphere from the sign and drops it", () => {
    expect(formatPosition(-13.8819, 55.5817)).toBe("14° S, 56° E");
    expect(formatPosition(13.8819, -55.5817)).toBe("14° N, 56° W");
  });

  it("puts a point on the line in the positive hemisphere rather than printing nothing", () => {
    // The equator and the prime meridian have no hemisphere and something has to be written. `>= 0`
    // matches the sign convention the data uses; what matters is that it is decided rather than
    // falling out of whichever comparison was typed.
    expect(formatPosition(0, 0)).toBe("0° N, 0° E");
  });

  it("rounds rather than truncates, so a feature does not drift a degree towards the equator", () => {
    expect(formatPosition(-13.6, 55.6)).toBe("14° S, 56° E");
  });
});

describe("a bbox becomes the point the formatter wants", () => {
  it("averages the corners", () => {
    expect(boundsCentre([-75.6, -55.9, -66.4, -17.5])).toEqual({
      latitude: -36.7,
      longitude: -71,
    });
  });

  it("is what the gallery calls, so one page cannot drift from the other", () => {
    // THE WHOLE REASON THIS MODULE EXISTS. Both were local arrow functions in `index.astro`, correct
    // where they sat; a second listing would have copied them and the two pages would have started
    // disagreeing about how one planet is written down, with nothing going red.
    expect(GALLERY).toContain("boundsCentre(country.bbox)");
    expect(GALLERY).toContain("formatPosition(latitude, longitude)");
    expect(LITE).toContain("formatPosition(feature.latitude, feature.longitude)");
  });
});

describe("a sorted list becomes lettered sections", () => {
  it("keeps the caller's order and does not sort again", () => {
    // Takes the sorted list on purpose: sorting here would either repeat the caller's collation or
    // silently impose a different one than the page was reasoned about in.
    const groups = byInitial(["ash", "arc", "bee"], (word) => word[0]!);
    expect([...groups.keys()]).toEqual(["A", "B"]);
    expect(groups.get("A")).toEqual(["ash", "arc"]);
  });

  it("letters on what the caller passes, not on a field it picked", () => {
    // Earth letters on the country's name, Mars on `cleanName`, so Belén files under B on a page
    // whose visitor may only be able to type "Belen".
    const entries = [{ name: "Ébano", clean: "Ebano" }];
    expect([...byInitial(entries, (entry) => entry.clean[0]!).keys()]).toEqual(["E"]);
    expect([...byInitial(entries, (entry) => entry.name[0]!).keys()]).toEqual(["É"]);
  });

  it("partitions the real catalogue into A–Z with nothing left over", () => {
    // The page renders one section per key and nothing else, so a feature outside these buckets is
    // a feature that silently does not appear. Asserted over the shipped index rather than a
    // fixture, because what would put a row outside A–Z is an edition the IAU publishes, not a bug.
    //
    // NOTE WHAT THIS CANNOT SEE: it letters the catalogue itself, so it stays true no matter what
    // the PAGE passes. Mutating `lite.astro` to letter on the published name came back MISSED
    // against it — the guard below is the one that has to hold the page.
    const groups = byInitial(featureIndex, (feature) => feature.cleanName[0]!);
    expect([...groups.keys()].toSorted()).toEqual(
      "ABCDEFGHIJKLMNOPQRSTUVWXYZ".split(""),
    );
    const listed = [...groups.values()].reduce((total, bucket) => total + bucket.length, 0);
    expect(listed).toBe(featureIndex.length);
  });

  it("letters the page on cleanName, and the cost of not doing is measured rather than assumed", () => {
    // TWO ROWS, NOT THE 69 THE ALIAS IS FOR — the diacritic is mid-word in every other name, so
    // only Ōmura and Žulanka move. Lettering on the published name gives each its own section after
    // Z holding one feature, and puts two letters on the rail nobody would think to press.
    expect(LITE).toContain("byInitial(alphabetical, (feature) => feature.cleanName[0]!)");
    const published = [...byInitial(featureIndex, (feature) => feature.name[0]!).keys()];
    const clean = new Set(byInitial(featureIndex, (feature) => feature.cleanName[0]!).keys());
    expect(published.filter((letter) => !clean.has(letter)).toSorted()).toEqual(["Ō", "Ž"]);
  });
});

describe("the listing is findable with the browser's own find", () => {
  it("renders the diacritic-free name as text wherever it differs", () => {
    // Cmd/Ctrl+F is the search on this page, and it matches neither a `title` attribute nor
    // anything `display:none` — so the alias has to be in the document or "Belen" fails to find
    // Belén. 69 features are affected, and every one of them is a name a visitor might type.
    const aliased = featureIndex.filter((feature) => feature.cleanName !== feature.name);
    expect(aliased.length).toBeGreaterThan(0);
    expect(LITE).toContain("feature.cleanName !== feature.name");
    expect(LITE).toContain("<span class=\"gz-alias\">{feature.cleanName}</span>");
    // The parens are decoration and must stay in CSS: content inside `::before` is not text the
    // browser's find can match, which is exactly why the NAME is not drawn that way.
    expect(LITE).toMatch(/\.gz-alias::before\s*\{\s*content:/);
  });

  it("never hides a row behind a toggle the way the gallery's index is hidden", () => {
    // Earth's listing is a `:target` overlay, which is right over a card grid and wrong here: this
    // page IS the listing, and a closed one would answer "your device cannot draw Mars" with a
    // blank page. Cmd+F also cannot see text in a `visibility: hidden` panel.
    expect(LITE).not.toContain(":target");
    expect(LITE).not.toMatch(/visibility:\s*hidden/);
  });
});

describe("the row states what it links to", () => {
  it("links the name alone, not the whole row", () => {
    // A row-wide anchor gives every link on this page an accessible name ending in an etymology up
    // to 254 characters long, and makes the listing unselectable as text.
    expect(LITE).toContain('class="gz-name"');
    expect(LITE).not.toMatch(/<a[^>]*>\s*\{?\s*<p class="gz-head"/);
  });

  it("sends a reader to the publisher's own entry, in a new tab", () => {
    expect(LITE).toContain("href={feature.gazetteer}");
    expect(LITE).toContain('rel="noopener noreferrer"');
  });

  it("reads the card's own formatters rather than writing a second kind and size", () => {
    // A listing and a card describing the same feature differently is the drift this prevents:
    // both must call the descriptor and diameter rules that `detailPanel` already owns.
    expect(LITE).toContain("featureTypeLabel(feature.type)");
    expect(LITE).toContain("formatFeatureDiameter(feature.diameterKm)");
  });
});
