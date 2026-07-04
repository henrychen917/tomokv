#!/usr/bin/env bash
# Launch (or arm) the knobtune sweep with reboot/stall recovery.
# Usage: knobtune_launch.sh <deadline_epoch> [bench_secs] [--fresh]
# Writes knobtune.state consumed by knobtune_watchdog.sh (cron */5 + @reboot).
set -u
OUT=/shared/Projects/overnight_sweep
DL=${1:?usage: knobtune_launch.sh <deadline_epoch> [bench_secs] [--fresh]}
TT=${2:-9}
[ "${3:-}" = "--fresh" ] && rm -f $OUT/knobtune.tsv $OUT/knobtune.log $OUT/knobtune_stdout.log
printf 'DEADLINE=%s\nT=%s\n' "$DL" "$TT" > $OUT/knobtune.state
exec $OUT/knobtune_watchdog.sh --now
