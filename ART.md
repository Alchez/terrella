# Art-direction levers — tuning cheat sheet

The knobs that shape the final look, what each one does, and which are safe to play with.
Baseline = the v2 look from the 2026-07-05 tuning session (constants in PLAN.md decision
log; canonical render `blender/renders/india_hero_8k_candidate.png`, v1 kept for history). Everything here is about matching the Ramspott "Neutral" reference: soft
raytraced shadows, heavy vertical exaggeration, warm sand/rose land, desaturated teal sea
with visible shelf bathymetry.

## Levers (play with these)

### Vertical exaggeration — Displacement node → Scale
- Baseline `8.0e-6` ≈ **15×**. Conversion: 1 Blender unit = 1,872,643 m, so
  `scale = multiplier × 5.34e-7` → 5× = `2.7e-6`, 10× = `5.3e-6`.
- More exaggeration = more drama, longer shadows, but ranges start reading as walls.
- **Tune as a pair with sun altitude** — raising one and lowering the other can cancel
  out in shadow length while changing the shape of the terrain. Sweep the pair, not each alone.

### Sun altitude & azimuth — Sun object → Rotation
- Baseline `(44°, 0°, −45°)`. X = 44° tilt → sun sits **46° above the horizon**;
  Z = −45° → light from the NW-ish (cartographic convention — relief reads as relief,
  not inverted).
- Exaggeration and altitude were tuned as a pair (shadow length ∝ height × cot(altitude));
  change one and you must re-solve the other to keep shadow drama constant.
- **Azimuth stays NW-ish globally** — it's a locked convention, not an art lever.

### Shadow softness — Sun lamp data → Angle
- Baseline `5°`. This is the sun's angular size: bigger = softer penumbras.
- ~0.5° = crisp architectural shadows; ~10° = a diffuse look.
- 3° vs 5° is invisible at 2K test res (penumbra ≈ shadow length × tan(angle) —
  sub-pixel); only judge this lever at 8K.

### Light balance — Sun Strength + World
- Sun Strength baseline `3`; World baseline `F2E7D5` @ strength `0.3` — the fill light:
  it decides how dark the shadow floor is, tints everything, and is also the backdrop
  color around the map plane.
- If shadows go pure black, raise World strength before raising Sun — sun controls
  contrast, world controls the floor.

### Land color ramp (elevation-keyed)
- Baseline: heights mapped 0→6,000 m onto ramp position 0→1 (the cap), stops
  `E9D9C0@0.0 / D7AC8E@0.083 / CE9880@0.25 / C9AD97@0.5 / E8DFD2@0.75 / F6F1E8@1.0`
  (elevation of a stop = position × 6,000 m).
- Shape: rose deepens to ~1,500 m, then *lightens* to bone/near-white — high terrain
  is pale and shadow-carved (the Ramspott move); above the cap clamps to snow-white.
- The cap is itself a lever: it decides where the palette "runs out" — everything
  above it gets the last stop's color.
- Gotcha: stops re-sort by position — never identify a stop by its index; click it
  and read its color/position.

### Sea color ramp (depth-keyed)
- Baseline: depths mapped 0→−3,000 m onto position 0→1, stops
  `C6E4E2@0.0 / 98C5C8@0.15 / 649BA4@0.4 / 487D8A@1.0`.
- The signature shelf-sea look lives in the **low-position stops** (0–0.15): that's the
  0–450 m band — Palk Strait, Gulf of Khambhat, the Sundarbans shelf.
- The −3,000 m cap controls how fast open ocean saturates to the darkest teal.

### View transform — Render Properties → Color Management
- **Decided: Standard** (2026-07-05). AgX's highlight desaturation greyed the sand and
  teal; a map has no speculars, so filmic rolloff buys nothing. Ramp hexes now render
  near-verbatim — treat this as locked, not a lever.

### Borders (composited overlay — current baseline 2026-07-06)
- Drawn by pipeline/overlay_borders.py over the finished render; iterate freely,
  no re-render needed. Alignment is verified by the coastline oracle before any tuning.
- **Judge width on the 2K preview (≈ fit-to-screen), never on the 1:1 crops** — the
  first attempt (4 px) looked right in crops and vanished at viewing scale.
- Baseline: land borders white 95% @ 10 px, casing #3D2B1F 35% @ 14 px; disputed/LoC
  same + dash [30, 20]; maritime white 80% @ 7 px, casing 25% @ 10.5 px, dash [40, 25].
  All values live in the style dicts at the top of the script.
- Casing = wider dark stroke under the white ink; dashes are cased per-dash (same
  path + dash phase). It should be invisible as a feature — only felt over pale terrain.
- Not levers: worldview (NE default, site-wide — editorial policy, see PLAN.md) and
  which classes are dashed (Disputed / Line of control / Indefinite / Indeterminant;
  DBF field is uppercase `FEATURECLA`).

## Fixed (don't touch without re-litigating)

- Orthographic camera, straight down, ortho scale 2.06 — framing is data-driven,
  becomes per-country math in Phase 1.
- Displacement Midlevel 0, plane scale, adaptive subdivision + dicing rates.
- Mask wiring: Non-Color, Closest interpolation, 0/255 PNG mask.
- Resolution ratio (2048×2109 test / 7680×7906 final) — from the raster's aspect.
- No Map Range with reversed ranges — Math Multiply + Clamp only.

## Tuning protocol

- Reference image on one screen, render on the other. **One lever per iteration**, F12
  at test res (2048), compare against `india_look_v1.png`.
- Save keeper renders as `renders/india_<lever>_<value>.png` so A/Bs survive.
- Watch for scroll-wheel drift: hovering a value field and scrolling silently edits it
  (that's how the `_check` render happened). After a session, audit against baseline.
- When it looks right: record the final constants in PLAN.md (that's the Phase 0 exit
  checkpoint — they become global for all ~195 countries).
