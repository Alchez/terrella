"""Watch the instrumented pass and EXIT when something worth reporting happens.

The harness re-invokes Claude when a background task exits, so "exit on event" is how a
multi-hour job gets check-ins instead of a single verdict at the end. Polling every few seconds
from the assistant side would burn context for nothing; this sleeps, and only returns when
there is genuinely something to say.

Fires on:
  * STAGE     -- the pass crossed a stage boundary and said so. The vocabulary is ONE marker,
                 owned by `pipeline/progress.py`, because a watcher holding a list of the
                 phrasings it expects goes stale the day a stage is added and says nothing while
                 it does: this module carried such a list, and four of Earth's five surface
                 layers plus both of Mars's own stages had never been reported.
  * FAULT     -- a line that means something went wrong, matched by pattern rather than declared,
                 because the interesting faults are the ones nobody wrote a marker for. A dying
                 process prints; it does not get to update a status document first.
  * PROGRESS  -- the producer's own status sidecar crossed a milestone, or changed state.
                 Throttled by `--progress-step`, which is what a sidecar buys and a regex cannot:
                 the raytrace producer renders one block per grid cell -- 1,024 on Earth at
                 today's RENDER_BLOCK_PX -- and a match is a match, so a per-block MARKER would be
                 one wake-up per block in a night. A number can be sampled; a match cannot.
  * DONE      -- the scope's cgroup is gone: pass finished or died
  * MEMORY    -- ANON memory nearing this body's cap, an actual oom_kill, or the BOX swapping.
                 NOT memory.current: that includes PAGE CACHE, which is reclaimable, and a job
                 streaming a 31 GB raster parks the cgroup at its cap by design (measured:
                 current 12287 MB = anon 802 + file 11382, with oom_kill 0 and the
                 pass perfectly healthy). Watching memory.current cried wolf on the first try --
                 the same "measure the proxy, not the thing" error as the day's bbox-max lake
                 oracle. `max` in memory.events counts reclaims, not kills; only oom_kill matters.
  * STALL     -- no CPU and no disk progress anywhere in the cgroup for STALL_S
  * HEARTBEAT -- HEARTBEAT_S elapsed with none of the above, so silence is never ambiguous

The cap this runs under is the BODY's and this module does not know it: `pipeline/profile/
pass_memory.py` derives it and holds every measurement behind it.

Exit code is always 0; the REASON is on stdout. Usage:
  watchdog.py --unit terrella-pass.scope --log pass.log --samples samples.jsonl \
              [--status <work>/raytrace_status.json]
"""

import argparse
import glob
import json
import re
import time
from pathlib import Path

from pipeline import progress

POLL_S = 10.0
HEARTBEAT_S = 1200.0     # 20 min: quiet enough not to nag, often enough that silence is not scary
STALL_S = 420.0          # 7 min of zero CPU AND zero disk anywhere in the cgroup
ANON_WARN_MB = 10_000    # UNCALIBRATED: sized off the composite's 6.24 GiB of anon, and that
                         # stage is deleted. `--anon-warn`'s help carries what stands in its place.
#: System-wide swap before warning, in MB. **IT IS THE BOX'S NUMBER AND NOT THE RUN'S**, which is
#: the one memory term here that does not come from the cgroup: `sample_tree` reads SwapTotal minus
#: SwapFree out of `/proc/meminfo`, and a pass scoped `MemorySwapMax=0` cannot contribute a byte to
#: it. So it answers "is this box thrashing", and a desktop that has parked cold pages there answers
#: yes forever — which is why `--swap-warn` exists rather than this being the only reading.
SWAP_WARN_MB = 1_500
PROGRESS_STEP_PCT = 5.0  # 20 wake-ups across a whole planet, against 4,096 if every block fired

#: A stage boundary, in the one spelling the pass emits. Imported rather than copied: a second
#: spelling here is the exact failure this replaced, one file further along.
STAGE_RE = re.compile(re.escape(progress.STAGE_MARKER))

#: Trouble, matched rather than declared. `FAILED` and `ABORT` are the runner's own words for a
#: block that died and a run that gave up; the rest are what an interpreter or the kernel says
#: when nothing in this repo got the chance to say anything.
FAULT_RE = re.compile(r"(Traceback|MemoryError|Killed|ABORT|FAILED|Error|error)")


def classify(line: str) -> str | None:
    """What this log line is worth waking for, if anything.

    FAULT wins a line that is both, because a stage boundary that also carries a failure is read
    for the failure.
    """
    if FAULT_RE.search(line):
        return "FAULT"
    if STAGE_RE.search(line):
        return "STAGE"
    return None


def find_cgroup(unit: str):
    for pattern in (f"/sys/fs/cgroup/user.slice/user-*.slice/user@*.service/app.slice/{unit}",
                    f"/sys/fs/cgroup/**/{unit}"):
        matches = glob.glob(pattern, recursive=True)
        if matches:
            return Path(matches[0])
    return None


def cgroup_health(cgroup: Path) -> dict:
    """anon (unreclaimable) and oom_kill -- the only two memory numbers that mean anything here."""
    health = {"anon_mb": 0.0, "file_mb": 0.0, "oom_kill": 0}
    try:
        for line in (cgroup / "memory.stat").read_text().splitlines():
            key, _, value = line.partition(" ")
            if key == "anon":
                health["anon_mb"] = int(value) / 1048576
            elif key == "file":
                health["file_mb"] = int(value) / 1048576
    except (OSError, ValueError):
        pass
    try:
        for line in (cgroup / "memory.events").read_text().splitlines():
            key, _, value = line.partition(" ")
            if key == "oom_kill":
                health["oom_kill"] = int(value)
    except (OSError, ValueError):
        pass
    return health


def tail_events(log: Path, seen: int):
    """Return (new_reportable_lines, worst_reason, total_lines_seen)."""
    try:
        lines = log.read_text(errors="replace").splitlines()
    except OSError:
        return [], None, seen
    fresh = [(line, classify(line)) for line in lines[seen:]]
    reportable = [line for line, reason in fresh if reason]
    worst = "FAULT" if any(reason == "FAULT" for _, reason in fresh) else (
        "STAGE" if reportable else None)
    return reportable, worst, len(lines)


def read_status(status: Path | None) -> tuple[dict | None, str | None]:
    """The producer's own progress document, or None when there is none to read.

    Absence is THREE different things and a caller that cannot tell them apart is why this returns
    the reason: no `--status` given (a raytraced run wired without the flag looks exactly like a
    stage that writes no sidecar), the path given but not yet written, or written and unreadable.
    """
    if status is None:
        return None, "no --status given"
    try:
        return json.loads(status.read_text()), None
    except FileNotFoundError:
        return None, f"not written yet: {status}"
    except (OSError, ValueError) as failure:
        return None, f"unreadable ({failure}): {status}"


def crossed_step(previous: float | None, current: float, step: float) -> bool:
    """Whether `current` has entered a new `step`-wide band since `previous`.

    Banded rather than differenced so the milestones are absolute -- 5, 10, 15 percent of the
    planet -- and a resumed night that starts at 62% reports at 65 rather than at 67. `previous`
    is None on the first read, which establishes the baseline and never fires: a watcher started
    over a finished run must not announce last night's result as this night's progress.
    """
    if previous is None:
        return False
    return int(current // step) > int(previous // step)


def last_sample(samples: Path):
    try:
        with open(samples, "rb") as handle:
            handle.seek(0, 2)
            size = handle.tell()
            handle.seek(max(0, size - 65536))
            chunk = handle.read().decode("utf-8", "replace")
        for line in reversed(chunk.splitlines()):
            if line.startswith("{") and line.rstrip().endswith("}"):
                return json.loads(line)
    except (OSError, ValueError):
        pass
    return None


def summarise_status(status, absence: str | None) -> str:
    """The producer's own numbers, on every report, or why there are none.

    Printed even when absent because an optional input that says nothing when it is missing makes
    the broken wiring the quiet case: a raytraced night watched without `--status` would look
    exactly like one whose producer never wrote a block.
    """
    if not status:
        return f"  (no producer status: {absence})"
    return (f"  {status.get('body')} {status.get('state')}  {status.get('progress')} "
            f"({status.get('percent')}%)  {status.get('blocks_per_min')} blk/min  "
            f"eta {status.get('eta_min')} min  {status.get('failures')} failed  "
            f"{status.get('free_gb')} GB free  last {status.get('last_block')!r}")


def summarise(sample) -> str:
    if not sample:
        return "  (no sample yet)"
    out = [(f"  t={sample['t']:.0f}s  cgroup {sample['cg_mem_mb']:.0f} MB "
            f"(peak {sample['cg_peak_mb']:.0f})  avail {sample['mem_avail_mb']:.0f} MB  "
            f"swap {sample['swap_used_mb']:.0f} MB")]
    for proc in sample["procs"]:
        if proc["comm"] in ("perf",):
            continue
        out.append(f"    {proc['comm']:<14} rss {proc['rss_kb']/1024:>7.0f}M "
                   f"thr {proc['threads']:>2} cpu {proc['cpu_s']:>8.1f}s "
                   f"rd {proc['read_mb']:>7.0f}MB wr {proc['write_mb']:>8.0f}MB")
    return "\n".join(out)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--unit", required=True)
    parser.add_argument("--log", required=True)
    parser.add_argument("--samples", required=True)
    parser.add_argument("--seen", type=int, default=0, help="log lines already reported")
    parser.add_argument("--status", type=Path, default=None,
                        help="the producer's own progress document, if it writes one "
                             "(block_render's raytrace_status.json). Without it a night reports "
                             "only stage boundaries and faults, which on a producer whose whole "
                             "middle is one stage means nothing between the warp and the cut.")
    parser.add_argument("--progress-step", type=float, default=PROGRESS_STEP_PCT,
                        help="percent of the planet between progress reports. This is a WAKE "
                             "POLICY rather than a display setting: each report exits the "
                             "watchdog and wakes the reader.")
    parser.add_argument("--anon-warn", type=float, default=ANON_WARN_MB,
                        help="anon MB before warning. A coarse net rather than a threshold: it was "
                             "sized off the deleted composite's windowed sawtooth, and oom_kill is "
                             "the real signal. Unmeasured on the raytrace producer, whose memory "
                             "sits in a Blender subprocess rather than in this one.")
    parser.add_argument("--swap-warn", type=float, default=SWAP_WARN_MB,
                        help="system-wide swap MB before warning. Raise it on a box whose desktop "
                             "legitimately holds cold pages in swap: the scope cannot swap at all, "
                             "so a static occupancy below this is somebody else's memory and not "
                             "this run's.")
    parser.add_argument("--heartbeat", type=float, default=HEARTBEAT_S,
                        help="seconds of quiet before reporting 'still healthy'. Raise it for "
                             "unattended overnight runs: stage/memory/stall events still fire, so "
                             "a long heartbeat costs nothing but silence.")
    args = parser.parse_args()
    heartbeat_s = args.heartbeat
    anon_warn_mb = args.anon_warn
    swap_warn_mb = args.swap_warn

    log, samples = Path(args.log), Path(args.samples)
    seen = args.seen
    started = time.time()
    last_event = time.time()
    last_progress = time.time()
    last_totals = None
    last_state: str | None = None
    last_percent: float | None = None

    def report(reason: str, status, absence, lines=()) -> int:
        print(f"REASON: {reason}\nSEEN: {seen}\n")
        for line in lines:
            print(f"  {line}")
        print(summarise_status(status, absence))
        print(summarise(last_sample(samples)))
        return 0

    while True:
        time.sleep(POLL_S)
        now = time.time()

        fresh, worst, seen = tail_events(log, seen)
        sample = last_sample(samples)
        status, absence = read_status(args.status)

        if fresh:
            return report(worst or "STAGE", status, absence, fresh[-6:])

        # AFTER the log and before the cgroup: a sidecar milestone is real progress, and a sidecar
        # that has gone quiet is not an event at all -- STALL below is what notices that, from the
        # cgroup, because a killed process stops updating this file and stops burning CPU together.
        if status:
            state, percent = status.get("state"), float(status.get("percent") or 0.0)
            if last_state is not None and state != last_state:
                last_state, last_percent = state, percent
                return report("PROGRESS", status, absence)
            if crossed_step(last_percent, percent, args.progress_step):
                last_state, last_percent = state, percent
                return report("PROGRESS", status, absence)
            last_state, last_percent = state, percent

        cgroup = find_cgroup(args.unit)
        if cgroup is None:
            return report(f"DONE (scope gone after {(now-started)/60:.1f} min of watching)",
                          status, absence)

        health = cgroup_health(cgroup)
        if health["oom_kill"] or health["anon_mb"] > anon_warn_mb or (
                sample and sample["swap_used_mb"] > swap_warn_mb):
            return report(f"MEMORY  (anon {health['anon_mb']:.0f} MB, "
                          f"file/cache {health['file_mb']:.0f} MB, "
                          f"oom_kill {health['oom_kill']})", status, absence)

        if sample:

            totals = (round(sum(p["cpu_s"] for p in sample["procs"]), 1),
                      round(sum(p["write_mb"] + p["read_mb"] for p in sample["procs"])))
            if last_totals is not None and totals != last_totals:
                last_progress = now
            last_totals = totals
            if now - last_progress > STALL_S:
                return report(f"STALL (no cpu/disk progress for {STALL_S/60:.0f} min)",
                              status, absence)

        if now - last_event > heartbeat_s:
            return report(f"HEARTBEAT ({heartbeat_s/60:.0f} min, all healthy)", status, absence)


if __name__ == "__main__":
    raise SystemExit(main())
