/** The globe's atmosphere — MapLibre's `sky`, and the zoom ramp on its strength.
 *
 *  Sibling of terrainSource.ts's exaggeration ramp, not a generalisation of it. The two share an
 *  interpolation shape and nothing else: one scales geometry through a per-frame uniform we write
 *  by hand, the other scales a post-process that MapLibre will evaluate from a zoom expression
 *  (see ATMOSPHERE_BLEND below — the asymmetry is the whole reason this file is short and that
 *  one is not). Kept apart on the same reasoning that keeps reliefTiles.ts and terrainSource.ts
 *  apart.
 *
 *  WHAT THE ATMOSPHERE ACTUALLY IS, because the name undersells it. This is not a halo painted
 *  behind the sphere: `shaders/glsl/atmosphere.fragment.glsl` ray-marches the air column from the
 *  camera and truncates the integral at the planet surface (`rsi(r0, r, rPlanet)`, then
 *  `p.y = min(p.y, p2.x)`), so one `atmosphere-blend` uniform scales BOTH the limb glow and full
 *  aerial perspective over the ground. Its blue bias is Rayleigh — the shader's scattering
 *  coefficients are `(5.5, 13.0, 22.4)e-6`, so blue scatters four times as hard as red.
 *
 *  Not to be confused with terrain fog, which shares these `fog-*` properties and never runs for
 *  us: `terrain.fragment.glsl` skips fog entirely under `u_is_globe_mode`.
 */

import type { SkySpecification } from "maplibre-gl";

/** Committed sky colours. Browser-only aesthetic constants — deliberately NOT in palette.ts,
 *  whose contract is "colours the PIPELINE owns, restated for the browser", each one pinned by a
 *  Python test that recomputes it from palette.py. Nothing here has a pipeline counterpart to be
 *  pinned against, so filing them there would put unguarded values under a guarded banner. */
const SKY_COLOR = "#8fb8d6";
const HORIZON_COLOR = "#cbd8dd";
const FOG_COLOR = "#dfe7ea";

/** Atmosphere strength at and below ATMOSPHERE_RAMP_START_ZOOM. Chosen when the starfield landed
 *  and left alone since: against dark space it reads as a gentle earth-glow, which is the entire
 *  job the atmosphere was kept for. → HISTORY § the starfield. */
export const BASE_ATMOSPHERE_BLEND = 0.7;

/** Zoom at or below which the ramp holds BASE_ATMOSPHERE_BLEND. The glow needs off-globe pixels
 *  to be drawn into, and at z3 they are still there (measured: 2 of 10 sampled screen rows read
 *  as background at pitch 0, 5 of 10 at pitch 60). */
export const ATMOSPHERE_RAMP_START_ZOOM = 3;

/** Zoom at or above which the ramp holds its floor. By z5 at pitch 0 the sphere already fills the
 *  viewport (0 of 10 rows off-globe) and at z7-8 nothing is off-globe at ANY pitch, so past here
 *  the atmosphere cannot deliver the effect it exists for and only hazes the map. */
export const ATMOSPHERE_RAMP_END_ZOOM = 6;

/** Atmosphere strength held at ATMOSPHERE_RAMP_END_ZOOM.
 *
 *  Picked off measured damage rather than taste. At a pitched z7 frame the constant 0.7 pushes
 *  23.8% of all pixels to a clipped >=254 and costs a quarter of the frame's saturation; the
 *  atmosphere alone adds up to +59,+84,+94 DN at the top of the frame, turning a saturated
 *  `166,137,105` into a near-neutral `225,221,199`. The ladder measured at that camera:
 *
 *      blend  0.70 -> 23.8% clipped, mean saturation 0.251
 *      blend  0.35 -> 11.8%,         0.289
 *      blend  0.15 ->  5.8%,         0.311
 *      blend  0    ->  1.8%,         0.328   <- the tiles' own snow, the floor no setting beats
 *
 *  0.15 is where clipping stops being the thing you notice while distance still lightens — which
 *  is the one part of aerial perspective worth keeping, since it reads as depth rather than as
 *  blown highlights. → HISTORY § the atmosphere ramp. */
export const DEFAULT_ATMOSPHERE_FLOOR = 0.15;

/** `?sky=off` — the control arm, holding BASE_ATMOSPHERE_BLEND at every zoom (what shipped before
 *  the ramp). */
export const ATMOSPHERE_RAMP_OFF = "off";

export type AtmosphereRamp = { kind: "off" } | { kind: "ramp"; floor: number };

/** Built fresh per call rather than exported as a shared literal, so no caller can mutate the
 *  default out from under the next one — same reasoning as defaultTerrainRamp. */
export function defaultAtmosphereRamp(): AtmosphereRamp {
  return { kind: "ramp", floor: DEFAULT_ATMOSPHERE_FLOOR };
}

/**
 * Read `?sky=off|<floor>` — absent is the default ramp, `off` holds the base constant, and a
 * number is the strength to hold at ATMOSPHERE_RAMP_END_ZOOM.
 *
 * Returns null for malformed ONLY. Absent and malformed both end up on the default ramp, but the
 * caller has to tell them apart to warn about a typo — mirrors parseTerrainRamp, for the reason
 * given there: a run that believes it swept 0.15 while running 0.7 is worse than no run.
 *
 * Zero IS accepted here, unlike `?terrain=0`: a floor of 0 means "no atmosphere past the
 * overview", which is a legitimate arm and visibly distinct from the default. The ceiling is 1,
 * MapLibre's own maximum for the property.
 */
export function parseAtmosphereRamp(params: URLSearchParams): AtmosphereRamp | null {
  const raw = params.get("sky");
  if (raw === null || raw.trim() === "") return defaultAtmosphereRamp();
  if (raw.trim().toLowerCase() === ATMOSPHERE_RAMP_OFF) return { kind: "off" };
  const floor = Number(raw);
  if (!Number.isFinite(floor) || floor < 0 || floor > 1) return null;
  return { kind: "ramp", floor };
}

/**
 * Per-zoom-level decay factor that carries `base` to `floor` across the ramp's span.
 *
 * Doubles as MapLibre's `["exponential", base]` interpolation base, which is not a coincidence
 * but an identity: MapLibre interpolates `y = y0 + (y1-y0)·(b^(x-x0) - 1)/(b^(x1-x0) - 1)`, and
 * substituting `b = (y1/y0)^(1/(x1-x0))` makes `b^(x1-x0) = y1/y0`, so the denominator becomes
 * `(y1-y0)/y0` and the whole expression collapses to `y = y0·b^(x-x0)` — exact geometric decay.
 * That is what lets one two-stop expression say precisely what rampedAtmosphereBlend says.
 */
export function atmosphereDecayRatio(
  baseBlend: number = BASE_ATMOSPHERE_BLEND,
  floorBlend: number = DEFAULT_ATMOSPHERE_FLOOR,
): number {
  return (floorBlend / baseBlend) ** (1 / (ATMOSPHERE_RAMP_END_ZOOM - ATMOSPHERE_RAMP_START_ZOOM));
}

/**
 * Atmosphere strength for a map zoom, decaying geometrically from `base` to `floor`.
 *
 * MapLibre evaluates the shipped ramp from the expression `atmosphereBlend()` builds; this is the
 * JS mirror, used for the `?perf` read-out, and a test pins the two together at every stop so the
 * read-out cannot quietly disagree with what is on screen.
 *
 * Geometric rather than linear for a measured reason, not for symmetry with the terrain ramp: the
 * limb is gone from the frame by z5 at pitch 0, so most of the reduction should be spent by then.
 * Linear leaves 0.333 at z5 (52% of the way down); geometric leaves 0.251 (66%).
 */
export function rampedAtmosphereBlend(
  baseBlend: number,
  zoom: number,
  floorBlend: number = DEFAULT_ATMOSPHERE_FLOOR,
): number {
  if (zoom <= ATMOSPHERE_RAMP_START_ZOOM) return baseBlend;
  if (zoom >= ATMOSPHERE_RAMP_END_ZOOM) return floorBlend;
  const span =
    (zoom - ATMOSPHERE_RAMP_START_ZOOM) /
    (ATMOSPHERE_RAMP_END_ZOOM - ATMOSPHERE_RAMP_START_ZOOM);
  return baseBlend * (floorBlend / baseBlend) ** span;
}

/**
 * `atmosphere-blend` as MapLibre will evaluate it — a zoom expression, not a number.
 *
 * The style spec marks this property zoom-interpolatable and its own doc says "it is best to
 * interpolate this expression when using globe projection", so the ramp is declared once and
 * evaluated per frame by MapLibre. That matters beyond tidiness: driving it from a `zoom` handler
 * would mean a `setSky` per step, and Style.setSky re-runs the sky's transitions on every call
 * with a **300 ms default duration** (style.ts, `extend({duration: 300}, stylesheet.transition)`)
 * — measured live: a fresh value is unchanged at t=0, half-applied at t=100 ms, settled by
 * t=500 ms. A per-step handler would therefore chase the camera a third of a second behind and
 * restart the transition before it ever landed. An expression has no such lag.
 *
 * This is exactly where terrain cannot follow: `exaggeration` is typed a plain number, which is
 * why that ramp has to be hand-driven while this one is declarative.
 *
 * A floor of 0 falls back to linear — geometric decay cannot reach zero, and MapLibre's
 * `exponential` divides by `base^span - 1`, which a base of 0 degenerates.
 */
export function atmosphereBlend(ramp: AtmosphereRamp): SkySpecification["atmosphere-blend"] {
  if (ramp.kind === "off") return BASE_ATMOSPHERE_BLEND;
  const interpolation: ["exponential", number] | ["linear"] =
    ramp.floor > 0 ? ["exponential", atmosphereDecayRatio(BASE_ATMOSPHERE_BLEND, ramp.floor)] : ["linear"];
  return [
    "interpolate",
    interpolation,
    ["zoom"],
    ATMOSPHERE_RAMP_START_ZOOM,
    BASE_ATMOSPHERE_BLEND,
    ATMOSPHERE_RAMP_END_ZOOM,
    ramp.floor,
  ];
}

/**
 * The whole `sky` spec, with the atmosphere ramped and every other property held.
 *
 * Owned here rather than inline in globe.astro so the colours and the ramp that scales them sit
 * in one reviewable place — the module that defines a thing names it, as countryHighlight.ts owns
 * COUNTRIES_SOURCE.
 *
 * `fog-*` is carried unchanged and is inert on our map (globe projection skips terrain fog
 * outright); it is kept because it costs nothing and would be the correct configuration the day
 * a mercator view exists.
 */
export function skySpec(ramp: AtmosphereRamp): SkySpecification {
  return {
    "sky-color": SKY_COLOR,
    "horizon-color": HORIZON_COLOR,
    "fog-color": FOG_COLOR,
    "sky-horizon-blend": 0.5,
    "horizon-fog-blend": 0.5,
    "fog-ground-blend": 0.1,
    "atmosphere-blend": atmosphereBlend(ramp),
  };
}

/**
 * One line describing the live atmosphere for the `?perf` overlay.
 *
 * The ramp makes atmosphere strength a function of zoom, so a screenshot no longer says what
 * produced it — the same reasoning that put the terrain arm on screen. `map.getSky()` returns the
 * expression rather than the evaluated number, so the value here comes from the JS mirror.
 */
export function describeAtmosphereState(zoom: number, ramp: AtmosphereRamp): string {
  if (ramp.kind === "off") {
    return `sky ${BASE_ATMOSPHERE_BLEND.toFixed(2)} · ramp off`;
  }
  const blend = rampedAtmosphereBlend(BASE_ATMOSPHERE_BLEND, zoom, ramp.floor);
  return `sky ${blend.toFixed(2)} · ramp ${BASE_ATMOSPHERE_BLEND}→${ramp.floor}`;
}
