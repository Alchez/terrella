"""Prefix each stdout line with wall-clock + elapsed seconds.

shade_planet.py already prints a marker at every stage boundary ("warp height -> 3857 ...",
"per-row-z hillshade ...", "global sky-view factor ...", "composited rows N/93009" every 20
windows, "cutting z0-8 512px tiles -> ..."). Timestamping those lines is the per-stage timing story,
at zero overhead and zero code change -- and the composite's every-20-windows marker turns into a
rows/second curve over latitude for free, which is how the lake warp's spatially non-uniform rate
would have been caught before it broke the estimate.

mawk (Ubuntu's default awk) has no strftime, so this is python rather than a one-liner.
"""

import sys
import time

start = time.time()
for line in sys.stdin:
    elapsed = time.time() - start
    sys.stdout.write(f"[{time.strftime('%H:%M:%S')} +{elapsed:8.1f}s] {line}")
    sys.stdout.flush()
