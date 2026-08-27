#!/usr/bin/env bash
# Instrumented planet pass.
#
# Usage:
#   pipeline/profile/run_pass.sh --body earth           # the planet raster only
#   pipeline/profile/run_pass.sh --body earth --tiles   # the raster (skipped when fresh) + the cut
#
# "the planet raster" rather than "shade", because which producer fills it is the BODY's answer
# (Body.planet_producer) and this wrapper never learns it; and the cut runs to that body's own
# ceiling, z8 on Earth and z7 on Mars, rather than to a number spelled here.
#
# `--body` is REQUIRED and this wrapper deliberately does not supply one: injecting a default here
# would reintroduce, one layer up, exactly the silent Earth assumption planet_pass refuses to make.
#
# Args are passed through to pipeline.tile.planet_pass, which is the pass's entry point and the
# module that chooses the body's producer; --tiles additionally picks its own output dir, scope name
# and memory cap, so a tiling run never overwrites a shade run's profile.
#
# Four instruments, chosen because each answers something the others cannot:
#   1. perf record   -> WHERE the CPU goes, at symbol level, for every forked child (perf inherits
#                       across fork+exec, so one file covers gdalwarp/gdaldem/gdal_rasterize/numpy).
#   2. sample_tree   -> RSS, peak RSS, thread count, real disk bytes per process per second.
#                       perf cannot answer "is it I/O-bound or single-threaded"; this can.
#   3. stamp.py      -> per-stage wall clock from the pass's own existing stage prints, free.
#   4. the cgroup    -> memory.peak for the whole scope, and the body's own cap, which kills the job
#                       rather than the box (proven: a 4-cell region render hit it and died alone).
#                       The number is pass_cap.py's, never this script's -- see the block below.
#
# THE CAP IS THE BODY'S AND THIS SCRIPT DOES NOT KNOW IT -- pipeline/profile/pass_cap.py derives
# it from the registry, and holds the whole argument plus the measurements behind both numbers.
# MEMORY_CAP_OVERRIDE_GIB substitutes the number afterwards and says so on stdout when it does; the
# registry is still asked either way, and the branch itself carries why that ordering matters.
# The short version: 16 G is the CAP-RENDERING number, because the pass ENDS by invoking cap_render
# as a subprocess that inherits this scope's cgroup; a body rendering no caps never reaches that
# stage, so on it the 16 G is unbacked rather than protective and the preflight below then refuses
# a pass the box could have run. The composite is NOT why either number is what it is, and
# COMPOSITE_ROWS=128 is a hardcoded constant rather than a function of this cap, so a larger cap
# cannot let it grow. The per-stage peaks are measured in PROCESS.md, not restated here.
#
# What this script still owns is GDAL_CACHEMAX=512 (per shade_planet.py's own launch note), which
# `gdal raster tile` multiplies: it spawns -j ALL_CPUS workers that EACH inherit it. That product is
# an UPPER BOUND the cut never reaches -- the block cache fills lazily, and measured the cut is the
# lightest stage of the pass, so it is not what sizes this cap. A worker killed mid-write still
# leaves a TRUNCATED png, but build_tiles no longer resumes over a partial staging dir -- it removes
# it and cuts clean, so a bad tile can no longer survive into the pyramid.
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
else
    RUN_LABEL=pass
fi
PROF=$DATA/work/_profile_$RUN_LABEL   # output: data, gitignored
UNIT=terrella-$RUN_LABEL

# Ask the registry, through the pass's OWN argument parser, rather than reading --body here: this
# argv is forwarded to that module verbatim seconds later, so a second spelling of the grammar is
# a second thing to keep in step. It also makes this wrapper honour the contract its header states
# -- until now a run that omitted --body cleared the preflight, opened a cgroup scope, and only
# then died inside Python. argparse writes its own message to stderr, so nothing is restated here.
MEMORY_CAP_GIB=$("$VENV" -m pipeline.profile.pass_cap "$@") || exit 1

# A DELIBERATE OVERRIDE, READ AFTER THE RESOLVER AND NEVER INSTEAD OF IT, which is the whole design
# of this branch. Written `${MEMORY_CAP_OVERRIDE_GIB:-$(...)}` it would let an exported variable skip
# the resolver entirely, and with it the --body check the line above exists to enforce; written here
# the registry is always asked, the body is always named, and only the NUMBER is substituted.
#
# It exists because the alternative is an untestable wiring. Both bodies render caps now, so the
# resolver answers 16 for every planet in the registry and no real invocation can tell "the shell
# used the number it was given" from "the shell holds a 16" -- a distinction sabotage.py has a case
# for. A synthetic body cannot help: pass_cap runs in a SUBPROCESS, so a monkeypatched registry
# never reaches it. This makes the number a controllable input, which is what a wiring test needs.
#
# ANNOUNCED, BECAUSE A SILENT ONE WOULD BE THE THING pass_cap's "NO FALLBACK" NOTE REFUSES. A pass
# capped at an arbitrary number that nothing names is exactly the failure that module is written to
# prevent; a pass capped at a number it prints is an operator decision, like ALLOW_LOW_MEMORY.
if [[ -n "${MEMORY_CAP_OVERRIDE_GIB:-}" ]]; then
    # Validated rather than trusted: a non-numeric value makes the comparison below evaluate it as
    # 0, so every box would clear every cap and the preflight would silently stop being a check.
    if [[ ! "$MEMORY_CAP_OVERRIDE_GIB" =~ ^[0-9]+$ ]]; then
        echo "ABORT: MEMORY_CAP_OVERRIDE_GIB=$MEMORY_CAP_OVERRIDE_GIB is not a whole number of GiB." >&2
        exit 1
    fi
    echo "memory cap overridden: ${MEMORY_CAP_OVERRIDE_GIB} G instead of this body's ${MEMORY_CAP_GIB} G"
    MEMORY_CAP_GIB=$MEMORY_CAP_OVERRIDE_GIB
fi
MEMORY_CAP=${MEMORY_CAP_GIB}G

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

# STOP_AFTER exists so the tests can exercise branches without launching a real pass, and it names
# the point rather than being a boolean: `preflight` stops above any side effect at all, `logs`
# stops once this run's log is prepared, which is the only way to observe the rotation below.
[[ "${STOP_AFTER:-}" == preflight ]] && exit 0

# ONE LOG PER RUN, AND EVERY RUN'S LOG KEPT. The raytrace producer resumes across nights by design
# -- the box is not free for 22 consecutive hours -- and this line used to be `: > pass.log`, which
# meant a four-night render kept only the fourth night's record of which blocks failed.
#
# Rotated rather than appended, because the log is not the only per-run artifact and the others do
# not append either: samples.jsonl is rewritten, and stamp.py's elapsed column counts from ITS OWN
# start, so two runs in one file would carry two clocks under one heading. A rotated name keeps
# each night internally consistent, and `grep FAILED "$PROF"/pass*.log` still reads the whole
# render in one command.
mkdir -p "$PROF"
if [[ -s "$PROF/pass.log" ]]; then
    # Named for when that run's log was last written rather than for now, so the filename says
    # which night it covers, and so re-running twice inside one second cannot land on one name.
    mv "$PROF/pass.log" "$PROF/pass-$(date -r "$PROF/pass.log" +%Y%m%dT%H%M%S).log"
fi
: > "$PROF/pass.log"

[[ "${STOP_AFTER:-}" == logs ]] && exit 0

# Sampler first: it polls for the cgroup, so it is already watching when the scope appears.
# 0.5 s, not 1 s, AND THE REASON IS THE COMPOSITE PRODUCER'S ALONE: it forks ~728 short-lived snow
# subprocesses (gdalwarp + gdal_rasterize per window x 364 windows) and a 1 s interval races their
# exit. perf catches their CPU regardless, but only the sampler sees their RSS and disk bytes.
# The raytrace producer forks one long-lived Blender per block instead, which nothing can race, so
# on that producer the rate buys accuracy nobody needs and costs ~158k samples over a night. It is
# left at 0.5 s rather than made per-producer because this script does not know which one runs --
# the body does, and asking would be a second reader of pass_cap's question for a sampling rate.
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
    env GDAL_CACHEMAX=512 "$VENV" -u -m pipeline.tile.planet_pass "$@" 2>&1 \
    | "$VENV" "$HARNESS/stamp.py" | tee -a "$PROF/pass.log"

STATUS=${PIPESTATUS[0]}
echo "=== scope exit status: $STATUS  $(date -Is) ===" | tee -a "$PROF/pass.log"

wait "$SAMPLER_PID" 2>/dev/null
echo "=== sampler stopped ===" | tee -a "$PROF/pass.log"
exit "$STATUS"
