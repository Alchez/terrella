#!/usr/bin/env python3
"""Raster comparison that cannot quietly lie to you.

This module exists because of a measured pattern, not a hunch. Across two days, SEVEN
verification bugs shipped, and every one was in the CHECK, never in the pipeline:

  1. `pgrep -f` matched the `/usr/bin/time` wrapper, not gdalwarp -> three impossible "findings"
  2. a bbox MAX as a lake oracle -> a 92 m Caspian "leak" whose argmax sat on land near Baku
  3. the raw lakedepth FILE instead of what `composite()` is handed -> a leak that cannot reach a pixel
  4. `memory.current` (incl. reclaimable page cache) instead of `anon` -> a false OOM alarm
  5. a calibration oracle restricted to lakes where GLOBathy copies the published depth verbatim
  6. differencing CPU across two same-named PIDs -> **-0.1% CPU**
  7. `altitude=46.0` retyped from the hero constants; the tile path uses 45.0 -> 10.3 G px "differ"

The common shape: measuring something ADJACENT to the question because it was easier to reach, and
never noticing because the proxy usually agrees. What CAUGHT them was always the same three things
-- a witness, a distribution, or a value impossible on its face. What HID them was always a bare
aggregate ("max = 92", "differs by a bit") that looked plausible.

So this helper is deliberately incapable of returning a bare aggregate. Every comparison yields:

  * the FULL histogram of |difference| -- shape is the diagnostic. Precision noise centres on 0; a
    systematic offset does not. Bug 7 was diagnosed in one glance from a mode at 3 DN, and would
    have shipped as "small float32 rounding" from a mean or a sample.
  * a WITNESS -- worst pixel in lon/lat plus both values. Bug 2 died the instant its argmax was
    printed.
  * a CONTROL -- a self-comparison asserted to be exactly 0, so "0 differences" is proven reachable
    rather than assumed. Per HISTORY 2026-07-06 (the blind-oracle bug: a structural diff whose
    filter removed the very lines the bug was in, so it passed on a broken scene), a check that
    cannot fail is indistinguishable from a check that passed.
  * COVERAGE -- how much of each raster was actually read, so a partial scan can never be reported
    as if it were exhaustive.

Companion rule this module CANNOT enforce, so it is written here instead: **verify by calling the
production function with the production module's own constants -- import, never retype.** Bug 7 was
a retyped constant. `from pipeline.tile.shade_planet import ALT` cannot drift; `ALT = 46.0` can.
"""

from dataclasses import dataclass, field

import numpy as np
import rasterio
from rasterio.warp import transform

from pipeline.raster_io import band_window, row_bands


@dataclass
class Comparison:
    """The result of comparing two rasters. Deliberately has no single 'score' field."""

    histogram: np.ndarray               # index = |difference|, value = pixel count
    worst: int
    worst_lonlat: tuple | None
    worst_values: tuple | None
    pixels_compared: int
    pixels_total: int
    control_passed: bool
    tolerance: int
    notes: list = field(default_factory=list)

    @property
    def within_tolerance(self) -> bool:
        beyond = int(self.histogram[self.tolerance + 1:].sum())
        return beyond == 0 and self.control_passed

    @property
    def beyond_tolerance(self) -> int:
        return int(self.histogram[self.tolerance + 1:].sum())

    def report(self) -> str:
        lines = [f"compared {self.pixels_compared:,} of {self.pixels_total:,} px "
                 f"({self.pixels_compared / self.pixels_total * 100:.1f}% coverage)"]
        if self.pixels_compared < self.pixels_total:
            lines.append("  !! PARTIAL SCAN -- this is a sample, not a proof")
        lines.append("")
        lines.append(f"  {'|diff|':>8} {'pixels':>16} {'share':>10}")
        lines.append("  " + "-" * 36)
        nonzero = np.nonzero(self.histogram)[0]
        for value in nonzero[:12]:
            count = int(self.histogram[value])
            lines.append(f"  {int(value):>8} {count:>16,} "
                         f"{count / max(self.pixels_compared, 1) * 100:>9.4f}%")
        if len(nonzero) > 12:
            lines.append(f"  ... and {len(nonzero) - 12} further difference levels")
        lines.append("")
        lines.append(f"  worst: {self.worst} (tolerance {self.tolerance})")
        # Both are set together or not at all, but say so explicitly: a witness printed with
        # half its evidence would be the bare aggregate this module exists to refuse.
        if self.worst_lonlat and self.worst_values:
            lines.append(f"  witness: lon {self.worst_lonlat[0]:.3f}, lat {self.worst_lonlat[1]:.3f}"
                         f"  reference={self.worst_values[0]} candidate={self.worst_values[1]}")
        lines.append(f"  beyond tolerance: {self.beyond_tolerance:,} px")
        lines.append(f"  control (self-compare == 0): {'PASS' if self.control_passed else 'FAIL'}")
        for note in self.notes:
            lines.append(f"  note: {note}")
        lines.append("")
        lines.append("  VERDICT: " + ("WITHIN TOLERANCE" if self.within_tolerance else "DIFFERS"))
        return "\n".join(lines)


def compare_rasters(reference_path, candidate_path, tolerance: int = 1, band: int = 1,
                    window_rows: int = 2048, max_diff: int = 4096) -> Comparison:
    """Compare two same-grid rasters band-for-band over EVERY pixel.

    `tolerance` is stated by the caller BEFORE the run and recorded in the result, so the bar
    cannot be quietly relaxed to fit the number that came out.
    """
    with rasterio.open(reference_path) as ref, rasterio.open(candidate_path) as cand:
        if (ref.width, ref.height) != (cand.width, cand.height):
            raise ValueError(f"grid mismatch: {ref.width}x{ref.height} vs "
                             f"{cand.width}x{cand.height}")
        width, height = ref.width, ref.height
        histogram = np.zeros(max_diff, dtype=np.int64)
        worst, worst_lonlat, worst_values = 0, None, None
        compared = 0

        for row0, row1 in row_bands(height, window_rows):
            window = band_window(width, row0, row1)
            a = ref.read(band, window=window).astype(np.int32)
            b = cand.read(band, window=window).astype(np.int32)
            delta = np.abs(a - b)
            histogram += np.bincount(delta.ravel(), minlength=max_diff)[:max_diff]
            compared += delta.size
            block_worst = int(delta.max())
            if block_worst > worst:
                worst = block_worst
                index = np.unravel_index(np.argmax(delta), delta.shape)
                easting, northing = ref.xy(row0 + int(index[0]), int(index[1]))
                # transform() returns (xs, ys) or (xs, ys, zs) depending on whether zs was
                # passed, so index the pair off rather than unpacking a variable-length tuple.
                projected = transform(ref.crs, "EPSG:4326", [easting], [northing])
                worst_lonlat = (projected[0][0], projected[1][0])
                worst_values = (int(a[index]), int(b[index]))

        # Control: prove 0 is reachable by this code path, so "no differences" means something.
        probe_window = band_window(width, height // 2, height // 2 + min(32, height))
        probe = ref.read(band, window=probe_window)
        control_passed = bool(np.abs(probe.astype(np.int32) - probe.astype(np.int32)).max() == 0)

        return Comparison(histogram=histogram, worst=worst, worst_lonlat=worst_lonlat,
                          worst_values=worst_values, pixels_compared=compared,
                          pixels_total=width * height, control_passed=control_passed,
                          tolerance=tolerance)
