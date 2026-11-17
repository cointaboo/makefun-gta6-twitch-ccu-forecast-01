"""Forecast GTA VI's launch-day hourly Twitch viewers as five quantiles an hour.

The case gives hour 1's print and 38-42 past big launches' hourly category
counts, each from 14 days before its own release day to 3 days after.  Those
launches are the model.

Two views of them are combined.  Each comparable becomes a log-ratio curve
r(h) = ln(v(h) / v(1)) at hour offsets from its own release-day midnight, which
removes the launch's size and keeps the shape: how the audience moved on from
the first hour of its release day.  Across the comparables, ln v(h) is also fit
on ln v(1) hour by hour (weighted least squares), so a launch whose first hour
is small or large gets a shape read off the level it actually had.  The centre
of the forecast is that fitted line at the case's own hour-1 print; the width
is a robust scale of the fit's residuals, sigma = sqrt(wmedian(resid^2)),
turned into quantiles as K_SPREAD * z * sigma.

Comparables are weighted by how close their hour-1 print is to the case's (in
logs), by recency, and by tier: a release day contaminated by an earlier
early-access release, or a free-to-play or slow-burn launch, counts for less,
since GTA VI is a paid console launch.  Comparables whose first hour sat far
below their own day's peak (an unlock later in the day, so their hour 1 was
pre-release and their shape belongs to a different clock) are dropped.

The case's own hour 1 is the first hour of the UTC day while the game unlocks
at midnight local time, so the United States joins hours later and the day's
audience keeps climbing into the American afternoon; a small positive tilt with
the hour carries that, and it is what the practice launches show.

Reads every *.in under MAKEFUN_INPUT_DIR (default /input), writes <id>.out
under MAKEFUN_OUTPUT_DIR (default /output).  Standard library only, no network,
deterministic, far under the 8 second cap.
"""

import json
import math
import os
from datetime import datetime
from pathlib import Path

LEVELS = (0.05, 0.25, 0.5, 0.75, 0.95)
Z = (-1.6449, -0.6745, 0.0, 0.6745, 1.6449)   # standard normal at those levels

# Calibrated on the kit's four practice launches and on leave-one-out fits over
# the comparables themselves.
SIGMA_LEVEL = 0.85    # log tolerance on the hour-1 level match
DECAY = 0.4           # per-year weight decay towards older launches
RIDGE = 0.05          # ridge on the per-hour log-log fit
TILT = 0.4            # log widening of the centre, per hour after noon
K_SPREAD = 0.80       # scale on the robust residual sigma
V0R_LO = 0.05         # drop comparables whose hour 1 was under 5% of their peak
V0R_HI = 1.0
TIER_W = {"comp": 1.0, "ea": 0.55, "weak": 0.25}


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


def hourly_offsets(hourly, base):
    out = {}
    for row in hourly or ():
        viewers = row.get("viewers")
        if not isinstance(viewers, (int, float)):
            continue
        try:
            off = int(round((ts(row["from"]) - base) / 3600.0))
        except Exception:
            continue
        if -200 <= off <= 200:
            out[off] = float(viewers)
    return out


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


def wls(xs, ys, ws):
    """Weighted least squares y = a + b x, with a ridge on the slope."""
    sw = sum(ws)
    if sw <= 0:
        return 0.0, 0.0
    mx = sum(w * x for x, w in zip(xs, ws)) / sw
    my = sum(w * y for x, y, w in zip(xs, ys, ws)) / sw
    sxx = sum(w * (x - mx) ** 2 for x, w in zip(xs, ws)) + RIDGE
    sxy = sum(w * (x - mx) * (y - my) for x, y, w in zip(xs, ys, ws))
    slope = sxy / sxx if sxx > 1e-12 else 0.0
    return my - slope * mx, slope


def candidates(case, p1, target_year):
    """(log v1, shape, weight) for every usable comparable."""
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
        peak = max([curve.get(o) or 0.0 for o in range(24)])
        v0 = curve.get(0) or 0.0
        if peak <= 0 or not (V0R_LO <= v0 / peak <= V0R_HI):
            continue
        weight = TIER_W.get(tier, 0.25) * math.exp(-((math.log(v0 / p1)) / SIGMA_LEVEL) ** 2)
        try:
            year = int(str(comp.get("day_start"))[:4])
        except Exception:
            year = target_year
        weight *= math.exp(-DECAY * max(0, target_year - year))
        if weight > 1e-12:
            bars.append((math.log(max(v0, 1.0)), shape, weight))
    return bars


def forecast_case(case):
    known = case.get("known") or []
    p1 = 1.0
    if known:
        try:
            p1 = float(known[0].get("viewers") or 1.0)
        except Exception:
            p1 = 1.0
    p1 = max(p1, 1.0)
    log_p1 = math.log(p1)

    try:
        target_year = int(str(case.get("day_start"))[:4])
    except Exception:
        target_year = 2026

    bars = candidates(case, p1, target_year)
    hours = [row.get("hour") for row in (case.get("forecast") or ()) if row.get("hour")]
    if not hours:
        hours = list(range(2, 25))

    out = {"hours": []}
    for h in sorted(set(hours)):
        tilt = TILT * max(0.0, h - 12) / 10.0
        if bars:
            xs = [b[0] for b in bars]
            ys = [b[0] + b[1][h - 1] for b in bars]
            ws = [b[2] for b in bars]
            intercept, slope = wls(xs, ys, ws)
            centre = intercept + slope * log_p1 + tilt
            # Width from the fit's own residuals, not from the spread of the
            # comparables' shape quantiles.  A shape curve r(h) only divides out
            # each launch's own hour 1, so two comparables with the same
            # underlying shape but different levels still land at different
            # r(h) -- the slope term is exactly what carries that level
            # difference.  Taking a quantile spread of the raw shapes about
            # their median therefore counts the between-comparable level gaps
            # as if they were shape uncertainty, and the band comes out too
            # wide (and lopsided, since the shape distribution is skewed).  The
            # residuals resid = y - (intercept + slope*x) are what the fit did
            # not explain; a weighted median of resid^2 is a robust scale of
            # that, immune to a single odd launch.
            resid2 = [((y - (intercept + slope * x)) ** 2, w)
                      for x, y, w in zip(xs, ys, ws)]
            sigma = math.sqrt(max(wquantile(resid2, 0.5), 0.0))
            widths = [K_SPREAD * z * sigma for z in Z]
        else:
            centre = log_p1
            widths = [0.0] * 5
        qs = [math.exp(centre + wdt) for wdt in widths]
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
