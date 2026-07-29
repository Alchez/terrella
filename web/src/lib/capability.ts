/**
 * Capability probe + tier decision — the brain behind Terrella's three-tier
 * progressive enhancement (gallery / globe / full).
 *
 * `decideTier` is a PURE function of a signals snapshot plus the user's persisted
 * quality choice: it is the single source of truth for "which tier", unit-tested
 * exhaustively in capability.test.ts. Everything impure (reading WebGL, the
 * Network Information API, media queries, localStorage) is isolated in the probe
 * and persistence helpers below so the decision itself stays testable.
 *
 * Design stance (from the project architecture): default PESSIMISTIC — the
 * gallery is the guaranteed-instant baseline — and upgrade OPTIMISTICALLY only
 * when the device clearly clears the bar. An explicit user choice always wins,
 * but never past the hard WebGL2 floor the globe physically needs.
 */

/** The experience actually served. */
export type Tier = "gallery" | "globe" | "full";

/** The persisted user preference. `auto` defers to the probe; the rest force a tier. */
export type Quality = "auto" | "lite" | "globe" | "full";

/** A snapshot of the device/environment, reduced to the booleans the decision needs. */
export interface CapabilitySignals {
  /** WebGL2 context creates — the hard floor for the MapLibre globe. */
  webgl2: boolean;
  /** A software rasterizer (SwiftShader/llvmpipe) — present but too slow for the globe. */
  softwareGpu: boolean;
  /**
   * The BROWSER's own verdict that this context would be badly slow —
   * `failIfMajorPerformanceCaveat`.
   *
   * Kept separate from `softwareGpu` rather than folded in, because they are different facts with
   * the same consequence: one is a renderer NAME matching a regex, the other is the browser
   * refusing to promise acceleration. When someone reports "no globe" the log has to say which
   * fired. It also repairs a real hole `rendererStrings` documents about itself — Chrome and
   * Firefox each mask one of the two renderer strings, and a hardened browser masks both, at which
   * point the regex silently reports a healthy GPU. This signal cannot be masked: it is an answer,
   * not a string.
   */
  performanceCaveat: boolean;
  /** Data-saver: `navigator.connection.saveData` or `prefers-reduced-data`. */
  saveData: boolean;
  /** A slow effective connection (2g / very low downlink). */
  slowNetwork: boolean;
  /** `navigator.deviceMemory` below the comfortable threshold for the heavier tier. */
  lowMemory: boolean;
  /** `prefers-reduced-motion` — the user opts out of the idle animation full adds. */
  reducedMotion: boolean;
}

export const QUALITY_KEY = "rg:quality";
const DEFAULT_QUALITY: Quality = "auto";

/**
 * `navigator.deviceMemory` at or below this reads as "modest device" — serve globe, not full.
 *
 * The comparison is `<=`, and that is the whole point. The Device Memory API reports RAM rounded
 * to the NEAREST power of two, so the only values that exist are 0.25 / 0.5 / 1 / 2 / 4 / 8 / 16…
 * The previous `< 4` could therefore only ever mean "2 or less" — nothing reports 3 — while
 * everything from 4 GB upward sailed through to `full`. That band starts with the **Moto G Power,
 * Lighthouse's own mobile reference device**, which reports exactly 4.
 *
 * Measured rather than taken from the spec, because the spec is out of date here: the W3C text
 * describes an 8 GiB upper clamp, and current Chrome does not apply it — a 29 GiB machine reports
 * **32**. Neither the clamp nor the rounding direction changes the argument above; only the claim
 * that the set is small and has no odd numbers in it does, and that holds.
 *
 * Being wrong in this direction is cheap: a demoted device loses the idle animation (and, once
 * Tier 3 wires up, the terrain mesh). It never loses the globe.
 */
export const LOW_MEMORY_GIB = 4;

/**
 * Whether a reported `deviceMemory` counts as modest. `undefined` — every Safari and Firefox —
 * is NOT low: see the note at the read site in `probeSignals` for why there is no honest proxy.
 *
 * Pure, and separate from the probe, so the threshold is testable without a fake `navigator`.
 */
export function isLowMemory(deviceMemoryGib: number | undefined): boolean {
  return (deviceMemoryGib ?? Infinity) <= LOW_MEMORY_GIB;
}

/** Renderer strings that mean "there is no real GPU behind this context". */
export const SOFTWARE_RENDERER_PATTERN =
  /swiftshader|llvmpipe|software|basic render|microsoft basic|softpipe|mesa offscreen/i;

/** True if any of these renderer strings names a software rasterizer. */
export function isSoftwareRenderer(renderers: readonly string[]): boolean {
  return renderers.some((renderer) => SOFTWARE_RENDERER_PATTERN.test(renderer));
}

/**
 * WebGL2 present, not a software rasterizer, and no browser-declared performance caveat — the
 * globe's non-negotiable floor.
 *
 * Exported because `index.astro` was re-deriving it inline (`gpu.webgl2 && !gpu.softwareGpu`) to
 * decide whether to offer the Globe link. A duplicated floor is a floor that silently stops
 * matching the moment a signal is added — which is exactly what adding one just demonstrated.
 */
export function canRunGlobe(signals: CapabilitySignals): boolean {
  return signals.webgl2 && !signals.softwareGpu && !signals.performanceCaveat;
}

/**
 * Decide the tier from a signals snapshot and the persisted quality choice.
 *
 * Precedence:
 *  1. An explicit choice (lite/globe/full) wins — but a globe/full request on a
 *     device below the WebGL2 floor falls back to the gallery (we can't fake it).
 *  2. On `auto`, walk a pessimistic ladder: no GPU or data pressure → gallery;
 *     capable-but-constrained (low memory, or reduced-motion opting out of the
 *     animation) → globe; capable and healthy → full.
 */
export function decideTier(signals: CapabilitySignals, quality: Quality): Tier {
  if (quality === "lite") return "gallery";
  if (quality === "globe") return canRunGlobe(signals) ? "globe" : "gallery";
  if (quality === "full") return canRunGlobe(signals) ? "full" : "gallery";

  // quality === "auto": the probe decides, pessimistically.
  if (!canRunGlobe(signals)) return "gallery";
  if (signals.saveData || signals.slowNetwork) return "gallery"; // tiles are data-heavy
  if (signals.lowMemory || signals.reducedMotion) return "globe"; // capable, but skip full
  return "full";
}

// --- Impure environment access (not unit-tested; kept thin) -------------------

const isBrowser = (): boolean => typeof window !== "undefined";

/**
 * Read the renderer string, preferring the debug extension but falling back to the standard
 * parameter.
 *
 * The fallback is not belt-and-braces, it is the Firefox path. `WEBGL_debug_renderer_info` is
 * deprecated there on fingerprinting grounds, and Firefox's own advice is to read
 * `gl.getParameter(gl.RENDERER)`, which it now returns UNMASKED. The previous
 * `if (!ext) return false` meant that the day the extension finally goes, every Firefox visitor
 * silently becomes `softwareGpu: false` and gets promoted — a check that stops being able to fail
 * is worse than no check, because nothing looks different.
 *
 * Both strings are tested rather than just the first non-empty one: Chrome masks `RENDERER` to a
 * generic "WebKit WebGL" while the extension carries the truth, and Firefox is the reverse.
 */
function rendererStrings(gl: WebGL2RenderingContext): string[] {
  const strings: string[] = [];
  const ext = gl.getExtension("WEBGL_debug_renderer_info");
  if (ext) strings.push(String(gl.getParameter(ext.UNMASKED_RENDERER_WEBGL) || ""));
  strings.push(String(gl.getParameter(gl.RENDERER) || ""));
  return strings;
}

/** Detect a software GL renderer — present, but far too slow for the globe. */
function detectSoftwareGpu(gl: WebGL2RenderingContext): boolean {
  return isSoftwareRenderer(rendererStrings(gl));
}

/**
 * Ask the browser directly whether accelerating this context would come with a major caveat.
 *
 * `failIfMajorPerformanceCaveat: true` makes `getContext` return **null** instead of handing back
 * a context it would have to software-render or otherwise cripple. Run against a throwaway canvas
 * it costs one context and answers a question no string can be masked out of.
 *
 * WHY THIS IS A PROBE AND **NOT** SET ON THE MAP ITSELF
 * ----------------------------------------------------
 * Passing the flag through `canvasContextAttributes` would make `new maplibregl.Map(...)` fail on
 * any machine the browser flags — including a working GPU behind a driver blocklist, which is the
 * live situation on this project's own Firefox (`nvidia/unknown`, DMABUF_WEBGL blocklisted since
 * the 595.84 driver). There the globe runs, just slowly, and trading a slow globe for no globe is
 * a worse outcome that nothing at runtime could undo — a context attribute cannot be changed after
 * creation. As a probe the same fact instead feeds `decideTier`, which is reversible: the reader
 * gets the gallery by default and can still force `?quality=globe`.
 */
function detectPerformanceCaveat(): boolean {
  try {
    const probe = document
      .createElement("canvas")
      .getContext("webgl2", { failIfMajorPerformanceCaveat: true });
    // Null means the browser declined to promise acceleration. Release it either way: on the
    // machines this fires for, an extra live context is the last thing to leave lying around.
    probe?.getExtension("WEBGL_lose_context")?.loseContext();
    return probe === null;
  } catch {
    // A throw is not a verdict. Stay silent rather than demote a device on an exception.
    return false;
  }
}

/**
 * Gather the live capability signals. SSR-safe: off the browser it returns the
 * fully-pessimistic snapshot, so any server render decides "gallery".
 */
export function probeSignals(): CapabilitySignals {
  if (!isBrowser()) {
    return {
      webgl2: false,
      softwareGpu: false,
      performanceCaveat: false,
      saveData: false,
      slowNetwork: false,
      lowMemory: false,
      reducedMotion: false,
    };
  }

  let webgl2 = false;
  let softwareGpu = false;
  let performanceCaveat = false;
  try {
    const gl = document.createElement("canvas").getContext("webgl2");
    if (gl) {
      webgl2 = true;
      softwareGpu = detectSoftwareGpu(gl);
      // Only meaningful once a plain context succeeds: without that control, "null" would be
      // reporting "no WebGL2 here" a second time rather than "acceleration comes with a caveat".
      performanceCaveat = detectPerformanceCaveat();
    }
  } catch {
    webgl2 = false;
  }

  // Network Information API is not on every browser; treat absent as "no constraint".
  const connection = (navigator as any).connection ?? {};
  const reducedData =
    typeof matchMedia === "function" && matchMedia("(prefers-reduced-data: reduce)").matches;
  const saveData = Boolean(connection.saveData) || reducedData;
  const effectiveType = String(connection.effectiveType ?? "");
  const downlink = Number(connection.downlink ?? Infinity);
  const slowNetwork = /(^|\b)(slow-2g|2g)\b/.test(effectiveType) || downlink < 1.5;

  // ABSENT deviceMemory stays optimistic, deliberately — this is every Safari and every Firefox.
  //
  // Both vendors decline to implement the Device Memory API on fingerprinting grounds, so its
  // absence is a statement about the BROWSER, not about the hardware, and there is no honest
  // proxy to substitute. `navigator.hardwareConcurrency` in particular is not one: WebKit clamps
  // it to 8 on macOS and **2 on iOS**, so every iPhone and every iPad Pro reports 2 while a budget
  // Android reports 8 — as a device-strength signal it is not merely weak, it is INVERTED. MDN
  // says the same in general terms: "don't treat this as an absolute measurement of the number of
  // cores".
  //
  // So the static gate reports what it can actually see, and the runtime ladder
  // (fpsDegradation.ts) carries what it cannot — which is the vendors' own stance: observe
  // behaviour, do not interrogate hardware. That ladder now has a terrain rung, which is what
  // makes this division of labour real rather than an excuse.
  const lowMemory = isLowMemory((navigator as any).deviceMemory);

  const reducedMotion =
    typeof matchMedia === "function" && matchMedia("(prefers-reduced-motion: reduce)").matches;

  return {
    webgl2,
    softwareGpu,
    performanceCaveat,
    saveData,
    slowNetwork,
    lowMemory,
    reducedMotion,
  };
}

// --- Persisted quality choice -------------------------------------------------

/** Read the persisted quality choice, defaulting to `auto` (and validating). */
export function getQuality(): Quality {
  if (!isBrowser()) return DEFAULT_QUALITY;
  const stored = localStorage.getItem(QUALITY_KEY);
  return stored === "auto" || stored === "lite" || stored === "globe" || stored === "full"
    ? stored
    : DEFAULT_QUALITY;
}

/** Persist the quality choice. */
export function setQuality(quality: Quality): void {
  if (isBrowser()) localStorage.setItem(QUALITY_KEY, quality);
}

/** Convenience: probe the live device and fold in the saved choice. */
export function currentTier(): Tier {
  return decideTier(probeSignals(), getQuality());
}
