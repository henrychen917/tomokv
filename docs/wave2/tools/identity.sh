#!/bin/bash
# wave2 hot-body identity (docs/ttlclean method, stock tools, never runs a binary) of the integrated
# default build against the 991d48f65 default build (git archive, build/wave2/pre-src/build; its
# loadable sections equal bench-bins/tomokv-headline-991d48f65). The tools are run twice: with the
# selector as it was at 991d48f65 (tools copied from that commit) and with this branch's tools
# (HOT selection + ExLoopT<true>::prepare_local_read). Output: docs/wave2/identity/<label>-*.
# usage: identity.sh <label> [tools-dir]
set -u
cd /home/user/Projects/cx-wave2
label=$1; tools=${2:-tools}
PRE=build/wave2/pre-src/build
D=docs/wave2/identity; W=build/wave2/identity-$label; mkdir -p "$D" "$W"
: > "$D/$label-tool-exits.log"
taskset -c 80-95 python3 $tools/lbstall_artifacts.py compare $PRE build $W/hot.json > "$D/$label-hot.log" 2>&1
echo "lbstall exit=$?" >> "$D/$label-tool-exits.log"
rm -rf "$W/full"
taskset -c 80-95 python3 $tools/ccfix_audit.py $PRE build $W/full > "$D/$label-full.log" 2>&1
echo "ccfix exit=$?" >> "$D/$label-tool-exits.log"
taskset -c 80-95 python3 docs/deadswitch/linked_bytes.py $PRE/tomokv build/tomokv $W/linked.json > "$D/$label-linked.log" 2>&1
echo "linked exit=$?" >> "$D/$label-tool-exits.log"
echo DONE >> "$D/$label-tool-exits.log"
