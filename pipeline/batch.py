"""Batch runner: drive the whole pipeline across every in-scope country.

Reuses country_config's resolver (scope, frames, per-country stage commands)
and runs each country's stages as isolated subprocesses. Built to survive
abrupt shutdown (OOM / brownout / blackout):

  * Crash-safe resume. Every stage finalizes its outputs atomically (write
    .tmp, os.replace on success — see fuse_heightfield / render_prep /
    snow_mask), so a file at its final path always means "complete." Resume
    is therefore just filesystem existence: a country whose phase target
    exists is skipped; a partially-prepped one resumes stage-by-stage
    (each stage skips what it already finished). The renderer writes the raw
    Cycles frame to heroes/raw/<slug>.png (kept); sky_view then derives the
    shaded heroes/<slug>.png from it — so a cached raw skips the GPU and a look
    re-tune re-shades only. No durable in-memory state — a killed runner just
    re-runs and picks up where it left off.
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
  python -m pipeline.batch --dry-run                       # preview, run nothing
  python -m pipeline.batch --through prep                   # prep sweep (default)
  python -m pipeline.batch --through render --only bhutan   # one hero, end to end
"""

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

from pipeline import paths
from pipeline.frame.country_config import (
    build_scope,
    country_render_dir,
    country_work_dir,
    load_config,
    load_ne_rows,
    preflight_gebco,
    resolve,
    stage_commands,
)
from pipeline.profile import pass_memory
from pipeline.render import blender_proc, render_seam

#: The CHECKOUT, and the working directory every stage subprocess is run from — so the
#: checkout-relative paths in those commands (`pipeline/…`, `blender/…`) resolve. Data paths do NOT
#: hang off it; they come from `country_work_dir`, which follows the store.
ROOT = paths.ROOT


def stage_env() -> dict[str, str]:
    """The environment every stage subprocess runs under.

    Stage commands say "python …" assuming a venv-active shell, so this runner's own interpreter
    dir goes first on PATH and the subprocesses use the venv rather than the system one.

    THE REST IS `blender_proc`'s, INCLUDING FOR THE STAGES THAT ARE NOT BLENDER. One of these
    commands is the 8K hero render, which is the largest Cycles tile buffer this project produces
    and the stage the memory gate below is sized for — and that gate is defeated by exactly the
    tmpfs the buffer would otherwise fill. A per-stage env would mean deciding, at each stage,
    whether it is the Blender one; handing every stage the same environment cannot get that wrong.

    A function rather than a module constant, on `paths`' derive-at-call-time rule: frozen at
    import, a relocated `MAPS_DATA` would move the store and leave this pointing at the old one.
    """
    return blender_proc.env(
        PATH=f"{Path(sys.executable).parent}{os.pathsep}{os.environ.get('PATH', '')}")
FAIL_LOG = ROOT / "blender/renders/batch_failures.jsonl"
PREP_STAGES = 6           # stage_commands[:6] = download,mosaics,fuse,prep,snow,lake
RENDER_STAGE = 6          # scene_build --render
GATE_STAGES = {6}         # render: the 11-12 GB consumer the floor is set for
CAP_STAGES = {2, 6}       # fusion + render: best-effort cgroup containment
GATE_POLL_S = 30
GATE_MAX_WAIT_S = 1800    # wait up to 30 min for other load to clear, then skip


def meminfo_gib(key: str) -> float:
    with open("/proc/meminfo") as meminfo:
        for line in meminfo:
            if line.startswith(key + ":"):
                return int(line.split()[1]) / (1024 * 1024)  # kB -> GiB
    return 0.0


def detect_cgroup_cap() -> bool:
    """True if systemd --user scopes can enforce MemoryMax here (best-effort)."""
    if not shutil.which("systemd-run"):
        return False
    probe = ("systemd-run --user --scope -q -p MemoryMax=256M "
             "-p MemorySwapMax=0 -- true")
    return subprocess.run(probe, shell=True, capture_output=True, check=False).returncode == 0


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
    ts = datetime.now(UTC).isoformat(timespec="seconds")
    with open(FAIL_LOG, "a") as log_file:
        log_file.write(json.dumps(dict(
            ts=ts, slug=slug, stage_index=stage_index,
            cmd=cmd, returncode=returncode, kind=kind)) + "\n")


def bootstrap() -> None:
    """One-time, idempotent global data: Natural Earth + global GEBCO."""
    for cmd in ("bash pipeline/acquire/download_naturalearth.sh",
                "python -m pipeline.acquire.download_gebco"):
        print(f"[bootstrap] {cmd}", flush=True)
        if subprocess.run(cmd, shell=True, cwd=ROOT, env=stage_env(), check=False).returncode != 0:
            sys.exit(f"bootstrap failed: {cmd} — cannot proceed without it")


def prune_intermediates(slug: str) -> None:
    """Reclaim a country's regenerable intermediates once its hero exists — the
    fused rasters, warp dir, and scene file. The hero PNG and the shared raw
    GLO-30/GEBCO tiles are kept. Used by --clean to keep a full sweep within
    disk (a near-global run accretes ~500 GB of tiles + fusions otherwise)."""
    work = country_work_dir(slug)
    if work.exists():
        shutil.rmtree(work)
    (ROOT / f"blender/{slug}_hero.blend").unlink(missing_ok=True)
    print(f"    cleaned intermediates for {slug}", flush=True)


def run_country(slug, resolved, through, force, dry, cap_gib, use_cap, floor,
                clean) -> str:
    """Run one country's stages; return a short outcome string."""
    do_clean = clean and through == "render" and not dry
    target = (ROOT / f"blender/renders/heroes/{slug}.png" if through == "render"
              else country_render_dir(slug) / render_seam.LAKEDEPTH)
    if target.exists() and not force:
        if do_clean:
            prune_intermediates(slug)
        return "skip-done"

    stage_count = 7 if through == "render" else PREP_STAGES
    stages = stage_commands(resolved)[:stage_count]
    if dry:
        return f"would-run ({stage_count} stages)"

    for idx, cmd in enumerate(stages):
        if idx in GATE_STAGES and not wait_for_mem(floor):
            log_failure(slug, idx, cmd, None, "low-mem")
            return "skip-low-mem"
        prefix = ""
        if idx in CAP_STAGES and use_cap:
            prefix = (f"systemd-run --user --scope -q "
                      f"-p MemoryMax={int(cap_gib * 1024)}M "
                      f"-p MemorySwapMax=0 -- ")
        final = raw = raw_tmp = None
        run_cmd = cmd
        if idx == RENDER_STAGE:  # keep the raw Cycles frame; shade a derived hero
            final = f"blender/renders/heroes/{slug}.png"
            raw = f"blender/renders/heroes/raw/{slug}.png"
            raw_tmp = f"blender/renders/heroes/raw/{slug}.tmp.png"
            (ROOT / raw).parent.mkdir(parents=True, exist_ok=True)
            run_cmd = cmd.replace(final, raw_tmp)

        # Skip the GPU when a raw already exists (and we're not forcing): a look
        # re-tune then re-shades from the pristine raw with no re-render.
        if raw and raw_tmp and (ROOT / raw).exists() and not force:
            print(f"    {slug}: raw render cached — re-shading only, no GPU",
                  flush=True)
        else:
            rc = subprocess.run(prefix + run_cmd, shell=True, cwd=ROOT,
                                env=stage_env(), check=False).returncode
            if rc != 0:
                kind = "oom" if rc in (137, -9) else "error"
                if raw_tmp:
                    (ROOT / raw_tmp).unlink(missing_ok=True)
                log_failure(slug, idx, cmd, rc, kind)
                return f"FAIL@{idx} ({kind})"
            if raw and raw_tmp:
                os.replace(ROOT / raw_tmp, ROOT / raw)  # durable raw, atomic

        if raw and final:
            # sky-view shading darkens land valleys for depth; it reads the raw and
            # writes the shaded hero as a SEPARATE file (atomic, internal .tmp), so
            # the raw stays pristine and post-look tweaks never re-render.
            sv = subprocess.run(
                f"python -m pipeline.look.sky_view --render-dir {country_render_dir(slug)}"
                f" --hero {raw} --out {final}"
                f" --strength {resolved['sky_view_strength']}", shell=True,
                cwd=ROOT, env=stage_env(), check=False).returncode
            if sv != 0:
                log_failure(slug, idx, "sky_view", sv, "error")
                return f"FAIL@{idx} (sky_view)"
    if do_clean:
        prune_intermediates(slug)
    return "ok"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--through", choices=("prep", "render"), default="prep",
                    help="prep = download..lake (default); render adds the GPU render")
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
        slugs = [slug for slug in slugs if slug in want]
    if args.limit:
        slugs = slugs[:args.limit]

    use_cap = False if args.dry_run else detect_cgroup_cap()
    # THE CEILING IS A POLICY AND MUST NOT BE DERIVED FROM THE HOST. This read `0.85 *
    # MemTotal`, which scales the blast radius with the machine rather than bounding it, and it is
    # the one place in the tree that sized a cap that way. It also hid a real fault: the largest
    # hero under a base grid wants 17.0 GB, which dies loudly at the ratified cap below and would
    # have passed silently on a bigger box, shipping a hero lane that only works on big machines.
    cap_gib = pass_memory.HEAVY_JOB_GIB
    print(f"batch: {len(slugs)} countries, through={args.through}, "
          f"mem-floor={args.mem_floor_gib:g} GiB, cgroup-cap="
          f"{f'{cap_gib:.0f} GiB' if use_cap else 'unavailable'}"
          f"{' [DRY-RUN]' if args.dry_run else ''}", flush=True)

    # A CAP THAT SILENTLY BECOMES NO CAP IS THE ONE FAILURE THIS ANNOUNCEMENT EXISTS FOR. The status
    # line above carries `cgroup-cap=unavailable` as one field among four, which is invisible at the
    # head of a ten-hour run. Running on rather than refusing is deliberate and is about portability:
    # a box without systemd user scopes should still be able to render heroes. What it must not do is
    # let the operator believe the ratified ceiling is holding when nothing is enforcing it.
    if not use_cap and not args.dry_run:
        print(f"\n  !! NO CGROUP CAP IS IN FORCE. systemd --user scopes cannot enforce MemoryMax\n"
              f"     here, so the render stage runs with nothing bounding it and a bad frame can\n"
              f"     take the desktop with it. The ratified ceiling is {cap_gib:.0f} GiB\n"
              f"     (`pass_memory.HEAVY_JOB_GIB`) and this run cannot honour it.\n", flush=True)

    outcomes: dict[str, list[str]] = {}
    for slug in slugs:
        resolved = resolve(slug, scope[slug], cfg)
        if resolved is None:
            outcome = "skip-antimeridian"
        elif preflight_gebco(resolved["frame"]):
            outcome = "skip-gebco"
        else:
            outcome = run_country(slug, resolved, args.through, args.force,
                                  args.dry_run, cap_gib, use_cap,
                                  args.mem_floor_gib, args.clean)
        key = outcome.split(" ")[0].split("@")[0]
        outcomes.setdefault(key, []).append(slug)
        print(f"  {slug:28} {outcome}", flush=True)

    print("\nsummary: " + ", ".join(f"{key}={len(members)}"
                                    for key, members in sorted(outcomes.items())),
          flush=True)
    # roster the countries that did NOT produce output, by name, so a re-run is
    # informed at a glance (the JSONL has the per-run stage/returncode detail).
    attention = {key: members for key, members in sorted(outcomes.items())
                 if key.startswith("FAIL") or key == "skip-low-mem"}
    for key, members in attention.items():
        print(f"  {key} ({len(members)}): {', '.join(members)}", flush=True)
    if attention:
        print(f"re-run the same command to retry these; "
              f"per-run detail in {FAIL_LOG}", flush=True)
    return 1 if any(key.startswith("FAIL") for key in attention) else 0


if __name__ == "__main__":
    sys.exit(main())
