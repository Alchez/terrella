import { afterEach, describe, expect, it } from "vitest";

import "../styles/global.css";
import globalCss from "../styles/global.css?raw";
import baseLayout from "../layouts/Base.astro?raw";
import globePage from "../components/Globe.astro?raw";
import { BODIES, bodyFor, type BodySlug } from "./bodies";
// Its own module now, because `bodies.ts` is compiled by the tile Worker (via tileAddress.ts) and
// a `document` reference there fails that program. Tested from here anyway: the split is a runtime
// boundary, not a change of subject, and these cases are about the registry a slug resolves in.
import { currentBody } from "./currentBody";
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

/** Compare hex as a COLOUR, not a spelling: `palette.ts` is uppercase (its Python pin formats
 *  `%02X`), `global.css` is lowercase. CSS hex is case-insensitive, so case is not the invariant. */
function asColour(hex: string): string {
  return hex.trim().toLowerCase();
}

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
      expect(asColour(accentOf(slug)), `computed --accent for ${slug}`).toBe(
        asColour(BODIES[slug].accent.light),
      );
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
      expect(declaredAccents(slug).map(asColour), `global.css declarations for ${slug}`).toEqual([
        asColour(BODIES[slug].accent.light),
        asColour(BODIES[slug].accent.dark),
      ]);
    }
  });

  it("gives no body a token block the descriptor does not know about", () => {
    // The other direction. A block left behind by a removed body would be dead CSS that still
    // matched, so a stale `data-body` on a cached page would keep painting a planet that is gone.
    const styled = [...globalCss.matchAll(/:root\[data-body="([^"]+)"\]/g)].map((m) => m[1]);
    expect([...new Set(styled)].toSorted()).toEqual(Object.keys(BODIES).toSorted());
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

/**
 * Which body a page passes to `<Base>`, resolved from either spelling the site uses.
 *
 * A page may name the body outright (`body="mars"`) or take it from the descriptor it already
 * holds (`body={body.slug}`), and both are read here. A THIRD spelling is an ERROR rather than an
 * absence, for the reason the view bar's flag parser records: a miss and a genuine mismatch would
 * otherwise be the same value, and this guard's whole claim is that it read what the page ships.
 */
function resolveBodyProp(route: string, source: string): string {
  const attrs = /<Base\b([^>]*)>/.exec(source)?.[1];
  if (attrs === undefined) throw new Error(`${route} no longer opens with a <Base …> tag`);
  const literal = /\bbody="([^"]*)"/.exec(attrs)?.[1];
  if (literal !== undefined) return literal;
  const expression = /\bbody=\{([^}]*)\}/.exec(attrs)?.[1]?.trim();
  // The page names its body once in frontmatter and passes `.slug` down, so the answer is read
  // from the declaration rather than from the attribute — which is the half a rename would break.
  if (expression === "body.slug") {
    const named = /\bconst body = BODIES\.(\w+)\b/.exec(source)?.[1];
    if (named !== undefined) return named;
  }
  throw new Error(
    `${route}: cannot resolve body={${expression}}. Teach this guard about it — an unread ` +
      `expression would let a page dress itself in the wrong planet with nothing reporting it.`,
  );
}

describe("a body's slug is its route", () => {
  it("gives every body in the registry a page at its own slug", () => {
    // THE ACCEPTANCE CRITERION FOR THIS WHOLE DESCRIPTOR: adding a planet should be a registry
    // entry plus data, and this is the half a type cannot check. Astro routes by filename, so
    // `slug` and the page name are one fact stored in two places — add `mars` to the registry with
    // no `mars.astro` and the switcher would link at a 404, with every other gate green.
    //
    // `import.meta.glob` is resolved by Vite at build time, so this sees the real page directory
    // rather than a list someone maintained by hand.
    //
    // A DIRECTORY PER BODY, and the globe is that directory's `index.astro`. Astro routes
    // `earth.astro` and `earth/index.astro` to the same `/earth/`, so this is a filing decision
    // rather than a routing one: a body owns two pages now, and the flat spelling scattered them
    // across two places in the tree — `pages/earth.astro` beside `pages/earth/lite.astro`.
    const pages = Object.keys(import.meta.glob("../pages/**/*.astro"));
    // Prove the recursive glob resolves before trusting what it does not contain — every
    // expectation below is a lookup, so an empty list would fail loudly, but a list that stopped
    // recursing would report every body's globe missing and read as a routing catastrophe.
    expect(pages, "the page glob must actually resolve").toContain("../pages/about.astro");
    for (const slug of Object.keys(BODIES)) {
      expect(pages, `${slug} needs a globe at src/pages/${slug}/index.astro`).toContain(
        `../pages/${slug}/index.astro`,
      );
    }
  });

  it("gives every body's lite route a page to land on", () => {
    // THE OTHER HALF OF THE SLUG-IS-A-ROUTE RULE, and the half whose failure nobody would report.
    // The pre-paint guard redirects here BEFORE the page paints, and only for a visitor whose
    // device cannot run a globe — so a typo in `liteRoute` is a 404 on exactly the hardware we do
    // not develop on, reached with nothing on screen to say what happened.
    //
    // Recursive, unlike its sibling above: this route may be nested (`/mars/lite/`), and a
    // non-recursive glob would report the page missing rather than find it.
    const pages = Object.keys(import.meta.glob("../pages/**/*.astro"));
    // Prove the glob resolves before trusting an absence — the two routes below are looked UP in
    // this list, so an empty list would fail loudly, but a list missing only nested pages would
    // fail confusingly. Naming one file per depth says which.
    expect(pages.some((path) => path.endsWith("/pages/index.astro"))).toBe(true);
    expect(pages.some((path) => path.endsWith("/pages/mars/lite.astro"))).toBe(true);

    for (const [slug, descriptor] of Object.entries(BODIES)) {
      // `/` is `index.astro`; `/mars/lite/` is `mars/lite.astro`. Astro routes by filename, so the
      // route and the path are the same fact and this is the comparison that holds them together.
      const trimmed = descriptor.liteRoute.replace(/^\/|\/$/g, "");
      const expected = `../pages/${trimmed === "" ? "index" : trimmed}.astro`;
      expect(pages, `${slug}'s liteRoute ${descriptor.liteRoute} needs ${expected}`).toContain(
        expected,
      );
    }
  });

  it("dresses every page a body owns in that body, and not in the one next door", () => {
    // A SECOND GLOBE IS WHAT MAKES THIS REACHABLE. `mars.astro` is `earth.astro` with two words
    // changed, and the way to get it wrong is to change one of them: a page served at `/mars/` that
    // passes Earth's descriptor draws Mars's relief in Earth's teal, sends its Lite button to the
    // gallery, and steers a WebGL2-less visitor onto a planet they never asked for. Nothing else
    // compares a page's ROUTE to the body it dresses itself in, so all of that ships green.
    //
    // "Owns" is the route, not the subject. `[slug].astro` is a country page and passes
    // `body="earth"` because a country is Earth's; what is checked here is the narrower claim that
    // a page reachable UNDER a body's own path agrees with the body whose path it is.
    const sources = import.meta.glob("../pages/**/*.astro", {
      query: "?raw",
      import: "default",
      eager: true,
    }) as Record<string, string>;
    const owned = Object.entries(sources).flatMap(([path, source]) => {
      const route = path.replace("../pages/", "");
      const slug = Object.keys(BODIES).find(
        (candidate) => route === `${candidate}.astro` || route.startsWith(`${candidate}/`),
      );
      return slug === undefined ? [] : [{ route, source, slug }];
    });
    // One probe per KIND of page a body owns — its globe and its lite route — because the two are
    // written by different hands and a sweep that found only one of them would still look busy.
    const routes = owned.map((entry) => entry.route);
    expect(routes, "the sweep missed a body's globe").toContain("earth/index.astro");
    expect(routes, "the sweep missed a body's lite page").toContain("mars/lite.astro");

    for (const { route, source, slug } of owned) {
      expect(resolveBodyProp(route, source), `${route} is ${slug}'s route`).toBe(slug);
    }
  });

  it("has no page left at the route the globe used to live at", () => {
    // The rename was a move, not a copy. A leftover `globe.astro` would go on building and serving
    // a second, diverging globe at the old URL — reachable, stale, and invisible to every test that
    // reads the page by its new name.
    const names = Object.keys(import.meta.glob("../pages/*.astro")).map((p) => p.split("/").pop());
    // An absence check passes on an empty list, so prove the list is real first — otherwise a
    // broken glob would report "the old page is gone" about a directory it never read.
    expect(names, "the page glob must actually resolve").toContain("about.astro");
    expect(names).not.toContain("globe.astro");
    // Nor at the flat spelling each globe used to have. Astro routes `earth.astro` and
    // `earth/index.astro` to one URL, so a leftover is not a second route that someone would
    // notice — it is two files competing for `/earth/`, one of which stops being edited.
    for (const slug of Object.keys(BODIES)) {
      expect(names, `${slug}.astro should have moved into ${slug}/index.astro`).not.toContain(
        `${slug}.astro`,
      );
    }
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
