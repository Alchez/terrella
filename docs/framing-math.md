# How a country becomes a framed render

Every hero render shares one *look* — the same sun, the same colors, the same 15× vertical exaggeration (the "Locked global constants" in PLAN.md). What changes from country to country is only *geometry*: where the camera looks, and how numbers convert between the real world and Blender's little stage. This page explains each conversion in plain English, with the formulas alongside.

The chain, end to end:

```
country name ──frame_country.py──▶ frame (a lon/lat box)
frame ──render_prep.py──▶ projection + warped rasters + frame.json
frame.json ──scene_build.py──▶ Blender scene (+ render)
frame.json ──overlay_borders.py──▶ borders drawn in exactly the camera's view
```

`frame.json` is the hand-off: one small file per country holding every derived number. Blender's Python cannot read geographic metadata, so these numbers must be computed outside and handed over.

## Step 1 — the frame

The frame is the rectangle of the world the poster shows. It comes from the country's bounding box in the Natural Earth data, grown a little so the country doesn't touch the edges:

- **Padding:** 5% of the country's larger side (north–south or east–west), added to all four sides.
- **Rounding:** edges pushed outward to the next 0.1°, purely so frames are tidy to read and compare.

Nepal's bounding box is 80.03–88.17°E / 26.34–30.42°N; padded and rounded it becomes the frame **79.6–88.6°E / 25.9–30.9°N**.

Known limitation: countries with far-flung territories (France + French Guiana) or antimeridian crossers (Fiji) get absurd frames from this rule — they are on the plan as a separate per-country-overrides item.

## Step 2 — the projection

A camera looking straight down at the scene means the finished poster *is* a flat map — so the choice of how to flatten the round Earth (the projection) is baked into the image. Two requirements drive the choice:

- **Equal-area:** a square kilometer should cover the same pixels everywhere in the frame, or terrain would look stretched in one part of the country versus another.
- **Centered on the frame:** flattening distorts least near the projection's "home"; every country deserves its own home rather than borrowing a neighbor's. This is the same reason national atlases each use a national projection.

We use the Albers equal-area conic. The picture to have in mind: rest a paper cone over the globe so it touches along two circles of latitude, trace the surface onto the cone, unroll it. Along those two touch lines (the **standard parallels**) there is no distortion at all, and between them it stays tiny. The rule for placing them is a cartography textbook standard:

- standard parallels: **1/6 of the frame's latitude span in from its south and north edges** — `lat₁ = S + (N−S)/6`, `lat₂ = N − (N−S)/6`
- projection center: the frame's middle — `lat₀ = (S+N)/2`, `lon₀ = (W+E)/2`

For Nepal (25.9–30.9°N): parallels at 26.73° and 30.07°, centered at 28.4°N 84.1°E.

## Step 3 — the warped grid

`render_prep.py` re-samples the fused heightfield from plain lon/lat degrees into this projection, producing the raster Blender will actually displace. Its `--width` sets the pixel width, bounded on both sides: don't exceed the source data's own width (upsampling invents nothing), and keep it near the render width (the Switzerland QA, 2026-07-08, showed this is what prevents "bumpy" over-detail — the warp grid low-passes anything finer than the render can show, so displacement can't pick up sub-pixel noise). The height follows from the frame's shape. One number falls out that everything below depends on: the frame's true width in meters, `extent_w = width_px × meters_per_pixel`.

## Step 4 — the scene numbers

Here is the one idea everything else hangs on: **the displacement plane in Blender is always 2 units wide, no matter how wide the country's frame really is.** India's 3,745 km and Sri Lanka's 299 km both become 2 Blender units. So:

> **1 Blender unit = half the frame width, in meters.**

Every scene number is just this conversion applied to a locked look constant:

- **Plane height** — the plane must have the same shape as the raster: `plane_height = 2 × height_px / width_px`. Wider-than-tall countries (Nepal) get a plane shorter than 2; taller-than-wide ones (Sri Lanka) get taller than 2.
- **Displacement scale** — the heightfield stores real meters. Multiplying by scale must turn meters into Blender units *and* apply the locked 15× exaggeration: `scale = 15 ÷ (extent_w / 2)`. This is why the number is different per country while the mountains' *relative* drama is identical: a small frame means each Blender unit is fewer meters, so each meter of rock is a bigger fraction of a unit. Copying India's value onto Switzerland would exaggerate ~100× — mountains as walls.
- **Camera size (ortho scale)** — an orthographic camera has no zoom, just a window width in scene units. Blender applies `ortho_scale` to the *larger* side of the render. We set it to the plane's larger dimension × **1.0006**, so the picture is a hair bigger than the plane and the map never touches the frame edge: `ortho = max(2, plane_height) × 1.0006`.
- **Resolution** — width is fixed at 7680 px for every hero; height follows the raster's shape: `res_y = round(7680 × height_px / width_px)`. (Very tall countries make this explode — Sri Lanka wants 7680×12498 — which the per-country-config item will cap with overrides.)

Worked examples (from the real `frame.json` files):

| | India (pinned) | Nepal | Sri Lanka |
|---|---|---|---|
| frame (°) | 66–99 E, 4–38 N | 79.6–88.6 E, 25.9–30.9 N | 79.4–82.1 E, 5.7–10.1 N |
| frame width (km) | 3,745 | 902 | 299 |
| raster (px) | 16384 × 16866 | 8192 × 5106 | 3072 × 4999 |
| plane (units) | 2 × 2.058 | 2 × 1.2466 | 2 × 3.2546 |
| displacement scale | 8.0e-6 | 3.33e-5 | 1.00e-4 |
| ortho scale | 2.06 | 2.0012 | 3.2565 |
| render (px) | 7680 × 7906 | 7680 × 4787 | 7680 × 12498 |

## The India exception

India's scene was built by hand during Phase 0, and several numbers were typed in rounded (plane 2.058 instead of 2.05884, ortho 2.06 instead of 2.06007, displacement 8.0e-6 instead of 8.0113e-6 — all within 0.15%). The approved v3 hero is baked with those values, so India's `frame.json` is **hand-authored with the historical numbers** and `render_prep.py` never overwrites an existing `frame.json`. That is the pinning mechanism, and the same file is where future per-country overrides will live. Every new country gets the exact formula values.

## Checking it worked — the coastline oracle

`overlay_borders.py --mode oracle` draws the Natural Earth coastline through the same projection and camera model, then measures how much of it lands on the rendered land/sea boundary. If the framing math were wrong anywhere, the whole line would miss by kilometers in one direction — unmissable.

Tolerances are in **ground meters, not pixels** (600 / 1200 / 2500 m; the bar is 90% within 2500 m). Judged in pixels the oracle would silently mean a different thing per country: 5 px is 2.4 km on India's render but only 650 m on Sri Lanka's finer one — which is how Sri Lanka first "failed" the oracle while being perfectly aligned. The residual disagreement (both countries score ~57–65% at 600 m) is the two *data products* differing — Natural Earth's generalized 1:10m line versus the 30 m satellite water mask — biggest around lagoon spits and shifting sandbars, ~1–2 km at worst. That is the noise floor the tolerances sit above.

## Glossary

- **bounding box (bbox):** the smallest west/south/east/north rectangle containing a shape.
- **frame:** our padded bbox — the window of the world one hero shows; also the fusion window and projection home.
- **projection:** any recipe for flattening the round Earth onto a plane; every one distorts something.
- **Albers equal-area conic:** the projection we use; preserves areas, distorts least near its two standard parallels.
- **standard parallels:** the two latitudes where a conic projection touches the globe — zero distortion there.
- **CRS (coordinate reference system):** the machine-readable string naming a projection and its parameters.
- **warping / resampling:** recomputing a raster's pixels onto a new grid (here: from lon/lat degrees into Albers meters).
- **m/px:** ground meters covered by one pixel; smaller = finer detail.
- **orthographic camera:** a camera with no perspective — parallel rays, so the image is a true plan view; `ortho_scale` is the width of its window in scene units.
- **displacement:** Cycles pushing mesh surface up per-pixel by the heightfield value × scale.
- **frame.json:** the per-country contract file carrying all numbers above from the GDAL world into the Blender world.
