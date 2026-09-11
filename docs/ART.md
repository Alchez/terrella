# Art-direction levers: tuning cheat sheet

The knobs that shape the look, what each is set to, and what moving it costs. The target is the Ramspott "Neutral" reference: soft raytraced shadows, heavy vertical exaggeration, warm sand land, desaturated teal sea with visible shelf bathymetry, data-driven snow.

**The code is the system of record.** Shared constants in `pipeline/look/palette.py`, the hero and tile rig in `pipeline/render/scene_build.py`, per-body geometry in `pipeline/bodies.py`, per-country knobs in `config/countries.toml`. Where a row here and the code disagree, the code is right and the row is the bug, so a lever change updates its row in the same edit.

Ramp constants are Earth's unless a row says otherwise. Each body resolves its own `Look`, so every cost quoted here is Earth's, and docs/PROCESS.md § What a look change costs carries the measured bill.

## Lever index (every tunable, by what a pull costs)

### Both surfaces (`palette.py`), hero sweep ~10–13 h plus tile restage ~29 min plus caps ~3:05

| Lever | Value | Section |
|---|---|---|
| `LAND_STOPS` (+ `LAND_MAX_M`) | 6 stops; Earth's domain 0–6000 m, but the ENDS are the body's, a `Surface` carrying `origin_m` and `extreme_m` | § Land color ramp |
| `MARS_LAND_STOPS` | 6 stops over −6000…+6100 m, sharing no colour object with Earth, at **0.71× Earth's shipped land** | § Land color ramp |
| `SEA_STOPS` (+ `SEA_MIN_M`) | 6 shelf-weighted stops, 0…−6000 m | § Sea color ramp |
| `LAKE_STOPS` (+ `LAKE_MAX_M`) | 3 stops; stop 0 == `WATER_RGB`, far end 1642 m (Baikal) | § Inland water |
| `WATER_RGB` | `8EC6C4`, pinned relationally: sea surface +7% | § Inland water |
| `SNOW_RGB` / `SNOW_SHADOW_RGB` | `E8F1F6` / `B0C7DB` | § Snow |
| `ICE_RGB` / `ICE_SHADOW_RGB` | `D4E4F0` / `9CB8D2` | § Sea ice |
| `SUN_ALT_DEG` | 45.0: hero X-tilt and tile light both derive from it | § Sun altitude |
| `EXAGGERATION` | 15.0, the authored value, read by no path; every surface reads `Body.baked_exaggeration`, pinned equal to it for Earth | § Vertical exaggeration |
| `LUT_STEP_M` | 1.0 m: ramp LUT resolution, fidelity rather than hue | § Land color ramp |

### Hero only (`scene_build.py`, `render_prep.py`), the 203-country sweep

| Lever | Value | Section |
|---|---|---|
| `sky_view_strength` (countries.toml) | 0.20 default; **0.0** volcanic islands, **0.38** flat Qatar and Paraguay | § Sky-view shading |
| `resolution_floor_m` (countries.toml) | 60 default, auto-engaging above 5× upsample; **0** exempts andorra | § Resolution floor |
| `sun_angle` | 12° disc, the shadow penumbra | § Shadow softness |
| `sun_strength` / `world_strength` / `world_rgba` (`RIG`) | 3.0 / 0.3 / achromatic | § Light balance |
| `fill_rotation` / `fill_angle` / `fill_strength` | alt 60° az 135° / 10° disc / 0.45, being 15% of sun | § Fill sun |
| `FRAME_MARGIN` / `HERO_LONG_EDGE` (render_prep) | 1.0006 / 7680 px | § Vertical exaggeration |
| `view_transform` (`RIG`) | Khronos PBR Neutral | § View transform |
| render quality (`samples` 4096, `adaptive_threshold` 0.01, `clamp_indirect` 10) | cost, not look | § View transform |

### Tiles and caps, one cost tier and it is a whole body

Every tile pixel comes off Cycles, so any look change reaching a recipe restages every block, plus a re-cut, an upload and a Worker deploy. There is no `--knob` flag: an arm is a separate checkout plus a scratch mosaic.

| Lever | Value | Section |
|---|---|---|
| `exaggeration` (bodies.py) | 15 on Earth, 20 on Mars, read by tiles and caps alike | § Vertical exaggeration |
| NH ice `ICE_LO` / `ICE_BAND` / `ICE_MAX_ALPHA` (seaice.py) | 0.55 / 0.40 / 0.85 | § Sea ice |
| SH ice `SH_ICE_LO` / `SH_ICE_MAX_ALPHA` (seaice.py) | 0.62 / 0.55 | § Sea ice |
| `lake_depth.LAKE_CURVE` | log1p, hero only, through `render/lake_mask.py` | § Inland water |
| `CAP_PX` / `CAP_WEBP_QUALITY` / `edge_lat` (cap_pass.py) | 8192 / 85 / ±78° | § Polar caps |

### Compositing and web, seconds to minutes

Border style dicts (`overlay_borders.py`) and the hero variant rungs (`hero_variants.py`) regenerate without a render. Everything else on the web side is a look value living in the module that reads it: `countryHighlight.ts` for the highlight, `skyAtmosphere.ts` for the atmosphere ramp, `terrainSource.ts` for the displacement ramp, `Globe.astro` for camera and chrome. Each ships with `pnpm build`.

## Levers (play with these)

### Vertical exaggeration: global constant, per-country number

- Baseline **15× on Earth**, `exaggeration` on the body in `bodies.py`, which every multi-body path reads. `EXAGGERATION` in `palette.py` is the authored constant Earth's field is pinned to, and nothing in production reads it directly.
- The number in the scene is `displacement_scale` in frame.json, and it varies per country because a frame's width does (India 8.0e-6, Nepal 3.3e-5, Sri Lanka 1.0e-4; docs/framing-math.md). Copying one country's scale onto another multiplies exaggeration by the frame-width ratio.
- **Adjust globally:** `EXAGGERATION` and `Body.baked_exaggeration` together, a test failing if you move one alone, then regenerate frame.json per country.
- **Adjust one country:** edit `displacement_scale` in its frame.json, legitimate only as a recorded pathology override. Per-country drama re-litigates the series promise: same border, two posters, same mountain height.
- **Tune as a pair with sun altitude**: shadow length is proportional to height × cot(altitude).

### Sun altitude & azimuth: `palette.SUN_ALT_DEG` → `SUN_ROTATION` (scene_build.py)

- Baseline **45° above the horizon**, shared: the hero X-tilt is `90 − SUN_ALT_DEG`, so one edit moves both surfaces.
- Z = −45° puts the light NW-ish, the cartographic convention, so relief reads as relief rather than inverted. **Azimuth stays NW-ish globally**: a locked convention, not an art lever.

### Shadow softness: `sun_angle` (scene_build.py)

- Baseline **12°**, the sun's angular size. About 0.5° gives crisp architectural shadows, beyond about 15° goes diffuse.
- It is the jagged-edge lever and not the depth lever, having lost to the fill sun on depth in the A/B that adopted both. Judge at 8K, since penumbra is sub-pixel at 2K.

### Fill sun: shadow floor with modeling (`fill_*` on `RIG`, scene_build.py)

- Baseline: a shadowless second sun from the SE, `fill_rotation` 60° up on the opposite azimuth, `fill_strength 0.45` being **15% of the main sun**, `fill_angle 10°`, `use_shadow` off.
- It re-lights shadowed faces directionally, so gullies and spurs keep modeling where the main sun cannot reach. This, not world strength, is the fix for "shadows are hiding texture".
- Self-regulating: fill only matters where resolved slopes are steep (fine grids, Switzerland) and barely registers on coarse ones (India), so one global strength behaves per-country. Swept 10/15/20%: 15 balanced, 10 defensibly moodier.
- **It is why the tiles work at all.** A single 45° sun on the 15×-exaggerated grid turns a 4° real slope into 46°, past the sun, and the face goes to zero light: measured **43.7% of the Alps at zero**, which any fill at or above 0.10 clears everywhere. Flat country is untouched (Amazon 0.02%), so if flat terrain ever moves, something is broken.

### Land color ramp (elevation-keyed): `palette.LAND_STOPS` + `LAND_MAX_M`

- Baseline: 6 stops at positions 0 / 0.083 / 0.25 / 0.5 / 0.75 / 1.0 over 0→6000 m, a stop's elevation being position × `LAND_MAX_M`. Stored linear; scene_build derives its ramp from them and the tile LUT samples them at `LUT_STEP_M`.
- Shape: rose deepens to about 1,500 m then lightens, staying in the **warm sand register all the way up**. A near-white top double-signals snow and misfires on high deserts such as Ladakh and Tibet. **White and blue belong to the snow mask alone.**
- Mars is monotone in luminance by choice: it is really brightest at both ends, so fidelity would put Hellas and Olympus in one colour.
- **Adjust:** the palette constants. In-blend gotcha: stops re-sort by position, so never identify one by index; colour writes are safe, position writes invalidate.

### Snow: mask + color (heroes: `snow_mask.py`; colour: `palette.SNOW_RGB`)

- Data, not paint: `snowmask.png` from ESA WorldCover class 70, permanent snow and ice only. The shader branch keys on the file existing, so with no mask the graph is identical to pre-snow.
- Colour baseline `E8F1F6`. The **cool cast is the signal**: at continental scale it separates snow from pale high terrain, and relief shading reads through it.
- **The mask itself is not a lever**, dataset and class being pinned provenance.
- The contrast budget on full snow is the luminance gap `SNOW_SHADOW_RGB → SNOW_RGB`, **43.9 DN, and that is all there is.** The ice has whatever relief the DEM gives it, so REMA and ArcticDEM are the real lever there rather than any colour term.

### Sea color ramp (depth-keyed): `palette.SEA_STOPS` + `SEA_MIN_M`

- Baseline: 6 stops at positions 0 / 0.033 / 0.133 / 0.333 / 0.633 / 1.0 onto 0→−6000 m, shared by both surfaces. The signature shelf-sea look lives in the **low-position stops**, the 0–450 m band.
- `SEA_MIN_M` controls how fast open ocean saturates to the darkest teal; the deep stops keep abyssal plains varying instead of flatlining.

### Sea ice: TILES + caps (`ICE_*` in `look/seaice.py`; colours in `palette.py`)

- The sea-side mirror of snow: an OSI SAF annual ice-frequency climatology (1991–2020) drives a translucent white overlay over the bathymetry, gated on ocean, landing on the Mercator tiles and both caps through one producer so the two cannot disagree at the seam.
- **`ICE_LO` / `ICE_BAND` (0.55 / 0.40)**, a smoothstep on frequency with no latitude term. `ICE_LO` is the "how much seasonal fringe" knob: raise for less ice. It cannot move the perennial core, which saturates below 0.95.
- **`ICE_MAX_ALPHA` (0.85)** tops out below opaque so year-round pack stays a touch see-through and deep bathymetry glows through.
- **`ICE_RGB` / `ICE_SHADOW_RGB`** are a notch cooler and dimmer than snow's, so floating ice reads distinct from the land ice-sheet without a hard blue/white split.
- **Not a lever: the dataset and period.** The climatology is winter-weighted, and a recent-data check moved the rendered extent by −4.2%, invisible. Reflecting the September-minimum decline would take a different reduction in `download_seaice`, not a knob.
- **Adjust:** the `ICE_*` constants plus palette colours. These are live, recorded in the producers' recipe, so a change restages every block and both caps. The climatology rebuilds via `download_seaice.py --build-only --force` in about 40 s.

### Polar caps: the pole look (`tile/cap_pass.py`, raytraced)

- Web Mercator cannot reach the poles, and **no flat cap colour works**: dark reads as a hole and pale as a plug, the problem being flatness rather than hue.
- **The look:** deep ocean floor under floating sea ice, draped over the real uncapped bathymetry, in the Patterson/Blue-Earth school.
- **Delivered as AEQD caps via a MapLibre custom layer**, not baked into Mercator tiles. AEQD's radius is proportional to colatitude, which the frontend's linear-colatitude UV assumes, so the projection cancels on the globe. Chosen over EPSG:3031, whose radial law would force a frontend rewrite for no visible gain.
- **North** takes a baked dark coastline (`COAST_RGB`, muted steel-blue), a white coast vanishing between white snow and white ice. **South** takes none, white ice on teal self-separating, and forces snow white over Antarctic land (`snow.antarctic_snow_mask`) to close the gaps NSIDC-0791 leaves and RGI's region 19 does not reach. Its sea ice is toned down because Antarctica is a continent ringed by a mostly-seasonal belt where the NH-strength climatology read as a bright halo.
- **Production assets:** 8192² WebP q85 at `web/public/caps/`. The web layer reads `caps.json` rather than copying pipeline constants; constrained GPUs clamp to `MAX_TEXTURE_SIZE`, so mobile effectively ships 4096.

### Sky-view shading: heroes post-render (`pipeline/look/sky_view.py`)

- Burn-only horizon sky-view-factor from `heightfield.tif`, darkening land valleys for topographic depth so flat countries read, leaving open ground at rendered brightness. Applied by `batch.py` after the render, before the atomic promote. Land only.
- **Per-country strength** in `config/countries.toml`. **Default 0.20**, since 0.38 mudded alpine depth; **0.0** on 7 volcanic islands where the burn blackens dendritic drainage into dark pinecones; **0.38** on flat Qatar and Paraguay, the original reason it exists. The distinction is morphological, so it is a curated list rather than a formula.
- Chosen over per-country adaptive exaggeration, which breaks consistent vertical scale, and over in-Blender Cycles AO, which dims the scene, is grainy, and costs +2.5 min per render.

### Resolution floor: heroes (`render_prep.py`, `resolution_floor_m`)

- A tiny country's frame warps to 8192 px, upsampling the 30 m DEM far past its source resolution (San Marino 11×), which magnifies along-track striping: the render reads like re-assembled shredded paper.
- **Fix:** a **60 m box-mean lowpass** of the warped heightfield, auto-engaging only above 5× upsample, so it selects the microstates by geometry and never softens larger countries. Unlike the pinecone list this is a formula, striping severity being a clean function of upsample factor, and it caught nauru where a hand list missed it.
- **Adjust:** per country, **0 to exempt** a borderline alpine case such as andorra where the floor softened real ridge detail. Pixel values move, the grid does not, so no re-pin but a re-render.

### Inland water: `palette.WATER_RGB` + `LAKE_STOPS` (both surfaces)

- Lakes and rivers come from the WBM masks; the flat tint `8EC6C4` is **pinned relationally to the sea-surface stop (+7%)** and shared by import, so it cannot strand when the sea ramp moves.
- **Lake depth is depth-keyed, not flat:** GLOBathy depths drive `LAKE_STOPS` through `LAKE_CURVE` (log1p), calibrated to published max depths within 1%. Heroes wire it through `lake_mask.py`; an undeclared `lakedepth.tif` gives a flat graph, so lake-less render dirs stay renderable.
- **Depth is tint-only, NEVER displacement**: at 15× Namtso becomes a 1.5 km crater and the shadow-catching plate dies.
- **Rivers stay flat**, no global bed data existing. They read faint by design: nearest sampling keeps water area rather than line continuity, the honest trace over a drawn cartographic line.

### View transform: `RIG.view_transform` (scene_build.py)

- **Khronos PBR Neutral**, a `Rig` field, so a change of tone map restages.
- **It rolls highlights off instead of clipping them.** On the Iceland arm that took snow from 21.59% of pixels clipped to 0.00%, at about 9 DN of global darkening.
- **AgX's rejection does not transfer.** AgX was refused for desaturating the sand and teal; PBR Neutral moved snow hue by 1 DN in the same arm, buying the rolloff without the wash.
- **Open:** the frozen ramp hexes in `test_palette.py` were locked under `Standard`, so they describe a hero rendered under a tone map this rig no longer uses.

### Borders (composited overlay, heroes)

- Drawn by `pipeline/compose/overlay_borders.py` over the finished render, so iterate freely with no re-render. Alignment is verified by the coastline oracle before any tuning.
- **Judge width on the 2K preview, never on 1:1 crops**: 4 px looked right in crops and vanished at viewing scale.
- Baseline: land borders white 95% at 10 px, casing #3D2B1F 35% at 14 px; disputed and LoC the same plus dash [30, 20]; maritime white 80% at 7 px, casing 25% at 10.5 px, dash [40, 25].
- Casing is the wider dark stroke under the white ink. It should be invisible as a feature and only felt over pale terrain.
- Not levers: worldview (Natural Earth default, site-wide, editorial policy) and which classes are dashed.

## Fixed (don't touch without re-litigating)

- Orthographic camera, straight down. Ortho scale, plane height and render resolution are per-country derived numbers in frame.json (formulas in docs/framing-math.md). Resolution rule: 7680 px on the longer axis.
- Displacement Midlevel 0, adaptive subdivision and dicing rates.
- Mask wiring (ocean, lake, river, snow): Non-Color, Closest interpolation. Binary masks are 0/255; graded ones are 16-bit, because 8 bits terraced the sea floor.
- Warp width about render width and at most source width, the anti-bump rule.
- No Map Range with reversed ranges: Math Multiply plus Clamp only.

## Rejected, so it is not re-proposed

- **A numpy cast-shadow term, refused twice, the second time on the mechanism.** Attenuating a composited sun scales light amplitude, and fine detail amplitude falls with it, so shadowed nooks kept only 55–68% of their modeling. Every body raytraces now and carries real cast shadows.
- **Raising `ambient` to soften the tiles.** It will look like the obvious fix. Every metric improved and every render got worse, the same haze the hero ambient-raise A/B rejected. The fill sun is the shadow floor.
- **Occlusion as the softness term, falsified by a six-run sweep** where local contrast moved the wrong way. A reopening needs a new mechanism, not a new value.
- **Widening the snow window instead of curving it.** Greenland's interior light span sits nested inside the Alps' span, 17× narrower, so no linear window serves both: wide leaves Greenland blank, narrow makes an Alpine cartoon.
- **A polar feather in the terrain encode.** A ramp flattening toward datum over 78°–85° shipped when the cap could not displace, and reopened its own seam once `polarCaps.vertexSrc` began lifting cap vertices. Refuse any argument of the form "the poles need special treatment in the encode": `cap_render.write_cap_elevation` calls the same function for a grid with no rows.
- **A flat pole colour, and the flat-pole taper that followed it.** Both are gone; `ice_relief_damp` quenched the wash at its source before the compositor went.
- **A blue/white split between sea ice and land ice**, rejected as gimmicky and off-Patterson.

## How to judge a look change

- **A metric that scores contrast cannot judge softness, twice-failed and structurally so.** The old ambient clip manufactured contrast at its own cliff, so softening it scored as a loss while it looked like a gain. Judge on the sphere at planet scale and quote metrics for direction only. Local-contrast std is retired as a proxy.
- **Softness is view-independent and fully bakeable; crispness is a data ceiling.** z8 is 305.7483 m/px, which is the 10″ fuse, so real crispness means re-fusing finer and box-filtering the shaded RGB down, never the heights.
- **An artifact that tracks a SEAM is a compositing bug; one pinned to GEOGRAPHY is a data bug.** Answer assets-or-screen with a same-camera screenshot, layer on and off, rather than by inspection. The GL contract seam bugs violate is in `web/src/lib/polarCaps.ts`.
- **Judge any successor to a global tone term on `/earth` at planet scale.** Region crops and contrast metrics both got the ambient knee wrong.
- Reference image on one screen, render on the other. **One lever per iteration.** Cheap arms are the built .blend at `resolution_percentage 27`, one full-frame image per arm, never a side-by-side strip: a strip halves each arm's pixels and the difference being judged is usually smaller than that.
- Watch for scroll-wheel drift in the GUI: hovering a value field and scrolling silently edits it. The constants are the record and the .blend is disposable.

## Delivery encoding: what the browser actually receives

The masters are lossless and stay lossless. Everything below is delivery only and regenerable, so a wrong call costs an encode pass, never pixels. **Quality is a policy rather than one constant, following how closely a surface is inspected.**

| asset | quality | why |
|---|---|---|
| hero 640 / 960 / 1280 / 1920 | **q85** | thumbnails in a ~350 px masonry column |
| hero 3840 / native | **q95** | the artefact a reader opens full-screen and zooms into |
| relief tiles (all zooms) | **q95** | 512 px served into a 256 px slot; fine shading is the whole look |
| polar caps | **q85** | foreshortened background texture at the limb |
| spotlight overlay | **q88** | only ever covers the dimmed surroundings |

- **q95, not q98 and not lossless.** On a native 7680 hero the climb from q85 to q98 costs 2.1×, and the last step to mathematical identity costs another 2.4× on top: you pay more for the invisible step than for every visible one combined.
- **Uniform quality is the wrong shape.** Raising the caps to match the tiles cancels the tile saving outright. Spend quality where it is looked at.
- **Never judge a format A/B where resolution also moved.** The cap comparison that appeared to settle this had 4096 PNG against 8192 WebP, and a 4× pixel gain masks any quality penalty, so what got chosen was "more pixels".

## The srcset ladder: 640 / 960 / 1280 / 1920 / 3840 / native, plus a portrait fill rung

- **A rung names the LONG EDGE; `srcset` selects on WIDTH.** They are the same number only for a landscape hero; for a portrait one the delivered width is `rung × aspect`, which is why a portrait country gets **one extra rung sized from its own aspect** (`hero_variants.fill_rung`). A single shared extra rung does not work: a fixed long edge serves every aspect differently, the same defect one level down.
- **Chosen against measured layout, not viewport intuition.** The masonry gallery renders a card at 324–516 CSS px from 390 px to 3440 px of viewport, so device pixel ratio is the only real variable and demand falls in three bands that 640/960/1280 serve.
- **`sizes` must state a fixed width above the breakpoint, not a viewport fraction.** Fractions over-declared by up to 3.08×, and the browser selects on the declared width, so a wrong `sizes` defeats the ladder on the largest screens. **Never under-declare**: rounding down shows as blur, rounding up shows only as bytes.
- **Hero and spotlight share one ladder by IMPORT, not a copied constant**, and they are the whole set. A rung in one and missing from the other makes the browser fetch mismatched files, which is how an 85 kB border once landed on a 48 kB hero.
- **Two countries are knowingly unserved.** Chile and Maldives need long edges above the 3840 inspection floor, so their fill rung would be a q95 file delivered as a thumbnail. They wait for a ladder keyed to width.
- **The caps have their own ladder**, 1024 / 2048 / 4096 / 8192, picked from projected size on the globe because no `srcset` chooses a GPU texture. At the default camera a cap is 110 × 42 CSS px, so 8192 there was a 74× linear oversupply. The top rung is deferred rather than retired and still arrives on a zoom to the pole, in one step rather than a walk, since each swap costs a main-thread decode and upload.
