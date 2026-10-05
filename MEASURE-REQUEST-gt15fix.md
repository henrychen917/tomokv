# gt15fix: feature snapshot reloads during placement transitions

Worktree `/home/user/Projects/cx-gt15fix`, branch `cx-gt15fix`, base
`07023fd6e67a2e13cb6f8946cf609eda0c11271c`. Implementation commit `e395454bc`.
Test-only change: the server, its layout, and its configuration are unchanged.
No server, load generator, benchmark, or gate was started by this lane. The live
proofs below remain **PENDING**, following the shared maintainer-run rule; they
are requests, not claimed results. No push.

**Race and audit.** `tests/gate.sh:770` defines `feature_split_job`; its loop
invokes `tests/$t.py`, including `tests/hexpire.py`. At the base commit, hexpire's
three `DEBUG RELOAD` calls are at lines 519, 537, and 539: the long-deadline/value
round-trip, the short-deadline save/load before expiry, and the save/load after
expiry. The latter two ignored their replies. The first refusal returned before
five persistence assertions, explaining the reported 202 checks versus floor 206.

`src/cmd/scatter_engine.inc:1493` refuses these loads before snapshot planning if
`Server::loading_begin()` fails. That method takes `shape_transition_mu_` and
checks `placement_transition_active()` (`src/core/server.h:822,994`), which
includes **both** non-idle FlipStage and non-idle LbStage. Both cases report the
same exact text: `ERR loading is not allowed while FLIP is in progress`.
The error alone therefore does not identify which transition caused the incident.
In this checkout, `feature_split_job` does not pass `--flip-auto`, whose default
is **0** (`src/core/config.h:337`); key/client balancing remain enabled. This is
also true of the inspected `origin/cpp` files. Historical runtime telemetry was
not supplied, so attributing the refusal specifically to the auto-FLIP controller
would go beyond the available evidence.

All 33 names in `FEATURE_BATTERIES` were inspected with grep and a Python AST
audit. `edgeenc.py:664` at the base is the only other reload site in this family.
There are no `DEBUG LOADAOF` sites in it. Per-key DUMP/RESTORE in `dumprestore`,
`hexpire`, `edgeenc`, and `cmdgap`, and FUNCTION RESTORE in `scriptsurf`, do not
enter this all-owner load admission guard. `dumprestore`'s SAVE/restart modes
are outside the feature job's default live mode. `servertail` exercises separate
process/configuration restarts, not runtime DEBUG loads. Other jobs' reload
batteries (`aof`, `debug`, `multidb`, `dumpttl`, `xacct`) were outside this lane's
requested feature-split scope and were not changed.

**Change.** Shared `tests/_lib.py::wait_flip_idle` polls `INFO SERVER LB` every
50 ms, requiring `flip_in_progress:0` and `tomokv_keylb_stage:0`. The former
reads the actual FlipStage, not the controller's learning phase. In fused mode,
`thread_mode:1s` plus `flip_available:0` establishes FLIP unavailability; the LB
stage must still become idle. Missing or malformed witnesses fail. Polling has a
monotonic 30 s deadline and caps each INFO socket timeout to the remaining budget,
restoring the connection's original timeout afterward.

`debug_load` supports RELOAD and LOADAOF. It waits before the first load and,
only for the exact returned RESP error above, waits again and retries once. Both
waits share the original deadline. A second refusal, any different error, or any
non-OK reply fails. The existing client timeout still governs the load command
itself. No controller or balancer is disabled.

All three hexpire reloads and edgeenc's reload use this helper. Hexpire requires
the short-TTL save/load to complete within its original 500 ms window. If a wait
consumes that window, it re-arms from a fresh FLUSHALL and fresh deadlines, at most
three times. An unopened window fails; retries add no executed checks. The 0.8 s
post-expiry sleep and every original check/check_true expression are unchanged.
These preserve the existing persistence postconditions; they do not newly prove
that expired fields were removed by the loader rather than ordinary expiry.

**Local proofs completed.** `python3 tests/debug_load_test.py -v`: **13/13 PASS**,
with a virtual clock and a connection-shaped fake; no sockets/processes/sleeps.
Coverage includes refusal-once/accept-once with both idle waits; RELOAD/LOADAOF;
both existing OK representations; exactly two load attempts; unrelated errors;
permanent FLIP/LB timeout; shared retry deadline; late INFO; fused LB; missing
telemetry; disconnection; fresh expiry re-arming; a permanently unopened window;
and fatal reload errors during arming.

Six throwaway in-memory mutations were rejected by those tests: omit idle waits,
omit the retry, accept non-OK loads, retry unrelated errors, ignore the LB stage,
and accept an unopened expiry window. Log:
`build/gt15fix/negative-controls.log`. Production/test source was unchanged by
the mutations. Python syntax parsing and `git diff --check` passed. AST comparison
against the base found all original hexpire check/check_true expressions intact.

**Rows and counts.** Zero new or retired rows. The feature-split collection is at
`tests/gate.sh:3099`, before the quick-tier exit at line 3202. EXPECT_QUICK=490,
EXPECT_FULL=507, hexpire EXPECT_DEFAULT=206, and all fixtures remain unchanged.
The serverless witness is standalone and does not add a gate row.

**Requested live proofs.** Run serially on the scheduled quiet box. Use the same
server binary for PRE and POST because C++ is unchanged; the arms are the base
and changed Python batteries/helper. No server build was needed for the local
serverless checks. There is no text/layout change or PAD arm, and no performance
gain is claimed. Record the selected binary path, commit, and SHA-256. The POST
commands below assume the maintainer has built `build/tomokv` in this worktree.

| Cell | Repetitions | Geometry / verdict |
| --- | ---: | --- |
| hexpire, atomic 1, POST | 20 fresh boots | 112–119 server, 120–127 clients, shards 16, ratio 6:2, gate's flip-auto default; every run succeeds with at least 206 checks and all persistence assertions |
| feature-split-1, POST | 5 complete jobs | Same CPU partition and unmodified job boot; every battery and shutdown row passes, including hexpire and edgeenc |

Do not infer that twenty successful runs exercised the refusal race. The fake's
ordered command trace is the deterministic witness for that race. An additional
live `--flip-auto 1` campaign can supplement the requested default-geometry proof,
but must be labelled separately. Hexpire's purpose is hash-field TTL/persistence,
not FLIP policy. This patch does not pin the feature job to `--flip-auto 0`; the
commands below preserve its existing omission and verify the resulting value.

The following standalone driver uses the existing owned-process helper for port
guarding, readiness, connection quiescence, and bounded teardown. Each boot gets
an empty persistence directory. This code was prepared, not executed:

```bash
cd /home/user/Projects/cx-gt15fix
taskset -c 120-127 python3 - <<'PY'
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
sys.path.insert(0, str(Path('tests').resolve()))
from _gate_process import server
from _lib import info

binary = Path('build/tomokv').resolve()
assert binary.is_file() and os.access(binary, os.X_OK), binary
output = Path(tempfile.mkdtemp(prefix='gt15fix-hexpire-', dir='build')).resolve()
(output / 'identity.json').write_text(json.dumps({
    'commit': subprocess.check_output(['git', 'rev-parse', 'HEAD'], text=True).strip(),
    'binary': str(binary),
    'sha256': hashlib.sha256(binary.read_bytes()).hexdigest(),
}, indent=2) + '\n')
env = dict(os.environ, TOMO_GATE_STRICT='1')
for run in range(1, 21):
    directory = output / ('run-%02d' % run)
    with server(binary, '112-119', 7919, directory,
                ['--shards', '16', '--ratio', '6:2', '--atomic', '1']) as (control, process):
        actual = info(control, 'SERVER', 'LB')
        (directory / 'info-before.json').write_text(json.dumps(actual, indent=2) + '\n')
        assert actual['thread_mode'] == '2s' and actual['atomic'] == '1', actual
        assert actual['shards'] == '16' and actual['flip_auto'] == '0', actual
        with (directory / 'hexpire.log').open('w') as log:
            subprocess.run([sys.executable, 'tests/hexpire.py', '127.0.0.1', '7919'],
                           env=env, stdout=log, stderr=subprocess.STDOUT,
                           check=True, timeout=300)
        body = (directory / 'hexpire.log').read_text()
        count = re.search(r'hexpire: (\d+) checks \(floor 206\), 0 failures -> PASS', body)
        assert count and int(count[1]) >= 206, body
        (directory / 'info-after.json').write_text(json.dumps(
            info(control, 'SERVER', 'LB'), indent=2) + '\n')
    print('hexpire %02d/20 PASS: %s' % (run, directory), flush=True)
print(output)
PY
```

For the five whole-job repetitions:

```bash
cd /home/user/Projects/cx-gt15fix
mkdir -p build/gt15fix
for gt15_run in 1 2 3 4 5; do
  GATE_ONLY_JOBS=feature-split-1 \
    tests/gate.sh quick \
      --candidate-binary "$PWD/build/tomokv" \
      --server-cores 112-119 --server-smt '' \
      --load-cores 120-127 --load-smt '' --ports 7919-7921 \
      > "build/gt15fix/feature-split-1-$gt15_run.log" 2>&1 || exit 1
done
```

`quick` selects the same feature job body. It avoids the planner's unrelated
reviewed 32-thread ABBA geometry requirement when only these sixteen physical
cores are allocated. `GATE_ONLY_JOBS` then runs only the selected job and its
release prerequisite, with no full EXPECT tally, ABBA, NIC, or receipt. Each
successful feature job has its existing 33 battery rows plus shutdown. Its nested
servertail servers inherit a subset of GATE_CORES, also inside 112–127.

The read-only planner command was executed successfully (no gate/boot/build):
`python3 tests/gateplan.py quick --server-cores 112-119 --server-smt '' --load-cores 120-127 --load-smt '' --ports 7919-7921 --json`.
It reports one 6:2 correctness slot on server CPUs 112–119 and load CPUs 120–127;
the saved plan is `build/gt15fix/proof-plan.json`.

Append actual outcomes, logs/partial-ledger locations, runtime INFO, binary
identity, and any refusal/timeout to `MEASURE-RESULT`. Acceptance requires all
20 standalone runs and all five complete jobs green, with no skipped persistence
arm, no reduced check floor, and no weakened EXPECT/fixture. Until those results
exist, live acceptance is pending.
