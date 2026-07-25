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
