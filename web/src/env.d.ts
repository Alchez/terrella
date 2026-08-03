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
 * Debug handles the page attaches to `window`, declared once so the writes are plain assignments
 * rather than a cast at each site — a cast says "trust me" and is unchecked; a declaration is
 * checked everywhere the handle is read or written.
 *
 * BOTH ARE OPTIONAL AND BOTH ARE FLAG-GATED, which is the point of typing them `?`. Production
 * ships neither: a writable global pins the map, and everything it owns including GL resources,
 * alive past teardown. `__map` is written only under `?perf` in earth.astro; `terrellaMap` only
 * from `lib/perf/perfOverlay.ts`, which is behind a lazy import boundary that `lazyBoundary.test.ts`
 * and `capability.test.ts` both guard. Declaring them here does NOT relax either gate — the type
 * says the property may exist, never that it does.
 *
 * Inline `import(...)` types on purpose: a top-level `import` would make this file a module and
 * silently stop it augmenting the global scope at all.
 */
interface Window {
  __map?: import("maplibre-gl").Map;
  terrellaMap?: import("maplibre-gl").Map;
}
