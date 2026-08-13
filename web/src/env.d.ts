/// <reference types="astro/client" />

/**
 * Build-time overrides for where the heavy asset stores live — see src/lib/assetBase.ts
 * for what each one addresses and what the unset default means.
 *
 * All three are optional: unset means same-origin, which is what `astro dev` and the
 * nginx prod-sim serve. The PUBLIC_ prefix is what lets Vite inline the value into the
 * client bundle; without it the globe's browser script would read `undefined`.
 */
interface ImportMetaEnv {
  readonly PUBLIC_HERO_BASE?: string;
  readonly PUBLIC_BORDERS_BASE?: string;
  readonly PUBLIC_TILE_BASE?: string;
}

/**
 * The debug seam the instrument attaches to `window`, declared once so the write is a plain
 * assignment rather than a cast — a cast says "trust me" and is unchecked; a declaration is checked
 * everywhere the handle is read or written.
 *
 * ONE handle, and the singular is load-bearing. Two names for this same map shipped side by side
 * once, each correct where it sat, and the guard on one could not see the other arrive; the
 * duplicate ended up assigned twice with its own gate dead from the day it landed. A second entry
 * here is the first symptom of that, so adding one is the thing to refuse.
 *
 * OPTIONAL, which is the point of the `?`. Production ships nothing: a writable global pins the map
 * and every GL resource it owns alive past teardown. It is written only from
 * `lib/perf/perfOverlay.ts`, which sits behind a lazy import boundary that `lazyBoundary.test.ts`
 * and `capability.test.ts` both guard. Declaring it here does NOT relax that gate — the type says
 * the property may exist, never that it does.
 *
 * Inline `import(...)` types on purpose: a top-level `import` would make this file a module and
 * silently stop it augmenting the global scope at all.
 */
interface Window {
  terrella?: {
    map: import("maplibre-gl").Map;
    /** The same composition the panel and the export button read, or undefined when the page
     *  supplied no report builder. */
    report(): unknown;
    /** Capture to `web/.perf/`, named by `arm` when the dev endpoint is there to name it. */
    export(arm?: string): Promise<"saved" | "copied" | "failed">;
  };
}
