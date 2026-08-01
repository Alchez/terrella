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
# Shade cap 16 G, raised from 12 G. The composite is NOT why: it still peaks at
# 10.55 GiB (opt #5, 128/N4; the serial composite was 6.24 GiB) and COMPOSITE_ROWS=128
# is a hardcoded constant, not a function of this cap, so raising the cap does not let the
# composite grow -- N stays 4 because 256/N3 and N=6 OOM on their own arithmetic. The cap moved
# because the pass ENDS by rendering the polar caps (shade_planet invokes cap_render as a
# subprocess, which inherits this scope's cgroup) and the caps peak at ~14 GB -- so a 12 G pass
# completed every tile stage and then died at the very last one. Known cost of the raise: 12 G was
# also an accidental tripwire on composite footprint, and a regression there now goes unnoticed
# until 16 G.
#
# Tiling cap 16 G, and it is NOT the same calculation. The composite is skipped when planet_rgb is
# fresh, so the peak stage becomes `gdal raster tile`, which spawns -j ALL_CPUS workers that EACH
# inherit GDAL_CACHEMAX -- 16 x 512 MB of block cache alone, before any tile buffers. Tiling's real
# peak has never been measured, so the cap is sized off that per-worker cache math with headroom;
# 16 G still kills the job and not the box (29 G total, ~20 G available). A worker killed mid-write
# still leaves a TRUNCATED png, but build_tiles no longer resumes over a partial staging dir -- it
# removes it and cuts clean, so a bad tile can no longer survive into the pyramid.
# GDAL_CACHEMAX=512 per shade_planet.py's own launch note.
set -uo pipefail

# Roots derive from this script's own location, never a hardcoded home path: the harness has to
# run from any checkout, and the preflight tests drive it on CI. MAPS_DATA moves the data store,
# the same seam pipeline/paths.py and build_mosaics.sh read.
ROOT=$(cd "$(dirname "$0")/../.." && pwd)
HARNESS=$ROOT/pipeline/profile   # code: tracked in git
VENV=$ROOT/.venv/bin/python
DATA=${MAPS_DATA:-$ROOT/data}
cd "$ROOT" || exit 1

if [[ " $* " == *" --tiles "* ]]; then
    RUN_LABEL=tiles
    MEMORY_CAP=16G
else
    RUN_LABEL=pass
    MEMORY_CAP=16G
fi
PROF=$DATA/work/_profile_$RUN_LABEL   # output: data, gitignored
UNIT=terrella-$RUN_LABEL

# --- memory preflight -------------------------------------------------------------------------
# A cgroup cap kills the job instead of the box -- but only if the box can actually BACK the cap.
# Capping at 16 G on a machine with 9 G free does not protect anything; it just relocates the
# failure to the most expensive possible moment, hours into a pass, after every completed stage
# has been paid for. Refuse to start instead.
#
# MemAvailable is the kernel's own estimate of what a new job can take WITHOUT swapping, which is
# exactly the question being asked -- unlike `free`, whose "free" column undercounts by ignoring
# reclaimable page cache (the note). MEMINFO is overridable so the check itself is
# testable: a guard that has never been seen to fire is indistinguishable from one that passed.
MEMINFO=${MEMINFO:-/proc/meminfo}
memory_cap_gib=${MEMORY_CAP%G}
memory_available_kib=$(awk '/^MemAvailable:/ {print $2}' "$MEMINFO")

if [[ -z "$memory_available_kib" ]]; then
    echo "ABORT: no MemAvailable line in $MEMINFO -- cannot verify the box can back $MEMORY_CAP." >&2
    exit 1
fi

if (( memory_available_kib < memory_cap_gib * 1024 * 1024 )) && [[ -z "${ALLOW_LOW_MEMORY:-}" ]]; then
    awk -v available="$memory_available_kib" -v cap="$memory_cap_gib" -v label="$RUN_LABEL" 'BEGIN {
        printf "ABORT: the %s run is capped at %d G but only %.1f GiB is available.\n", label, cap, available/1048576
        printf "       Starting anyway would OOM somewhere deep in the pass, not here.\n"
        printf "       Free memory (browser/editor are the usual holders) and re-run,\n"
        printf "       or set ALLOW_LOW_MEMORY=1 to override deliberately.\n"
    }' >&2
    exit 1
fi

awk -v available="$memory_available_kib" -v cap="$memory_cap_gib" 'BEGIN {
    printf "memory preflight: %.1f GiB available >= %d G cap -- OK\n", available/1048576, cap
}'

# PREFLIGHT_ONLY exists so the tests can exercise BOTH branches without launching a real pass.
[[ -n "${PREFLIGHT_ONLY:-}" ]] && exit 0

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
