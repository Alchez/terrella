#!/usr/bin/env bash
# Measure whether MapLibre's parallel image-request cap is worth moving off its default of 16.
#
# WHY THIS IS A MEASUREMENT AND NOT A SETTING. Over HTTP/2 every tile shares one connection, so
# concurrency divides bandwidth rather than adding it — fewer streams finish sooner, and a tile
# that has finished is a tile that has painted. But an edge-cold tile is latency-bound (~440 ms
# TTFB, measured) and parallelism is exactly what overlaps latency. The two effects
# pull opposite ways and which one wins depends on cache state and link speed. "Leave it at 16"
# is a perfectly good outcome; guessing a number is not.
#
# RUN THIS AGAINST PRODUCTION. The tile Worker's ALLOWED_ORIGIN is the site's own origin, so a
# locally served shell is refused every tile and would measure nothing.
#
# Two things this script refuses to let you get wrong:
#
#   1. `--throttling-method=devtools`, not Lighthouse's default `simulate`. Under simulation the
#      network timings in the trace come from an UNTHROTTLED pass and only the headline metrics
#      are modelled — so a network-shaped change can look like it did nothing at all.
#   2. It asserts the flag actually took effect, by recomputing peak concurrency from the trace
#      and comparing it to the rung requested. A run that silently fell back to the default would
#      otherwise produce exactly the "no difference between rungs" result being tested for.
#
# Usage:  ./scripts/measure_tile_concurrency.sh [runs-per-rung]   (default 3)

set -euo pipefail

URL_BASE="${URL_BASE:-https://terrella.alchez.dev/earth/}"
RUNS="${1:-3}"
RUNGS=(4 8 16 32)
OUT="${OUT:-/tmp/tile-concurrency}"
CHROME_FLAGS="--headless=new --no-sandbox --enable-unsafe-swiftshader --use-gl=angle --use-angle=swiftshader"

mkdir -p "$OUT"
echo "url=$URL_BASE  runs/rung=$RUNS  rungs=${RUNGS[*]}  out=$OUT"

for rung in "${RUNGS[@]}"; do
  for run in $(seq 1 "$RUNS"); do
    target="${URL_BASE}?maxreq=${rung}"
    echo "  rung=${rung} run=${run} ..."
    npx lighthouse "$target" \
      --output=json --output-path="$OUT/lh-${rung}-${run}.json" \
      --only-categories=performance --quiet \
      --throttling-method=devtools \
      --chrome-flags="$CHROME_FLAGS"
  done
done

python3 - "$OUT" "$RUNS" <<'PY'
import glob, json, os, statistics, sys

out_dir, runs = sys.argv[1], int(sys.argv[2])
print(f"\n{'rung':>5} {'runs':>5} {'LCP med':>9} {'TBT med':>9} {'tile window med':>16} {'peak conc':>10}")

for rung in (4, 8, 16, 32):
    lcp, tbt, window, peaks = [], [], [], []
    for path in sorted(glob.glob(os.path.join(out_dir, f"lh-{rung}-*.json"))):
        report = json.load(open(path))
        audits = report["audits"]
        lcp.append(audits["largest-contentful-paint"]["numericValue"])
        tbt.append(audits["total-blocking-time"]["numericValue"])
        items = audits.get("network-requests", {}).get("details", {}).get("items", [])
        tiles = [i for i in items if "tiles.terrella" in i.get("url", "")]
        if not tiles:
            continue
        window.append(max(t["networkEndTime"] for t in tiles)
                      - min(t["networkRequestTime"] for t in tiles))
        # Peak concurrency, recomputed from the trace: the guard that the flag actually applied.
        edges = sorted([(t["networkRequestTime"], 1) for t in tiles]
                       + [(t["networkEndTime"], -1) for t in tiles])
        live = peak = 0
        for _, delta in edges:
            live += delta
            peak = max(peak, live)
        peaks.append(peak)
    if not lcp:
        print(f"{rung:>5}     -  (no reports found)")
        continue
    observed = max(peaks) if peaks else 0
    # `observed == rung` is the WRONG assertion for a high rung: peak concurrency is bounded by
    # how many tiles are ever wanted at once (~36 on a desktop viewport, fewer on a small one), so
    # a cap above demand simply never binds and would read as a failure. What must never happen is
    # exceeding the cap; and a peak that lands exactly on the default is the one ambiguous case,
    # since it cannot be told apart from a silent fallback.
    if observed > rung:
        flag = f"  <-- CAP EXCEEDED (saw {observed}, cap {rung}) — flag not applied"
    elif observed < rung:
        flag = f"  <-- cap not binding (demand peaked at {observed})"
        if observed == 16 and rung != 16:
            flag += " — AMBIGUOUS: indistinguishable from a silent fallback to the default"
    else:
        flag = ""
    print(f"{rung:>5} {len(lcp):>5} {statistics.median(lcp):>8.0f}ms {statistics.median(tbt):>8.0f}ms "
          f"{statistics.median(window) if window else 0:>15.0f}ms {observed:>10}{flag}")

print("\nRead the spread, not just the median: Lighthouse variance on this page has been measured "
      "larger than most effects worth chasing: score 48/TBT 2120 vs 53/TBT 3300 on identical\n"
      "input. If the rungs sit inside each other's spread, the honest answer is 'leave it at 16'.")
PY
