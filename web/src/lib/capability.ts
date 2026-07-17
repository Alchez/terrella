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

/** WebGL2 present AND not a software rasterizer — the globe's non-negotiable floor. */
function capable(signals: CapabilitySignals): boolean {
  return signals.webgl2 && !signals.softwareGpu;
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
  if (quality === "globe") return capable(signals) ? "globe" : "gallery";
  if (quality === "full") return capable(signals) ? "full" : "gallery";

  // quality === "auto": the probe decides, pessimistically.
  if (!capable(signals)) return "gallery";
  if (signals.saveData || signals.slowNetwork) return "gallery"; // tiles are data-heavy
  if (signals.lowMemory || signals.reducedMotion) return "globe"; // capable, but skip full
  return "full";
}

// --- Impure environment access (not unit-tested; kept thin) -------------------

const isBrowser = (): boolean => typeof window !== "undefined";

/** Detect a software GL renderer via the (best-effort, often masked) debug ext. */
function detectSoftwareGpu(gl: WebGL2RenderingContext): boolean {
  const ext = gl.getExtension("WEBGL_debug_renderer_info");
  if (!ext) return false; // masked or unsupported → assume a real GPU, don't over-penalize
  const renderer = String(gl.getParameter(ext.UNMASKED_RENDERER_WEBGL) || "");
  return /swiftshader|llvmpipe|software|basic render|microsoft basic/i.test(renderer);
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
      saveData: false,
      slowNetwork: false,
      lowMemory: false,
      reducedMotion: false,
    };
  }

  let webgl2 = false;
  let softwareGpu = false;
  try {
    const gl = document.createElement("canvas").getContext("webgl2");
    if (gl) {
      webgl2 = true;
      softwareGpu = detectSoftwareGpu(gl);
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

  const deviceMemory = Number((navigator as any).deviceMemory ?? Infinity);
  const lowMemory = deviceMemory < 4;

  const reducedMotion =
    typeof matchMedia === "function" && matchMedia("(prefers-reduced-motion: reduce)").matches;

  return { webgl2, softwareGpu, saveData, slowNetwork, lowMemory, reducedMotion };
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
