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
