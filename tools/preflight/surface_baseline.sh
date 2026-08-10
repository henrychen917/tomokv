#!/usr/bin/env bash
# surface_baseline.sh -- materialise the PINNED surface baseline binary and print its path.
#
# WHY
#   surface_diff.sh is a differential gate: it asserts the observable surface (CONFIG names,
#   COMMAND names, INFO fields, DEBUG subcommands) is byte-identical between a base binary and the
#   candidate. Without a base that is genuinely a DIFFERENT build, bigstress compares the candidate
#   against itself, which is trivially identical and proves nothing -- which is why CASE
#   SURFACE-GATE reported INCONCLUSIVE rather than PASS. That verdict was correct; this supplies
#   the missing input.
#
# WHAT THE BASELINE IS
#   A specific reviewed commit, recorded in surface_baseline.sha, built once and cached. It is NOT
#   "the previous commit" -- a moving baseline would silently absorb every surface change one
#   commit at a time, which is precisely the regression this gate exists to catch. It moves only
#   when a human updates the .sha file, and the header of that file records why.
#
# USAGE
#   base=$(tools/preflight/surface_baseline.sh)   # builds if needed, prints path
#   tools/preflight/surface_baseline.sh --check   # verify cache without building; rc 1 if absent
#
#   bigstress picks this up automatically: SURFACE_BASE=$(surface_baseline.sh) if unset.
#
# COST
#   One full build the first time (several minutes), then free -- the cache is keyed by SHA, so it
#   is rebuilt only when the pin actually moves.
set -uo pipefail

DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
REPO=$(cd "$DIR/../.." && pwd)
PINFILE=$DIR/surface_baseline.sha
CACHE=${SURFACE_BASELINE_CACHE:-${TMPDIR:-/tmp}/tomo-surface-baseline}

die() { printf 'surface_baseline: %s\n' "$*" >&2; exit 1; }

[ -r "$PINFILE" ] || die "no pin file at $PINFILE"
SHA=$(grep -vE '^[[:space:]]*(#|$)' "$PINFILE" | head -1 | tr -d '[:space:]')
[ -n "$SHA" ] || die "pin file $PINFILE contains no SHA"

BINDIR=$CACHE/$SHA
BIN=$BINDIR/redis-server

if [ "${1:-}" = "--check" ]; then
    [ -x "$BIN" ] || { printf 'surface_baseline: not cached: %s\n' "$BIN" >&2; exit 1; }
    printf '%s\n' "$BIN"; exit 0
fi

if [ -x "$BIN" ]; then printf '%s\n' "$BIN"; exit 0; fi

git -C "$REPO" rev-parse --verify --quiet "$SHA^{commit}" >/dev/null \
    || die "pinned SHA $SHA is not a commit in $REPO (fetch it, or update the pin)"

# Build in a throwaway worktree so the caller's tree is never touched -- this may run from inside
# a suite that has the working tree in a specific state, and a stray checkout would corrupt it.
WT=$(mktemp -d "$CACHE/build.XXXXXX" 2>/dev/null) || { mkdir -p "$CACHE" && WT=$(mktemp -d "$CACHE/build.XXXXXX"); }
cleanup() { git -C "$REPO" worktree remove --force "$WT" >/dev/null 2>&1; rm -rf "$WT"; }
trap cleanup EXIT

rm -rf "$WT"
git -C "$REPO" worktree add --detach "$WT" "$SHA" >/dev/null 2>&1 \
    || die "could not create a worktree at $SHA"

# Same build the suites use. Serialised deliberately at -j4: this can be invoked from a harness
# that is about to measure, and saturating the box during a build is how a neighbouring
# measurement gets poisoned.
if ! make -C "$WT" -j4 >"$CACHE/build.$SHA.log" 2>&1; then
    die "baseline build failed; see $CACHE/build.$SHA.log"
fi
[ -x "$WT/src/redis-server" ] || die "build produced no redis-server; see $CACHE/build.$SHA.log"

mkdir -p "$BINDIR"
cp "$WT/src/redis-server" "$BIN"
cp "$WT/src/redis-cli" "$BINDIR/redis-cli" 2>/dev/null || true
chmod +x "$BIN"
printf '%s\n' "$BIN"
