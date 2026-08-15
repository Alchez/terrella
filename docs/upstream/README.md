# Upstream reports

Performance defects found in [maplibre-gl-js](https://github.com/maplibre/maplibre-gl-js) while
building this site, written up so they can be filed upstream. Each directory is self-contained: a
report and a standalone `repro.html` that needs no Terrella code, no local patch and no private data.

**Neither report is filed.** They are written and reproducible; nothing has been opened upstream.

| Report | What it claims | State |
|---|---|---|
| `maplibre-terrain-coords-allocation/` | `_getTerrainCoordsForRegularTile` allocates a tile ID and a `Float64Array(16)` for every renderable tile and discards ~96% of them. Mechanical fix, no visual change. | Unfiled. A fix is obvious and small. |
| `maplibre-covering-tiles-fov-cliff/` | `coveringTiles` selects tiles ~3 zoom levels over-refined at narrow fields of view — 61 px tiles on a scheme aiming for 512. The count also exhausts VRAM and loses the WebGL context, which is a severity claim the reproduction does not yet carry. | Unfiled. **No fix proposed** — the root cause is not established. |

**A third report was considered and rejected.** A production freeze — a camera parked at pitch 60
inside a narrow zoom band, 0.9 fps, style never loading, GL context lost — turned out to be this same
covering-tiles defect reached by a different route, so it sharpened the report above rather than
opening a new directory. The rule that produced that answer is worth keeping: *a distinct trigger is
not a distinct defect.* Before adding a directory here, check whether the mechanism is already
described by one of these — the VRAM amplifier (`Painter._rttObjectRecyclePool`, uncapped) turns any
tile-count spike fatal, so several unrelated-looking symptoms land on one of the two reports.

## What upstream expects

Read from MapLibre's own [`CONTRIBUTING.md`](https://github.com/maplibre/maplibre-gl-js/blob/main/CONTRIBUTING.md)
and [pull request template](https://github.com/maplibre/maplibre-gl-js/blob/main/.github/PULL_REQUEST_TEMPLATE.md),
which are the authority — this table is a pointer, not a copy to trust when the two disagree.

- **Reproductions go up as a jsbin link, not an attached HTML file.** A maintainer asked for exactly
  that on #7699 ("Please provide a jsbin link instead of attaching html files"), and the reporter
  complied. Both `repro.html` files here are single self-contained pages, so porting is mechanical —
  but it has to happen before filing, not after being asked.
- **A bug without a fix still has a good artifact: the failing test.** CONTRIBUTING suggests writing a
  failing test first and opening it as a **draft PR that documents the incorrect behaviour**. That is
  the cheapest honest contribution for the covering-tiles report, which has a measured defect and no
  proposed fix.
- **Disclose AI assistance.** CONTRIBUTING asks contributors to disclose significant AI assistance and
  to be able to explain and defend the code under review; the PR template carries a checklist item
  confirming the [AI policy](https://github.com/maplibre/maplibre/blob/main/AI_POLICY.md) has been read,
  and an optional `Assisted-By:` / `Generated-By:` trailer naming the model. Both currently-open PRs
  read for these reports carry that trailer.
- **The PR checklist**, in full: no Mapbox backports without a compliant licence; describe the change;
  link related issues; **before/after visuals or gifs** for anything visual; tests for all new
  functionality; document public API changes; post before/after `npm run bench` results if the file has
  a `*.bench.ts` beside it; add a `CHANGELOG.md` entry under `## main`; confirm the AI policy.
- **Changelog scope:** *must* have an entry for public API, visual appearance or security changes;
  *should* for performance work and bugfixes; *should not* for documentation.
- **Performance claims want a before/after table** from `npm run bench -- --compare` in the PR body.

## Conventions for a report in this directory

- **It must run against public data on stock MapLibre.** A report that needs our tiles, our patch or
  our application code is a claim about our site, not something a maintainer can act on.
- **Say what is not claimed.** Each report carries an explicit eliminations section, and an explicit
  statement where the root cause is unknown, so nothing reads as settled that is not.
- **Read the related threads rather than matching their titles.** Both reports carry a section placing
  the defect against the existing tracker, including the threads that turned out *not* to be it and the
  measurement that discriminates.
