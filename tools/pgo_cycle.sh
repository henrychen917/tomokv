#!/usr/bin/env bash
# Build an instrumented server, wait for a user-driven workload, then rebuild
# the server from the resulting GCC profile.  The workload is deliberately not
# embedded here: it must be the representative serving workload being tuned.
set -euo pipefail

usage() {
    printf 'usage: %s <empty-profile-directory>\n' "${0##*/}" >&2
}

if [[ ${1:-} == -h || ${1:-} == --help ]]; then
    usage
    exit 0
fi
if [[ $# -ne 1 ]]; then
    usage
    exit 2
fi
if [[ ! -t 0 ]]; then
    printf '%s\n' 'pgo_cycle: an interactive terminal is required for the workload pause.' >&2
    exit 2
fi

root=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
profile_dir=$1
if [[ $profile_dir =~ [[:space:]] ]]; then
    printf '%s\n' 'pgo_cycle: the GCC profile directory must not contain whitespace.' >&2
    exit 2
fi
case $profile_dir in
    /*) ;;
    *) profile_dir=$PWD/$profile_dir ;;
esac

mkdir -p "$profile_dir"
profile_dir=$(cd "$profile_dir" && pwd)
if [[ -n $(find "$profile_dir" -mindepth 1 -print -quit) ]]; then
    printf 'pgo_cycle: profile directory must be empty: %s\n' "$profile_dir" >&2
    printf 'pgo_cycle: use a fresh directory so profiles from different builds are not merged.\n' >&2
    exit 2
fi

# Step 1: build-generate.  The Make target cleans stale server objects and
# applies -fprofile-generate only to the server objects and server link.
make -C "$root" pgo-generate PGO_PROFILE_DIR="$profile_dir"

server_bin=$root/src/redis-server${PROG_SUFFIX:-}
printf '\nPGO generate build ready: %s\n' "$server_bin"
printf '%s\n' \
    'Run the representative workload against this binary now.' \
    'When it finishes, shut the server down cleanly so GCC flushes its profile.' \
    'Press Enter only after the instrumented server has exited.'
read -r _

# Step 2 is the user-run workload above.  Refuse the use build when the
# instrumented process did not emit any profile data.
if [[ -z $(find "$profile_dir" -type f -name '*.gcda' -print -quit) ]]; then
    printf 'pgo_cycle: no GCC profile data found in %s; use build not started.\n' "$profile_dir" >&2
    exit 1
fi

# Step 3: build-use.  This cleans the instrumented objects but leaves the
# caller-owned profile directory intact, then applies profile-use/correction.
make -C "$root" pgo-use PGO_PROFILE_DIR="$profile_dir"
printf 'PGO use build ready: %s\n' "$server_bin"
