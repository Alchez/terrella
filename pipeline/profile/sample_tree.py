"""Sample every process in the pass's cgroup once a second: RSS, peak RSS, CPU, threads, disk I/O.

Why a sampler at all, when perf is already recording? They answer disjoint questions. perf says
where the CPU went (symbols); it says nothing about resident memory, disk bytes, or thread counts.
The three open questions about the 31 GB height warp -- is it CPU-bound, I/O-bound, or
single-threaded? -- need exactly those, and `/usr/bin/time -v` cannot answer them per-stage because
the pass is one python process shelling out to many children whose peaks it conflates.

Sampling by CGROUP, not by pid-tree walk or `pgrep -f`, is deliberate. `pgrep -f` is what matched
the `/usr/bin/time` wrapper instead of gdalwarp and produced three impossible
profiles that got built on. The cgroup is ground truth: if it is in the scope, it is ours, and
short-lived children (the ~728 per-window snow subprocesses) cannot hide from it the way they hide
from a tree walk that races their exit.

VmHWM is the kernel's own high-water mark and only ever grows, so the last sample before a process
exits carries its true peak even at a 1 s interval. /proc/PID/io read_bytes/write_bytes are actual
block-layer bytes -- page-cache hits do not count -- which is what distinguishes "reading 31 GB" from
"re-reading 31 GB the kernel already had".

Usage: sample_tree.py --unit terrella-pass.scope --out samples.jsonl [--interval 1.0]
"""

import argparse
import glob
import json
import sys
import time
from pathlib import Path

CLOCK_TICKS = 100.0  # _SC_CLK_TCK on Linux/x86-64


def find_cgroup(unit: str) -> Path | None:
    """Locate the scope's cgroup dir. Globbed rather than hardcoded: the path embeds the uid."""
    for pattern in (f"/sys/fs/cgroup/user.slice/user-*.slice/user@*.service/app.slice/{unit}",
                    f"/sys/fs/cgroup/user.slice/user-*.slice/user@*.service/{unit}",
                    f"/sys/fs/cgroup/**/{unit}"):
        matches = glob.glob(pattern, recursive=True)
        if matches:
            return Path(matches[0])
    return None


def read_int(path: Path, default: int = 0) -> int:
    try:
        return int(path.read_text().split()[0])
    except (OSError, ValueError, IndexError):
        return default


def proc_sample(pid: int) -> dict | None:
    """One process's counters. Returns None if it exited mid-read (expected and common)."""
    base = Path(f"/proc/{pid}")
    try:
        # comm can contain spaces/parens, so split on the LAST ')' -- the classic /proc/stat trap.
        stat = base.joinpath("stat").read_text()
        comm = stat[stat.index("(") + 1:stat.rindex(")")]
        fields = stat[stat.rindex(")") + 2:].split()
        utime, stime = int(fields[11]), int(fields[12])
        threads = int(fields[17])

        status = base.joinpath("status").read_text()
        rss = hwm = 0
        for line in status.splitlines():
            if line.startswith("VmRSS:"):
                rss = int(line.split()[1])
            elif line.startswith("VmHWM:"):
                hwm = int(line.split()[1])

        read_bytes = write_bytes = 0
        try:
            for line in base.joinpath("io").read_text().splitlines():
                if line.startswith("read_bytes:"):
                    read_bytes = int(line.split()[1])
                elif line.startswith("write_bytes:"):
                    write_bytes = int(line.split()[1])
        except OSError:
            pass  # /proc/PID/io needs matching uid; harmless if absent

        cmdline = base.joinpath("cmdline").read_bytes().replace(b"\0", b" ").decode(
            "utf-8", "replace").strip()
        return {"pid": pid, "comm": comm, "cmd": cmdline[:220],
                "rss_kb": rss, "hwm_kb": hwm, "threads": threads,
                "cpu_s": (utime + stime) / CLOCK_TICKS,
                "read_mb": read_bytes / 1048576, "write_mb": write_bytes / 1048576}
    except (OSError, ValueError, IndexError):
        return None


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--unit", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--interval", type=float, default=1.0)
    parser.add_argument("--wait", type=float, default=120.0, help="seconds to wait for the cgroup")
    args = parser.parse_args()

    deadline = time.time() + args.wait
    cgroup = None
    while time.time() < deadline:
        cgroup = find_cgroup(args.unit)
        if cgroup:
            break
        time.sleep(0.25)
    if not cgroup:
        print(f"cgroup for {args.unit} never appeared", file=sys.stderr)
        return 1
    print(f"sampling {cgroup}", file=sys.stderr, flush=True)

    # The handle is held for the whole pass, so `with` is doing real work rather than satisfying a
    # style: this sampler wraps a 30+ minute planet run, and the two `break`s below were the only
    # paths that reached the old `close()`. Anything raised inside the loop left the file open,
    # which on a watchdog process is exactly when someone goes looking for what it recorded.
    with open(args.out, "w", buffering=1) as out:
        started = time.time()
        empty_rounds = 0
        while True:
            now = time.time()
            try:
                pids = [int(p) for p in cgroup.joinpath("cgroup.procs").read_text().split()]
            except OSError:
                break  # scope torn down -> pass finished

            if not pids:
                empty_rounds += 1
                if empty_rounds > 5:
                    break
            else:
                empty_rounds = 0

            procs = [sample for sample in (proc_sample(pid) for pid in pids) if sample]
            record = {
                "t": round(now - started, 2),
                "cg_mem_mb": read_int(cgroup / "memory.current") / 1048576,
                "cg_peak_mb": read_int(cgroup / "memory.peak") / 1048576,
                "mem_avail_mb": 0,
                "swap_used_mb": 0,
                "procs": procs,
            }
            try:
                meminfo = Path("/proc/meminfo").read_text()
                info = {}
                for line in meminfo.splitlines():
                    key, _, rest = line.partition(":")
                    info[key] = int(rest.split()[0])
                record["mem_avail_mb"] = info.get("MemAvailable", 0) / 1024
                record["swap_used_mb"] = (info.get("SwapTotal", 0)
                                          - info.get("SwapFree", 0)) / 1024
            except (OSError, ValueError, IndexError):
                pass

            out.write(json.dumps(record) + "\n")
            time.sleep(max(0.0, args.interval - (time.time() - now)))

    print("sampler done", file=sys.stderr, flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
