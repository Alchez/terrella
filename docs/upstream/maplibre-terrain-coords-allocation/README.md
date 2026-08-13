# Terrain RTT: `_getTerrainCoordsForRegularTile` allocates for every renderable tile, keeps ~4%

A performance report prepared for upstream [maplibre-gl-js](https://github.com/maplibre/maplibre-gl-js).
Everything here is reproducible with the library alone — `repro.html` in this directory uses public
demo tiles and no application code.

Observed on **maplibre-gl 6.3.0**, Chrome 151, Linux, RTX 4070 Super.

## Summary

`TerrainTileManager._getTerrainCoordsForRegularTile` allocates a tile-ID clone and a `Float64Array(16)`
for **every** renderable terrain tile, then discards both for every tile that is not the same tile, a
parent, or a child. The discard branch is reached *after* both allocations.

Measured on a live map during a 5 s camera ease, the ratio of allocated to kept is **27.8 : 1 at
pitch 0** — about 5,700 discarded pairs per frame, roughly 11,000 objects per frame that exist only
to be thrown away.

The fix is mechanical, changes no rendered output, and is largest at low pitch where frame rates are
highest.

## Where

`src/tile/terrain_tile_manager.ts`:

```ts
_getTerrainCoordsForRegularTile(tileID: OverscaledTileID): Record<string, OverscaledTileID> {
    const coords: Record<string, OverscaledTileID> = {};
    for (const key of this._renderableTilesKeys) {
        const terrainTileID = this._tiles[key].tileID;
        const coord = tileID.clone();          // allocated for every renderable tile
        const mat = createMat4f64();           // allocated for every renderable tile
        if (terrainTileID.canonical.equals(tileID.canonical)) {
            ...
        } else if (terrainTileID.canonical.isChildOf(tileID.canonical)) {
            ...
        } else if (tileID.canonical.isChildOf(terrainTileID.canonical)) {
            ...
        } else {
            continue;                          // ...and discarded here, for most tiles
        }
        coord.terrainRttPosMatrix32f = new Float32Array(mat);
        coords[key] = coord;
    }
    return coords;
}
```

The caller, `src/webgl/render_to_texture.ts`, runs it once per visible coordinate for each source
carrying a draped layer:

```ts
for (const tileID of tileManager.getVisibleCoordinates()) {
    const keys = this.terrain.tileManager.getTerrainCoords(tileID, terrainTileRanges);
```

So the count is *visible tiles × renderable terrain tiles*, while the related tiles per call are a
handful. (PR #7863, already merged, narrowed the outer loop to RTT-eligible sources; this is the
inner product that remains.)

## Measurements

Taken by wrapping `map.terrain.tileManager.getTerrainCoords` on a live map, counting
`_renderableTilesKeys.length` per call against `Object.keys(result).length`, over one 5 s `easeTo`.
Globe projection, zoom 5.61, terrain on. `repro.html` performs exactly this.

`repro.html`, globe + terrarium DEM over the Alps:

| | pitch 0 | pitch 60 |
|---|---|---|
| frames sampled | 825 | 825 |
| `getTerrainCoords` calls per frame | 30.0 | 53.9 |
| renderable terrain tiles per call | 15.0 | 27.0 |
| **allocation pairs per frame** | **450** | **1,454** |
| allocated : kept | **15.0 : 1** | **27.0 : 1** |

A different scene (a globe over Mars relief, 512 px tiles, three draped sources) gives 5,716 pairs
per frame at pitch 0 against 496 at pitch 60 — **27.8 : 1 and 9.5 : 1**.

**Note the two scenes disagree about which pitch is worse, so the direction is not the finding.**
What holds across every arm measured is the ratio: between 9 and 28 allocations for each one kept.
In both scenes `kept` equals the call count almost exactly — a visible tile typically has exactly
**one** related terrain tile, so the loop allocates N pairs to keep one.

Independently, a JS self-profile of a pitched pan attributes **92%** of samples whose leaf frame is
the `Float64Array(16)` allocator to `_getTerrainCoordsForRegularTile < getTerrainCoords <
prepareForRender`, with 4% under `_calcMatrices`. In the heaviest run sampled, that allocator was
27.4% of main-thread busy time.

## Proposed change

Two independent, behaviour-preserving edits:

1. **Decide before allocating.** Compute the relationship first and `continue` before `clone()` and
   `createMat4f64()`. This removes the discarded allocations entirely.
2. **Reuse a scratch matrix.** Only `new Float32Array(mat)` escapes the loop, so the `Float64Array`
   can be a single module-scope scratch that is re-initialised per hit rather than reallocated.

Both preserve the returned coords and matrices exactly; existing tests in
`src/tile/terrain_tile_manager.test.ts` should pass unchanged, which is itself the argument that no
rendered output moves.

## What this does NOT claim

- **It is not a fix for high-pitch terrain slowness.** That was the hypothesis this investigation
  started from and the measurements refute it: in the scene where high pitch was pathological, pitch 0
  allocated 11.5× *more* per frame and was the smooth arm. The waste is real and largely
  pitch-independent, and the browser absorbs it when the rest of the frame is cheap. Expect a general
  reduction in GC pressure, not a fix for a specific stall.
- **No patched build has been measured.** The expected win is inferred from the allocation counts and
  the profile attribution, not demonstrated. A maintainer should treat the numbers above as the
  problem statement and the patch as unbenchmarked.

## Related upstream work

- **#7863** (merged) — limits RTT preparation to useful sources. Narrows the outer loop; the inner
  per-tile allocation is untouched by it.
- **#8048** (open) — stops source LOD settings from reaching internal terrain tiles.
- **#8049** (open) — terrain tile detail near a pitched camera.

None of these change the allocate-then-discard pattern.

## Running the reproduction

`repro.html` is standalone. Serve the directory over http (the DEM source needs a real origin):

```
python3 -m http.server 8099
```

then open `http://localhost:8099/repro.html`. Press **Measure at pitch 0** and **Measure at pitch 60**;
each runs a 4 s settle followed by a 5 s eased pan and prints the table above for your machine.
