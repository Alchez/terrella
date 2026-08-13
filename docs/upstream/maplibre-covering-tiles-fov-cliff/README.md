# Terrain covering tiles: narrow fields of view put the tile count on a cliff

A performance report prepared for upstream [maplibre-gl-js](https://github.com/maplibre/maplibre-gl-js).
Everything here is reproducible with the library alone — `repro.html` in this directory uses the
public terrarium DEM and the demo globe style, with no application code, no patch, no
`setSourceTileLodParams` and no `setMaxPitch`.

Observed on **maplibre-gl 6.3.0**, Chrome 151, Linux, RTX 4070 Super, canvas 2560×1321 at DPR 1.

## Summary

With terrain enabled on the globe projection, `coveringTiles` returns **878 renderable terrain tiles
for a view of open ocean**, at an ordinary camera a drag can reach. The frame rate there is **4 fps**,
with a worst frame of **293 ms**. A narrower lens is worse: at `fov` 12 the same centre reaches
**1,472 tiles, 1.3 fps and a 984 ms frame**.

The cost is not a curve. It is a knife-edge in camera zoom, and its position slides with the field of
view, so every lens narrower than about 25° has some reachable camera where the count explodes.

**The tiles are real, on screen, and far too small.** All 876 project inside the viewport and tile it
exactly once, at a median of **61 px** where the scheme's own target is 512 — the same camera at the
default lens gives 20 tiles at 434 px. The selection is over-refined by about three zoom levels, which
is a defect rather than an honest cost, and the section below traces it to the 3D-distance term.

## Where

`src/geo/projection/covering_tiles.ts`. Each candidate tile gets a desired zoom, which is floored:

```ts
thisTileDesiredZ = tileZoomFunc(
    transform.zoom + scaleZoom(transform.tileSize / options.tileSize),
    distToTile2d, distanceZ, distanceToCenter3d, transform.fov);
thisTileDesiredZ = (options.roundZoom ? Math.round : Math.floor)(thisTileDesiredZ);
```

`createCalculateTileZoomFunction` sums four terms into it: the centre zoom, a 3D-distance ratio
carrying `1 / max(0.5, cos(fov/2))`, a pitch-foreshortening term scaled by `pitchTileLoadingBehavior`,
and a tile-count damping term.

## Measurements

All at centre **lon −140, lat −52** — open South Pacific, no complex terrain — pitch 60, zoom swept
**4 → 8 in 0.02 steps**, taking the peak. "median" is the median across that whole sweep, i.e. what
this camera costs at a typical zoom.

| fov | peak tiles | at zoom | median | deepest levels at the peak |
|---|---|---|---|---|
| 5 | 572 | 7.24 | 7 | z9:250 z10:322 |
| 10 | 1,026 | 6.24 | 10 | z8:158 z9:868 |
| **12** | **1,472** | 5.98 | 11 | z8:316 z9:1156 |
| 15 | 878 | 5.66 | 12 | z8:878 |
| 18 | 644 | 5.38 | 14 | z7:167 z8:477 |
| 20 | 869 | 5.24 | 15 | z7:133 z8:736 |
| 25 | 27 | 7.80 | 18 | z6:6 z7:9 z8:12 |
| 36.87 (default) | 36 | 7.48 | 21 | z4:2 z6:10 z7:12 z8:12 |

**The peak's zoom slides monotonically with the lens** — 7.24, 6.24, 5.98, 5.66, 5.38, 5.24 — which is
the single most important thing in this table. It means a comparison of fields of view taken at one
camera, or over a narrow zoom window, measures where that window happens to sit rather than what the
lens costs. Peaks here span 2.0 zoom levels.

### Cost, at fov 15, with three one-variable controls

Driven under forced continuous repaint, so no arm is merely idle — a settled MapLibre map paints only
on change and reports 0 fps for a perfectly healthy view.

| arm | tiles | fps | worst frame |
|---|---|---|---|
| **zoom 5.66, pitch 60, fov 15** | **878** | **4.0** | **293 ms** |
| zoom 5.80 — 0.14 away | 6 | 165.3 | 7 ms |
| pitch 0 — same zoom | 15 | 165.0 | 7 ms |
| fov 36.87 — same camera | 20 | 165.0 | 11 ms |

Each control changes exactly one variable and each restores 165 fps.

### The band is ~0.01 wide

At fov 15, sweeping zoom across the peak:

| zoom | 5.60 | 5.62 | 5.64 | 5.65 | **5.66** | 5.67 | 5.68 | 5.70 |
|---|---|---|---|---|---|---|---|---|
| tiles | 46 | 97 | 341 | 703 | **876** | 111 | 9 | 9 |

It collapses between 5.66 and 5.68. **A sweep coarser than about 0.02 reports a clean null**, which is
worth knowing before concluding the bug is absent on any given configuration.

### Latitude

At fov 15, zoom 5.66, pitch 60, sweeping the centre's latitude:

| lat | 0 | −4 | −12 | −20 | −28 | −36 | −44 | **−52** | −60 | −68 |
|---|---|---|---|---|---|---|---|---|---|---|
| tiles | 570 | 7 | 11 | 32 | 96 | 329 | 759 | **876** | 496 | 78 |

Mercator tiles shrink toward the poles, so the same screen area holds more of them and the sum crosses
its `floor` boundary earlier. The per-level histograms show the mass walking down the pyramid as
latitude grows — z4 at −4, z5 at −16, z6 at −24, z7 at −32, z8 by −44. **The equator is a separate
outlier** (570 against 7 one step away) that this report does not explain.

## Why: the selected tiles are 61 px on a scheme aiming for 512

The tile counts above do not by themselves say anything is wrong — a demanding view may simply need
many tiles. What settles it is asking what the selection *should* be, and the LOD scheme states its own
target: choose the level at which a tile lands on screen at about `tileSize`.

Projecting all four corners of every selected tile at the peak, against the same camera at the default
lens:

| lens | tiles | fell off screen | Σ projected area ÷ canvas | **median tile on screen** |
|---|---|---|---|---|
| fov 15 | 876 | **0** | **1.0×** | **61 px** |
| fov 36.87 | 20 | 0 | 1.2× | **434 px** |

So the 876 tiles are not spurious, not overlapping, not off-frame and not culling debris. They tile the
visible view **exactly once**, at roughly one eightieth of the area per tile that the scheme's own
target calls for. Rendering asks for ~70× more texels than the display can show. That is the defect.

**It is the distance term, not the `floor`.** Flooring a real-valued desired zoom into a quadtree is
bounded at 4× by construction, so it can explain a sharp edge and can never explain a 68× height. A
replica installed through `calculateTileZoom` reproduces the built-in count exactly (876 against 876),
and its decomposition at the peak reads:

| term | value |
|---|---|
| centre zoom | 5.66 |
| **3D-distance ratio** | **+2.76 min, +3.12 median, +3.25 max** |
| pitch foreshortening | ≈ 0 |
| tile-count damping | **exactly 0** |
| desiredZoom | **7.97 – 8.91** → `floor` **8** |

**The correct value of that distance term for the centre tile is 0** — it *is* the centre. Instead the
whole frame carries ~3 levels of it, and that reconciles independently with the pixels: 512 / 61 = 8.4 =
2^3.07. Sampled arguments show `distanceToTile2D = 0`, `distanceToTileZ = 0.0928` and
`distanceToCenter3D = 0.8777` — the geometry reporting these tiles **9.46× nearer than the centre point**
where a 60° pitch makes the true ratio **2.0**.

**Why the lens governs it.** Narrowing the field of view pushes the camera back, since
`cameraToCenterDistance = 0.5 · height / tan(fov/2)`. That inflates the numerator of the distance ratio
directly, while whatever `distanceToTileZ` measures does not scale with it, so the over-refinement grows
as the lens narrows. `fov` also enters the sum through `max(0.5, cos(fov/2))`, through
`pitchTileLoadingBehavior`, and through both bounds of the `tileCount` integrals.

**Why a cliff and not a slope.** desiredZoom across the whole set spans **0.94** — just under one
integer — so every tile crosses its `floor` boundary at the same moment instead of in ones and twos. A
wide lens spreads the frame across more than a level and the crossings dither; a narrow lens collapses
the spread and they go together. That is the mechanism for the *shape*; the magnitude is the paragraph
above.

**Not established, and stated so it is not mistaken for settled:** *why* `distanceToTileZ` comes out
about 9× too small here. A units or reference-frame mismatch in the globe covering-tiles details
provider is the hypothesis and it is untested. This report does not claim a root cause.

**Separately, nothing bounds the returned set's size.** `coveringTiles` has no cardinality budget at
all — and `TerrainTileManager` sets `this.maxzoom = 22` in its constructor and never narrows it to the
DEM source's own depth, so at `fov` 5 above, tiles are selected at z10 from a source declaring
`maxzoom: 12`. That is a small, separate defect: the useful ceiling is `source.maxzoom + 1`, since
`getSourceTile` feeds a render tile at zN from DEM z(N−1).

## What this does NOT claim

- **It is not the terrain elevation bounding volume.** That was the first hypothesis, and it is
  eliminated with a positive control: substituting `getMinMaxElevation` wholesale in the explosive
  regime gives 822 tiles for the identity, 818 for a flat band, and 919 for an absurd −200…+800 km
  band, with a call counter confirming the substitution was reached (4,470 and 6,670 calls). The knob
  demonstrably moves the output; the realistic answer does not move.
- **It is not `maxZoomLevelsOnScreen`.** Measured at a failing camera: 824 tiles at the default 9.314,
  820 at 11, 731 at 16, 665 at a visually broken 20.
- **It is not `setSourceTileLodParams`.** Stock parameters throughout — the reproduction never calls it.
- **It is not complex terrain.** The centre is open ocean; the DEM there is nearly flat.
- **No fix is proposed.** Moving the field of view is a dodge, not a fix — the table above shows it
  relocates the cliff rather than removing it.
- **One machine, one canvas size.** The tile count scales with screen area, so the absolute numbers are
  not portable; the shape is.

## Relationship to existing issues

Eight threads read in full rather than matched on their titles. **None of them is this failure class** —
globe projection, terrain on, stock LOD parameters, default `maxPitch`, a narrow lens, and a cliff in
camera zoom — which is why this is offered as a new report rather than a comment on an existing one.

### The one that matters

**[#7146](https://github.com/maplibre/maplibre-gl-js/issues/7146)** (open) — *Low resolution tiles
loading with low VFOV (≤10°) and high pitch*. **This is the same function seen from the other side**,
and the reason this report exists. The fix proposed in that thread adds `scaleZoom(36.87 / fov)` for
lenses narrower than the default, which at `fov` 15 is **+1.30 zoom levels** — taking the decomposition
above from 7.44 to 8.74, i.e. `floor` 7 → 8, one whole quadtree level deeper at a camera that already
selects hundreds of tiles. This report is the counter-example: the same lens widths, the same function,
two orders of magnitude too *many* tiles at a nearby camera. **Any fix that adds zoom for narrow lenses
should be measured against the cameras in the table above.**

### The lineage behind it, all pointing one way

**[#2444](https://github.com/maplibre/maplibre-gl-js/issues/2444)** *Terrain is not sharp at low field
of view (FOV)* (closed) · **[#4940](https://github.com/maplibre/maplibre-gl-js/issues/4940)** *Raster
satellite blurred in Terrain3D at vertical field of view < 15 deg* (closed) ·
**[#4779](https://github.com/maplibre/maplibre-gl-js/pull/4779)** *Fix level of detail at high pitch*
(merged 2024-11-04).

Three reports and one merged fix, all of the form "narrow lens, too little detail", all answered by
adding zoom. The whole recorded pressure on `calculateTileZoom` runs in that direction, so the
over-refinement measured here has had nothing pushing back on it. Note that **#4940's title puts 15° on
the boundary** — the same lens this report measures at 878 tiles.

### Same symptom, different mechanism

**[#5368](https://github.com/maplibre/maplibre-gl-js/issues/5368)** (open) — *Excessive renderable tiles
generated when terrain is activated*. The headline symptom matches, and the mechanism does not: it is
diagnosed there as a **culling** defect, the frustum test treating a tile as a box spanning its
min-to-max elevation rather than a flat sheet, so unseeable neighbours are requested. This is a
**zoom-selection** defect, and the elevation ladder above is what separates them — under #5368's
mechanism, flattening the elevation band would have collapsed the count, and it moved 822 → 818.

### Reachable only outside this configuration

- **[#8049](https://github.com/maplibre/maplibre-gl-js/pull/8049)** (open PR) — *Fix terrain tile detail
  near a pitched camera*. Gated on `transform.pitch > maxConstantZoomPitch`, and
  `maxConstantZoomPitch` is `clamp(78.5 − zfov/2, 0, 60)`, which is **60** at `fov` 15 — so with
  MapLibre's `defaultMaxPitch` of 60 and no `setMaxPitch` call, the strict inequality is unreachable
  here, and unreachable for anyone at the default cap and any `fov` ≤ 37. It also points the other way,
  giving near terrain *more* detail (its author reports roughly 3× the near-camera tiles at pitch 85,
  bounded at two extra levels by a `distanceZ / 4` floor), so where it is reachable it would compound
  this rather than relieve it.
- **[#8048](https://github.com/maplibre/maplibre-gl-js/pull/8048)** (open PR) — *Prevent source LOD
  settings from affecting internal terrain tiles* — and its parent issue
  **[#7699](https://github.com/maplibre/maplibre-gl-js/issues/7699)**. Both are gated on
  `setSourceTileLodParams`, which this reproduction never calls. **They do corroborate the magnitude**:
  #8048's author measured `setSourceTileLodParams(2, 1)` taking the internal RTT selection from **44 to
  3,406 tiles** on `main` — the same order as the counts here, reached by an unrelated route. That is
  independent evidence that this function's output is unbounded, rather than that the camera here is
  exotic.

  *Note for anyone reproducing the decomposition above:* the replica is installed by assigning
  `source.calculateTileZoom` and relying on the terrain tile manager passing it through, which is
  exactly the path #8048 removes.

## Running the reproduction

`repro.html` is standalone. Serve the directory over http (the DEM source needs a real origin):

```
python3 -m http.server 8099
```

then open `http://localhost:8099/repro.html` and press **Sweep zoom at each fov**.

The page prints its own configuration, because three things change the answer:

- **Canvas size and DPR.** The count scales with screen area; a small window will not reach these
  numbers.
- **The DEM source's tile size.** Terrain covers at twice it, so the centre zoom fed to
  `calculateTileZoom` is `transform.zoom + log2(512 / that)`. The 256 px terrarium source used here
  puts the centre zoom at the camera zoom; a source declaring 128 px puts it one level deeper and moves
  the whole table by about one zoom level.
- **The sweep step.** The band is ~0.01–0.02 wide. A coarser step will find nothing.

**Keep the tab focused, and watch for the abort banner.** A background tab throttles
`requestAnimationFrame` and every arm then reads the same stale number; a page whose WebGL context has
been lost keeps answering every query with the last good frame. The page counts its own render events
per arm and aborts loudly on context loss, because both faults were met while building it and both read
as clean data.
