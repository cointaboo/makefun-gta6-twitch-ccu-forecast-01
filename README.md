# makefun-gta6-twitch-ccu-forecast-01

[![make.fun · gta6-twitch-ccu-forecast-01](https://make.fun/badge/gta6-twitch-ccu-forecast-01.svg)](https://make.fun/bounty/gta6-twitch-ccu-forecast-01?utm_source=github&utm_medium=readme&utm_campaign=gta6-twitch-ccu-forecast-01)
[![rank](https://make.fun/badge/gta6-twitch-ccu-forecast-01/cointaboo/makefun-gta6-twitch-ccu-forecast-01/rank.svg)](https://make.fun/bounty/gta6-twitch-ccu-forecast-01/leaderboard?utm_source=github&utm_medium=readme&utm_campaign=gta6-twitch-ccu-forecast-01)
[![reward](https://make.fun/badge/gta6-twitch-ccu-forecast-01/cointaboo/makefun-gta6-twitch-ccu-forecast-01/reward.svg)](https://make.fun/bounty/gta6-twitch-ccu-forecast-01?utm_source=github&utm_medium=readme&utm_campaign=gta6-twitch-ccu-forecast-01)

A forecaster for GTA VI's launch-day Twitch concurrent viewers, entered in
[make.fun/bounty/gta6-twitch-ccu-forecast-01](https://make.fun/bounty/gta6-twitch-ccu-forecast-01).

## What it does

`main.py` reads one case (hour 1's print plus 38–42 past big launches' hourly
category counts) and writes, for hours 2–24 of the release day, five quantiles
(5%, 25%, 50%, 75%, 95%) of that hour's viewer count.

The model is a similarity-weighted comparables forecaster in log space. Each
comparable becomes a log-ratio curve `r(h) = ln(v(h) / v(1))` at hour offsets
from its own release-day midnight, which removes the launch's size and keeps
its shape. Hour 1's print anchors the level; the shape is a weighted median of
the comparables' shapes, and the quantiles come from the same weighted
distribution of shapes, scaled to a width calibrated by leave-one-launch-out
pinball loss.

Weighting favours comparables whose hour-1 level is close to the case's (in
logs), whose jump into hour 1 over its preceding six hours looks like the
case's, and which are recent; early-access-contaminated release days and
free-to-play or slow-burn launches count for less.

## Run

```bash
mkdir -p out
MAKEFUN_INPUT_DIR=input MAKEFUN_OUTPUT_DIR=out python3 main.py
```

Python 3.13, standard library only, no network, deterministic, well under the
8 second cap per case.

## License

MIT — see [LICENSE](LICENSE).
