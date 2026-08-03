#!/usr/bin/env python3
"""Trace per-process GPU memory once a second, so a VRAM climb can be told from a crash-respawn.

`nvidia-smi --query-compute-apps` lists CUDA/OpenCL clients only. A browser is a *graphics*
client and never appears there, so that flag reports a browser as using no GPU memory at all.
The XML dump (`nvidia-smi -q -x`) carries every client tagged G / C+G, which is the only
scriptable path to a browser's VRAM on this driver.

The process age column is the point of the whole script. The 2K freeze was recorded as
"6,218 MiB and 4m31s old" on a browser session hours older than that -- meaning the GPU
process had already died and respawned, and the number was a *refill*, not a steady state.
Sampling pid and age continuously turns that inference into an observation: a pid change is
a crash, and only a number that grows under a stable pid is a genuine steady-state cost.
"""

from __future__ import annotations

import subprocess
import sys
import time
import xml.etree.ElementTree as ElementTree
from dataclasses import dataclass

SAMPLE_INTERVAL_SECONDS = 1.0
CLOCK_TICKS_PER_SECOND = 100.0


@dataclass(frozen=True)
class GraphicsClient:
    pid: int
    used_mib: int
    command: str


def parse_used_mib(raw_value: str | None) -> int:
    """Turn nvidia-smi's "478 MiB" into 478; unsupported readings become 0."""
    if not raw_value:
        return 0
    parts = raw_value.split()
    return int(parts[0]) if parts and parts[0].isdigit() else 0


def read_graphics_clients() -> tuple[int, list[GraphicsClient]]:
    dump = subprocess.run(
        ["nvidia-smi", "-q", "-x"], capture_output=True, text=True, check=True
    ).stdout
    root = ElementTree.fromstring(dump)
    total_used_mib = 0
    clients: list[GraphicsClient] = []
    for gpu in root.iter("gpu"):
        total_used_mib += parse_used_mib(gpu.findtext("./fb_memory_usage/used"))
        for process in gpu.iter("process_info"):
            pid_text = process.findtext("pid")
            if pid_text is None:
                continue
            clients.append(
                GraphicsClient(
                    pid=int(pid_text),
                    used_mib=parse_used_mib(process.findtext("used_memory")),
                    command=process.findtext("process_name") or "",
                )
            )
    return total_used_mib, clients


def process_age_seconds(pid: int) -> float:
    """Seconds since this pid started, from /proc -- a reset means the process died."""
    try:
        with open(f"/proc/{pid}/stat", encoding="utf-8") as handle:
            stat_fields = handle.read().rsplit(") ", 1)[1].split()
        started_at_ticks = float(stat_fields[19])
        with open("/proc/uptime", encoding="utf-8") as handle:
            uptime_seconds = float(handle.read().split()[0])
        return uptime_seconds - started_at_ticks / CLOCK_TICKS_PER_SECOND
    except (OSError, IndexError, ValueError):
        return -1.0


def is_chrome_gpu_process(client: GraphicsClient) -> bool:
    return "/opt/google/chrome/chrome" in client.command and "--type=gpu-process" in client.command


def is_zen_gpu_process(client: GraphicsClient) -> bool:
    return "/zen/zen" in client.command


def main() -> int:
    started_at = time.monotonic()
    print(
        "iso_time,elapsed_s,gpu_total_mib,chrome_gpu_pid,chrome_gpu_mib,"
        "chrome_gpu_age_s,zen_gpu_mib,other_graphics_mib",
        flush=True,
    )
    while True:
        total_used_mib, clients = read_graphics_clients()
        chrome = next((client for client in clients if is_chrome_gpu_process(client)), None)
        zen_mib = sum(client.used_mib for client in clients if is_zen_gpu_process(client))
        other_mib = sum(
            client.used_mib
            for client in clients
            if not is_chrome_gpu_process(client) and not is_zen_gpu_process(client)
        )
        print(
            f"{time.strftime('%H:%M:%S')},"
            f"{time.monotonic() - started_at:.1f},"
            f"{total_used_mib},"
            f"{chrome.pid if chrome else -1},"
            f"{chrome.used_mib if chrome else 0},"
            f"{process_age_seconds(chrome.pid) if chrome else -1:.0f},"
            f"{zen_mib},"
            f"{other_mib}",
            flush=True,
        )
        time.sleep(SAMPLE_INTERVAL_SECONDS)


if __name__ == "__main__":
    sys.exit(main())
