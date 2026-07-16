#!/usr/bin/env bash
# Instrumented planet shade pass (no --tiles; tiling is a separate gated step).
#
# Four instruments, chosen because each answers something the others cannot:
#   1. perf record   -> WHERE the CPU goes, at symbol level, for every forked child (perf inherits
#                       across fork+exec, so one file covers gdalwarp/gdaldem/gdal_rasterize/numpy).
#   2. sample_tree   -> RSS, peak RSS, thread count, real disk bytes per process per second.
#                       perf cannot answer "is it I/O-bound or single-threaded"; this can.
#   3. stamp.py      -> per-stage wall clock from the pass's own existing stage prints, free.
#   4. the cgroup    -> memory.peak for the whole scope, and the 12 G cap that kills the job not
#                       the box (proven today: a 4-cell region render hit it and died alone).
#
# The cap is 12 G per PLAN: composite measures 6.93 GiB with lake depth, so this is ~1.7x measured.
# GDAL_CACHEMAX=512 per shade_planet.py's own launch note.
set -uo pipefail

HARNESS=/home/rohan/projects/maps/pipeline/profile   # code: tracked in git
PROF=/home/rohan/projects/maps/data/work/_profile     # output: data, gitignored
VENV=/home/rohan/projects/maps/.venv/bin/python
UNIT=terrella-pass
cd /home/rohan/projects/maps || exit 1

mkdir -p "$PROF"
: > "$PROF/pass.log"

# Sampler first: it polls for the cgroup, so it is already watching when the scope appears.
# 0.5 s, not 1 s: the composite forks ~728 short-lived snow subprocesses (gdalwarp +
# gdal_rasterize per window x 364 windows) and a 1 s interval races their exit. perf catches
# their CPU regardless, but only the sampler sees their RSS and disk bytes.
"$VENV" "$HARNESS/sample_tree.py" --unit "${UNIT}.scope" --out "$PROF/samples.jsonl" \
    --interval 0.5 2> "$PROF/sampler.log" &
SAMPLER_PID=$!

echo "=== instrumented shade pass starting $(date -Is) ===" | tee -a "$PROF/pass.log"

systemd-run --user --scope --unit="$UNIT" -p MemoryMax=12G -p MemorySwapMax=0 \
    perf record -F 49 -g --output="$PROF/pass.perf.data" -- \
    env GDAL_CACHEMAX=512 "$VENV" -u -m pipeline.tile.shade_planet 2>&1 \
    | "$VENV" "$HARNESS/stamp.py" | tee -a "$PROF/pass.log"

STATUS=${PIPESTATUS[0]}
echo "=== scope exit status: $STATUS  $(date -Is) ===" | tee -a "$PROF/pass.log"

wait "$SAMPLER_PID" 2>/dev/null
echo "=== sampler stopped ===" | tee -a "$PROF/pass.log"
exit "$STATUS"
