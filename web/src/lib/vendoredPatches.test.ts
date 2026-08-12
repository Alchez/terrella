import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

/**
 * Guards the MapLibre patch we vendor from upstream PR #7851.
 *
 * The patch normalises the camera-to-centre x delta into [-0.5, 0.5] for globe projections, in
 * `coveringTiles`. Without it, a camera and centre straddling the antimeridian produce a
 * `distToCentre` wrong by exactly 1.0, which feeds `calculateTileZoom` and inflates the desired
 * zoom for every tile at once: measured at 13x the renderable tiles and 4.1 fps against 165, in two
 * ~42.5-degree-wide Pacific bands.
 *
 * This needs a test rather than a comment because the failure is INVISIBLE. A dropped patch does
 * not error, does not warn in a build, and does not change any behaviour we render in CI — it costs
 * a 40x frame rate in one region of the globe that no other test visits. The three things that
 * would silently drop it are a version bump (the patch is keyed to an exact version), a `pnpm
 * install` against a lockfile that lost the entry, and a merge that drops `pnpm-workspace.yaml`'s
 * `patchedDependencies`. All three fail here.
 *
 * DELETE THIS FILE when PR #7851 merges upstream and we take the release that carries it — at that
 * point the patch must also come out of `pnpm-workspace.yaml`, and this guard would then be
 * asserting our own stale edit rather than upstream behaviour. The upstream release also carries a
 * SECOND change we deliberately excluded (a narrow-lens zoom bump of `scaleZoom(36.87 / fov)`,
 * which at our fov 15 adds ~1.3 zoom levels and so multiplies tile counts); re-measure before
 * accepting it.
 */

const SHIPPED_BUNDLE = "../../node_modules/maplibre-gl/dist/maplibre-gl.mjs";
const PATCHED_VERSION = "6.3.0";

function readShippedBundle(): string {
  return readFileSync(new URL(SHIPPED_BUNDLE, import.meta.url), "utf8");
}

describe("vendored MapLibre patch (upstream PR #7851)", () => {
  it("is applied in the bundle the app actually loads", () => {
    // The ENTRY POINT, not the dev bundle. `exports["."].import` resolves to maplibre-gl.mjs, so
    // that is the file the page runs; the dev bundle our other canaries read is deliberately left
    // unpatched and would report a false pass here.
    //
    // Asserted as a BOOLEAN, never `expect(bundle).toMatch(...)` — on failure vitest prints the
    // received value, and the received value here is four megabytes of minified JavaScript that
    // buries the summary line telling you what broke.
    const patched =
      /Math\.hypot\(\s*(\w+)\s*\?\s*\((\w+)\.x-(\w+)\.x\)-Math\.round\(\2\.x-\3\.x\)\s*:\s*\2\.x-\3\.x\s*,/;
    expect(
      patched.test(readShippedBundle()),
      "PR #7851's wrap fix is missing from maplibre-gl.mjs — the antimeridian tile explosion is " +
        `back (13x tiles, 4.1 fps). Check \`patchedDependencies\` in pnpm-workspace.yaml and that ` +
        `patches/maplibre-gl@${PATCHED_VERSION}.patch still applies, then re-run \`pnpm install\`.`,
    ).toBe(true);
  });

  it("leaves no unpatched copy of the expression behind", () => {
    // A patch that applied to a stale duplicate would satisfy the test above while the live call
    // site stayed broken — the same class of defect as a superseded assignment surviving beside
    // its replacement.
    const unpatched = /Math\.hypot\((\w+)\.x-(\w+)\.x,\1\.y-\2\.y\)/;
    expect(
      unpatched.test(readShippedBundle()),
      "an UNPATCHED copy of the coveringTiles distance expression is still in maplibre-gl.mjs — " +
        "the patch applied somewhere that is not the live call site.",
    ).toBe(false);
  });

  it("is keyed to the installed MapLibre version", () => {
    // A version bump silently orphans the patch: pnpm keys it to an exact version, so 6.0.1 would
    // install clean and unpatched. This is the check that turns that into a failure.
    const workspace = readFileSync(
      new URL("../../pnpm-workspace.yaml", import.meta.url),
      "utf8",
    );
    const installed = JSON.parse(
      readFileSync(
        new URL("../../node_modules/maplibre-gl/package.json", import.meta.url),
        "utf8",
      ),
    ) as { version: string };
    expect(
      installed.version,
      "maplibre-gl was upgraded but patches/ is still keyed to " +
        `${PATCHED_VERSION}. Either re-cut the patch for the new version, or — if the new version ` +
        "contains PR #7851 — drop the patch and delete this file (see the note at its head).",
    ).toBe(PATCHED_VERSION);
    expect(workspace).toContain(`maplibre-gl@${PATCHED_VERSION}: patches/`);
  });
});
