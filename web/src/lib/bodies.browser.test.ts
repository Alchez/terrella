import { afterEach, describe, expect, it } from "vitest";

import "../styles/global.css";
import globalCss from "../styles/global.css?raw";
import baseLayout from "../layouts/Base.astro?raw";
import globePage from "../pages/globe.astro?raw";
import { BODIES, bodyFor, currentBody, type BodySlug } from "./bodies";
import { DEEP_SEA } from "./palette";

/**
 * The accent is declared once, per body, and selected by an attribute on `<html>`.
 *
 * Two halves of one claim live here, deliberately. The stylesheet says a colour and the descriptor
 * says the same colour; the SOURCE half checks they agree, and the COMPUTED half checks that what
 * the browser resolves from the cascade is that colour and not something the source read like. A
 * source scan alone would be reassembling a document the browser never builds — it can prove a rule
 * was written and nothing about whether it wins.
 *
 * The failure this guards is specific: `--accent` has no bare `:root` declaration any more, so a
 * page that reaches the stylesheet without `data-body` has no accent at all. That is the intended
 * design (a missing body must be visible, not silently Earth), and it means the attribute is now
 * load-bearing for every link, button and heading rule on the site.
 */

/** The real element the tokens are declared on. Restored after each test — leaving a stray
 *  attribute on the document root would leak into every file that runs after this one. */
const root = document.documentElement;
const originalBody = root.getAttribute("data-body");

afterEach(() => {
  if (originalBody === null) root.removeAttribute("data-body");
  else root.setAttribute("data-body", originalBody);
});

function accentOf(slug: string | null): string {
  if (slug === null) root.removeAttribute("data-body");
  else root.setAttribute("data-body", slug);
  return getComputedStyle(root).getPropertyValue("--accent").trim();
}

/** The declarations for one body, light scheme and dark, read out of the shipped stylesheet.
 *
 *  Written as a scan for the body's own selector rather than for a hex, so a colour moved between
 *  two bodies' blocks reads as a change here instead of as "the file still contains that string". */
function declaredAccents(slug: BodySlug): string[] {
  const pattern = new RegExp(
    `:root\\[data-body="${slug}"\\]\\s*\\{[^}]*?--accent:\\s*([^;]+);`,
    "g",
  );
  return [...globalCss.matchAll(pattern)].map((match) => match[1].trim());
}

describe("the accent comes from the body descriptor", () => {
  it("computes the descriptor's colour for every body the site knows", () => {
    // The load-bearing assertion: the cascade, not the file. `getComputedStyle` on the element the
    // token is declared on is what every `var(--accent)` in the sheet resolves against.
    for (const slug of Object.keys(BODIES) as BodySlug[]) {
      expect(accentOf(slug), `computed --accent for ${slug}`).toBe(BODIES[slug].accent.light);
    }
  });

  it("leaves the accent undefined when no body is declared, rather than defaulting to Earth", () => {
    // The negative control, and the reason the design is safe: drop the attribute and the accent is
    // GONE, loudly, on the first page that loads. Without this the first assertion would pass just
    // as happily against a bare `:root { --accent }` fallback that made the attribute decorative.
    expect(accentOf(null)).toBe("");
    expect(accentOf("mercury")).toBe(""); // a body the stylesheet has never heard of
  });

  it("declares both schemes for every body, matching the descriptor exactly", () => {
    // The source half. Both entries, in order: the `:root` block then the dark-scheme override.
    // `prefers-color-scheme` cannot be flipped from inside the page, so the dark value is the one
    // claim here that only a source scan can reach — stated as such rather than implied.
    for (const slug of Object.keys(BODIES) as BodySlug[]) {
      expect(declaredAccents(slug), `global.css declarations for ${slug}`).toEqual([
        BODIES[slug].accent.light,
        BODIES[slug].accent.dark,
      ]);
    }
  });

  it("gives no body a token block the descriptor does not know about", () => {
    // The other direction. A block left behind by a removed body would be dead CSS that still
    // matched, so a stale `data-body` on a cached page would keep painting a planet that is gone.
    const styled = [...globalCss.matchAll(/:root\[data-body="([^"]+)"\]/g)].map((m) => m[1]);
    expect([...new Set(styled)].sort()).toEqual(Object.keys(BODIES).sort());
  });
});

describe("the layout writes the body onto the element the tokens are declared on", () => {
  it("renders data-body on <html>, server-side and unconditionally", () => {
    // `:root` IS `<html>`. Put on `<body>` instead, every one of these rules would stop matching
    // and the whole site would lose its accent — a mistake with no compiler and no type to catch
    // it, because both spellings are valid Astro.
    expect(baseLayout).toMatch(/<html[^>]*\bdata-body=\{body\}/);
  });

  it("takes the body as a required prop with no default", () => {
    // `astro check` enforces the requirement at every call site; this asserts the shape it checks
    // against has not quietly gained a default, which would make the check pass and the guard moot.
    expect(baseLayout).toMatch(/\n {2}body: BodySlug;/);
    expect(baseLayout).not.toMatch(/body = ["']/);
  });
});

describe("the page resolves which body it draws from that same attribute", () => {
  it("returns the declared body's descriptor", () => {
    // One declaration serving both the stylesheet and the script is the point of putting it on
    // <html>: a `define:vars` would have given the script a body the CSS could not see, and the two
    // could then disagree about which planet the page is.
    root.setAttribute("data-body", "earth");
    expect(currentBody()).toBe(BODIES.earth);
  });

  it("throws when the layout declared nothing, rather than assuming Earth", () => {
    root.removeAttribute("data-body");
    expect(() => currentBody()).toThrow(/no data-body/);
  });

  it("throws on a body the site cannot draw", () => {
    root.setAttribute("data-body", "mercury");
    expect(() => currentBody()).toThrow(/unknown body "mercury"/);
  });
});

describe("the globe's space-floor is the body's colour, not a constant", () => {
  it("paints the background layer from the descriptor", () => {
    // The layer exists so a gap reads as more of this planet rather than as a hole to space. Wired
    // to a fixed colour it does the opposite for every body but the one it was written for: Earth's
    // abyssal teal under a missing Martian tile reads as data loss, which is the exact impression
    // the layer was added to prevent.
    expect(globePage).toMatch(
      /id: "space-floor", type: "background", paint: \{ "background-color": body\.spaceFloor \}/,
    );
  });

  it("no longer reaches past the descriptor for the raw palette constant", () => {
    // Both the import and the use. Leaving the import behind would let the old constant be
    // reintroduced at a second call site without anything noticing.
    expect(globePage).not.toContain("DEEP_SEA");
  });

  it("takes Earth's floor from the pipeline's own stop rather than a third copy of the hex", () => {
    // palette.ts restates the pipeline's ramp and is pinned against it by tests/test_palette.py.
    // Retyping the hex here would be a copy with nothing comparing it back to the sea it matches —
    // which is precisely how WATER_RGB drifted 15% brighter than the surface it was meant to be.
    expect(BODIES.earth.spaceFloor).toBe(DEEP_SEA);
  });
});

describe("the registry refuses a body it does not know", () => {
  it("throws and names the ones that exist, rather than falling back", () => {
    expect(() => bodyFor("mercury")).toThrow(/unknown body "mercury".*earth/);
  });

  it("keys every descriptor by its own slug", () => {
    // One body, two spellings, is two bodies to everything downstream — the directory, the archive
    // key and the route are all this one word.
    for (const [key, descriptor] of Object.entries(BODIES)) {
      expect(descriptor.slug).toBe(key);
    }
  });
});
