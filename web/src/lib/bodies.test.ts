// The descriptor's Earth-only flags, and the two things that can actually be checked about them
// here.
//
// A boolean in a registry is the cheapest thing in the codebase to get wrong: it type-checks at any
// value, every gate stays green, and the only symptom is a subsystem that quietly never runs — or
// one that runs against nothing.
//
// WHAT IS DELIBERATELY NOT IN THIS FILE, so the gaps read as decisions:
//   * `rendersPolarCaps` is checked against `pipeline/bodies.py` instead, by
//     tests/test_bodies.py — the pipeline is what decides it, and this side only has to agree.
//   * `hasBorders` has no coherence partner at all. The overlay is a standalone Natural Earth
//     GeoJSON from BORDERS_BASE, derived from no pyramid and no cap, so there is nothing for a rule
//     to relate it to. Its truth — that Mars has no nations — is not a thing code can check.
//   * `rendersPolarCaps` implies a relief pyramid, and that rule is NOT asserted, because both
//     bodies publish relief so no registry state could falsify it. An unfalsifiable guard is the
//     species scripts/sabotage.py exists to hunt; the reasoning lives in the field's docstring
//     until a body arrives that could break it.
//   * `rendersPolarCaps` is also NOT in EARTH_ONLY_FLAGS below, for the same reason arriving from
//     the other direction: the cap is a Web Mercator repair rather than an ice layer, so it is what
//     every body wants and Mars's False was only ever "its ramps are unratified". Ratified, both
//     bodies answer true and the flag stops being Earth-only — the list holds the flags that still
//     divide the registry, and is worth nothing the moment it holds one that cannot.
//
// `bodies.browser.test.ts` covers what needs a renderer: accent tokens, `data-body`, and the
// slug-is-a-route binding. Nothing here needs a DOM.

import { describe, expect, it } from "vitest";
import { BODIES, type BodySlug } from "./bodies";
import { PUBLISHED } from "./tileAddress";

const SLUGS = Object.keys(BODIES) as BodySlug[];
const EARTH_ONLY_FLAGS = ["hasBorders", "hasHeroes"] as const;

describe("what a body declares it ships", () => {
  it("holds both answers to every flag, so none of them is a constant in disguise", () => {
    // The failure this catches is a third planet added by copying Earth's row — every flag true,
    // every gate green, and three subsystems switched on for a body that has none of them. It is
    // also what stops the rule below being satisfiable by a record where nothing ever differs.
    expect(SLUGS.length).toBeGreaterThan(1);
    for (const flag of EARTH_ONLY_FLAGS) {
      const answers = new Set(SLUGS.map((slug) => BODIES[slug][flag]));
      expect(answers, `${flag} is the same on every body`).toEqual(new Set([true, false]));
    }
  });

  it("names every body distinctly, which is all a label can be checked for here", () => {
    // DELIBERATELY WEAKER THAN THE FLAGS ABOVE, and the field's docstring says why: capitalising
    // the slug answers correctly for both bodies that exist, so there is no derivation this could
    // catch being wrong. What it catches is the copy-pasted row — two planets wearing one name in
    // a control whose entire job is to tell them apart — and the empty string, which type-checks.
    const labels = SLUGS.map((slug) => BODIES[slug].label);
    for (const label of labels) expect(label.trim()).not.toBe("");
    expect(new Set(labels).size, "two bodies answer to the same name").toBe(SLUGS.length);
  });

  it("gives every body two spellings of what its catalogue is of, and never the same one twice", () => {
    // The failure is silent and reads as a typo nobody wrote: singular and plural are used in two
    // different sentences — "Search countries" and "No country matches that." — so a row that
    // copied one into both produces "No countries matches that." on a live rail, and only on the
    // query that finds nothing. The distinctness across bodies is the copy-pasted-row check the
    // label above makes, for the same reason: a second planet inheriting the first one's noun.
    for (const slug of SLUGS) {
      const { singular, plural } = BODIES[slug].catalogue;
      expect(singular.trim(), `${slug} has no singular noun`).not.toBe("");
      expect(plural.trim(), `${slug} has no plural noun`).not.toBe("");
      expect(singular, `${slug} uses one spelling for both sentences`).not.toBe(plural);
    }
    const plurals = SLUGS.map((slug) => BODIES[slug].catalogue.plural);
    expect(new Set(plurals).size, "two bodies search for the same kind of thing").toBe(SLUGS.length);
  });

  it("gives heroes only to a body that publishes a countries pyramid", () => {
    // On the globe a hero panel opens exactly one way: `map.on("click")` resolves the point through
    // `countryAt()` against the countries MVT, looks the admin name up in the manifest, and calls
    // `openPanel`. No pyramid, no hit-test, no panel — so heroes without countries declares a
    // subsystem with no route into it, which stays true forever with nothing reading it.
    for (const slug of SLUGS) {
      if (!BODIES[slug].hasHeroes) continue;
      expect(PUBLISHED[slug].vector, `${slug} has heroes but no way to open one`).not.toBeNull();
    }
  });
});
