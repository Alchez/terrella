import { describe, it, expect } from "vitest";
import { createHoverHighlight, type HighlightTarget } from "./hoverHighlight";

/**
 * The decoration state machine, driven without a map.
 *
 * WHAT THESE EXIST FOR is the pair of transitions no pointer event produces: switching the
 * highlight off while the pointer is parked on something, and switching it back on. Everything
 * else here is the behaviour those two depend on — that the module knows what is lit even while it
 * is painting nothing, and that the name and the paint can never disagree about the switch.
 */

const FILL: HighlightTarget = { source: "countries", sourceLayer: "country_fill" };
const OUTLINE: HighlightTarget = { source: "countries", sourceLayer: "country_outline" };

/** A recording harness: every state write in order, and every label the chip was handed. */
function harness(enabled: boolean, targets: HighlightTarget[] = [FILL, OUTLINE]) {
  const writes: string[] = [];
  const labels: (string | null)[] = [];
  const highlight = createHoverHighlight({
    targets,
    write: (target, id, hover) => writes.push(`${target.sourceLayer}:${id}=${hover}`),
    label: (id) => labels.push(id),
    enabled,
  });
  return { highlight, writes, labels };
}

describe("painting what the pointer is on", () => {
  it("lights every target that carries paint, because one write cannot serve two layers", () => {
    const { highlight, writes } = harness(true);

    highlight.paint("Chile");

    // Feature state keys on (source, sourceLayer, id) — the fill and the outline share a source and
    // are still two separate writes. A loop that stopped at the first would light half a country.
    expect(writes).toEqual(["country_fill:Chile=true", "country_outline:Chile=true"]);
  });

  it("clears what is being left before lighting what is being entered", () => {
    const { highlight, writes } = harness(true);

    highlight.paint("Chile");
    writes.length = 0;
    highlight.paint("Peru");

    expect(writes).toEqual([
      "country_fill:Chile=false",
      "country_outline:Chile=false",
      "country_fill:Peru=true",
      "country_outline:Peru=true",
    ]);
  });

  it("names what it lights, so the chip cannot describe a different feature", () => {
    const { highlight, labels } = harness(true);

    highlight.paint("Chile");
    highlight.paint(null);

    expect(labels).toEqual(["Chile", null]);
  });
});

describe("switched off", () => {
  it("writes nothing at all and names nothing", () => {
    const { highlight, writes, labels } = harness(false);

    highlight.paint("Chile");
    highlight.paint("Peru");

    expect(writes).toEqual([]);
    // The chip is part of the decoration, not a neighbour of it: a visitor who asked not to have
    // the thing under the pointer dressed up must not get a floating label instead.
    expect(labels).toEqual([null, null]);
  });

  it("still tracks what the pointer is on, which is what makes switching back on work", () => {
    const { highlight } = harness(false);

    highlight.paint("Chile");

    expect(highlight.lit()).toBe("Chile");
  });
});

describe("the switch itself", () => {
  it("clears the parked feature the moment it goes off, with no pointer event to help", () => {
    // THE TRANSITION THIS MODULE EXISTS FOR. The pointer is sitting on a country when the button is
    // pressed and no mousemove is coming, so without this the globe keeps the old paint until the
    // visitor moves the mouse — which reads as the button having done nothing.
    const { highlight, writes, labels } = harness(true);
    highlight.paint("Chile");
    writes.length = 0;
    labels.length = 0;

    highlight.setEnabled(false);

    expect(writes).toEqual(["country_fill:Chile=false", "country_outline:Chile=false"]);
    expect(labels).toEqual([null]);
  });

  it("lights the parked feature the moment it goes on", () => {
    const { highlight, writes, labels } = harness(false);
    highlight.paint("Chile");
    writes.length = 0;
    labels.length = 0;

    highlight.setEnabled(true);

    expect(writes).toEqual(["country_fill:Chile=true", "country_outline:Chile=true"]);
    expect(labels).toEqual(["Chile"]);
  });

  it("does nothing on a repeat of the value it already holds", () => {
    // The layout broadcasts on every click, and a globe that re-wrote state per broadcast would do
    // a write per target for no visible change.
    const { highlight, writes, labels } = harness(true);
    highlight.paint("Chile");
    writes.length = 0;
    labels.length = 0;

    highlight.setEnabled(true);

    expect(writes).toEqual([]);
    expect(labels).toEqual([]);
  });

  it("is safe over empty ground, where there is nothing to repaint", () => {
    const { highlight, writes } = harness(true);

    highlight.setEnabled(false);
    highlight.setEnabled(true);

    expect(writes).toEqual([]);
    expect(highlight.lit()).toBeNull();
  });

  it("reports its own state, which is how the second body inherits it", () => {
    // Mars wires its highlight long after the page loads, and reads this to start out agreeing with
    // whatever the visitor has already chosen — including a click made while the wiring was pending.
    const { highlight } = harness(true);

    expect(highlight.isEnabled()).toBe(true);
    highlight.setEnabled(false);
    expect(highlight.isEnabled()).toBe(false);
  });
});

describe("relabelling after a card closes", () => {
  it("restores the name without touching feature state", () => {
    // `closePanel`'s repaint. The paint never went anywhere — the card was over it — so re-writing
    // state here would be a write per card close for no change.
    const { highlight, writes, labels } = harness(true);
    highlight.paint("Chile");
    writes.length = 0;
    labels.length = 0;

    highlight.relabel();

    expect(writes).toEqual([]);
    expect(labels).toEqual(["Chile"]);
  });

  it("stays silent while the highlight is switched off", () => {
    // The regression this pins: `closePanel` used to write the chip directly, so a card closed with
    // the highlight off would have put a name back up over completely unlit ground.
    const { highlight, labels } = harness(false);
    highlight.paint("Chile");
    labels.length = 0;

    highlight.relabel();

    expect(labels).toEqual([null]);
  });
});
