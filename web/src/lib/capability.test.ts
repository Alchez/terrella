import { describe, it, expect } from "vitest";
import { readFileSync } from "node:fs";
import {
  decideGlobeTier,
  decideTier,
  isLowMemory,
  isSlowNetwork,
  isSoftwareRenderer,
  LOW_MEMORY_GIB,
  SLOW_DOWNLINK_MBPS,
  canRunGlobe,
  type CapabilitySignals,
  type Quality,
} from "./capability";
import { BODIES, type BodySlug } from "./bodies";
import { bodyRoutes } from "./bodyRoutes";

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

  it("slow network → globe, NOT gallery (a slow link is not a reason to refuse the globe)", () => {
    // It used to return `gallery`, sharing a line with Save-Data. That made the module disagree
    // with `Base.astro`'s pre-paint guard, which consults `saveData` and has never consulted this:
    // the guard admitted a slow-network visitor to /earth/ and the module then declared the device
    // unable to run it. A slow link now buys what low memory buys — the globe minus what `full` adds.
    expect(decideTier(signals({ slowNetwork: true }), "auto")).toBe("globe");
  });

  it("Save-Data still outranks a slow network, because it is a stated preference", () => {
    // The asymmetry is the point: one is an explicit ask to spend fewer bytes, the other is an
    // estimate about the link. Only the first is allowed to cost someone the globe.
    expect(decideTier(signals({ saveData: true, slowNetwork: true }), "auto")).toBe("gallery");
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

describe("decideGlobeTier — `gallery` on a page already showing the globe is a contradiction", () => {
  it("clamps a soft demotion to globe, where plain decideTier says gallery", () => {
    // Save-Data is the live case: `Base.astro`'s pre-paint guard bounces on `quality === "lite"`
    // and on the hard floor, and has NEVER consulted saveData — so a Save-Data visitor who
    // deep-links /earth/ is admitted and was then told the device could not run it.
    expect(decideTier(signals({ saveData: true }), "auto")).toBe("gallery");
    expect(decideGlobeTier(signals({ saveData: true }), "auto")).toBe("globe");
  });

  it("does NOT clamp an explicit Lite — that is the visitor's own instruction", () => {
    expect(decideGlobeTier(signals(), "lite")).toBe("gallery");
  });

  it("does NOT clamp a failed hard floor — the device genuinely cannot, and the guard bounces it", () => {
    // The two verdicts that survive are exactly the two the guard acts on, so the module and the
    // guard cannot disagree. That agreement is the point of the function, not a side effect.
    expect(decideGlobeTier(signals({ webgl2: false }), "auto")).toBe("gallery");
    expect(decideGlobeTier(signals({ softwareGpu: true }), "auto")).toBe("gallery");
    expect(decideGlobeTier(signals({ performanceCaveat: true }), "auto")).toBe("gallery");
  });

  it("leaves every non-gallery verdict exactly as decideTier decided it", () => {
    // A clamp that also moved `globe` or `full` would be a second tier ladder, which is the thing
    // this file exists to avoid having two of.
    for (const overrides of [{}, { lowMemory: true }, { reducedMotion: true }, { slowNetwork: true }]) {
      const probed = signals(overrides);
      expect(decideGlobeTier(probed, "auto"), JSON.stringify(overrides)).toBe(
        decideTier(probed, "auto"),
      );
    }
  });

  it("keeps an explicit Globe/Full request behaving identically", () => {
    expect(decideGlobeTier(signals({ saveData: true }), "full")).toBe("full");
    expect(decideGlobeTier(signals({ webgl2: false }), "full")).toBe("gallery");
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
// seen the globe" — and a visitor who reached /earth any other way (deep link, or the view bar's
// Globe/Full button, which additionally cleared the flag) was hijacked straight back to the globe
// the moment they navigated to a lite page. The control that made that vivid was the globe's
// `← Gallery` link, since deleted; the flag's meaning is what these pin, not that link.
const guardSource = (() => {
  const base = readFileSync(new URL("../layouts/Base.astro", import.meta.url), "utf8");
  const inlineScripts = [...base.matchAll(/<script is:inline>([\s\S]*?)<\/script>/g)].map(
    (match) => match[1],
  );
  const guard = inlineScripts.find((script) => script.includes("rg:steered"));
  if (!guard) throw new Error("Base.astro no longer has an inline script mentioning rg:steered");
  return guard;
})();

/** A Storage-shaped view over a plain Map, for handing the inline guard a localStorage it can
 *  read and write without a DOM. Only the three members that guard actually calls. */
const storage = (backing: Map<string, string>) => ({
  getItem: (key: string) => backing.get(key) ?? null,
  setItem: (key: string, value: string) => void backing.set(key, value),
  removeItem: (key: string) => void backing.delete(key),
});

interface GuardVisit {
  /** What the landed-on page says it IS — `Base.astro`'s `pageRole`, stamped on `<html>`.
   *
   *  THERE IS NO `path` HERE ANY MORE, AND THAT IS THE POINT OF THE ROLE. The guard used to decide
   *  which of a body's two pages you were on by comparing `location.pathname` against the registry,
   *  so every case below had to name a URL and the suite carried a table of trailing-slash
   *  spellings to prove the comparison agreed with `isSamePath`. A page that declares itself needs
   *  neither: `/earth` and `/earth/` are one page and say so, and Earth's lite content can answer
   *  at both `/` and `/earth/lite/` without the guard having to be taught about aliases.
   *
   *  `location` is still handed in, because the guard still NAVIGATES — it just no longer reads. */
  role?: string;
  /** Which body's page the visit lands on, i.e. what `Base.astro` stamped on `<html>`.
   *
   *  THE WHOLE REASON THE GUARD IS TESTABLE FOR A SECOND BODY BEFORE ONE HAS A GLOBE. The guard
   *  reads its two routes off attributes rather than matching a literal path, so a test can hand it
   *  Mars's and watch it steer — no Mars globe, no Mars page, nothing on disk. Had the routes stayed
   *  inside the guard, the only way to exercise them would have been to ship the thing they route
   *  to, and the bug would have been found by looking at it. */
  body?: BodySlug;
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
  role = "lite",
  body = "earth",
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
  // From the real registry, not spelled out here: the values under test are the ones the layout
  // will stamp, so a route that changes there changes what the guard is driven with.
  const routes = bodyRoutes(body);
  const attributes: Record<string, string> = {
    "data-body": body,
    "data-page-role": role,
    "data-globe-route": routes.globe,
    "data-lite-route": routes.lite,
  };

  new Function(
    "location",
    "localStorage",
    "sessionStorage",
    "navigator",
    "document",
    "matchMedia",
    guardSource,
  )(
    // No `pathname`: if the guard ever starts reading one again, every case here reports it as an
    // exception rather than as a quietly different verdict.
    { replace: (url: string) => redirects.push(url) },
    storage(local),
    storage(session),
    { connection: { saveData } },
    {
      documentElement: { getAttribute: (name: string) => attributes[name] ?? null },
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
    expect(visit({ role: "lite" })).toEqual({ redirects: ["/earth/"], steered: true });
  });

  it("steers only once per session, so a deliberate return to the gallery sticks", () => {
    expect(visit({ role: "lite", steered: true }).redirects).toEqual([]);
  });

  it("leaves the gallery alone when the visitor forced Lite", () => {
    expect(visit({ role: "lite", quality: "lite" }).redirects).toEqual([]);
  });

  it("leaves the gallery alone without WebGL2, whatever the saved quality", () => {
    expect(visit({ role: "lite", quality: "full", webgl2: false }).redirects).toEqual([]);
  });

  it("respects data-saver on auto, but not against an explicit choice", () => {
    expect(visit({ role: "lite", saveData: true }).redirects).toEqual([]);
    expect(visit({ role: "lite", quality: "full", saveData: true }).redirects).toEqual(["/earth/"]);
  });
});

describe("Base.astro tier guard — rg:steered means 'this session has seen the globe'", () => {
  // The regression the flag's old meaning caused, one test per way onto the globe.
  it("marks the session steered when the globe is reached by deep link", () => {
    expect(visit({ role: "globe" })).toEqual({ redirects: [], steered: true });
  });

  it("does NOT mark it when the globe refuses to render, since it was never seen", () => {
    expect(visit({ role: "globe", quality: "lite" })).toEqual({ redirects: ["/earth/lite/"], steered: false });
    expect(visit({ role: "globe", webgl2: false })).toEqual({ redirects: ["/earth/lite/"], steered: false });
  });

  it("lets a lite page hold a visitor who has already seen a globe this session", () => {
    // The reported bug, end to end: the flag written by visit one must survive into visit two.
    // Reachable today by a lite page's own back link, or by any external link into `/` mid-session.
    const globeVisit = visit({ role: "globe" });
    expect(globeVisit.steered).toBe(true);
    expect(visit({ role: "lite", steered: globeVisit.steered }).redirects).toEqual([]);
  });

  it("never clears the flag — clearing it is what re-armed the hijack", () => {
    const base = readFileSync(new URL("../layouts/Base.astro", import.meta.url), "utf8");
    expect(base).not.toMatch(/removeItem\(\s*["']rg:steered["']\s*\)/);
  });

  it("marks a session steered on ANY body's globe, so `/` holds a visitor arriving from Mars", () => {
    // The flag is one key across bodies because it means "this session has seen a globe", and `/`
    // is Earth's lite content whichever planet you came from. Written per body, a Mars visitor
    // reaching the gallery would be steered straight back to EARTH's globe — a different planet,
    // before paint, with nothing on screen to say one had been chosen for them.
    const marsVisit = visit({ role: "globe", body: "mars" });
    expect(marsVisit).toEqual({ redirects: [], steered: true });
    expect(visit({ role: "lite", steered: marsVisit.steered }).redirects).toEqual([]);
  });
});

describe("Base.astro tier guard — a second body's globe is guarded like the first", () => {
  // WHAT THIS COMMIT EXISTS FOR. The guard used to match the literal `/earth`, so on any other
  // body's globe every branch was skipped: a device with no WebGL2 was left sitting on a map it
  // could not draw, and nothing anywhere reported it. These run today, with no Mars globe built.
  it("bounces a Lite visitor off Mars's globe to MARS's fallback, not Earth's", () => {
    expect(visit({ role: "globe", body: "mars", quality: "lite" })).toEqual({
      redirects: ["/mars/lite/"],
      steered: false,
    });
  });

  it("bounces a device that cannot run a globe at all", () => {
    expect(visit({ role: "globe", body: "mars", webgl2: false }).redirects).toEqual([
      "/mars/lite/",
    ]);
  });

  it("steers a capable visitor from Mars's fallback onto Mars's globe", () => {
    expect(visit({ role: "lite", body: "mars" })).toEqual({
      redirects: ["/mars/"],
      steered: true,
    });
  });

  it("leaves a Lite visitor on Mars's fallback", () => {
    expect(visit({ role: "lite", body: "mars", quality: "lite" }).redirects).toEqual([]);
  });

  it("never sends a Mars visitor to Earth, on any of the four outcomes", () => {
    // The failure mode stated as its own assertion, because each case above only checks one
    // destination: a control that answers "your device cannot draw Mars" by showing you a
    // different planet is the specific wrong that the literal `/earth` produced.
    const outcomes = [
      visit({ role: "globe", body: "mars", quality: "lite" }),
      visit({ role: "globe", body: "mars", webgl2: false }),
      visit({ role: "lite", body: "mars" }),
      visit({ role: "lite", body: "mars", saveData: true }),
    ];
    expect(outcomes.flatMap((outcome) => outcome.redirects).join(" ")).not.toMatch(/earth/);
  });

  it("reads both trailing-slash spellings of a body's globe", () => {
    // Astro serves `/mars` and `/mars/` alike, so an `===` against one of them is a guard that
    // works for everyone who arrives the way we happened to test.
    expect(visit({ role: "globe", body: "mars", quality: "lite" }).redirects).toEqual([
      "/mars/lite/",
    ]);
    expect(visit({ role: "lite", body: "mars" }).redirects).toEqual(["/mars/"]);
  });

  it("leaves a page that is neither of a body's two alone, whatever body it dresses in", () => {
    for (const slug of Object.keys(BODIES) as BodySlug[]) {
      expect(visit({ role: "plain", body: slug }).redirects, `${slug} plain`).toEqual([]);
      // And on anything it does not recognise. The dispatch is an allowlist rather than a
      // "not globe → treat as lite" test, so a role that is misspelled, renamed upstream, or
      // absent because the attribute stopped rendering leaves the visitor where they are —
      // rather than steering every country page onto the globe.
      expect(visit({ role: "gallery", body: slug }).redirects, `${slug} typo`).toEqual([]);
    }
  });

  it("sends every body to the fallback that body advertises", () => {
    // The loop rather than two literals, so a third planet added by copying a row is caught here
    // and not by a visitor on a phone that cannot run its globe.
    for (const slug of Object.keys(BODIES) as BodySlug[]) {
      const routes = bodyRoutes(slug);
      expect(
        visit({ role: "globe", body: slug, quality: "lite" }).redirects,
        `${slug} bounced off its globe`,
      ).toEqual([routes.lite]);
      expect(
        visit({ role: "lite", body: slug }).redirects,
        `${slug} steered off its fallback`,
      ).toEqual([routes.globe]);
    }
  });
});

describe("every page tells the guard what it is, and tells it the truth", () => {
  // WHAT REPLACED A TABLE OF PATH SPELLINGS. This suite used to drive the guard at `/earth`,
  // `/earth/`, `/earth//` and seven more, and assert its verdict matched `isSamePath` — because the
  // guard carried its own copy of that rule and a drifted copy would put the pre-paint redirect and
  // the view bar's tier picker on different pages. That duplication is gone: the guard is told what
  // the page is, so spelling cannot reach it and there is nothing left to drift.
  //
  // The risk moved rather than vanishing. A page can now LIE — and a page that calls a globe a lite
  // route steers a capable visitor in a loop, while one that calls a lite route plain leaves a
  // device with no WebGL2 sitting on a map it cannot draw. The type only insists an answer is
  // given; this insists it is the right one.
  //
  // Two of the three claims are derived from the registry. The third is not derivable by anything,
  // and that is exactly why it is asserted: `/` renders Earth's lite content because the gallery
  // was the front page before there was a second body to need a route name.
  const PAGES = new URL("../pages/", import.meta.url);
  const declaredRole = (route: string) => {
    const source = readFileSync(new URL(route, PAGES), "utf8");
    const attributes = /<Base\b([^>]*)>/.exec(source)?.[1];
    if (attributes === undefined) throw new Error(`${route} no longer opens with a <Base …> tag`);
    const role = /\bpageRole="([^"]*)"/.exec(attributes)?.[1];
    // An ERROR rather than an absence, for the reason `resolveBodyProp` next door gives: a miss and
    // a genuine mismatch would otherwise be the same value, and the whole claim here is that this
    // read what the page ships.
    if (role === undefined) throw new Error(`${route} declares no literal pageRole`);
    return role;
  };

  for (const slug of Object.keys(BODIES) as BodySlug[]) {
    it(`calls ${slug}'s globe a globe`, () => {
      expect(declaredRole(`${slug}/index.astro`)).toBe("globe");
    });

    it(`calls ${slug}'s lite route a lite page`, () => {
      // Off the registry rather than written out, so a body whose lite route moves takes its
      // declaration with it or fails here — which is the half of this commit that had no guard.
      expect(declaredRole(`${bodyRoutes(slug).lite.replace(/^\/|\/$/g, "")}.astro`)).toBe("lite");
    });
  }

  it("calls the site root a lite page, which no registry field can tell it", () => {
    expect(declaredRole("index.astro")).toBe("lite");
  });

  it("keeps the pages that are neither out of the guard's way", () => {
    expect(declaredRole("about.astro")).toBe("plain");
    expect(declaredRole("[slug].astro")).toBe("plain");
  });
});

describe("Base.astro stamps the guard's inputs onto the page", () => {
  // The guard reads its routes off `<html>`, and an attribute that stopped being rendered would
  // take every branch above out of service SILENTLY — the guard is wrapped in `try/catch` so it can
  // never break a page, which also means it can never complain. The harness above supplies the
  // attributes itself, so it cannot see this; only the layout's own source can.
  const base = readFileSync(new URL("../layouts/Base.astro", import.meta.url), "utf8");
  // ANCHORED AT COLUMN 0, and that is not stylistic. An unanchored match found the tag quoted in
  // this layout's own prose — the "a source scan matches its own documentation" trap, on its first
  // outing here — and read a comment's `<html>` as the element. The real one is a top-level node in
  // the template, so it is the only one that can begin a line.
  const rootTags = base.match(/^<html[^>]*>/gm) ?? [];

  it("renders exactly one root element, which is what the check below assumes", () => {
    expect(rootTags).toHaveLength(1);
  });

  it("puts the body and both of its routes on that element", () => {
    // One case rather than three, and the title is static on purpose: the mutation table matches a
    // guard by its exact `it(...)` string, so a title built from a loop variable names a test that
    // cannot be found — and the case would be recorded as covering something nothing runs.
    for (const attribute of ["data-body", "data-globe-route", "data-lite-route"]) {
      expect(rootTags[0], `the root element must carry ${attribute}`).toContain(`${attribute}={`);
    }
  });

  it("takes both routes from the registry rather than writing them out", () => {
    // `bodyRoutes(body)` and nothing else: a literal here would be a third copy of a fact the
    // registry already holds, and it would be correct on the day it was written.
    expect(base).toMatch(/const routes = bodyRoutes\(body\);/);
  });
});

describe("Base.astro view bar sends a visitor to THIS body's pages", () => {
  // A SOURCE SCAN, AND ONLY BECAUSE NOTHING ELSE CAN REACH IT. The tier picker is a module script
  // inside the layout: no export, no entry point, and its whole effect is a navigation. The guard
  // above is testable because its source can be extracted and run; this one is testable by what it
  // says. Both destinations were `"/"` and `"/earth/"` until this commit, which is how Globe and
  // Full on Mars came to navigate to Earth.
  const base = readFileSync(new URL("../layouts/Base.astro", import.meta.url), "utf8");

  it("takes both tier destinations from the body's own routes", () => {
    expect(base).toMatch(/const target = choice === "lite" \? routes\.lite : routes\.globe;/);
  });

  it("asks the registry which body it is dressed in, rather than reading the path", () => {
    expect(base).toMatch(/const routes = bodyRoutes\(currentBody\(\)\.slug\);/);
  });

  it("decides 'am I already there' with the comparison the guard uses", () => {
    // `===` against one trailing-slash spelling reloaded nothing and navigated to the page it was
    // already on — cheap to miss, since both outcomes end up displaying the right page.
    expect(base).toMatch(/isSamePath\(location\.pathname, target\)/);
    expect(base).toMatch(/isSamePath\(location\.pathname, routes\.globe\)/);
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
    const globe = readFileSync(new URL("../components/Globe.astro", import.meta.url), "utf8");
    // Keyed on the fact rather than on one spelling — the twin of this detector is in
    // terrainSource.test.ts, and both went red together when `currentTier()` was hoisted to a
    // `bootTier` const, which is the drift signal working rather than a defect.
    const gate = globe.match(
      // The trailing `(?:,[^)]*)?` is not decoration: this matcher was anchored on the call taking
      // exactly TWO arguments, and it broke the day a third (the body) was added without a single
      // character of the tier expression changing. An arity is not the property under test.
      /resolveTerrainExaggeration\(\s*urlFlags\s*,\s*([\w$]+(?:\(\))?)\s*===\s*"full"\s*(?:,[^)]*)?\)/,
    );
    const tierExpression = gate?.[1] ?? "";
    // `decide(Globe)?Tier` — both spellings are the tier decision. `decideGlobeTier` wraps
    // `decideTier` to clamp a soft `gallery` verdict on a page already showing the globe, so a
    // const built from it rides the tier exactly as much as one built from the other. Matching
    // only the narrow spelling turned this green-by-accident in the "don't claim terrain"
    // direction the moment the globe page adopted the wrapper.
    const terrainRidesOnTier =
      tierExpression === "currentTier()" ||
      tierExpression === "currentGlobeTier()" ||
      (tierExpression !== "" &&
        new RegExp(`const\\s+${tierExpression}\\s*=\\s*decide(?:Globe)?Tier\\(`).test(globe));
    const fullTooltip = base.match(/data-quality="full"[\s\S]*?title="([^"]+)"/)?.[1] ?? "";
    expect(fullTooltip, "the Full button must carry a tooltip at all").not.toBe("");
    if (terrainRidesOnTier) {
      expect(fullTooltip.toLowerCase()).toContain("terrain");
    } else {
      expect(fullTooltip.toLowerCase()).not.toContain("terrain");
    }
  });

});

// --- The signals the probe reads, pulled out so they are testable at all -----------------------

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

describe("isSlowNetwork — zero is 'not estimated yet', and it used to cost a visitor the globe", () => {
  it("does NOT treat zero as slow — a cold load has no estimate, not a slow link", () => {
    // The defect this replaces. `downlink` is built from observed traffic, so a browser that has
    // not moved enough bytes reports 0 — which is the state `probeSignals` runs in. The old
    // `downlink < 1.5` read that as slower than 1.5 Mbps and `decideTier` sent it to `gallery`.
    // Measured live: a Lighthouse session on a fresh profile reports 0 and produced `tier gallery`
    // on a page rendering the globe at 243 fps, having already pulled 37 tiles.
    expect(isSlowNetwork("4g", 0)).toBe(false);
    expect(decideTier({ ...healthy, slowNetwork: isSlowNetwork("4g", 0) }, "auto")).toBe("full");
  });

  it("does NOT treat an absent value as slow — the same optimism isLowMemory applies", () => {
    expect(isSlowNetwork(undefined, undefined)).toBe(false);
    expect(isSlowNetwork("4g", undefined)).toBe(false);
  });

  it("still catches a genuinely slow link, so the guard did not disarm the signal", () => {
    // 0 is excused because it is not a measurement. Anything the estimator actually produced is.
    expect(isSlowNetwork("4g", 0.5)).toBe(true);
    expect(isSlowNetwork("4g", 1.4)).toBe(true);
    // `globe`, not `gallery` — the signal still fires, it just no longer refuses the globe.
    expect(decideTier({ ...healthy, slowNetwork: isSlowNetwork("4g", 0.5) }, "auto")).toBe("globe");
  });

  it("brackets the threshold, and records how little headroom a real desktop has", () => {
    // This project's dev box, on fibre, reports 1.6 — one tenth of a megabit clear of the line.
    // If that number ever drifts under, healthy desktops start landing in the gallery, so the
    // margin is pinned here rather than left as a remark in a docstring.
    expect(isSlowNetwork("4g", SLOW_DOWNLINK_MBPS)).toBe(false);
    expect(isSlowNetwork("4g", SLOW_DOWNLINK_MBPS - 0.1)).toBe(true);
    expect(isSlowNetwork("4g", 1.6)).toBe(false);
    expect(SLOW_DOWNLINK_MBPS).toBeLessThan(1.6);
  });

  it("reads effectiveType independently, so an unmeasured 2g link is still slow", () => {
    // The bucketed signal survives when the measured one does not — which is what makes excusing
    // zero safe rather than a blanket promotion.
    expect(isSlowNetwork("slow-2g", 0)).toBe(true);
    expect(isSlowNetwork("2g", undefined)).toBe(true);
    expect(isSlowNetwork("3g", 0)).toBe(false);
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
  it("bounces a software-rasterizer visitor who deep-links /earth", () => {
    // Previously the guard tested WebGL2 alone, so this visitor rendered the globe while the
    // page module was independently deciding "gallery" — the two disagreed on the same device.
    const outcome = visit({ role: "globe", unmaskedRenderer: "Google SwiftShader" });
    expect(outcome.redirects).toEqual(["/earth/lite/"]);
  });

  it("bounces one whose only renderer string is the standard parameter (Firefox)", () => {
    const outcome = visit({
      role: "globe",
      unmaskedRenderer: null, // no WEBGL_debug_renderer_info
      renderer: "llvmpipe (LLVM 15.0.7, 256 bits)",
    });
    expect(outcome.redirects).toEqual(["/earth/lite/"]);
  });

  it("does not steer a software-rasterizer visitor onto the globe from the gallery", () => {
    const outcome = visit({ role: "lite", unmaskedRenderer: "llvmpipe (LLVM 15.0.7, 256 bits)" });
    expect(outcome.redirects).toEqual([]);
    expect(outcome.steered).toBe(false);
  });

  it("still steers a real GPU — the control that stops the three above passing vacuously", () => {
    const outcome = visit({ role: "lite", unmaskedRenderer: "Apple M2 Pro" });
    expect(outcome.redirects).toEqual(["/earth/"]);
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
          role: "lite",
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

describe("the scripted-diagnosis seam is gated by the module boundary", () => {
  const globe = readFileSync(new URL("../components/Globe.astro", import.meta.url), "utf8");
  const overlay = readFileSync(new URL("./perf/perfOverlay.ts", import.meta.url), "utf8");

  it("lives in the lazily-imported instrument, so an ordinary visit cannot reach it", () => {
    // The gate is that perfOverlay loads only inside the ?perf branch, so a visitor without the flag
    // never downloads this module at all. The import SHAPE is not re-checked here: `lib/perf/`'s own
    // lazyBoundary.test.ts owns that rule for the whole directory, and a duplicate of it here was
    // silently vacuous for its entire life — anchored `^import` against Astro's indented imports, so
    // it matched nothing and passed by finding nothing.
    expect(overlay).toContain("window.terrella = {");
    expect(globe).toMatch(/if \(urlFlags\.has\("perf"\)\)/);
    expect(globe).toContain('import("../lib/perf/perfOverlay")');
  });

  it("is not also written from the page, where nothing structural would gate it", () => {
    // The first version of this seam DID live in earth.astro behind the flag, guarded by a test
    // asserting the assignment appeared within the flag block's text span. A sabotage that closed
    // the block early and re-opened it after the assignment passed that test: the statement was
    // outside the gate and still inside the span. A region match cannot decide what encloses a
    // statement, so the gate moved to the module boundary and this asserts the page stays clean.
    //
    // KEYED TO THE SHAPE, NOT TO A NAME, and that is the correction this assertion carries. It
    // used to name one handle — so when a SECOND handle for the same map was added to this page
    // under a different name, it passed without noticing, and that duplicate shipped assigned
    // twice with its own flag gate dead from the day it landed. Both spellings were correct where
    // they sat; nothing could go red. A guard that names its subject cannot see the same defect
    // arrive under another name, so this one asks the question the concept asks: does the page
    // hand the live map to a global at all?
    const pageHandles = [...globe.matchAll(/window\.(\w+)\s*=\s*map\b/g)].map((match) => match[1]);
    expect(pageHandles, "the map seam belongs behind the module boundary").toEqual([]);
  });
});

describe("probeSignals is a GPU allocation, and callers must treat it as one", () => {
  const capability = readFileSync(new URL("./capability.ts", import.meta.url), "utf8");
  const globe = readFileSync(new URL("../components/Globe.astro", import.meta.url), "utf8");

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
    // A RUNAWAY DETECTOR, not a size budget — Globe.astro is ~100 KB, so anything that escaped the
    // composer overshoots this by an order of magnitude. Bumped once, when the report gained
    // `probedTier`; bump it again for a legitimate growth rather than trimming the composer to fit.
    expect(compose!.length, "matched a runaway span, not the composer").toBeLessThan(4000);
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
    // BOTH fields, because the report now carries the clamped tier and the raw probe verdict, and
    // a stale `probedTier` is the worse of the two to have: it is the field that exists purely to
    // disagree, so a frozen copy of it would agree forever and read as "nothing to see".
    expect(globe).toContain("tier: decideGlobeTier(probedSignals, getQuality())");
    expect(globe).toContain("probedTier: decideTier(probedSignals, getQuality())");
  });
});
