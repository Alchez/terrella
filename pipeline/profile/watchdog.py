#!/usr/bin/env python3
"""Watch the instrumented pass and EXIT when something worth reporting happens.

The harness re-invokes Claude when a background task exits, so "exit on event" is how a
multi-hour job gets check-ins instead of a single verdict at the end. Polling every few seconds
from the assistant side would burn context for nothing; this sleeps, and only returns when
there is genuinely something to say.

Fires on:
  * STAGE     -- a new stage marker in pass.log (NOT the every-20-windows composite progress,
                 which would fire ~18 times and say nothing new)
  * DONE      -- the scope's cgroup is gone: pass finished or died
  * MEMORY    -- ANON memory nearing the 12 G cap, an actual oom_kill, or swap in use.
                 NOT memory.current: that includes PAGE CACHE, which is reclaimable, and a job
                 streaming a 31 GB raster parks the cgroup at its cap by design (measured
                 2026-07-15: current 12287 MB = anon 802 + file 11382, with oom_kill 0 and the
                 pass perfectly healthy). Watching memory.current cried wolf on the first try --
                 the same "measure the proxy, not the thing" error as the day's bbox-max lake
                 oracle. `max` in memory.events counts reclaims, not kills; only oom_kill matters.
  * STALL     -- no CPU and no disk progress anywhere in the cgroup for STALL_S
  * HEARTBEAT -- HEARTBEAT_S elapsed with none of the above, so silence is never ambiguous

Exit code is always 0; the REASON is on stdout. Usage:
  watchdog.py --unit terrella-pass.scope --log pass.log --samples samples.jsonl
"""

import argparse
import glob
import json
import re
import time
from pathlib import Path

POLL_S = 10.0
HEARTBEAT_S = 1200.0     # 20 min: quiet enough not to nag, often enough that silence is not scary
STALL_S = 420.0          # 7 min of zero CPU AND zero disk anywhere in the cgroup
ANON_WARN_MB = 10_000    # the cap is 12 G; composite peaks at 6.24 GiB of anon (re-measured 07-16)
SWAP_WARN_MB = 1_500     # swap sat pinned 7/7 all of 2026-07-15; never again unnoticed

# Stage markers shade_planet.py already prints. "composited rows" is deliberately excluded.
STAGE_RE = re.compile(
    r"(warp height ->|warp ocean ->|warp water ->|warp lake depth ->|no lakedepth|"
    r"color-relief \(|per-row-z hillshade|global sky-view factor|planet_rgb fresh|"
    r"wrote |DONE|Traceback|Error|error|Killed|MemoryError)")


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


def tail_stages(log: Path, seen: int):
    """Return (new_stage_lines, total_lines_seen)."""
    try:
        lines = log.read_text(errors="replace").splitlines()
    except OSError:
        return [], seen
    fresh = [line for line in lines[seen:] if STAGE_RE.search(line)]
    return fresh, len(lines)


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


def summarise(sample) -> str:
    if not sample:
        return "  (no sample yet)"
    out = [f"  t={sample['t']:.0f}s  cgroup {sample['cg_mem_mb']:.0f} MB "
           f"(peak {sample['cg_peak_mb']:.0f})  avail {sample['mem_avail_mb']:.0f} MB  "
           f"swap {sample['swap_used_mb']:.0f} MB"]
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
    parser.add_argument("--anon-warn", type=float, default=ANON_WARN_MB,
                        help="anon MB before warning. The hillshade legitimately sawtooths to "
                             "~11.6 G under the 12 G cap (float64 @ 1024 rows), so a 10 G "
                             "threshold is a false-alarm generator: oom_kill is the real signal.")
    parser.add_argument("--heartbeat", type=float, default=HEARTBEAT_S,
                        help="seconds of quiet before reporting 'still healthy'. Raise it for "
                             "unattended overnight runs: stage/memory/stall events still fire, so "
                             "a long heartbeat costs nothing but silence.")
    args = parser.parse_args()
    heartbeat_s = args.heartbeat
    anon_warn_mb = args.anon_warn

    log, samples = Path(args.log), Path(args.samples)
    seen = args.seen
    started = time.time()
    last_event = time.time()
    last_progress = time.time()
    last_totals = None

    while True:
        time.sleep(POLL_S)
        now = time.time()

        fresh, seen = tail_stages(log, seen)
        sample = last_sample(samples)

        if fresh:
            print(f"REASON: STAGE\nSEEN: {seen}\n")
            print("\n".join(f"  {line}" for line in fresh[-6:]))
            print(summarise(sample))
            return 0

        cgroup = find_cgroup(args.unit)
        if cgroup is None:
            print(f"REASON: DONE (scope gone after {(now-started)/60:.1f} min of watching)\n"
                  f"SEEN: {seen}\n")
            print(summarise(sample))
            return 0

        health = cgroup_health(cgroup)
        if health["oom_kill"] or health["anon_mb"] > anon_warn_mb or (
                sample and sample["swap_used_mb"] > SWAP_WARN_MB):
            print(f"REASON: MEMORY  (anon {health['anon_mb']:.0f} MB, "
                  f"file/cache {health['file_mb']:.0f} MB, oom_kill {health['oom_kill']})\n"
                  f"SEEN: {seen}\n")
            print(summarise(sample))
            return 0

        if sample:

            totals = (round(sum(p["cpu_s"] for p in sample["procs"]), 1),
                      round(sum(p["write_mb"] + p["read_mb"] for p in sample["procs"])))
            if last_totals is not None and totals != last_totals:
                last_progress = now
            last_totals = totals
            if now - last_progress > STALL_S:
                print(f"REASON: STALL (no cpu/disk progress for {STALL_S/60:.0f} min)\n"
                      f"SEEN: {seen}\n")
                print(summarise(sample))
                return 0

        if now - last_event > heartbeat_s:
            print(f"REASON: HEARTBEAT ({heartbeat_s/60:.0f} min, all healthy)\nSEEN: {seen}\n")
            print(summarise(sample))
            return 0


if __name__ == "__main__":
    raise SystemExit(main())
