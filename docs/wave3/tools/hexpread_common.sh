#!/bin/bash
# wave3: hexpread's ordinary lazy-expiry replies / notifications / INFO deltas (docs/hexpread/common.py)
# against a FRESH Redis 7.4.10 oracle run and the lane's committed oracle observations; target in both
# modes x atomic 0/1. Oracle on 88 (port 22881), target servers 80-87 (port 22882), driver 89-95.
# usage: hexpread_common.sh <out-dir>
set -u
cd /home/user/Projects/cx-wave3
OUT=$(realpath -m "$1"); mkdir -p "$OUT"
: > "$OUT/summary.txt"
taskset -c 89-95 python3 docs/hexpread/common.py --binary /home/user/Projects/redis74/src/redis-server --oracle \
  --artifacts "$OUT/oracle" --cores 88 --port 22881 > "$OUT/oracle.log" 2>&1
echo "oracle rc=$?" | tee -a "$OUT/summary.txt"
cmp "$OUT/oracle/common.json" docs/hexpread/common-oracle-resp3/common.json > "$OUT/oracle-vs-committed.txt" 2>&1
echo "fresh-oracle-equals-committed rc=$?" | tee -a "$OUT/summary.txt"
for mode in 1s 2s; do for atomic in 0 1; do
  taskset -c 89-95 python3 docs/hexpread/common.py --binary build/tomokv --artifacts "$OUT/$mode-atomic$atomic" \
    --mode $mode --cores 80-87 --port 22882 --atomic $atomic --compare "$OUT/oracle/common.json" \
    > "$OUT/$mode-atomic$atomic.log" 2>&1
  echo "$mode atomic=$atomic rc=$?" | tee -a "$OUT/summary.txt"
done; done
