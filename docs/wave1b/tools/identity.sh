#!/bin/bash
# wave1b hot-body identity (docs/ttlclean method, stock tools, never runs a binary):
#   against origin/cpp 1ba80bd4e (git archive build, build/wave1b/refs/pre-src/build) and
#   against the bisection build b4 (b959fc844, lanes' own budgets; frozen copy build/wave1b/b4-build
#   of /home/user/Projects/bisect-w1/b4/build). Output: docs/wave1b/identity/<base>-*.
cd /home/user/Projects/cx-wave1b
D=docs/wave1b/identity; mkdir -p "$D" build/wave1b/identity
: > "$D/tool-exits.log"
for base in origin b4; do
  case $base in origin) PRE=build/wave1b/refs/pre-src/build;; b4) PRE=build/wave1b/b4-build;; esac
  taskset -c 112-127 python3 tools/lbstall_artifacts.py compare $PRE build build/wave1b/identity/$base-hot.json > "$D/$base-hot.log" 2>&1
  echo "$base lbstall exit=$?" >> "$D/tool-exits.log"
  rm -rf build/wave1b/identity/$base-full
  taskset -c 112-127 python3 tools/ccfix_audit.py $PRE build build/wave1b/identity/$base-full > "$D/$base-full.log" 2>&1
  echo "$base ccfix exit=$?" >> "$D/tool-exits.log"
  taskset -c 112-127 python3 docs/deadswitch/linked_bytes.py $PRE/tomokv build/tomokv build/wave1b/identity/$base-linked.json > "$D/$base-linked.log" 2>&1
  echo "$base linked exit=$?" >> "$D/tool-exits.log"
done
echo DONE >> "$D/tool-exits.log"
