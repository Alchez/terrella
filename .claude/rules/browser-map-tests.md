---
paths:
  - "web/src/**/*.browser.test.ts"
  - "web/src/lib/testing/*.ts"
---

# Driving a real map in the vitest browser project

All measured in this runner, not assumed. The fixture is `web/src/lib/testing/mountGlobe.ts`.

- **Pre-flight `canvas.getContext("webgl2")` and throw a NAMED error.** Without it a GL-less runner reports a bare vitest timeout, which sends the reader to the assertions instead of the browser. The runner is the headless shell CI uses, with software WebGL2 via SwiftShader: deterministic, and fine for anything that is not a pixel assertion.
- **Mount MapLibre directly, never through the tier probe.** `capable()` correctly *rejects* SwiftShader, so a fixture routed through it gets Lite and measures a different page.
- **A fixture needs no tiles and should have none.** The camera is completely real with an empty style. Wiring a fixture to the local asset stores makes it unrunnable on CI and couples the test to a multi-GB archive existing; tests that genuinely need features add **inline GeoJSON**.
- **Two MapLibre APIs take a screen point and disagree about what one is.** `transform.screenPointToLocation` accepts `{x, y}`; `map.queryRenderedFeatures` does **not**, and handed one it returns **zero features**, with no throw and no warning, which reads exactly like a map with nothing rendered. It wants `[x, y]` or a real `Point`. Check the point type per call site; never generalise from the forgiving one.
- **The map centre cannot move, so it cannot test a camera.** `map.project([0,0])` on a map centred at `[0,0]` returns the viewport centre at every zoom. Any "does the camera work" assertion needs an **off-centre** ground point.
- **Assert the canvas has the size the fixture DECLARED, not that it has one.** Without MapLibre's stylesheet the canvas flows normally and hands the div a height back: 800×158 where 800×600 was declared. A silent reframe, not a collapse, and every geometric assertion sits on top of it.
- **Every mount needs an `afterEach` calling `map.remove()`.** Browsers cap WebGL contexts near 16 and evict the oldest, so one leaky file poisons every file after it in run order.
- **Keep `optimizeDeps: {include: ["maplibre-gl"]}` on the browser project**, or the first test to import it triggers Vite's optimizer mid-run and Vite reloads the page under test.

When probing the live map's own DEM, which is the only oracle that separates "loaded but not rendered" from "never loaded":

- The decoded tiles are at **`map.terrain.tileManager.tileManager._inViewTiles._tiles`**, and the doubled `tileManager` is real. `map.terrain.sourceCache` and `_sourceTileCache` are dead ends.
- **`queryTerrainElevation` returns 0.0 when the DEM for that tile zoom is not cached**, which reads exactly like flat terrain. Treat a zero as "no answer", check `dem` is present at `transform.tileZoom` first, and remember the value already has exaggeration applied.
- **The idle spin moves the camera under a probe**, and `await map.once('idle')` can hang forever at overview zooms. Pin with `jumpTo` immediately before reading, and re-read `map.getZoom()` beside the result.
- **The mesh samples every OTHER texel**, so a one-column defect on the wrong parity is invisible. That is luck, not a property.

**Say which half a file covers.** A real-map test owns the *outcome*: that a reading is true and that it moves. It cannot see a captured-reference bug that only manifests during map setup, because `map.painter.transform` is the same object across a `jumpTo` in a fixture; that belongs to a source-text guard.

Casebook: memory `testing-a-real-maplibre-map`.
