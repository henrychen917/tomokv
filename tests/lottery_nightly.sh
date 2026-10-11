#!/bin/bash
# Opt-in only. No landing-gate rows or EXPECT constants change.
set -eu
cd "$(dirname "$0")/.."
exec taskset -c 112-127 python3 tests/lottery_runner.py --all "$@"
