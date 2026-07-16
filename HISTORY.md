# Terrella — decision history

Chronological archive of decisions and their rationale, split out of PLAN.md on 2026-07-14 to keep the living plan lean. Newest first. PLAN.md's locked constants and open questions cite entries here for the *why*; append new decisions here, not in PLAN.md.

## Decision log

### 2026-07-16 — the gdaladdo step DELETED: I optimised it 4.5x an hour before proving it does nothing

Read the gdaladdo docs before the cut, found three candidate flags, killed two on measurement, landed the
third at **4.5x** — and then read the `gdal raster tile` docs and discovered **the whole step is inert.**
The 4.5x was a speed-up of a no-op. HISTORY's own 2026-07-15 lesson — *"the morning's entire optimisation
plan was aimed at the fastest stage"* — was read the same day and walked into anyway. **Optimise only after
proving the stage is on the critical path; "it runs every pass" is not that proof.**

**`gdal raster tile` NEVER reads the source's overviews.** It builds each low zoom from the tiles it just
generated — which is precisely why `--resampling` is documented as *"for max zoom"* and
`--overview-resampling` exists separately. Proven by tiling one raster with and without overviews:
**byte-identical manifest over every tile, identical wall time.** GDAL's RasterIO auto-uses overviews for
any downsampled *source* read, so had low zooms come from the source, both bytes and time would have moved.

- **Where the false belief came from — a confounded fix.** The 2026-07-14 note (*"tiling the 194-source VRT
  directly re-reads every block per low-zoom tile — far too slow"*) bundled **two** changes: materialising
  the VRT to a GTiff, and adding overviews. Materialisation was the real fix; the overviews rode along on
  the same commit and were **never tested separately**. Two changes, one measurement, credit to both.
- **Cost of the belief:** ~3 min and ~4 GB appended to the master, every cut, for nothing — plus the
  "`build_tiles` is the only unguarded stage" wart, which **dissolves**: the unguarded stage no longer exists.
- **Two GDAL facts, still true, still worth keeping** (they apply to `fuse_heightfield`'s `build_overviews`,
  which is real). Recorded *because* they are dead ends — each is plausible enough to be re-proposed:
  **`COMPRESS_OVERVIEW`** is a no-op (internal overviews already inherit the main image's DEFLATE — the docs
  say it is "honoured" since 3.6 but never state the default, which is why it needed checking), and
  **`GDAL_TIFF_OVR_BLOCKSIZE`** is a no-op (they already build at 512, inherited; the documented default of
  128 never applies).

**Two more landed from the same doc read, both proven byte-safe on a tile-ALIGNED rig** (col/row multiples
of 512, matching `planet_rgb`'s `-tap` alignment — the first probe used col 60,000, off-grid, which would
have forced resampling production never does):

- **`--webviewer=none`.** The default is `all`. The live pyramid has been carrying `leaflet.html`,
  `openlayers.html`, `mapml.mapml` and `stacta.json` since 07-14 — dead weight we never serve, and they
  would have ridden into PMTiles. Tiles byte-identical; only the four files disappear.
- **`--overview-resampling=cubic` — a PIN, not a change.** Identified by elimination: unset, it silently
  inherits `--resampling`, so **z0-7 have always been cubic**. `average` was proposed and **rejected on
  test — it is NOT the default and changes z0-7 pixels**; cubic is what built the verified 07-14 pyramid,
  and there is no evidence against it. Pinned so most of the globe's zoomed-out surface stops depending on
  an undocumented default. (Full elimination table: only `cubic` reproduced the default's bytes; `q1`
  degenerates to `min` at these block sizes.)
- **Hazard, docs-derived and NOT measured:** `--resume` "generates only missing files" with **no
  verification**, so a tile left truncated by a kill is skipped rather than repaired. Not hypothetical —
  the 07-15 cut was OOM-interrupted and resumed. Worth a verify pass before trusting a resumed pyramid.

### 2026-07-16 — optimisation #3 landed: `NUM_THREADS` on the GTiff writers (10x), and the "three for three" record explained

`-co NUM_THREADS` had been measured and **rejected three times** here (`-multi`, `-wm`/`-wo NUM_THREADS`,
and `-co NUM_THREADS` for color-relief — see § the profile that killed three flags). PLAN then proposed a
fourth instance on the strength of one number, *libdeflate = 9.93% of python-side CPU*, which lived
nowhere but PLAN and had **no surviving perf artifact**. So it was measured rather than trusted, on real
data (`pipeline/experiments/writer_threads.py`).

**Result: 8.79 s → 0.88 s, a 10.0x speedup on the writer**, with output **byte-identical** (same MD5, with
an LZW control proving the comparison can fail).

**Why this is not a contradiction of the three rejections — the reason matters more than the result.**
Every earlier rejection was Amdahl's law, not a broken flag: for color-relief, libdeflate was **4.33%** of
a stage dominated by libgdal's **19.37%** interpolation, so threading DEFLATE could touch ~18% of it at
best. A *pure writer* has no interpolation — it is essentially all DEFLATE — so the same flag addresses
~100% of the stage. **The flag was never useless; it was pointed at stages that were not compression-bound.**
The rejections and this acceptance are the same finding read at two different call sites.

- **Three writers, not the two PLAN named.** `shade.py`'s region writer is the composite writer's sibling,
  and the "one implementation, both shade paths" rule (§ optimisation #2 landed) exists precisely because
  the float32 fix reached `composite` and never reached `hillshade`. Taking only PLAN's two would have been
  the **fifth** instance of that bug. Applied to `shade_planet.py` (composite), `hillshade.py`, `shade.py`.
- **Two of the remaining writers must STAY unflagged — and that is a hard constraint on `GTIFF_CREATE`.**
  `fuse_heightfield.py:212` and `build_void_wbm.py:116` run under `fuse_planet.py`'s `FUSE_ENV`, which sets
  **`GDAL_NUM_THREADS=1` deliberately**: *"parallelism is across cells, not within a warp"*, with
  `--workers W` cells in flight at a budgeted ~1.5 GB each. An **explicit creation option overrides that
  config**, so flagging them would oversubscribe W x 16 threads against a sized RAM envelope. A shared
  `GTIFF_CREATE` that carried `num_threads` everywhere would therefore silently break fusion's design —
  **the constant must carry the FORMAT options; threading is per-call-site policy.** `render_prep.py:117`
  (hero path) is merely unpaid, not unsafe.
- **Verified in the pass's own environment, not just a clean one.** The first benchmark ran without
  `GDAL_CACHEMAX=512`, which `run_pass.sh` sets and which changes block-cache flush timing — the exact
  shape of this project's seven proxy bugs (the check diverging from the real thing). Re-run under it:
  **10.10x**, unchanged. The tile pass sets no `GDAL_NUM_THREADS`, so the creation option governs there.
- **No rebuild forced.** `composite_params()` serialises KNOBS + palette, never creation options, and
  `hs_params.json` is only `{alt, az, exag}` — verified: params byte-identical, `planet_rgb` still fresh,
  **with a control that fires** (a just-edited source as a dep returns True). The first control tried was
  itself blind — `is_stale` reads `newest_mtime`, which ignores a path that does not exist, so a missing
  dependency can never mark anything stale. The blind-oracle bug (§ 2026-07-06), caught in its own control.
- **Extrapolated saving: ~6 min of the composite's 53.8**, and that is an **upper bound** — the benchmark
  band compresses 2.0x against the planet's 3.0x average, and flatter data deflates faster. The hillshade's
  share is unmeasured; the 3-band RGB number does not transfer to a 1-band raster. **Pays only on the next
  pass**, which is why it is worth exactly one line each and no more.

### 2026-07-16 — `composite_ram.py` was never the number PLAN said it was

PLAN carried *"`composite_ram.py`'s 6.93 GiB is STALE — re-run the fixture so it stops disagreeing with
reality."* Re-running it moves it **further** from the real pass, not closer, because the premise was wrong:
**6.93 GiB was never the fixture's output.** It was the *pipeline* peak measured on 2026-07-15 with the
fixture's help (§ GLOBathy lake depth), and the fixture was rewritten for the post-LUT signature in the same
commit that landed it — so nobody had re-run it since its inputs changed.

Measured today, capped, both arms in separate processes: **3.88 GiB without depth, 4.50 GiB with** — the
depth branch costs **+0.62 GiB** (the 07-15 pipeline-scope figure was +0.48).

**The fixture and the pass measure different things, and always did.** `composite_ram.py` measures
`composite()` *in isolation*; it opens no dataset. The real pass adds five readers, the writers, the GDAL
block cache (`GDAL_CACHEMAX=512`) and runtime overhead — so the fixture is a **lower bound on the pass**,
by ~1.7 GiB, and no amount of re-running will reconcile 4.50 with 6.24. That is not a defect: the docstring
says exactly what it measures. The defect was PLAN conflating two scopes into one number.

**Nothing needs resizing.** The real pass peaks at **6.24 GiB** (§ optimisation #2 landed) against the 12 G
cap = **1.9x**, and composite is once again the peak stage now that the hillshade fix took it 11.6 → 2.03 GB.
`watchdog.py`'s `ANON_WARN_MB = 10_000` sits correctly between the two. Only the quoted numbers were stale.

### 2026-07-16 — the composite parallelises with THREADS, and the xarray/dask question is settled by that

Asked whether the pipeline should move to the xarray/dask ecosystem. Answered by measurement rather than
by argument, because the first answer given was argued from memory and three of its four reasons did not
survive checking (below).

**The measurement.** `shade.composite` — the production function, imported, not retyped — over real
windows read off the real `height/ocean/water/hs/lakedepth_3857` rasters, 8 windows × 32 rows × 131072,
under the usual 12 G scope. (Honest caveat: `snow_a` is zeros and `occ` synthetic; both are
elementwise/interpolation ops whose *cost* is value-independent, so this times the same work. The
bandwidth-driving arrays are real.)

| threads | wall | cpu | cores | speedup | efficiency |
|---|---|---|---|---|---|
| 1 | 3.84 s | 3.83 s | 1.00 | 1.00× | 100% |
| 2 | 2.14 s | 4.05 s | 1.90 | 1.80× | 90% |
| 4 | 1.36 s | 4.80 s | 3.54 | **2.83×** | 71% |
| 8 | 1.08 s | 6.97 s | 6.48 | 3.57× | 45% |

- **numpy releases the GIL, so plain threads work.** 4 threads genuinely occupy 3.54 cores. This kills the
  `ProcessPoolExecutor` design drafted the same morning — it existed to dodge a GIL that does not bind,
  and would have paid ~36 GB of pickling across 1456 windows to do it. Threads need no IPC, no fork-safe
  handle juggling, and no serialisation. **~10 lines around the existing loop.**
- **Memory bandwidth is the real ceiling, not the GIL and not the scheduler.** Efficiency decays 90%→45%
  between 2 and 8 threads; CPU time inflates 3.83→6.97 s for the same work. **~3× is the ceiling and 4 is
  the knee.** No framework changes this — it is a property of streaming 100 MB float32 arrays.
- **Therefore the xarray/dask case collapses on its own merits, not on taste.** Dask's headline benefit
  here is parallel scheduling, and its threaded scheduler would reach the same ~3× by the same mechanism
  (threads + GIL-releasing ufuncs) that a `ThreadPoolExecutor` reaches for free. Two supporting facts,
  both verified rather than recalled: **rioxarray does not replace rasterio** — it is "a geospatial xarray
  extension *powered by rasterio*" (PyPI, 0.22.0), so adopting it *adds* a layer; and **xarray-spatial
  cannot do our hillshade at all** — `hillshade(agg, azimuth, angle_altitude, name, shadows, boundary)`
  has **no z-factor parameter**, which is the entire reason `render/hillshade.py` exists.
- **What dask would genuinely buy, recorded honestly so this can be reopened:** `map_overlap` expresses
  the 1-row halo we hand-rolled; named dims/coords make the per-row latitude z a natural broadcast
  instead of a `.reshape(-1, 1)`; chunk management would retire the manual `del` + `gc.collect()`. All
  real, none worth a migration of code that was verified bit-for-bit this week — and none of it is
  parallelism, which was the thing we wanted.
- **The retracted argument, kept as the lesson.** The first answer gave four reasons to reject dask. Only
  one survived: CLAUDE.md's "prefer boring, debuggable scripts over frameworks" (a real, quotable
  convention). "Zero RAM headroom" was false (`free`: 20 GB available). "OOM-killed twice this week" was
  false (`journalctl -k`: exactly one, 2026-07-15 22:17). "Dask replaces a measured number with a
  scheduler that decides for you" was wrong — dask chunks are explicit. And "dask graphs are harder to
  debug" was judgment presented as finding. **Four reasons felt more rigorous than one; three were
  decoration.** Same disease as the proxy bugs, one level up: the check felt thorough because there were
  several of them. → § 2026-07-16 — the instrumented planet pass

### 2026-07-16 — optimisation #2 landed: `gdaldem color-relief` DELETED; the ramps became a 17.6 KB LUT

`composite()` now takes ELEVATION and applies the land/sea ramps itself via `palette.relief_lut`.
Both `gdaldem color-relief` passes are gone from both shade paths.

**Why a flag could never have fixed it.** color-relief was **28:19 and 24.4% of all pass CPU**,
single-threaded, each pass reading the full 31 GB height raster to write 1 GB. The profile split it
**`libgdal` 19.37% (interpolation) vs `libdeflate` 4.33%** — so `-co NUM_THREADS`, which threads only
DEFLATE, could reach ~18% of it at best. That 19.37% is a per-pixel **binary search** over the 241 rows
`color_relief_rows(step=25)` emits. gdaldem searches because its file format permits arbitrary stop
positions. **Ours are uniform** (0..6000 every 25 m), so the bracketing index is just `elevation/step` —
a divide, not a search. gdaldem cannot know that; numpy can. The LUT is **17.6 KB** at 1 m resolution,
i.e. *finer* than the 25 m rows gdaldem interpolated across.

**Measured, end to end (planet, 12.19 G px):**

| | before | after |
|---|---|---|
| color-relief | 28.3 min | **0 — deleted** |
| composite | 44.3 min | 53.8 min (+9.5: it now reads the 31 GB height, not 1.6 GB of RGB) |
| **the pair** | **72.6 min** | **53.8 min — net −18.8 min** |
| composite peak RSS | 6.93 GiB | **6.24 GiB** (one Float32 window replaces two RGB windows) |
| whole pass | ~98 min | **~72 min (−26%)** with the hillshade fix |

**Correctness, twice, against independent pre-existing oracles:**
1. LUT vs `gdaldem`'s own `land_3857`/`sea_3857` (written before the LUT existed): **6/6 bands, 100%
   coverage, 96.7% identical, 3.3% at exactly 1 DN, ZERO beyond.**
2. LUT-fed `planet_rgb` vs the gdaldem-fed mosaic: **3/3 bands, 100% coverage, ~92% identical, ~7.5%
   at 1 DN, ~0.35% at 2 DN, ZERO beyond.** The tolerance of 2 was **pre-registered with its reasoning**
   (1 DN input x composite's max gain, saturation 1.18 x hi 1.30 = 1.53) — and the distribution landed
   exactly there. A bar set before the run is a prediction; set after, it is a rationalisation.

- **The trap this opened, and closed.** `LAND_STOPS`/`SEA_STOPS` were tracked *only* by
  `ramp_{land,sea}.txt`, whose sole purpose was gating the gdaldem stages. Deleting color-relief without
  moving them into `composite_params()` would have left `planet_rgb` **falsely fresh** after any ramp
  re-tune — silently rendering the planet with the old palette, the exact failure the guard exists for.
  Three new tests pin it (land stops, sea stops, `LUT_STEP_M`).
- **The ramps are applied INSIDE `composite()`, not in each caller** — deliberately. A per-call-site copy
  of a shared decision is precisely how the float32 fix reached `composite` and never reached
  `hillshade` (11.6 GB). One implementation, both shade paths.
- **Follow-up:** `composite_ram.py`'s 6.93 GiB is now stale (its inputs changed). The real pass measures
  **6.24 GiB**, so the 12 G cap is ~1.9x — sound, but re-derive from the real number, not the fixture.

### 2026-07-16 — optimisation #1 landed: hillshade float32 + 256-row windows (1.84x faster, 5.7x less RAM)

Carried `composite()`'s 2026-07-14 fix to its sibling, `per_row_zfactor_hillshade`, which had never
received it. Measured on the real planet (12.19 Gpx), not a fixture:

| | before (float64 @ 1024) | after (float32 @ 256) |
|---|---|---|
| wall | 932 s (15:32) | **508 s (8:28)** — **1.84x** |
| peak RSS | 11.6 GB | **2.03 GB** — **5.7x** |
| cgroup reclaims | 122,501 | — |

**Correctness, full-raster against an independent pre-existing oracle** (`hs_3857.tif`, written by the
OLD code during the previous night's pass, before this change was designed): **99.9374% of 12.19 billion
pixels bit-identical, 0.0626% differ by exactly 1 DN, ZERO beyond 1 DN.** Worst pixel: 1 DN at lon
-179.408 / lat 85.051 — inside the polar band that gets capped flat regardless.

- **The speed-up was not the goal and is the interesting part.** The change was made for RAM; float32
  halved the bytes crossing cache/RAM and removed 122k reclaims, and the stage got ~2x faster for free.
  It is still 97% CPU on one core — numpy is not threaded here — so the win is pure memory traffic.
- **The float64 was always dead weight:** the function emits **uint8**. Tests show float32 tracks float64
  to <=1 DN, so every one of those extra bytes was discarded on the last line.
- **The trap that TDD caught, and that a colour test never would have.** `zfactor` is built from
  `np.cos(latitude)` -> float64; under NEP 50 `float32 array * float64 array` -> **float64**, which
  silently restores every byte the change saves *while all output assertions still pass*. Fixed inside
  `hillshade_array` (`np.asarray(zfactor, dtype=heights.dtype)`) rather than at the call site, so no
  future caller can reintroduce it. Latitude stays float64 upstream — `merc_y ~2e7` needs the mantissa.
  `tests/test_hillshade.py` (9 tests, suite 120 -> 129) pins dtype, <=1 DN equivalence, and window
  invariance at 256/97/1024/4096 — the last being what makes changing `window_rows` safe at all.
- **My own proxy bug, the seventh, caught by the oracle in one shot.** The first benchmark ran
  `altitude=46.0`, typed from CLAUDE.md's *locked constants* — but those are the **Blender hero** sun
  altitude; the tile path uses `KNOBS["alt"] = 45.0`. Result: 10.3 billion px "differing", **mode at
  3 DN**. 255·sin(46°) − 255·sin(45°) = **3.1 DN** — the offset was the entire histogram. Diagnosed
  instantly by the *shape*: precision noise centres on 0, a systematic offset does not. **A sampled
  check, or one reporting only a mean, would have read as "small float32 rounding" and shipped.**
  Distribution over aggregate; and the re-run does `from pipeline.tile.shade_planet import EXAG, ALT, AZ`
  — imported, not retyped, because a benchmark that retypes a constant measures a different program.
- **A real divergence, flagged not fixed:** heroes use sun altitude **46°**, tiles **45°**. Same species
  as the known hero/tile sea-ramp divergence — visually nil (3 DN on flat ground), but a second instance
  of the two render families drifting. Fold into the deferred hero sea-sync, do not touch alone.
- **The guard is blind to code changes, by design, and that was right here.** `hs_params.json` records
  `{exag, alt, az}` — *source-level params*, not code — so this pure-performance change left
  `hs_3857.tif` fresh and did NOT trigger a 31 GB rebuild. Correct, because equivalence was *proven*.
  But note the general gap: had the change altered the algorithm's output, the guard would not have
  noticed. It is the deliberate trade for not having `git checkout` force a full-planet rebuild
  (`write_if_changed`, 2026-07-15) — so any *behavioural* change to a shading kernel must be verified
  against an oracle by hand, exactly as this one was.

### 2026-07-16 — the instrumented planet pass: the baseline, and why every warp optimisation we planned was worthless

The GLOBathy + Caspian + `WATER_RGB` pass, run once under full instrumentation (`perf record -F 49 -g`
wrapping the whole job so it inherits into every forked child; a 0.5 s cgroup sampler for RSS/threads/
disk; the pass's own stage prints timestamped; the cgroup's own `memory.peak`). **98 min wall, exit 0,
`planet_rgb.tif` 11.96 GB, 349,384 perf samples in 65 MB.** Shade only — tiling deliberately gated on
looking at the mosaic first.

**Mosaic verified** against a *pre-registered* known-bad (what it would read if depth never reached the
pixels: all lakes identical at `(141,197,195)`):
Baikal `(81,137,149)` lum 121.6 over 959,498 px · Namtso `(100,155,164)` lum 139.6 over 28,092 px —
**18.0 lum apart** where yesterday they were the same pixel. Tanganyika `(81,136,149)` lands on Baikal,
as absolute (not per-lake) calibration requires. Caspian: 2,372,060 class-1 px, spread **0.0 → 30.8**.
Its planet numbers (137.1/158.9/167.8) match the region render's (137.0/158.8/167.8) to a decimal — an
unplanned cross-validation that the two shade paths agree.

**The stage timeline — the whole point, since none of this had ever been measured:**

| stage | wall | CPU | threads | note |
|---|---|---|---|---|
| height warp (31 GB out) | **5:07** | **486%** | 17 | already parallel |
| ocean + water warps | 2:32 | 110% | 17 | |
| **color-relief (land)** | **12:31** | 98% | **1** | reads 31 GB → writes 1 GB |
| **color-relief (sea)** | **15:48** | 98% | **1** | reads 31 GB again |
| **per-row-z hillshade** | **15:32** | — | — | **anon peaks 11.6 GB** |
| global SVF | 2:29 | — | — | free |
| composite (364 windows) | 44:20 | — | — | 2.7 GB, comfortable |

CPU attribution (6,830 CPU-s total): python 43.5% · gdalwarp 23.0% (height) · gdaldem sea 13.6% ·
gdaldem land 10.8% · **gdal_rasterize ×363 4.0%** · **gdalwarp ×363 3.8%**.

- **The morning's entire optimisation plan was aimed at the fastest stage.** The 31 GB height warp runs
  at **486% CPU / 17 threads in 5 minutes**. `-wo NUM_THREADS=ALL_CPUS` + `-wm` would have optimised a
  warp that is *already ~5× parallel* — and we'd have credited the flags with any noise. The correction
  recorded on 2026-07-15 (that the lake warp's profile does not transfer) was right, and the reason is
  now visible: **the expensive warp was the small one.** 310 MB in 62 min (masker-bound) vs 31 GB in 5.
- **`-co NUM_THREADS` is NOT the fix for color-relief either — the third "obvious flag" to die.**
  Measured split of gdaldem's 24.4% of all CPU: **`libgdal.so` 19.37% (the interpolation) vs
  `libdeflate.so` 4.33% (compression)**, `libz` 0.01%. So the flag that threads only DEFLATE addresses
  **~18%** of the stage; best case ~5 min of 28. Symbol addresses cluster tight
  (`0x1a99c8b`–`0x1a99ca8`) = one hot loop in a stripped libgdal. Flag drift *looked* like the
  explanation (the height warp has the flag, color-relief doesn't); the profile says otherwise.
  Three for three: `-multi`, `-wm`/`-wo NUM_THREADS`, `-co NUM_THREADS`.
- **The box averaged 1.16 of 16 cores** across 98 min wall / 114 min CPU. The pipeline is ~93% idle
  silicon, and it is not I/O-bound (the height warp: 126 MB/s write vs 6 MB/s read, 720 MB RSS).
- **The 12 G cap was sized from the wrong stage.** PLAN called it "1.7× measured" from `composite()`'s
  6.93 GiB. Measured here, the **hillshade** peaks at **11.6 GB** — the cap is **1.03×**, and the cgroup
  logged **122,501 reclaim events** grinding to keep it under. It survived (`oom_kill 0`), but the
  hillshade's 15:32 is a *thrashing* number, not a clean one. The composite measurement was never wrong;
  it was the wrong stage. Same disease as the day's proxy bugs, one level up.
- **Instrumentation notes for next time.** `perf record -- cmd` inherits across fork+exec, so one file
  covers gdalwarp/gdaldem/gdal_rasterize/numpy, filterable with `--comms`; use `-g none` for a flat
  report or the call graphs swamp it; libgdal is stripped, so read the *dso* split
  (libgdal-vs-libdeflate) rather than hunting symbols. Sample by **cgroup**, never `pgrep -f` (which
  matched the `/usr/bin/time` wrapper on 2026-07-15 and, twice on 2026-07-16, matched the very shell
  issuing the `pkill`). Attribute per **PID**, never comm+time-window: differencing across two
  same-named processes produced **−0.1% CPU**, an impossible number that was caught only because it was
  impossible on its face.

### 2026-07-15 — GLOBathy lake depth: a render layer, not a fusion channel; and what the cone is actually worth

Reopens the 2026-07-07 "Lake depth: flat stays" decision, whose stated bar was *"real modeled data —
GLOBathy or better"*. Acquired, wired, validated on renders, **approved by Rohan on the Tibet + Baikal
A/B**. The full pass is not yet run.

- **Architecture reversed: a render layer beside snow, NOT the re-fuse PLAN.md:67 specified.** The
  deciding constraint was already on the books and PLAN.md had simply not restated it — *"tint-only,
  never carve displacement (at 15× Namtso becomes a 1.5 km crater and the shadow-catching plate dies)"*.
  If depth never enters the heightfield, the fusion master is not its home: it is a **rendering** input,
  exactly like snow, which is warped at composite time and has never touched fusion. Three consequences,
  all good: **no re-fuse**; **no HydroLAKES join** (it existed only to place basins vertically, and
  nothing is placed) → **the layer stays CC0 with no attribution obligation**; and a future z10 re-fuse
  would not redo it, since depth is not in the master. `HISTORY.md:1110` had recorded this fork as open
  ("post-tint stage vs fusion depth channel"); this closes it.
- **The epistemics, measured — and my first "validation" was circular.** I checked `Dmax_use_m` against
  published depths for Baikal/Erie/Superior/Tanganyika/Ladoga/Titicaca, got exact matches, and called
  the calibration verified. All six sit in the **0.10% of lakes (1,487) that carry a surveyed depth**,
  where GLOBathy *uses the published number verbatim* — I was comparing a value to itself. The real
  split: of our 83,357 rendered lakes, **647 (0.78%) surveyed, 82,710 (99.22%) random-forest estimate**
  — though **14 of the 15 deepest are surveyed**, so the visual weight lands on real numbers.
- **The cone is right in scale, wrong in shape (the Caspian is the only place it can be falsified).**
  `experiments/globathy_vs_gebco.py`: deepest point within **68 km** on a 1,200 km lake and max depth
  within 1.6 m (1023.6 vs 1022.0) — my prediction that it would *invert* the Caspian was wrong. But
  correlation is only **0.534**, median |error| **191 m**, and where the truth is under 20 m the cone
  claims **155 m** — it renders the famously ~5 m north shelf as a 236 m basin, because it cannot know
  about shelves or sills. This **empirically settles** keeping the Caspian on GEBCO.
- **GEBCO is not a usable oracle for lakes.** Erie's true max is 64 m; GEBCO says **225** (its "deepest
  point" lands near Buffalo, at the Niagara outflow). Superior's is 406; GEBCO says **469**. GLOBathy's
  `Dmax` beats GEBCO on both. So two of the three checks were void — you cannot falsify a model against
  a broken measurement — and only the Caspian (sea-like, properly surveyed) is a genuine test.
- **Surveyed-only was tested and rejected.** Restricting depth to the 647 surveyed lakes was tempting
  (they carry **55.7% of all lake pixels**) but **84.7% of every surveyed lake on Earth is in the USA**:
  Canada has 41,793 lakes worth drawing and 58 real depths. It would render **survey funding as geology**,
  with the discontinuity landing on the US/Canada border, through the Great Lakes. Worse than either
  uniform option, and it fixes the *scale* axis while leaving the *shape* — which was the actual
  objection — untouched. Uniform modelled treatment is the deliberate choice; caveat it on the About page.
- **The ramp: log1p, decided by measurement not taste.** The median lake is **11.2 m** and Baikal is
  1642 — three orders of magnitude. Linear parks the median lake at **0.7%** of the ramp (invisible);
  sqrt at 8.3%. Across 457,722 real lake px in Tibet the p10–p90 spread is **log1p 0.38 vs sqrt 0.14** —
  sqrt is a no-op dressed as caution. Caveat worth keeping: log1p hands most of the ramp to shallow
  water, which is exactly where the cone is least trustworthy. `LAKE_STOPS[0]` is **derived from**
  `WATER_RGB` rather than copied, so the shore tint cannot drift from the flat tint the way WATER_RGB
  itself drifted from the sea.
- **What the flat fill was costing, in one number:** today Baikal (1642 m) and Namtso (125 m) render
  **the identical pixel colour, (141,197,195)** — 13× the depth, zero difference. With depth: (75,131,145)
  vs (97,152,162). Coverage is fine: GLOBathy reaches 71% of WBM lake px in Tibet / 99% at Baikal, and of
  the shortfall ~31% is whole ponds with a **median size of 2 px** (no gradient possible at any threshold,
  so lowering `MIN_BYTES` buys nothing) while ~69% is rim inside graded lakes — the HydroLAKES↔WBM
  shoreline mismatch — invisible because the ramp starts at `WATER_RGB` and reads as a shelf.
  **528 bodies carry 91% of all lake pixels**, which is why a threshold that keeps 83,357 of 1.43 M
  rasters loses nothing visible.
- **RAM measured (`experiments/composite_ram.py` + a timed region render), and the cap was already wrong.**
  Real pipeline peak: **6.45 GiB without depth, 6.93 GiB with** — the depth branch costs **+0.48 GiB**,
  not the ~1 GB I predicted by summing temporaries (numpy frees as it goes; the peak is not the sum).
  The finding is that **today's code already peaked at 6.45 GiB against the 8 GB cap** — 19% headroom
  *before* this change. That 8 GB was never sized against anything; it was picked reactively after the
  morning's OOM, when the box had ~10 GB free because 12 GB was trapped in tmpfs. **Cap raised to 12 GB**:
  1.7× the measured peak, still half the 24 GB now available, so it still kills the job and not the box.
- **The one-shot 83k-source warp, profiled (`perf`, paranoid lowered to 1). Verdict: viable, ~50 min,
  and every one of my three bottleneck hypotheses was wrong.** The warp source is the **VRT** (gdalwarp
  sees `lakedepth.vrt [1/1]`, one logical dataset); the VRT fans out internally, holding ~450 of the
  83,356 TIFFs open at a time. Where the CPU actually goes:
  `GDALWarpNoDataMasker` **51.3%**, `GDALCopyWords64` 7.2%, `VRTComplexSource::RasterIO` **2.4%**.
  - **So the bottleneck is `-srcnodata` masking, not the sources and not the resampling.** The masker
    walks every source pixel testing it against -9999 on a raster that is ~98% nodata. The VRT read path
    is 2.4%, so the many-source VRT is a **non-issue** — the "materialise before touching a many-source
    VRT" learning applies to the *tiler* (which re-reads per tile), not a one-shot warp that touches each
    source once. **No fallback pre-mosaic needed.**
  - **Dead ends this killed:** all 83,356 sources are LZW + **STRIPED, never tiled** (GDAL's ~8 KB default
    → Baikal gets 1-row strips of 88 KiB, an apparent 88× read amplification for a 256² window). Looks
    damning, measures at 2.4%: chunking evidently spans each source's width, so each strip decodes about
    once. **Re-tiling 83 k files would have bought nothing** — a fix I was about to propose.
  - **Docs correction that matters (`gdalwarp` page):** `-multi` is *"Two threads... **Note that
    computation is not multithreaded itself**"* — it overlaps I/O with compute and would have bought ~0
    here. **`-wo NUM_THREADS=ALL_CPUS`** is the option that parallelises computation, and **`-wm`** (never
    set by us, docs: *"shared among all threads... especially beneficial when running with `-wo
    NUM_THREADS` greater than 1"*) sizes the chunks. `-co NUM_THREADS` is a **GTiff creation option** for
    *"multi-threaded compression"* only — which is exactly the observed 17 threads / 16 idle: DEFLATE
    workers starved by a single warp thread at 99%.
  - **Untested lead, worth a look before optimising blindly:** `-srcnodata -9999` merely restates the
    nodata the VRT already declares. If the sources carried **0** as their fill instead, no masking would
    be needed at all — and bilinear blending toward 0 at a lake edge is *physically correct*, since depth
    really does go to 0 at the shore. That could delete ~half the warp's CPU, but it is a source rewrite.
  - **Cost is spatially non-uniform, which broke my estimate:** 10% at 2:25 and 20% at 3:32 (the polar
    band above ~78N is empty of lakes) → I projected ~20 min; it hit the 50-70N lake belt (Canada,
    Scandinavia, Siberia) and collapsed ~7x, landing near **50 min**. Output ~400 MB for 12.19 Gpx.
  - **The real prize is elsewhere:** the same serial path, no `-wm` and no `-wo NUM_THREADS`, applies to
    the **31 GB height warp**, which re-runs on *every* re-fuse — whereas this lake warp is a
    freshness-guarded one-shot. `ocean`/`water` already use GDAL's documented fast path (`-r near
    -ot Byte`, no nodata) and have nothing to win.
  - **CORRECTION, same day — this profile does NOT transfer to the height warp, so the "prize" above is
    unfounded.** Checked rather than assumed, on both counts that produced it:
    (a) **The 51% masker cannot even run there.** `GDALWarpNoDataMasker` is driven by nodata;
    `planet_heightfield.vrt` declares **zero** `NoDataValue` entries and the height warp passes no
    `-srcnodata`. Half the measured cost is absent from the height warp *by construction*.
    (b) **The "17 threads, 16 idle" is an artifact of output size.** That was `-co NUM_THREADS`' DEFLATE
    pool with nothing to compress — the lake warp writes **310 MB**. The height warp writes **31 GB**, 100×
    more, so the already-set `-co NUM_THREADS=ALL_CPUS` has real work and the write side may already be
    parallel.
    The height warp's bottleneck is therefore **unknown**, not "the same". Generalising one warp's profile
    to another warp is the same error as the day's other five — reasoning from an unrepresentative sample.
    **We also have no baseline wall-clock for it at all**, which is the decisive practical point: changing
    its flags before measuring it once would destroy the only free chance to learn whether they helped.
  - **Method note:** the first three profiling samples were of `/usr/bin/time`, not gdalwarp — `pgrep -f`
    matched the wrapper's command line — and reported "Threads: 1, zero source opens, zero reads" while
    progress advanced. Impossible on its face, and it *fit my pool-churn hypothesis*, so I built on it
    instead of questioning it. Four predictions were wrong today (+1 GB RAM → +0.48; the cone would
    invert the Caspian → 68 km; ~20 min → ~50; VRT/striping is the bottleneck → 2.4%). Measure.
  - **Landed: `1:01:38` wall, peak RSS `2.18 GB`, 310 MB output, exit 0** (102% CPU — the single warp
    thread plus DEFLATE workers). Grid is byte-identical to what `warp_inputs` generates (`-te`/`-ts`
    both derive from `height_3857.tif`), so the hand-run artifact was stamped `.done` rather than
    re-warped. **RSS is the quiet headline: 2.18 GB.** The warp is nowhere near the RAM cliff, so `-wm`
    (which sizes warp chunks and is currently unset → GDAL's 64 MB default) has plenty of room to grow
    alongside `-wo NUM_THREADS`. That pairing is the untested prize on the 31 GB height warp.
- **The calibration oracle, run on the WARPED planet raster — the check the 2026-07-07 prototype lacked
  and was rejected for.** Max depth within each lake vs its published survey: Baikal 1638.3/1642 (0.998),
  Tanganyika 1464.7/1470 (0.996), Ladoga 229.7/230 (0.999), Titicaca 279.1/281 (0.993), Superior
  405.5/406 (0.999), Namtso 123.9/125 (0.991). All within 1%. This proves *two* things at once: GLOBathy's
  cone is calibrated to real surveys where they exist, **and** the 3857 warp preserved it — no shift, no
  rescale, no nodata clobber. (The ~0.5% shortfall is expected: the cone's apex rarely lands exactly on a
  306 m pixel centre.)
  - **My first oracle was broken, and it cried wolf on the Caspian.** It took the **max over a lat/lon
    bounding box**, which for the Caspian catches every Iranian, Turkmen and lower-Volga lake in the
    rectangle — it reported a 92 m "leak" whose argmax sits at 49.88E/40.45N, *on land near Baku*. Point
    samples on open Caspian water (deep S basin, mid S basin, middle basin, N shelf ×2) all read exactly
    **0.0**. The lesson is the recurring one: a rectangle is not a lake, and an oracle that can't tell the
    difference will fail on the one body you most need it to be right about.
- **The freshness guard fired on the real thing, first time out.** The entire `planet_tiles/` derived chain
  dates from **2026-07-14 10:38–11:24**, while the planet VRTs were rebuilt **2026-07-15 16:08** after the
  Caspian re-fuse → `height`/`ocean`/`water` all correctly report `stale=True`, `lakedepth` `False`. Made
  concrete: **`water_3857.tif` today reads watermask class `2` at the Caspian deep basin**, not the `1` the
  re-fuse wrote — i.e. without the guard, a re-run would have shaded the Caspian from the pre-re-fuse mask
  and the flat-slab bug would have survived the fix silently. This is exactly the trap the guard was built
  for on 2026-07-15, and it is why no manual `rm` list is needed before the pass.
  - **The two shade paths have opposite staleness exposure, which is worth keeping straight.** The
    **region** path (`shade.py --cells`) is immune: `reproject_cell` warps from `CHUNKS/<name>/` with
    `-overwrite` on every run, so it always sees the current chunks — that is *why* it has no skip-if-present
    and the deferred "region idempotency" item is not costing correctness. The **planet** path caches into
    `planet_tiles/` and is exposed by design, which is what the guard exists to cover. Practical consequence:
    a Caspian regression check is valid via the region path today, and only valid via the planet path *after*
    the mask re-warp.
- **Item 6 — the Caspian regression, proven at the render level (`e040_n30`/`e050_n30`, 7281×4456).**
  Measured over the 2,372,061 class-1 Caspian px: routing is 100% class 1 → sea ramp; **0 px** of lake
  depth reach `composite()`; and the structure result is the one worth keeping — luminance p10/p50/p90 was
  **182.9 / 182.9 / 182.9 before (spread 0.0 across 2.37 M pixels — a *literal* flat slab)** and is now
  **137.0 / 158.8 / 167.8 (spread 30.8)**. The `before` is the same geographic pixels in `planet_rgb_v1.tif`,
  proven pixel-comparable rather than assumed: exact integer lattice offset (80100, 49621 px) and land
  correlating **0.9972** (mean |Δ| 2.7 lum = the region path's *regional* SVF normalisation vs the planet's
  *global* one — a real difference to remember when reading any region render as a proxy for the planet).
  The PLAN's prediction held exactly: the win is **structure, not darkness** — the Caspian stays legitimately
  bright (p50 158.8, median depth only ~48 m); a flat slab became a shaded basin.
  - **Why it was runnable before the pass at all:** the two shade paths differ in what they read. `shade.py`'s
    `reproject_cell` warps from `CHUNKS/<name>/` with `-overwrite` every run → always current. The planet path
    caches into `planet_tiles/`, whose `water_3857.tif` still reads **class 2** at the deep basin, so a planet
    re-shade today would have tested the old bug and "confirmed" a failure that no longer exists.
  - **The region path is NOT windowed** — it composites the whole region at once, so cell count is a direct RAM
    multiplier. I widened the scope to 4 cells (70 Mpx = 2.1× the planet's 33.6 Mpx window) → **~14.5 GiB →
    OOM-killed at the 12 G cap** (`constraint=CONSTRAINT_MEMCG`: the cap killed the job, not the box, which is
    exactly what raising 8 G → 12 G was for). The morning's 6.93 GiB measurement predicted this precisely and I
    failed to apply it. PLAN's original 2-cell scope = 32.4 Mpx ≈ one planet window, and fits.
  - **Two false alarms in one session, same root cause: testing a proxy instead of the contract.** (a) A **bbox
    max is not a lake oracle** — it caught Iranian and lower-Volga lakes and reported a 92 m Caspian "leak"
    whose argmax sat on land near Baku. (b) `lakedepth_*.tif` **on disk is the raw, unmasked warp**; `lakes_only`
    is applied in memory (`shade.py:163`), so 1,578 px of shore-lake bleed look like a leak in the file and are
    zeroed before any pixel sees them. Both were my oracle, not the pipeline. **Select by watermask; assert on
    what `composite()` is handed.** Also discarded: an RGB-distance test comparing shore px to the *mean* of all
    sea px — meaningless when the population spans a 98-lum deep basin.
- **Latent dependency gap, found while stamping (not yet fixed, bites only at z10):** the `ocean`/`water`/
  `lakedepth` warps take their grid (`-te`/`-ts`) from `height_3857.tif`, but **none of them depends on it**
  for freshness — `lakedepth`'s only dep is `LAKE_VRT`. Harmless while the grid is frozen at z8; the moment
  a z10 re-fuse re-warps height to a different grid, `lakedepth` stays "fresh" at the old dimensions and the
  composite reads mismatched windows. An mtime dep on `height` is the wrong fix (it would force a needless
  62-min re-warp every time height rebuilds to the *same* grid) — the right one is to compare the existing
  raster's `width/height/bounds` against the target and rebuild only on a genuine mismatch.
- **Process, and the day's real culprit: `/tmp` is a 15 GB RAM-backed tmpfs.** Region renders had been
  writing their intermediates into the session scratchpad — 12 GB of `c_land`/`c_sea`/`sp_merc`/`height`
  tifs from finished experiments (`southasia`, `prod_iceland`, `seamtest`, `stress/scandinavia`), held in
  RAM and spilling to swap. That is why **swap sat pinned at 7/7 all day**, and why the morning's region
  render OOM-killed a box that looked like it had room: the composite's arrays were the trigger, but this
  was why there was no headroom to absorb them. It also broke the Bash tool for ~40 minutes (Warp's
  output-capture hook hitting the tmpfs quota). Clearing it returned 11.5 GB of /tmp, **all 7 GB of swap**,
  and 4 GB of RAM. CLAUDE.md already says to keep project data on ext4; the scratchpad is not an exception.

### 2026-07-15 — The staleness trap: freshness guards for the planet shading chain, and a 41 GB reclaim

Found while auditing INVENTORY.md, which was stale only in the boring way (sizes/dates) but omitted
enough to hide both problems below.

- **`exists()` conflated "built" with "still correct" — one flaw, two symptoms.** Every stage of
  `shade_planet.py` guarded on `if not out.exists()`. The Caspian re-fuse rewrote 4 of 540 chunks, so a
  plain re-run would have **skipped every stage and re-cut tiles from the pre-Caspian rasters**. Worse:
  `planet_rgb.tif` + its `.done` both existed, so the composite would have been skipped too — and that
  file predated `ramp_sea.txt` (12:28 vs 18:59), so the run would have silently **regressed the locked sea
  rework** on top of missing the Caspian. The same flaw also forces a 31 GB rewrite for a 0.15% change:
  the cache granularity is the file (the planet), the change granularity is 4 cells.
- **Fixed with content-gated mtime (`is_stale`).** A stage re-runs if its output is missing, was never
  stamped `.done`, or is older than any input. Three decisions earn their place: (1) inputs include the
  chunk **directory**, not just its VRT — re-fusing a cell never moves the VRT's mtime, which is exactly
  how this hid; (2) freshness reads the **`.done` marker, never the raster** — GDAL stamps its target at
  the *start*, so a crashed pass leaves a full-sized, freshly-dated, half-written file that any mtime test
  on the raster would accept (this closes a partial-output hole the old guard also had, now that `.done`
  covers all 7 outputs, not just `planet_rgb`); (3) params that live only in source (`KNOBS`,
  `WATER_RGB`, ramp stops) are **materialised into generated files via `write_if_changed`**, which rewrites
  only on a real value change. Hashing a 31 GB raster to decide whether to rebuild it is self-defeating,
  and plain mtime on `palette.py` would force a full planet rebuild on every `git checkout`; a generated
  file whose mtime moves iff a value moved gives precision without either cost. `palette.color_relief_text`
  was split out of `write_color_relief` so a ramp can be compared without being touched (byte-identity
  tested). `tests/test_shade_planet.py` covers all of it, including the re-fused-cell case.
- **Windowed patching: possible, rejected for now.** The Caspian is ~0.15% of `height_3857.tif` (≈3,277 ×
  5,462 px of 12.19 billion) — a ~680× write amplification. The prep chain *is* patchable and provably
  seam-free: `gdalwarp` opens an existing target in update mode and resamples from the source VRT (so
  `-te` yields bit-identical output), color-relief is per-pixel, hillshade is local given a halo. Rejected
  because **it wouldn't help**: `WATER_RGB` is a planet-wide change, so the composite (the expensive stage)
  must re-run regardless — and GLOBathy will force a full pass anyway, so a patch path would cost real
  effort, risk reintroducing the seams `shade_planet.py` exists to prevent, and still not spare that pass.
  Batch Caspian + `WATER_RGB` + GLOBathy into one pass instead. (Wrinkle if it's ever built:
  `global_occlusion` normalises against a planet-wide `svf.min()/max()` — non-local, the same hazard flagged
  for GLOBathy's shore-distance transform.)
- **Reclaimed 41 GB** (487 → 529 GB free) — itemised in [INVENTORY.md](INVENTORY.md). Mostly superseded
  generations the old one-line `planet_tiles/` summary hid: the retired 194-strip `blocks/` (8.2 GB), the
  pre-rework `tiles_old/` (13 GB) and `planet_rgb.tif` (14 GB, also the trap above), the `redsea_proto/`
  A/B variants (4.8 GB). Kept `planet_rgb_v1.tif` — it is the source of the live tiles and the only RGB
  rollback until the Caspian re-shade lands.

### 2026-07-15 — Inland water: the `WATER_RGB` drift, the Caspian probe (open question resolved), and the lake-depth dataset evaluation

Triggered by Rohan spotting a "stark difference" between inland lakes/rivers and the reworked sea on the
globe (Caucasus/Caspian screenshot).

- **`WATER_RGB` had silently drifted, and it was a test gap.** The 2026-07-14 sea rework deepened the sea
  surface ~15% (`8FC7C5` → `85B9B7`) but left the flat inland tint stranded at the old-era `98C5C8`
  (152,197,200) — brighter *and* bluer than the sea it's meant to sit beside (B=200 > G=197, a cool cyan
  lean the teal sea doesn't have). Originally the two *were* related (inland = a slightly-lighter tint of the
  sea surface, the standard lake convention); the rework broke that silently because
  **`tests/test_palette.py` freezes the land/sea ramp endpoints but not `WATER_RGB`** — nothing tied the
  inland tint to the sea surface, so nothing failed. Re-synced to **`#8EC6C4` (142,198,196)** = the new sea
  surface lightened ~7%. Worth adding a guard that pins `WATER_RGB` *relative to* `SEA_STOPS[0]` so the
  relationship can't drift again.
- **But the base colour was never the real problem — measured, not assumed.** The re-render moved the
  Caspian only 184 → 180 luminance: imperceptible. Sampling the actual raster showed why: the sea spans
  **lum 126 (deep basin) → 191 (coastal shallow)** depending on depth, so the Caspian's flat 180 already
  sat right next to the sea's *coastal* band. The eye compares it against the **deep** basin, and no flat
  fill can close a 126-vs-180 gap. **The clash is structural — flat fill vs depth shading — not chromatic.**
  The `#8EC6C4` change is kept on its own merit (small/shallow lakes and rivers *should* be flat, and they
  now sit in the sea's green-teal family), but it is not the answer to what Rohan saw.
- **Open question resolved — "Caspian Sea routing" (both halves of its probe).** WBM class = **2 (inland
  lake)**, and GEBCO **does** carry its measured bathymetry. The fusion consults GEBCO only where `ocean`
  (`fuse_heightfield.py:211`), and `coastal_water` (`|land| ≤ 1`) can't fire on a −28 m surface → the
  heightfield takes GLO-30's flat lake surface. Verified: fused = **−28.0 m at both the deep basin and the
  north shelf**, while GEBCO holds **−464 m / −1026 m**. The data exists and fusion discards it.
- **The fix, as shipped** (`fuse_heightfield.is_caspian`, re-fused 2026-07-15; migrated here from PLAN on
  2026-07-16 once it stopped being a forward plan). One rule absorbs the Caspian into `ocean`, after which
  *everything downstream flows with no shading change* — oceanmask → sea ramp + `sea_lift`/`sea_shade`/
  `sea_svf`, and `classify_water` reclassifies 2→1 so the flat-water branch stops catching it:

      (wbm == 2) & (land < CASPIAN_MAX_SURFACE_M) & in_bbox(46.5, 36.5 → 55.5, 47.5)

  **Each clause earns its place, and the bbox is load-bearing rather than laziness:**
  - `wbm == 2` gives the **DEM's own shoreline**, so GEBCO's coarse 15″ coast never defines the edge
    (`min(gebco, -1)` then keeps shallow margins continuous instead of cutting a ring).
  - `land < −5 m` excludes the **Mingevir Reservoir** (+83 m); the Caspian's surface is a uniform −28 m.
  - The **bbox** excludes the **Dead Sea** (−430 m, WBM lake, but **no GEBCO bathymetry**). Without it the
    rule catches the Dead Sea, which collapses to `min(gebco, -1) = −1` and renders as a flat bright slab —
    a regression. This is why the rule is not simply "below-sea-level lakes".
  - Uniquely cheap **because the Caspian is below sea level throughout**, so absolute elevation maps onto the
    existing sea ramp: no new ramp, no per-lake datum. Nothing else on the planet qualifies.
  - **Expected result was structure, not darkness** — median Caspian depth is only ~48 m, so it stays
    legitimately bright. Predicted lum 180 → 168 shelf / 152 mid / 146 deep (vs Black Sea 129). The
    2026-07-15 regression render measured p10/p50/p90 = **137.0 / 158.8 / 167.8** against a *literal* flat
    slab (spread **0.0** over 2.37 M px). A flat slab became a shaded basin, as predicted.
- **Lake-depth datasets evaluated (answers `lake_depth_prototype.py`'s "see the PLAN.md open question").**
  GEBCO was probed across every major lake: real bathymetry for **the Caspian and the Great Lakes only** —
  Baikal, Tanganyika, Victoria, Titicaca, Ladoga, Great Bear and the Aral all return a flat surface
  elevation. So there is no general "lakes get bathymetry" feature available from what we already hold.
  - **GLOBathy** (Khazaei 2022, *Sci Data*; CC0; 1.43 M waterbodies; 1″) — **chosen** as the general answer.
    It is literally `lake_depth_prototype.py` *with* calibration: the same linear cone `D = l × Dmax / L`
    (Hollister & Milstead distance method over HydroLAKES), but with true published `Dmax` for every lake
    GEBCO misses. Fake but *visually plausible*, which is the stated bar. Caveats: a single deepest point per
    lake, no sills/ridges; depth-below-surface with **no elevation column** → needs a HydroLAKES join
    (CC-BY-4.0 attribution, unlike GLOBathy's CC0) to place basins vertically.
  - **Architectural catch that shapes the eventual implementation:** a shore-distance transform is inherently
    **non-local**, but `fuse_planet` is deliberately per-pixel/co-located precisely so cells are independent
    and share bit-identical seams. A lake straddling a cell edge would compute wrong distances cell-wise —
    which is the argument for eating GLOBathy's pre-computed, globally-consistent per-lake rasters rather
    than rolling our own cone. (At 306 m/px only lakes more than a few km across show any gradient, so a
    few thousand rasters, not 1.4 M.)
  - **3D-LAKES** (Huang 2025, *Sci Data*) — **rejected.** Its bathymetry covers only the lake bed *exposed
    by water-level variation* over Landsat 1984–2021 (the drawdown zone); anything below the historical
    minimum water level is absent, so a stable-level lake like Baikal yields a thin rim and nothing else.
    Also quantized to 91 elevation steps (terraced). Built for storage-change hydrology, not relief.
  - **GLDB / Kourzeneva v2** — **rejected as a foundation, retained as a possible supplement.** Probing the
    actual raster: **36 lakes carry real digitized bathymetry** (Great Lakes via ETOPO1, plus Ladoga,
    Victoria, Great Bear, Great Slave, Winnipeg, Balkhash, Sevan, Onego…, from ILEC surveys and Russian navy
    charts); everything else is a flat slab at mean depth (Baikal = a single 744 m value). Decisively, the
    gridded file is **freshwater-only — the Caspian is absent entirely.** 30″ (~1 km ≈ 3× our z8 px, adequate),
    10.2 MB gzipped / 2.8 GB unpacked, HTTP-only host; **GLDBv3 is unobtainable** (host 404s, only v2 served).
  - **Decision: decouple.** Caspian now via GEBCO (measured data beats GLOBathy's cone *for that lake*, and
    GLDB doesn't have it); GLOBathy logged as the decided answer to the general lake-depth question, to be
    done as its own pass (needs a lake ramp + planet-wide re-fuse and re-tile).
- **Process note (cost a real OOM):** the first preview re-render (4 cells, 70 M px) was killed entering
  `composite()` — it materialises a stack of full-size float32 arrays at once, and the box was already at
  0 GB free with swap full. It took the terminal *and* the astro dev server with it. Re-ran 2 cells under
  `systemd-run --user --scope -p MemoryMax=8G -p MemorySwapMax=0` → clean. **Any region render must be
  cgroup-capped**, per CLAUDE.md's one-heavy-job-at-a-time rule. Separately: `shade.py`'s region path
  re-runs reprojection, colour-relief and hillshade *unconditionally* (no skip-if-present, unlike
  `shade_planet.py`), so a crash in `composite()` discards ~2 min of prep already on disk — at odds with the
  "idempotent and resumable" convention and worth fixing if we iterate on palette values much.

### 2026-07-15 (later) — Frontend hardening: astro-check + TS, `.ts` config + `.env`, Tier-1 gazetteer, Spin option A

All on `feat/frontend` (uncommitted at time of writing — Rohan's to commit).

- **`astro check` wired up; 106 strict-mode errors cleared → 0/0/0.** Added `@astrojs/check`; **pinned
  `typescript` to 6.x** — TS 7's native (Go) compiler dropped the programmatic API `astro check` relies on,
  so it errors at startup; 6.x is the newest that works. (This *overrides* "use latest verified versions":
  7 is latest but not *compatible* — don't bump it until `@astrojs/check` supports the native compiler.)
  Load-bearing gotcha found: **JSDoc `@type` casts are silently ignored inside Astro `<script>` blocks**
  (they're TS, not JS) → several `getElementById`/`querySelector` refs stayed `Element|null` and failed
  strict; converted to real `as` casts. Maplibre paint/filter consts typed with
  `ExpressionSpecification`/`FilterSpecification` as **annotations** (contextual typing validates the array
  literals), not `as` assertions.
- **`astro.config.mjs` → `astro.config.ts`.** Dev-only asset-store paths (`HERO/TILES/BORDERS_STORE`) moved
  out of committed source into a **gitignored `.env`** (+ committed `.env.example`), read via Vite
  `loadEnv` (needed because `.env` isn't in `process.env` at config-load). **No fallback** — the on-disk
  layout will change when this worktree folds into the main repo, so a sibling-path guess would silently
  resolve wrong; an unset var fails loudly instead. **Validation is per-request inside the middleware, NOT
  at `configureServer`:** Astro's *build* creates a Vite server that runs `configureServer`, so validating
  there breaks `astro build`; the asset routes are never *requested* during build, so a per-request check
  keeps build green and 500s the dev route clearly when a var is unset (proven live by cycling the dev
  server without `.env`).
- **Spin option A shipped.** Above `SPIN_MAX_ZOOM` (z3) the Spin toggle is now **disabled + greyed with a
  "Zoom out to spin" tooltip**, re-enabled on zoom-out (`zoomend` → `syncSpinAvailability`) — fixes the
  dead-toggle confusion (checking it there was a silent no-op). Auto-resume still deferred (see entry below).
- **Tier-1 no-JS fallback = the gazetteer.** The gallery already SSGs all 203 cards, so browsing needs no
  JS; the only gaps were the dead search box + no find-by-name. Removed the search entirely; added an atlas
  **gazetteer** — every country a link with its **bbox-centroid coordinates** (mono), grouped under Fraunces
  letter-markers, with an A–Z rail. Rohan rejected a bottom-of-page placement (buried on mobile), so it
  **opens as a full-screen overlay** from the header "Index" link, done in **pure CSS**: `.gazetteer:target`
  opens it, `.gazetteer:has(:target)` keeps it open through letter-jumps (kept as *separate* rulesets so a
  browser without `:has()` still honours `:target` and can open it) — zero JS, and Cmd/Ctrl+F searches it
  once open. Plus a `no-js`→`js` `<html>` class flip (inline pre-paint) so `.fab-stack` (border/quality
  toggles) hides when JS is off — no dead controls. Grid untouched. Design chosen via the frontend-design
  skill: the atlas *gazetteer* is the subject-true find tool; coordinates are the signature detail.

### 2026-07-15 — Frontend: capability probe, tier routing, quality + spin toggles, mobile polish (all committed on `feat/frontend`)

Shipped the three-tier selection end-to-end and polished the globe on mobile. Commits: `a595ef9`
(capability probe + auto-steer), `c7eda66` (spin toggle + the fixes below).

- **Capability probe** (`src/lib/capability.ts`): pure `decideTier(signals, quality)` (WebGL2 hard
  floor; software-GPU via `WEBGL_debug_renderer_info`; Save-Data / slow-net / low-mem / reduced-motion),
  TDD, 15 vitest cases. A pre-paint inline `<head>` guard in `Base.astro` steers capable visitors
  `/` → `/globe/` (bounces incapable/Lite deep-links back), no flash. Quality toggle persists `rg:quality`.
- **Mobile fixes:** control-collision → single bottom-right `.fab-stack` (order Spin, Borders,
  Lite/Globe/Full — quality at the bottom per Rohan). Borders de-jagged: the geojson source `tolerance`
  was **1.2** (3× default) → back to **0.375** + `buffer: 256` (the staircase + intermittent breaks).
  Attribution compact-collapses to the ⓘ on small screens and is **re-parented to `<body>`** so, when
  expanded, it floats above the controls — it's otherwise trapped under `.fab-stack` inside `#globe`'s
  `position:fixed; z-index:1` stacking context (no element z-index can escape that).
- **Spin (current, committed):** idle rotation at ≤ z3; **any interaction retires it** (Spin checkbox
  unticks) and the **Spin toggle restarts it**. `map.stop()` on pointer-down kills the in-flight easeTo
  so a pan starting mid-spin can't fight it / misfire as a country click. Suppressed above z3 because the
  fixed 2°/s sweep whips the surface past too fast to follow.
- **FAILED experiment — resume-on-zoom-out (do NOT re-attempt naively).** Tried making Spin a persistent
  auto-rotate *mode* (a `userInteracting` flag; resume by calling `spin()`/easeTo from `mouseup` /
  `zoomend` / `moveend`; `zoomstart`/`zoomend` handlers to pause). It **broke MapLibre's render loop** —
  re-entrant `easeTo`/`map.stop` from the map's own animation events →
  `TypeError: this._onEaseFrame is not a function` and `Error: Attempting to run(), but is already
  running`; the zoom handlers chopped scroll-zoom into janky micro-steps fighting the spin; and pan died
  after zooming in. Reverted. **Lesson:** never call `easeTo`/`map.stop` re-entrantly from MapLibre's
  `mouseup`/`zoomend`/`moveend` during an animation. Resume-on-zoom-out is still wanted but **deferred** —
  if revisited, use MapLibre's official spin-globe pattern (no `map.stop`, no custom zoom handlers) and
  test the full zoom + pan + click matrix in a real browser *before* declaring it done.

### 2026-07-14 (night) — Sea rework (#3): levers 1+2 prototyped, **V1 chosen** (lock + winner z0-8 pending)

The sea read as a flat, tacked-on backdrop with no depth. Diagnosis (from the code): `shade.py`
shaded the seafloor at only `sea_shade=0.26` off a land-exaggerated hillshade (near-flat on gentle
bathymetry), forced ocean SVF to 1.0 (no ambient occlusion), and `palette.py` `SEA_MIN_M=-3000`
clamped all deep ocean to one slab while the ramp squeezed shelves into ~7% of its range.

**Levers applied (PROTOTYPE — uncommitted, not yet locked):**
- `palette.py`: `SEA_STOPS` redistributed so the two brightest bands sit in the top 800 m (shelves
  read as a gradient); `SEA_MIN_M` -3000 → **-6000** (deep ocean varies, e.g. Gulf of Aden);
  surface + shelf stops **deepened ~15%** (pull the bright cyan toward a richer teal — Rohan's ask).
- `shade.py`: new `sea_svf` knob (ocean gets a fraction of the land occlusion); un-compressed
  `sea_shade`. Caveat: the SVF input zeroes bathy below -500 m, so deep-basin AO is limited — shelves
  and shelf-edges carry it; deep gets depth from ramp+hillshade. (Lever 3 = a sea-specific
  high-exaggeration hillshade — deferred; would sculpt the abyss but wasn't needed for 1+2.)

**Candidates (sea knobs; shared palette/tone):** V1 `{sea_shade 0.55, sea_lift 1.00, sea_svf 0.5}`
(calmer, water-like sheen), V2 `{0.72, 0.98, 0.7}` (stronger relief). Prototyped on the Red Sea via
`shade.py --cells` (fast, no planet re-shade). **Rohan chose V1** — pending his final go to lock.

**A/B infra (all verified live on the globe):** `pipeline/experiments/sea_ab.py` **[deleted
2026-07-16 — fully dead: its subject locked at V1, its winner's knobs baked into `shade.py`'s
KNOBS, and both stages it drove (`color_and_hillshade`, `sea_3857.tif`) removed with the
color-relief deletion. The dual-variant machinery it exercised SURVIVES as
`composite_planet(variants=..., max_windows=...)` for the next A/B]** drove a
dual-output planet composite (both variants in one pass) → non-destructive `tiles_v1`/`tiles_v2`
(z0-7; z8 deferred to the winner), live tiles untouched. Frontend: `globe.astro` Current/V1/V2
segmented toggle + two hidden raster sources; `astro.config.mjs` serves `/tiles-v1` `/tiles-v2`.
Both sets built (15,585 tiles each).

**Profiling (measured, `composite_bench.py`):** the hotspot is the **composite numpy math**
(~2 s/window, run once per variant), then the per-window snow-warp + glacier-rasterize gdal
subprocesses (~2 s combined). Optimizations tested: **#1** share-across-variants — pixel-identical
but only ~4% faster, **dropped**; **#3** bigger windows — **dropped** (caused an OOM, below);
**#2 precompute global snow_alpha + glacier rasters once** (warp+rasterize to two 3857 rasters,
~24 GB disk, composite reads slices) — **saves ~2.9 s/window; BUILD THIS for the winner z0-8 pass.**

**OOM incident (20:40):** ran `composite_bench` concurrently with the v2 tiling; the benchmark held
all 5 windows + composited a 768-row window (~19 GB RSS) and the box (29 GB RAM, 8 GB swap already
**full**) OOM-killed it, interrupting the v2 tile cut (since resumed). **Operating rule: one heavy
pipeline job at a time — no second pass or benchmark alongside it.** (`composite_bench` has this
memory bug: holds all windows + a 768-row composite — bound it before any re-run.)

**NOT DONE / next (blocked on Rohan's go to lock V1):**
1. Bake V1 knobs into `shade.py` KNOBS defaults (currently the OLD `sea_shade=0.26, sea_lift=1.08,
   sea_svf=0.0`); `palette.py` already holds the new ramp/tone as prototype.
2. Update `tests/test_palette.py` + the CLAUDE.md locked sea constants (still the OLD `8FC7C5`/
   `3A6E7D` at 0/-3000 — the frozen set Rohan OK'd moving; the test will fail until updated).
3. Run the winner's full **z0-8** into the live tiles, built with the **#2 precompute** optimization,
   run **solo**. Then a globe re-check + commit.

Uncommitted prototype state: `palette.py`, `shade.py`, `shade_planet.py`, `sea_ab.py`,
`composite_bench.py` (main worktree); `globe.astro`, `astro.config.mjs` (frontend worktree).

### 2026-07-14 (evening) — #4 "highest point" stat attempted then dropped; Google Earth datasets assessed

**Highest-point stat — dropped.** Tried computing a per-country highest point from our fused
heightfields (`data/work/<slug>/heightfield_{1s,3s}.tif`, EPSG:4326 float32 m) by masking with the
NE country polygon (zonal max). Prototyped thoroughly; dropped for two reasons:
- **Accuracy wart from generalised NE borders.** NE 10m borders assign border-straddling summits to
  one side, so the masked max misattributes marquee peaks. Worst case **Nepal → ~8,140 m, not Everest
  8,849** (NE draws the border south of the summit; the 8,731 m pixel lands on the China side, and even
  ~600 m of mask dilation only reached 8,371). Most countries were within ~2 % (France nailed Mont
  Blanc 4,804; India 8,535≈Kangchenjunga; Netherlands 325≈Vaalserberg) — but a visibly-wrong Nepal on
  a relief site isn't worth shipping. This is inherent to our committed NE-default worldview, not a bug.
- **Compute cost for giants.** An accurate masked max must scan all interior pixels; native block-stream
  of Russia's 3s field (10 G cells) exceeded 2 min *per country* (~15 giants → 30 min+). The coarse
  global `planet_heightfield.vrt` (10 arc-sec) is fast (Russia 18 s) but its coarse mask **leaks foreign
  terrain into small countries** (Netherlands → 819 m, grabbing German uplands). A size-gated hybrid
  (native for small, decimated for giants) would work but wasn't worth the complexity for a card stat.

Verdict: the panel keeps its current copy; no computed elevation. Revisit only if we want a curated
highest-point table (hand-authored, off our data) — deliberately not doing that now.

**Google Earth datasets vs ours (from its Data-attribution panel).** Its list — *SIO/NOAA/US Navy/NGA/
GEBCO, Landsat/Copernicus, IBCAO, USGS, PGC/NASA* — maps to: ocean floor = SRTM15+ (Scripps) blended
with GEBCO, i.e. **the same ~15″ (~450 m) altimetry-predicted bathymetry class we use** (so Google's
oceans are smooth for the same reason — confirms the **#3** finding that our blurry/flat deep sea is a
data limit, fix is aesthetic not data); Landsat/Copernicus = optical *imagery* (Sentinel-2, a different
product from the Copernicus **DEM** GLO-30 we use — not our medium); IBCAO = Arctic bathymetry already
inside GEBCO; USGS = SRTM-class land (older/inferior to our TanDEM-X-derived GLO-30 globally).
**The one genuinely-better source is PGC/NASA = REMA (Antarctica) + ArcticDEM (Greenland/Arctic), 2 m
native** — relevant only to our deferred polar work (both currently flat-capped). Filed for the
Antarctica/Greenland pass; no change to land (GLO-30) or bathymetry (GEBCO) choices.

### 2026-07-14 (evening) — Starfield space backdrop shipped (`feat/frontend`)

Built #5. The globe now sits in dark space with a sparse, static starfield instead of the flat teal
fill. Approach: a full-viewport `<canvas id="starfield">` painted **behind** a now-transparent map
(dropped the solid-teal `space` background layer, so MapLibre's canvas is transparent in space and
the stars read through around the sphere). Ground is `#0e1519` (very dark desaturated navy, not pure
black — stays in the Neutral palette); ~1 pale star per 5200 CSS px², radius 0.4–1.3 px, opacity
0.16–0.66. **Static — no twinkle**, so it's inherently calm and reduced-motion-safe; repainted only
on resize (DPR-backed for crisp hi-DPI stars). No "when zoomed out" logic needed — the sphere covers
the field when zoomed in.

The one risk flagged when scoping — that dropping the teal background (which also "blends any gap at
the capped poles into the disc") would expose stars through the un-tiled sliver above +85°/below −60°
— proved a **non-issue**: the flat polar caps baked into the tiles plus the atmosphere fully cover
the top, verified by zooming the north pole (Greenland's white cap, no stars poking through). The
soft blue `setSky` atmosphere, kept unchanged, reads as a gentle earth-glow against the dark space
(the earlier worry it would wash to light grey was unfounded).

### 2026-07-14 (evening) — Globe experience polish: remaining items scoped (from using the globe)

Five notes from living with the globe. #1 (in-place render zoom) is BUILT — see the next entry.
The rest are scoped-not-built; capturing so they survive compaction:

- **#5 Starfield (NEXT UP):** a space backdrop when zoomed out. MapLibre `setSky` has **no star
  support** (Mapbox-only) → DIY: replace the solid teal `space` background layer with a transparent
  space + a sparse, faint starfield on a **very dark desaturated navy** (not pure black — stay in the
  Neutral palette), **no twinkle** (or honour `prefers-reduced-motion`). Needs no "when zoomed out"
  logic: space is only visible when the globe is small, so stars appear only zoomed out.
- **#4 Richer hero panel:** add **elevation range / highest point** — computable from our own fused
  heightfield in `gen_manifest.py` (sample per-country min/max), reinforces the relief theme; and/or
  the hypsometric `Legend` scaled to the country. **Push back on population/area/capital** (off-brand
  almanac data).
- **#3 Bathymetry reads blurry + flat** — **not a Tier-3 issue** (Tier 3 = 3D displacement). Two
  separate causes: (a) *blurry* is a hard data limit — GEBCO ~450 m (15″) vs GLO-30 30 m land, ~15×
  coarser → upsampled = smooth; unfixable globally. (b) *flat* is **our own tunable choice** —
  `palette.py` `SEA_MIN_M = -3000` clamps every depth past 3 km to one deepest colour (most open
  ocean → featureless slab), and the sea hillshade is faint on GEBCO's gentle gradients at the current
  z. Fix direction: extend/band the depth ramp (hypsometric sea tint = the "shelf seas" signature) +
  a stronger sea-specific hillshade — a `palette.py` + `shade_planet.py` tune; **prototype on Red Sea /
  Mediterranean** (good shelf structure) before any planet re-shade. Lives under the Phase-2 "on-globe
  tile judgment" item.
- **#2 Mumbai-in-viewport (answered, no work):** pyramid ceiling is z8 ≈ 290 m/px at 19°N → a laptop
  viewport frames ~250 km (Mumbai ~70 px). Filling the screen with the city needs ~z11 (~30 m, GLO-30
  native) = the deferred finer re-fuse (the z10+ open question), not available today.

Sequence: #1 done → **#5 starfield next** → #3 as its own focused session; #4 opportunistic.

### 2026-07-14 (evening) — Detail-page hero: in-place pan/zoom (`feat/frontend`)

The full-size render (`/[slug]/`) now zooms in-place: wheel / double-click / pinch to zoom,
drag or arrow-keys to pan, a Reset control, edge-clamped so no gutters. The **native full-res
variant is lazy-loaded the first time you zoom** so the page still loads on the light display
variant. Vanilla pointer-events, no library; descriptive names throughout.

**Perf rewrite (do not regress to CSS transform).** First cut CSS-`transform: scale()`-ed a
`<img>` of the 7680 px hero: catastrophically janky — wheel sluggish, the Reset *click* delayed
5–10 s and worse the more you'd zoomed. Cause: transform-scaling the bitmap forces the browser to
re-rasterise the whole scaled image each frame, and once scaled dims pass the ~8192 px GPU max
texture size it falls back to CPU-tiled raster; those multi-hundred-ms tasks starve the input queue.
Fix: render into a viewport-sized box and sample the source via **`background-size` +
`background-position`** (`.zoom-hero`/`.zoom-border` divs) — the painted element stays frame-sized
(verified 1420×1338 even at scale), so every frame is one small raster, never a giant re-raster.
No `will-change`, no rAF batching (background-* are paint-only → the browser already coalesces to one
paint/frame; rAF also went dead in backgrounded tabs, which broke local verification).

Follow-up fixes (same session): (1) **Reset needed a few tries** — the figure's `pointerdown` did
`setPointerCapture`, which retargets the pointerup and swallows the Reset button's `click`; guard with
`resetButton.contains(event.target) → return`. (2) **Black flash on first zoom** — swapping
`background-image` to the not-yet-loaded native URL showed the dark figure background through the gap;
now preload + `img.decode()` and only swap on `.finally()`, so the display variant holds until native
is ready. (3) **Globe → hero navigation spammed `AJAXError: NetworkError`** — MapLibre tiles in flight
abort on navigation; added a `map.on("error")` gate that silences AJAX/Network errors once a `pagehide`
flag is set, but still surfaces genuine errors during use.

### 2026-07-14 (evening) — Click-to-fly-to → in-globe hero panel (BUILT, `feat/frontend`)

Globe interaction: click a country → `fitBounds` to it → show its hero in a floating panel.
Built exactly on the design below; Rohan's two calls were **in-globe overlay panel** (not detail-page
nav) and **one pass**. Pieces: `pipeline/compose/countries_geojson.py` (new; NE country polygons
simplified at 0.05° → `data/work/borders/countries.geojson`, 1.5 MB, served via the existing
`/borders` middleware), `bbox=list(r["frame"])` added to `gen_manifest.py`, and the interaction +
floating `.hero-panel` in `globe.astro`. The panel reuses the hero `srcset`/`variantWidth` math and
the shared `body.borders-on` toggle from the detail page.

Latent bug fixed in passing: `gen_manifest.py`'s import was stale (`sys.path` at `pipeline/` +
`from country_config import …`) since `country_config` moved to `pipeline/frame/` and switched to
absolute `pipeline.*` imports — now inserts the repo **root** and imports `pipeline.frame.country_config`.

Verified live (Chrome): the invisible `fill-opacity:0` layer is queryable (click hit "Chad",
`promoteId:'ADMIN'` gives feature id = ADMIN), panel populates (eyebrow/name/`/slug/` link/hero),
border overlay follows the toggle, and the `padding.right:460` frames the country **clear of the
panel**. Note: the `fitBounds` *animation* couldn't be observed in the harness (the automation tab is
`visibilityState:hidden` → `requestAnimationFrame` is paused, so all easing/tile-fade/`load`/`idle`
stall; screenshots still force a one-off paint). Destination framing validated via a synchronous
`jumpTo(cameraForBounds(...))`; the animation is stock MapLibre and runs when the tab is visible.

UX refinement (same session, on Rohan's feedback): (1) the flat white hover *tint* didn't delineate
the boundary, so hover now draws a **gold silhouette wash + gold outline over a soft dark casing**
(`country-hl-casing`/`country-hl-line`, added above the borders). Gold is the one hue that pops on all
three grounds — the teal accent would vanish along coasts against the teal sea — and it reads as an
interactive pick, distinct from the white informational borders. (2) The panel's "View full render"
was opaque about what it offered, so it now carries a descriptor ("A ray-traced relief render — softer
shadows and heightened terrain than the globe's live tiles") and the link reads "Open full-size render
→". Fixed in passing: a shared `.hp-figure img { display:block }` outranked `.hp-border`'s
`display:none`, forcing the panel's border overlay **on regardless of the toggle** — scoped the
`display:block` to `.hp-hero` (the detail page dodges this by not putting `display` on the shared rule).

Original design (discovered from `country_config.resolve()`, `gen_manifest.py`, and the NE countries
shapefile), for reference:

- **Hit detection:** the globe is raster, so add NE `ne_10m_admin_0_countries` polygons (258,
  EPSG:4326, attrs `ADMIN`/`ISO_A3`) as an *invisible fill* layer; `map.on('click','country-fill')`
  + `queryRenderedFeatures` returns the clicked country. Shapefile is 8.8 MB → **simplify hard**
  (`ogr2ogr -simplify`) to a few hundred KB (only needed for hit-testing + a hover tint, not
  coastline detail). New generator `pipeline/compose/countries_geojson.py` (mirror
  `borders_geojson.py`), served via the `/borders`-style middleware.
- **The join is FREE:** `countries.json.name` IS the NE `ADMIN` string (`gen_manifest` sets
  `name = resolve()["admin"]`). So clicked `feature.properties.ADMIN` → our record by
  `name === ADMIN`; no ISO matching. NE 258 polygons vs our ~204 scope → gate hover/pointer/click
  to matched names; unmatched (Antarctica, micro-territories, excludes) are no-ops.
- **Fly-to bbox = the authored hero frame:** `resolve()["frame"]` = (w,s,e,n) 4326 — same framing
  as the heroes, and it already fixes the awkward multipolygon cases (France's *raw* bbox spans to
  French Guiana; the override frame uses metropolitan France; same for US/Chile/Russia). Surface
  via ONE line in `gen_manifest.py` (`bbox=list(r["frame"])`), regenerate countries.json, then
  `fitBounds(bbox)` or `cameraForBounds→flyTo` (curved). **VERIFY on build:** MapLibre accepts the
  flat `[w,s,e,n]` bounds form, and `fitBounds` frames sanely under *globe* projection for big/
  high-lat countries (Russia/Canada).
- **Hover polish:** pointer + faint fill tint via `feature-state` + `promoteId:'ADMIN'`; a click
  stops the idle spin; Esc/close returns to the globe.
- **RESOLVED:** hero display → in-globe overlay panel (lazy `<img srcset>` from `/heroes/` + close/Esc,
  a "View full render →" link to `/[slug]/`); built in one pass. The "rendering…" placeholder path is
  moot — all 203 in-scope countries are rendered, and the fill layer is filtered to those names, so an
  unrendered country is simply not clickable.

### 2026-07-14 (evening) — Tier 2 globe + Natural Earth vector borders (frontend, `feat/frontend`)

First interactive globe. Standalone `/globe` route (deliberately independent of the not-yet-built
capability probe, so Tier 2 can be judged in isolation; the probe will later route `/` here with the
gallery as fallback).

- **Library:** MapLibre GL **5.24.0** (current stable; v6 is prerelease). Verified via research that
  v6 (ESM-only, WebGL1-drop, raster mipmaps) and WebGPU are *below-the-API* changes — nothing we'd
  author differently today; authored v6-safe anyway (ESM `import`, public API only, no `map.transform`,
  modern array expressions). WebGPU in GL JS is Phase 4 of a 5-phase plan (mid-Phase-1 in mid-2026),
  realistically 2027+, and lands as an opt-in over a WebGL2 default — a future no-op tier, not a rewrite.
- **Config lifted from the proven `planet_tiles/index.html` viewer:** raster source
  `/tiles/{z}/{x}/{y}.png`, `tileSize:256` (512px assets @2x for crisp DPI), globe projection declared
  in the style (v5 stable), soft sky, `maxZoom:8` (data ceiling; never reaches the z12 globe→mercator
  auto-switch). Baked polar caps show as clean discs on the sphere — no starburst.
- **Framework-free integration:** the Astro site has no UI framework, so MapLibre lives in a plain
  Astro-bundled `<script>` (code-split — absent from the gallery bundle). Dev serving mirrors the
  existing `heroDevServer()`: added `/tiles` + `/borders` Vite middlewares in `astro.config.mjs`
  (same-origin → no CORS; nginx serves the same paths in prod; PMTiles is a Phase-4 packaging swap).
- **Controls:** Navigation + Globe (globe⇄flat toggle) + Scale + Attribution (bottom-left, clear of
  the border toggle). **Idle spin** refactored onto the map's own gesture events
  (`dragstart`/`zoomstart`/…) rather than ad-hoc DOM listeners — pauses cleanly, never fights its own
  `easeTo`, and is skipped entirely under `prefers-reduced-motion`.
- **Vector borders (land-only v1):** the hero border PNGs are baked into each country's Albers camera
  and cannot drape on a sphere, so the globe needs live vector geometry (CLAUDE.md already mandates a
  vector overlay, never baked). `pipeline/compose/borders_geojson.py` = one `ogr2ogr` call translating
  NE `ne_10m_admin_0_boundary_lines_land` (already EPSG:4326 → format change, not reprojection) →
  `data/work/borders/boundary_lines.geojson` (505 lines, FEATURECLA carried, 3 non-rendered classes
  dropped, ~1 m precision, 2.0 MB, gitignored). One MapLibre `geojson` source (`maxzoom:8`, `tolerance`
  for low-zoom thinning, NE attribution) → four `line` layers: dark casing under white ink, each split
  solid-international vs dashed-disputed/LoC by a **layer `filter` on FEATURECLA** (not a source filter,
  not `promoteId`). Toggled by layer `visibility` off the shared `rg:borders` key (one control across
  gallery/detail/globe). **Maritime indicator lines: added then dropped (2026-07-14)** —
  NE's maritime "indicator" data is open `LineString` segments (median/treaty/200 nm limits)
  that *divide* seas rather than enclose territory, so on a relief-first globe they read as
  disconnected offshore noise, not boundaries; land borders already carry country identity.
  Generator (`borders_geojson.py`) and frontend reverted to land-only. (EEZ *polygon* zones
  would be a different, larger, more political dataset if maritime territory is ever wanted.)
- **Border legibility fix (same day):** the white line vanished over pale highlands + snow
  (Tibet/Himalaya) — a single-colour line can't self-contrast against both light and dark ground, and
  the casing (`#3d2b1f` @ 0.5, thin) was decorative. Fix (Option A + blur): strengthened the casing
  into a real dark halo — darker/near-neutral colour, higher opacity, wider rim, slight `line-blur` to
  match the soft raytraced aesthetic. Rejected terrain-adaptive line colour (MapLibre can't condition
  line colour on the raster beneath it; cased line is the correct tool).

### 2026-07-14 (day) — Tile-shading rework: readable snow, exposure, seamless per-latitude relief, pole caps, float32/window RAM fix

Fixes to the overnight globe, driven by on-8765 review. **Three distinct defects, three causes** (do not conflate):

- **Himalaya grey smear vs white Greenland** — a *rendering* issue, not data. Snow is a soft alpha
  over the hillshade; the neutral `SNOW_RGB × light` floored shaded snow on rugged terrain to grey,
  while flat Greenland (persistence≈1) stayed white. Fix: two-colour snow ramp —
  `palette.SNOW_SHADOW_RGB` (blue-white) → `SNOW_RGB`, keyed by light. Verified Karakoram/Alps/Greenland.
- **Sri Lanka "washed out / too bright"** — a *land-exposure* blow-out, unrelated to snow. Pale-sand
  lowland (233,217,192) × `exposure=1.30`'s 1.15× flat-lit gain clipped to white (30% of land ≥235).
  Fix: `exposure` 1.30 → **1.05** (flat land ≈ true colour; mountains keep punch — `ambient`/`hi`
  unchanged). Knobs were Nepal-tuned, so flat bright lowland was never seen. Verified Sri Lanka + Alps.
- **North-pole starburst** — MapLibre's globe smears the non-uniform ±85.05° edge row into the pole.
  Fix: flat deep-sea pole caps (>84°N, <−59.5°S). Same for the −60°S (Antarctica-deferred) edge.
- **Seams + wrong exaggeration** (the "refinements") — retired per-strip `tile_planet.py` (single
  global z=20 blew out tropics; per-strip `--compute_edges` seamed ocean) for **one global streaming
  pass** `pipeline/tile/shade_planet.py`: warp→3857 once, global color-relief, a **custom per-row-z
  hillshade** `render/hillshade.py` (z=15/cos(lat), full-width + 1-row halo → seamless + correct 15×
  everywhere; matches gdaldem ≤1 DN), globally-normalised SVF (back on), per-window composite.
- **OOM fix** — the full-width float64 composite at 384 rows peaked ~18 GB (numpy temporaries stack
  on persistent arrays; memory *creeps* over windows) and was OOM-killed under browser load. Fix:
  `composite()` in **float32** (output-identical, ≤1 DN), `WINDOW_ROWS=256`, per-window `del`+`gc`,
  launch `GDAL_CACHEMAX=512` → ~2.6 GB RSS in practice.
- **Docs** — split the 726-line decision log into HISTORY.md; PLAN.md 870→~185 lines + a new "Active
  learnings" section; CLAUDE.md +4 gotchas (Earthdata/RGI access, GLO-30 withheld tiles, OptiX crash,
  8K-CPU-denoise reconcile); new INVENTORY.md (storage map).

**Status:** all crop-verified; the full-planet z0–8 rebuild is running on the float32 path (~2.6 GB,
past the prior OOM point). **On-globe 8765 verification is the last open step.** Relaunch (skips cached
head stages, resumes at composite): `GDAL_CACHEMAX=512 python -m pipeline.tile.shade_planet --out
data/work/planet_tiles --tiles`. When checking if it's running, filter on `comm==python` — a bare
`pgrep -f shade_planet` self-matches the launch shell and false-aborts. After tiling it swaps
`tiles_new`→`tiles` (old kept as `tiles_old`); verify via `cd data/work/planet_tiles && python3 -m
http.server 8765`.

### 2026-07-14 (overnight) — First full planet tile pyramid: snow + glaciers, z0–8, served & verified

**`pipeline/tile/tile_planet.py`** shades the non-Antarctic planet as **194 RAM-safe horizontal
cell-strips** (grouped under an 80 Mpx budget — 6-cell strips at the equator down to 1-cell at high
latitudes where Mercator stretches), each via `shade.py` with a **single global z-factor** (20.0 ≈ lat 41;
`--zfactor` added to shade.py) so the hillshade is seamless across strips, and **SVF off**
(`--knob svf_strength=0` — per-block SVF min/max normalisation would seam). Strips are `-tap` pixel-aligned,
so the VRT mosaic is seamless. Resumable + fault-tolerant (**0/194 failed**); a cross-strip seam test
(Alps + central-Europe strips) confirmed the join is invisible.

**Mosaic → tiles.** VRT mosaic 131072×93009 RGBA (alpha for the Antarctica/pole gaps), 8.2 GB of strips.
Materialised to a tiled GTiff + overviews first (tiling the 194-source VRT directly re-reads every block
per low-zoom tile — far too slow), then `gdal raster tile --tile-size 512 --skip-blank` → **z0–8, 62,177
tiles, 13 GB** at `data/work/planet_tiles/tiles/{z}/{x}/{y}.png`. Globe page: `data/work/planet_tiles/index.html`
(MapLibre v5 globe, 512px@2x). **Serve:** `cd data/work/planet_tiles && python3 -m http.server 8765`.
**Verified** on 8765 (whole-planet mosaic + Alps z5 tile): seamless across strips, global persistence+ramp
snow, RGI glaciers crisp (Greenland/Arctic/Himalaya/Andes/Alps), full bathymetry.

> **`tile_planet.py` DELETED 2026-07-16.** Recover with
> `git show a7b7223:pipeline/tile/tile_planet.py` — a7b7223 is an ancestor of main, so the copy is
> permanent and byte-identical to what was removed. This entry is now the record; the file was not.
>
> **Why it went, beyond being superseded** — the reasons are the transferable part:
> - **A retired path kept in production aims at production.** Both scripts defaulted `--out` to
>   `data/work/planet_tiles`, so `tile_planet --tiles` would re-shade 194 strips for hours, then hit
>   `if not planet_tif.exists()` — silently **skipping its own mosaic** because the *good* verified
>   `planet_rgb.tif` was sitting there — and cut tiles **straight into the live `tiles/`** with
>   `--resume`, which *skips existing tiles*. Result: a hybrid of new and pre-Caspian tiles with **no
>   `tiles_old` rollback**. It predates every safety mechanism that replaced it (`.done`, `is_stale`,
>   stage-into-`tiles_new`-then-swap). It still parsed, and `shade.py` still exposed the `--zfactor` and
>   `svf_strength=0` it shelled out to — so it **ran**. Dead code that still runs and still points at the
>   live outputs is not clutter; it is a loaded gun.
> - **It had stopped being a faithful record — the thing it was being kept for.** It shelled out to
>   `shade.py`, which moved underneath it: LUT ramps replaced color-relief, lake depth arrived,
>   `WATER_RGB` changed, float32 replaced float64. Running it would reproduce **neither** the strip
>   output documented above **nor** the current look — only a chimera of today's palette with the
>   retired z=20/no-SVF geometry. Its own line 32 already admitted the drift ("safe for the float64
>   composite"). The experiments audit's bar for keeping things is that *a **working** experiment is the
>   record of a decision*; a script whose dependencies have drifted under it cannot reproduce what it
>   records, so it fails that bar even though it is not "broken".
> - **Retirement hygiene, stated generally:** when a path is superseded, *delete it or move it out of
>   the production package the same day*. Prose calling it "retired" (PLAN, INVENTORY, and
>   `shade_planet.py`'s own docstring all did) does not disarm an entry point. git is the archive.

**First-pass caveats — refinements, not blockers:**
1. Faint **vertical lines in deep ocean** = lon-adjacent strip boundaries; `gdaldem hillshade --compute_edges`
   extrapolates each strip's shared edge ~1px differently. Fix: shade strips with a small overlap and crop,
   or one global hillshade (windowed composite).
2. **Single global z-factor** over-exaggerates the tropics and flattens high latitudes vs the hero's
   per-latitude 15×. Fix: per-row/banded z-factor (a custom hillshade) — the real seamless-per-latitude answer.
3. **SVF off** → valley shadows subtler than the heroes. Fix: compute SVF globally, slice per strip.
4. Antarctica deferred; Greenland interior renders flat white (persistence=1 over smooth ice).

**Not yet:** PMTiles packaging (Phase 4); the three seamless refinements above; tuning against the on-globe look.

### 2026-07-14 — Snow integrated into shade.py; RGI 7.0 glacier union added and verified

**shade.py integration.** SP + latitude ramp are now production: new `pipeline/render/snow.py`
(`warp_persistence` → `snow_alpha` with the per-row latitude ramp), `shade.py`'s WorldCover class-70
branch removed, `composite()` soft-blends shaded `SNOW_RGB` over land by the alpha. pyright-clean;
full-res Alps in 16 s reproduces the prototype.

**RGI glacier union.** RGI 7.0 (NSIDC-0770 v7) has **no CMR granules** and its NSIDC data pool needs
interactive-OAuth (a token-only earthaccess session is bounced to the login page *even after authorizing
`nsidc-daacdata`*), so we fetch from **UNESCO's open IHP-WINS re-host** (`pipeline/acquire/download_rgi.py`:
CKAN `package_search` → 18 GTN-G region shapefiles, region 19 Antarctic skipped, merged/reprojected to
`data/raw/rgi/rgi7_g_3857.gpkg`, **271,789 glaciers**). `snow.rasterize_glaciers` burns them onto the
Mercator grid; `shade.py` unions `alpha = max(persistence_alpha, glacier)` → crisp permanent ice over the
soft persistence snow. Graceful when RGI is absent (returns None → persistence-only). **Verified:** Alps
(47 k glacier px, sharper massif cores) and Iceland (829 k px — Vatnajökull/Langjökull/Hofsjökull/Mýrdalsjökull
render crisp and bright, distinct from the softer seasonal snow).

**Data-access learnings (July 2026).** A NASA Earthdata bearer token (`EARTHDATA_TOKEN`, gitignored `.env`,
~60-day) authenticates **CMR granule** downloads (NSIDC-0791 via `earthaccess`) but **not** the NSIDC file
pool's OAuth. RGI isn't granule-searchable at all; the open IHP-WINS CKAN mirror is the reliable programmatic
source. `earthaccess 0.18` added as a dep.

**Docs updated:** ATTRIBUTIONS (NSIDC-0791 public-domain + RGI 7.0 CC-BY 4.0, with attribution strings),
both pipeline `.mmd` diagrams (snow sources + the tile path, marked in-progress), `docs/pipeline.md`
(a Phase-2 tile-pipeline section).

**Still open for the tiles:** the seamless **full-planet shade** (single vs per-latitude z-factor across
blocks) and windowing; tiling → PMTiles. See the globe-build note below/next.

### 2026-07-13 (night) — Snow source reworked: NSIDC-0791 persistence + latitude-ramped soft alpha (replaces WorldCover class 70)

**Why.** The 5-region stress test (one global shade knob set) exposed that WorldCover class 70 is *permanent ice
only*, so mid/high-latitude ranges render bare. The heroes had the identical gap (Norway 0.37 %, Argentina 0.35 %
snow) — a deliberate "eternal snow" editorial stance (`snow_mask.py`), only glaring now that we render high-latitude
mountains as tiles; Nepal/South-Asia tile validation hid it (subtropics, where permanent ice ≈ the visible snowline).
Rohan's requirement: snow that "closely resembles reality," not an estimate. Snow is seasonal, so "reality" = an
observed *climatology*, not a snapshot or a modeled elevation×latitude snowline.

**Decision.** Snow = **NSIDC-0791** (MODIS/Terra Global Annual Snow-Cover Climatology, 0.01°, WY2001–2023), variable
`snow_persistence_climatology` (packed uint16 × 1e-4 → 0..1 fraction; 65535 = fill). Persistence → **soft alpha**
(smoothstep) so margins fade and snow still takes the hillshade (never flat white). A single global persistence
cutoff traded Alps (want ~0.40) against the boreal (Scandinavia floods at 0.40, right at 0.60) — the same
latitude-regime tension as the z-factor. Resolved with a **per-pixel latitude ramp**: low = 0.40 at |lat| ≤ 45° →
0.60 at |lat| ≥ 63° (linear), high = low + 0.32. One global rule, correct everywhere: Alps + Scandinavia both good
simultaneously, Sahara/Indonesia bare, Andes naturally patchy (arid). Prototype `pipeline/experiments/snow_proto.py`.

**Consequences / next.**
- Cured the stress test's "dark muddy high country" too (the darkest pixels were the highest terrain → now
  snow-capped; the remaining brown is correct mid-slope) — no separate palette rework for peaks.
- **RGI 7.0** glacier outlines to be unioned for crisp permanent ice (1 km persistence blurs glacier tongues), then
  fold SP + ramp (+ RGI) into production `pipeline/tile/shade.py`, replacing the class-70 branch.
- That integration makes `data/raw/worldcover` (114 GB) reclaimable — keep only a compact class-70 floor if RGI
  under-covers; the remaining tie is WBM void-fill for any re-fusion.
- Dataset vetting (July 2026, web-verified): NSIDC-0791 beat raw MOD10CM (pre-computed persistence, finer, gap-filled);
  HLS 30 m rejected (no product, petabyte-scale, over-resolved for z8); Copernicus global 1 km daily (new Feb-2026)
  held in reserve for the *seasonal* overlay path. RGI 7.0 = NSIDC-0770 v7, direct-download (no CMR granules).
- Access: Earthdata bearer token in gitignored `.env` (`EARTHDATA_TOKEN`, ~60-day); earthaccess 0.18 added.
  SP granule `data/raw/snow/NSIDC-0791_SP_0.01Deg_WY2001-2023_V01.0.nc` (1.6 GB).

### 2026-07-13 — First MapLibre globe: Tier-2 stack validated end-to-end (region-first)

Built the first working globe over our z8 tiles — the full chain **shade → tile → MapLibre globe** — on a
South Asia region (6 cells, 70–100°E / 20–40°N: N India, Himalaya, Tibet, Myanmar), to de-risk the whole
stack before a full-planet build. **Judge the z8 look on the sphere here — this is what the z8-vs-z10 call was
waiting on.** Reopen: `python -m http.server 8765` in the tiles dir, open `localhost:8765` (scratchpad artifact,
regenerable via the commands below).

- **`pipeline/tile/shade.py`** (new, production) — shades a set of chunks into ONE seamless Web Mercator RGB.
  Reprojects each chunk's height+masks to a **WebMercatorQuad-aligned 3857 grid** (`gdalwarp -tap -tr 305.7483`,
  which snaps to the z8 tile grid because 20037508.34 = 65536 × 305.7483), VRT-mosaics them, then shades the
  **mosaic once** (color-relief × hillshade × SVF, mask-composited) so there are **no chunk-edge seams** (shading
  per-chunk would seam at the hillshade 3×3 / SVF halo). Locked knobs (single-NW, physical 15× via
  `relief.mercator_zfactor` at the region mid-latitude, tuned composite defaults). Composite loads the whole
  region into RAM — **a planet run must window it**. ~27 s for 6 cells; pyright-clean.
- **Tiling path:** `gdal raster tile --tiling-scheme WebMercatorQuad --min-zoom 0 --max-zoom 8 region_rgb.tif
  DIR/tiles` → XYZ dir (z0–8; 571 tiles / 70 MB for the region; ~3 s). **Default tile size is 256 px — production
  wants 512 px** (still to set). gdal's default `xyz` convention matches MapLibre's raster scheme (no y-flip).
  **For local dev, serve the XYZ dir with `http.server` + a MapLibre raster source at `/tiles/{z}/{x}/{y}.png` —
  no PMTiles needed.** PMTiles is the Phase-4 single-file deploy; `pmtiles convert` only reads **MBTiles**, so the
  eventual pack path is gdal→MBTiles→`pmtiles convert` (or gdal→dir→mb-util→pmtiles).
- **The globe page** (MapLibre GL JS v5 via CDN, `projection: {type:'globe'}`, a raster XYZ source + a background
  ocean layer + `setSky` atmosphere) is a ~40-line `index.html` in scratchpad — trivial to rebuild.
- **Validated:** MapLibre globe + our shaded z8 tiles render correctly, seamless across chunks, correctly placed.
  The Tier-2 stack works on our data.
- **Caveats (all deliberate):** region-only (rest of sphere = flat ocean bg); 256 px; snow only where WorldCover
  is already on disk; the untuned grey high-country gap; single mid-lat z-factor per region (planet bands it).
- **Next:** judge z8 on the sphere → the z8-vs-z10 call; then scale to the full planet (+ global snow layer,
  512 px, latitude-band the z-factor, window the composite, PMTiles); optionally a composite-knob sweep first to
  warm the high country.
- **Uncommitted (Rohan commits):** `pipeline/tile/shade.py` + `pipeline/tile/__init__.py` (this milestone) — plus
  the still-uncommitted `pipeline/render/palette.py`, `relief.py`, `tests/test_palette.py`, `test_relief.py`,
  `pipeline/experiments/tile_chunk.py`, and `PLAN.md`.

### 2026-07-13 — Shading stage designed + first Mercator chunk vs hero; Antarctica prefetched; snow is tile-scope

Started Phase 2 step 2 (raster shading). Design decided and validated on one chunk before a global build.

- **Antarctica prefetched (data only).** All **26,450** GLO-30 land tiles now on disk (the deferred ~7,042
  Antarctic tiles added, ~55 GB — they compress small). Antarctica *fusion* stays a separate special-case
  pass: GEBCO_2026 is ice-SURFACE elevation, not bathymetry, so the fusion's no-tile→ocean rule would clamp
  it to −1 m. New `download_glo30 --tiles` + `fuse_planet --emit-missing` drive precise scattered-gap fetches.
- **Tier scope clarified — the shaded raster tiles are the visual skin for BOTH Tier 2 and Tier 3.** Tier 3 =
  the same draped tiles + a terrain-RGB *displacement* layer (elevation encoded as RGB, carries no color) +
  click-to-hero. So **snow must be visible on the tiles**, else Tier-3 fly-to shows bare peaks while the heroes
  (Tier 1, and the Tier-3 click-to-hero) show them snow-capped. → a **global snow layer is required tile-scope**,
  not merely a Tier-1 hero input.
- **Projection: shade natively in Web Mercator with a per-latitude-band z-factor** (`relief.mercator_zfactor =
  exaggeration / cos(latitude)`; `pipeline/render/relief.py`, TDD'd). Reversed an initial equal-area-then-
  reproject lean, on this reasoning: hillshade needs correct slope *aspect* (an angle), and the projection
  property that preserves angles is **conformality**, not equal-area. **Mercator IS conformal** → aspect is
  already correct; its only error is scale (`1/cos φ`, flattening relief poleward), fixed exactly by the band
  z-factor. Equal-area would distort aspect (wrong-facing slopes) *and* needs a lossy reproject before tiling.
  So Mercator-native is both **more faithful and simpler** (tiling is a pass-through, no resample). The heroes'
  per-country AEA works only because a small area is near-conformal in any projection.
- **Recipe = `gdaldem color-relief` (shared palette) × `gdaldem hillshade` × SVF, composited by mask** — ported
  from the `experiments/tile_recipe.py` prototype. New `pipeline/render/palette.py` is the **single source of
  truth** for the land/sea/snow/water ramps (bpy-free so the hero scene can import it too), TDD'd with an
  independent-oracle drift guard against the frozen hero hex (E9D9C0/E9DCC8, 8FC7C5/3A6E7D). pytest is back in.
- **First artifact — Nepal cell `e080_n20`, ~27 s** (`experiments/tile_chunk.py`, which shades one chunk and
  knob-sweeps vs a hero). The Mercator recipe **reproduces the hero family** (warm land, brown mountains, snow,
  teal water). Findings: **single-NW sun beats multidirectional** (multidir greys the high country; matches the
  hero's baked NW convention) → the `[ ]` shading checkbox's "multidirectional" is superseded; exaggeration
  ~×1.0–1.2; the one real gap is the high Himalaya/Tibet reading grey/desaturated vs the hero's warm brown,
  which the *composite* knobs (saturation/warmth/exposure) address. This **leans the raster-vs-Blender fork
  toward raster.**
- **Cost model (why tuning is cheap):** the expensive layers (reproject, color-relief, SVF, snow) are computed
  once per chunk (~30 s); hillshade re-runs per light/exaggeration (~5 s); the composite is pure numpy (~ms) —
  so a whole knob grid costs about one build. Next: sweep the composite knobs to warm the high country, then
  judge final restraint on the real MapLibre globe (not in the abstract).
- **Uncommitted (Rohan commits):** `pipeline/render/palette.py`, `pipeline/render/relief.py`,
  `tests/test_palette.py`, `tests/test_relief.py`, `pipeline/experiments/tile_chunk.py`.

### 2026-07-13 — Planet-wide fused heightfield built (Phase 2, step 1)

The first Phase-2 artifact: a seamless global land+bathymetry heightfield, the analysis-ready
input the tile pyramid is shaded and cut from. New `pipeline/fuse/fuse_planet.py` orchestrates
`fuse_heightfield.py` over the globe; `fuse_heightfield` gained `--coverage-warn`, `download_glo30`
gained `--tiles` (both leave existing paths unchanged).

- **Grid: EPSG:4326 @ 10 arcsec, chunked into 10x10-degree whole-degree cells** (3600x3600 px;
  648 global, 540 run). 4326 over 3857 because a constant-degree grid and WebMercator both scale
  ground-res by cos(lat), so 10" feeds the locked z8 ceiling 1:1 at every latitude with no polar
  oversampling — and a projection-agnostic master keeps the 3857 warp + latitude-varying hillshade
  z-factor as the *shading* stage's job. Whole-degree cells put every edge on an exact output-pixel
  boundary, so adjacent cells share bit-identical seams (the fusion mask is purely window-local, no
  neighbour lookup). Verified: 80E boundary reads seamless from the VRT, 0 nodata.
- **Memory was never the constraint** — `fuse_heightfield` is already windowed (~1.3 GB peak/process
  regardless of extent). Chunking buys parallelism, resume, and per-cell coverage, not RAM. Measured:
  43 s/dense-land cell, 12 workers ~9 GiB aggregate RSS, whole sweep ~15 min (the earlier "overnight"
  guess was wrong — dominated by ocean/sparse cells that fuse in ~5 s). CPU-bound at 12-wide, not
  RAM-bound; ulimit -n on this box is 524288 so the flat-VRT FD concern was moot.
- **The coverage oracle (the reason fuse_planet exists).** At fusion time an un-downloaded 1x1 land
  cell (dem=-9999, wbm=255) is pixel-identical to open ocean and `fuse_heightfield` routes it to
  min(gebco,-1) — silently flooding real land as sea, uncounted by its in-window gap check. Only
  `tileList.txt` (the AWS land index) distinguishes the two, so `fuse_planet` asserts every listed
  tile intersecting a land cell is on disk *before* fusing, and fails loudly (naming cell + missing
  keys) otherwise. `--emit-missing` prints the exact gap list for `download_glo30 --tiles`. Verified:
  deep-interior land (Kazakhstan/Sahara/Congo/Australia/Tibet) all 100% land, no flooding.
- **Antarctica deferred** (`--skip-south -60`), consistent with PLAN's special-case stance. It was
  92% of the missing tiles (7,044 of 7,659); deferring shrank the download to 615 tiles (~14 GB,
  ~2 min) from ~180 GB. Cost: the WebMercator basemap's southern cap (-60..-85, which Mercator does
  show) is blank until a later Antarctica pass. GEBCO_2026 is ice-SURFACE elevation, so a proper
  Antarctica needs its own GLO-30 ice tiles (not a bathymetry clamp) — a reason it's its own step.
- **Output as per-chunk GTiffs + VRTs, not one BigTIFF** — parallel writes/overviews/resume, and the
  tiler reads reduced-res through the VRT down to per-chunk overviews (z0-z4 mosaic with no global
  overview pass). Emits all three layers (heightfield/oceanmask/watermask) the shading recipe needs.
- **Uncommitted (Rohan commits):** `pipeline/fuse/fuse_planet.py` (new), `fuse_heightfield.py`,
  `pipeline/acquire/download_glo30.py`, `PLAN.md`. Outputs live in gitignored `data/`.
- **Next:** the raster shading stage — reproject 4326->3857, multidirectional hillshade (with the
  latitude z-factor) + `sky_view.py` SVF + the hero land/sea ramps, matched to the hero family.

### 2026-07-13 — Test suite + CI on the resolver layer (a bug caught on day one)
Added `pytest` (dev dep) + `tests/` covering the pure geometry/config layer — `pad_frame` (incl. the ±180 antimeridian clamp), `country_config` validation (the fail-loudly contract), `build_scope`, `resolve` (frame/aspect/size/fusion + the "no resolved frame escapes the world" invariant), and `main_part_fraction` — all on synthetic countries, **no external data**. Rendering/fusion/downloads are deliberately not unit-tested (GPU/data-bound). `.github/workflows/ci.yml` runs the fast gate on push-to-main + PRs: `uv sync` → `pyright pipeline/` → `pytest` (needs `libcairo2-dev` for pycairo). The suite earned its keep immediately — it caught a real fail-loudly bug: `build_scope` with an unknown `[scope].include` ADMIN recorded the error but then crashed with a raw `KeyError` before its clean `sys.exit`; fixed to build the admin set from valid includes only. Also cleared the one standing pyright finding (`download_cop30_void.ot_index` did `.search(...).group()` on a possibly-`None` match → rewritten to capture the key in the `findall`) so the CI baseline is green. A heavier data-dependent job (download Natural Earth, assert `--all` = 204/203/1 across the real scope) is a deliberate follow-up, not built.

### 2026-07-13 — Known latent bugs (recorded pre-compaction; UNFIXED in tree)
Two real defects surfaced this session by a data-free pytest suite on the resolver layer (the suite + a fast GitHub-Actions CI job were built and exercised — pyright + pytest — but are not committed to the tree). Both are latent (no live-operation crash), which is exactly why they're easy to forget — so they're recorded here with the known fix:
- **`pipeline/acquire/download_cop30_void.py` → `ot_index`** — `KEY_RE.search(stem).group()` dereferences an `Optional[Match]` (the sole pyright finding). Safe *today*: every `stem` comes from a `re.findall` whose pattern contains the tile key, so `search` never returns `None` — but brittle if that DEM-name pattern ever drifts. **Fix:** capture the key as a second group in the `findall` (`r"(Copernicus_DSM_10_([NS]\d\d_00_[EW]\d\d\d_00)_DEM)"`) and drop the separate `search`.
- **`pipeline/frame/country_config.py` → `build_scope`** — an unknown ADMIN in `[scope].include` (a `countries.toml` typo) raises a raw `KeyError` at `scope[slug] = by_admin[admin]` *before* the function's clean `sys.exit`, degrading the fail-loudly contract to a traceback. **Fix:** build the admin set from valid includes only — `… | {name for name in cfg["scope"]["include"] if name in by_admin}` — so the already-recorded "no such ADMIN" error reaches the exit.

### 2026-07-13 — Renamed to Terrella; `pipeline/` reorganized into a package; single-letter names purged
Three pre-Phase-2 cleanups, all on `main` (`feat/frontend` stays unmerged until Phase 3; it barely touches `pipeline/`, so the eventual merge mostly takes main's version):
- **Relief Globe → Terrella** (a *terrella* is the little model globe of the Earth that early scientists spun — Gilbert, Birkeland; picked over plain "Terra" because NASA's Terra Earth-observation satellite, whose ASTER instrument made the ASTER GDEM, is a direct search/branding collision for an elevation project). Renamed brand strings (site titles, masthead, About-page lede with a one-line etymology) + docs + `pyproject.toml`/`uv.lock`. **Not** renamed: the `maps/`/`maps-frontend/` folders, the git branch, the deploy domain — separate calls.
- **`pipeline/` is now a Python package**, grouped by phase — `acquire/ fuse/ frame/ render/ compose/`, with `batch.py` + `ot_oracle.py` at the root, `experiments/` unchanged. Stages now run as **`python -m pipeline.<sub>.<module>`** (was `python pipeline/<file>.py`); shell stages as `bash pipeline/<sub>/<script>.sh`; the Blender scene stays a file path (`--python pipeline/render/scene_build.py` — it imports only `bpy`). Sibling imports became absolute (`from pipeline.frame.country_config import …`); the two `sys.path.insert` hacks (gen_borders, ot_oracle) removed; `Path(__file__)…parent.parent` → `parents[2]` in the four movers that anchor on repo root; the three shell scripts' `$(dirname "$0")/..` → `/../..`. Blast radius stayed small because the command strings are centralized in `country_config.stage_commands()` + `batch.bootstrap()`. Also fixed `experiments/tile_recipe.py`'s import (double-broken: its earlier move into `pipeline/experiments/` had already broken its `sys.path` anchor). **Verified:** `pyright pipeline/` clean (one pre-existing `download_cop30_void.py` regex-`None` guard, left as out-of-scope), `-m` resolution + `--all` = 204/203/1, a srilanka run through the moved chain (download→mosaics→fuse→prep→snow all executed via the new invocations), and Blender loading `scene_build.py` at its new path. The full 8K render+sky_view wasn't run to completion — memory-gated by the desktop session, not the reorg.
- **Single-letter variable names purged** across all `pipeline/*.py` (readability; project-wide preference). Geo tuples included — `w,s,e,n`→`west,south,east,north`, `x,y`→`x_coord(s)/y_coord(s)`, `d/w/g`→`dem_win/wbm_win/geb_win`. Pure renames, no behavior change (the resolver's `--country`/`--all` output is byte-identical).

### 2026-07-13 — South Caucasus data void fixed: Copernicus "Public" withholds 25 tiles; filled from OpenTopography (Path A)
- **Root cause (not an oceanmask bug after all).** Armenia/Azerbaijan rendered as flat teal because Copernicus GLO-30 **DGED edition 2021** ("Public", the AWS Open Data tier this pipeline downloads) *withholds* the tiles over the South Caucasus — exactly **25 tiles** (lat 38–42, lon 43–51). Where the DEM is absent, fusion had nothing to place, so the frame read as ocean. Quantified with a fresh oracle: Armenia fused mean **282.9 m** (min −1.0, ~81% "ocean") vs the truth **1571.1 m** — the country is a highland, not a coast.
- **Fix — Path A (keyless fill), chosen over Path B (CDSE auth).** The void-filled tiles exist in OpenTopography's edition **2023_1**, served from a keyless public S3 bucket (`s3://raster/COP30/COP30_hh/` at `https://opentopography.s3.sdsc.edu`, `--no-sign-request`, plain-HTTPS-GETtable). Path A adds no credential to the pipeline and no friction to a future dataset bump; Path B (CDSE 2024_1) would have added OAuth for a 25-tile gap. New stages: `pipeline/download_cop30_void.py` (computes `withheld = OT_tile_index − AWS_tileList`, live not hardcoded, downloads to `data/raw/cop30_void/dem/`) and `pipeline/build_void_wbm.py` (OT ships no water-body mask, so synthesize one from ESA WorldCover: class 80 → lake=2, else land=0 — matches how the Caspian is already classed). `build_mosaics.sh` globs both `raw/glo30/` and `raw/cop30_void/` into the VRTs (`shopt -s nullglob`).
- **Oracle.** `pipeline/ot_oracle.py` fetches an independent reference clip via the OpenTopography REST API (`API_Key` from `.env`) and compares it to the pipeline's fusion — the tool that proved the void quantitatively (matched COP90 to the decimal). Kept as a dev-time validation oracle only: the REST API caps at 50 calls/24h and 450,000 km² per call for 30 m, so it is impractical for bulk fetch but ideal as a fusion witness.
- **Result.** Re-fused Armenia: mean 282.9 → **1571.1 m**, min −1.0 → 75.4, ocean 0%. Re-rendered the 5 affected countries (armenia 81% void, azerbaijan 66%, georgia 28%, iran/turkey corner slivers); kazakhstan/russia Caspian corners are cosmetic and deferred. The OpenTopography API key is gitignored (`.env`); their terms prohibit publicizing it.

### 2026-07-11 — Full v3 hero render sweep (COMPLETE 2026-07-13): 2 bugs found + post-sweep to-do — all resolved
**Status 2026-07-13 — all items below closed:** snow_mask OOM fixed (streamed via `gdalwarp` with a warp-memory cap, `snow_mask.py`), Russia + Canada re-rendered; South Caucasus oceanmask fixed via the void-fill migration (OpenTopography 2023_1 tiles for the 25 withheld tiles + synthesized WBM — see the 2026-07-13 entry), Armenia/Azerbaijan re-rendered clean; usa CONUS verified; assets (variants/borders/manifest) regenerated. Phase 1 closed.
Full v3 re-render of all 201 prepped countries (`batch.py --through render --force`, launched
2026-07-10 ~22:00), watched by a self-firing ScheduleWakeup loop + `~/render_watch.sh` logger +
`~/hero_montage.py` visual QA of every batch. Interrupted at 147/201 by an OOM at russia; **resumed**
via `batch.py --through render --only <54 remaining> --force` (russia+canada excluded — their cached
prep is absent so the OOM-prone stage is skipped). On completion the 201 prepped countries have v3
heroes; the items below are **outstanding, to handle after the sweep**:
- **BUG — snow_mask OOM on continent-scale frames.** russia + canada both die at stage 4 (`snow_mask.py`)
  loading their huge WorldCover mask (~2542 tiles) into one ~29 GB array on the 29 GB box (russia's
  killed the runner+terminal — shared cgroup). FIX: memory-bound `snow_mask.py`'s WorldCover reads
  (tile/stream the window) for huge high-lat frames; then re-prep + re-render russia + canada. Their
  download/fuse/render_prep are fine (russia's download self-healed on retry) — only snow_mask OOMs.
- **BUG — South Caucasus oceanmask over-marks water.** armenia (84% ocean) + azerbaijan (76%) render
  mostly flat featureless teal (land jammed in a corner). Confined to those two: georgia (37% = real
  Black Sea) and kazakhstan (Caspian) both render CLEAN. FIX: correct the oceanmask for armenia +
  azerbaijan, re-render. (Prep/data bug — the terrain itself renders fine.)
- **NOTE — ecuador framing.** Sea-heavy frame (Galápagos in-frame; coherent render *with* bathymetry,
  NOT the oceanmask bug) pushes the mainland to the edge — optional framing revisit, low priority.
- **VERIFY — usa** antimeridian CONUS render looks right (Rohan's request); check at/after completion.
- **VALIDATED:** antimeridian handling works end-to-end — fiji + newzealand render correctly, usa in
  the resume batch. ~197 of 201 heroes clean on visual QA (only armenia/azerbaijan broken).
- **THEN — post-render asset workflow** for the good heroes: `pipeline/hero_variants.py` →
  `pipeline/gen_borders.py` → `web/scripts/gen_manifest.py` → `pnpm build` (Phase 3, populates gallery/
  detail/borders for all countries).

### 2026-07-10 — Phase 3 begins: Tier 1 gallery shipped (Astro 7, `feat/frontend`)

Migrated here from PLAN.md on 2026-07-16 — these are shipped architecture decisions, not forward plan.
An Astro 7 static site under `web/` (git worktree `../maps-frontend`, merge to `main` later): responsive
gallery of country heroes, per-country detail pages, About page — all data-driven so they fill in as
renders complete.

- **Astro 7 + pnpm.** Self-hosted **Fraunces** display serif via the stable Fonts API (`_astro/fonts`,
  **no runtime external requests**); system sans + mono utility face. Component hierarchy: `Base` (shell +
  fonts + the floating persistent border toggle) → `Masthead` (eyebrow + heading + optional back link +
  legend, per-page via props/slots) → `Legend` (the hypsometric ramp — the signature element). Design
  tokens live in `src/styles/global.css`, moved out of a component `<style is:global>` for reliable CSS HMR.
- **Assets are external, never bundled** — the rule that keeps `dist` small. Hero WebP + border PNGs live
  in the render store: a dev-only Vite middleware maps `/heroes/*` → `blender/renders/variants/`; in prod
  nginx serves the same path. The build emits only HTML/CSS/JS referencing `/heroes/…`, so **tens of GB are
  never copied into `dist`**.
- **Manifest bridge:** `gen_manifest.py` reads `country_config` + scans the variant store → `countries.json`
  (name, continent, aspect, variant sizes, `hasBorder`). Re-run after each asset pass. Operational command
  chain lives in `docs/pipeline.md` § From heroes to the website — **not** in PLAN, where a stale copy
  rotted against moved paths (`pipeline/hero_variants.py`, `web/scripts/`) before being deleted 2026-07-16.
- **Borders** are drawn by `gen_borders.py` from prep outputs only (reusing `overlay_borders`' AEA→pixel
  mapping), independent of the render — which is what lets the gallery toggle them.
- **Responsive: two width tiers.** Browse grid `min(2200px, 94vw)` with column-*width*-driven masonry
  (~6 cols at 2K → 1 on mobile); content pages `min(1500px, 92vw)`; prose kept to a readable measure.
  **CSS gotcha worth keeping:** scoped component selectors must not collide with the shared
  `.legend`/`.card` — Astro's `figure[data-astro-cid]` **outspecifies** a global `.legend`, so scope to
  `.card figure` / `.stage figure` instead.

### 2026-07-10 — Phase 2 step B prototype: raster recipe viable; "quieter tiles" reframed
- **Result (`experiments/tile_recipe.py`, Switzerland):** gdaldem color-relief × gdaldem hillshade
  (`-z 15`, exaggeration read from frame.json) × our `horizon_svf`, reusing the hero's exact ramps +
  WATER_RGBA/SNOW_RGBA under the Standard view transform, reproduces the hero's structure and palette;
  inland lakes/rivers and snow composite in; ~20 s/run. The raster arm is viable (the raster-vs-Blender
  -tile open question leans raster), and reusing `sky_view.py` verbatim settles the SVF engine (our own
  code, not WBT/RVT). Runs on the AEA `render_1s` grid so output overlays 1:1 on the Cycles hero.
- **"Tune quieter than the heroes" → "match the hero family; decide final restraint in-context."** The
  old note borrowed a real convention (relief recedes under overlays, Huffman) that applies weakly here:
  the relief *is* the brand, typography is minimal, and borders already read on the dramatic heroes — so
  a muted globe would only break Tier 2↔Tier 3 (globe↔hero) continuity. Surviving tile-only constraints
  are high-zoom 30 m noise (fix: shelved resolution-bumping) and border/label legibility headroom — both
  argue for *slight* restraint, not flattening. "How quiet" is only fairly judged against the actual
  overlays, so decide it on the MapLibre globe with borders at several zooms, not a static side-by-side.

### 2026-07-10 — Phase 2 step A: tiling toolchain locked (WhiteboxTools dropped)
- **Locked stack:** GDAL (gdaldem hillshade/color-relief + `gdal raster tile`) + our own
  `pipeline/sky_view.py` for the SVF/openness term + `pmtiles` for packaging. `pmtiles` 1.31.0 is the
  sole vendored binary (pinned github release, installed by `pipeline/install_geotools.sh` into
  gitignored `tools/`; no brew, no `.venv` touch → reproduces in the rohome container and is safe to
  run during a live prep sweep).
- **WhiteboxTools dropped.** It was briefly installed (v2.4.0, whiteboxgeo prebuilt) as the SVF
  comparison arm, then removed the same day on two findings: (1) its repo is now **legacy** — the
  README redirects to a next-gen rewrite (`whitebox_next_gen`, Rust, no releases/binaries yet, and
  GDAL-free so no architectural fit for us); (2) the community SVF specialist is **RVT** (`rvt-py`
  2.2.3, 2025-07-04 — SVF / anisotropic SVF / openness; built on numpy/scipy/gdal/rasterio), which
  supersedes WBT for the one job it had. Decisive: our own `sky_view.py` is **already the production
  openness pass** burned into every hero, so reusing it for tiles makes them palette-consistent by
  construction. RVT is kept only as an **optional one-off numeric oracle** (needs Python <3.12; our
  venv is 3.12.10, so a throwaway 3.11 env), never a pipeline dependency.
- **GDAL pinned to 3.13.1** (latest; 2026-06-05) as the production target, delivered via the official
  OSGeo GDAL container (reproducible on dev + rohome). apt on Ubuntu 26.04 tops out at 3.12.2, and
  3.13 brings nothing our recipe needs over 3.12 (its tiling headline is the gdal2tiles→`gdal raster
  tile` default-remap of a path we already call directly) — so the step-B prototype runs on the box's
  3.12.2 and we adopt 3.13.1 at containerization. The prep sweep is unaffected either way: the venv's
  rasterio bundles its own GDAL (3.12.1) rather than linking the system `gdal-bin`.
- **Deferred:** `tippecanoe` (vector borders/coastlines → vector tiles) — a from-source build needed
  only when the vector-tile step lands, not for the raster recipe.

### 2026-07-10 — Overnight render sweep ran to 123/204, then STOPPED to fix hero quality; pipeline hardened

- **The sweep.** `batch.py --through render --clean` ran ~14 h and produced **123 heroes** before Rohan
  reviewed them and stopped it to re-assess (next entry). Single-runner throughput ~9–10 heroes/h
  (blended, incl. giant-download lulls); GPU duty cycle only ~9 % (renders are 1–4 min; most wall-clock
  is downloads — the prep-ahead redesign would reclaim this). Thermals a non-issue: GPU peaked 61 °C even
  at 98 % render load; the CPU briefly hits its 95 °C Tjmax cap during the CPU-OIDN denoise of each 8K
  frame (self-throttling, safe — a lone 95 °C read is normal, only *sustained* would be a fault). A 60 s
  GPU temp logger + a 30-min watchdog loop ran throughout (both stopped now).
- **Bug #1 — two-runner collision (Claude's error).** Rohan launched the sweep; then asked Claude to
  run+monitor it and Claude launched a **second** runner without checking → two `batch.py` raced a→z,
  `--clean`-pruning each other's `data/work/<slug>` (⇒ `heightfield.tmp: No such file` fuse errors) and
  double-downloading tiles (~30 % download failures). Killed the duplicate ~1 h in. Most of the run's ~53
  failure log-lines (27 distinct countries) trace to that hour; recoverable on re-run. **Lesson: a
  single-instance guard is needed** (the `flock` in the prep-ahead design); check
  `pgrep -af pipeline/batch.py` before launching.
- **Bug #2 — snow_mask non-idempotent (FIXED, uncommitted).** `snow_mask.py` `sys.exit`'d non-zero when
  its output existed instead of skip-exit-0 like fuse/render_prep → every already-prepped country FAIL@4'd
  and never rendered. Now prints "… exists — skipping" and returns 0.
- **Bug #3 — silent partial-data renders (GUARDED, uncommitted).** Georgia shipped with a flat nodata
  block (missing GLO-30 tiles, likely corrupted when its Caucasus tiles were fetched during the
  collision) and the runner never noticed. Added a **coverage-validation guard** to `fuse_heightfield`:
  counts land px with no GLO-30 tile (`DEM==nodata & WBM==land`) and `sys.exit`'s above 1 % → the re-run
  auto-flags + re-downloads these instead of rendering garbage.
- **Antimeridian snow_mask edge (deferred).** fiji + newzealand (+ russia, unreached) FAIL@4 — frames
  at/near 180°E hit a WorldCover edge case. A small AM snow_mask fix is needed later; those 3 (plus
  kiribati) stay unrendered until then.
- **Broken heroes on disk:** brazil + cambodia are flat/empty (collision fuse-race casualties;
  relief-detail 4.1 vs 70 median — the *only* two empties, per a full audit). The forced re-run redoes them.

### 2026-07-10 — Hero look v3: shallow-sea ramp + sky-view shading; full re-run tonight

Rohan reviewed the 123 heroes and flagged: shallow shelf seas render as white "ice" (Denmark/Ireland/
Kuwait/Netherlands/Estonia/Malaysia/El Salvador); flat countries look basic (Paraguay/Qatar); atoll
nations show ~no land (Maldives/Palau/Marshall Is./Micronesia/Mauritius/Cape Verde); Georgia/Iran partial
gaps; Monaco/Nauru banding; brazil/cambodia empty. Decisions (each validated with rendered/post-processed
demos before adopting):

- **Sea ramp → "smooth-C" (6-stop), uncommitted.** The shallowest `SEA_STOPS` stop was C6E4E2 (near-white)
  so shelf seas read as ice. New 6-stop ramp from **8FC7C5** (a real teal) with a smooth shelf→deep
  gradient, set in `scene_build.SEA_STOPS` (linear values from sRGB). Fixes the ice look AND turns
  Maldives' lagoons teal. **Supersedes the locked sea-ramp constant.** (Candidate "D" was stronger/moodier
  but needed the whole ramp re-toned; Rohan chose C.)
- **Shading → post-composite horizon sky-view-factor, burn-only. New file `pipeline/sky_view.py`,
  uncommitted.** Horizon openness (16 dir) from `heightfield_aea`, computed at reduced res + upsampled
  (~20–30 s CPU, overlaps the GPU render), **burn-only**: darkens genuinely-occluded valleys above a
  threshold and leaves open ground at rendered brightness — so flat countries gain drainage/valley depth
  with no dimming and no "desert" wash (dodge-and-burn was rejected: brightening the dominant open flats
  read as desert). Land only (ocean mask). Wired into `batch.py`'s render stage: shades the `.tmp.png`
  before the atomic promote ⇒ applied **exactly once**, never compounds; a sky_view failure fails the
  country cleanly. Strength **~0.38** (tunable). **Chosen over per-country adaptive exaggeration** (breaks
  the one-consistent-vertical-scale look) **and over in-Blender Cycles AO** (dims the whole scene, grainy
  "dirt" at ridge bases even at tight AO distance, +2.5 min/render; SVF is free by comparison).
- **Shelf edge: kept, equal exaggeration.** The shelf→deep abruptness is real geography (continental
  slope) plus the 15× exaggeration applied equally to bathymetry; Rohan chose to keep it ("truest picture
  even if shocking"). No sea-exaggeration change.
- **Maldives / atolls: accept as mostly ocean.** Tested 1″ + max-resampling (added `--land-resampling` to
  fuse; **default unchanged = average, status quo**) — **no gain** (0.46 %→0.46 % land; frame is 99.9 %
  ocean). Data reality; the stronger sea ramp handles the look.
- **THE RE-RUN (do this next):** `python pipeline/batch.py --through render --force` — **no `--clean`**
  (keep prep for fast iteration) and **`--force`** so all 204 re-render with the new ramp + SVF (the sea
  change is baked in Blender ⇒ every hero must re-render; prep re-fuses from the **cached raw GLO-30
  tiles** — no re-download except gaps/remaining countries). **SINGLE RUNNER ONLY** (`pgrep` first). The
  coverage guard + snow_mask fix + single runner prevent the earlier damage. fiji/nz/russia + kiribati
  stay unrendered pending the AM snow_mask fix. Expect a full overnight (~re-prep all 123 done + download
  the ~81 remaining + render all + SVF).
- **Raw-render preservation (uncommitted `batch.py`).** The render stage now writes the raw Cycles frame to
  `blender/renders/heroes/raw/<slug>.png` (kept) and sky_view derives the shaded `heroes/<slug>.png` as a
  separate file. A cached raw + no `--force` **skips the GPU and re-shades only**, so future post tweaks
  (sky_view strength/threshold, border overlay, grading) re-composite over every hero in minutes with no
  re-render — provided `data/work/<slug>/render/` (heightfield+oceanmask) is kept, i.e. still **no
  `--clean`**. ~12 GB for 203 8K raws vs 556 GB of tiles. Landed *before* the render pass so tonight's run
  captures the raws (retrofitting would mean re-rendering to recover discarded raws).
- **Workflow split (2026-07-10):** prep-all now (`--through prep`, running — dry-run: 179 would-run, 24
  skip-done, only Kiribati skipped; russia/usa/nz/fiji now resolve via frame overrides and are attempted —
  their snow_mask outcome is the open question the prep run answers), then a GPU-only `--through render
  --force` pass tonight (prep stages skip in seconds). GPU has large thermal headroom (61 °C peak vs ~83 °C
  throttle) — run renders back-to-back, no throttle; steady load is gentler than thermal cycling.
- **Antimeridian/polar snow_mask fix (uncommitted `snow_mask.py`).** Root-caused the canada/nz/fiji
  stage-4 failures: `snow_mask` derived its WorldCover tile window from `transform_bounds` of the AEA
  raster, which for a large high-latitude or antimeridian frame fans past the pole/dateline and returns a
  wrapped window (west ≥ east) → `tiles_for_bounds` selects 0 tiles → false "every tile absent" abort. Fix:
  keep `transform_bounds` as primary (byte-identical for normal countries — verified chile 135, cambodia 9,
  chad 35, bulgaria 6 unchanged), fall back to render_prep's `frame_lonlat` **only** when the window wraps
  (canada 0→594, nz→42, fiji→8). Self-contained in `snow_mask.py`, so russia/usa are auto-handled when the
  running prep reaches them, and canada/nz/fiji regenerate their snowmask during tonight's `--force` render.
  Resolves the deferred antimeridian snow_mask item; russia/usa/nz/fiji can now render.
- **Uncommitted (Rohan commits):** `snow_mask.py`, `fuse_heightfield.py`, `scene_build.py`, `batch.py`,
  `pipeline/sky_view.py` (new), `PLAN.md`.

### 2026-07-09 — Hero presentation explored (spike): no single universal design; geography-conditional; margins read flat

- **Question:** beyond the rectangular framed hero, how should a country be *presented* in
  the gallery? Ran as post-processes on existing heroes (Sri Lanka = coastal, Switzerland =
  landlocked) reusing `overlay_borders` geometry — no look change to the renders, no
  locked-constant touch.
- **Ruled out (incoherent / artefacts):** (1) country-shape cutout with a faded **sea ring**
  into a cream page — three unrelated zones (land → teal ring → paper); water doesn't dissolve
  into cream. (2) hard-edged coastal **rim** of sea — a uniform band that reads as an outline,
  "juts." (3) **synthesising** a generous ocean from the tight render — real bathymetry ends at
  the render frame, so beyond it is invented → visible rectangle/glow seams (the frame boundary
  is literally visible).
- **What works:** (a) **cutout-cream** — country land silhouette + **drop shadow** on a cream
  vignette; the shadow is essential (grounds it; without it the silhouette floats). Coherent,
  honest, neighbour-free; works for island *and* landlocked. (b) **real generous ocean** —
  re-render at a bigger frame so real GEBCO bathymetry fills the sea edge-to-edge with an ocean
  vignette; coherent and on-brand. Demoed: Sri Lanka at 35 % pad, 3″ fusion (adequate — the
  97 m/px render is coarser than the 3″ source), rendered 2:24; generous frames pull in
  **neighbours** (India across the Palk Strait).
- **The trilemma (why no universal rule):** *consistent across all countries* / *coherent (no
  land–sea–cream salad)* / *only the target country visible* cannot all hold at once.
  cutout-cream = consistent + coherent + neighbour-free + real-data but **no sea**; real-context
  = consistent + coherent but **neighbours dominate** (a landlocked country is lost in neighbour
  terrain); everyone-an-island (mask all neighbour land → sea) = consistent + coherent +
  neighbour-free but the sea is synthetic and **fictional for landlocked** (Switzerland floating
  in an ocean); real generous ocean = gorgeous + coherent + real but only honest for **true
  islands** (landlocked have no sea) → cannot be universal.
- **Conclusion (Rohan, deliberately not finalised):** no single fixed design — presentation is
  **geography-conditional**: cutout-cream suits continental/landlocked; real-ocean suits
  genuinely water-surrounded (island) countries.
- **Central open gap:** the two treatments fit the *extremes* (pure island, pure landlocked);
  **most countries are BOTH coastal and bordered** (France, USA, India, Brazil) and the split
  doesn't classify them. Needs a tier rule (coastline-fraction of perimeter? land-neighbour
  count? % sea in frame?).
- **Second open problem (Rohan):** **every** treatment reads **flat at the country margin** —
  the boundary transition lacks depth. Unsolved; wants its own pass (edge relief / lighting /
  gradient?).
- **Cost is not a blocker for two of three.** cutout-cream and everyone-island are **pure
  post-processes of the existing tight renders** — no re-render, no frame change → the current
  tight-frame prep sweep is correct for them. Only the island real-ocean tier needs bigger
  frames; of the three cost paths (A synthetic = fake; B full generous re-renders ≈ 2–3× GPU +
  storage; C low-res sea pass + high-res land composite ≈ +10–20 %), **C** is the sweet spot if
  that tier is pursued.
- **Reusable machinery (for the Phase-3 revisit):** AEA→render-pixel mapping via
  `overlay_borders.render_mapping` (reads `frame.json` `ortho_scale`), validated by the coast
  oracle (< 2500 m); ocean-mask convention **0 = land, 1 = sea**; hero PNGs are opaque RGBA
  (`film_transparent` off, opaque sand world) so alpha only means something after a cut;
  neighbour removal is an NE-polygon mask (keep real sea, drop neighbour land); sea shares the
  land's 15× vertical exaggeration → dramatic submarine relief (a knob if calmer sea is wanted —
  Rohan: exaggeration is fine).
- **Housekeeping:** throwaway spike scripts (`pipeline/experiments/hero_*_spike.py`) and demo
  outputs removed; the reusable core stays in `overlay_borders.py`; `CUTOUT.md` graduated into
  this entry. **Decided at:** Phase 3 gallery/globe design, once the rectangular heroes exist to
  judge against — does not touch the locked constants.

### 2026-07-09 — Antimeridian: no wrap-math; 4 mainland overrides + Kiribati deferred

- **Premise-check beat the scary version.** True antimeridian wrap-math (W>E frames, shifted
  source VRTs across ±180, touching 4 pipeline files) looked inevitable. A cos-lat-area part
  audit of the 5 marked countries showed the land concentrates on ONE side of 180 for four:
  Russia 99.3% at 19.6-180E, US 100% western (CONUS=82.9%), NZ 99.7% at 166-179E, Fiji 95.8%
  at 174.6-180E. So each reduces to a **non-crossing mainland/main-island frame override** —
  the existing France/Chile mechanism, zero wrap-math. Dropped trans-180 remainders (Chukotka
  sliver, Alaska/Hawaii, Chathams, Lau group) recorded in each `notes`; consistent with the
  mainland-only far-flung policy.
- **Kiribati deferred** (decided with Rohan): genuinely split 32% Gilberts (east, capital
  Tarawa) / 68% Phoenix+Line (west, largest atoll Kiritimati), no dominant side. No
  non-crossing frame represents it and a true 40deg crosser is mostly empty ocean — a
  special-case like Antarctica, kept `status="antimeridian"` (in-scope but skipped), no hero.
- **Code: two tiny changes.** `frame_country.pad_frame` now clamps to [-180,180]x[-90,90]
  (a no-op off the antimeridian; **also fixes Tuvalu**, whose 179.9E island padded to 180.1
  and failed the GEBCO window). `country_config.resolve` skips the "raw bbox spans 180 -> need
  a status marker" abort when a `frame` override is present (the override is authoritative).
- **Verified:** the 4 resolve to frames with E<=180, GEBCO covers, GLO-30 fetches on demand
  (Russia 4919 tiles — the sweep's biggest, `--clean` reclaims it); `--all` now 203 resolved /
  1 antimeridian-skipped (was 199/5); **no** resolved frame escapes [-180,180]x[-90,90];
  nepal/switzerland/france/india/chile frames byte-identical (clamp is inert elsewhere).

### 2026-07-09 — Batch runner: crash-safe orchestration + dynamic OOM defense

- **`pipeline/batch.py`** drives the full pipeline across the in-scope countries, reusing
  `country_config` (scope, frames, `stage_commands`). Each stage runs as an isolated
  subprocess (a Blender segfault/OOM kills only that process), sequential (the render is
  GPU-bound). `--through prep` (default) runs download→snow; `--through render` adds the
  render. Default prep so a bare run can never start the ~10–13 h render sweep; `--dry-run`
  previews (204 → 5 antimeridian, 1 GEBCO/Tuvalu-past-±180°, 196 to run). `--only`/`--limit`/
  `--force`. `--clean` (render mode) prunes each country's `data/work/<slug>` + `.blend`
  once its hero lands — the disk-safety valve for a full sweep, which otherwise accretes
  ~500 GB of GLO-30 tiles + fusions on top of the 285 GB already used (hero PNGs and the
  shared raw tiles are kept). Failures → one timestamped JSONL line in
  `blender/renders/batch_failures.jsonl`, country's rest skipped, run continues; the
  end-of-run summary rosters the failed + low-mem-skipped slugs by name so a re-run is
  informed at a glance. Fail-once-then-skip is accepted (Rohan): recover by re-running the
  same command (filesystem resume).
- **Resilience to abrupt shutdown (Rohan's requirement) is the keystone.** Filesystem-resume
  is only safe if "output exists" means "output complete," so **every stage now finalizes
  atomically** — `fuse_heightfield`, `render_prep`, `snow_mask` write to `.tmp` and
  `os.replace` on success (PNG `.aux.xml` sidecar moved too); the runner renders to a
  `.tmp.png` it promotes on exit 0. (This fixed a latent CLAUDE.md violation — those stages
  wrote straight to final paths, so a kill mid-write left a partial file resume would trust.)
  `fuse_heightfield` also aligned to skip-exit-0 when complete (was a hard error), so
  "re-run all stages, each skips what it finished" is the uniform resume contract. **Verified:**
  SIGKILL mid-fusion leaves only `.tmp` (no partial final); re-run recovers byte-identical;
  deleting a snowmask and re-running re-executes only `snow_mask` (fusion skip-exit-0).
- **Dynamic OOM defense** (machine: 30 GiB): sequential; a pre-render memory gate waits
  (bounded 30 min) if `MemAvailable` < floor (default 14 GiB, `--mem-floor-gib`) then defers
  the country rather than starting a doomed render; heavy stages (fuse, render) run under a
  best-effort `systemd-run --user` cgroup `MemoryMax` (≈85 % of MemTotal, `MemorySwapMax=0`)
  so a runaway is cleanly killed, not left to thrash. **Cap enforcement verified** on the dev
  box (300 MB under a 64 MB cap → rc 137; memory controller delegated to the user manager);
  degrades to no-cap where unavailable (container). An OOM-kill (rc 137) is logged `kind:oom`
  and the country skipped — **no silent quality-degrade** (locked-look consistency); the human
  decides from the log. Runner keeps no durable in-memory state → a killed runner just re-runs.
- **Prep-ahead producer/consumer runner: designed, measured, DEFERRED — and probably permanently.**
  (Migrated here from PLAN.md on 2026-07-16; it sat as an unbuilt 25-line design in the living plan long
  after its gate passed.) `batch.py` serialises prep (stages 0–4: download/mosaic/fuse/warp/snow —
  network/CPU/disk, GPU-idle) with the render (stage 5 — GPU) per country, so the GPU idles through
  downloads. **Measured on the 2026-07-09 sweep: ~9% GPU duty cycle** — ≈15 min of rendering inside
  ~2h49m; Canada's 6376-tile download alone idled the GPU ~40 min, while renders are only ~1–4 min each.
  - **Design, if ever built.** Render is VRAM-locked to one-at-a-time (8K peaks ~11–12 GB of 12 GB), so
    *render must stay serial*; the win is overlapping prep with render (disjoint hardware). One render
    worker holds **the sole GPU lease**, draining a queue; 1–few prep workers stay N countries ahead.
    The ready queue is **implicit** — countries whose `render/`+snowmask exist but hero doesn't,
    discoverable by filesystem scan — so **resume stays filesystem-only, with no durable queue state**.
    Prep **smallest-first** (by GLO-30 tile count) so the renderer never starves behind a giant download.
    Disk bounds the queue depth N (each un-pruned work dir is up to ~4.5 GB).
  - **Safety invariants that must NOT regress** — each one is a bug this project already paid for:
    (1) **single-instance `flock`** — the 2026-07-09 two-runner collision was exactly this missing guard;
    (2) **per-country claim** (atomic `mkdir data/work/<slug>/.claim`) so no two workers share a work dir
    — this is what produced the `--clean`-vs-fuse race and its `heightfield.tmp: No such file` errors;
    (3) `--clean` stays post-render and render-worker-only; (4) atomic stage finalisation unchanged;
    (5) **RAM-aware gating** — cap concurrent memory-heavy ops (≤1 fuse) and keep the pre-render
    `MemAvailable` gate + cgroup cap, since a big fuse plus a ~12 GB render can blow past 30 GB.
  - **Why it is probably moot.** Expected win was wall-clock → `max(total_prep, total_render)` instead of
    the sum (~2–4× on download-heavy runs). Its gate was "after Phase 1 hero renders complete" — which
    passed on 2026-07-13, with the sweep already done. The **zero-complexity 90% alternative** is the
    existing phase split (`--through prep` to completion, *then* `--through render` = pure GPU), which
    suffices whenever prep may finish first. Build it only if a full re-render sweep is ever needed again.

### 2026-07-09 — Global GEBCO acquired: batch renders unblocked 6 → 198 countries

- **Why now:** a data audit via `country_config`'s own preflights found only **6 of 204**
  countries were renderable — all inside the single regional GEBCO tile
  (60–100°E/0–40°N); the other 193 failed GEBCO coverage. GLO-30 was never the blocker
  (on-demand per country). Global bathymetry was the true critical path for the whole rest
  of Phase 1. Chosen over antimeridian handling (those 5 are blocked on this same data and
  can't be render-validated without it).
- **Acquired:** GEBCO_2026 **ice-surface** global grid, 8× 90° GeoTIFF tiles (15″, Int16,
  nodata −32767), ~4 GB zip direct from CEDA
  (`dap.ceda.ac.uk/bodc/gebco/global/gebco_2026/ice_surface_elevation/geotiff/`) →
  `data/raw/gebco/gebco_2026_global.vrt` via `gdalbuildvrt`. Ice-surface not under-ice
  (relief shows the visible landscape; Greenland is a hero). TID grid deferred
  (diagnostic-only, like GLO-30's FLM). Regional tile kept as the `--gebco` regression
  reference. **Refined the plan** (which said "single translated GeoTIFF"): a VRT over the
  8 tiles matches the `dem_mosaic.vrt` convention and avoids a 7.5 GB copy.
- **Wiring:** `fuse_heightfield.py` `GEBCO` → the global VRT, plus a `--gebco PATH`
  override (default = the constant, so `country_config`'s import still resolves);
  `country_config.preflight_gebco` message now points a coverage miss at the antimeridian
  item (the only way to miss a global grid). Unblock proven: `--country japan` passes GEBCO;
  scope-wide GEBCO coverage **6 → 198/204** (remainder = antimeridian frames past ±180°).
- **Regression (Sri Lanka, all-coast, re-fused from global vs regional):** land and both
  masks **bit-identical**; ocean differs by **±1 m at ~0.02 % of pixels**. Chased to ground
  with independent oracles: the two GEBCO sources are **byte-identical where they overlap**
  (0 diffs at native res), and wrapping the regional tile in a VRT is bit-identical to
  reading it directly — so it is not a data difference and not the VRT path, but
  `Resampling.cubic_spline`'s source-structure-dependent numerics (diff count itself
  shifts 1804/1465/1299 with source tiling/extent). **Sub-visible and irrelevant:** ±1 m is
  below GEBCO's own vertical accuracy (tens of m) and invisible under a sea ramp spanning
  0→−3000 m in 4 stops. Consequence noted: the 6 held fusions came from the regional tile,
  so they differ from global by this same sub-visible ocean noise — optional one-source
  re-fusion later; India's render is approved/pinned, so no re-render is warranted.
- **Reproducibility (follow-up, same day):** GEBCO was the only dataset acquired by hand
  (an ad-hoc curl) — a fresh clone / rohome could not fuse. Closed by
  `pipeline/download_gebco.py` (mirrors download_glo30: reuses its `download_one`,
  resumable, versioned-path edition pin, 404 = naming-drift abort; fetches the 8 tiles and
  rebuilds the VRT). `country_config --country` now prints it + `download_naturalearth.sh`
  as **stage 0** (once per machine), so the printed recipe is a complete fresh-clone
  bootstrap. Folder-grouping the download scripts was considered and **deferred**: the
  cross-module flat imports (`country_config` ← download_glo30/frame_country/…) would force
  the package layout CLAUDE.md defers until the batch runner reveals the seams.

### 2026-07-09 — Hero .blend files are build artifacts, not versioned; source is canonical; prior-art audit logged

- **Decision:** stop git-versioning generated hero `.blend` scenes (`blender/*.blend` gitignored; `git rm --cached` the two tracked ones). The **one exception** kept in git is `india_hero_handbuilt_phase0.blend` — the hand-built Phase 0 scene, which no script reproduces (archival provenance of the origin recipe).
- **Why:** each `.blend` is a thin ~96K pointer file that references the heightfield/mask rasters living in gitignored `data/`, so a committed copy opens with dangling textures on a fresh clone — it is not a working artifact. It is fully regenerated by `scene_build.py` from committed constants + `frame.json` (+ data), so it is a build artifact in the same class as a rendered PNG (already gitignored). It also goes stale silently the moment a constant changes. The canonical, diffable, forkable form of a scene is `scene_build.py` itself — the script is the better open-source artifact than a binary with broken paths. If a ready-to-open scene is ever wanted for third parties, the mechanism is a *packed* `.blend` (Blender File → External Data → Pack) shipped as a GitHub Release asset, not a repo-tracked file.
- **Follow-up:** end-of-Phase-1 item added to document the regeneration/CLI path (a fresh clone reproduces any hero from source).
- **Prior-art audit (context):** GitHub + web survey of neighbours. Closest is **LuisSevillano/relievo** (bbox→Blender relief in one command; per-map, no fusion/snow/tiling/globe); also tbloch1/dsm_blend, mattf1n/Relief-Map, joewdavies/geoblender (technique automation); globe engines NASA WorldWind / openglobus / Cesium; global raster relief galleries shadedrelief.com / Natural Earth. **No project combines all-countries raytraced heroes + interactive relief globe + PMTiles static serving** — the novelty is the integration; the gap is labor/compute, not law (see ATTRIBUTIONS.md for the licensing posture). Neighbours mostly *validated* our choices by convergent evolution (dry-run preview, sun+fill two-light, TOML config, min-viable-resolution, low-pass anti-bump); two genuinely new ideas captured as spikes above (country-shape alpha cutout; gdaldem post-composite = our Phase 2 tile arm). Made-with-AI attribution + full data-license posture recorded in the new ATTRIBUTIONS.md.

### 2026-07-09 — Per-country config live: countries.toml is the scope/overrides home; long-edge resolution rule; fusion choice formalized

- **Scope (decided with Rohan): strict + curated.** NE admin-0 `ADMIN == SOVEREIGNT` (de-facto worldview) selects 208 rows; 9 excluded with reasons in config (Bir Tawil, Spratly, Scarborough Reef, Bajo Nuevo, Serranilla, Cyprus No Mans Area, Brazilian Island, S. Patagonian Ice Field; **Antarctica deferred** — special-case hero: polar projection, no WorldCover); 5 curated dependent territories included (Greenland, Faroe Islands, New Caledonia, French Polynesia, Puerto Rico) = **204 heroes**. Audit that drove the design: 62 countries over 9,000 px tall under fixed-width-7680 (Maldives 56k, Norway 25k), 37 far-flung-inflated bboxes, 6 antimeridian crossers.
- **Resolution (decided with Rohan): hero long edge 7680**, config default + per-country override (`hero_long_edge`; render_prep `--hero-long-edge`). Wide countries are a no-op by construction — replaying scene_numbers against Nepal/Switzerland frame.jsons reproduces all five numbers exactly. Sri Lanka's frame.json regenerated: only res_x/res_y changed, 7680×12498 → 4720×7680; scene_build cross-check passes. India stays pinned at 7680×7906.
- **Far-flung (decided with Rohan): whole bbox unless catastrophic** (main landmass under ~25% of a bbox axis). Five mainland frames authored in config — France, Netherlands, Norway, Portugal, Chile — as mainland-part bbox unions through the standard pad_frame math; every dropped part verified by coordinates (Easter Island, Svalbard, Azores, Caribbean municipalities, Guiana/Mayotte/Réunion…). 17 further far-flung rows flagged informational only (genuine archipelagos: Micronesia 1%, Tuvalu 1% — whole bbox is their correct frame).
- **Resolver (pipeline/country_config.py), read-only glue:** frame (override or bbox+pad), projected aspect via the frame's own AEA, warp width (long grid edge ≈ 8192), **auto fusion — 1″ iff the 3″ mosaic would upsample into the warp grid** (reproduces the India/Nepal/Switzerland history; Sri Lanka's legacy 3″/3072 QA-era grid predates the rule and would re-fuse at 1″ if ever redone), GLO-30 held-tiles preflight from tileList.txt (land-tile index ⇒ ocean cells can't count missing), GEBCO window preflight (fails loudly; global GEBCO = Phase 2 acquisition), `--emit-pin` (config/frames/<slug>.json → workdir; India's round-trips byte-identical; render_prep no-op re-verified), `--all` audit (204 rows, 0.45 s). Fail-loudly oracles *witnessed* on doctored configs: unknown keys, unresolvable names, unmarked antimeridian bbox.
- Antimeridian rows (Russia, US, NZ, Fiji, Kiribati) marked `status = "antimeridian"` and skipped loudly — their own Phase 1 item. Noted for it: **Tuvalu's padded frame crosses 180°** (pad pushes 179.9 → 180.1) without its bbox crossing; the marker list isn't the whole story.

Newest first. Each entry records what was decided, the deciding evidence, and what it would take to reopen. Constants and tunable levers live in the locked section above and in ART.md — not here.

### 2026-07-08 (late night, follow-up) — GLO-30 aux layers audited: hero mountain terrain is ~20–50% fallback-DEM fill; FLM adopted as on-demand diagnostic, not a pipeline stage

- The bucket carries, per tile: DEM + 4 aux rasters (EDM edit mask, FLM filling mask, HEM 1σ height error, WBM) + ACM/SRC KMLs + XML + quicklooks; same URL pattern (`<tile>/AUXFILES/<name>_FLM.tif`).
- FLM legend (Product Handbook i5.0, Table 7): 0 void, 1 edited, **2 native (not edited/not filled)**, 3 ASTER, 4 SRTM90, 5 SRTM30, 6 GMTED2010, 7 SRTM30plus, 8 TerraSAR-X radargrammetric, 9 AW3D30, 100+ national DEMs. EDM (Table 6): 0 void, 1 not edited, 2 infill, 3 interpolated, 4 smoothed, 5 airport, 6 raised-negative, 7 flattened, 8/9/10 ocean/lake/river, 11 shoreline, 12 morphed, 13 shifted.
- One-time audit of six money-terrain tiles (fill = 100% − native − edited): **Karakoram/K2 ~49% filled** (30% SRTM30 + 17% AW3D30), **Nanga Parbat ~48%** (46% SRTM30), Everest ~19%, Zanskar ~22%, Valais ~17%, Aletsch E ~28%. TanDEM-X radar fails exactly on steep snow/ice faces, so fill concentrates in the dramatic terrain our heroes feature.
- Verdict: no visible seams or texture anomalies in any approved render to date (India v3/v4, Switzerland, Nepal, Sri Lanka — all QA'd at 1:1), so **no action and no pipeline stage** — the risk is real but not manifest; Airbus's delta-surface blending plus our 15× shading evidently masks source boundaries at poster scale. **FLM is the first thing to fetch when a hero ever shows a smooth patch, texture seam, or implausible mountainside**; EDM is the first fetch for shoreline oddities (relevant to the known NE-vs-WBM lagoon-spit disagreement class). HEM = per-pixel trust map, third in line.

### 2026-07-08 (late night) — Snow/ice adopted as a data mask; shadow fill sun; land ramp de-whitened

- **Why:** satellite imagery shows permanent snow on the high Alps that the hero couldn't — snow is climate, not elevation (snowline ~3,000 m Alps vs ~5,500 m Himalaya), so no global elevation ramp can paint it honestly. Same-day decision window deliberately: a look change now costs 2 re-renders, after the batch ~195.
- **Dataset: ESA WorldCover 2021 v200 class 70** (10 m, Sentinel-1/2 full-year composite, frozen versioned edition, CC-BY 4.0, public S3 COGs — same provenance family as GLO-30). Full-year composite ⇒ class 70 is *permanent* snow/glacier; seasonal snowpack excluded by construction — matching the hero's editorial stance everywhere (permanent water, perennial rivers). Rejected: RGI 7.0 (year-2000 snapshot, no ice sheets), ESRI/IO annual (mutating series, Clouds holes), Dynamic World (not pinnable), CGLS-100m + MODIS MOD10/climatologies (too coarse: 100 m–1.1 km), DLR Global SnowPack (500 m; **shelved as the persistence-audit layer** if class-70 contamination ever appears), Copernicus HR-WSI Persistent Snow Area (semantically ideal, 20 m, but pan-European only — kept as validation reference), HLS (reflectance record, not a classification — would mean rolling our own snow science), NE glaciated_areas (1980s–90s DCW vintage), Glaciers CCI (unshipped), climatic snowline formula / per-country ramp normalization (invented data / breaks locked semantics).
- **Masks sane:** Switzerland 2,936 km² in-frame (≈½ non-Swiss Alps: Mont Blanc, Monte Rosa south side, W Austria), India 117,252 km² (Karakoram–Himalaya–Pamir–Kunlun–Tibet); both hug the high chains, zero lowland speckle; 10 m→48 m nearest edge speckle reads as natural fragmented snowfields (majority filter held in reserve, on evidence only).
- **Snow color E8F1F6** (glacial blue-white) over F4F8FA/FFFFFF/warmer arms: at continental scale the cool cast is what separates snow from pale high ramp colors — on India, F4F8FA vanished into the ramp; warm ivory failed outright.
- **Shadow legibility** (Rohan's observation: shadowed faces hid texture, jagged sun/shadow alternation): shadowed slopes had only flat world fill — no directional light to express texture; 15× on the finely-resolved Swiss grid maximizes shadow area. Chosen: **shadowless SE fill sun @ 15% + main sun angle 12°** — fill restores modeling in shadow while barely touching sunlit faces; benign on India. Rejected: ambient 0.3→0.5 (lifts levels, adds no modeling, washes rosy), angle-only (≈no effect on depth), higher sun altitude (kills the low-sun signature), per-country exaggeration (breaks series comparability), post tone-lift (second look-definition outside the scene). 10/15/20% sweep: 15% balanced; 10% defensible-moodier.
- **Land ramp top de-whitened:** 0.75 E8DFD2→DCC9B2, 1.0 F6F1E8→E9DCC8. Pale-peaks tinting was the snow *proxy*; with real snow it double-signals and misfires exactly where high ≠ snowy (Ladakh/W Tibet rendered cream-white). India A/B: "warm" makes the tri-partition legible (warm rock / cool snow / teal water); "cap" (flatten to E8DFD2) too timid; Switzerland unaffected (needs 4,500 m to reach the zone). Affects the India/Nepal/Andes class; Everest clamps at the recolored stop.
- **Verification:** pre-adoption India regression zero-diff (snow branch inert without mask); post-adoption dump-diff exactly the intended change set (ramp stops + evaluation, Snow mix splice, fill light, sun angle — nothing else); scene_dump now prints use_shadow. Confirmed at 8K: swiss_hero_8k_v2 + india_hero_8k_v4 (supersede swiss_hero_1s / india v3 as look references; pinned frame.json values untouched — geometry unchanged). Canonical homes after the same-day renders cleanup: renders/heroes/switzerland.png + heroes/india.png, scenes switzerland_hero.blend + india_hero.blend; superseded arms in renders/archive/, prototype blends pruned, hand-built Phase 0 scene kept as india_hero_handbuilt_phase0.blend (only non-regenerable artifact).
- **Infra:** pipeline/snow_mask.py promoted from experiments (runs after render_prep): 6-worker downloads, 404 = legitimate ocean cell, all-absent = naming-drift abort, atomic .part; pin is the versioned v200/2021 URL path (multipart ETags — no md5 oracle, size checks only). Cache data/raw/worldcover ≈ 9.8 GB (146 tiles), shared across countries. Reopen only if prototype-scale seasonal contamination appears (then: DLR SnowPack duration ∩ class 70).

### 2026-07-08 (night) — Switzerland QA: 1″ is the small-country standard; warp width ≈ render width is the anti-bump guard; resolution bumping rejected for heroes

- Three-arm A/B on the finest hero yet (51 m/px; frame 5.7–10.7°E / 45.5–48.1°N, both arms warped to the same 8192-px / 48 m grid): 3″ reads soft (its 6120-px source is *undersampled*), 1″ reads crisp — sharper crests, cirques, gullies — with only faint orange-peel in the low-relief Mittelland. Huffman-style bumpiness did not appear.
- Why: the warp grid is the low-pass. Bumpiness needs the displacement texture to out-resolve the render; at texture ≈ render width, 1-px dicing cannot resurrect what the warp already removed. **Rule codified: warp --width ≈ render width (7680) and ≤ source width; 1″ fusion for countries whose 3″ source falls under the render width.** (docs/framing-math.md updated.)
- Third arm (experiments/resolution_bump.py: σ=3 px low-pass + 10% detail, Patterson's recipe) lost decisively — smeared landforms, fattened crests, even rounded the Lake Geneva shoreline (smoothing bleeds lake plates). Bumping treats texture-out-resolves-display; our width rule prevents that condition, so for heroes it only destroys signal. It stays shelved for Phase 2 tiles, where high zooms genuinely out-resolve the display.
- First out-of-extent data expansion, infrastructure now honest: download_glo30.py takes --extent + runs the ETag preflight automatically (first live pass: 3 held tiles matched — bucket unmoved); the formerly unscripted VRT rebuild is pipeline/build_mosaics.sh (system gdalbuildvrt; nodata fills match fuse's constants); post-rebuild India oracle byte-identical (196.24 m @ 77.5E/28.5N); fusion class counts: ocean 0.00% in the landlocked frame, identical lake/river fractions across 3″/1″.
- Memory data point: 7680×5738 renders peak at ~11.4 GB host RSS (dicing-dominated, not texture) in ~3.5 min; "free" undercounts headroom — check `available` (reclaimable page cache).

### 2026-07-08 (late) — Pyright adopted as the CLI type-check oracle; pipeline clean

- `uv run pyright` (dev dependency group; [tool.pyright] in pyproject.toml) runs the same engine as Pylance, so IDE findings are reproducible at the terminal and in CI; experiments/ excluded as archival one-offs.
- Triage of the initial 38 errors: the pyshp Optional/union findings were *valid* (the shapefile spec allows null shapes; DBF fields can be non-str) — None-guards added in frame_country + overlay's read_lines, ADMIN coerced via str(). rasterio and affine ship no py.typed, so Window(...) calls and Affine attribute access are checker inference gaps on correct code — suppressed with scoped pragmas naming the reason. bpy imports pragma'd (exists only in Blender's interpreter).
- The regeneration diff-oracle caught a real wrinkle: frame.json's dst_crs spelling differed between the --frame branch (pretty aea_crs string) and the from-file branch (PROJ-normalized) — render_prep now normalizes both; Nepal/Sri Lanka frame.json regenerated, India's pin re-spelled to match, Sri Lanka oracle re-run byte-identical (97.8%).

### 2026-07-08 (evening) — Per-country framing live: frame.json is the contract; India pinned; oracle re-based to meters

- Chain complete and proven twice end-to-end: frame_country.py (NE bbox + 5%-of-larger-span pad, rounded outward to 0.1°) → render_prep --frame (Albers per the ⅙ rule, emits frame.json with plane/ortho/displacement/resolution) → scene_build/overlay_borders consume frame.json. All derivations in docs/framing-math.md; India constants deleted from every script.
- frame.json doubles as the override mechanism: hand-authored files are never overwritten. India's is hand-authored with the v3 hand-rounded values (decided with Rohan: v3 stays canonical; derived exacts differ ≤0.15%). Regression: render_prep on the India dir is a zero-write no-op, and the scene built from the pinned file dump-diffs to zero against india_hero_scripted.blend; the resolution formula reproduces 7680×7906 exactly.
- Nepal (wide frame, landlocked) = first fully scripted hero, 4:34 @ 7680×4787; exposed that oceanmask_aea.png had been hand-made for India and scripted nowhere — render_prep now emits it (0/255, same class-PNG path as lake/river). Sri Lanka (tall frame) proved the orientation flip and the coastline oracle.
- Oracle lesson: fixed pixel tolerances silently change meaning per country (5 px = 2.4 km on India's render, 650 m on Sri Lanka's) — Sri Lanka "failed" at 65% within 5 px while perfectly aligned. Measured signed offsets (west −5±16 px, east +10±8 px, opposite signs, high variance) = NE 1:10m vs WBM product disagreement around lagoon spits, not mapping error; India re-scored 91.1% on the same code. coast_agreement re-based to ground meters (600/1200/2500, bar ≥90% @ 2500 m): India 91.1%, Sri Lanka 97.8%.
- Fixed-width resolution rule strains on tall countries (Sri Lanka wants 7680×12498) — the per-country config item inherits the cap decision. scene_build gained --render and --render-scale (scripted version of the 2048-wide test convention).
- Cosmetic debt noted: numpy 2.5 DeprecationWarnings in rasterio reads, and Blender 6.0 will remove Material.use_nodes — both harmless today.

### 2026-07-08 — Raster source provenance audited: GEBCO self-pinned; GLO-30 unversioned bucket gets an ETag oracle

- GEBCO: filenames carry release + extent (gebco_2026_* + TID twin) — self-documenting, nothing to fix. The full-globe grid for Phase 2 will be a separate deliberate download of the same release.
- GLO-30: the AWS bucket (copernicus-dem-30m) has no edition in any path, so a future fetch could silently mix Copernicus DEM editions across tiles. Checked tiles are Last-Modified 2022-05-09 — the bucket has been frozen for 4 years, so current holdings are edition-coherent.
- Standing oracle (validated on N28/E077: local md5 == bucket ETag): before any future download_glo30 run, HEAD a few held tiles and compare ETag to local md5 — a mismatch means the bucket moved; stop and decide the edition question deliberately.
- Completeness verified 2026-07-08: 979/979 DEM + 979/979 WBM tiles for the 60–100°E / 0–40°N extent, none missing, none outside the extent, no failures.txt, no stray .part files.

### 2026-07-08 — Natural Earth 6.0 draft: not adopted; disk verified as 5.1.2; download script pinned

- Trigger: shadedrelief.com/ne-draft/ surfaced as "Blue Earth 6.0" — it's actually the Natural Earth 6.0 preliminary (Blue Earth is at 2.0, entry below); first major NE release since 5.1.2 (2022), explicitly a work in progress soliciting error reports.
- Rasters irrelevant: land rasters are replaced by our own Copernicus renders, and the 6.0 ocean-bottom raster is the same 21,600×10,800 / 60″ grid as Blue Earth 2.0 (its NE packaging) — rejected per the entry below.
- Vector draft not adopted: borders are the stability-critical layer (worldview policy, disputed segments, bbox-derived camera frames); draft→final polygon shifts would orphan any hero rendered against draft geometry.
- Skew false alarm (corrected same day): layers first looked version-mixed (coastline 5.0.0-pre9, countries 5.1.1), but VERSION.txt is per-layer — it records when that layer last changed, not which release it shipped in; repo tag v5.1.2 carries the identical values. Content oracle: every on-disk layer sha256-matches the tag on .shp/.shx/.dbf; text components identical modulo line endings. Disk is 5.1.2; no re-download needed.
- Real gap fixed instead: download_naturalearth.sh fetched unversioned naciscdn "latest" (a fresh machine running it after 6.0 finals would silently get 6.0) and omitted disputed_areas — repointed to per-file raw downloads from the pinned GitHub tag (nvkelso/natural-earth-vector @ v5.1.2), disputed_areas added to its layer list, upgrade = deliberate one-line TAG bump. Fetch path proven by re-fetching disputed_areas: binaries identical to the naciscdn original, second run a clean no-op. countries_ind (India-POV variant, unused — worldview is NE default) stays out of the script; verified unreferenced repo-wide and deleted from disk 2026-07-08.
- Reopen when 6.0 goes final: deliberate one-time migration — re-download, bbox-diff all country frames, re-check disputed-segment styling. Check its release timing before Phase 2 mass production; worst case is 6.0 finalizing right after a 200-country render pass against 5.x.

### 2026-07-07 (night) — Blue Earth Bathymetry 2.0: considered, not adopted; shelved as tile-artifact remedy

- Trigger: Patterson released v2.0 on 2026-07-06; the project had cited Blue Earth only as aesthetic prior art (CLAUDE.md reference list) and never evaluated it as a bathymetry source — this entry closes that gap.
- Rejected as primary source: it's a 60″ global grid (21,600×10,800) — 4× coarser than GEBCO 15″, and our heroes sample at ~229 m/px (z8 at 306 m/px) where GEBCO is already the limiting layer; shelf detail (the signature look) would upsample ~8× into mush. It also ships no TID provenance channel (the Khambhat diagnosis depends on one), and v2.0's deep basins are BathDNN25 (neural-net-predicted) selectively composited with GEBCO plus manual edits of "suspiciously unnatural" ridges — curated for looks, a step further from auditable truth than GEBCO's gravity model.
- Shelved as the ocean analogue of Patterson resolution bumping: if the tile-shading open question resolves badly (GEBCO survey noise / provenance edges pop at low zooms), Blue Earth 2.0 is purpose-built to clean exactly those artifacts and its native resolution is adequate through ~z5 (1.85 km/px at the equator, vs z5 tiles at 2.45 km/px) — use it there, or replicate its selective-compositing recipe on our own GEBCO to keep one source family.

### 2026-07-07 (night) — Dead render blobs rewritten out of history

- Two 2K PNGs (15 MB) existed only in history (added f6e9647, deleted 6afead7). With no remote yet the rewrite was free: soft-reset to 5b18632, both commits recreated as one, stale water-mask branch / ORIG_HEAD / reflog cleared, gc'd. Repo 15.39 MiB → 323 KiB; the blob-scan oracle returns empty.
- `blender/*.png` added to .gitignore as a tripwire. After the first push this class of rewrite is gone for good — done now deliberately.

### 2026-07-07 (night) — Python packaging: pyproject.toml + uv, manifest-only

- Premise: the venv was the only record of dependencies — unreconstructible after loss.
- pyproject.toml declares the six direct deps with `[tool.uv] package = false` (scripts, not an installable library). Committed uv.lock pins the full tree to the validated environment (numpy held at 2.5.0 after the resolver wanted 2.5.1) — upgrades happen via `uv lock --upgrade`, never incidentally.
- Python pinned two ways: `requires-python = ">=3.12"` is the compatibility floor; `.python-version` (3.12) is what uv provisions and runs. The bpy scripts run on Blender's bundled 3.13.9, outside all of this — shared code must stay compatible with both interpreters.
- Verified by syncing the lock into a throwaway env: package set identical to the live venv, all six imports OK (rasterio wheels bundle GDAL 3.12.1). The live .venv is now lock-managed (`uv sync`; pip survives as a seed package).
- Deferred on purpose: package structure (src layout, shared modules, entry points) waits until per-country generalization reveals the real seams.

### 2026-07-07 (evening) — Phase 1 keystone: scene_build.py rebuilds the hand-built scene from code

- Verified by three oracles, strongest last: structural (pipeline/scene_dump.py, order-normalized, ramp stops included), ramp-function (cr.evaluate() sampled at 10 positions per ramp), pixel (2K renders: max |diff| = 2/255, 0.0000% of samples differ by > 1 — denoiser noise).
- Bug 1, bpy ColorRamp: elements.new() and position writes re-sort the collection and invalidate held element references — colors land on wrong stops, and a surviving default white stop painted the shelf seas white. Fix: shrink to one element, append stops in ascending order, color each via the reference .new() returns. (How-to also in CLAUDE.md.)
- Bug 2, blind oracle: the first structural diff passed on the broken scene — its grep filter for object `loc=` lines also deleted every material-node line, exactly where the bug was; the pixel diff caught what the filtered diff blessed. Lesson, now encoded in scene_dump.py: a check must be shown to FAIL on a known-bad input before its pass means anything.
- Loose end: the hand-built plane height 2.058 is rounded (exact raster aspect 2.0588); switching to exact is a per-country-generalization decision, expected to *improve* coastline registration by ~1.6 px N-S.
- Notes: scene_build takes explicit numbers via CLI — all geo math stays outside Blender (bundled Python has no GDAL); it clears the scene, not factory settings, so user prefs (OptiX) survive.

### 2026-07-07 (later) — Lake depth: flat stays

- The v2 distance-transform prototype (shore anchored at the flat teal, size-attenuated contrast) proved intra-lake gradients read at hero scale and arguably beat flat on looks — rejected regardless: geometry-only depth is an artificial gradient, epistemically worse than honest flat and blind on deep lakes. Parked in pipeline/experiments/lake_depth_prototype.py.
- Reopening bar: real modeled data — GLOBathy or better (costs bulk acquisition + HydroLAKES→WBM shoreline re-registration; MERIT Hydro is river flow/width, not depth). Implementation choice then: post-tint stage vs fusion depth channel + shader ramp.
- Constraints if reopened: tint-only, never carve displacement (at 15× Namtso becomes a 1.5 km crater and the shadow-catching plate dies); needs a per-lake depth channel + its own shallow ramp cap (lakes sit above sea level, mostly < 50 m — the sea ramp can't see them).
- River depth rejected outright: no real global bed data exists (SWOT measures the water surface), and 5–15 m river depths are one ramp tone anyway.

### 2026-07-07 — Inland water: full Route A (raster, in-scene); headless rendering becomes standard

- Verdict: lakes AND rivers painted from the WBM in the material; vector hydro rejected, hybrid explicitly declined — truth over pop. Trigger: the approved 8K had no inland water (the fusion ocean rule absorbs only sea-level water, by design).
- Build: fusion emits a 4-class watermask (0 land / 1 ocean / 2 lake / 3 river; class 1 verified pixel-identical to the ocean mask over all 1.6 Gpx; `--watermask-only` backfills without recomputing); render_prep warps it onto the existing AEA grid and splits 0/255 lake/river PNGs; the shader gains Lake/River Mix switches fed by one RGB node — the tuning lever, documented in ART.md (gotcha: the GUI hex field converts sRGB→linear silently; raw bpy values would not).
- Deciding evidence (Tibet): the WBM carries 3,358 plateau lakes in one 8°×4° window (1,849 survive at hero 229 m/px, 1,381 at z8; everything ≥ 0.5 km² survives at all scales) vs ~10 generalized NE polygons whose outlines visibly contradict the DEM's own basins.
- Rivers: NE centerlines are more legible but are synthesized courses that drift off the braid plains and miss reservoirs; raster rivers render as a pale broken trace (nearest sampling preserves water *area*, not *continuity*) — they stay raster and faint. `--mode hydro` stays in overlay_borders.py as a documented rejected experiment. NE hydro quirks: the current 10m rivers file has no strokeweig, and its DBF fields are lowercase (unlike the boundary files).
- Flatness is ground truth: GLO-30 hydro-flattens water surfaces (Namtso: one plate at 4,725 m; the Ganges: 82→38 m in steps over 83–85.5°E). The *ocean* is the stylized element — bathymetric tint renders seafloor, not surface.
- Ops finding: the GUI 8K render OOMed at 18.4 GB host RSS (kernel oom-kill took the desktop down; unsaved node work lost, rebuilt). The identical render headless: 3 min 36 s, 12.3 GB host peak. `blender -b` is the standard render path from now on.

### 2026-07-06 (late) — Khambhat seam: data-provenance edge, no smoothing

- TID probe: the straight offshore seam is rectangular blocks of TID 16 "optical" (satellite-derived bathymetry, scene-shaped) meeting TID 40 gravity-predicted fill; ENC soundings sprinkle the gulf itself. Extent-wide ocean mix: 83.3% gravity-predicted / 13.0% multibeam / 2.3% optical / 1.2% gravity-guided soundings. Straight edges recur wherever optical blocks exist (shallow coastal water).
- Decision: no smoothing — nobody noticed it on the approved v2 8K. Spot-check the seam zone (72.3–72.6°E, 21.0–21.8°N, offshore Saurashtra) once by eye; reopen only if Phase-2 tile shading makes provenance edges pop.

### 2026-07-06 (evening) — Overlay pipeline live; alignment oracle passed

- Coastline oracle: 74.5 / 91.1 / 93.8 % of drawn NE coastline within 2 / 5 / 10 px of the ocean-mask boundary at 8K, no directional bias in crops — the AEA→pixel mapping (including the ~2 px ortho-margin correction) is confirmed. Residual disagreement is NE 1:10m generalization vs our 30 m coast (Khambhat tidal flats, as predicted at design time).
- First composite: 59 solid / 17 dashed / 14 maritime features in frame; the standalone transparent border layer is emitted alongside (the gallery-toggle asset).
- Aesthetics left open: white-on-bone contrast over high pale terrain (halo/casing is the designated lever); maritime dash visibility to be judged on the 8K; borders drawing over the flat no-data collar at the frame corners — really a Phase-1 framing/collar decision, not a borders bug.

### 2026-07-06 — Border overlay designed; worldview: NE default (de-facto), site-wide

- One editorial stance for all heroes (Kashmir must not change shape between the India and Pakistan pages); disputed/LoC segments dashed; policy noted on the About page. NE ships 31 national POV variants for the country *polygons* only — boundary *lines* exist in the default worldview alone (a POV would be a filtering transform we'd own).
- Rendering route: composite in post (pipeline/overlay_borders.py). With a straight-down ortho camera, draped-3D and flat-2D lines project to identical pixels (no parallax, no overhangs), so the in-scene route buys nothing; evaluated fully anyway (BlenderGIS + Grease Pencil Dot Dash / Freestyle / GN dashing are all real) and rejected on iteration cost (re-render vs recomposite), GUI-add-on dependency in the headless Phase-1 batch, Freestyle perf vs diced terrain — and the frontend needs a standalone transparent border layer anyway, which the compositor emits as a byproduct (gallery toggle = stacked <img>; globe tiers toggle their MapLibre vector layer for free).
- Alignment oracle defined: NE coastline rasterized onto the render grid must hug the land/sea color boundary (checks systematic offset; NE 1:10m is more generalized than our 30 m coast, so local disagreement is expected and fine).
- Styling classes from the DBF (uppercase `FEATURECLA` in this NE release — don't filter on lowercase): solid white = "International boundary (verify)"; dashed = Disputed / Line of control / Indefinite / Indeterminant frontier; maritime indicators all dashed per the reference look.
- Stack (versions verified current on PyPI 2026-07-06): pyshp + pyproj + pycairo — read/reproject/draw needs no geometric ops, so geopandas/shapely would be dead weight; fiona unmaintained since 2024-09 (pyogrio succeeded it); cairo has native dashes/AA/RGBA. pycairo builds from sdist: needs system libcairo2-dev + pkg-config. Data from naciscdn.org via pipeline/download_naturalearth.sh: boundary_lines_land, maritime_indicator, countries (Phase-1 camera bboxes), coastline (oracle).

### 2026-07-06 — First 8K hero approved; CPU-denoise rule; Blender 5.2 plan

- 7680×7906 completed at 1 px dicing, 6.8 GB VRAM peak; approved on desktop and phone (phone softening = display downscaling, not a defect). Claude's prediction that 1 px geometry wouldn't fit was wrong (per-quad memory overestimated; Max Subdivisions also caps effective dicing) — trust the empirical peak, not the estimate.
- The morning's Xid 31 MMU fault re-attributed, low confidence, to GPU render + GPU OIDN denoise VRAM contention at 8K (known pattern, blender/blender#119035; the failed attempt had GPU denoise on, the success had it off) → rule: denoise on CPU for 8K frames. OIDN over the OptiX denoiser for final stills (detail preservation; OptiX is a viewport tool).
- GPU debug recipe: OPTIX_ERROR_UNKNOWN at context creation right after a failed render → check `journalctl -k` for NVRM Xid lines; if the Xid pid is Blender, the driver is fine — restart Blender to clear the dead CUDA context.
- Version plan: finish Phase 0 and the Phase 1 bpy script on 5.1.2; pin 5.2 LTS (releases 2026-07-14) once out — its Cycles texture cache (`--command maketx`) and geometry-memory reduction target exactly our batch workload, and our API surface is untouched by its breaking changes (Geometry Nodes/paint APIs only). Verify the switch with an A/B render against a 5.1.2 reference before trusting it.

### 2026-07-05 — Tuning session → v2 look (supersedes v1)

- View transform **Standard**, locked — AgX's highlight desaturation greyed the palette; a map has no speculars, so filmic compression buys nothing.
- Exaggeration 15× paired with sun altitude 46° — pairing math: shadow length ∝ height × cot(altitude), so cot(new) = cot(old) ÷ exaggeration ratio holds drama constant while adding lowland micro-relief. Sun angle 5° (3° vs 5° invisible at 2K — penumbra sub-pixel at test res; re-judged at 8K).
- World fill F2E7D5 @ strength 0.3 (was default dark grey) — lifts shadow cores to warm brown, tints the backdrop paper-bone; the raytraced analogue of Phase-2's sky-view factor.
- Land ramp rebuilt around cap 6,000 m: rose peaks ~1,500 m then rises to bone/near-white (the Ramspott pale-highlands move); C68A76 retired as too heavy. Sea ramp audited, unchanged from v1. Full stops live in "Locked global constants" above.

### 2026-07-05 — v1 look baseline (superseded by v2)

- Pre-tuning constants, kept as the tuning baseline: 10× (Scale 5.3e-6), sun (55°, 0°, −45°) @ angle 3°, land ramp cap 2,000 m ending in C68A76, view transform AgX. Reference renders: blender/renders/india_look_v1.png (canonical) and *_check.png (accidental sun-angle drift — instructive soft-shadow example, kept).

### 2026-07-05 — First full-look render (india_hero.blend)

- Scene recipe: plane scaled to raster aspect, Simple subdivision + adaptive dicing, Float32 heightfield (Non-Color) driving Displacement, sun lamp, ortho camera from above, two ColorRamps switched by the ocean mask via Mix. (Now reproduced in code by pipeline/scene_build.py.)
- Hard-won lessons for the bpy era: (a) Blender divides 8-bit images by 255 — masks must be exported 0/255, Float32 passes raw; (b) image nodes Non-Color, mask interpolation Closest; (c) Map Range with any reversed range is undefined territory in 5.1.2 — use forward ranges or Math Multiply+Clamp; (d) ColorRamp stops re-sort by position and renumber — never identify a stop by index (the final bug was a hidden 5th pale stop that four index-walking verifications missed).
- Debug toolkit proven: binary mask test, independent numpy albedo oracle, base-resolution ASCII map, revert-to-baseline + minimal diff.

### 2026-07-04 — Render projection: Albers equal-area conic

- India frame: `+proj=aea +lat_1=10 +lat_2=32 +lat_0=21 +lon_0=82.5`. Geographic degrees are E-W stretched (~5% at 21°N mid-frame, varying N-S); a conic with standard parallels ⅙ in from the frame's latitude edges keeps scale near-uniform, so displaced terrain isn't anisotropically distorted. Phase 1 derives per-country params the same way (pipeline/render_prep.py). Heights stay in meters; exaggeration is a Blender-side constant.

### 2026-07-04 — Fusion rule refined after full-frame spot checks

- Rule: ocean = WBM class 1 ∪ no-coverage ∪ (class 2/3 with |elev| ≤ 1 m); never convert dry land; high-altitude lakes unaffected. Context: WBM classifies coastal lagoons and tidal channels as lake/river (~2,200 km² of sea-level "lakes" + ~8,000 km² of sea-level "rivers" in the India frame — Chilika, Kerala backwaters, Sundarbans).
- Spot-check oracles for any future fusion run: Delhi ~214 m, Everest ~8.7 km (3″ averaging shaves the true 8,849 m peak), open Arabian Sea deeply negative, Chilika lagoon ≤ −1 m with mask = 1.
- Caveat learned the hard way: verify anomalies at the data's own pixel scale before calling them bugs — 79.7°E 9.5°N reads +0.6 m/land *correctly* (ESA maps an emergent tidal flat there; the water starts one pixel west).

### 2026-07-04 — Khambhat fusion experiment: hard splice, −1 m ocean clamp, no feathering

- Run on the adversarial macro-tidal case (pipeline/experiments/fuse_khambhat.py; confirmed by the two-ramp color test, color_khambhat.py — naive fusion renders phantom sand-colored land inside the gulf, the clamp eliminates it).
- Decisions: sea = WBM ocean class only (lakes/rivers keep the land surface — their water *tint* is a material decision, not a fusion decision); hard splice with ocean clamped ≤ −1 m; feathering rejected — no visible seam in multidirectional hillshade even here.
- Key learning: naive fusion's failure mode is *coloring*, not shading — 3.2% of ocean pixels resolve ≥ 0 m (up to +18 m) and would key off the wrong end of a depth ramp. The clamp also makes sign-of-elevation a valid sea/land key downstream (caveat: rare below-sea-level land like Kuttanad mis-keys; the mask COG stays ground truth).
- Side find: a dead-straight GEBCO source boundary offshore W Khambhat — diagnosed 2026-07-06 via TID (see above).

### 2026-07-04 — Fusion reframed after prior-art check

- Land/sea DEM fusion is a solved problem (ETOPO 2022 is the finished 15″ product; grdblend the standard tool; cartographers do this routinely). We proceed with our own fusion anyway — justified by 1″ land detail for small countries and z9–z10 tiles, plus learning value — treated as method selection, with ETOPO 2022 as an external validation oracle. Noted honestly: for a ship-it project, "use ETOPO 2022" would be the right call at hero scale (~370 m/px for India-sized framing).

### 2026-07-04 — Phase 0 data acquired

- Extent locked 60–100°E / 0–40°N (979 GLO-30 tiles, half-open east/north edges); GEBCO_2026 (April 2026 release) chosen over 2025; water-body masks (WBM) downloaded alongside DEMs as a candidate coastline source.
- The downloader's stdlib-only .part → verify → atomic-rename pattern is the template for all later pipeline stages. Git initialized (code only; data/ ignored).

### 2026-07-04 — Purpose reframed: learning first

- Understanding every piece is the primary goal; the shipped site is secondary. Claude acts as guide, not workhorse; the plan is expected to change significantly as understanding surfaces. (Charter recorded in CLAUDE.md.)

### 2026-07-03 — Project scoped; dev environment decided

- Scoped in a claude.ai conversation; architecture, data sources, and rendering approach locked into CLAUDE.md. Phase 0 target: India.
- All work in the Ubuntu boot of the dual-boot desktop (Blender + pipeline on one ext4 filesystem, native OptiX); Windows boot and WSL ruled out. Rohome remains deploy target and production runner for the tile pipeline. Constraint: overnight GPU renders occupy the desktop (no gaming those nights).
