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

## What the pipeline already does

Stated in the present tense because it is verifiable in the tree, and listed so that the remaining
work below is legible as *remaining*.

- **`pipeline/bodies.py` is the registry**, and a body is a small set of facts: two sphere
  radii, the vertical exaggeration, the pyramid depth, and the path segment its outputs nest under.
  - No field carries a default, so adding one is a hard error at every construction until each body
    answers for it — rather than a value silently inherited by every planet but the one it was
    written for.
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
- **Two web seams are already body-agnostic** and need no work: the ground-distance readout takes
  its distance function injected, and the tile base is a single environment knob.

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
  not published as a layer. HRSC DTM footprints *are* published, so one is constructible, and
  building it is the only way to answer whether the boundary reads as banding.
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
  the planet fuse currently emits into: heightfield, ocean mask, water mask.
  - Or else: mirroring Copernicus's tiling, void-filling and bathymetry fusion for a single
    pre-fused download is inventing work that has no input.
- **The Earth-only composite layers must become off-switchable, not conditionally patched.** Snow
  persistence, glaciers, sea ice, lake depth.
  - Or else: every one of them is a dataset with no Martian analogue, and a conditional branch
    inside the composite is where the two bodies' looks start diverging by accident.
- **Keep the tile grid in standard Earth-radius Web Mercator.** Tile boundaries in longitude and
  latitude are identical whichever sphere is named, so the scheme, the archive format and the client
  carry over untouched.
  - The Mars radius enters only where **ground metres** are needed: the hillshade z-factor and the
    scale ruler. The ratio is about **1.88** (Earth's Mercator sphere over Mars's mean radius).
  - Or else: mixing the two radii yields a latitude-varying wrong exaggeration that renders
    plausibly everywhere and is true nowhere — the failure mode with no symptom.
- **The palette must be body-parameterised, not copied.** A second set of look constants is the same
  drift that has already cost this project a full overnight re-render of every hero; the cure was
  making the hero scene import the shared module, and a copy undoes it.
  - The existing guards will actively refuse a second look until this lands — the palette's
    relational pins treat a divergent constant as drift, by design.
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

- **The cheapest lookable thing.** A z6 Mars pyramid — about 2.8 GB of master, 0.2 GB packed.
  - Dev store layout, then the Worker's Mars archive routes with the cache recount, then the
    registry entry and its acquisition recipe, then the `/mars/` route and its Lite page.
  - Then the pipeline run, whose committed artifact is the recipe sidecar, not the pixels.
  - No sea, no vectors, a first-guess ramp. Its only job is to exist on the sphere.
  - Build the provenance mask here and look at the HRSC/MOLA boundary on the globe.
- **The look loop, still at z6.** Each candidate look is one commit to the registry.
  - Palette from scratch; exaggeration judged rather than computed.
  - The sea question decided by rendering all three options — none, one contour, the family — rather
    than by arguing them.
- **Pick a ceiling and cut.** One commit moving the Mars ceiling, then the re-cut.
- **Vectors and the product model.** One commit per layer: units, then labels, then hit-testing.
- **Heroes**, if they are wanted at all.

Estimated cost of the first phase is **11–18 GB** all-in, against a disk with several hundred GB
free. Disk is not a constraint for Mars, which is the opposite of Earth's situation at z9.

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
- **At the end of the first pyramid.** Does the HRSC/MOLA boundary read as texture banding? Answered
  by the provenance mask on a real z6 pyramid, not by argument.
- **During the look loop**, all decided on the sphere.
  - Terrella's look applied to Mars, or a Mars look of its own? This is the deepest question here;
    everything downstream keys off it.
  - Does Mars draw a sea — none, one chosen contour, or the family of candidate shorelines?
  - Exaggeration: the ~10× above is arithmetic and needs judging.
  - Does THEMIS night IR belong in the look, as a second physical field over relief?
- **After a look is ratified.**
  - The accent: derived from the Mars palette the way Earth's teal is derived from its hero ramp, or
    chosen for contrast against it?
  - Heroes: worth a second Blender sweep once an 8K Olympus Mons can be pictured concretely?
- **Before the cut.** z7 or z8, ratified on the sphere rather than chosen from the table.
- **Before vectors.** The unit of subdivision, if there is a gallery at all: geologic units, MC
  quadrangles, a curated landform list, or nothing.
- **Any time.** What goes on the Mars Lite page, and whether the imagery licence splits per body.
  - The licence question is genuinely open in one direction only: Creative Commons licences are
    irrevocable, so a freely-licensed Mars cannot later be pulled back to a more restrictive one.
  - Mars is the easier case — public-domain sources impose no notices where Copernicus imposes
    three. The real cost is clarity: the About page's single licence line becomes wrong and would
    have to state the split.

## Sources

**No Mars source below imposes a notice obligation.** Checked against the primary statements, not
assumed from the agency name — every credit here is a courtesy, where Copernicus imposes three
verbatim notices on the Earth build.

- **The blend is a USGS product, not an ESA one**, even though it contains HRSC data: it is
  published through the USGS Astrogeology PDS Annex as a US government work. A citation is
  *requested* — Fergason, Hare & Laura (2018) — not required.
- **ESA's Planetary Science Archive is registered as public domain**, and ESA's own acknowledgement
  page asks rather than requires: it *suggests* wording crediting the instrument's Principal
  Investigators and the archive. HRSC products are additionally mirrored by the NASA PDS
  Geosciences Node under an ESA–NASA cooperative agreement, which states no terms at all.
- **The one genuine trap is ESA's published imagery, which is a different thing from its archive.**
  ESA releases its HRSC *pictures* — the colour perspective views — under CC BY-SA 3.0 IGO, and that
  licence names "images, videos or other ESA works" while saying nothing about science archives.
  - Share-alike is the problem, not attribution. This site's renders are CC BY-NC 4.0, and **BY-SA
    input cannot flow into an NC output**. The permitted direction is the other one: individual
    renders may additionally be released as free-culture at the author's discretion.
  - So the rule is simply: take HRSC from the archive, never from the picture gallery. Nothing about
    the planned work needs the gallery.

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
