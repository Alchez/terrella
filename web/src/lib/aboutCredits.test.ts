import { describe, expect, it } from "vitest";
import aboutPage from "../pages/about.astro?raw";
import { BODIES } from "./bodies";

/**
 * Every body the site ships has its own credits group on the About page.
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
 * Read off the SOURCE rather than a rendered page, because the subject is the data the page is
 * built from: a group present in `dataSources` but dropped by a template bug would be a different
 * defect, and one the build's own output diff would show.
 */
const GROUP_LABEL = /^\s*body: "([^"]+)",$/gm;
const SOURCE_NAME = /^\s*name: "([^"]+)",$/gm;

/** Each group label in page order, with the number of source cards that follow it. */
function creditGroups(): { label: string; sources: number }[] {
  const labels = [...aboutPage.matchAll(GROUP_LABEL)].map((match) => ({
    label: match[1],
    at: match.index,
  }));
  const names = [...aboutPage.matchAll(SOURCE_NAME)].map((match) => match.index);
  return labels.map((group, index) => {
    const end = labels[index + 1]?.at ?? aboutPage.length;
    return {
      label: group.label,
      sources: names.filter((at) => at > group.at && at < end).length,
    };
  });
}

describe("the About page credits every body the site ships", () => {
  it("parses the groups and their cards, so the rules below are not checking an empty list", () => {
    // Both halves proven, because each fails differently: no groups makes every membership check
    // below vacuous, and no cards makes the emptiness check vacuous while the labels still read.
    const groups = creditGroups();
    expect(groups.length, "no `body:` group parsed — the dataSources shape changed").toBeGreaterThan(
      0,
    );
    expect(
      groups.reduce((total, group) => total + group.sources, 0),
      "groups parsed but no source cards did — the `name:` shape changed",
    ).toBeGreaterThan(0);
  });

  it("gives every registered body a group of its own", () => {
    // Derived from the registry, which is the half a person cannot be trusted to remember: adding
    // a planet is a registry entry, and this is what makes crediting it part of adding it.
    const labels = creditGroups().map((group) => group.label.toLowerCase());
    for (const slug of Object.keys(BODIES)) {
      expect(labels, `${slug} ships a globe but the About page credits no source for it`).toContain(
        slug,
      );
    }
  });

  it("gives every group at least one source, so a heading cannot credit nothing", () => {
    // The failure this separates out: a body gains a heading and no cards. The check above would
    // pass — the label is there — while the page names a planet and says nothing about it.
    for (const { label, sources } of creditGroups()) {
      expect(sources, `the ${label} group has a heading and no data sources under it`).toBeGreaterThan(
        0,
      );
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
 * survives; removal does not.
 */
describe("the About page discloses that Mars is coloured by elevation", () => {
  const HEADING = /<h2 class="eyebrow">Mars colour<\/h2>/;

  /** The note block's own text, so a phrase elsewhere on the page cannot satisfy these. */
  function marsColourNote(): string {
    const start = aboutPage.search(HEADING);
    if (start < 0) return "";
    const end = aboutPage.indexOf("</section>", start);
    return end < 0 ? "" : aboutPage.slice(start, end);
  }

  it("extracts the note, so the assertions below are not reading an empty string", () => {
    expect(
      marsColourNote().length,
      "no `Mars colour` note block found — the disclosure was removed or its heading renamed",
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
