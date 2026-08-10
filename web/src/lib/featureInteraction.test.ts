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
