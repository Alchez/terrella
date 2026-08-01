import { describe, it, expect } from "vitest";
import { readFileSync } from "node:fs";
import {
  decideTier,
  isLowMemory,
  isSoftwareRenderer,
  LOW_MEMORY_GIB,
  canRunGlobe,
  type CapabilitySignals,
  type Quality,
} from "./capability";

// A device that passes every check — the baseline each test perturbs one field of.
const healthy: CapabilitySignals = {
  webgl2: true,
  softwareGpu: false,
  performanceCaveat: false,
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
  /** What WEBGL_debug_renderer_info reports, or null to model a browser without the extension. */
  unmaskedRenderer?: string | null;
  /** What the standard gl.RENDERER parameter reports — Firefox's unmasked path. */
  renderer?: string;
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
  unmaskedRenderer = "NVIDIA GeForce RTX 4070 SUPER",
  renderer = "WebKit WebGL",
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
    {
      createElement: () => ({
        getContext: () =>
          webgl2
            ? {
                RENDERER: "RENDERER",
                getExtension: (name: string) =>
                  name === "WEBGL_debug_renderer_info" && unmaskedRenderer !== null
                    ? { UNMASKED_RENDERER_WEBGL: "UNMASKED" }
                    : null,
                getParameter: (name: string) =>
                  name === "UNMASKED" ? unmaskedRenderer : renderer,
              }
            : null,
      }),
    },
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

describe("Base.astro view bar", () => {
  const base = readFileSync(new URL("../layouts/Base.astro", import.meta.url), "utf8");

  it("carries no collapse machinery, on any of the four surfaces it used to touch", () => {
    // The bar's controls measure 229.7 px against the 281.6 px it is allowed at 320 px, so they
    // fit one row at every width the site serves — and a trigger is what pushes 320 px onto two,
    // since trigger-plus-controls is what does not fit there. Reintroducing any one of these
    // brings the wrap back, so all four are named: markup, class, persisted state, and the media
    // query.
    const css = readFileSync(new URL("../styles/global.css", import.meta.url), "utf8");
    expect(base).not.toContain("view-bar-toggle");
    expect(base).not.toContain("is-collapsible");
    expect(base).not.toContain("rg:viewbar");
    expect(css).not.toContain("view-bar-toggle");
    expect(css).not.toMatch(/\.view-bar[^{]*:not\(\.is-open\)/);
  });

  it("announces the controls as a group without sweeping the whole pill into it", () => {
    // role="group" sits on the inner wrapper, not on `.view-bar`: the globe absolutely positions
    // its scale ruler inside that pill, and a readout must not be announced as a view option.
    expect(base).toMatch(/class="view-bar-items"[^>]*role="group"/);
    expect(base).not.toMatch(/class="view-bar"\s+role="group"/);
  });

  it("gives every control in the bar a tooltip", () => {
    // The bar is all short one-word labels ("Lite", "Focus"), which name the thing without saying
    // what it does. A control added without a title is the drift this catches.
    //
    // THE COUNT IS AN ANTI-VACUITY GUARD, not a spec: if the slice or the regex ever stops
    // matching, the loop below passes over an empty array and reports success having checked
    // nothing. Five is what the source renders across every branch: borders, focus, lite, globe,
    // full.
    //
    // The rail's own buttons are built in TypeScript, not markup, so they are out of this test's
    // reach by construction; railControls.browser.test.ts pins their title/aria-label pair
    // instead. Between the two, every control on the globe has a name.
    const items = base.slice(base.indexOf('class="view-bar-items"'), base.indexOf("</body>"));
    const buttons = items.match(/<button[\s\S]*?>/g) ?? [];
    expect(buttons.length).toBeGreaterThanOrEqual(5);
    for (const button of buttons) expect(button).toMatch(/title="[^"]+"/);
  });

  it("advertises exactly what the tier actually buys — no more, no less", () => {
    // Bidirectional on purpose, and keyed on the MECHANISM rather than on a count of
    // `currentTier()` reads. The earlier form only checked one direction ("don't claim terrain
    // before it is wired"), so the moment terrain shipped the test went quiet instead of asking
    // for the copy — a tooltip left describing only the idle spin would have been undersold with
    // nothing to catch it. Now: if terrain rides on the tier the tooltip must say so, and if it
    // ever stops riding on the tier the claim must come back out.
    const globe = readFileSync(new URL("../pages/globe.astro", import.meta.url), "utf8");
    // Keyed on the fact rather than on one spelling — the twin of this detector is in
    // terrainSource.test.ts, and both went red together when `currentTier()` was hoisted to a
    // `bootTier` const, which is the drift signal working rather than a defect.
    const gate = globe.match(
      /resolveTerrainExaggeration\(\s*urlFlags\s*,\s*([\w$]+(?:\(\))?)\s*===\s*"full"\s*\)/,
    );
    const tierExpression = gate?.[1] ?? "";
    const terrainRidesOnTier =
      tierExpression === "currentTier()" ||
      (tierExpression !== "" &&
        new RegExp(`const\\s+${tierExpression}\\s*=\\s*decideTier\\(`).test(globe));
    const fullTooltip = base.match(/data-quality="full"[\s\S]*?title="([^"]+)"/)?.[1] ?? "";
    expect(fullTooltip, "the Full button must carry a tooltip at all").not.toBe("");
    if (terrainRidesOnTier) {
      expect(fullTooltip.toLowerCase()).toContain("terrain");
    } else {
      expect(fullTooltip.toLowerCase()).not.toContain("terrain");
    }
  });

});

// --- The two signals the probe reads, pulled out so they are testable at all -------------------

describe("isLowMemory — the threshold that let the reference phone through", () => {
  // The API reports RAM rounded to the NEAREST power of two, so these are the only values that
  // exist — which is what makes `< 4` and `<= 4` differ by a whole tier of real devices rather
  // than by a rounding edge. The 8 GiB upper clamp in the W3C text is not applied by current
  // Chrome: a 29 GiB machine measured 32, hence the top of this list.
  const REPORTABLE = [0.25, 0.5, 1, 2, 4, 8, 16, 32];

  it("treats every value the API can actually report, on the right side of the line", () => {
    expect(REPORTABLE.filter(isLowMemory)).toEqual([0.25, 0.5, 1, 2, 4]);
    expect(REPORTABLE.filter((gib) => !isLowMemory(gib))).toEqual([8, 16, 32]);
  });

  it("has no odd values to worry about — the reason `< 4` was silently a no-op above 2", () => {
    // If any reportable value sat strictly between 2 and 4, the old comparison would have caught
    // something and this whole fix would be a rounding tweak rather than a tier of real phones.
    expect(REPORTABLE.filter((gib) => gib > 2 && gib < 4)).toEqual([]);
  });

  it("catches exactly 4 — the case the old `< 4` missed", () => {
    // The Moto G Power reports 4, and it is Lighthouse's own mobile reference device. Under the
    // old comparison it was promoted to `full`; nothing in the suite noticed.
    expect(isLowMemory(LOW_MEMORY_GIB)).toBe(true);
    expect(isLowMemory(4)).toBe(true);
  });

  it("does NOT treat an absent value as low — this is every Safari and Firefox", () => {
    // Deliberate, not an oversight. Both vendors decline to implement the API on fingerprinting
    // grounds, so absence describes the browser, not the hardware, and hardwareConcurrency is no
    // substitute: WebKit clamps it to 2 on iOS, so an iPad Pro reports LESS than a budget
    // Android. The runtime ladder carries what the static gate cannot see.
    expect(isLowMemory(undefined)).toBe(false);
  });
});

describe("isSoftwareRenderer — and the two browsers that report it differently", () => {
  it("names the rasterizers that cannot run the globe", () => {
    for (const renderer of [
      "Google SwiftShader",
      "llvmpipe (LLVM 15.0.7, 256 bits)",
      "Microsoft Basic Render Driver",
      "Mesa OffScreen",
      "Software Rasterizer",
    ]) {
      expect(isSoftwareRenderer([renderer]), renderer).toBe(true);
    }
  });

  it("leaves real GPUs alone", () => {
    for (const renderer of [
      "NVIDIA GeForce RTX 4070 SUPER/PCIe/SSE2",
      "Apple M2 Pro",
      "Adreno (TM) 730",
      "Mali-G78 MP14",
      "AMD Radeon RX 7900 XTX",
      "ANGLE (Intel, Intel(R) Iris(R) Xe Graphics, OpenGL 4.5)",
    ]) {
      expect(isSoftwareRenderer([renderer]), renderer).toBe(false);
    }
  });

  it("catches Chrome, where the truth is in the extension and RENDERER is masked", () => {
    expect(isSoftwareRenderer(["Google SwiftShader", "WebKit WebGL"])).toBe(true);
  });

  it("catches Firefox, where the extension is gone and RENDERER carries the truth", () => {
    // THE regression this exists for. `if (!ext) return false` meant that the day Firefox
    // finishes removing WEBGL_debug_renderer_info, every Firefox visitor silently becomes
    // "real GPU" and gets promoted — a check that can no longer fail, which is worse than none.
    expect(isSoftwareRenderer(["llvmpipe (LLVM 15.0.7, 256 bits)"])).toBe(true);
  });

  it("says nothing on an empty list rather than guessing", () => {
    expect(isSoftwareRenderer([])).toBe(false);
    expect(isSoftwareRenderer(["", ""])).toBe(false);
  });
});

describe("Base.astro tier guard — the software-rasterizer floor it used to be missing", () => {
  it("bounces a software-rasterizer visitor who deep-links /globe", () => {
    // Previously the guard tested WebGL2 alone, so this visitor rendered the globe while the
    // page module was independently deciding "gallery" — the two disagreed on the same device.
    const outcome = visit({ path: "/globe/", unmaskedRenderer: "Google SwiftShader" });
    expect(outcome.redirects).toEqual(["/"]);
  });

  it("bounces one whose only renderer string is the standard parameter (Firefox)", () => {
    const outcome = visit({
      path: "/globe/",
      unmaskedRenderer: null, // no WEBGL_debug_renderer_info
      renderer: "llvmpipe (LLVM 15.0.7, 256 bits)",
    });
    expect(outcome.redirects).toEqual(["/"]);
  });

  it("does not steer a software-rasterizer visitor onto the globe from the gallery", () => {
    const outcome = visit({ path: "/", unmaskedRenderer: "llvmpipe (LLVM 15.0.7, 256 bits)" });
    expect(outcome.redirects).toEqual([]);
    expect(outcome.steered).toBe(false);
  });

  it("still steers a real GPU — the control that stops the three above passing vacuously", () => {
    const outcome = visit({ path: "/", unmaskedRenderer: "Apple M2 Pro" });
    expect(outcome.redirects).toEqual(["/globe/"]);
  });
});

describe("the guard and capability.ts must not drift apart", () => {
  // They are two spellings of one rule — the inline guard cannot import the module, because it
  // has to run before the bundle. So the agreement is asserted rather than assumed, over the
  // same scenarios, by running BOTH.
  const scenarios = [
    { name: "real GPU", webgl2: true, renderers: ["NVIDIA GeForce RTX 4070 SUPER"] },
    { name: "SwiftShader via the extension", webgl2: true, renderers: ["Google SwiftShader"] },
    { name: "llvmpipe via RENDERER only", webgl2: true, renderers: ["llvmpipe (LLVM 15.0.7)"] },
    { name: "Mesa OffScreen", webgl2: true, renderers: ["Mesa OffScreen"] },
    { name: "no WebGL2 at all", webgl2: false, renderers: [] },
  ];

  for (const scenario of scenarios) {
    it(`agrees on: ${scenario.name}`, () => {
      const moduleSaysCapable =
        decideTier(
          { ...healthy, webgl2: scenario.webgl2, softwareGpu: isSoftwareRenderer(scenario.renderers) },
          "auto",
        ) !== "gallery";

      const guardSteers =
        visit({
          path: "/",
          webgl2: scenario.webgl2,
          unmaskedRenderer: null,
          renderer: scenario.renderers[0] ?? "",
        }).redirects.length > 0;

      expect(guardSteers, `${scenario.name}: guard and capable() disagree`).toBe(moduleSaysCapable);
    });
  }
});

describe("canRunGlobe — one floor, exported so nothing re-derives it", () => {
  it("passes a device with a real, unencumbered GPU", () => {
    expect(canRunGlobe(healthy)).toBe(true);
  });

  it.each([
    ["no WebGL2 at all", { webgl2: false }],
    ["a software rasterizer by name", { softwareGpu: true }],
    ["the browser declaring a major performance caveat", { performanceCaveat: true }],
  ])("refuses the globe on %s", (_case, overrides) => {
    expect(canRunGlobe(signals(overrides))).toBe(false);
  });

  it("sends a caveated device to the gallery on every quality setting that could reach the globe", () => {
    // The signal is only worth adding if it actually reaches the decision — a new field that
    // nothing consults is indistinguishable from no field.
    const caveated = signals({ performanceCaveat: true });
    expect(decideTier(caveated, "auto")).toBe("gallery");
    expect(decideTier(caveated, "globe")).toBe("gallery");
    expect(decideTier(caveated, "full")).toBe("gallery");
  });

  it("is independent of softwareGpu, so a log can say which one fired", () => {
    // Folding them into one boolean would have been fewer lines and would have lost the fact
    // anyone debugging "why no globe" actually needs.
    expect(canRunGlobe(signals({ softwareGpu: true, performanceCaveat: false }))).toBe(false);
    expect(canRunGlobe(signals({ softwareGpu: false, performanceCaveat: true }))).toBe(false);
  });
});

describe("index.astro asks the floor rather than restating it", () => {
  const index = readFileSync(new URL("../pages/index.astro", import.meta.url), "utf8");

  it("uses canRunGlobe to decide whether to offer the Globe link", () => {
    expect(index).toContain("canRunGlobe(probeSignals())");
  });

  it("no longer re-derives the floor inline", () => {
    // It read `gpu.webgl2 && !gpu.softwareGpu`, which would have silently kept offering the globe
    // to caveated devices the moment a third signal joined the floor.
    expect(index).not.toMatch(/webgl2\s*&&\s*!\w+\.softwareGpu/);
  });
});

describe("the scripted-diagnosis seam is gated by the module boundary", () => {
  const globe = readFileSync(new URL("../pages/globe.astro", import.meta.url), "utf8");
  const overlay = readFileSync(new URL("./perf/perfOverlay.ts", import.meta.url), "utf8");

  it("lives in the lazily-imported instrument, so an ordinary visit cannot reach it", () => {
    // The gate is that perfOverlay loads only inside the ?perf branch, so a visitor without the flag
    // never downloads this module at all. The import SHAPE is not re-checked here: `lib/perf/`'s own
    // lazyBoundary.test.ts owns that rule for the whole directory, and a duplicate of it here was
    // silently vacuous for its entire life — anchored `^import` against Astro's indented imports, so
    // it matched nothing and passed by finding nothing.
    expect(overlay).toContain("terrellaMap = map");
    expect(globe).toMatch(/if \(urlFlags\.has\("perf"\)\)/);
    expect(globe).toContain('import("../lib/perf/perfOverlay")');
  });

  it("is not also written from the page, where nothing structural would gate it", () => {
    // The first version of this seam DID live in globe.astro behind the flag, guarded by a test
    // asserting the assignment appeared within the flag block's text span. A sabotage that closed
    // the block early and re-opened it after the assignment passed that test: the statement was
    // outside the gate and still inside the span. A region match cannot decide what encloses a
    // statement, so the gate moved to the module boundary and this asserts the page stays clean.
    expect(globe).not.toContain("terrellaMap");
  });
});

describe("probeSignals is a GPU allocation, and callers must treat it as one", () => {
  const capability = readFileSync(new URL("./capability.ts", import.meta.url), "utf8");
  const globe = readFileSync(new URL("../pages/globe.astro", import.meta.url), "utf8");

  it("releases the context it creates, not just the canvas", () => {
    // A live WebGL context is a GPU resource held until GC. Browsers force-lose the OLDEST live
    // context past a per-page ceiling (~16 in Chrome), so a leaked probe context does not cost
    // memory — it costs whichever context is oldest, which is the map's.
    const probe = capability.match(/export function probeSignals[\s\S]*?\n\}/)?.[0];
    expect(probe, "probeSignals must exist").toBeTruthy();
    expect(probe).toContain('getContext("webgl2")');
    expect(probe).toContain('getExtension("WEBGL_lose_context")?.loseContext()');
  });

  it("is never called from the ?perf overlay's per-tick path", () => {
    // THE BUG THIS EXISTS FOR. `composeReport` ran from `extraLines`, which the overlay calls every
    // 300 ms while EXPANDED. probeSignals() creates a context, detectPerformanceCaveat() a second,
    // and currentTier() calls probeSignals() again — measured live at 0 contexts per 3 s collapsed
    // versus 40 per 3 s expanded, i.e. 13.3/second. It killed the map's context within about a
    // second of the panel being opened and then reported the rebuilds as the page's own fault,
    // producing five "context losses" per phone run and a false conclusion that terrain was to
    // blame. The signals are static hardware facts; probe once, outside the closure.
    // `\(` alone, not `\(timing`: the signature gained a third parameter and went multi-line, which
    // broke the old anchor and is worth noting — a matcher pinned to an argument list is pinned to
    // the least stable part of a declaration.
    const compose = globe.match(/const composeReport = \([\s\S]*?\n {8}\};/)?.[0];
    expect(compose, "the report composer must exist").toBeTruthy();
    expect(compose!.length, "matched a runaway span, not the composer").toBeLessThan(3200);
    for (const forbidden of ["probeSignals(", "currentTier(", "deviceClass("]) {
      expect(compose, `${forbidden}) allocates or re-probes; hoist it`).not.toContain(forbidden);
    }
    // ...and it must still REPORT them, from values probed once outside.
    expect(compose).toContain("signals: probedSignals");
    expect(compose).toContain("deviceClass: probedDeviceClass");
  });

  it("still tracks a quality change the user makes mid-session", () => {
    // Caching the tier outright would be the lazy fix and would be wrong: the quality toggle
    // writes localStorage while the page is live. Signals are hardware and static; quality is not.
    expect(globe).toContain("tier: decideTier(probedSignals, getQuality())");
  });
});
