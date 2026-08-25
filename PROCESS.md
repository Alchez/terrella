# Terrella — processes and how long they take

- Every number here is **measured on this box** (RTX 4070 Super, 16 cores, 29 GB RAM, ext4 NVMe),
  not estimated; where a figure is an estimate it says so.
- Numbers are **current-state**, qualified by the config that determines them (grid size, thread
  layout) — never by date. When the pipeline changes, re-measure and replace; **if a number and
  reality disagree, the number is the bug.** How each number moved over time lives in HISTORY
  (§ PROCESS.md goes dateless holds the superseded values).

## How "re-run" works

- Every pipeline stage is guarded by `is_stale(output, *inputs)`: it rebuilds only if its output
  is missing, never completed (`.done` marker), or older than any input. A re-run costs
  **~0 s per stage** until something upstream actually changes.
- Tunables that never reach a file of their own (`KNOBS`, palette colours) are materialised into
  `composite_params.json` / `hs_params.json` / `tile_params.json`, whose mtime moves **only when a
  value really changes** — that is what makes the guard trustworthy against a `git checkout`.
- One stage is the exception, and it is the interesting one: **`global_occlusion` (sky-view) has
  no file to stamp**, so it is guarded by *laziness* — passed to the composite unevaluated, it
  runs only if the composite is stale.
- `build_tiles` carries a `tiles.done` sentinel + a `tiles_are_fresh` guard, and **cuts clean
  each time** (no `--resume`, so a truncated tile can't survive).
- **`tile_params.json` is part of that guard**: the cut's own settings (format, quality, tile size,
  zooms, resampling) are recorded beside the pyramid, so changing the encoding restages the cut and
  nothing upstream. Without it a format change left the pyramid reading as fresh.

## The planet tile pipeline

`python -m pipeline.tile.planet_pass --body earth [--tiles]` — or instrumented:
`bash pipeline/profile/run_pass.sh --body earth [--tiles]`

**It is ONE global streaming pass, and the shape is the cost model:** warp → per-row-z hillshade
(full-width, with a 1-row halo, which is what makes it seamless) → globally-normalised SVF →
per-window composite. Nothing here is per-country.

**The two shade paths have opposite staleness exposure, deliberately.** `shade.py` (region) re-warps
on every run, so it is always current and is the right pre-flight before a re-fuse. `shade_planet.py`
caches its warps — exposed by design, and covered by `is_stale`.

**RAM: the region path is NOT windowed, so cell count is a direct multiplier.** Four cells is roughly
**14.5 GiB** and gets OOM-killed under the 12 G cap, so scale the cell count to the cap rather than to
the area you want. The planet path *is* windowed and does not have this failure mode.

**`gdal raster tile` needs `--tile-size 512` explicitly** — the default is 256, which halves the
master. And never tile a many-source VRT: materialise a tiled GTiff with overviews first.

The whole cost model in one picture — where a look change enters is what it costs:

```mermaid
flowchart LR
  HK(["hillshade-stage knob<br/>fill_strength · shadow_* · EXAG · alt"]) --> HS
  CK(["composite-stage knob<br/>ramps · tone · snow · sea ice · lake"]) --> SVF

  W["warps → 3857 grid<br/>(one-time per grid change)<br/>height 6:49 · masks 3:30<br/>lake 1:01:44 · snow 15:16 · ice 14:42"] --> HS
  HS["hillshade + fill sun<br/>16:20"] --> SVF["sky-view factor<br/>3:23 (lazy)"] --> C["composite<br/>21:37"] --> T["tile cut z0–8 → WebP q95<br/>4:19"] --> PK["pack + convert<br/>0:10 + 0:06 → 3.1 GB planet.pmtiles"]
  C -. auto, ~1:35 .-> CAP["polar caps<br/>→ web/public/caps/"]

  HK -. "≈ 46 min to live tiles" .-> T
  CK -. "≈ 29 min to live tiles" .-> T
```

The hero pipeline is the other lane (separate table below): per-country prep walk **1.25 s warm**
(six guarded stages) → Blender render **1:29–3:36** → full 203-country sweep **~10.5 h**, GPU-bound.

All stage numbers below are at the **131072² grid** (the full Mercator square) with the composite
**threaded 128-row/4-worker**:

| # | Stage | First run | Re-run (fresh) | Output | Guard |
|---|---|---|---|---|---|
| 0 | `fuse/fuse_planet.py` — 648 cells @ 10″, 12 workers *(separate command; run `build_mosaics.sh` first after any tile download — a stale mosaic fuses new land as ocean)* | **~15 min** (43 s/dense cell; the 108 polar cells ~2 min total — GLO-30 thins toward the pole) | skip | `work/planet/chunks/` (648 cells) + 3 VRTs + the seam declaration, 14 GB | per-cell exists() |
| 0a | `fuse_planet.py --masks` — the two MASKS re-fused at 1″ latitude × 10″ longitude, **6 workers** *(2.5 GiB each measured; `mem_available_gib` reads the host and cannot see the 16 G cap, so pass `--workers` explicitly)* | **27m44s** (648 cells; **faster than the square pass at 10× the rows**, because masks-only opens no GEBCO, writes no Float32 master and builds no overviews over one) | skip | `oceanmask_1x10s` + `watermask_1x10s` beside the square chunks, **+840 MB**; the mask VRTs become 129600 × 648000 | per-cell exists() on its OWN output |
| 0b | `--build-vrts` alone — re-index the chunks and re-declare | **~20 s** (opens all 648 chunks per raster) | same, and **replaces nothing**: the XML is byte-deterministic, so an unchanged planet keeps its VRT mtimes and stages 1–8 stay fresh | 3 VRTs + `planet_rasters.json` | content compare |
| 1 | warp height → 3857 | **6:49** | ~0 s | `height_3857.tif` 44 GB | `is_stale` |
| 2 | warp ocean + water masks → 3857 *(row 0a's 1″ latitude × 10″ longitude masks. The 3857 grid is FIXED at 131072², so a finer source changes the bytes and never the pixel count, which is why this stage grew by half and not by ten)* | **5:03** (ocean **2:30** + water **2:32**, still near-equal as they were at 10″) | ~0 s | **94 MB** (35 + 59), against 69 MB at 10″: same pixels, more resolved coastline, so deflate has less to squeeze | `warp_needs_rebuild` |
| 3 | warp GLOBathy lake depth → 3857 | **1:01:44** (nodata-masker-bound, 102% CPU; no lakes south of −60°, the cost lives in the 50–70°N belt) | ~0 s | `lakedepth_3857.tif` 310 MB | `warp_needs_rebuild` |
| 3b | warp snow persistence (banded) + rasterize glaciers + rasterize Antarctic rock + warp sea ice (banded) → 3857 | **snow 15:16, glaciers 0:19, rock 0:27, sea-ice 14:42** | ~0 s | `snow_persistence_3857.tif`, `glacier_3857.tif`, `addrock_3857.tif`, `seaice_3857.tif` | `warp_needs_rebuild` |
| 4 | `look/hillshade.py` — per-row z-factor **+ fill sun** | **16:20** | ~0 s | `hs_3857.tif` | `is_stale` |
| 5 | `global_occlusion` — sky-view factor | **3:23** (I/O-bound) | ~0 s | in-memory only | **lazy** |
| 6 | `composite_planet` — ramps × hillshade × SVF + snow + sea ice + lake depth | **57:23** (1024 windows at 0.30 win/s; the Antarctic windows are all snow+ice work) | ~0 s | `planet_rgb.tif` 11 GB | `is_stale` |
| 6r | `tile/block_render.py`, the raytraced producer: 1024 blocks through Cycles, one at a time *(it REPLACES stages 4, 5 and 6 rather than adding to them, because every block lights itself, so no hillshade and no SVF are built at all. `Body.planet_producer` chooses it, Earth `"raytrace"` and Mars still `"composite"`, and the header's composite threading does not apply to it)* | **11:41:33** at 1.46 blk/min, 1024 blocks, 0 failures, on the RTX 4070 Super. Per block **23.8 s min, 34.5 s median, 41.1 s mean, 76.8 s p95, 194.3 s max**. Median does rise with context size (27.9 s at 128 px against 60 to 140 s above 1536 px) but only 25 of 1024 blocks sit that high, and **context explains little of the block-to-block spread, r = 0.39**: the slowest block is `r02c09` at 194.3 s on a mid-range 896 px context, so the tail is not polar and what drives it is not established. | **~0 s**, but ALL OR NOTHING: blocks skip on per-block markers, and if any input or the recipe moved, `start_generation` clears the entire marker set and all 1024 re-render | `planet_rgb.tif` **30 GB** (the composite writes 11 GB to the same path) | `raytrace_deps` + `raytrace_params.json`, checked by `generation_is_current` against the generation stamp |
| 7 | `build_tiles` — `gdal raster tile` z0–8, WebP q95 | **4:19** | **skip** | `tiles/` **3.1 GB**, 87,381 tiles | `tiles.done` + `tile_params.json` |
| T | `tile/terrain_rgb.py` — terrain-RGB encode + cut **z0–8**, 8 m, lossless WebP *(separate lane: reads `height_3857.tif` directly, never the composite, and is not part of the planet pass)* | **30:14** cold, whole `elev_z*` chain built, of which cutting is 8:08 (z8 alone 5:31). The **41:00** this replaced was measured before the latitude ramp was deleted from the encode, which removed a per-row inverse-Mercator projection and a smoothstep multiply from every window. A z0–6 variant is **~4 min** once the chain exists. | **skip** | `work/planet_terrain/bathy_s8_webp/tiles/` **2.72 GB**, 87,381 tiles | `tiles.done` + `terrain_params.json`; chain on `elev_z*.done` |
| R | `tile/relief_scan.py`, the block partition's per-cell cache *(separate lane: streams `height_3857.tif` + the ocean mask once and feeds `block_plan`; not part of the planet pass)* | **3:07**, 1.5 GB peak (Mars measured **0:41** at its 65536² z7 grid) | ~0 s | `relief_cells.tif` + `ocean_cells.tif` | `is_stale` + `relief_params.json` |

### The same pass on Mars — measured, at the 65536² z7 grid

`python -m pipeline.tile.planet_pass --body mars --tiles`. The pass this column is taken from ran
**7:35 with the warp and the hillshade already fresh**; composing the carried warp onto it puts a
cold pass near **16:52**, against ~52 minutes for the equivalent Earth stages plus the hour and a half
of optional-layer warps Mars still mostly does not pay.

**NO SINGLE RUN HAS PRODUCED EVERY ROW, AND THE COLUMN SAYS WHICH.** The sky-view, composite, cut and
memory figures come from one instrumented pass whose profile log survives. The seam, hillshade and
whole-pass figures come from the seam rebuild, taken from stage mtimes and the scope's own accounting.
Only the **warp** is carried from the cold z7 pass before it, whose log the next run overwrote —
`_profile_tiles/` keeps only the most recent — so it is the one number here that cannot be re-derived
without a rebuild. The caps printed fresh and skipped, so their cost is still the separately-measured
figure.

**THE SEAM REBUILD IS ITS OWN SHAPE, AND IT IS THE ONE A FIX TO THE MASTER COSTS: 9:10 wall, 34:29
CPU, 14.9 G peak** — everything from `close_wrap_seam` down, with the warp and the ice alpha both
fresh and skipped. It is under the 16 G cap rather than pinned at it precisely because the ice stage,
which is where a Mars pass peaks, did not run.

| Stage | Earth z8 | Mars z7 | Note |
|---|---|---|---|
| warp height → 3857 | 6:49 | **4:37** | read-bound on the 10.6 GiB source, not pixel-bound. Carried — see above |
| `wrap_seam.close_wrap_seam` | ~0 s | **0:42** | the whole-raster hole scan, then one column written — a read of the warp's output in 1024-row bands and nothing else. **Earth pays none of it**: its warp declares no nodata, so the function returns before the scan, and the same is true of any raster this has already closed. That is what lets the call sit outside the warp's freshness gate, where it has to be to reach a master already on disk |
| ice alpha, polar bands | — | **2:23** | `mars_ice.build_alpha_raster`. The one optional layer Mars declares, and the pass's memory peak |
| warp masks + lake + glaciers + sea ice | 1:35:31 | **0:00** | declared, not skipped by absence — every gate prints its reason |
| `look/hillshade.py` | 16:20 | **3:38** | at Mars's own 20× and its own sphere |
| `global_occlusion` | 3:23 | **0:52** | |
| `composite_planet` | 21:37 | **2:58** | 512 windows, 2.88 win/s, threaded ×4 |
| `build_tiles` z0–7 | 4:19 | **1:21** | 21,845 tiles, 1.4 GB |
| `cap_render` | 1:36 | **~1:15** | Both discs, from the heightfield alone. Bounded by artifact mtimes on a run whose elevation rungs were already fresh, and it SKIPPED on the pass above |
| pack + convert | 0:16 | **~4 s** | `planet.pmtiles` **1.40 GB**, **20,950 unique tile bodies of 21,845** — counted over the cut directory, which is what the archive dedupes on |
| T · `tile/terrain_rgb.py` z0–7 | 41:00 | **8:15** | the separate lane, cut cold from the master. z7 alone is **1:36** and the whole `elev_z*` descent beneath it **1:03**, so the ceiling is most of the cost. **21,845 tiles, 0.77 GB** |
| T · `tile/terrain_rgb.py` z0–7, re-cut | — | **6:03** | the same cut with the elevation chain already on disk. `elev_z*` is gated on the master's mtime and NOT on `terrain_params.json`, so a recipe change re-encodes and re-cuts every zoom while re-descending none — z7 1:41, z6 0:27 |

**A COLD MARS SHADE PASS WITHOUT `--tiles` IS 15:54**, measured end to end — the first run to build every
stage from nothing rather than carrying rows. The per-stage split is not restated from it: its log
carries only the composite's own timing (174.0 s, 2.94 win/s), and the rest would have to come from
file mtimes at minute resolution, which is coarser than the instrumented figures above. The caps
printed fresh and skipped, which is correct and not a shortcut — `cap_sources` reads the VRTs and the
ice sources, never `height_3857.tif`, so rebuilding the master cannot restage a cap.

### Memory: what a cap has to back, and which of the three readings says so

This block is the authority for both cgroup caps, and `pipeline/profile/pass_cap.py` argues from its
figures by name. A heading rather than a bold lead-in because code cites it: a load-bearing block
nothing can point at is one nobody re-reads before changing a number.

**THREE MEMORY NUMBERS, AND ONLY ONE ANSWERS "DID IT FIT".** The cgroup's `memory.peak` is charged
for reclaimable page cache — the source read and the outputs written — so it overstates what the box
must actually hold. Summed per-process `VmHWM` overstates in the opposite direction and worse: it
adds LIFETIME high-water marks across children that never coexisted, and this pass forks gdalwarp,
gdal_translate, the tile workers and `cap_render` in sequence. **A Mars tiles pass sums to 19.03 GiB
of `VmHWM` under a 16 G cap that never fired**, which is proof the sum is not a simultaneity measure
and cannot size a cap. Size it off the **peak instantaneous summed RSS**.

On that same pass the three read **14.73 GiB** cgroup peak · **19.03 GiB** summed `VmHWM` ·
**8.85 GiB** peak live RSS, the last reached in the cap stage — so on Mars the caps, not the
composite, are what the cap has to back. An earlier Mars figure of 4.01 GiB is superseded twice
over: it was taken before Mars rendered caps at all, and by the summing method above.

**MARS PER STAGE AT z7, PEAK INSTANTANEOUS SUMMED RSS** — ice alpha **5.91 GiB** · composite
**4.37 GiB** · tile cut **2.95 GiB** · sky-view **0.64 GiB**, with the cgroup's `memory.peak` pinned
at the 16 G cap throughout and no kill. **The pass's peak is the ICE stage, not the composite**, which
is the opposite of Earth and was not true of Mars before this layer existed — `graded_alpha` evaluates
both poles in float64 across a band 65536 px wide, so a slice costs several times its float32
footprint while it is in hand. Ranked, what the cap has to back on Mars is caps 8.85 > ice 5.91 >
composite 4.37 > cut 2.95.

**EARTH, PER STAGE, PEAK LIVE RSS** — composite **12.56 GiB** · tile cut z0–8 **3.74 GiB** ·
`cap_render` **14.41 GiB**, with the cgroup peak pinned at the 16 G cap throughout (page cache,
reclaimed under the limit, never a kill). **The caps alone are what the cap has to back, on both
bodies**, and two older claims fall out: the composite does not peak at 10.55 GiB, and the tiling
stage does not approach 16 G. `GDAL_CACHEMAX=512` across `-j ALL_CPUS` workers is an upper bound
that never fills — measured at 3.74 GiB across the whole cut, 537 samples, making it the LIGHTEST
of the three stages rather than the reason for the cap.

**THE COMPOSITE ROW SAYS 57:23, AND CONTENTION IS NOT WHAT PUT IT THERE.** The row read **21:37**
for most of this file's life. A recipe-only restage of that same stage measured **26:40** while a
desktop session held ~6.5 GB of swap, and on that run the cut (4:29 against 4:19) and the caps (1:42
against 1:36) both matched, so the long DRAM-bandwidth-bound stage is the one that pays for
contention and every other figure here assumes an idle box.

**A full pass then measured 57:23**, on the same 1024 windows, threaded x4, at 0.30 win/s. That is
**2.2x the contended figure and 2.65x the original**, and the stages around it on that same pass
matched their records: sky-view **3:13** against 3:23, cut **4:30** against 4:19, glacier burn
**0:19** against 0:19. The whole pass came to **68:52**. Its cap stage read 3:00 against a recorded
1:36 and is NOT comparable: it re-rendered both colour discs and wrote the south elevation texture
while skipping the north's, so it did more work than the figure it is being read against.

**NO CODE CHANGE ACCOUNTS FOR IT, AND THE ICE-EDGE FEATHER IS REFUTED RATHER THAN UNTESTED.** A
cProfile over six real windows sampled across latitude, running the same `_compute_shared` +
`_compose` a worker runs, prices `soften_source_cells` at **4.1%** of composite compute (0.42 s of
8.19 s per window). Everything added since the 21:37 measurement summed is **9 to 14%**, an order of
magnitude short of the 165% the wall clock grew by, and `composite()` itself carries **35 numpy
operations against 33** in the commit that recorded 21:37. Grid, window count, threading, layer
count and the 16 G cgroup cap are all unchanged between the two measurements.

**The live candidate is sustained I/O under the cap, and no isolated rig can see it.** Reads measure
0.81 s per window on six windows, which would make the stage compute-bound, but that rig has a warm
cache and a real pass streams ~86 GB through a 16 G cgroup that `memory.peak` shows pinned at its
ceiling throughout. The production evidence points the same way: **per-window compute varies 1.87x
across latitude (6.00 s to 11.23 s) while the pass's own wall rate varies only 1.14x** (36.1 to 41.3
rows/s, flat from pole to pole), so something uniform is absorbing the compute variation. Settling
it means instrumenting the REAL pass for per-window read against compute, not building another arm.

**`pipeline/profile/run_pass.sh` sizes its cgroup cap from the body, and both bodies now want 16 G.**
`pipeline/profile/pass_cap.py` derives it from `renders_polar_caps` and holds both measurements. 16 G
is the cap-rendering number because the pass ends by invoking `cap_render` as a subprocess that
inherits the scope's cgroup and peaks near 14 GB; a body that renders no caps never reaches that
stage, so on it 16 G is unbacked rather than protective and the harness's own `MemAvailable`
preflight would refuse a pass the box could comfortably have run. Mars answered 12 G until its ramps
were ratified and its caps went on — the standing 12 G branch is live code with no body currently
taking it. The resolver reads `--body` through the pass's own argument parser, so an omitted body is
refused at the wrapper instead of after a cgroup scope has already been opened.

**`MEMORY_CAP_OVERRIDE_GIB` substitutes the number afterwards**, and prints that it did. It is read
*after* the resolver, never instead of it, so `--body` stays enforced; a non-numeric value aborts,
because bash would otherwise evaluate it as 0 and every box would clear every cap. It exists because
with no body on the 12 G branch nothing else can show that the shell uses the number it is handed
rather than a constant — `pass_cap` runs in a subprocess, so no test fixture can reach its registry.

### Mars's ice band takes ONE direct warp, and here is the measurement that settled it

`snow.warp_persistence_raster` and `seaice.warp_seaice_raster` warp in sub-bands because a
whole-grid warp's pole-inflated average scale makes GDAL read the source decimated — no error, no
symptom beyond structure quietly going missing, recorded there as Ruapehu falling 0.756 → 0.409.
Mars's ice occupies a band of a few degrees rather than a planet, and a band's scale spread is about
2.2× against the whole grid's 11×, so the question is whether it decimates too. Measured on the real
32768² z6 grid over the 76–84° band, three arms:

| arm | max \|diff\| vs the sub-banded reference | high-frequency energy |
|---|---|---|
| one direct warp | **0.0000 DN** (1 differing pixel of 145,555,456) | **+0.00%** |
| source decimated 4× first — the CONTROL | 61.11 DN | **−53.2%** |

**The metric is the deviation of the field from its own 3×3 mean, not mean error.** Decimation is a
smoothing: it can leave the mean and the rms nearly untouched while erasing exactly the structure an
ice edge is made of. The control is what makes the null result mean anything — a comparison that
cannot see a known-decimated read cannot report a clean one.

So `mars_ice._warp_band` is a single `gdalwarp` and must not grow banding: it would cost a
subprocess per sub-band for output already shown identical, and would read as though the question
were open.

**Re-measure if Mars's `tile_max_zoom` or `look/viking_luma`'s grid moves**, since both change the
scale ratio this rests on. The probe was scratch and is not shipped; rebuilding it is three warps of
the same band — sub-banded at `WINDOW_ROWS`, direct, and direct from a 4×-downsampled source — and
the two comparisons above.

**THAT TRIGGER HAS FIRED AND THE RE-MEASUREMENT IS OWED.** The ceiling moved to z7, so the table above
describes a grid the pipeline no longer cuts. It is not urgent, and the reason is a derivation rather
than a measurement — the failure mode is DECIMATION, and halving the target pixel doubles the
upsampling, moving the direct warp further from the condition that produces it. Do not let that
argument stand in for the control-backed table; it says only that the risk moved the safe way.

### The look loop on Mars — WARM iteration costs, which are what a look session actually pays

A cold pass is the wrong number to plan a look session with. Measured on repeated **z6** passes, warm,
at 20×, under the 12 G cap Mars had at the time — so the SHAPE below is current and the wall clocks
are one grid behind. Scale them by the composite's own measured ratio, **0:46 → 2:58, i.e. 3.9× for
4× the pixels**, rather than re-deriving a factor from the pixel count:

| Change | What restages | Wall clock |
|---|---|---|
| a ramp, **judged from the composite** (no `--tiles`) | sky-view + composite | **~1:03** |
| a ramp, judged on the globe (`--tiles`) | the above + the tile cut | **1:36** |
| the exaggeration (`Body.exaggeration`) | the above **plus** the hillshade | **2:14** |
| neither — a re-pack alone | nothing upstream | **~4 s** |

**Every row above is now ~1:15 longer, and the floor is 16 G.** The cap stage runs OUTSIDE the
`--tiles` branch, so turning Mars's caps on put it in the composite-only loop too — the cheapest
iteration is no longer ~1:03. Not skippable by a flag, deliberately: skipping the caps while the
tiles moved is what produced the −6.7 DN cap-vs-tile seam drift, and the look is ratified, so the
loop is now rare enough to pay for correctness.

**Drop `--tiles` while iterating and take the frames off `planet_rgb.tif` directly.** Measured over five
consecutive z6 candidates: 62–64 s each against 1:35 with the cut. Nothing about the colour is decided
by the tiler, so cropping the composite with `gdal_translate -srcwin` shows the ratified pixels with no
browser resampling, no globe projection and no atmosphere in the way — and it is the same raster the
tiles are cut from, so it cannot disagree with them. Run `--tiles` once, at the end, on the variant
that won.

- **A ramp change must not restage the hillshade, and does not**: the exaggeration is in `hs_params`
  and the ramps are not, so a ramp-only pass skips straight to the sky-view. Watch for that skip —
  a hillshade line appearing on a ramp-only change means a composite knob has leaked into
  `hs_params`, which is a 46-minute mistake on Earth.
- **The height warp never re-runs for either.** Both levers are downstream of it, so the 2:12 that
  dominates a cold pass is paid once.

**Three commands, not one — the archive is a separate chain from the pass.** Nothing in the pass
touches `planet.pmtiles`, so a look change is invisible in the browser until all three have run:

```
pipeline/profile/run_pass.sh --body mars --tiles
python -m pipeline.tile.pack_pmtiles --body mars          # → planet.mbtiles, the bridge
tools/pmtiles convert …/planet.mbtiles …/planet.pmtiles   # → what the dev server reads
```

The dev server serves tiles `no-cache`, so a plain reload picks up a re-pack; **the committed tile
token does NOT need regenerating to iterate**, because an address's token does not decide which
archive it resolves to. The token is a cache key for the CDN, so it is a deploy concern only.

**Archive size moves with the look, which is a deploy cost rather than a loop cost.** The same z6
pyramid packs to 356 MB at 10× and 438–454 MB at 20×: more relief is more WebP entropy. It changes
nothing about iterating locally and adds ~100 MB to every R2 upload once the archive lands.

Why the numbers are what they are (current-state explanations, not history):

- **The composite is DRAM-bandwidth-bound, not I/O-bound**: full-width windows make every
  3-channel array ~402 MB against ~32 MB of L3, so every numpy op is a DRAM round-trip — which is
  why threading caps at ~3.5× and bigger windows do not help.
- **The 128-row window is for the memory cap, not speed**: it fits 4 workers under `MemoryMax=12G`
  (256-row/3-worker OOMs). The threaded layout shifts the look sub-perceptibly (worst 20 DN on
  mountain snow, invisible at true scale).
- **The fill sun doubles the hillshade arithmetic** (a second `hillshade_array` per window, same
  blocks, no extra I/O).
- **A grid change restages every warp**: `warp_needs_rebuild` = mtime **or** off-grid, so the
  warps re-run only when the grid grows (next trigger: a z10 extension). The Antarctica grid
  change measured **2:28:01** end-to-end, dominated by the 1:01:44 lake warp.
- **Stage T's ~4 min is three independent measurements, not one.** The first run built the shared
  elevation chain and the `clamp` variant in **7:55**, then `bathy` in **3:53** reusing it — so the
  chain is ~**4:02** and a variant is ~**4 min**. Three later re-cuts at 2/4/8 m, chain present,
  came in at **3:49 / 3:57 / 4:16**. It is a single streaming descent from the 44 GB master, so it
  is I/O-shaped, not DRAM-bound like the composite.
- **Lossless WebP cuts ~3.8× FASTER than PNG, as well as 0.67× the size.** Same variant, same 8 m
  step, z6 cut alone: **PNG 1:49 vs WebP 0:29** (z5 0:42 → 0:12, z4 0:35 → 0:10). PNG's adaptive
  per-scanline filtering plus zlib 9 is simply more work than the WebP lossless coder. The whole
  z0–6 cut at the shipping settings is **~0:57**.
- **Stage T is guarded like every other stage.** `tiles/` is cut into `tiles_new`, swapped only on
  success, stamped `tiles.done`, and keyed on the master's marker plus `terrain_params.json` — so a
  `--step`, `--format` or `--max-zoom` change restages and nothing else does. One generation of
  rollback stays at `tiles_old`. The elevation chain moved off `exists()` onto its own `.done`
  markers, which is what stops a half-written level being trusted: rasterio creates its target at
  write-start, so the BigTIFF crash below left a full-sized truncated `elev_z8.tif` that an
  existence test accepts, and a truncated float32 raster reads as a very flat planet rather than as
  an error.
- **z7/z8 MEASURED 2026-07-28, and both projections here were wrong in the same direction.** The
  full z0–8 build is **41:00** and **2.63 GB**, against projections of 1.5–2.5 h and ~3.3 GB — so
  ~3× over on time and 25% over on size. Per-zoom cut: **z8 5:29, z7 1:37, z6 0:27, z5 0:12,
  z4 0:10, z3 0:05**, the rest sub-second.
- **CORRECTION — z8 *did* write an elevation intermediate, and it was 47 GB of nothing.** This file
  and HISTORY both claimed `--max-zoom 8` "encodes `height_3857.tif` in place"; it did not. The
  factor-1 branch still called `downsample_elevation`, so the build materialised `elev_z8.tif` —
  a byte-for-value copy of the 46 GB master, proven identical over six windows at exactly 0.0000 m
  with shifted-window controls differing by 240–1660 m. Part of the 41:00 was spent making it.
  `elevation_source` now returns the master itself at its native zoom, so **the claim is true going
  forward and was false when written**.
- **BigTIFF is mandatory past z6 and was missing until 2026-07-28.** The first z0–8 attempt died in
  83 s on `TIFFAppendToStrip:Maximum TIFF file size exceeded` — `GTIFF_CREATE` sets no BigTIFF and a
  classic TIFF caps at 4 GB. It could not surface below z7, and **z6 was surviving on deflate alone**
  (32768² float32 = 4.29 GB raw, 3.4 GB on disk). Both `terrain_rgb.py` sinks now pass
  `bigtiff: "IF_SAFER"`.

**End-to-end, measured:**

| Scenario | Wall | Notes |
|---|---|---|
| **A hillshade-stage re-tune** (`fill_strength` → live tiles) | **~46 min** | hillshade 16:20 + SVF 3:23 + composite 21:37 + tile cut 4:19. Warps all skip. |
| **A composite-stage re-tune** (`snow_curve`, `ICE_LO`, ramp colours → live tiles) | **~29 min** | SVF 3:23 + composite 21:37 + tile cut 4:19. |
| Everything cold, shade only | **~41 min** (+ the cut → ~46) | excludes the one-time lake warp + fuse |
| `--tiles`, everything fresh | **~0.4 s** | the cut is guarded; it runs only when `planet_rgb` actually changed |
| No `--tiles`, everything fresh | **0.29 s** | every stage skips; this is the guard working |
| Lake-depth warp (stage 3) | **1:01:44** | one-time; its `.done` is what stops a pass paying that hour again |
| **Cast shadows** (`shadow_strength` > 0 — currently 0.0, rejected) | **+0.625 s/Mpx** measured; est. **+2.1 h** on the planet hillshade at `shadow_reach=300` | Iran region A/B (32.4 Mpx): 16.73 s control → 37.01 s, **+121%**, peak RSS unchanged (the wide halo costs time, not memory). The march is `reach_px` full-raster passes — cost is **linear in `shadow_reach`** (300 px ≈ 2.6 h, covers 6,115 m of relief). Hillshade-stage, so ~46 min + the shadow march to see it. |
| **Polar cap render** (`tile/cap_render.py`) | **~1:36** both caps at the production 8192² (54 + 42 s), peak **14.3 GB north / 13.9 GB south** (measured under `systemd-run`, anon RSS) | AEQD warps + the shared `shade.composite` + baked coastline → `web/public/caps/cap_{north,south}_{1024,2048,4096,8192}.webp` (both caps together: **155 KB · 559 KB · 1.7 MB · 5.1 MB**, WebP q85) + `caps.json`. Every rung is downsampled from the one render, so the whole rung set costs ~1 s, not a second pass — adding the 1024/2048 rungs did not move this row's runtime (re-measured 1:39). The web layer picks one by the cap's projected on-screen size, so a default visit fetches only the 1024s. The fast browser-free pole-look loop. **Freshness-guarded** by a recipe sidecar carrying every input that can move a cap pixel, plus source mtimes; the planet pass's tail invokes it (`tile/planet_pass.py`), so the caps restage whenever the look does — a fresh check is ~2 s. |

> ⚠ **The cap render does NOT fit under the old 12 G cap** — it OOM-killed twice at a 12.5 GB
> anon-RSS peak before being measured at ~14 GB (this row previously claimed ~4 GiB, which was
> never true at 8192²). It needs **≥16 G**, and that reaches beyond a manual run: `planet_pass.py`
> invokes `cap_render` as a subprocess at the tail of the planet pass, inheriting the pass's cgroup —
> so a pass at `MEMORY_CAP=12G` completed every tile stage and then died at the last one.
> **Resolved:** `run_pass.sh`'s shade cap is now **16 G**, matching the tiling run, and
> `pass_cap.py` derives it per body. `COMPOSITE_ROWS=128` is a hardcoded constant rather than a
> function of the cap, so a bigger cap cannot let the composite grow into it. Accepted cost: 12 G
> was also an accidental tripwire on composite footprint, and a regression there now hides until
> 16 G. **That tripwire had already fired by the time anyone looked**: the composite is measured at
> **12.56 GiB** in § EARTH, PER STAGE above, so it no longer fits under 12 G at all.

**Memory preflight (both run labels).** `run_pass.sh` reads `MemAvailable` and **refuses to start**
when it is below the cap, because a cap the box cannot back protects nothing — it relocates the OOM
to the most expensive moment, hours in, after every finished stage has been paid for. `MemAvailable`
is the kernel's estimate of what a new job can take without swapping, which is the actual question
(`free`'s "free" column undercounts by ignoring reclaimable page cache). Override deliberately with
`ALLOW_LOW_MEMORY=1`; point `MEMINFO` elsewhere to test the guard. **This box runs close to the
line** — ~16.7 GiB available against the 16 G cap with a browser and editor open, so expect the
preflight to be a real gate, not a formality.

**What a knob actually restages** (measured, not inferred): all warps skip, including the 1:01:44
lake warp. A **hillshade-stage** knob (tracked in `hs_params.json`) restages hillshade → SVF →
composite → tiles — **~46 min**. A **composite-stage** knob (tracked in `composite_params.json`)
restages SVF + composite → tiles — **~29 min**. The composite is the bulk of any art iteration
(§ the composite is threaded is the 3.5× that made iterating viable), and the caps auto-restage
(~1:35) behind either knob.

Peak RSS is **12.56 GiB** for the threaded composite, measured as peak live RSS in § EARTH, PER
STAGE above; the **10.55 GiB** this line used to give was taken by a retired method, and the 1.14x
headroom it claimed under a 12 G cap was never available. The pass runs under **16 G** whichever run
label it takes, sized per body by `pass_cap.py`, and the cut is the lightest of the three stages
rather than the reason for the cap. **`memory.current` is not RSS**: during tiling the cgroup sits at
~16 GiB, but that is reclaimable page cache (`anon` 0.58 GiB), so watch **anon**, not the total.

## Hero renders (separate pipeline — Blender, not the tiler)

| Stage | First run | Re-run | Output |
|---|---|---|---|
| `render/render_prep.py --frame` → `frame.json` | ~seconds | `is_stale` | per-country frame + warps |
| `render/lake_mask.py` (stage 6 of 7) | **0:11 finland (lake-densest) / 0:03 estonia** — the feared 83k-source-VRT warp cost is seconds, not minutes | skip-if-exists | `lakedepth.tif` (log1p ramp position) |
| `render/scene_build.py --render` — headless Cycles, OptiX | **3:36 @ 8K** (finland 1:29 at 4142×7680) | n/a | one hero PNG |
| Full batch — **203 heroes** | **~10.5 h measured** (a full sweep at the current scene rig: 203 heroes, 0 fail; 9.36 h GPU-bound = 89.5% duty; host RSS peaked ~10 GB against the host-derived cap that run used, ~25 GB, since superseded by the ratified 16 G → the single 12 GB GPU is the wall, more RAM saves nothing) | per-country resume | `blender/renders/` |
| `look/sky_view.py` re-shade (look re-tune, no re-render) | **no GPU, minutes** — re-runs the AO over the kept `heroes/raw/*.png`; a `sky_view_strength` change re-shaded all 203 with no Blender pass | — | shaded `heroes/*.png` |
| Targeted re-render (e.g. a sea-floor fix across 7 microstates) | **~28 min** (~4 min each, tiny frames) — rm `heightfield.tif` + hero + raw, then `batch --through render --only` | per-country resume | the named heroes |
| `batch --through prep`, warm walk | **1.25 s/country** (six guarded stages) | same | prep-complete markers |

- 8K frames denoise on **CPU**, not GPU: GPU render + GPU OIDN contend for the 12 GB VRAM → Xid 31
  MMU fault.
- **The base grid is why the hero lane keeps its single quad, and the wall is host RAM as well as
  VRAM.** Measured on this box's 12 GB card, micropolygons per plane: a render block lands near
  **21M** and is comfortable, Nepal at **41.8M** renders but takes **177% longer**, and Australia at
  **67M** fails outright with `Failed to build OptiX acceleration structure`, having wanted
  **17.0 GB** of host against the ratified 16 G. Which frame sizes sit on which side is unmeasured:
  Nepal clears it at 36.8 Mpx and Australia does not at 58.8. `pipeline/profile/pass_cap.py`,
  `pipeline/batch.py` and `render/scene_build.py` all argue from the 17.0 GB figure, and this row is
  where it is measured.
- The warm walk is near-free because the two expensive per-country redundancies are guarded:
  `build_mosaics.sh` skips when its `.sources` sidecar matches (17.6 → 0.63 s) and
  `download_glo30` runs one ETag preflight per day (`preflight_ok.json`, then ~0.07 s). What
  remains is the deliberate subprocess-import tax (six isolated GDAL/rasterio starts — OOM
  isolation).

## Acquire (one-time, network-bound)

Run once; all are resumable and verify against a pinned size/md5, so a re-run is a no-op.

| Source | Size | Notes |
|---|---|---|
| Copernicus GLO-30 | **551 GB** | per-country, on demand — never bootstrapped globally (Russia alone ≈ 4,900 tiles) |
| ESA WorldCover | 114 GB | **hero snow only**, not the tile pipeline |
| GLOBathy | 16.7 GB zip | → 83,357 per-lake rasters; **reclaimable once extracted** |
| GEBCO 2026 | 7.3 GB | bathymetry + ice surface |
| RGI 7.0 glaciers | 2.7 GB | tile snow; **all 19 regions**, of which the merged `rgi7_g_3857.gpkg` is 1.1 GB. The merge ran **~40 min** while it carried `-skipfailures`, which sets the transaction size to 1: free into an empty table and quadratic into a populated one, measured at 51.8 s against 1.3 s appending region 19 into a 75,613-row base. That flag is gone and **the whole-merge cost without it has not been measured**, only the single-region A/B |
| NSIDC-0791 snow persistence | 1.6 GB | tile snow |
| OSI SAF sea ice (OSI-450-a) | 640 MB | tile sea ice; **anonymous** THREDDS, **serial** (OSI SAF forbids parallel); 720 monthly files → the 1991–2020 frequency climatology |
| Cop30 void-fill | 1.2 GB | fusion void-fill |
| Natural Earth | 38 MB | borders, framing, coastline oracle |

## Frontend and serving

| Process | Command | Time | Notes |
|---|---|---|---|
| Astro dev server — **the product globe** | `pnpm dev` in `web` | ~2 s | `/earth` on Astro's default port 4321 (not pinned in config); serves the three store routes (`/heroes`, `/borders`, `/tiles`) — the first two from `web/.env` paths, the third derived from the work tree — dev-only middleware, `no-cache`. `/tiles` answers THREE archives in-process, addressed `{body}/{layer}/{token}/{z}/{x}/{y}.{ext}` — `earth/relief` from `planet_tiles/planet.pmtiles`, `earth/terrain` from `planet_terrain/terrain.pmtiles`, `earth/vector` from `planet_vector/vector.pmtiles`, each under the requested body's work tree. That is the shape the page asks for (verified live: 407 tile requests, none legacy-shaped). The untokened shapes production served before the scheme — `{z}/{x}/{y}.webp`, `terrain/…`, `countries/…` — still resolve, through the same resolver the Worker uses, so a page built before a deploy keeps drawing. The local twin of the production tile Worker, parsing with the same module it does. The vector pyramid is the SPARSE one: a missing tile answers 204 there and 404 on the two raster pyramids. The retired layer word `countries` is still accepted in the addressed position and served as `vector`, logged once per isolate so the alias has a deletion signal |
| Static build | `pnpm build` | ~seconds (206 pages) | emits HTML/CSS/JS only — assets stay external |
| Tile smoke test — **not the product** | `python3 -m http.server` in `work/planet_tiles` | instant | proves the pyramid renders with zero deps; no starfield/borders/atmosphere by design |
| Worker deploy + first TLS | `npx wrangler deploy` in `web/worker` | deploy seconds; **certificate a few minutes** | Universal SSL covers only the apex + first level, but Workers Custom Domains **auto-generate an Advanced Certificate** for the target hostname and R2/Pages custom domains use Cloudflare-for-SaaS certs — both automatic, no ACM, any depth. So depth changes *when* TLS works, not *whether*. Expect `TLS alert handshake failure` while the cert issues, even though DNS already resolves: `*.zone` is an RFC 4592 wildcard that answers at any depth, so **check the certificate, never `dig`** |
| Site deploy | `pnpm run deploy` in `web` | preflight ~2 s · build ~0.5 s · upload **13 s** | Runs the asset-sync preflight, then builds with the production bases, then uploads. **Never `wrangler deploy` alone** — that ships a same-origin build whose 204 hero pages 404. Re-deploys upload nothing when `dist/` is unchanged ("No updated asset files"). **THE TILE WORKER DEPLOYS FIRST, ALWAYS** — there are two Workers and only this one has a script, so the other is easy to forget. `resolveTileRequest` tries the addressed grammar then falls back to the pre-scheme shapes, which makes the pair safe in exactly ONE order: a new Worker serves an old site, an old Worker serves nothing a new site asks for. Skipping it 404s **every** tile — relief and terrain, not just the layer that changed. Verify against the live host, never against the repo: a Worker's code and a Worker's deployment are different facts, and only a request can tell them apart |
| Deploy preflight | `pnpm run check:deploy-sync` | ~2 s (1,624 objects) | Lists `terrella-assets` and diffs it against the manifest. Advertised-but-absent is fatal (the site would 404); present-but-unreferenced warns, since the usual cause is a manifest not regenerated after a render. Needs `R2_ENDPOINT` in `web/.env` and the `r2` profile; `SKIP_ASSET_SYNC_CHECK=1` overrides |
| R2 upload — the archive | `aws --profile r2 --endpoint-url <r2> s3 cp planet.pmtiles s3://terrella-tiles/` | **~2 min** for the 3.1 GB WebP archive; **10m28s** measured on the 16.06 GB PNG one (≈ 205 Mbps on a 249 Mbps uplink). Mars's three together — 1.401 GB + 0.806 GB + 7 MB — are **90 s** at the same rate | 1,916 × 8 MiB multipart parts. Detach it. Verify by reconstructing the ETag locally, and **the file's size picks which oracle**: at or below the CLI's 8 MiB `multipart_threshold` the ETag is a plain MD5, above it the MD5 of the concatenated 8 MiB part MD5s plus `-N`. Choose by the `-N` suffix rather than by guessing, or a small archive is checked with the wrong oracle and "passes" for the wrong reason — the vector pyramids are the ones that land under the threshold |
| Hero variants — the srcset ladder | `hero_variants.py --jobs 8` | **6 min** (203 heroes × 6 rungs); **~49 min at the default `--jobs 1`**. Adding the portrait fill rung to an otherwise-current store is **4.1 s** (25 written, 1,218 skipped) — an unrecorded rung reads as q85, which equals the new rungs' policy, so nothing existing is retired | One `gdal_translate` peaks at **523 MB**, so the ceiling is cores, not the memory cap — but the default stays 1, as `gen_spotlight`'s does. Quality is a policy (`quality_for`): q85 to 1920, q95 at 3840/native. `hero_variants_recipe.json` records what each rung was written at, so a quality change restages exactly that rung and nothing else |
| Spotlight overlays — small rungs only | `gen_spotlight.py --only <slugs> --jobs 6` | **1m45s** (203 slugs × 3 new rungs). The portrait fill rung is **1.9 s and 615 MB peak for one slug**, so 25 slugs at `--jobs 4` took **10.7 s** | **The "~8 GB per job" in its docstring is a NATIVE-rung figure.** Generating only 640/960/1280 measured **0.49 GB per job**, ~16× lighter, so a high `--jobs` is safe for a small-rung pass and reckless for a full one. Time one slug before choosing |
| Country vector tiles | `compose/countries_pmtiles.py` | **17 s** (258 features, 413k vertices → 10.2 MB, z0–8) | Derives the outline and hit-point layers, stages a GeoPackage, then ONE `ogr2ogr -f PMTiles`. The GPKG exists only because the PMTiles driver cannot append a layer to an archive it already wrote. No tippecanoe and no `pmtiles convert` — GDAL 3.12 writes PMTiles directly, so the tool that once OOM'd the box is not in this path |
| Border layers — all rungs | `gen_borders.py` | **7m21s** (201 countries × 5 rungs, serial; no `--jobs` flag) | Redraws the full-res cairo layer per country and writes every rung from that one surface, so adding a rung costs a full regeneration. ~3 s per country |
| R2 upload — heroes + borders | `aws … s3 sync … --exclude "*.aux.xml" --exclude "*_recipe.json"` | ~2 min (1,622 files, 2.13 GB) | **Both excludes are mandatory** — GDAL PAM sidecars are the bulk of them, and `hero_variants_recipe.json` is pipeline-internal freshness state that must not be published (the deploy preflight caught it as an unreferenced object). 609 of the variants store's 2,231 files are GDAL sidecars. GeoJSON needs `--content-type application/json` or the edge will not compress it |
| PMTiles packaging | `pack_pmtiles.py` → `pmtiles convert` | **WebP q95 pyramid:** dir→MBTiles **10 s** (87,381 tiles, 3.19 GB); convert **5.8 s** → **3.1 GB** `planet.pmtiles`. *(The PNG pyramid it replaced: 33 s and 1m11s → 15 GB.)* | Always run convert **capped and with `--tmpdir` on ext4** — uncapped it stages ~12 GB through tmpfs `/tmp` (= RAM) |
| PMTiles packaging — terrain | `pack_pmtiles.py --body earth --tiles …/bathy_s8_webp/tiles --name terrella-terrain` → `pmtiles convert` | dir→MBTiles **12 s** (87,381 tiles, 2.69 GB); convert **6.1 s** → **2.63 GB** `terrain.pmtiles`. Same shape as the relief pack because the pyramids are the same size | `pack_pmtiles.py` needed no changes for a second *pyramid* — it reads the encoding off the directory, so the arguments are the body, the paths and the archive name. Dedupe is much lower than relief's (86,120 of 87,381 unique = **1.4%**, against ~5%): elevation tiles repeat only where the sea is flat, and the polar feather makes even those differ. **Index is 196,747 B** — under `INDEX_PREFETCH_BYTES` (262,144), which the Worker's test asserts. Verify the same way: `pmtiles show` reads `tile type: webp`, then byte-compare addresses against the tiles on disk (6 checked identical incl. `z8/128/255`, the TMS-flip-sensitive row) |
| PMTiles packaging — terrain, Mars | same with `--body mars --out …/planet_terrain/terrain.mbtiles` | dir→MBTiles **1 s** (21,845 tiles, 0.82 GB); convert **1.5 s** → **0.806 GB** `terrain.pmtiles` | **Dedupe is exactly zero here — 21,845 unique of 21,845** — against Earth's 1.4%, whose repeats are flat ocean. It was 5 tiles before the polar feather went: those were the only identical bodies on a planet with no sea, and they were identical because the feather had flattened them. **Index is 51,473 B**, a quarter of Earth's, well under `INDEX_PREFETCH_BYTES`. The flip-sensitive pair to byte-compare is `z7/64/0` against `z7/64/127` — same column, opposite poles, and each now carries its own relief rather than a shared flat plate |
| R2 upload — the archives | `aws --profile r2 --endpoint-url <r2> s3 cp <archive> s3://terrella-tiles/<key>` | ~2 min per 3 GB archive at ~205 Mbps. Detach it | **A new key per cut, never an overwrite** — the key carries a version the cut bumps, and a warm Worker isolate holds directory byte OFFSETS, and offsets from one cut against another's bytes serve a corrupt tile with a 200. The key lives in `web/src/lib/tileAddress.ts`'s registry, which both the Worker and the site compile; the deploy preflight enumerates that registry and refuses if any object it publishes is absent. When the superseded object may be deleted, and why that is one-way, is `web/DEPLOY.md` § Where the site lives |

## If you only remember one thing

The pipeline is **fast to re-run and slow to build**: a cold shade is ~46 min with the cut, plus a
one-time hour for the lake warp; warm is seconds. Even the tile cut is guarded, so a fully-fresh
`--tiles` re-run is seconds too — the 4:19 cut runs only when `planet_rgb` actually changed.
