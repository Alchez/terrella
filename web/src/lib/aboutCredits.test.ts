import { describe, expect, it } from "vitest";
import { ABOUT } from "./aboutContent";
import { BODIES } from "./bodies";

/**
 * Every body the site ships has its own credits on the About page.
 *
 * WHY THIS EXISTS: `/mars/` shipped a working globe while the About page still credited eight Earth
 * datasets and nothing else. Nothing failed, and nothing could have — the credits were one flat
 * list with no notion of which planet a source belonged to, so a second planet was not missing from
 * it so much as unrepresentable in it. **No obligation was breached**, since the Mars source is
 * published by USGS rather than under a notice licence, and that is exactly what made it silent:
 * `test_attributions.py` deliberately asserts licence-REQUIRED strings only, so a courtesy credit
 * that never appears is invisible to the one check pointed at this page.
 *
 * So the rule this file adds is not about licences at all. It is that the page's account of how the
 * site is made stays as wide as the site — a body with a route and a pyramid and no credits is the
 * page telling a reader something untrue by omission.
 *
 * READ OFF `aboutContent.ts` RATHER THAN THE PAGE'S SOURCE, which it did until that module existed.
 * Scraping `about.astro?raw` with two regexes was the best available reading of content that lived
 * inside a template; now the content is data, the same rules are checked against the data. A group
 * present here but dropped by a template bug would be a different defect, and one the build's own
 * output diff would show.
 */
describe("the About page credits every body the site ships", () => {
  it("has content to check, so the rules below are not passing over an empty record", () => {
    // Both halves proven, because each fails differently: no bodies makes every membership check
    // below vacuous, and no sources makes the emptiness check vacuous while the keys still read.
    const slugs = Object.keys(ABOUT);
    expect(slugs.length, "ABOUT declares no bodies at all").toBeGreaterThan(0);
    expect(
      slugs.reduce((total, slug) => total + ABOUT[slug as keyof typeof ABOUT].sources.length, 0),
      "bodies are declared but not one of them carries a source",
    ).toBeGreaterThan(0);
  });

  it("gives every registered body an entry of its own", () => {
    // Derived from the registry, which is the half a person cannot be trusted to remember: adding
    // a planet is a registry entry, and this is what makes crediting it part of adding it. The
    // Record type makes this a compile error too — this is the runtime half, for a body whose
    // entry exists but was filled in from nothing.
    for (const slug of Object.keys(BODIES)) {
      expect(ABOUT, `${slug} ships a globe but the About page has no entry for it`).toHaveProperty(
        slug,
      );
    }
  });

  it("gives every body at least one source, so an entry cannot credit nothing", () => {
    // The failure this separates out: a body gains an entry and no sources. The check above would
    // pass — the key is there — while the page names a planet and says nothing about it.
    for (const [slug, body] of Object.entries(ABOUT)) {
      expect(
        body.sources.length,
        `the ${slug} entry exists but declares no data sources`,
      ).toBeGreaterThan(0);
    }
  });

  it("gives every source a name, a role, a licence and a credit", () => {
    // Every field is load-bearing on the rendered card, and an empty string renders as a blank line
    // rather than as an error. The licence in particular: a card with no badge reads as a dataset
    // with no terms, which is the opposite of what an unlabelled one usually means.
    for (const [slug, body] of Object.entries(ABOUT)) {
      for (const source of body.sources) {
        for (const field of ["name", "href", "role", "license", "attribution"] as const) {
          expect(source[field]?.trim(), `${slug}: a source has an empty ${field}`).toBeTruthy();
        }
      }
    }
  });
});

/**
 * Mars's colours are a cartographic convention, and the page has to say so.
 *
 * WHY A GUARD FOR A PARAGRAPH: this is the only claim on the site that a reader could take as a
 * photograph and be wrong. Earth's ramp is a stylisation too, but nobody mistakes teal bathymetry
 * for a satellite image; a rust-coloured Mars under raking light is exactly what Mars looks like in
 * every published picture, so the resemblance does the misleading on its own. Measured before it
 * was written: across the elevations holding two thirds of the surface, real colour moves 7.1 luma
 * against a within-place scatter of 17.9, and Syrtis Major sits 42 luma off the mean for its own
 * elevation — further than the whole trend spans. The ramp rises with height because height should
 * be readable, not because Mars does.
 *
 * The failure mode is silent deletion during an unrelated edit — a paragraph carries no test of its
 * own and reads as decoration. So this asserts the CLAIMS rather than the sentences: a heading, a
 * named albedo feature the map does not show, and the elevation-not-appearance statement. Rewording
 * survives; removal does not. That distinction is why the note was safe to shorten.
 */
describe("the About page discloses that Mars is coloured by elevation", () => {
  const HEADING = "Mars colour";

  /** The note's own text, so a phrase elsewhere on the page cannot satisfy these. */
  function marsColourNote(): string {
    const note = ABOUT.mars.notes.find((entry) => entry.heading === HEADING);
    return note ? note.paragraphs.join(" ") : "";
  }

  it("finds the note, so the assertions below are not reading an empty string", () => {
    expect(
      marsColourNote().length,
      `no "${HEADING}" note found — the disclosure was removed or its heading renamed`,
    ).toBeGreaterThan(200);
  });

  it("names a real albedo feature the map does not reproduce", () => {
    // The concrete half. Saying "not fully accurate" commits to nothing a reader can check; naming
    // Syrtis Major tells them precisely what is absent and lets them go and look.
    const note = marsColourNote();
    const named = ["Syrtis Major", "Acidalia"].filter((feature) => note.includes(feature));
    expect(
      named.length,
      "the note no longer names a dark marking the ramp cannot show, so it claims a limitation " +
        "without saying what is missing",
    ).toBeGreaterThan(0);
  });

  it("states that the colouring follows elevation rather than appearance", () => {
    const note = marsColourNote().toLowerCase();
    expect(note, "the note does not mention elevation").toContain("elevation");
    expect(
      /dust/.test(note),
      "the note no longer says what really colours Mars, so the disclosure has no cause behind it",
    ).toBe(true);
  });
});

/**
 * The legend states a correspondence between a colour and a height, so it has to have both.
 *
 * A body may legitimately have none — `legend` is nullable on the reasoning `bodies.ts` gives for
 * `atmosphere`, and a body drawn from something other than a hypsometric ramp would say so there.
 * What is not legitimate is a ramp with no marks, or marks with no ramp: either half alone renders
 * as a decoration that looks like a key.
 */
describe("a body's legend is complete or absent, never half", () => {
  it("gives every declared legend a gradient and at least two marks", () => {
    for (const [slug, body] of Object.entries(ABOUT)) {
      if (!body.legend) continue;
      expect(body.legend.gradient, `${slug}: legend has no gradient`).toContain("linear-gradient");
      expect(
        body.legend.marks.length,
        `${slug}: a ramp needs at least a low and a high mark to mean anything`,
      ).toBeGreaterThanOrEqual(2);
    }
  });

  it("declares a legend for at least one body, so the rule above is not vacuous", () => {
    const withLegend = Object.values(ABOUT).filter((body) => body.legend !== null);
    expect(withLegend.length, "no body declares a legend at all").toBeGreaterThan(0);
  });
});
