# Relief Globe — living plan

Status legend: [ ] todo · [~] in progress · [x] done · [!] blocked
Update this file at the end of every work session. Record decisions in the log at the bottom.

## Phase 0 — Proof of concept (one country, end to end)

Goal: a single Ramspott-style render of **India** that looks right, before building anything global.

- [ ] Download Copernicus GLO-30 tiles covering India + margin (OpenTopography / AWS)
- [ ] Download GEBCO bathymetry for the same extent
- [ ] Fuse land + bathymetry into one seamless GeoTIFF heightfield (GDAL; document the
      land/sea blend approach — nodata handling at coastline is the tricky bit)
- [ ] Manual Blender scene: displacement plane, sun lamp, two-ramp material, ortho camera
- [ ] Iterate lighting/palette/exaggeration until it matches the reference aesthetic
- [ ] Add Natural Earth border overlay (white, ~like reference) + dashed maritime lines
- [ ] Render 8K still; review on both desktop and phone
- [ ] **Checkpoint: lock the scene rig parameters (light azimuth/altitude, ramps,
      exaggeration) — these become global constants**

## Phase 1 — Batch hero renders (all countries)

- [ ] Script the Phase 0 scene in bpy: load heightfield, frame ortho camera from a
      country bounding box (Natural Earth), render headless
- [ ] Per-country config: bbox padding, camera framing overrides for awkward shapes
      (Chile, Indonesia, Russia, island nations)
- [ ] Handle antimeridian-crossing countries (Fiji, Russia, NZ) explicitly
- [ ] Batch runner: queue all ~195 countries, resumable, logs failures
- [ ] Overnight render run on 4070 Super; QA pass over outputs
- [ ] Generate responsive variants (2K/4K/8K WebP) per country

## Phase 2 — Global tile pyramid

- [ ] Build planet-wide fused heightfield (chunked; will not fit in RAM)
- [ ] Raster shading pipeline: multidirectional hillshade + sky-view factor (WhiteboxTools)
      + land/sea color ramps, composited to match hero-render palette
- [ ] Compare a tile region side-by-side with the Cycles render; tune until acceptable
- [ ] Cut 512px tiles, zoom 0–8 (extend to 10 later if quality/storage allows)
- [ ] Package as PMTiles
- [ ] (Stretch) terrain-RGB elevation tiles for Tier 3 displacement

## Phase 3 — Frontend

- [ ] MapLibre GL v5 globe with the PMTiles raster source
- [ ] Natural Earth borders as vector overlay layer
- [ ] Country click → fly-to → hero render view (lazy-loaded)
- [ ] Tier 1 fallback: plain HTML gallery over the same hero images, country list/search
- [ ] Capability probe (~100 LOC): WebGL2 check → GPU tier (detect-gpu or renderer
      string) → network (Network Information API where present, else tile-timing)
- [ ] Quality toggle (Lite / Globe / Full), persisted in localStorage
- [ ] Runtime degradation hook on sustained low FPS
- [ ] Respect Save-Data / prefers-reduced-motion / prefers-reduced-data

## Phase 4 — Deploy & polish

- [ ] nginx container on rohome, cache headers, PMTiles range-request config
- [ ] Pangolin route: maps.alchez.dev (or chosen subdomain)
- [ ] Lighthouse pass on all three tiers; test on a weak Android device
- [ ] About page: data credits (Copernicus, GEBCO, Natural Earth), technique notes
- [ ] Ship. Post it somewhere.

## Open questions

- Land/sea heightfield fusion: offset bathymetry below zero on one scale, or two
  separate materials keyed to a sea mask? (Decide in Phase 0.)
- Exact palette hex values — sample from reference image or design fresh in the same spirit?
- Disputed boundaries policy (India's borders differ by audience; Natural Earth has
  point-of-view variants — pick one and note it on the About page).
- Tile shading: is pure raster compositing good enough, or render z0–z6 tiles in
  Blender for true shadows and switch to raster at higher zooms?
- Storage location for the tile pyramid on rohome (which mount, backup exclusion).

## Decision log

- 2026-07-03 — Project scoped in claude.ai conversation. Architecture, data sources,
  and rendering approach locked into CLAUDE.md. Phase 0 target: India.
- 2026-07-04 — Project purpose reframed: learning/understanding every piece is the primary
  goal; the shipped site is secondary. Claude acts as guide, not workhorse. Plan is
  expected to change significantly as understanding surfaces. (Recorded in CLAUDE.md.)
- 2026-07-03 — Dev environment decided: Ubuntu boot of the dual-boot desktop for all
  work (Blender + pipeline on one ext4 filesystem, native OptiX). Windows boot and WSL
  ruled out. Rohome remains deploy target and production runner for the tile pipeline.
  Constraint noted: overnight GPU renders occupy the desktop (no gaming those nights).
