**Lane hexpirefix — T0 CD1, ready for mainline live validation**

Worktree/branch: `/home/user/Projects/cx-hexpirefix` / `cx-hexpirefix`.
Launch HEAD: `e279aeb4cf08ae2c39f26be679388b872fed4667`.
`git fetch origin cpp && git merge --no-edit origin/cpp` completed first: already up to date.
Implementation commit: `46bb9757b`. Directed test and gate commit: `f6b0d63c3`.
No push, server, load generator, benchmark, or gate was run. All builds and serverless tests used CPUs 112–127.

**Diagnosis and scope**

Confirmed the mechanism in `/home/user/Projects/round3-read/cmd-data.md:253` and `REGISTER.md` CD1.
At launch, `src/cmd/t_hash_ttl.cc:234–247` could install one deadline, fail a later `HashFieldTtl::set`,
and return before the sole command-side registration. `src/store/flatstore.h:1010` updates both the
active attention index and lazy gate. The zero gate bypasses reaping in `src/cmd/t_hash.cc:817`,
while `field_live` (`src/cmd/t_hash_ttl.cc:78`) independently filters deadline queries. This produces
HTTL = -2 with HGET still returning the field.

Two details refine the report's trigger: `new HashFieldTtl` runs only while the table is absent, so
it cannot fail on field 2 after field 1 has already acquired a deadline in this loop. Also, the
initial eight-slot TTL table does not grow on its second insertion. The directed proof instead
fails the second field-name string allocation inside `HashFieldTtl::set` (`t_hash_ttl.h:87–91`).
It uses two distinct 32-byte names, counts both matching allocations, and requires exactly one
failure plus exactly one stored deadline on a fresh shard.

`maxmemory` alone does not force this allocation to fail: `FlatStore::budget_admit`
(`flatstore.h:1622–1647`) checks before dispatch; the field-name allocation is ordinary C++ `new`.
The test configures a finite noeviction budget (seed bytes + 4096), proves admission, and uses the
existing `netcmd_unit.cc:14–23` allocation injector for the precise failure. There is no new
production DEBUG command, allocator hook, knob, or test-only branch in production code.

The shared handler covers HEXPIRE, HPEXPIRE, HEXPIREAT, and HPEXPIREAT
(`t_hash_ttl.cc:265–275`). HPERSIST allocates its result vector before mutation, then only erases
entries (`:313–335`); its allocation failure preserves both deadlines. There are no HSETEX,
HGETEX, or HGETDEL implementations in this tree. The snapshot field-TTL loader frees its private
candidate on allocation failure (`t_hash.cc:1599–1614`), before publication.

Separate existing sibling issue, unchanged: HSET/HMSET can update a prefix and return on a later
allocation failure (`t_hash.cc:914–926`) before clearing that prefix's old field TTLs. The existing
`collection-oom` / OPEN F05 witness in `tests/netcmd_unit.cc` already documents the partial mutation.
This was a code-only finding here; that separate failing witness was not run or repaired.

**Change**

Only `src/cmd/t_hash_ttl.cc` changes production behavior. Both allocation-error exits now break
into the existing finalization block (`:235–260`) before returning the same `ERR out of memory`.
Previously stored deadlines survive, get registered once, and remain enforceable. That same block
also refreshes cached TTL allocation bytes, finishes size accounting, cleans an empty table,
and emits the existing HEXPIRE notification for a changed prefix. Successful per-field replies,
conditions, deadline parsing, and commands that set no deadline retain their behavior.

No struct layout or runtime option changed. The release build compiled the existing assertions:
Op 336 / Client 1984 / ThreadCtx 1408 / Shard 1440 / FlatStore 944 / Rob<64> 192 /
AtomicEntry 144 / Config 624. `io_loop.h`, `wb.h`, and `reorder.cc` are untouched, so the conditional
writeback-witness requirement does not apply. Both thread modes are compiled; boots remain for mainline.

CD5 remains out of scope: the TTL gate is still per shard, so one TTL-bearing hash sends accesses
to unrelated hashes on that shard through the out-of-line reap probe. Its cost is unchanged and
unmeasured here; evaluating that cost against the 3% rule is a follow-up.

**Proof actually run**

`tests/hexpire_oom_checks.inc` is the single directed-test implementation, selected by
`netcmd-unit hexpire-oom`. It calls the real registered handlers and advances the shard clock
without sleeps. The 104 cases per database build cover all four verbs, compact-to-external and
expanded hashes, clean and notification handlers, separate lazy/active expiry, a first-field
allocation failure, result-vector failure, success controls, and HPERSIST success/failure.
The second-field case verifies the stored prefix before expiry. Active expiry must collect it
before any post-deadline hash read; lazy expiry requires HTTL and HGET to agree, and both paths
check the actual expired-field counter and survival of the unset second field. Byte accounting
and the gate's armed state are also checked. Failed fault arming is always a hard failure.

An initial extra attempt to inject `new (std::nothrow) HashFieldTtl` failed the arming assertion:
the linked jemalloc nothrow allocation did not pass through the existing throwing-new injector.
That constructor is source-audited, not claimed as injected coverage. The final test targets
allocations the injector intercepts; its strict arming and prefix assertions remain intact.

| Check | PRE (original handler restored) | POST |
|---|---|---|
| Release build and layout assertions | PASS | PASS |
| Directed battery, multi-DB implementation | CD1 fails in per-case controls | 104/104 PASS |
| Directed battery, databases=1 implementation | CD1 fails in per-case controls | 104/104 PASS |
| Four verbs × lazy/active × both database implementations | 16/16 expected exit-1 failures | included in passing batteries |
| Gate shell syntax / diff whitespace | not a runtime claim | PASS |
| Live boots, live battery, gate, performance | not run | not run |

POST output below occurred for **each** of `build/netcmd-unit` and `build/netcmd-unit-db0`, exit 0:

```text
ok: CD1 HEXPIRE:lazy compact/expanded clean/notify
ok: CD1 HEXPIRE:active compact/expanded clean/notify
ok: CD1 HPEXPIRE:lazy compact/expanded clean/notify
ok: CD1 HPEXPIRE:active compact/expanded clean/notify
ok: CD1 HEXPIREAT:lazy compact/expanded clean/notify
ok: CD1 HEXPIREAT:active compact/expanded clean/notify
ok: CD1 HPEXPIREAT:lazy compact/expanded clean/notify
ok: CD1 HPEXPIREAT:active compact/expanded clean/notify
ok: CD1 104 deterministic hash-field TTL cases
ok: netcmd hexpire-oom
```

Negative-control runner output (same tests, only the production handler object replaced):

```text
expected FAIL (exit 1): netcmd-unit-pre HEXPIRE:lazy
expected FAIL (exit 1): netcmd-unit-pre HEXPIRE:active
expected FAIL (exit 1): netcmd-unit-pre HPEXPIRE:lazy
expected FAIL (exit 1): netcmd-unit-pre HPEXPIRE:active
expected FAIL (exit 1): netcmd-unit-pre HEXPIREAT:lazy
expected FAIL (exit 1): netcmd-unit-pre HEXPIREAT:active
expected FAIL (exit 1): netcmd-unit-pre HPEXPIREAT:lazy
expected FAIL (exit 1): netcmd-unit-pre HPEXPIREAT:active
expected FAIL (exit 1): netcmd-unit-pre-db0 HEXPIRE:lazy
expected FAIL (exit 1): netcmd-unit-pre-db0 HEXPIRE:active
expected FAIL (exit 1): netcmd-unit-pre-db0 HPEXPIRE:lazy
expected FAIL (exit 1): netcmd-unit-pre-db0 HPEXPIRE:active
expected FAIL (exit 1): netcmd-unit-pre-db0 HEXPIREAT:lazy
expected FAIL (exit 1): netcmd-unit-pre-db0 HEXPIREAT:active
expected FAIL (exit 1): netcmd-unit-pre-db0 HPEXPIREAT:lazy
expected FAIL (exit 1): netcmd-unit-pre-db0 HPEXPIREAT:active
ok: 16 negative controls failed at the named assertion
```

Representative PRE diagnostics, both exit 1 at the named assertion:

```text
HEXPIRE: HTTL=-2 but HGET still serves first field; gate=0
FAIL: CD1: HGET must hide the expired prefix after OOM (HTTL == -2)
HEXPIRE: active reaped=0 expected=1 gate=0
FAIL: CD1: active expiry must collect the installed prefix after OOM
```

Logs: `build/hexpirefix/{build,pre-build,unit-rebuild,post-unit,post-db0-unit,negative-controls}.log`;
individual negative-control logs are alongside them. Negative controls run only the serverless
unit binary with fresh private shards; no data directory or listener is involved.

**Reproduce the builds and serverless proof**

Run in this worktree. Builds below do not start any server:

```bash
taskset -c 112-127 make -j16 all build/netcmd-unit build/netcmd-unit-db0
taskset -c 112-127 ./build/netcmd-unit hexpire-oom
taskset -c 112-127 ./build/netcmd-unit-db0 hexpire-oom
mkdir -p build/hexpirefix
git show e279aeb4cf08ae2c39f26be679388b872fed4667:src/cmd/t_hash_ttl.cc > build/hexpirefix/t_hash_ttl-pre.cc
cp build/tomokv build/hexpirefix/tomokv-post
```

Write the following to `build/hexpirefix/control.mk` (already present in this worktree). It restores
the exact launch handler in a throwaway object, preserving the current production source and
using the identical test objects and other server objects:

```make
include Makefile

build/hexpirefix/t_hash_ttl-pre.o: build/hexpirefix/t_hash_ttl-pre.cc $(wildcard src/*/*.h)
	$(CXX) $(CXXFLAGS) $(JEFLAGS) -I. -Isrc/cmd -c $< -o $@
build/hexpirefix/t_hash_ttl-pre-db0.o: build/hexpirefix/t_hash_ttl-pre.cc $(wildcard src/*/*.h)
	$(CXX) $(CXXFLAGS) $(JEFLAGS) -DTOMO_SINGLE_DATABASE=1 -Dtomo=tomo_db0 -I. -Isrc/cmd -c $< -o $@

HEXPIREFIX_PRE_LIB := $(subst build/src/cmd/t_hash_ttl.o,build/hexpirefix/t_hash_ttl-pre.o,$(NETCMD_LIB_OBJ))
HEXPIREFIX_PRE_DB0_LIB := $(subst build/db0/src/cmd/t_hash_ttl.o,build/hexpirefix/t_hash_ttl-pre-db0.o,$(patsubst build/%,build/db0/%,$(NETCMD_LIB_OBJ)))
HEXPIREFIX_PRE_CORE := $(subst build/src/cmd/t_hash_ttl.o,build/hexpirefix/t_hash_ttl-pre.o,$(CORE_TEST_OBJ))
build/hexpirefix/netcmd-unit-pre: $(NETCMD_TEST_OBJ) $(HEXPIREFIX_PRE_LIB)
	$(CXX) $(CXXFLAGS) $^ -o $@ $(JELIBS) $(LDLIBS) -lm -Wl,--wrap=mkstemp -Wl,--wrap=fopen
build/hexpirefix/netcmd-unit-pre-db0: $(NETCMD_DB0_TEST_OBJ) $(HEXPIREFIX_PRE_DB0_LIB) $(HEXPIREFIX_PRE_CORE)
	$(CXX) $(CXXFLAGS) $^ -o $@ $(JELIBS) $(LDLIBS) -lm -Wl,--wrap=mkstemp -Wl,--wrap=fopen

HEXPIREFIX_PRE_OBJ := $(subst build/src/cmd/t_hash_ttl.o,build/hexpirefix/t_hash_ttl-pre.o,$(OBJ))
HEXPIREFIX_PRE_DB0_OBJ := $(subst build/db0/src/cmd/t_hash_ttl.o,build/hexpirefix/t_hash_ttl-pre-db0.o,$(DB0_OBJ))
build/hexpirefix/tomokv-pre: $(HEXPIREFIX_PRE_DB0_OBJ) $(HEXPIREFIX_PRE_OBJ)
	$(CXX) $(CXXFLAGS) $^ -o $@ $(JELIBS) $(LDLIBS) -lm
```

```bash
taskset -c 112-127 make -j16 -f build/hexpirefix/control.mk \
  build/hexpirefix/netcmd-unit-pre build/hexpirefix/netcmd-unit-pre-db0 \
  build/hexpirefix/tomokv-pre
```

Write this to `build/hexpirefix/check-controls.sh` (also already present), then run
`taskset -c 112-127 bash build/hexpirefix/check-controls.sh`. A wrong exit code, an unarmed
injection, or failure at any other assertion makes the runner fail:

```bash
#!/bin/bash
set -euo pipefail
count=0
for arm in netcmd-unit-pre netcmd-unit-pre-db0; do
  for verb in HEXPIRE HPEXPIRE HEXPIREAT HPEXPIREAT; do
    for path in lazy active; do
      log="build/hexpirefix/$arm-$verb-$path.log"
      rc=0
      taskset -c 112-127 "./build/hexpirefix/$arm" hexpire-oom "$verb:$path" >"$log" 2>&1 || rc=$?
      test "$rc" -eq 1 || { cat "$log"; exit 1; }
      if [ "$path" = lazy ]; then
        assertion='FAIL: CD1: HGET must hide the expired prefix after OOM (HTTL == -2)'
      else
        assertion='FAIL: CD1: active expiry must collect the installed prefix after OOM'
      fi
      grep -Fxq "$assertion" "$log" || { cat "$log"; exit 1; }
      printf 'expected FAIL (exit 1): %s %s:%s\n' "$arm" "$verb" "$path"
      count=$((count + 1))
    done
  done
done
test "$count" -eq 16
printf 'ok: %d negative controls failed at the named assertion\n' "$count"
```

**Artifacts and mainline work**

PRE: `build/hexpirefix/tomokv-pre`, SHA256
`47495a7638925b1743cac80699b2d4d1adb35c70acbed45313b97f3c336fca8c`.
POST: `build/hexpirefix/tomokv-post` (identical to `build/tomokv`), SHA256
`638e88a048178eb6db4770ac2e727e43333b4b6105f0d318db6a3b5783e3bdf2`.
GNU `size` text totals: PRE 8,544,637 bytes; POST 8,544,933 (+296); data and bss unchanged.
No object-layout change or PAD arm; no performance claim. Mainline's gate/ABBA remains the
performance verdict. The acceptance criterion for CD1 is actual expiry of the installed prefix,
with the unset field surviving, and the old handler failing both named expiry assertions.

The following **live checks are for MAINLINE; they were not run by this lane**. They use fresh
data directories, 16 shards, eight server CPUs, and split ratio 6:2. Fused mode rejects `--ratio`,
so only the split arm supplies it. Each profile runs the existing full HEXPIRE protocol battery:

```bash
(
set -euo pipefail
mkdir -p build/hexpirefix
hexpire_pid=
trap 'if [ -n "$hexpire_pid" ]; then kill -TERM "$hexpire_pid" 2>/dev/null || true; wait "$hexpire_pid" 2>/dev/null || true; fi' EXIT
for hexpire_mode in 2s 1s; do
  for hexpire_local in 0 1; do
    hexpire_dir=$(mktemp -d "$PWD/build/hexpirefix/live-${hexpire_mode}-${hexpire_local}.XXXXXX")
    hexpire_args=()
    if [ "$hexpire_mode" = 2s ]; then hexpire_args+=(--ratio 6:2); fi
    taskset -c 112-119 ./build/tomokv \
      --bind 127.0.0.1 --port 17953 --shards 16 --thread-mode "$hexpire_mode" \
      "${hexpire_args[@]}" --read-local "$hexpire_local" --atomic 0 --databases 1 \
      --maxmemory 64mb --maxmemory-policy noeviction --save '' --appendonly no \
      --enable-debug-command yes --dir "$hexpire_dir" >"$hexpire_dir/server.log" 2>&1 &
    hexpire_pid=$!
    hexpire_ready=0
    for hexpire_attempt in {1..150}; do
      if ! kill -0 "$hexpire_pid" 2>/dev/null; then cat "$hexpire_dir/server.log"; exit 1; fi
      if (exec 3<>/dev/tcp/127.0.0.1/17953) 2>/dev/null; then hexpire_ready=1; break; fi
      sleep 0.2
    done
    test "$hexpire_ready" = 1
    taskset -c 120-127 python3 tests/hexpire.py 127.0.0.1 17953 all
    kill -TERM "$hexpire_pid"
    wait "$hexpire_pid"
    hexpire_pid=
  done
done
)
```

After mainline incorporates this lane's row count (plus other merged lane deltas), run its gate:

```bash
tests/gate.sh iteration --server-cores 112-119 --load-cores 120-127 --load-smt ''
```

**Gate accounting**

Added `netcmd hexpire-oom regression` as one iteration of the loop at `tests/gate.sh:1385`.
Its collection is `collect_job netcmd_units` at line **2756**, before the quick-tier exit at
line **2878**. Therefore **+1 quick and +1 full**. On this branch's launch counts,
EXPECT_QUICK should become **447** (446 + 1) and EXPECT_FULL **464** (463 + 1).
Both constants remain unchanged for the maintainer. Existing normal HEXPIRE battery rows remain.
The new row executes all 104 cases in the multi-DB implementation; the databases=1 build's
additional 104-case run is recorded above and reproducible with the command provided.

**Diff from launch HEAD, including this report**

`git diff e279aeb4cf08ae2c39f26be679388b872fed4667 --stat`

<!-- DIFFSTAT -->
```text
 MEASURE-REQUEST-hexpirefix.md | 288 ++++++++++++++++++++++++++++++++++++++++++
 Makefile                      |   2 +-
 src/cmd/t_hash_ttl.cc         |  10 +-
 tests/gate.sh                 |   3 +-
 tests/hexpire_oom_checks.inc  | 162 ++++++++++++++++++++++++
 tests/netcmd_unit.cc          |   8 +-
 6 files changed, 466 insertions(+), 7 deletions(-)
```
