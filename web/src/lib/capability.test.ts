import { describe, it, expect } from "vitest";
import { decideTier, type CapabilitySignals, type Quality } from "./capability";

// A device that passes every check — the baseline each test perturbs one field of.
const healthy: CapabilitySignals = {
  webgl2: true,
  softwareGpu: false,
  saveData: false,
  slowNetwork: false,
  lowMemory: false,
  reducedMotion: false,
};

const signals = (overrides: Partial<CapabilitySignals> = {}): CapabilitySignals => ({
  ...healthy,
  ...overrides,
});

describe("decideTier — explicit user override wins over the probe", () => {
  it("'lite' always yields the gallery, even on a fully capable device", () => {
    expect(decideTier(signals(), "lite")).toBe("gallery");
  });

  it("'globe' yields the globe when capable", () => {
    expect(decideTier(signals(), "globe")).toBe("globe");
  });

  it("'full' yields full when capable", () => {
    expect(decideTier(signals(), "full")).toBe("full");
  });

  it("an override cannot exceed the hard WebGL2 floor: 'globe' without WebGL2 falls back to gallery", () => {
    expect(decideTier(signals({ webgl2: false }), "globe")).toBe("gallery");
  });

  it("an override cannot exceed the hard floor: 'full' on a software GPU falls back to gallery", () => {
    expect(decideTier(signals({ softwareGpu: true }), "full")).toBe("gallery");
  });

  it("an explicit 'full' ignores soft pessimistic signals (the user asked for it)", () => {
    expect(decideTier(signals({ saveData: true, lowMemory: true }), "full")).toBe("full");
  });
});

describe("decideTier — auto (probe decides), pessimistic by default", () => {
  it("no WebGL2 → gallery", () => {
    expect(decideTier(signals({ webgl2: false }), "auto")).toBe("gallery");
  });

  it("software GPU (SwiftShader/llvmpipe) → gallery", () => {
    expect(decideTier(signals({ softwareGpu: true }), "auto")).toBe("gallery");
  });

  it("Save-Data → gallery (tiles are data-heavy; respect the preference)", () => {
    expect(decideTier(signals({ saveData: true }), "auto")).toBe("gallery");
  });

  it("slow network → gallery", () => {
    expect(decideTier(signals({ slowNetwork: true }), "auto")).toBe("gallery");
  });

  it("capable but low memory → globe (raster globe is light; skip the heavier full)", () => {
    expect(decideTier(signals({ lowMemory: true }), "auto")).toBe("globe");
  });

  it("capable but reduced-motion → globe (full's extra is animation, which they opt out of)", () => {
    expect(decideTier(signals({ reducedMotion: true }), "auto")).toBe("globe");
  });

  it("capable and healthy → full (upgrade optimistically)", () => {
    expect(decideTier(signals(), "auto")).toBe("full");
  });

  it("data pessimism outranks the low-memory/globe rule: Save-Data + low memory → gallery", () => {
    expect(decideTier(signals({ saveData: true, lowMemory: true }), "auto")).toBe("gallery");
  });
});

describe("decideTier — quality type is the persisted contract", () => {
  it("accepts the four documented quality values", () => {
    const all: Quality[] = ["auto", "lite", "globe", "full"];
    for (const quality of all) {
      expect(() => decideTier(signals(), quality)).not.toThrow();
    }
  });
});
