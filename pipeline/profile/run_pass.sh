#!/usr/bin/env bash
# Instrumented planet pass.
#
# Usage:
#   pipeline/profile/run_pass.sh           # shade only
#   pipeline/profile/run_pass.sh --tiles   # shade (skipped when fresh) + cut z0-8 tiles
#
# Args are passed through to shade_planet.py; --tiles additionally picks its own output dir,
# scope name and memory cap, so a tiling run never overwrites a shade run's profile.
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
# Shade cap 12 G: the THREADED composite (opt #5, 128/N4) peaks at 10.55 GiB (2026-07-18; the serial
# composite was 6.24 GiB), so 12 G is ~1.14x measured -- and N=6 would OOM, which is why N stays 4.
#
# Tiling cap 16 G, and it is NOT the same calculation. The composite is skipped when planet_rgb is
# fresh, so the peak stage becomes `gdal raster tile`, which spawns -j ALL_CPUS workers that EACH
# inherit GDAL_CACHEMAX -- 16 x 512 MB of block cache alone, before any tile buffers. Tiling's real
# peak has never been measured, so the cap is sized off that per-worker cache math with headroom;
# 16 G still kills the job and not the box (29 G total, ~20 G available). A worker killed mid-write
# still leaves a TRUNCATED png, but build_tiles no longer resumes over a partial staging dir -- it
# removes it and cuts clean (2026-07-20), so a bad tile can no longer survive into the pyramid.
# GDAL_CACHEMAX=512 per shade_planet.py's own launch note.
set -uo pipefail

HARNESS=/home/rohan/projects/maps/pipeline/profile   # code: tracked in git
VENV=/home/rohan/projects/maps/.venv/bin/python
cd /home/rohan/projects/maps || exit 1

if [[ " $* " == *" --tiles "* ]]; then
    RUN_LABEL=tiles
    MEMORY_CAP=16G
else
    RUN_LABEL=pass
    MEMORY_CAP=12G
fi
PROF=/home/rohan/projects/maps/data/work/_profile_$RUN_LABEL   # output: data, gitignored
UNIT=terrella-$RUN_LABEL

mkdir -p "$PROF"
: > "$PROF/pass.log"

# Sampler first: it polls for the cgroup, so it is already watching when the scope appears.
# 0.5 s, not 1 s: the composite forks ~728 short-lived snow subprocesses (gdalwarp +
# gdal_rasterize per window x 364 windows) and a 1 s interval races their exit. perf catches
# their CPU regardless, but only the sampler sees their RSS and disk bytes.
"$VENV" "$HARNESS/sample_tree.py" --unit "${UNIT}.scope" --out "$PROF/samples.jsonl" \
    --interval 0.5 2> "$PROF/sampler.log" &
SAMPLER_PID=$!

echo "=== instrumented $RUN_LABEL pass starting $(date -Is) (cap $MEMORY_CAP, args: $*) ===" \
    | tee -a "$PROF/pass.log"

# perf needs kernel.perf_event_paranoid <= 1; Ubuntu ships 4, which blocks unprivileged perf and
# needs a root sysctl to change. DEGRADE rather than block: perf only adds symbol-level CPU
# attribution, while sample_tree/stamp/cgroup already answer how-long, how-much-RAM and
# io-vs-cpu-bound. A missing optional instrument must never cost a 40-minute pass.
PERF_PREFIX=()
if perf record -F 49 --output=/dev/null -- true > /dev/null 2>&1; then
    PERF_PREFIX=(perf record -F 49 -g --output="$PROF/pass.perf.data" --)
    echo "perf: ON" | tee -a "$PROF/pass.log"
else
    echo "perf: OFF (kernel.perf_event_paranoid=$(cat /proc/sys/kernel/perf_event_paranoid), needs <=1;" \
         "sudo sysctl -w kernel.perf_event_paranoid=1). Other 3 instruments unaffected." \
         | tee -a "$PROF/pass.log"
fi

systemd-run --user --scope --unit="$UNIT" -p MemoryMax="$MEMORY_CAP" -p MemorySwapMax=0 \
    ${PERF_PREFIX[@]+"${PERF_PREFIX[@]}"} \
    env GDAL_CACHEMAX=512 "$VENV" -u -m pipeline.tile.shade_planet "$@" 2>&1 \
    | "$VENV" "$HARNESS/stamp.py" | tee -a "$PROF/pass.log"

STATUS=${PIPESTATUS[0]}
echo "=== scope exit status: $STATUS  $(date -Is) ===" | tee -a "$PROF/pass.log"

wait "$SAMPLER_PID" 2>/dev/null
echo "=== sampler stopped ===" | tee -a "$PROF/pass.log"
exit "$STATUS"
