import { describe, expect, it } from "vitest";
import { TIER_NOTE } from "./aboutContent";
import { decideTier, type CapabilitySignals, type Tier } from "./capability";
import { nextDegradationAction, type DegradationAction } from "./fpsDegradation";

/**
 * The About note on Lite, Globe and Full restates two decisions the code makes: which signals move
 * a visitor off Full, and the order the globe steps down in. Both are read here from the functions
 * that make them, so a signal or a rung added to either is red until the note says it. The phrases
 * are the note's claims rather than its sentences: reword freely and keep them.
 */

const HEALTHY: CapabilitySignals = {
  webgl2: true,
  softwareGpu: false,
  performanceCaveat: false,
  saveData: false,
  slowNetwork: false,
  lowMemory: false,
  reducedMotion: false,
};

/** Keyed on the interface, so a signal added to the probe does not compile here until it is named. */
const SIGNAL_NAMED_AS: Record<keyof CapabilitySignals, string> = {
  webgl2: "can't draw",
  softwareGpu: "can't draw",
  performanceCaveat: "can't draw",
  saveData: "save data",
  slowNetwork: "slow connection",
  lowMemory: "memory",
  reducedMotion: "reduced motion",
};

/** The word on the picker's button, which is what a visitor reads the note for. */
const PICKER_LABEL: Record<Tier, string> = { gallery: "Lite", globe: "Globe", full: "Full" };

type Rung = NonNullable<DegradationAction>;
type LadderState = Parameters<typeof nextDegradationAction>[0];

const RUNG_NAMED_AS: Record<Rung, string> = {
  "retire-spin": "spin stops",
  "lower-pixel-ratio": "softens",
  "disable-terrain": "terrain flattens",
};

const TAKEN: Record<Rung, (state: LadderState) => LadderState> = {
  "retire-spin": (state) => ({ ...state, spinning: false }),
  "lower-pixel-ratio": (state) => ({ ...state, pixelRatioLowered: true }),
  "disable-terrain": (state) => ({ ...state, terrainEnabled: false }),
};

const text = TIER_NOTE.paragraphs.join(" ");

function reasonsFor(tier: Tier): string {
  const opening = text.split(/(?<=\.)\s+/).filter((sentence) => sentence.startsWith(PICKER_LABEL[tier]));
  expect(opening, `no one sentence of the note opens with "${PICKER_LABEL[tier]}"`).toHaveLength(1);
  return opening[0]!;
}

describe("the About note on Lite, Globe and Full", () => {
  it("gives every signal that moves a visitor off Full, in the sentence for the version it moves them to", () => {
    expect(decideTier(HEALTHY, "auto"), "the baseline is not Full, so no flip below tests anything").toBe("full");
    for (const signal of Object.keys(SIGNAL_NAMED_AS) as (keyof CapabilitySignals)[]) {
      const tier = decideTier({ ...HEALTHY, [signal]: !HEALTHY[signal] }, "auto");
      expect(tier, `${signal} no longer moves anyone off Full, so the note should drop it`).not.toBe("full");
      expect(reasonsFor(tier), `the note does not give ${signal} as a reason for ${PICKER_LABEL[tier]}`).toContain(
        SIGNAL_NAMED_AS[signal],
      );
    }
  });

  it("describes the step-downs in the order the globe takes them", () => {
    let state: LadderState = { spinning: true, pixelRatioLowered: false, devicePixelRatio: 2, terrainEnabled: true };
    const order: Rung[] = [];
    for (let action = nextDegradationAction(state); action !== null; action = nextDegradationAction(state)) {
      expect(order, `the ladder repeated ${action}, so this walk would never end`).not.toContain(action);
      order.push(action);
      state = TAKEN[action](state);
    }
    expect(new Set(order), "the walk from a spinning, sharp, raised globe skipped a rung").toEqual(
      new Set(Object.keys(RUNG_NAMED_AS)),
    );
    const positions = order.map((rung) => text.indexOf(RUNG_NAMED_AS[rung]));
    expect(positions, `the note is missing a step-down among ${order.join(", ")}`).not.toContain(-1);
    expect(positions, `the note gives the step-downs out of the order ${order.join(", ")}`).toEqual(
      positions.toSorted((first, second) => first - second),
    );
  });
});
