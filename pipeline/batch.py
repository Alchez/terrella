#!/usr/bin/env python3
"""Batch runner: drive the whole pipeline across every in-scope country.

Reuses country_config's resolver (scope, frames, per-country stage commands)
and runs each country's stages as isolated subprocesses. Built to survive
abrupt shutdown (OOM / brownout / blackout):

  * Crash-safe resume. Every stage finalizes its outputs atomically (write
    .tmp, os.replace on success — see fuse_heightfield / render_prep /
    snow_mask), so a file at its final path always means "complete." Resume
    is therefore just filesystem existence: a country whose phase target
    exists is skipped; a partially-prepped one resumes stage-by-stage
    (each stage skips what it already finished). The renderer writes to a
    .tmp.png that this runner promotes on exit 0. No durable in-memory state
    — a killed runner just re-runs and picks up where it left off.
  * Dynamic OOM defense. Sequential (the 8K render is GPU-bound). Before the
    render, a memory gate waits (bounded) if MemAvailable is below a floor,
    then skips the country rather than starting a doomed render. Heavy stages
    optionally run under a systemd --user cgroup MemoryMax cap (best-effort;
    absent inside containers) so a runaway is killed cleanly instead of
    thrashing the box. An OOM-killed stage (rc 137) is logged and skipped —
    never silently re-rendered at degraded quality (locked-look consistency).
  * Failures never abort the run. Nonzero rc -> one JSONL line in
    blender/renders/batch_failures.jsonl, skip the country's rest, continue.

Default phase is `prep` so a bare invocation can never start the ~10-13h
render sweep. `--through render` adds the render stage. `--dry-run` prints the
plan and runs nothing — the sweep preview.

Usage:
  batch.py --dry-run                          # preview, run nothing
  batch.py --through prep                      # prep sweep (default)
  batch.py --through render --only bhutan       # one hero, end to end
"""

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from country_config import (build_scope, load_config, load_ne_rows,
                            preflight_gebco, resolve, stage_commands)

ROOT = Path(__file__).resolve().parent.parent
# Stage commands say "python …" assuming a venv-active shell; put this runner's
# own interpreter dir first on PATH so the subprocesses use the venv, not system.
ENV = {**os.environ,
       "PATH": f"{Path(sys.executable).parent}{os.pathsep}{os.environ.get('PATH', '')}"}
FAIL_LOG = ROOT / "blender/renders/batch_failures.jsonl"
PREP_STAGES = 5           # stage_commands[:5] = download,mosaics,fuse,prep,snow
RENDER_STAGE = 5          # scene_build --render
GATE_STAGES = {5}         # render: the 11-12 GB consumer the floor is set for
CAP_STAGES = {2, 5}       # fusion + render: best-effort cgroup containment
GATE_POLL_S = 30
GATE_MAX_WAIT_S = 1800    # wait up to 30 min for other load to clear, then skip


def meminfo_gib(key: str) -> float:
    with open("/proc/meminfo") as f:
        for line in f:
            if line.startswith(key + ":"):
                return int(line.split()[1]) / (1024 * 1024)  # kB -> GiB
    return 0.0


def detect_cgroup_cap() -> bool:
    """True if systemd --user scopes can enforce MemoryMax here (best-effort)."""
    if not shutil.which("systemd-run"):
        return False
    probe = ("systemd-run --user --scope -q -p MemoryMax=256M "
             "-p MemorySwapMax=0 -- true")
    return subprocess.run(probe, shell=True, capture_output=True).returncode == 0


def wait_for_mem(floor_gib: float) -> bool:
    """Block until MemAvailable >= floor, or give up after GATE_MAX_WAIT_S."""
    waited = 0
    while meminfo_gib("MemAvailable") < floor_gib:
        if waited >= GATE_MAX_WAIT_S:
            return False
        print(f"    low memory: {meminfo_gib('MemAvailable'):.1f} < "
              f"{floor_gib:.1f} GiB; waiting {GATE_POLL_S}s (waited {waited}s)",
              flush=True)
        time.sleep(GATE_POLL_S)
        waited += GATE_POLL_S
    return True


def log_failure(slug, stage_index, cmd, returncode, kind) -> None:
    FAIL_LOG.parent.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).isoformat(timespec="seconds")
    with open(FAIL_LOG, "a") as f:
        f.write(json.dumps(dict(ts=ts, slug=slug, stage_index=stage_index,
                                cmd=cmd, returncode=returncode, kind=kind)) + "\n")


def bootstrap() -> None:
    """One-time, idempotent global data: Natural Earth + global GEBCO."""
    for cmd in ("bash pipeline/download_naturalearth.sh",
                "python pipeline/download_gebco.py"):
        print(f"[bootstrap] {cmd}", flush=True)
        if subprocess.run(cmd, shell=True, cwd=ROOT, env=ENV).returncode != 0:
            sys.exit(f"bootstrap failed: {cmd} — cannot proceed without it")


def prune_intermediates(slug: str) -> None:
    """Reclaim a country's regenerable intermediates once its hero exists — the
    fused rasters, warp dir, and scene file. The hero PNG and the shared raw
    GLO-30/GEBCO tiles are kept. Used by --clean to keep a full sweep within
    disk (a near-global run accretes ~500 GB of tiles + fusions otherwise)."""
    work = ROOT / f"data/work/{slug}"
    if work.exists():
        shutil.rmtree(work)
    (ROOT / f"blender/{slug}_hero.blend").unlink(missing_ok=True)
    print(f"    cleaned intermediates for {slug}", flush=True)


def run_country(slug, r, through, force, dry, cap_gib, use_cap, floor,
                clean) -> str:
    """Run one country's stages; return a short outcome string."""
    do_clean = clean and through == "render" and not dry
    target = (ROOT / f"blender/renders/heroes/{slug}.png" if through == "render"
              else ROOT / f"data/work/{slug}/render/snowmask_aea.png")
    if target.exists() and not force:
        if do_clean:
            prune_intermediates(slug)
        return "skip-done"

    n = 6 if through == "render" else PREP_STAGES
    stages = stage_commands(r)[:n]
    if dry:
        return f"would-run ({n} stages)"

    for idx, cmd in enumerate(stages):
        if idx in GATE_STAGES and not wait_for_mem(floor):
            log_failure(slug, idx, cmd, None, "low-mem")
            return "skip-low-mem"
        prefix = ""
        if idx in CAP_STAGES and use_cap:
            prefix = (f"systemd-run --user --scope -q "
                      f"-p MemoryMax={int(cap_gib * 1024)}M "
                      f"-p MemorySwapMax=0 -- ")
        final = tmp = None
        run_cmd = cmd
        if idx == RENDER_STAGE:  # render to .tmp.png, promote atomically
            final = f"blender/renders/heroes/{slug}.png"
            tmp = f"blender/renders/heroes/{slug}.tmp.png"
            run_cmd = cmd.replace(final, tmp)
        rc = subprocess.run(prefix + run_cmd, shell=True, cwd=ROOT,
                            env=ENV).returncode
        if rc != 0:
            kind = "oom" if rc in (137, -9) else "error"
            if tmp:
                (ROOT / tmp).unlink(missing_ok=True)
            log_failure(slug, idx, cmd, rc, kind)
            return f"FAIL@{idx} ({kind})"
        if idx == RENDER_STAGE and tmp and final:
            # sky-view shading: darken land valleys for depth, before promoting
            sv = subprocess.run(
                f"python pipeline/sky_view.py --render-dir data/work/{slug}/render"
                f" --hero {tmp}", shell=True, cwd=ROOT, env=ENV).returncode
            if sv != 0:
                (ROOT / tmp).unlink(missing_ok=True)
                log_failure(slug, idx, "sky_view", sv, "error")
                return f"FAIL@{idx} (sky_view)"
            os.replace(ROOT / tmp, ROOT / final)
    if do_clean:
        prune_intermediates(slug)
    return "ok"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--through", choices=("prep", "render"), default="prep",
                    help="prep = download..snow (default); render adds the GPU render")
    ap.add_argument("--only", help="comma-separated slugs to run")
    ap.add_argument("--limit", type=int, help="cap the number of countries")
    ap.add_argument("--force", action="store_true", help="redo done countries")
    ap.add_argument("--dry-run", action="store_true", help="print the plan only")
    ap.add_argument("--mem-floor-gib", type=float, default=14.0,
                    help="min MemAvailable before starting a render")
    ap.add_argument("--clean", action="store_true",
                    help="render mode: delete each country's intermediates "
                         "(data/work/<slug> + .blend) once its hero lands, so a "
                         "full sweep stays within disk; keeps hero + raw tiles")
    args = ap.parse_args()

    if not args.dry_run:
        bootstrap()

    cfg = load_config()
    _sf, rows = load_ne_rows()
    scope = build_scope(cfg, rows)

    slugs = sorted(scope)
    if args.only:
        want = set(args.only.split(","))
        if unknown := want - set(slugs):
            sys.exit(f"unknown slugs: {sorted(unknown)}")
        slugs = [s for s in slugs if s in want]
    if args.limit:
        slugs = slugs[:args.limit]

    use_cap = False if args.dry_run else detect_cgroup_cap()
    cap_gib = 0.85 * meminfo_gib("MemTotal")
    print(f"batch: {len(slugs)} countries, through={args.through}, "
          f"mem-floor={args.mem_floor_gib:g} GiB, cgroup-cap="
          f"{f'{cap_gib:.0f} GiB' if use_cap else 'unavailable'}"
          f"{' [DRY-RUN]' if args.dry_run else ''}", flush=True)

    outcomes: dict[str, list[str]] = {}
    for slug in slugs:
        r = resolve(slug, scope[slug], cfg)
        if r is None:
            outcome = "skip-antimeridian"
        elif preflight_gebco(r["frame"]):
            outcome = "skip-gebco"
        else:
            outcome = run_country(slug, r, args.through, args.force,
                                  args.dry_run, cap_gib, use_cap,
                                  args.mem_floor_gib, args.clean)
        key = outcome.split(" ")[0].split("@")[0]
        outcomes.setdefault(key, []).append(slug)
        print(f"  {slug:28} {outcome}", flush=True)

    print("\nsummary: " + ", ".join(f"{k}={len(v)}"
                                    for k, v in sorted(outcomes.items())),
          flush=True)
    # roster the countries that did NOT produce output, by name, so a re-run is
    # informed at a glance (the JSONL has the per-run stage/returncode detail).
    attention = {k: v for k, v in sorted(outcomes.items())
                 if k.startswith("FAIL") or k == "skip-low-mem"}
    for k, v in attention.items():
        print(f"  {k} ({len(v)}): {', '.join(v)}", flush=True)
    if attention:
        print(f"re-run the same command to retry these; "
              f"per-run detail in {FAIL_LOG}", flush=True)
    return 1 if any(k.startswith("FAIL") for k in attention) else 0


if __name__ == "__main__":
    sys.exit(main())
