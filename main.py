"""Forecast GTA VI's launch-day hourly Twitch viewers as five quantiles an hour.

The case gives hour 1's print and 38-42 past big launches' hourly category
counts, each from 14 days before its own release day to 3 days after.  Those
launches are the model.  For every comparable we take its log-ratio curve

    r_c(h) = ln(v_c(h) / v_c(1)),   h = 1..24

at hour offsets h-1 from its own release-day midnight: that cancels the
launch's size and keeps its shape, how the audience moved on from the first
hour of its release day.  Hour 1 of the case anchors the level; the shape is a
weighted median of the comparables' shapes, and the spread is the same
weighted distribution of shapes, scaled to its calibrated width.

A comparable counts more when its hour-1 level is close to the case's (in
logs), when its jump into hour 1 relative to its own preceding six hours looks
like the case's, and when it is recent.  Launches whose release day was
contaminated by an earlier early-access release count less; free-to-play and
slow-burn launches less still, since GTA VI is a paid console launch.

Reads every *.in under MAKEFUN_INPUT_DIR (default /input), writes <id>.out
under MAKEFUN_OUTPUT_DIR (default /output).  Standard library only, no
network, deterministic, far under the 8 s cap.
"""

import json
import math
import os
from datetime import datetime
from pathlib import Path

LEVELS = (0.05, 0.25, 0.5, 0.75, 0.95)
Z = (-1.6449, -0.6745, 0.0, 0.6745, 1.6449)   # standard normal at those levels

# Calibrated by leave-one-launch-out pinball loss over the kit's comparables.
SIGMA_LEVEL = 1.2     # log tolerance on the hour-1 level match
SIGMA_RAMP = 3.0      # log tolerance on the pre-launch ramp match
DECAY = 0.4           # per-year weight decay towards older launches
K_SPREAD = 0.75       # scale on the comparables' own shape spread
SIGMA_0 = 0.06        # unmodelled drift, per sqrt(hour - 1)
TIER_W = {"comp": 1.0, "ea": 0.6, "weak": 0.25}


def ts(value):
    s = str(value).strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    return datetime.fromisoformat(s).timestamp()


def tier_of(comp):
    note = comp.get("unlock") or ""
    if "target-history" in note:
        return "target"
    if "Tier: weak" in note:
        return "weak"
    if "Tier: early-access-contaminated" in note:
        return "ea"
    return "comp"


def hourly_offsets(hourly, base_ts):
    """Hour offset from the release-day midnight -> viewers."""
    out = {}
    for row in hourly or ():
        viewers = row.get("viewers")
        if not isinstance(viewers, (int, float)):
            continue
        try:
            off = int(round((ts(row["from"]) - base_ts) / 3600.0))
        except Exception:
            continue
        if -200 <= off <= 200:
            out[off] = float(viewers)
    return out


def ramp(curve):
    """ln(v(hour 1) / mean of the six hours before release day), or None."""
    v0 = curve.get(0)
    prev = [max(curve[-o], 1.0) for o in range(1, 7) if curve.get(-o) is not None]
    if not v0 or not prev:
        return None
    return math.log(max(v0, 1.0) / max(sum(prev) / len(prev), 1.0))


def shape_of(curve):
    """Log-ratio curve r(h) for h = 1..24, or None when an hour is missing."""
    v0 = curve.get(0)
    if not v0 or v0 <= 0:
        return None
    shape = [0.0]
    for off in range(1, 24):
        v = curve.get(off)
        if not v or v <= 0:
            return None
        shape.append(math.log(v / v0))
    return shape


def wquantile(pairs, q):
    """Weighted quantile of (value, weight) pairs."""
    if not pairs:
        return None
    pairs = sorted(pairs)
    total = sum(w for _, w in pairs)
    if total <= 0:
        return pairs[len(pairs) // 2][0]
    acc = 0.0
    for value, weight in pairs:
        acc += weight
        if acc >= q * total:
            return value
    return pairs[-1][0]


def candidates(case, p1, target_ramp, target_year):
    """(shape, weight) for every usable comparable."""
    bars = []
    for comp in case.get("comparables") or ():
        tier = tier_of(comp)
        if tier == "target":
            continue  # the game's own pre-release history has no launch day in it
        try:
            base = ts(comp["day_start"])
        except Exception:
            continue
        curve = hourly_offsets(comp.get("hourly"), base)
        shape = shape_of(curve)
        if shape is None:
            continue
        v0 = max(curve.get(0) or 1.0, 1.0)
        weight = TIER_W.get(tier, 0.25) * math.exp(-((math.log(v0 / p1)) / SIGMA_LEVEL) ** 2)
        r = ramp(curve)
        if r is not None and target_ramp is not None:
            weight *= math.exp(-((r - target_ramp) / SIGMA_RAMP) ** 2)
        try:
            year = int(str(comp.get("day_start"))[:4])
        except Exception:
            year = target_year
        weight *= math.exp(-DECAY * max(0, target_year - year))
        if weight > 1e-9:
            bars.append((shape, weight))
    return bars


def target_ramp_of(case):
    """The case's own ramp into hour 1, from history_hourly against day_start."""
    try:
        base = ts(case["day_start"])
    except Exception:
        return None
    curve = hourly_offsets(case.get("history_hourly"), base)
    return ramp(curve)


def forecast_case(case):
    known = case.get("known") or []
    p1 = 1.0
    if known:
        try:
            p1 = float(known[0].get("viewers") or 1.0)
        except Exception:
            p1 = 1.0
    p1 = max(p1, 1.0)

    try:
        target_year = int(str(case.get("day_start"))[:4])
    except Exception:
        target_year = 2026

    bars = candidates(case, p1, target_ramp_of(case), target_year)
    hours = [row.get("hour") for row in (case.get("forecast") or ()) if row.get("hour")]
    if not hours:
        hours = list(range(2, 25))

    log_p1 = math.log(p1)
    out = {"hours": []}
    for h in sorted(set(hours)):
        centre = log_p1
        qs = []
        if bars:
            pairs = [(shape[h - 1], weight) for shape, weight in bars]
            med = wquantile(pairs, 0.5)
            centre = log_p1 + med
            widening = SIGMA_0 * math.sqrt(h - 1)
            for tau, z in zip(LEVELS, Z):
                edge = (wquantile(pairs, tau) - med) * K_SPREAD
                qs.append(math.exp(centre + edge + z * widening))
        else:
            widening = SIGMA_0 * math.sqrt(h - 1)
            qs = [math.exp(centre + z * widening) for z in Z]
        floor = math.exp(centre) * 1e-3
        qs = [max(q, floor) for q in qs]
        for i in range(1, 5):
            if qs[i] < qs[i - 1]:
                qs[i] = qs[i - 1]
        out["hours"].append({"hour": h, "q": [round(q, 2) for q in qs]})
    return out


def main():
    in_dir = Path(os.environ.get("MAKEFUN_INPUT_DIR", "/input"))
    out_dir = Path(os.environ.get("MAKEFUN_OUTPUT_DIR", "/output"))
    out_dir.mkdir(parents=True, exist_ok=True)
    for path in sorted(in_dir.glob("*.in")):
        case = json.loads(path.read_text(encoding="utf-8"))
        cid = case.get("id") or path.stem
        (out_dir / (cid + ".out")).write_text(json.dumps(forecast_case(case)), encoding="utf-8")


if __name__ == "__main__":
    main()
