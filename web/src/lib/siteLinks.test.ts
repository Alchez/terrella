import { describe, expect, it } from "vitest";
import { readdirSync, readFileSync } from "node:fs";
import { REPO_URL } from "./siteLinks";

const PAGES_ROOT = new URL("../pages/", import.meta.url);
const page = (name: string) => readFileSync(new URL(name, PAGES_ROOT), "utf8");
/** Every page, walked rather than listed — see the no-literals rule below for why that matters. */
const ALL_PAGES: [string, string][] = readdirSync(PAGES_ROOT, { recursive: true })
  .filter((name): name is string => typeof name === "string" && name.endsWith(".astro"))
  .map((name) => [name, page(name)]);
/** The globe is a COMPONENT, not a page: `pages/earth/index.astro` is the `<Base>` wrapper around it,
 *  and everything asserted below — the credit control, the chrome row, the repo link — is here. */
const globe = readFileSync(new URL("../components/Globe.astro", import.meta.url), "utf8");
/** The globe's global stylesheet, which it imports — the rules that reach MapLibre's widgets. */
const globeStyles = readFileSync(new URL("../styles/globe.css", import.meta.url), "utf8");

/** The gallery is a COMPONENT too, for the same reason the globe is: `pages/index.astro` and
 *  `pages/earth/lite.astro` are both `<Base>` wrappers around it, so the masthead that carries this
 *  link is in neither of them. */
const gallery = readFileSync(new URL("../components/Gallery.astro", import.meta.url), "utf8");

/** The two views that carry a link back to the repository, each named by the file that draws it. */
const LINKED_VIEWS: [string, string][] = [
  ["Gallery.astro", gallery],
  ["Globe.astro", globe],
];

describe("the repository link", () => {
  it("is an absolute https URL, since it is rendered into an href verbatim", () => {
    expect(() => new URL(REPO_URL)).not.toThrow();
    expect(new URL(REPO_URL).protocol).toBe("https:");
    expect(new URL(REPO_URL).host).toBe("github.com");
  });

  it("reaches both views the user asked for", () => {
    // Named by the SOURCE that draws each view rather than by its route: the globe's link moved
    // into the component with the rest of its chrome, and `pages/earth/index.astro` is now a
    // wrapper that would satisfy neither assertion and pass the absence one below for free.
    //
    // THAT HAS NOW HAPPENED TWICE, which is what makes it a rule rather than an anecdote. The
    // gallery moved the same way when Earth's lite route needed a second URL to render it, and a
    // route named here would have gone on reading a file whose entire content is two imports.
    for (const [view, source] of LINKED_VIEWS) {
      expect(source, `${view} no longer imports the constant`).toContain('from "../lib/siteLinks"');
      expect(source, `${view} no longer uses it`).toContain("REPO_URL");
    }
  });

  it("is never inlined as a literal, which is the drift this constant exists to stop", () => {
    // A renamed repo or moved org would 404 silently — nothing in a build can see it.
    //
    // WALKED, NOT LISTED. This was four names, and a name list stops covering the site the moment
    // the site grows a page — which it does per body, and a body's globe is exactly where someone
    // pastes a repo URL. A page nobody checks cannot fail this, so the list going stale and the
    // rule being obeyed produce the same green.
    expect(ALL_PAGES.map(([name]) => name), "the walk did not recurse").toContain("mars/lite.astro");
    expect(ALL_PAGES.length, "the walk found no pages").toBeGreaterThan(0);
    const everywhere: [string, string][] = [...LINKED_VIEWS, ...ALL_PAGES];
    for (const [view, source] of everywhere) {
      expect(source, `${view} inlines the URL`).not.toContain("github.com/Alchez");
    }
  });

  it("opens externally without handing the opener over", () => {
    // target=_blank without rel=noopener gives the new tab window.opener on older engines.
    for (const [view, source] of LINKED_VIEWS) {
      const blankLinks = source.match(/target="_blank"/g) ?? [];
      const guarded = source.match(/rel="noopener noreferrer"/g) ?? [];
      expect(guarded.length, `${view} has an unguarded _blank link`).toBeGreaterThanOrEqual(
        blankLinks.length,
      );
    }
  });
});

// The on-map credit, which is the one link on the site carrying a licence obligation rather than
// a convenience. It is folded into the centred view bar, but it is still MapLibre's own control.
describe("the on-map credit", () => {

  it("stays a real AttributionControl, so a new source's credit still appears by itself", () => {
    // Hand-rolled markup would look identical today and silently omit the credit of whichever
    // source is added next: _updateAttributions walks every used tile manager and appends any
    // `attribution` it finds. That safety net only runs if the control exists. (The Map is still
    // constructed with attributionControl:false — that suppresses the DEFAULT one so this
    // explicitly-configured instance can replace it, which is not the same as having none.)
    expect(globe.match(/new maplibregl\.AttributionControl\(/g)).toHaveLength(1);
  });

  it("is constructed with compact:false, which is what keeps the ⓘ off the page", () => {
    // Omitting the option, or passing true, lets _updateCompact add `maplibregl-compact` at or
    // below 640 px — which reveals the <summary> button. Its glyph is a baked-in BLACK SVG
    // background-image, invisible on this theme and not recolourable from CSS. The constructor
    // option is the fix; a stylesheet override is not.
    expect(globe).toMatch(/new maplibregl\.AttributionControl\(\{\s*compact:\s*false\s*\}\)/);
  });

  it("folds into the top-left chrome row by class, not by relying on where the element sits", () => {
    // It lives beside ← Gallery and the source link: all three are ways OFF the globe, where the
    // view bar is what the globe SHOWS. The class travels with the element for exactly the reason
    // below — this is the element's SECOND home, and an ancestor selector would have quietly
    // stopped matching on the move rather than failing.
    // The two halves sit in two files now — the script that adds the class in the page, the rule
    // that reads it in the globe's stylesheet — which is exactly why both are asserted here rather
    // than in whichever file happens to hold one of them.
    expect(globe).toContain('classList.add("chrome-credit")');
    expect(globeStyles).toContain(".chrome-credit.chrome-credit");
    // A descendant rule would stop matching the moment anything re-parents the element again,
    // and would leave it half-styled rather than plainly unstyled — the harder failure to see.
    // Both former and current containers are named, so neither spelling can creep back in.
    expect(globeStyles).not.toMatch(/\.view-bar\s+\.maplibregl-ctrl-attrib/);
    expect(globeStyles).not.toMatch(/\.globe-chrome\s+\.maplibregl-ctrl-attrib/);
  });

  it("no longer races MapLibre to collapse the control", () => {
    // The old phone path re-parented to <body> and ran a MutationObserver to strip
    // `maplibregl-compact-show` once MapLibre added it a tick after mount. compact:false removes
    // the need for the whole exchange; this pins that it stays removed.
    expect(globe).not.toContain("maplibregl-compact-show");
  });

  it("points at the page that carries the verbatim licence notices", () => {
    // Copernicus GLO-30 Art. 6b demands an exact string we have never shown on the map; the
    // credit satisfies the obligation by being a findable link to where that notice lives.
    expect(creditsMarkup()).toContain('href="/about/"');
  });

  it("keeps an accessible name, the credit now being a glyph rather than a word", () => {
    // An unlabelled ⓘ is the one change here that could actually cost compliance rather than
    // just discoverability: a link whose only content is a decorative SVG has no accessible
    // name at all. title carries it for the pointer, aria-label for assistive tech.
    const credits = creditsMarkup();
    expect(credits).toContain("<svg");
    expect(credits).toMatch(/aria-label="[^"]+"/);
    expect(credits).toMatch(/title="[^"]+"/);
    expect(credits).toContain('aria-hidden="true"'); // the SVG itself, so the name is not doubled
  });

  it("survives MapLibre's sanitizer, which strips data: URIs from href and src", () => {
    // DOM.sanitize parses the string as text/html and drops javascript:/data: on href/src/
    // xlink:href. Inlining the icon as a data: URI would therefore vanish silently — the markup
    // stays, the glyph does not. Keep the SVG inline.
    expect(creditsMarkup()).not.toContain("data:");
  });
});

/** The CREDITS expression as written in earth.astro, spanning however many lines it takes. */
function creditsMarkup(): string {
  const match = globe.match(/const CREDITS =([\s\S]*?);\n/);
  if (!match) throw new Error("earth.astro no longer declares a CREDITS constant");
  return match[1];
}
