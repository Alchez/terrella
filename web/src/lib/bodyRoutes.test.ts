import { describe, it, expect } from "vitest";
import { BODIES, type BodySlug } from "./bodies";
import { bodyRoutes, isSamePath } from "./bodyRoutes";

const SLUGS = Object.keys(BODIES) as BodySlug[];

describe("the two pages a body has", () => {
  it("answers both for Earth", () => {
    expect(bodyRoutes("earth")).toEqual({ globe: "/earth/", lite: "/" });
  });

  it("answers both for Mars", () => {
    expect(bodyRoutes("mars")).toEqual({ globe: "/mars/", lite: "/mars/lite/" });
  });

  it("puts every body's globe at its own slug", () => {
    // The derivation stated as a test rather than trusted, because it is the argument for NOT
    // storing a globe route: the page-per-slug rule is enforced next door in bodies.browser.test.ts,
    // and this is the line that turns that rule into an address.
    for (const slug of SLUGS) expect(bodyRoutes(slug).globe).toBe(`/${slug}/`);
  });

  it("gives no body the same page twice", () => {
    for (const slug of SLUGS) {
      const routes = bodyRoutes(slug);
      expect(routes.globe, `${slug}`).not.toBe(routes.lite);
    }
  });

  it("has the bodies actually disagree, on both routes", () => {
    // ANTI-VACUITY, and it earns its place: every assertion above would still pass if both bodies
    // resolved to one set of routes, and so would the guard tests — a Mars visitor bounced to
    // Earth's gallery is exactly the bug this module exists to close, and it looks like success.
    expect(new Set(SLUGS.map((slug) => bodyRoutes(slug).globe)).size).toBe(SLUGS.length);
    expect(new Set(SLUGS.map((slug) => bodyRoutes(slug).lite)).size).toBe(SLUGS.length);
  });

  it("never sends a visitor off this body when they cannot run its globe", () => {
    // The failure the literal `/earth` produced, asserted at the registry rather than at the guard:
    // a fallback that IS another planet's globe answers "your device cannot draw this" by drawing
    // something else, and does it before paint so nothing on screen says a planet changed.
    for (const from of SLUGS) {
      for (const to of SLUGS) {
        if (from === to) continue;
        expect(bodyRoutes(from).lite, `${from} falls back onto ${to}`).not.toBe(
          bodyRoutes(to).globe,
        );
      }
    }
  });
});

describe("two pathnames name the same page", () => {
  it("ignores a trailing slash, in either argument", () => {
    expect(isSamePath("/earth", "/earth/")).toBe(true);
    expect(isSamePath("/earth/", "/earth")).toBe(true);
    expect(isSamePath("/mars/lite", "/mars/lite/")).toBe(true);
  });

  it("matches a path against itself, including the root", () => {
    expect(isSamePath("/", "/")).toBe(true);
    expect(isSamePath("/earth/", "/earth/")).toBe(true);
  });

  it("does not confuse the root with a body's page", () => {
    // `/` normalises to the empty string, which is the one case where a sloppier rule — say,
    // comparing the first path segment — would call the gallery and the globe the same page.
    expect(isSamePath("/", "/earth/")).toBe(false);
    expect(isSamePath("/", "/mars/")).toBe(false);
  });

  it("does not treat a page as its own parent", () => {
    expect(isSamePath("/mars/", "/mars/lite/")).toBe(false);
    expect(isSamePath("/mars/lite/", "/mars/")).toBe(false);
  });

  it("does not match a prefix of a longer name", () => {
    expect(isSamePath("/earth/", "/earthx/")).toBe(false);
    expect(isSamePath("/mars/", "/marsupial/")).toBe(false);
  });
});
