import { describe, it, expect } from "vitest";
import { readFileSync } from "node:fs";
import {
  COUNTRY_PANEL_NOTE,
  FRAME_EDGE_PX,
  GAZETTEER_LINK_LABEL,
  HERO_LINK_LABEL,
  PANEL_BESIDE_MIN_WIDTH_PX,
  PANEL_CLEARANCE_PX,
  countryPanelContent,
  countrySearchEntry,
  featurePanelContent,
  featureSearchEntry,
  featureTypeLabel,
  formatFeatureDiameter,
  heroSrcset,
  variantWidth,
  type PanelContent,
} from "./detailPanel";
import { featureIndex, type NamedFeature } from "./featureIndex";
import { formatGroundDistance } from "./scaleRuler";
import type { Country } from "./manifest";

const WEB_ROOT = new URL("../../", import.meta.url).pathname;
const GLOBE = readFileSync(`${WEB_ROOT}src/components/Globe.astro`, "utf8");
const PANEL_SOURCE = readFileSync(new URL("./detailPanel.ts", import.meta.url).pathname, "utf8");

/** A rendered landscape country, with every field the builder reads populated. */
function country(overrides: Partial<Country> = {}): Country {
  return {
    slug: "chile",
    name: "Chile",
    continent: "South America",
    searchTerms: ["Republic of Chile", "Chile.", "CL", "CHL"],
    bbox: [-75.6, -55.9, -66.4, -17.5],
    aspect: 0.5,
    sizes: [640, 1920, 3840],
    native: 3840,
    rendered: true,
    hasBorder: true,
    borderSizes: [640, 1920],
    hasSpotlight: false,
    spotlightSizes: [],
    ...overrides,
  };
}

describe("srcset descriptors are widths, not long edges", () => {
  it("leaves a landscape variant at its key", () => {
    expect(variantWidth(1920, 1.5)).toBe(1920);
  });

  it("narrows a portrait variant to its real width", () => {
    // The trap this exists for: a portrait hero's key names its HEIGHT, so a descriptor taken from
    // the key alone overstates the width and the browser settles for a rung too small.
    expect(variantWidth(1920, 0.5)).toBe(960);
    expect(variantWidth(3840, 0.75)).toBe(2880);
  });

  it("names the webp variants for a hero and the png ones for a border", () => {
    const hero = heroSrcset("chile", [640, 1920], 0.5);
    expect(hero).toContain("chile-640.webp 320w");
    expect(hero).toContain("chile-1920.webp 960w");
    expect(hero).not.toContain("-border-");

    const border = heroSrcset("chile", [640], 0.5, true);
    expect(border).toContain("chile-border-640.png 320w");
    expect(border).not.toContain(".webp");
  });
});

describe("a country becomes card content", () => {
  it("puts the continent in the eyebrow and the render sentence in the note", () => {
    const content = countryPanelContent(country());
    expect(content.eyebrow).toBe("South America");
    expect(content.name).toBe("Chile");
    expect(content.note).toBe(COUNTRY_PANEL_NOTE);
    expect(content.link).toEqual({
      href: "/chile/",
      label: HERO_LINK_LABEL,
      external: false,
    });
  });

  it("empties the eyebrow rather than printing a missing continent", () => {
    expect(countryPanelContent(country({ continent: "" })).eyebrow).toBe("");
  });

  it("builds the figure from the smallest rung and describes it for a screen reader", () => {
    const { figure } = countryPanelContent(country());
    expect(figure).not.toBeNull();
    expect(figure!.aspect).toBe(0.5);
    expect(figure!.src).toContain("chile-640.webp");
    expect(figure!.srcset).toContain("chile-3840.webp 1920w");
    expect(figure!.alt).toBe("Ray-traced relief map of Chile");
  });

  it("drops the border when the country has none", () => {
    expect(countryPanelContent(country({ hasBorder: false })).figure!.border).toBeNull();
    expect(countryPanelContent(country({ borderSizes: [] })).figure!.border).toBeNull();
  });

  it("yields NO figure for an unrendered country rather than a broken image", () => {
    // The defect this pins: the old panel indexed `sizes[0]` unconditionally and asked for
    // `chile-undefined.webp`, which 404s behind a spinner. Unreachable on Earth today because only
    // in-scope countries are interactive — and the reason the figure has to be nullable at all is
    // the body that has no renders for ANY of its places.
    const content = countryPanelContent(country({ sizes: [], native: null, rendered: false }));
    expect(content.figure).toBeNull();
    expect(JSON.stringify(content)).not.toContain("undefined.webp");
  });
});

describe("a country becomes a search row", () => {
  it("writes one summary for the eyebrow and the search row", () => {
    // The duplicate this exists to stop is the one the box already shipped once on Mars: two
    // readers composing the same sentence, correct on the day and free to drift after it.
    //
    // THE COUNTRY WITH NO CONTINENT IS WHAT MAKES THIS BITE, and the first version of this test had
    // a real one and asserted nothing: `countrySummary(c)` and `c.continent` agree on every input a
    // populated manifest can produce, so the mutation that inlines the field passed. They diverge in
    // exactly one place — the unchecked cast in `manifest.ts`, where a missing field arrives as
    // `undefined` through a type saying `string` and reaches the card as the word "undefined".
    const chile = country();
    expect(countrySearchEntry(chile).descriptor).toBe(countryPanelContent(chile).eyebrow);
    const unplaced = country({ continent: undefined as unknown as string });
    expect(countrySearchEntry(unplaced).descriptor).toBe("");
    expect(countryPanelContent(unplaced).eyebrow).toBe("");
  });

  it("shows no second spelling, because the alternatives are codes rather than names", () => {
    // `alias` is SHOWN. Natural Earth's alternatives are ISO codes and formal titles, which belong
    // in `terms` — matched without being read back at someone beside a name they already repeat.
    expect(countrySearchEntry(country()).alias).toBeNull();
  });

  it("makes the continent both the descriptor and a term, which no other field is", () => {
    const entry = countrySearchEntry(country({ continent: "Africa", searchTerms: ["KE"] }));
    expect(entry.descriptor).toBe("Africa");
    expect(entry.terms).toContain("Africa");
    expect(entry.terms).toContain("KE");
  });

  it("ranks by name rather than inventing a prominence Earth does not publish", () => {
    // Mars ranks by diameter because a one-letter query slices 1,919 features down to 8. Earth's
    // 203 against that same cap is a real page of a short list, so `null` takes name order — and a
    // proxy invented to fill this field (area, population) would be a claim the manifest never made.
    expect(countrySearchEntry(country()).weight).toBeNull();
  });

  it("carries every manifest term through, so a column added upstream is typeable at once", () => {
    const terms = ["Republic of Kenya", "KE", "KEN"];
    const entry = countrySearchEntry(country({ continent: "Africa", searchTerms: terms }));
    expect(entry.terms).toEqual([...terms, "Africa"]);
  });
});

describe("the panel seam the module cannot check itself", () => {
  function panelMarkup(): string {
    const start = GLOBE.indexOf('<aside id="detail-panel"');
    expect(start, "the detail panel is gone from the markup").toBeGreaterThan(-1);
    return GLOBE.slice(start, GLOBE.indexOf("</aside>", start));
  }

  it("takes content rather than a country", () => {
    // The whole point of the refactor. `openPanel(country: Country)` is what a second body cannot
    // call, so the signature is the thing worth pinning rather than any of the fields.
    expect(GLOBE).toContain("function openPanel(content: PanelContent)");
    expect(GLOBE).toContain("openPanel(countryPanelContent(country))");
  });

  it("opens only for a body whose places have renders", () => {
    // THE GATE, PINNED AT ITS SITE. `globeSubsystems.test.ts` asserts that `subsystems.heroes`
    // appears SOMEWHERE in the globe, which is an existence scan — and it stopped being able to
    // catch a deleted gate here the moment a second reader arrived, because `chip-answers-taps`
    // reads the same flag and keeps the string present. Proved by mutation: removing this `if`
    // left that scan green.
    expect(GLOBE).toContain("if (subsystems.heroes) openPanel(countryPanelContent(country));");
  });

  it("leaves every slot in the markup empty, the note and the link's wording included", () => {
    // The note used to be a sentence in the markup claiming the card showed a ray-traced render,
    // and the link used to promise one — "Open full-size render →" — over a body that has none.
    // A static string cannot be right on one body and wrong on another, so it must arrive written.
    expect(panelMarkup()).toContain('<p class="dp-note"></p>');
    expect(GLOBE).toContain('panel.querySelector(".dp-note")!.textContent = content.note;');
    expect(panelMarkup()).toContain('<a class="dp-link" href="/"></a>');
    expect(GLOBE).toContain("linkEl.textContent = content.link.label;");
  });

  it("honours both values of external, not just the one its own body asks for", () => {
    // `external` is a per-card field over a REUSED element, so writing only the true case leaves a
    // Mars card's `target` on the Earth card after it. That is unreachable today for a reason that
    // has nothing to do with the link — `subsystems.vectorProduct` is a single value, so a document
    // wires one builder — and this keeps the accident from becoming the thing holding it up.
    expect(GLOBE).toContain('linkEl.removeAttribute("target");');
    expect(GLOBE).toContain('linkEl.removeAttribute("rel");');
  });

  it("retires every spelling that named the panel after a hero", () => {
    // A half-finished rename is the failure mode here: the CSS block, the markup and the
    // querySelectors are three places, and a survivor in any one of them styles or selects nothing.
    for (const retired of ["hero-panel", "hero-close", "hp-"]) {
      expect(GLOBE, `${retired} survived the rename`).not.toContain(retired);
    }
  });

  it("selects only classes the markup actually carries", () => {
    // Catches the other half of a half-finished rename — a querySelector updated to a class the
    // markup never gained resolves to null and throws on the non-null assertion, but only when a
    // card is opened, which no test opens.
    const markup = panelMarkup();
    const selected = [...GLOBE.matchAll(/querySelector\("\.(dp-[a-z]+)"\)/g)].map((m) => m[1]);
    expect(selected.length).toBeGreaterThan(3);
    for (const cls of new Set(selected)) {
      expect(markup, `.${cls} is selected but not in the markup`).toContain(`class="${cls}"`);
    }
  });
});

describe("the content contract stays body-neutral", () => {
  it("names no country field", () => {
    // `PanelContent` exists so a second body can fill the card. A `slug`, a `continent` or a
    // `borderSizes` creeping back in would re-couple it to Earth's manifest without anything
    // failing, because Earth's builder would go on supplying them.
    const content: PanelContent = countryPanelContent(country());
    expect(Object.keys(content).toSorted()).toEqual(["eyebrow", "figure", "link", "name", "note"]);
  });

  it("is filled the same way by both bodies, or the card has two shapes", () => {
    // The contract only means something if the second builder honours it. Compared as key SETS
    // rather than asserted twice, so a field added to one builder and not the other fails here
    // instead of being caught by whichever test was updated.
    expect(Object.keys(featurePanelContent(feature())).toSorted()).toEqual(
      Object.keys(countryPanelContent(country())).toSorted(),
    );
  });
});

/** One gazetteer row, with every field the builder reads populated. */
function feature(overrides: Partial<NamedFeature> = {}): NamedFeature {
  return {
    name: "Gale",
    cleanName: "Gale",
    type: "Crater, craters",
    origin: "Walter Frederick; Australian astronomer (1865-1945).",
    gazetteer: "https://planetarynames.wr.usgs.gov/Feature/2071",
    diameterKm: 154.156,
    longitude: 137.85,
    latitude: -5.37,
    ...overrides,
  };
}

describe("the IAU descriptor becomes a label", () => {
  it("keeps the singular and drops the plural", () => {
    expect(featureTypeLabel("Crater, craters")).toBe("Crater");
    expect(featureTypeLabel("Vallis, valles")).toBe("Vallis");
  });

  it("is total over the real catalogue, not just over the tidy types", () => {
    // The rule is "split at the comma", which is only safe because every type in the published
    // gazetteer carries one — including the two that pluralise with a macron (`Rupes, rupēs`) and
    // the one whose singular and plural differ by nothing else. A future edition adding a
    // comma-less descriptor would silently pass the whole type through as a label.
    const types = new Set(featureIndex.map((row) => row.type));
    expect(types.size).toBeGreaterThan(20);
    for (const type of types) {
      const label = featureTypeLabel(type);
      expect(label, `${type} kept its plural`).not.toContain(",");
      expect(label.length, `${type} produced an empty label`).toBeGreaterThan(0);
      expect(type.startsWith(label), `${label} is not the head of ${type}`).toBe(true);
    }
  });
});

describe("a published diameter is quoted, not measured", () => {
  it("reads whole kilometres with a separator once it is large", () => {
    expect(formatFeatureDiameter(154.156)).toBe("154 km");
    expect(formatFeatureDiameter(1471.557)).toBe("1,472 km");
    expect(formatFeatureDiameter(5855.873)).toBe("5,856 km");
  });

  it("keeps a decimal on a small crater and drops to metres below a kilometre", () => {
    expect(formatFeatureDiameter(4.63)).toBe("4.6 km");
    expect(formatFeatureDiameter(0.23)).toBe("230 m");
  });

  it("disagrees with the scale ruler, which is the point of it existing", () => {
    // THE ASYMMETRY PINNED RATHER THAN COMMENTED. `formatGroundDistance` holds two significant
    // figures because its subject is a scale sampled off a sphere and re-sampled every frame.
    // Neither reason survives here, and collapsing the two — the obvious tidy-up, since both turn
    // a length into a label — would round the IAU's 1,471.6 km to "1,500 km" on the card.
    expect(formatGroundDistance(1471.557 * 1000)).toBe("1,500 km");
    expect(formatFeatureDiameter(1471.557)).not.toBe(formatGroundDistance(1471.557 * 1000));
  });
});

describe("a gazetteer row becomes a card", () => {
  it("names the feature, its kind and how big it is", () => {
    const content = featurePanelContent(feature());
    expect(content.name).toBe("Gale");
    expect(content.eyebrow).toBe("Crater · 154 km");
    expect(content.note).toBe("Walter Frederick; Australian astronomer (1865-1945).");
  });

  it("falls back to the kind alone where the gazetteer publishes no size", () => {
    // Two features reach this branch, and they are the same two `candidateFrom` refuses to size.
    // A card reading "Chaos · 0 km" would be the catalogue disagreeing with itself about which
    // features have a diameter at all.
    expect(featurePanelContent(feature({ diameterKm: null })).eyebrow).toBe("Crater");
  });

  it("carries no picture, because this body renders no heroes", () => {
    expect(featurePanelContent(feature()).figure).toBeNull();
  });

  it("sends a reader to the IAU entry the note is quoting, in a new tab", () => {
    // The card has no page of its own to open, so the only onward destination is the publisher's.
    // `external` decides the new tab, and leaving the globe tears down a WebGL context that costs
    // seconds and gigabytes to rebuild — see `PanelLink`.
    expect(featurePanelContent(feature()).link).toEqual({
      href: "https://planetarynames.wr.usgs.gov/Feature/2071",
      label: GAZETTEER_LINK_LABEL,
      external: true,
    });
  });

  it("labels the two bodies' links differently, or one card lies about where it goes", () => {
    // The defect this replaced: "Open full-size render →" was hardcoded in the markup, so a Mars
    // card promised a render that does not exist and pointed at a catalogue instead. Equal labels
    // here would mean the wording drifted back into something one body has to be wrong about.
    expect(featurePanelContent(feature()).link?.label).not.toBe(
      countryPanelContent(country()).link?.label,
    );
  });

  it("fills every slot for every feature in the catalogue", () => {
    // The card is opened by a tap on any of them and by a search for any of them, so a row that
    // produces a blank eyebrow or an empty note is a card that looks broken for that one feature
    // and no other. Cheaper to assert over all of them than to argue about which could be empty.
    for (const row of featureIndex) {
      const content = featurePanelContent(row);
      expect(content.name.length, `${row.name} lost its name`).toBeGreaterThan(0);
      expect(content.note.length, `${row.name} has no origin to show`).toBeGreaterThan(0);
      expect(content.eyebrow.length, `${row.name} has no eyebrow`).toBeGreaterThan(0);
      expect(content.link?.href, `${row.name} has nowhere to send a reader`).toMatch(
        /^https:\/\/planetarynames\.wr\.usgs\.gov\/Feature\/\d+$/,
      );
    }
  });
});

describe("the camera and the card agree about how much room the card takes", () => {
  it("gives Earth's padding and Mars's offset one source", () => {
    // Two APIs spending one number: `fitBounds` takes padding on the card's side, `flyTo` has no
    // padding at all and takes half the clearance as a leftward shift. Written as literals, a
    // change to the card's width would correct one framing and leave the other pushing its subject
    // under the panel — visible only as "the fly-to feels off" on one body.
    expect(GLOBE).toContain("right: FRAME_EDGE_PX + PANEL_CLEARANCE_PX,");
    expect(GLOBE).toContain("[-PANEL_CLEARANCE_PX / 2, 0] : [0, 0]");
    expect(GLOBE).not.toMatch(/padding: wide[\s\S]{0,120}right: \d/);
  });

  it("leaves the clearance inside a phone's screen, or the offset flies the subject away", () => {
    // The offset is applied only above the breakpoint. If half the clearance ever exceeded the
    // narrowest viewport that takes it, the framed feature would land off-screen — the failure is
    // silent because the camera still reports arriving exactly where it was asked to.
    expect(PANEL_CLEARANCE_PX / 2).toBeLessThan(PANEL_BESIDE_MIN_WIDTH_PX / 2);
    expect(FRAME_EDGE_PX).toBeGreaterThan(0);
  });
});

describe("the builders name Mars's rows without fetching them", () => {
  it("keeps the catalogue off the chunk both bodies share", () => {
    // MOVED HERE FROM `catalogueSearch.test.ts`, WITH ITS SUBJECT. `Globe.astro` splits
    // `featureIndex` onto its own chunk so Earth never downloads 324 KB of Martian place names, and
    // both bodies mount that one component — so a VALUE import in any module the component reaches
    // statically undoes the split, silently and with every other gate green. This module is that
    // module now: it holds the card's builder and the search row's, and both take a `NamedFeature`.
    // Present-then-absent rather than absent alone, because "does not appear" is true of any string
    // that was merely renamed.
    expect(PANEL_SOURCE).toContain('import type { NamedFeature } from "./featureIndex"');
    expect(PANEL_SOURCE).not.toMatch(/^import\s+(?!type\b)[^;]*from "\.\/featureIndex"/m);
  });

  it("writes one summary for the eyebrow and the search row, rather than two that agree today", () => {
    // The row's second line and the card's eyebrow are the same sentence about the same feature,
    // moments apart. They WERE two expressions — the box composed its own from this module's two
    // formatters — which reads correctly right up to the day one side gains a unit or drops the
    // separator. Asserted as equality against the real catalogue, not against a literal.
    const sized = featureIndex.find((row) => row.diameterKm !== null)!;
    const unsized = featureIndex.find((row) => row.diameterKm === null);
    for (const row of [sized, unsized].filter(Boolean) as NamedFeature[]) {
      expect(featureSearchEntry(row).descriptor).toBe(featurePanelContent(row).eyebrow);
    }
    expect(featureSearchEntry(sized).descriptor).toContain(formatFeatureDiameter(sized.diameterKm!));
  });

  it("hands the matcher the RAW gazetteer type, or half of every kind stops being typeable", () => {
    // "Crater, craters" is a singular/plural pair and the matcher splits it, so both spellings
    // answer. `featureTypeLabel` throws the plural away — correct for a card, wrong here, and the
    // damage is a query that returns nothing while every other query keeps working.
    const paired = featureIndex.find((row) => row.type.includes(","))!;
    expect(featureSearchEntry(paired).terms).toEqual([paired.type]);
    expect(featureSearchEntry(paired).terms[0]).not.toBe(featureTypeLabel(paired.type));
  });

  it("shows the flattened spelling only where it differs, and never matches on it", () => {
    // `alias` is display-only by contract: the fold already reaches diacritics, so putting this in
    // the token set would buy nothing and cost a second spelling in every row.
    const differs = featureIndex.find((row) => row.cleanName !== row.name)!;
    const same = featureIndex.find((row) => row.cleanName === row.name)!;
    expect(featureSearchEntry(differs).alias).toBe(differs.cleanName);
    expect(featureSearchEntry(same).alias).toBeNull();
  });
});
