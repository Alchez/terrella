"""Prefix each stdout line with wall-clock + elapsed seconds.

The pass marks its own stage boundaries (`pipeline/progress.py`), so timestamping every line it
prints is the per-stage timing story at zero overhead and zero code change. The lines that are NOT
boundaries pay off too: any stage printing a periodic row count becomes a rows/second curve over
latitude for free, which is how the lake warp's spatially non-uniform rate would have been caught
before it broke the estimate.

The elapsed clock is THIS PROCESS's, so it restarts with each run. `run_pass.sh` keeps one log per
run for that reason among others: two runs appended into one file would carry two clocks counting
from different moments under one column heading.

mawk (Ubuntu's default awk) has no strftime, so this is python rather than a one-liner.
"""

import sys
import time

start = time.time()
for line in sys.stdin:
    elapsed = time.time() - start
    sys.stdout.write(f"[{time.strftime('%H:%M:%S')} +{elapsed:8.1f}s] {line}")
    sys.stdout.flush()
