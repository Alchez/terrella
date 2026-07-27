import { describe, it, expect } from "vitest";
import { readFileSync } from "node:fs";
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

// Base.astro's pre-paint tier guard, tested by RUNNING THE SHIPPED SOURCE. It cannot be imported
// — it must execute before the bundle loads, which is the whole reason it is `is:inline` — so the
// script is extracted from the .astro file and evaluated against stubbed browser globals. That
// keeps one copy of the logic: a rewrite of the guard is exercised here, not just string-matched.
//
// These tests exist because the guard shipped with a bug nothing pinned. `rg:steered` was written
// ONLY on the auto-steer path, so it meant "we bounced you once" rather than "this session has
// seen the globe" — and a visitor who reached /globe any other way (deep link, or the view bar's
// Globe/Full button, which additionally cleared the flag) had their ← Gallery click hijacked
// straight back to the globe.
const guardSource = (() => {
  const base = readFileSync(new URL("../layouts/Base.astro", import.meta.url), "utf8");
  const inlineScripts = [...base.matchAll(/<script is:inline>([\s\S]*?)<\/script>/g)].map(
    (match) => match[1],
  );
  const guard = inlineScripts.find((script) => script.includes("rg:steered"));
  if (!guard) throw new Error("Base.astro no longer has an inline script mentioning rg:steered");
  return guard;
})();

interface GuardVisit {
  path: string;
  quality?: string;
  steered?: boolean;
  webgl2?: boolean;
  saveData?: boolean;
}

interface GuardOutcome {
  /** Every URL the guard redirected to, in order. Empty means it let the page render. */
  redirects: string[];
  /** The session flag AFTER the guard ran. */
  steered: boolean;
}

/** Run the extracted guard against one simulated visit. */
function visit({
  path,
  quality = "auto",
  steered = false,
  webgl2 = true,
  saveData = false,
}: GuardVisit): GuardOutcome {
  const session = new Map<string, string>(steered ? [["rg:steered", "1"]] : []);
  const local = new Map<string, string>(quality ? [["rg:quality", quality]] : []);
  const redirects: string[] = [];

  const storage = (backing: Map<string, string>) => ({
    getItem: (key: string) => backing.get(key) ?? null,
    setItem: (key: string, value: string) => void backing.set(key, value),
    removeItem: (key: string) => void backing.delete(key),
  });

  new Function(
    "location",
    "localStorage",
    "sessionStorage",
    "navigator",
    "document",
    "matchMedia",
    guardSource,
  )(
    { pathname: path, replace: (url: string) => redirects.push(url) },
    storage(local),
    storage(session),
    { connection: { saveData } },
    { createElement: () => ({ getContext: () => (webgl2 ? {} : null) }) },
    () => ({ matches: false }),
  );

  return { redirects, steered: session.get("rg:steered") === "1" };
}

describe("Base.astro tier guard — steering onto the globe", () => {
  // POSITIVE CONTROL, and deliberately first. The guard body is wrapped in `try { } catch (e) {}`
  // so that it can never break the page — which also means a broken stub here would be swallowed
  // and every "does not redirect" assertion below would pass vacuously. This test is the one that
  // fails loudly if the harness stops driving the real code.
  it("steers a capable first-time visitor from the gallery to the globe", () => {
    expect(visit({ path: "/" })).toEqual({ redirects: ["/globe/"], steered: true });
  });

  it("steers only once per session, so a deliberate return to the gallery sticks", () => {
    expect(visit({ path: "/", steered: true }).redirects).toEqual([]);
  });

  it("leaves the gallery alone when the visitor forced Lite", () => {
    expect(visit({ path: "/", quality: "lite" }).redirects).toEqual([]);
  });

  it("leaves the gallery alone without WebGL2, whatever the saved quality", () => {
    expect(visit({ path: "/", quality: "full", webgl2: false }).redirects).toEqual([]);
  });

  it("respects data-saver on auto, but not against an explicit choice", () => {
    expect(visit({ path: "/", saveData: true }).redirects).toEqual([]);
    expect(visit({ path: "/", quality: "full", saveData: true }).redirects).toEqual(["/globe/"]);
  });
});

describe("Base.astro tier guard — rg:steered means 'this session has seen the globe'", () => {
  // The regression the flag's old meaning caused, one test per route onto the globe.
  it("marks the session steered when the globe is reached by deep link", () => {
    expect(visit({ path: "/globe/" })).toEqual({ redirects: [], steered: true });
  });

  it("marks it for the extensionless path too", () => {
    expect(visit({ path: "/globe" }).steered).toBe(true);
  });

  it("does NOT mark it when the globe refuses to render, since it was never seen", () => {
    expect(visit({ path: "/globe/", quality: "lite" })).toEqual({ redirects: ["/"], steered: false });
    expect(visit({ path: "/globe/", webgl2: false })).toEqual({ redirects: ["/"], steered: false });
  });

  it("lets ← Gallery reach the gallery after a deep-linked globe visit", () => {
    // The reported bug, end to end: the flag written by visit one must survive into visit two.
    const globeVisit = visit({ path: "/globe/" });
    expect(globeVisit.steered).toBe(true);
    expect(visit({ path: "/", steered: globeVisit.steered }).redirects).toEqual([]);
  });

  it("never clears the flag — clearing it is what re-armed the hijack", () => {
    const base = readFileSync(new URL("../layouts/Base.astro", import.meta.url), "utf8");
    expect(base).not.toMatch(/removeItem\(\s*["']rg:steered["']\s*\)/);
  });
});

// The view bar's phone collapse. It lives here rather than beside the credit tests because its
// render condition IS the capability control: the toggle exists exactly where the tier picker
// does, since that segment is what makes the bar too wide for a phone.
describe("Base.astro view bar — the phone collapse", () => {
  const base = readFileSync(new URL("../layouts/Base.astro", import.meta.url), "utf8");

  it("renders the trigger only alongside the tier picker", () => {
    // A hero page's bar is one Focus button; collapsing that costs a tap and saves nothing.
    const [, afterToggleGuard] = base.split('{quality && (\n            <button');
    expect(afterToggleGuard).toBeDefined();
    expect(afterToggleGuard).toContain('class="view-bar-toggle"');
  });

  it("puts the trigger OUTSIDE the group it controls", () => {
    // A control that collapses a group must not be inside it, or collapsing hides the only way
    // to un-collapse. Structural, not stylistic: .view-bar-items is what `display: none` hits.
    const toggleAt = base.indexOf('class="view-bar-toggle"');
    const groupAt = base.indexOf('class="view-bar-items"');
    expect(toggleAt).toBeGreaterThan(-1);
    expect(groupAt).toBeGreaterThan(-1);
    expect(toggleAt).toBeLessThan(groupAt);
    // role="group" moved onto the collapsible wrapper, so the credit folded in beside it by
    // globe.astro is not announced as a "view option".
    expect(base).toMatch(/class="view-bar-items"[^>]*role="group"/);
    expect(base).not.toMatch(/class="view-bar"\s+role="group"/);
  });

  it("wires the trigger to the group it hides, and reports its state", () => {
    expect(base).toMatch(/aria-controls="view-bar-items"/);
    expect(base).toMatch(/aria-expanded="false"/); // server default: closed
    expect(base).toContain('viewBarToggle.setAttribute("aria-expanded", String(open))');
  });

  it("defaults closed, so a phone visitor gets the map rather than the chrome", () => {
    // `=== "1"` and not `!== "0"`: an absent key must read as closed, not open.
    expect(base).toContain('localStorage.getItem(VIEW_BAR_KEY) === "1"');
  });

  it("gives every control in the bar a tooltip", () => {
    // The bar is all short one-word labels ("Lite", "Focus", "Spin"), which name the thing
    // without saying what it does. A control added without a title is the drift this catches.
    const items = base.slice(base.indexOf('class="view-bar-items"'), base.indexOf("</body>"));
    const buttons = items.match(/<button[\s\S]*?>/g) ?? [];
    expect(buttons.length).toBeGreaterThanOrEqual(6); // borders, focus, spin, lite, globe, full
    for (const button of buttons) expect(button).toMatch(/title="[^"]+"/);
  });

  it("does not advertise a tier feature the site has not built", () => {
    // Full currently buys ONE thing: globe.astro's idle spin, the site's only currentTier()
    // read. Terrain is built but behind ?terrain and wired to no tier. If a tooltip starts
    // claiming terrain while nothing reads the tier for it, the button is selling a promise.
    const globe = readFileSync(new URL("../pages/globe.astro", import.meta.url), "utf8");
    const tierReads = (globe.match(/currentTier\(\)/g) ?? []).length;
    const fullTooltip = base.match(/data-quality="full"[\s\S]*?title="([^"]+)"/)?.[1] ?? "";
    if (tierReads <= 1) expect(fullTooltip.toLowerCase()).not.toContain("terrain");
  });

  it("marks the bar collapsible on EXACTLY the condition that renders the trigger", () => {
    // The bug this catches, found by measurement: the media query hid .view-bar-items on every
    // page at phone width, but the trigger renders only where `quality` does — so a hero page
    // lost its Focus button with nothing on screen able to bring it back. The class and the
    // trigger must be gated on the same prop, or the collapse strands controls.
    expect(base).toMatch(/class:list=\{\["view-bar", quality && "is-collapsible"\]\}/);
    const css = readFileSync(new URL("../styles/global.css", import.meta.url), "utf8");
    expect(css).toContain(".view-bar.is-collapsible:not(.is-open) .view-bar-items");
    // The unscoped form is the bug; it must not come back.
    expect(css).not.toMatch(/\.view-bar:not\(\.is-open\) \.view-bar-items/);
  });
});
