#!/usr/bin/env bash
# Build a BOLT-ready server, collect a user-driven serving profile under perf,
# and write an optimized binary without replacing the sampled input image.
set -euo pipefail

usage() {
    cat >&2 <<EOF
usage: ${0##*/} <empty-profile-directory> -- [redis-server arguments...]

The server runs in the foreground under perf.  Drive the representative
workload from another terminal, then shut the server down cleanly.
EOF
}

if [[ ${1:-} == -h || ${1:-} == --help ]]; then
    usage
    exit 0
fi
if [[ $# -lt 2 ]]; then
    usage
    exit 2
fi

profile_dir=$1
shift
if [[ $1 != -- ]]; then
    usage
    exit 2
fi
shift

if ! command -v llvm-bolt >/dev/null 2>&1; then
    printf '%s\n' 'bolt_cycle: llvm-bolt not found; install LLVM BOLT and rerun (BOLT cycle skipped).' >&2
    exit 0
fi
if ! command -v perf2bolt >/dev/null 2>&1; then
    printf '%s\n' 'bolt_cycle: perf2bolt not found; install the LLVM BOLT tools and rerun (BOLT cycle skipped).' >&2
    exit 0
fi
if ! command -v perf >/dev/null 2>&1; then
    printf '%s\n' 'bolt_cycle: perf not found; install Linux perf and rerun (BOLT cycle skipped).' >&2
    exit 0
fi

root=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
case $profile_dir in
    /*) ;;
    *) profile_dir=$PWD/$profile_dir ;;
esac

mkdir -p "$profile_dir"
profile_dir=$(cd "$profile_dir" && pwd)
if [[ -n $(find "$profile_dir" -mindepth 1 -print -quit) ]]; then
    printf 'bolt_cycle: profile directory must be empty: %s\n' "$profile_dir" >&2
    printf 'bolt_cycle: use a fresh directory to keep the sampled binary and profile paired.\n' >&2
    exit 2
fi

server_name=redis-server${PROG_SUFFIX:-}
built_server=$root/src/$server_name
bolt_input=$profile_dir/$server_name.bolt-input
perf_data=$profile_dir/perf.data
fdata=$profile_dir/perf.fdata
output=$profile_dir/$server_name.bolt

# BOLT needs relocations in the linked image.  GCC block partitioning must also
# be disabled so BOLT can safely split and reorder the resulting functions.
make -C "$root/src" USE_URING=yes PROG_SUFFIX="${PROG_SUFFIX:-}" server-clean
make -C "$root/src" USE_URING=yes \
    PROG_SUFFIX="${PROG_SUFFIX:-}" \
    REDIS_SERVER_CFLAGS="-fno-reorder-blocks-and-partition" \
    REDIS_SERVER_LDFLAGS="-fno-reorder-blocks-and-partition -Wl,--emit-relocs" \
    "$server_name"
cp "$built_server" "$bolt_input"

printf '\nBOLT input ready: %s\n' "$bolt_input"
printf '%s\n' \
    'The server will now run in the foreground under perf.' \
    'Drive the representative workload from another terminal, then shut the server down cleanly.'

if ! perf record -e cycles:u -j any,u -o "$perf_data" -- "$bolt_input" "$@" --daemonize no; then
    printf '%s\n' 'bolt_cycle: perf record failed; no BOLT binary was produced.' >&2
    exit 1
fi

perf2bolt -p "$perf_data" -o "$fdata" "$bolt_input"
llvm-bolt "$bolt_input" -o "$output" -data="$fdata" \
    -reorder-blocks=ext-tsp \
    -reorder-functions=hfsort \
    -split-functions

printf 'BOLT optimized binary ready: %s\n' "$output"
