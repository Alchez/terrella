# Art-direction levers — tuning cheat sheet

The knobs that shape the final look, what each one does, and which are safe to play with.
Baseline = `blender/renders/india_look_v1.png` (constants recorded in PLAN.md decision log,
2026-07-05). Everything here is about matching the Ramspott "Neutral" reference: soft
raytraced shadows, heavy vertical exaggeration, warm sand/rose land, desaturated teal sea
with visible shelf bathymetry.

## Levers (play with these)

### Vertical exaggeration — Displacement node → Scale
- Baseline `5.3e-6` ≈ **10×**. Conversion: 1 Blender unit = 1,872,643 m, so
  `scale = multiplier × 5.34e-7` → 5× = `2.7e-6`, 15× = `8.0e-6`.
- More exaggeration = more drama, longer shadows, but ranges start reading as walls.
- **Tune as a pair with sun altitude** — raising one and lowering the other can cancel
  out in shadow length while changing the shape of the terrain. Sweep the pair, not each alone.

### Sun altitude & azimuth — Sun object → Rotation
- Baseline `(55°, 0°, −45°)`. X = 55° tilt → sun sits **35° above the horizon**;
  Z = −45° → light from the NW-ish (cartographic convention — relief reads as relief,
  not inverted).
- Altitude range worth sweeping: 25–45° above horizon (X rotation 45–65°). Lower sun =
  longer shadows, more texture in flat terrain, but big ranges black out.
- **Azimuth stays NW-ish globally** — it's a locked convention, not an art lever.

### Shadow softness — Sun lamp data → Angle
- Baseline `3°`. This is the sun's angular size: bigger = softer penumbras.
- ~0.5° = crisp architectural shadows; ~10° = a diffuse look
- The Ramspott look is *soft but present* — likely 2–5°.

### Light balance — Sun Strength + World
- Sun Strength baseline `3`. World (background) color/strength is the fill light:
  it decides how dark the shadow floor is and tints everything.
- If shadows go pure black, raise World strength before raising Sun — sun controls
  contrast, world controls the floor.

### Land color ramp (elevation-keyed)
- Baseline: heights mapped 0→2,000 m onto ramp position 0→1 (the cap), stops
  `E9D9C0@0.0 / D7AC8E@0.25 / CE9880@0.5 / C68A76@1.0`.
- The 2,000 m cap is itself a lever: it decides where the palette "runs out" —
  everything above the cap gets the last stop's color.
- **Open agenda item: a pale/snow stop near position 1.0 for the high Himalaya**
  (the reference style often lightens extreme elevations).
- Gotcha: stops re-sort by position — never identify a stop by its index; click it
  and read its color/position.

### Sea color ramp (depth-keyed)
- Baseline: depths mapped 0→−3,000 m onto position 0→1, stops
  `C6E4E2@0.0 / 98C5C8@0.15 / 649BA4@0.4 / 487D8A@1.0`.
- The signature shelf-sea look lives in the **low-position stops** (0–0.15): that's the
  0–450 m band — Palk Strait, Gulf of Khambhat, the Sundarbans shelf.
- The −3,000 m cap controls how fast open ocean saturates to the darkest teal.

### View transform — Render Properties → Color Management
- Baseline **AgX** (Blender default): filmic, desaturates bright areas, gentle rolloff.
- A/B against **Standard**: punchier, truer to the ramp hexes, but can clip.
- This multiplies *every* color decision — settle it early in the tuning session,
  before fine-tuning ramp hexes.

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
