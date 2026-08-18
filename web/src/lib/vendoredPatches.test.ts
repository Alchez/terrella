import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

/**
 * Guards the MapLibre patch we vendor: `coveringTiles` must locate the camera from the camera's own
 * position, not by unprojecting its nadir screen point.
 *
 * `getCameraPoint()` returns a point `tan(pitch) * cameraToCenterDistance` px below the viewport, and
 * unprojecting it is exact only against mercator's ground plane. On globe it is a ray/sphere
 * intersection that lands at `asin(u)` instead of `u`, for
 * `u = cameraToCenterDistance * sin(pitch) / globeRadiusPixels`, and past `u = 1` misses the sphere
 * and clamps to the horizon. The recovered point then feeds `distanceToCenter3d`, which sets the
 * desired zoom for every tile at once — so the frame is refined to a depth no camera asked for.
 *
 * This needs a test rather than a comment because the failure is INVISIBLE. A dropped patch does not
 * error, does not warn in a build, and renders the same picture; it costs tiles, and under terrain
 * every tile is an RTT allocation. The three things that would silently drop it are a version bump
 * (the patch is keyed to an exact version), a `pnpm install` against a lockfile that lost the entry,
 * and a merge that drops `pnpm-workspace.yaml`'s `patchedDependencies`. All three fail here.
 *
 * THIS FILE CHECKS PRESENCE; `vendoredPatches.browser.test.ts` CHECKS EFFECT. Neither substitutes
 * for the other — a regex cannot tell whether the expression it matched does anything, and the
 * browser test cannot say which of `patchedDependencies`, the lockfile or the patch file broke.
 *
 * THE WRAP TERNARY THIS REPLACED IS GONE ON PURPOSE, AND MUST NOT COME BACK AS A COMPANION. Until
 * now we vendored upstream PR #7851, which normalises `cameraCoord.x - centerCoord.x` into
 * [-0.5, 0.5]. That corrects a coordinate that came back WRAPPED; this patch builds the camera as
 * centre-plus-offset, which is never in another world copy, so the correction has nothing to
 * correct — and would be actively wrong where the offset legitimately exceeds half a world, which a
 * narrow lens at a low zoom reaches. Measured over 637 cameras: the wrap fix alone leaves the fov
 * ridge untouched, this patch clears both.
 *
 * DELETE BOTH FILES when a MapLibre release carries the fix — at that point the patch must also come
 * out of `pnpm-workspace.yaml`, and these guards would be asserting our own stale edit rather than
 * upstream behaviour. Re-measure rather than assuming parity: our globe runs at a far narrower field
 * of view than MapLibre's default (`VERTICAL_FIELD_OF_VIEW_DEG` in Globe.astro), which is the regime
 * upstream exercises least, so any zoom logic keyed to the field of view lands hardest here.
 *
 * RE-CUT it in the shape asserted below — one expression replaced in place — rather than reproducing
 * whatever structure upstream's source has by then. The patch target is a MINIFIED bundle, where
 * editing an expression survives a re-minify that an added class method or a new import would not.
 */

const SHIPPED_BUNDLE = "../../node_modules/maplibre-gl/dist/maplibre-gl.mjs";
const PATCHED_VERSION = "6.3.0";

/**
 * The library's own camera-position accessor, which already calls both functions the patch needs.
 *
 * Reading the names out of it rather than writing `ht` and `Ut` down is the whole point: minified
 * identifiers are assigned per build, so a listed pair would either go stale into a false failure or
 * — worse — match some unrelated function that inherited the name. Deriving them also turns the
 * assertion into a real claim: that the patched call site calls the SAME two functions MapLibre uses
 * to answer "where is the camera", rather than something that merely looks like a call.
 */
const CAMERA_ACCESSOR =
  /getCameraLngLat\(\)\{let (\w+)=(\w+)\(1,this\.center\.lat\)\*this\.worldSize,(\w+)=this\.cameraToCenterDistance\/\1;return (\w+)\(this\.center,this\.elevation,this\.pitch,this\.bearing,\3\)\.toLngLat\(\)\}/;

/** `coveringTiles`' opening `let`, up to the centre coordinate. Group 2 is the patched expression. */
const COVERING_TILES_PREAMBLE =
  /function \w+\((\w+),\w+\)\{let \w+=\1\.getCameraFrustum\(\),\w+=\1\.getClippingPlane\(\),\w+=([^;]*?),\w+=\w+\.fromLngLat\(\1\.center,\1\.elevation\);/g;

function readShippedBundle(): string {
  // The ENTRY POINT, not the dev bundle. `exports["."].import` resolves to maplibre-gl.mjs, so that
  // is the file the page and the dev server both run; the dev bundle our perf rigs read is
  // deliberately left unpatched and would report a false pass here.
  return readFileSync(new URL(SHIPPED_BUNDLE, import.meta.url), "utf8");
}

describe("vendored MapLibre patch (coveringTiles camera position)", () => {
  it("builds cameraCoord from the same helpers the library's own camera accessor uses", () => {
    const bundle = readShippedBundle();

    const accessor = CAMERA_ACCESSOR.exec(bundle);
    expect(
      accessor,
      "could not find TransformHelper.getCameraLngLat in maplibre-gl.mjs, so the minified names of " +
        "mercatorZfromAltitude and cameraMercatorCoordinateFromCenterAndRotation could not be " +
        "derived. This assertion is vacuous until that regex matches again — re-derive it against " +
        "the installed bundle before trusting a green run here.",
    ).not.toBeNull();
    // Groups: 1 the pixels-per-metre local, 2 mercatorZfromAltitude, 3 the distance local,
    // 4 cameraMercatorCoordinateFromCenterAndRotation.
    const [, , altitudeFn, , cameraFn] = accessor!;

    // Asserted as BOOLEANS below, never `expect(bundle).toMatch(...)` — on failure vitest prints the
    // received value, and the received value here is half a megabyte of minified JavaScript that
    // buries the summary line telling you what broke.
    const preambles = [...bundle.matchAll(COVERING_TILES_PREAMBLE)];
    expect(
      preambles.length,
      "expected exactly one function opening with getCameraFrustum() and getClippingPlane() — " +
        `found ${preambles.length}. Either coveringTiles was restructured upstream, or the patch ` +
        "applied beside a second copy of it.",
    ).toBe(1);

    const transform = preambles[0][1];
    const cameraCoord = preambles[0][2];
    expect(
      cameraCoord.startsWith(`${cameraFn}(`),
      `coveringTiles builds its camera coordinate as \`${cameraCoord}\`, which does not call ` +
        `${cameraFn} — the function getCameraLngLat uses to locate the camera. The patch is ` +
        `missing or was re-cut into a different shape. Check \`patchedDependencies\` in ` +
        `pnpm-workspace.yaml and that patches/maplibre-gl@${PATCHED_VERSION}.patch still applies, ` +
        "then re-run `pnpm install`.",
    ).toBe(true);

    // THE WHOLE ARGUMENT LIST, not just the callee. Every argument here is a way to be wrong that
    // still calls the right function: `${altitudeFn}(1, 0)` in place of the centre's latitude
    // misses by 1/cos(lat) — 0.70 zoom levels at lat -52 — and that is a plausible slip when this
    // patch is re-cut by hand at the next version bump, which is what the note above asks for.
    // The effect guard cannot see it: the error is real but stays inside the depth bound that
    // guard asserts, so this is the only place it fails.
    //
    // Brittle on purpose. A re-formulation that is mathematically identical will fail here, and
    // that is the trade taken deliberately: this patch's failure mode is silence, so a loud
    // failure asking a human to look is worth more than tolerance.
    const expected =
      `${cameraFn}(${transform}.center,${transform}.elevation,${transform}.pitch,` +
      `${transform}.bearing,${transform}.cameraToCenterDistance/` +
      `(${altitudeFn}(1,${transform}.center.lat)*${transform}.worldSize))`;
    expect(
      cameraCoord === expected,
      `coveringTiles' camera coordinate is\n  ${cameraCoord}\nand the patch cuts\n  ${expected}\n` +
        "Same call, different arguments — check which one moved before re-cutting.",
    ).toBe(true);
  });

  it("leaves no unprojected nadir point behind", () => {
    // A patch that applied to a stale duplicate would satisfy the test above while the live call
    // site stayed broken — the same class of defect as a superseded assignment surviving beside its
    // replacement. The expression is the patch's entire subject, so bundle-wide absence is the
    // honest check; it is not used anywhere else in 6.3.0.
    const nadir = /\.screenPointToMercatorCoordinate\(\w+\.getCameraPoint\(\)\)/g;
    const found = readShippedBundle().match(nadir) ?? [];
    expect(
      found.length,
      `${found.length} unpatched copies of the nadir unprojection are still in maplibre-gl.mjs — ` +
        "the patch applied somewhere that is not the live call site.",
    ).toBe(0);
  });

  it("is keyed to the installed MapLibre version", () => {
    // A version bump silently orphans the patch: pnpm keys it to an exact version, so 6.4.0 would
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
        "carries the fix upstream — drop the patch and delete this file and its browser twin (see " +
        "the note at its head).",
    ).toBe(PATCHED_VERSION);
    expect(workspace).toContain(`maplibre-gl@${PATCHED_VERSION}: patches/`);
  });
});
