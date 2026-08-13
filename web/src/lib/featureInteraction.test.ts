import { readFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

/**
 * Mars's pointer wiring, read out of the component because nothing can import it.
 *
 * A SOURCE SCAN IS THE WEAKEST GUARD AND IT IS FORCED HERE, the same trade paintedLayers.test.ts
 * makes: the wiring lives in a page's client script, and a unit test cannot drive a real globe with
 * real archives on CI. What it buys is the class of failure that actually happens — a listener
 * quietly dropped in an edit, which leaves a globe that looks perfect and answers nothing.
 *
 * Every assertion below is about a behaviour with NO other witness. The layer specs, the pick rule
 * and the state targets are all unit-tested against the functions that build them; what is left is
 * whether the page calls them, and when.
 */

const LIB_DIR = path.dirname(fileURLToPath(import.meta.url));
const GLOBE = readFileSync(path.resolve(LIB_DIR, "../components/Globe.astro"), "utf8");
/** The globe's GLOBAL rules. The page writes a body class that only this file can act on, so the
 *  two spellings have to be compared across the seam — see the class guard below. */
const GLOBE_CSS = readFileSync(path.resolve(LIB_DIR, "../styles/globe.css"), "utf8");

/** The body of `wireFeatureInteraction`, so an assertion cannot be satisfied by a line that happens
 *  to sit in Earth's half of the file. Sliced to the next top-level `function ` at the same indent,
 *  which is how the neighbouring scans in this repo bound a function body. */
function wiringBody(): string {
  const start = GLOBE.indexOf("function wireFeatureInteraction()");
  expect(start, "wireFeatureInteraction is gone — Mars answers nothing").toBeGreaterThan(-1);
  const rest = GLOBE.slice(start + 1);
  const end = rest.indexOf("\n  function ");
  return rest.slice(0, end === -1 ? undefined : end);
}

/** The block that BUILDS the search control, which is deliberately NOT inside the wiring that arms
 *  it — the comment there carries the measurement. Bounded the same way as `wiringBody`. */
function searchBlock(): string {
  const start = GLOBE.indexOf("let matcher: CatalogueSearch | null = null;");
  expect(start, "the search control is gone — the rail has no field").toBeGreaterThan(-1);
  const rest = GLOBE.slice(start);
  const end = rest.indexOf("\n  function ");
  return rest.slice(0, end === -1 ? undefined : end);
}

/** The body of `addFeatureOverlay`, bounded the same way. */
function overlayBody(): string {
  const start = GLOBE.indexOf("function addFeatureOverlay()");
  expect(start, "addFeatureOverlay is gone — Mars has no vector layers at all").toBeGreaterThan(-1);
  const rest = GLOBE.slice(start + 1);
  const end = rest.indexOf("\n  /**");
  return rest.slice(0, end === -1 ? undefined : end);
}

describe("the page adds every layer the overlay builds", () => {
  it("adds the hit surface for features that exist only as lines", () => {
    // A layer that is built but never added is invisible to every other guard here: the spec is
    // still in the source for the ledger scan to find, and the module's own tests still pass
    // because they call the factory directly. Only the page can say it was mounted.
    expect(overlayBody()).toContain("featureLinearHitLayer()");
  });

  it("adds the hover linework, or the pick lights nothing", () => {
    expect(overlayBody()).toContain("featureHighlightLayers()");
  });
});

describe("the page actually wires Mars's pointer", () => {
  it("finds the function at all, or every assertion below is vacuous", () => {
    expect(wiringBody().length).toBeGreaterThan(400);
  });

  it("is called only where the body publishes features", () => {
    // Earth must not pay for it, and more importantly must not have two trackers bound to one
    // mousemove — the country resolver is already there and answers for that body.
    expect(GLOBE).toMatch(/vectorProduct === "features"\) \{\s*\n\s*addFeatureOverlay\(\);/);
    expect(GLOBE).toContain("wireFeatureInteraction();");
  });

  it("re-resolves when the camera moves, which matters more here than on Earth", () => {
    // A parked pointer over a moving globe goes stale on any body. Here it goes stale TWICE over,
    // because the pick depends on the scale as well as the position: the same point under the same
    // pointer answers with a different feature after a zoom, with no mousemove to prompt it.
    expect(wiringBody()).toContain('map.on("moveend", () => featureTracker.viewChanged());');
  });

  it("answers a tap, so the body is not mute on a phone", () => {
    // A tap is the only pointer event a phone sends. Routed into the same tracker on purpose: the
    // alternative is a second resolution path that drifts from the first.
    expect(wiringBody()).toContain("featureTracker.pointerMoved(event.point);");
    expect(wiringBody()).toContain("goToFeature(featureAt(event.point));");
  });

  it("resolves the click's own point instead of asking the tracker what it holds", () => {
    // MEASURED ON THE SHIPPED PAGE, where the first version of this handler read
    // `featureTracker.current()` and clicks intermittently did nothing at all. The tracker QUEUES
    // its resolve for the next frame, so `current()` answers for the previous one — and a tap has
    // no previous one, because touch sends no hover and MapLibre synthesises the whole sequence in
    // a single tick. The first tap on a phone did nothing and the second worked.
    //
    // NOTHING ELSE CAN SEE THIS. Every other assertion here passes either way: the listener is
    // bound, the tracker is fed, the fly and the card are wired. Only the ORDER of a queue and a
    // read separates a globe that answers a tap from one that answers the second tap.
    expect(wiringBody()).not.toContain("goToFeature(featureTracker.current())");
    expect(wiringBody()).toContain("goToFeature(featureAt(event.point));");
  });

  it("flies AND opens the card, which is the whole of mirroring Earth", () => {
    // Earth gates the panel on a rendered hero and never gates the fly. Mars's card carries no
    // picture, so there is nothing left to gate and half-wiring it — a fly with no card, or a card
    // with no fly — is the failure this pins. Neither half has another witness.
    expect(wiringBody()).toContain("map.flyTo(camera);");
    expect(wiringBody()).toContain("openPanel(featurePanelContent(feature));");
  });

  it("takes the centre from the catalogue, because a tile does not carry one", () => {
    // `features_geojson.CARRIED_FIELDS` keeps the gazetteer's unfolded centres out of the tiles, so
    // the picked name must be looked up before the camera has a target. Building the card from the
    // same row is what keeps a searched card and a tapped card identical.
    expect(wiringBody()).toContain("featureNamed(name)");
  });

  it("asks for the catalogue LAZILY, or Earth downloads Mars's place names", () => {
    // THE ONLY SYMPTOM OF GETTING THIS WRONG IS BYTES. Both pages mount this one component and so
    // share one client chunk; a static import puts 324 KB of Martian nomenclature into Earth's
    // download, where nothing reads it and no test notices. Present-then-absent rather than absent
    // alone, because "does not appear" is true of any string that was merely renamed.
    expect(wiringBody()).toContain('import("../lib/featureIndex")');
    expect(GLOBE).not.toMatch(/^\s*import .*from "\.\.\/lib\/featureIndex";$/m);
  });

  it("hands the chip to the tracker that answers on this body", () => {
    // `closePanel` repaints the chip with no pointer event to go on, so it has to ask the resolver
    // this body actually uses. Reading the country tracker there leaves a closed Mars card with a
    // lit outline and no name, until the pointer happens to move.
    expect(wiringBody()).toContain("chipOwner = featureTracker;");
    expect(GLOBE).toContain("chipOwner.viewChanged();");
    expect(GLOBE).toContain("paintChip(chipOwner.current());");
  });

  it("suppresses the chip on touch for every body, now that every tap brings a card", () => {
    // `chip-answers-taps` existed because a Mars tap had no card to arrive and the chip was the
    // whole answer. It has a card now, so the exception is gone and the rule is unconditional —
    // which also covers the window where Mars's card is still waiting on its catalogue fetch.
    expect(GLOBE).toMatch(/@media \(hover: none\) \{\s*\n\s*\.country-chip \{/);
    expect(GLOBE).not.toContain("chip-answers-taps");
  });

  it("queries BOTH hit surfaces, since the two kinds of feature are disjoint sets", () => {
    // Polygons answer through the fill; the valles and fossae carry no polygon anywhere in the
    // archive and answer only through their own widened stroke. Querying one is a globe where an
    // entire class of named feature is unreachable, and nothing else would say so.
    // Per layer rather than in one query, because which surface a feature arrived through is
    // what says whether its diameter is a width or a length.
    expect(wiringBody()).toContain('["feature-fill", false]');
    expect(wiringBody()).toContain('["feature-linear-hit", true]');
  });

  it("clears the highlight when the pointer leaves the canvas", () => {
    expect(wiringBody()).toContain('map.on("mouseout", () => featureTracker.pointerLeft());');
  });

  it("writes the hover state through the shared targets rather than a local list", () => {
    // A second copy of "which source-layers carry hover paint" is the drift that leaves half a
    // feature lit — featureOverlay.test.ts holds that list against the layers that actually paint.
    expect(wiringBody()).toContain("hoverStateTargets()");
  });
});

describe("the page wires the search field to the pick path it already has", () => {
  it("mounts the button in the CAMERA group, which is what the placement argument rests on", () => {
    // Not `.maplibregl-ctrl-fullscreen`, which is the frame group the quiet toggle joins. Choosing
    // a result moves the camera, so the button belongs with zoom, compass and spin — the grouping
    // is the only thing on the page that states which concern a control serves.
    expect(searchBlock()).toContain(
      'joinRailGroup(map.getContainer(), ".maplibregl-ctrl-zoom-in", searchToggle.button)',
    );
  });

  it("builds the control with the rest of the rail, not when its catalogue arrives", () => {
    // THE DEFECT THIS REPLACED. Every other rail control is created during module evaluation and
    // this one was created inside the map's first `idle`, so the group grew a fourth button under
    // a pointer already resting on it — 543, 593 and 1142 ms in over three cold loads, against the
    // 50-67 ms the catalogue then took, which is the delay everyone would have blamed instead.
    // A source scan is what is reachable here: the construction sits outside the wiring, and the
    // wiring only arms it.
    expect(wiringBody()).not.toContain("createCatalogueSearchBox(");
    expect(searchBlock()).toContain("createCatalogueSearchBox(");
  });

  it("joins the rail after spin, since joinRailGroup appends and that IS the rail's order", () => {
    // Not cosmetic and not incidental: moving the construction earlier moves the button, and the
    // order these two calls appear in is the only record of where a visitor finds it.
    const spin = GLOBE.indexOf('".maplibregl-ctrl-zoom-in", spinToggle.button');
    const search = GLOBE.indexOf('".maplibregl-ctrl-zoom-in", searchToggle.button');
    expect(spin, "spin no longer joins the camera group").toBeGreaterThan(-1);
    expect(search, "search no longer joins the camera group").toBeGreaterThan(-1);
    expect(spin).toBeLessThan(search);
  });

  it("routes a chosen row through goToFeature, so one card is built one way", () => {
    // A second path from a search hit to a card would be a second card builder in all but name:
    // the same feature could then arrive with a different eyebrow or no fly-to at all.
    //
    // TWO HALVES NOW, because the control outlives the scope its pick path lives in: the box hands
    // the row to a binding, and the wiring points that binding at `goToFeature`. Either half alone
    // is a field that opens, lists and does nothing when a row is chosen.
    // The box's own parameter is `entry` and not `feature`: the control is shared with Earth now,
    // and a row it hands back is a `SearchEntry` whichever planet built it.
    expect(searchBlock()).toContain("onChoose: (entry) => searchPick?.(entry.name)");
    expect(wiringBody()).toContain("searchPick = goToFeature;");
  });

  it("dismisses the card when the field opens, because the two share one corner", () => {
    // Measured on the live page rather than assumed: the card spans 2121-2541 and the panel
    // 2154-2506 at desktop width. Without this they stack.
    expect(searchBlock()).toContain("if (open) closePanel();");
  });

  it("greys the button until the catalogue lands, rather than looking live and doing nothing", () => {
    // The two ends are in the two blocks by construction: the button is born unavailable where it
    // is built, and only the arrival of a catalogue can say otherwise.
    expect(searchBlock()).toContain("searchToggle.setAvailable(false,");
    expect(wiringBody()).toContain("searchToggle?.setAvailable(true)");
  });

  it("builds the matcher from the SAME dynamic import the pick path uses", () => {
    // One fetch of the catalogue, not two. `catalogueSearch` itself is imported statically and may
    // be — it names `NamedFeature` as a type and holds no data; the 324 KB array is what has to
    // stay on this chunk, and asking for it again here would defeat that by duplicating it.
    expect(wiringBody()).toContain("featureCatalogue.then(({ featureIndex })");
    expect(wiringBody()).toContain("matcher = createCatalogueSearch(featureIndex.map(featureSearchEntry))");
  });

  it("hands the panel to quiet mode, which cannot reach it through the stylesheet", () => {
    // `body.is-quiet` hides `.maplibregl-ctrl-group`s. The panel is not one — it is a panel, not a
    // button — so hiding the controls would otherwise leave a search field floating beside a
    // vanished rail. Verified as a pair: the handover here, and the close in `reflectQuiet`.
    expect(searchBlock()).toContain("searchPanel = searchBox;");
    expect(GLOBE).toContain("if (next) searchPanel?.close();");
  });
});

describe("the right-hand band holds one box at a time, and none of them cover the rail", () => {
  it("closes the search panel when a card opens, which is the direction that was missing", () => {
    // One direction was already there (opening the field dismisses the card) and was not enough:
    // with the field up, a click on the globe opened a card straight over it.
    expect(GLOBE).toContain("searchPanel?.close();\n    panel.querySelector");
  });

  it("clears the rail rather than covering it, on BOTH bodies", () => {
    // At a flat inset the card sat on top of the whole top-right stack from the moment anything was
    // picked — its z-index is 30 against MapLibre's control corner at 2 — so zoom, compass, spin
    // and fullscreen were all unreachable behind it. Earth had this too.
    expect(GLOBE).toContain("right: var(--rail-clearance);");
    expect(GLOBE).toContain(
      "width: min(420px, calc(100vw - var(--page-inset) - var(--rail-clearance)));",
    );
    expect(GLOBE).not.toMatch(/\.detail-panel\s*\{[^}]*right:\s*1\.2rem/);
  });

  it("takes the whole narrow band rather than dropping below the row it would cover", () => {
    // Widening into the space the rail leaves puts the card's left edge back over the top-left row, and
    // the first fix dropped the card past that row. At 390 px the card spans 326 px of the
    // viewport, so nothing shares its line either way — dropping it cost 48 px AND left the row
    // reading as debris above the card. The row yields now, on a class the page writes.
    //
    // READ OUT OF THE CARD'S OWN RULE, not out of a slice of the file. Written as a region scan
    // anchored on `.detail-panel[hidden]` this MISSED its own mutation twice over: the declaration
    // it guards sits ABOVE that anchor, and `top: var(--page-inset)` is true of four other rules,
    // so both halves passed against a card pinned back at 4.2rem.
    const rules = [...GLOBE.matchAll(/\.detail-panel\s*\{([^}]*)\}/g)].map((match) => match[1]);
    expect(rules, "the card must still have exactly one positioning rule").toHaveLength(1);
    expect(rules[0], "the card starts at the shared inset, at every width").toMatch(
      /top:\s*var\(--page-inset\);/,
    );
  });
});

describe("a narrow phone gives the open box the whole top band", () => {
  it("writes the class from BOTH occupants' state, not from whoever moved last", () => {
    // The card and the field close each other, so every open runs a close first. Two
    // `toggle(true/false)` calls would depend on listener order, and the failure is a phone whose
    // way back to the gallery is gone with nothing on screen explaining it.
    expect(GLOBE).toContain(
      "const occupied = !panel.hidden || (searchPanel?.isOpen() ?? false);",
    );
    // Every state change has to reach it: the card opening, the card closing, the field either way.
    expect(GLOBE.match(/reflectBand\(\);/g) ?? [], "three call sites, one per transition").toHaveLength(3);
  });

  it("spells the class the same on both sides of a seam nothing can close", () => {
    // A stylesheet cannot import a constant, so the name exists twice — and a class that matches
    // nothing is valid CSS that cascades and does nothing. Derived from the page rather than
    // listed, so renaming it in one place is what fails rather than editing this line.
    const declared = GLOBE.match(/const PANEL_OPEN_CLASS = "([\w-]+)";/);
    expect(declared, "the page must still name the class it writes").not.toBeNull();
    expect(GLOBE_CSS, "globe.css must carry rules for the class the page writes").toContain(
      `body.${declared![1]} `,
    );
  });

  it("hides the credit with everything else in its band, and says why in the same breath", () => {
    // The one that looks like an oversight and is not: quiet mode deliberately KEEPS the credit as
    // a ghost, because quiet is a state you can sit in. A card is transient and restores the band
    // on close. Asserting them together is what stops a later reader "restoring" one of them.
    // The body switcher is in the list because it shares the band, not the row — it is centred
    // between the left row and the rail, which is exactly where a phone's panel lands.
    const block = GLOBE_CSS.slice(GLOBE_CSS.indexOf("body.panel-open .globe-source"));
    for (const hidden of [".globe-source", ".body-switcher", ".chrome-credit"]) {
      expect(block.slice(0, 300), `${hidden} must yield with the rest of the band`).toContain(
        hidden,
      );
    }
  });
});
