#!/bin/bash
# wave3 hot-body identity (docs/ttlclean method, stock tools, never runs a binary) of the integrated
# default build against the f821104a9 default build (git archive, build/wave3/refs/pre-src/build; its
# loadable sections equal bench-bins/tomokv-headline-f821104a9). Output: docs/wave3/identity/<label>-*.
# usage: identity.sh <label> [tools-dir]
set -u
cd /home/user/Projects/cx-wave3
label=$1; tools=${2:-tools}
PRE=build/wave3/refs/pre-src/build
D=docs/wave3/identity; W=build/wave3/identity-$label; mkdir -p "$D" "$W"
: > "$D/$label-tool-exits.log"
taskset -c 80-95 python3 $tools/lbstall_artifacts.py compare $PRE build $W/hot.json > "$D/$label-hot.log" 2>&1
echo "lbstall exit=$?" >> "$D/$label-tool-exits.log"
rm -rf "$W/full"
taskset -c 80-95 python3 $tools/ccfix_audit.py $PRE build $W/full > "$D/$label-full.log" 2>&1
echo "ccfix exit=$?" >> "$D/$label-tool-exits.log"
taskset -c 80-95 python3 docs/deadswitch/linked_bytes.py $PRE/tomokv build/tomokv $W/linked.json > "$D/$label-linked.log" 2>&1
echo "linked exit=$?" >> "$D/$label-tool-exits.log"
echo DONE >> "$D/$label-tool-exits.log"
