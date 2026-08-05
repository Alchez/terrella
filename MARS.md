# Mars — the second body

- A standing brief for putting a second planet on this site. It states current truth and carries
  no schedule, no dates and no checkboxes: if a row here and the code disagree, the row is the bug.
- It exists because the questions that decide the work's shape are **look** questions, and those
  cannot be answered from arithmetic. Everything below is either verified, derived from a stated
  premise, or explicitly marked as undecided.
- Named for actual scope rather than ambition. Renaming this to a body-general document later is
  trivial; designing for Moon, Mercury and Venus before anyone has checked their data is not.

## What is decided

- **Mars rides the same site, on its own route** — `/mars/`, beside `/earth/`. Not a body switcher
  inside one globe page.
  - The globe page is a composition root over ~25 `lib/` modules; a switcher would double the state
    space of its script rather than reuse it.
  - Separate routes also bound GPU memory: a switch is a new document, so MapLibre's tile caches die
    with it. In one document two bodies' sources can coexist, and dropping a source does not give
    the memory back.
  - The cost is a teardown and re-init per switch, which is the same event that reclaims the VRAM.
- **The body is a required argument with no default, everywhere.** A run that quietly borrows
  Earth's geometry because a name was misspelled produces a full pyramid that is wrong everywhere
  and looks right.
- **Earth's output stays byte-identical** through every parameterisation step. Byte-identity is a
  per-commit gate, not an end-of-phase one — that is what makes a bisect mean anything.
- **Mars ships a Lite page from the start**, even before its content is decided.
  - Removing the tier button would not be enough: the pre-paint capability guard routes incapable
    devices too, and with no Mars Lite destination it would land them on Earth's gallery.
- **The tier preference is one key across bodies.** Which tier a device can run is a fact about the
  device, not a per-planet preference.
- **The site keeps its name and its origin.** No rename, and no separate subdomain — a subdomain is
  a separate origin, so the tier preference would stop being shared, the capability probe would
  re-run, and the warm asset cache would not carry.
- **No z9 or z10, for either body.** Same disk wall Earth is parked behind, and on Mars the source
  cannot honestly fill it.
- **One output licence for both bodies: CC BY-SA 4.0.** The blend's publisher labels its HRSC half
  CC BY-SA 3.0 IGO, and share-alike cannot flow into the CC BY-NC the renders used to carry — so the
  strict reading is assumed and Earth is matched to Mars rather than split from it. It complies
  whichever way the label is read, which is why it needs no legal determination to act on.
  - Irrevocable, and that is the whole cost: nothing published under it can be narrowed later.
  - **The alternative was to change the source rather than the licence, and it was declined.** MOLA
    MEGDR is CC0 at 463 m/px against a z6 cut of 651 m/px, so the swap costs nothing visible today.
    But it bites from z7 (326 m/px) up, where MEGDR is upsampled and the blend is not, and at z8 it
    is a 2.8x upsample. Keeping the option of a finer cut is worth more than the permissive terms.
  - Both readings of the label, the evidence for each, and the clause that permits a 3.0 IGO input
    to become a 4.0 output all live in `ATTRIBUTIONS.md`.

## What the pipeline already does

Stated in the present tense because it is verifiable in the tree, and listed so that the remaining
work below is legible as *remaining*.

- **`pipeline/bodies.py` is the registry**, and a body is a small set of facts: two projection
  spheres and the body's own, the resolution of the raster its pyramid is cut from, the vertical
  exaggeration, the pyramid depth, and the path segment its outputs nest under.
  - The body's own sphere is separate from the projections' because Earth hides the distinction:
    EPSG:3857 is defined on Earth's equatorial radius, so one number has been answering both "what
    is a map unit" and "what is a ground metre". Earth's ratio between them is exactly 1.
  - No field carries a default, so adding one is a hard error at every construction until each body
    answers for it — rather than a value silently inherited by every planet but the one it was
    written for.
  - **Mars is registered**, and answers every field. **Both its projection spheres are Earth's, on
    purpose** — the registry asserts that sameness deliberately, because giving Mars its own would
    read as the obvious fix and produce a raster the tiler cannot cut. Its ground sphere is the IAU
    2015 sphere the source DEM declares, giving a ratio of 0.532 and a z-factor 1.878× Earth's.
  - **Its exaggeration and its ceiling are provisional and neither is a decision**, held so the type
    is satisfied and the path exists, exactly as the browser registry's Mars accent is. 10× is
    arithmetic to be judged on the sphere; z6 is the cheapest lookable thing rather than the
    eventual ceiling. A run is harmless meanwhile: there is no Mars heightfield, so the first warp
    fails loudly rather than producing a plausible wrong pyramid.
  - **One word names a body in both registries**, and a scan holds them together, because neither
    language can import the other and a divergence is a pyramid written under one name and requested
    under another — a 404 at the edge, long after the run that produced it.
- **Both of Mars's entry stages exist and neither has run**, because both wait on the one download.
  - `pipeline/acquire/download_mars_dem.py` fetches the blend and refuses anything but the pinned
    edition: the server's size *and* its Last-Modified stamp before the transfer, then the grid's
    width, height, dtype, nodata and **sphere** afterwards. USGS republishes mosaics in place under
    the same filename, so a same-name file with a different date is a different planet's worth of
    pixels arriving under our recipe.
  - `pipeline/fuse/relabel_mars.py` publishes that file as Mars's planet heightfield by **declaring**
    its CRS to be EPSG:4326 — an identity on the angles, and a VRT, so nothing is resampled and no
    copy of 10.6 GiB is made. It re-runs the grid check first, because the relabel is only honest
    while the source really is a sphere in degrees: on an ellipsoid the same declaration would
    silently shift every latitude, and nothing downstream could see it.
  - It emits a heightfield and **declares that it emitted nothing else**, which is the whole of what
    Mars needs from the fuse tier.
- **The body goes in the PATH, not in the freshness recipe.** Every tile stage is gated on a recipe
  sidecar whose *contents* are its dependency, so a body field inside those recipes would invalidate
  Earth's correct output the moment a second body existed, for no pixel change at all. Separate
  directories make every sidecar body-specific for free, because they are different files.
- **`--body` is required on the shade and cap passes**, and the shade pass hands its own body down
  to the cap pass rather than letting the cap pass default.
- **Served assets and intermediates have separate roots.** Intermediates follow the relocatable data
  store; anything the site ships follows the checkout, because the build reads it from there.
- **Earth's path segment is empty on purpose**, and the asymmetry is measured rather than sloppy.
  Its intermediates already hold the live pyramid, so moving them under a new segment would make
  every stage read as missing and re-derive the whole planet to produce identical pixels. A second
  body pays no such cost and nests properly from the start.
- **The web side has the same registry**, keyed by a `data-body` attribute on `<html>` that the
  layout must declare. There is no bare fallback: a page that omits it has no accent at all, loudly,
  rather than quietly wearing Earth's.
  - **Mars is already in it**, with a route, accent tokens and a work-tree prefix, and it publishes
    a relief pyramid — so `/mars/` draws the same globe `/earth/` does, from one shared component
    rather than a second copy of it. Everything Mars does not publish is refused from the registry,
    so a body page turns nothing off by hand. Its chrome colours are placeholders held to satisfy
    the type, not choices; they are downstream of a palette nobody has ratified, and replacing them
    with imports from a Mars ramp is the first thing a decided look changes.
- **Every tile URL names its body**, in a fixed six-segment grammar — body, layer, a content token
  for the cut, then `z/x/y` and an extension. Adding a planet, a layer or a re-cut adds a *word*,
  never a shape, which is what makes two archives unable to share an address by construction.
  - A body that publishes nothing says so explicitly, layer by layer, and every consequence is the
    one wanted: a tile URL for it is refused before any storage is touched, a lookup throws rather
    than borrowing Earth's pyramid, and the deploy preflight demands no object for it.
  - The preflight *enumerates* that registry, so an archive is checked for the day it is published.
- **Which surface layers a body has is a body fact, not a question about the filesystem.** Snow
  persistence, glaciers, sea ice and lake depth are declared per planet; Mars declares none.
  - **The `.exists()` guards that made three of them "optional" could never have worked.** Every one
    of those sources is a module constant at a single global path, so the check asks "have we
    downloaded Earth's data" — true on the build box for every body alike. A Mars pass would have
    warped Earth's northern-hemisphere snow, its glaciers, its sea ice and its lake bathymetry onto
    Mars's grid *at the same latitudes* and composited them. Snow in the north, none in the south:
    no error, no missing file, and an entirely plausible planet.
  - The body is therefore asked **before** the disk, and the Antarctic land-ice patch — pure
    latitude-and-land, with no dataset behind it that could ever switch it off — rides with the snow
    layer it patches. Left on, it whitens every piece of land below 60° south, which on a sea-less
    body is most of one.
  - Earth declares all four, so its composite recipe is unchanged and its 46 GB of output cannot
    restage. A body that omits a layer records the omission, because an unbuilt raster is *silently*
    not a dependency: a missing path scores zero in the mtime comparison.
  - **Empty is a statement about our data, not about Mars.** It has polar ice and seasonal CO₂
    frost; we have no product for any of it and the physics is not Earth's. A Phase-2 question, to
    re-ask with Mars on screen.
- **The tile shading converts map units to ground metres through the body's own sphere.** Every
  raster here is EPSG:3857 whatever planet the elevations describe, so a slope is a rise in body
  metres over a run in map units — and on Mars a map unit is worth 0.53 of a ground metre, making
  the real relief 1.878× steeper than the grid says. That one ratio divides the hillshade's z-factor
  and scales the sky-view's horizon search.
  - The cast shadow needed no change and that is not an accident worth rediscovering: it accumulates
    `zfactor × Δh ÷ (distance × map units)`, so the correction arrives with the z-factor it is
    already handed, and applying it a second time there would double it.
  - The ratio is **exactly 1.0 for Earth**, by construction of EPSG:3857 rather than by rounding, so
    the conversion reached production without restaging a pixel. It is written into the hillshade's
    freshness recipe only when it is *not* 1.0 — the same rule the fill sun and the cast shadow
    already follow, and for the same reason: a key whose value is the identity would mark 46 GB of
    correct output stale.
  - A grid row's latitude is a separate question with the opposite answer: it is a property of the
    projection, not of the ground, so it stays on EPSG:3857's own sphere for every body. That
    constant lives in the projection module now rather than being read off Earth's registry entry,
    where it invited a "fix" that would have put Mars's rows 31° out.
- **The polar caps cannot be given Mars's own sphere either, and this was measured.** PROJ refuses
  `EPSG:3857` → an AEQD written `+a=3396190` with *"Source and target ellipsoid do not belong to the
  same celestial body (Mars vs Earth)"* — it identifies the body from a bare radius in a proj4
  string, with no EPSG code involved. An Earth-radius AEQD target from the same source succeeds.
  - So the caps' disc is Earth-sphered for every planet, exactly as the tile grid is, and the caps
    need their own map-unit-to-ground ratio: `ground_radius_m ÷ aeqd_radius_m`, which is **not** the
    Mercator one, because the two projections are defined on different spheres.
- **The tile base is per-body**: a URL is built from the body's slug and its layer, with the body a
  required argument, so nothing derives a tile address without naming a planet.
- **The scale ruler measures on the body's own sphere**, and how it came not to is the lesson worth
  keeping. `rulerGroundDistance` took a `locate` function, which reads as parameterised — but
  `locate` returned a MapLibre `LngLat`, and the distance came from `LngLat.distanceTo`, whose
  radius is a constant in the shipped bundle. The seam injected *where the points are*, never *what
  a metre is worth*, so a second body's ruler read 1.876× long: plausible at every zoom, wrong at
  all of them, and the one readout on the page claiming to be measured rather than drawn.
  - The locator now returns coordinates and the arc is computed here, against a required
    `groundRadiusM` with no default — so a body that names no radius is a compile error, not a
    plausible reading.
  - Earth's readings are unchanged **by identity, not by tolerance**: the same formula and the same
    constant MapLibre uses, proven against the library itself over a table of live camera positions.
- **The tile Worker's directory cache is sized by summing every published archive**, across bodies,
  rather than by a hand tally — because two planets asked for alternately is precisely the traffic
  an undersized LRU handles worst, and an evicted directory costs a gunzip rather than a fetch, so
  the failure is invisible. The per-archive cost is generated from the archive's own bytes.

## The data

What does not exist is stated as plainly as what does, because two of the absences below shape the
whole project.

- **The MOLA/HRSC blended DEM is a 200 m/px grid, but not 200 m of information.**
  - HRSC stereo DTMs cover about **44%** of the planet. The other **56%** is MOLA at 463 m/px,
    upsampled onto the finer grid.
  - HRSC edges are feathered into the MOLA background over roughly **5 km** — about 100 px at the
    blend's own resolution.
  - This is the single most consequential fact in this document, and it argues against a deep cut.
- **MOLA MEGDR, 463 m/px, global, is the honest floor** — one instrument, one resolution, no seams.
- **No provenance mask ships with the blend.** Which pixels are HRSC and which are upsampled MOLA is
  not published as a layer. HRSC DTM footprints *are* published, so one is constructible.
- **THE BOUNDARY READS AS BANDING, AND NO MASK WAS NEEDED TO SEE IT.** The first z6 pyramid answers
  it directly: the northern plains carry rectangular patches of visibly rougher terrain with hard
  straight edges, which are HRSC DTM footprints against the MOLA background.
  - It is **not** an elevation seam — the 5 km feather handles the level. It is a *roughness*
    discontinuity, and hillshade plus sky-view amplify precisely the high-frequency detail that
    distinguishes a 463 m instrument from a stereo DTM.
  - So it **argues for a low ceiling rather than against one**. Going deeper sharpens the HRSC
    patches while the 56% beneath becomes a wider upsample: the contrast grows with the cut.
  - A constructed provenance mask is now a *treatment* tool — knowing which pixels to low-pass — and
    no longer a diagnostic. The diagnosis is done.
- **The heightfield holds no holes, and this is a census rather than a sample.** All 1,073,741,824
  pixels of the warped z6 grid read: **zero nodata**, against a declared `-32768`. Earlier sampling
  covered 1.9% of rows and could only ever be evidence, since a hole smaller than the decimation is
  invisible to it. Valid range **−8,511 m to +21,166 m**.
- **Paleobathymetry does not exist.** There is no measured sea floor, because there is no sea.
  - What exists is a set of *contested shoreline contours*. Published mappings of the Arabia Level
    disagree by up to **2.2 km** in mean elevation and roughly **500 km** laterally.
  - Our sea ramp is depth-keyed off the heightfield and has never consumed a bathymetry product,
    so nothing technical blocks a Martian sea.
  - The consequence is editorial, not technical: **a sea on Mars is a chosen contour**, and choosing
    one is a claim. That makes it a look decision with an honesty obligation attached, not an
    acquisition problem.
- **Vector data splits into two very different products.**
  - The USGS/IAU gazetteer is *nomenclature* — named features. Its geometry type is unconfirmed and
    believed to be points with a diameter attribute, which would make it labels, not regions.
  - The **Geologic Map of Mars (SIM 3292)**, at 1:20M, ships shapefiles of **polygon units**.
    That is the real analogue of our country polygons, and the only candidate that could carry a
    gallery.
- **Other renderable layers, all openly licensed.**
  - THEMIS day IR and night IR at 100 m/px, global; night IR covers 60°N–60°S.
  - Viking MDIM 2.1 colorized, 232 m/px.
  - The CTX global mosaic at 5 m/px — **imagery, not a DEM**. Over 99.5% coverage, about 10 TB.
  - MOLA polar grids at 512 px/degree (~112 m/px), plus an HRSC south polar DTM at 50 m.
  - Digitised paleoshoreline vectors, and MGS crustal magnetism.

## The zoom ceiling

- Mars's equatorial circumference is **21,339 km**. On our 512 px tile scheme that gives:

| zoom | ground resolution | master pyramid | packed archive |
| --- | --- | --- | --- |
| z6 | 651 m/px | ~2.8 GB | ~0.2 GB |
| z7 | 326 m/px | ~11 GB | ~0.8 GB |
| z8 | 163 m/px | ~44 GB | ~3.1 GB |
| z9 | 81 m/px | ~176 GB | ~12.4 GB |

- **Pyramid size is set by the ceiling, not by the body.** The tile grid at a given zoom has the
  same number of tiles whichever planet it covers, so these figures are Earth's measured artifacts
  re-read against Mars's resolutions.
- **The honest ceiling is probably z7**, and the reason is the 44% coverage above: z8 costs four
  times the disk to deliver a 2.8× upsample of MOLA over most of the planet.
  - Not a decision. A resolution ceiling has never been judgeable from a number here — it has to
    exist, be served, and be looked at on the sphere, which is how Earth's was settled.

### Exaggeration: two ratios that point opposite ways

Easy to conflate, and conflating them yields ~5× where the answer is ~10×.

- **On its own sphere, Mars needs LESS exaggeration than Earth.** Its relief range is about
  **0.87%** of its radius against Earth's **0.31%** — roughly 2.8× more dramatic before any
  exaggeration.
  - That figure is now measured off our own grid rather than carried from a source: the full census
    of the warped heightfield gives a **29,677 m** span on the 3,396,190 m sphere, i.e. **0.874%**.
- **On MapLibre's globe, Mars needs MORE.** The globe shader draws every body on the same
  Earth-sized sphere and displaces in metres, so only the metres matter — and Mars's ~30 km range is
  about **1.5×** Earth's ~20 km.
  - So to read the way Earth reads at 15×, Mars wants roughly **15 / 1.5 ≈ 10×**.
- That ~10× is arithmetic, not a decision. It is a starting point to be judged on the sphere.

### Heroes, if they happen

- A hero at 8K needs about `span / 7680` metres per pixel, so the blend already suffices above
  roughly 400 km of span: Valles Marineris ~521 m/px, Hellas ~299, Tharsis ~651.
- Anything crater-scale needs HRSC or CTX, which is a different acquisition problem entirely.

## What still has to change

Each with its "or else", because a seam without a failure mode is a preference.

- **The fuse tier disappears — the blend IS the heightfield.** Mars enters the pipeline at the seam
  the planet fuse currently emits into, and it emits a heightfield and nothing else.
  - Or else: mirroring Copernicus's tiling, void-filling and bathymetry fusion for a single
    pre-fused download is inventing work that has no input.
- **The planet stage DECLARES what it produced, in a file it writes last, and no consumer looks for
  the rasters themselves.** Earth's declaration names all three — heightfield, ocean mask, water
  mask; Mars's names one. Its presence is the stage's completion stamp; its contents are the body
  fact.
  - Or else, in two separate ways that a missing file cannot tell apart. **Absence is not a
    statement:** a missing ocean mask reads identically whether the planet has no sea or the
    producer died two rasters in, and the second must never be shaded. **Absence is also invisible
    to freshness:** an unbuilt raster scores nothing at all in an mtime comparison, so it stops
    being a dependency at the same moment it stops being an input — and the composite painted with
    the old one reads fresh forever. That is precisely the loop the sea question below runs.
  - **Mars is given no ocean or water mask at all, not an empty one**, and that is the decision the
    seam exists to make possible. A raster of zeros on disk cannot be told apart from one produced
    by measuring Mars's oceans and finding none; it would be the only body fact in the project
    written as a fabricated dataset. The all-land selectors are built in memory from the
    declaration, at the two places that read them, and are proven to paint exactly what a measured
    all-land mask paints.
  - So **a sea at a chosen contour is a producer change plus a registry line**, not a swap of one
    fake raster for a real one — which is what makes the sea question answerable by rendering rather
    than by arguing. The two masks are gated separately for the same reason: a shoreline contour
    gives Mars an ocean mask while it still has no inland water.
- **The Earth-only layers are declared per body, and both render paths obey.** Snow persistence,
  glaciers, sea ice, lake depth and the baked coastline are named on the body; the tile composite and
  the polar caps each ask it before they ask the disk, and each records the layers it is missing so
  that switching one restages the output it changes.
  - Or else: every one of them is a dataset with no Martian analogue sitting at one global path that
    is present on the build box, so a file-presence check answers *"did we download Earth's data"*
    for every planet alike — and a Mars pass would paint Earth's cryosphere onto Mars's grid at the
    same latitudes, with no error and no missing file.
  - The forced Antarctic ice patch rides the snow layer rather than a file, because there is no
    dataset behind it: it is latitude and land, so on a sea-less body it whitens everything below 60
    degrees south. Nothing on disk could ever have switched it off.
  - Each stage records only the layers **it** reads. The caps never composite lake bathymetry and the
    tiles never bake a coastline, so a shared vocabulary would make one stage's decision restage the
    other's output — 46 GB of planet for the sake of a polar texture.
- **Keep the tile grid in standard Earth-radius Web Mercator — this is forced, not preferred.** Tile
  boundaries in longitude and latitude are identical whichever sphere is named, so the scheme, the
  archive format and the client carry over untouched. But the deciding fact is upstream of taste:
  **PROJ refuses to build an operation between two celestial bodies**, and the tiler reprojects into
  WebMercatorQuad, so a Mars-radius Mercator raster cannot be cut into tiles at all without
  disabling that guard globally.
  - So a non-Earth heightfield enters by having its CRS **declared** as EPSG:4326 — an identity on
    angles, since only the sphere label changes — and every projection downstream stays Earth-sphered.
  - The Mars radius then enters only where **ground metres** are needed. The ratio is **1.878** —
    Earth's Mercator sphere over the IAU 2015 Mars sphere of 3,396,190 m, which is the figure the
    ceiling table above is built on and the one the source DEM's own CRS declares.
  - Both render paths convert through it now, but **not through the same ratio**, because they are
    projected on different spheres. The caps' azimuthal-equidistant disc divides by 6,371,000 m, so
    its Mars ratio is 0.5331 and its **Earth ratio is 1.0011, not 1.0** — the one place adopting the
    conversion moved Earth's own pixels rather than none. The browser's **scale ruler** is a third
    ratio for the same reason: it converts an angle rather than a map unit, so it divides by the
    body's mean radius and Earth's factor there is exactly 1.
  - That AEQD sphere is as forced as the Mercator one, and separately measured: PROJ refuses
    EPSG:3857 to `+proj=aeqd +a=3396190` with the same celestial-body objection, from a bare proj4
    string that names no body at all.
  - Or else: mixing the two radii yields a latitude-varying wrong exaggeration that renders
    plausibly everywhere and is true nowhere — the failure mode with no symptom.
- **What is left of the palette work is the LOOK ITSELF, not the parameterisation.** The seam is
  built: `palette.LOOK_BY_BODY` answers which ramps a body draws with, `look_for` refuses an
  unregistered planet rather than falling back to Earth's, and the composite takes the resolved
  look as a required argument so no ramp can be chosen by omission.
  - Mars's entry deliberately borrows Earth's land ramp — shared, not copied, so the borrowing
    cannot silently stop being true — and declares **no sea ramp at all**, which is a fact rather
    than a placeholder while its planet seam declares no oceanmask.
  - A second set of look constants would be the drift that has already cost this project a full
    overnight re-render of every hero; the cure was making the hero scene import the shared module,
    and a copy undoes it. Registering a look is what replaces copying.
  - The palette's relational pins still treat a divergent constant as drift, by design, so they
    will refuse a Mars ramp written as new module-level constants rather than as a `Look`.
- **The tile Worker's directory cache must be recounted.** It is sized by counting the entries each
  shipped archive occupies, and the Worker records that arithmetic beside the constant. Mars adds up
  to three more archives, so the count is redone, not raised by feel.
  - Or else: an undersized cache evicts on *alternating* requests, which is exactly the pattern a
    body switch produces — and it is invisible, because nothing fails. Dev cannot reproduce it
    either: the dev middleware reads local files and keeps no directory cache at all, so dev is the
    more forgiving of the two environments here.
- **A dev store layout that keeps its fail-loud property.** One root plus a body/archive path
  convention.
  - Or else: a missing Mars archive that falls back to Earth's is a globe that renders perfectly and
    shows the wrong planet.
- **The UI's per-body chrome is an existing mechanism, not a new one.** The layout already renders
  its view bar from boolean props, and the accent is already one token that varies by scheme.
  - The body switcher belongs in the **title**, not the actions row: the body is the subject, not an
    action on it, and the masthead has roughly 23 px of spare width at 360 px — not a two-state
    control. Annotating existing content costs no row width; a sibling in the actions slot does.

## Risks carried from the Earth build

Restated as standalone facts, because the reason each was learned matters more than the incident.

- **A straight edge in fused elevation is usually a data-provenance edge, not a defect.** Verify at
  the data's own pixel scale before calling one a bug, and do not smooth reflexively. Mars's 44/56
  split with 5 km feathering is this phenomenon by construction, not by accident.
- **Build-cost estimates for this pipeline have been wrong in a consistent direction.** Trust the
  measured peak, never the estimate. Make the first Mars run small and measured.
- **Every module-level constant is a latent cross-body bug**, and the ones that hurt are the ones
  that do not raise. The body must never have a default.
- **One heavy job at a time, under the memory cap, with temp on a real filesystem.** The archive
  packer has OOM-killed this box once, on the assumption that it was "just IO".
- **An unchecked directory inside a checked package is where correctness quietly rots.** Two harness
  scripts once sat in an excluded folder long enough to become no-ops nobody could observe — one
  swept a ladder whose rungs had become identical, the other restored a default that had moved. If
  Mars work wants a scratch harness, it goes in the checked tree or it does not go in.

## The sequence from here

One small commit at a time, each green and each shippable alone. No commit may leave Earth broken.

- **The cheapest lookable thing — RUN, and it was cheaper than the estimate.** The z6 pyramid is
  **3.1 GB of master and 340 MB packed**, cut in **4:41** end to end. The estimate said 2.8 GB and
  0.2 GB; the master is bigger because it is Float32 and the archive because Mars, having no flat
  sea, dedupes to 5,334 unique tiles of 5,461 where Earth sheds about 5%.
  - Dev store layout, then the Worker's Mars archive routes with the cache recount, then the
    registry entry and its acquisition recipe, then the `/mars/` route and its Lite page.
  - Then the pipeline run, whose committed artifact is the recipe sidecar, not the pixels.
  - No sea, no vectors, a first-guess ramp. Its only job is to exist on the sphere.
  - **What it proved beyond the pixels:** every surface-layer gate fires and says why, the cap gate
    declines out loud, and the nodata and provenance questions are both answered above.
- **The look loop, still at z6.** Each candidate look is one commit to the registry.
  - Palette from scratch; exaggeration judged rather than computed.
  - The sea question decided by rendering all three options — none, one contour, the family — rather
    than by arguing them.
- **Pick a ceiling and cut.** One commit moving the Mars ceiling, then the re-cut.
- **Vectors and the product model.** One commit per layer: units, then labels, then hit-testing.
- **Heroes**, if they are wanted at all.

The first phase costs roughly **15–22 GB** all-in, against a disk with several hundred GB free. The
source blend is **10.6 GiB** — measured from the server rather than estimated, and about half again
the first guess, because the mosaic is uncompressed Int16 rather than compressed. Disk is still not
a constraint for Mars, which is the opposite of Earth's situation at z9.

## Deliberately not doing

Listed so they are not re-proposed as if new.

- **z9 or z10.** The disk wall, and a source that cannot honestly fill it.
- **An acquisition tier.** There is one download. Mirroring the Copernicus machinery — tiling,
  void-filling, gap-fetching from a second provider — would be building for a problem Mars does not
  have.
- **Porting the snow, sea-ice or glacier layers.** They are Earth datasets describing Earth
  processes. Mars gets its own cryosphere question or none.
- **A redirect from the old globe URL.** The route was renamed before it was publicised.
- **A separate tile server.** Ours are pre-rendered and immutable, and the tile Worker exists to
  solve a cache-object size limit that a tile server does not address. This is closed, not parked.

## Open questions

Triaged by when each must be answered, because most of them cannot be answered early.

- **Before any download.** The blended DEM itself, and one gazetteer shapefile to settle whether its
  geometry is points or polygons. Both are public domain and neither adds an obligation — the
  licensing is settled, so this is a decision about disk and time, not about terms.
- **During the look loop**, all decided on the sphere.
  - **ANSWERED — a Mars look of its own, and the answer came from measuring the planet's colour
    rather than from taste.** Mars draws `MARS_LAND_STOPS`, authored for Mars and sharing no colour
    object with Earth.
    - **The premise for deriving the ramp from real colour was tested and FAILED, which is what made
      the decision.** A global Viking colour mosaic was joined to the shipped heightfield at 6.48 M
      co-registered samples: across the elevations holding **64%** of the surface (−3,000 to
      +3,000 m) mean colour moves **7.1 luma** against a within-place scatter of **17.9** — a ratio
      of 0.40. Widened to 92% of the surface it is 1.03. Mars's albedo is set by wind-blown dust,
      which does not track height.
    - The named features prove it individually: **Syrtis Major sits at +1,369 m and luma 41.5 where
      its own elevation band averages 84** — off the trend by more than the trend's whole range.
      Acidalia is low and dark, Hellas is the lowest place on the planet and bright.
    - **So the ramp is cartographic convention and the About page says so to visitors**, naming the
      markings it cannot show. That disclosure is guarded, because a paragraph with no test reads as
      decoration and gets deleted during an unrelated edit.
    - **HUE was taken in full, LEVEL in part, SHAPE refused.** Channel ratios survive an uncalibrated
      tone curve, so the mosaic's G/R 0.654 against Earth's borrowed 0.780 is trustworthy. Its 2.07×
      darker reading is not: real land albedo is broadly comparable between the bodies, so most of
      that factor is the product's own tone curve plus an uncorrected atmospheric haze floor. Mars
      ships at **0.71× Earth's land brightness**. Rising monotonically with elevation is the refused
      part — faithful would mean Hellas and Olympus wearing the same colour, the exact defect
      inherited from Earth's shoreline hinge.
    - **The mosaic is evidence, not an input.** Nothing in the pipeline reads it; the ramp is
      authored constants. It is recorded here and at the constant so the derivation is findable.
  - **ANSWERED — the ramp's DOMAIN is Mars's own, −6,000 to +6,100 m.** A `Surface` used to hinge on
    0 m at one end, which is right on Earth, where 0 is the shoreline and a real boundary. Mars's
    0 m is the areoid: an equipotential reference with no expression on the ground, sitting at the
    MEDIAN of the planet's elevations. Hinging there put **51.6% of the surface below the ramp
    entirely**, clamped to one colour, with only 0–4,000 m getting any gradient at all.
    - The ends are p1 and p99, measured area-weighted on the sphere over the shipped heightfield:
      p1 −5,990 · p50 −260 · p99 +6,098, against a true range of −7,882 to +21,014 m.
    - The extremes were rejected on the same measurement: only **1.1%** of Mars is above +6,000 m,
      so keying the ceiling to Olympus Mons spends most of the ramp on almost nothing — and Olympus
      still reads, because it reads through the hillshade, which no ramp touches.
    - `Surface` carries `origin_m` beside `extreme_m` now, and Earth reduces to its old expressions
      exactly rather than approximately, so its shipped pyramid cannot restage over this.
    - The domain is what unblocked the colours: it gave a set of stops something to do across 98%
      of the surface, which is what made them judgeable on the sphere at all.
  - Does Mars draw a sea — none, one chosen contour, or the family of candidate shorelines?
  - **Does Mars want any air at all?** The registry now carries the three atmosphere colours per
    body and Mars answers `null`: no sky pass, no glow at the limb, no aerial perspective over the
    ground. That is the physics — Mars's surface pressure is under 1% of Earth's, so an atmosphere
    faithful to Earth's tuning is invisible at every zoom the globe reaches. The open half is
    whether a wisp reads better than none once the ramp is ratified, which is three colours in one
    registry row.
  - **Mars's poles wear Earth's sea ice, and it is a LOOK constant with no body behind it —
    `CAP_RGB`.** The composite flat-fills everything above `CAP_NORTH` 84° and below `CAP_SOUTH`
    −84° with `(216, 226, 233)`, described in its own comment as "pale sea-ice fill", because Web
    Mercator carries no data past ~85° and the 84–85° band is smeared. That fill is the BASE the
    azimuthal cap textures are drawn over; Earth's caps hide it completely, and a body that renders
    none leaves it bare.
    - Found by deleting Mars's sky and watching the band not move — the earlier reading here, that
      the sky colour filled the polar hole, was wrong on both halves.
    - Measured in the shipped archives: uniform from the Mercator limit down to 84°, 120 of 512 rows
      in the z3 top tile, the whole z6 top tile, both poles. `#d8e2e8` on screen against the
      constant's `#d8e2e9` is WebP q95, one DN of blue.
    - **On a body that renders caps the fill is DEAD PIXELS.** The browser feathers with
      `smoothstep(81, feather_hi)` where `feather_hi` is `CAP_NORTH` itself, so the cap is fully
      opaque from 84° poleward and nothing beneath it is ever seen. The plug exists only because the
      raster must hold something between 84° and the 85.05° grid edge, and a smeared Mercator sliver
      is uglier than a flat colour in the one case the flat colour shows.
    - **So the answer was never a per-body `CAP_RGB`.** It was that Mars rendered no caps, and the
      stated reason — a cap wears the same ramps as the tiles, so rendering one publishes a look
      decision — expired when the look was ratified. Mars's caps now hide the plug exactly as
      Earth's do, and they are relief rather than ice: Mars declares no surface layers, so the two
      discs shade from the same ramps as the tiles. Anyone expecting white is expecting a layer.
  - Exaggeration: the ~10× above is arithmetic and needs judging.
  - Does THEMIS night IR belong in the look, as a second physical field over relief?
- **After a look is ratified.**
  - The accent: derived from the Mars palette the way Earth's teal is derived from its hero ramp, or
    chosen for contrast against it?
  - Heroes: worth a second Blender sweep once an 8K Olympus Mons can be pictured concretely?
- **Before the cut.** z7 or z8, ratified on the sphere rather than chosen from the table.
- **Before vectors.** The unit of subdivision, if there is a gallery at all: geologic units, MC
  quadrangles, a curated landform list, or nothing.
- **Any time.** What goes on the Mars Lite page.

## Sources

**The blend's terms are not legally settled, and an earlier reading here was too confident.** This
section once said no Mars source imposes any obligation. The USGS product page for the blend states
its own access constraints as *"MOLA (CC0) and HRSC (CC BY-SA 3.0 IGO)"* and its use constraints as
*"Please cite authors"* — read verbatim off the publisher's metadata for the exact file this project
downloads. **The response is settled even though the question is not**: the site's renders are
CC BY-SA 4.0, which complies whichever way that label is read. Both readings and the evidence for
each are in `ATTRIBUTIONS.md`; what must not be re-derived is a conclusion that the archive route
imposes nothing.

- **The blend is a USGS product, not an ESA one**, even though it contains HRSC data: it is
  published through the USGS Astrogeology PDS Annex as a US government work. That is what made the
  earlier reading plausible — but the publisher labelling its own inputs is a different statement
  from the agency it belongs to, and it is the labelling that has to be answered.
- **The citation is requested by the publisher**, not merely academic courtesy: Fergason, Hare &
  Laura (2018), which the About page now carries in full.
- **ESA's Planetary Science Archive is registered as public domain**, and ESA's own acknowledgement
  page asks rather than requires: it *suggests* wording crediting the instrument's Principal
  Investigators and the archive. HRSC products are additionally mirrored by the NASA PDS
  Geosciences Node under an ESA–NASA cooperative agreement, which states no terms at all.
- **The one genuine trap is ESA's published imagery, which is a different thing from its archive.**
  ESA releases its HRSC *pictures* — the colour perspective views — under CC BY-SA 3.0 IGO, and that
  licence names "images, videos or other ESA works" while saying nothing about science archives.
  - Share-alike was the problem, not attribution — it is what ruled out the CC BY-NC the renders
    used to carry, and the reason they are CC BY-SA 4.0 now.
  - One rule survives the change: take HRSC from the archive, never from the picture gallery.
    Nothing about the planned work needs the gallery, and the gallery's terms are ESA's own rather
    than the ones already accounted for here.

| dataset | what it is | where |
| --- | --- | --- |
| MOLA/HRSC blend | 200 m/px global DEM, 44% HRSC over MOLA | USGS Astrogeology |
| MOLA MEGDR | 463 m/px global DEM, single instrument | NASA PDS Geosciences Node |
| MOLA polar grids | 512 px/degree polar DEMs | NASA PDS Geosciences Node |
| HRSC DTM footprints | per-DTM coverage, for the provenance mask | NASA PDS, or ESA PSA |
| SIM 3292 | 1:20M geologic map, polygon units | USGS Publications Warehouse |
| USGS/IAU gazetteer | planetary nomenclature | USGS Astrogeology |
| THEMIS day/night IR | 100 m/px global infrared | ASU / USGS Astrogeology |
| Viking MDIM 2.1 | 232 m/px colorized global mosaic | USGS Astrogeology |
| CTX global mosaic | 5 m/px imagery, ~10 TB | Caltech Murray Lab |
