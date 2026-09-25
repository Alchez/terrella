import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";
import baseLayout from "../layouts/Base.astro?raw";
import { SOCIAL_CARD } from "./assetBase";
import { SOCIAL_CARD_FILE, SOCIAL_CARD_HEIGHT, SOCIAL_CARD_WIDTH } from "./socialCard";
import { advertisedObjects } from "../../scripts/check_deploy_sync.ts";
import type { Manifest } from "./manifest";

/**
 * The link-preview tags, which nothing else here can see: they are invisible on the site, and the
 * only reader is a scraper on another machine. What can go wrong silently is an address, so these
 * guard the address rather than the markup.
 */
describe("the link-preview card", () => {
  it("is addressed through the base, never by a host written into the layout", () => {
    // A literal `https://assets.…` here would work in production and point at a host the deploy
    // no longer sets, which is the failure `resolveAssetBase` exists to make impossible.
    expect(baseLayout).toContain("SOCIAL_CARD");
    expect(baseLayout).not.toMatch(/content=\{?"https:\/\//);
  });

  it("declares the size the card really is, from one place", () => {
    expect(baseLayout).toContain("String(SOCIAL_CARD_WIDTH)");
    expect(baseLayout).toContain("String(SOCIAL_CARD_HEIGHT)");
    // 1.91:1 is what the platforms lay out for; a card that drifts off it gets letterboxed or
    // cropped by whoever renders it, and nothing here would say so.
    expect(SOCIAL_CARD_WIDTH / SOCIAL_CARD_HEIGHT).toBeCloseTo(1.905, 2);
  });

  it("carries the four properties a scraper needs, plus the large-image card", () => {
    for (const property of ["og:type", "og:title", "og:description", "og:image"]) {
      expect(baseLayout, property).toContain(`property="${property}"`);
    }
    expect(baseLayout).toContain('name="twitter:card" content="summary_large_image"');
  });

  it("is a file the deploy preflight refuses to ship without", () => {
    // The preflight lists what R2 must hold. Read through its own function rather than restated,
    // so deleting the card from that set fails here rather than at the first share.
    const manifest: Manifest = { countries: [] } as unknown as Manifest;
    const advertised = advertisedObjects(manifest);
    expect([...advertised].some((key) => key.endsWith(SOCIAL_CARD_FILE))).toBe(true);
  });

  it("names the same file the layout points at", () => {
    expect(SOCIAL_CARD.endsWith(SOCIAL_CARD_FILE)).toBe(true);
    // The unset default is same-origin, which is what dev serves; production supplies the base.
    const deployCommand = JSON.parse(
      readFileSync(new URL("../../package.json", import.meta.url), "utf8"),
    ).scripts["build:deploy"] as string;
    expect(deployCommand).toContain("PUBLIC_SOCIAL_BASE=https://");
  });
});
