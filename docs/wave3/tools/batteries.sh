#!/bin/bash
# wave3: the lane batteries on the integrated binary, one after another (never alongside the gate),
# CPUs 80-95, ports 22840-22899. Each step logs its exit code to build/wave3/batteries/exits.txt.
set -u
cd /home/user/Projects/cx-wave3
B=build/wave3/batteries; mkdir -p "$B"
step(){ local name=$1; shift; local start=$(date +%s); echo "=== $name $(date -Is)" >> "$B/exits.txt"; "$@" > "$B/$name.log" 2>&1; echo "$name rc=$? seconds=$(( $(date +%s) - start ))" | tee -a "$B/exits.txt"; }
# respresume: limits corpus (PRE f821104a9 vs integrated vs Redis) and TLS fragment corpus, both engines, both modes
for mode in 1s 2s; do for engine in uring epoll; do
  step rr-limits-$mode-$engine docs/wave3/tools/rr_limits.sh $mode $engine $B/rr-limits-$mode-$engine
  step rr-tlsfrag-$mode-$engine docs/wave3/tools/rr_tlsfrag.sh $mode $engine $B/rr-tlsfrag-$mode-$engine
done; done
# aoforder: aoforder's hash-expiry live-tear probe (fixed by hexpread HX-1) and its five persistence proof parts
step hash-expiry taskset -c 80-95 python3 docs/wave3/tools/hash_expiry_run.py $B/hash-expiry
for part in primary drivers rewrite snapshot supplementary; do
  step aoforder-$part taskset -c 80-95 python3 docs/wave3/tools/aoforder_persist_proof.py --binary build/tomokv --output $B/aoforder-$part --part $part
done
# hexpread: notifications/INFO vs a fresh Redis 7.4.10 oracle, atomic batteries in both modes
step hexpread-common docs/wave3/tools/hexpread_common.sh $B/hexpread-common
step atomic-batteries docs/wave3/tools/atomic_batteries.sh $B/atomic-batteries
# rlfix: read-local witnesses + RYOW/B+/lane batteries (integrated), and the PRE negative control
step rlfix-post taskset -c 80-95 python3 docs/wave3/tools/rlfix_check.py build/tomokv $B/rlfix-post --cases miss delete --atomics 0 1 --batteries
step rlfix-pre-negative taskset -c 80-95 python3 docs/wave3/tools/rlfix_check.py build/wave3/refs/pre-src/build/tomokv $B/rlfix-pre --cases miss delete --atomics 0 1 --negative
# mkfix2 A+B (C reverted): WB replies/send (uninstrumented) and allocation counts (scratch LD_PRELOAD counter)
step mkfix-wb taskset -c 80-95 python3 docs/wave3/tools/mkfix_counts_w3.py --binary build/tomokv --output $B/mkfix-wb
step mkfix-alloc taskset -c 80-95 python3 docs/wave3/tools/mkfix_counts_w3.py --binary build/tomokv --shim build/wave3/mkcount/mkcount.so --output $B/mkfix-alloc
echo "BATTERIES-DONE $(date -Is)" >> "$B/exits.txt"
