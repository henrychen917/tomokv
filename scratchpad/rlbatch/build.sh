#!/bin/bash
# The replay driver is not part of the server build; rebuild it here.
set -eu
cd "$(dirname "$0")"
gcc -O2 -Wall -Wextra -o replay replay.c
echo "built $(pwd)/replay"
