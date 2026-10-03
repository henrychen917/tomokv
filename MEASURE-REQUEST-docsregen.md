# docsregen — documentation and serverless proofs

Lane/worktree: `/home/user/Projects/cx-docsregen`, branch `cx-docsregen`.
Launch HEAD before the required fetch/merge: `e279aeb4cf08ae2c39f26be679388b872fed4667`.
First action was `git fetch origin cpp && git merge --no-edit origin/cpp`, which
fast-forwarded to `b47544aad6cb8a81f835f54145b2387beade0bc7` (hexpirefix already
merged/gated by mainline). Repeated immediately before report preparation:
`origin/cpp` is unchanged and the merge says “Already up to date.” No push.

Implementation commits:

- `889158dd5` — Regenerate configuration reference and gate parser name drift.
- `61b8ab2c1` — Correct as-built read-local docs and retire stale control-plane claims.

No production source/configuration was edited by this lane. The diff against
the synchronized base is confined to documentation and tests. No server,
benchmark, gate, or live client test was run. No performance measurement or
PRE/POST/PAD arm is requested: production source/layout/behavior did not change.
The verdict is exact documentation/parser agreement and successful mainline
boot/correctness checks, not a throughput delta.

## What was wrong and what changed

Audit inputs: `/home/user/Projects/round3-read/REGISTER.md` TIER 4;
`cmd-server.md` SV15–SV17; `config-gate.md` GT7/GT8; io-loop/ex-path section D;
`reorder.md` RO10; `read-local.md` RL10; `controllers.md` CT13; cmd-data section D;
`persist.md` PS6; `store.md` ST19. Their anchors were rechecked against source.

| Problem in launch documentation | Current source anchor and delivered correction |
| --- | --- |
| Nonexistent `--conf`, `x-overlap` (including value 2), `x-ex-sched`, `lb`, `flip-work-window`, `script-instruction-limit`, `load`, and the four list/set compact knobs; CONFIGURATION.md:33,72,74,79,135,136,208,239–242. | Positional file path at `src/main.cc:164`; flags in `src/core/config.h:584`; encoding spellings at `:247`. Replaced the entire reference with all accepted spellings. Removed these names as operator options, including repeated bad examples in README. |
| Missing key-lb, client-lb, overlap, reorder, shard-home, unixsocketperm, hll-sparse-max-bytes, aof-load-truncated rows. | `src/core/config.h:648`, `:795`, `:836`, `:851`, `:857`, `:1013`, `:1022`, `:1055`. All now have grammar, default, change policy, INFO mapping (or no direct field), semantics and anchors. |
| `databases` described as live and restricted to 1; compact names described as unrelated to Redis names. | `src/core/config.h:933`, `src/cmd/t_server.cc:395`, `src/core/config.h:247`. Documented boot-only 1..256, seven canonical encoding controls and all nine aliases with their actual distinct grammars. |
| Snapshot restart claimed to need an explicit input flag; worked example could not parse. | `src/main.cc:245` selects dir/dbfilename after AOF-plan precedence. New example uses a first positional config path, a fresh data directory and 6:2 / 16-shard geometry. Actual Markdown block is parsed by the serverless C++ fixture. |
| FINDINGS.md:100–110,158,160,163 contradict parser names, Config size, quoting and CONFIG membership. | Five-row correction table in FINDINGS: independent LB controls (`config.h:851`), 624-byte lock (`:430`), quoting (`server_tail.cc:653`, `:723`), port/bind/unixsocket membership (`t_server.cc:314`), current overlap/reorder controls (`config.h:795`, `:836`). Also rechecked REWRITE preservation (`server_tail.cc:681`), fixed u32 narrowing (`t_server.cc:481`), and removed dangling historical links. |
| ARCHITECTURE-CONTROLPLANE.md described the deleted scheduler, including its obsolete stack-overwrite finding. | Replaced with two paragraphs pointing to round3-read/reorder.md section A and controllers.md section A, with code anchors for the three-rank R7 scheduler, connection-head eligibility, bounded picks, separate LB controls and FLIP verify/revert. |
| CONFIGURATION.md:75,140 and ARCHITECTURE.md:30 restricted read-local to 1s/old overlap; ARCHITECTURE.md:201–204 inverted capacity admission. | Both runtimes at `src/main.cc:325`, `src/core/rl2s.cc:72`; defer-never-demote admission at `src/core/io_loop.h:3443`; exact RYOW predicate at `src/net/rob.h:557`, `:644`. Corrected prose and diagram; described arming fence and on-demand sidecar. |
| Defaults and stale active-retry statements could mislead the paper. | ARCHITECTURE now states 2s, overlap/read-local/reorder 0, both LB controls 1, Redis's three save clauses, slowlog armed. Production MGET jumps to demotion at `src/core/ex_loop.h:1291` before another attempt despite the retained kAttempts=2 control; armed overwrite always refuses at `src/store/flatstore.h:2712`. README and FINDINGS agree. |

CONFIG inventory was counted from `init_config` (`src/cmd/t_server.cc:308`):
**68 canonical entries**, plus **seven non-CONFIG boot directives**, plus **nine
encoding aliases** = **84 accepted spellings** in the reference. A separate
source/table comparison confirmed every row's live/immutable/boot-only label,
including the explicit dir/dbfilename/tcp-backlog refusal at `t_server.cc:615`.
File-only `pin yes/no` is documented as the loader translation of the no-pin
setting; `--help` is an action, not a knob. The name guard intentionally checks
these 84 parser spellings, not prose, defaults, value grammar, INFO or mutability.

The older FINDINGS registry count was also recounted, rather than copied: 245
names from 18 tables (`src/cmd/commands.cc:124`), with 42 in t_server's table
(`src/cmd/t_server.cc:2787`) and 203 elsewhere. README was synchronized.

## Positive proofs, completed on CPUs 112–127

```bash
taskset -c 112-127 make -j16 build/config-parser-test
taskset -c 112-127 ./build/config-parser-test
taskset -c 112-127 python3 tests/docs_drift.py --self-test
bash -n tests/gate.sh
git diff --check
git diff b47544aad -- src
```

All exit 0; the final source diff is empty. Observed receipts:

```text
PASS documented config example: parser, defaults, 6:2 placement, 16 shards
boot presentation: 512 resolved cells, eight placement witnesses each
PASS knob set matches parser: 84 spellings
```

The existing parser fixture now extracts the one `conf` fence from
CONFIGURATION.md, uses `load_conf_file`/`parse_config_args`/`validate_config`,
checks the documented posture, and resolves an eight-CPU 6:2 placement with 16
shards. It opens no listener and constructs no Server. It additionally retains
all the pre-existing parser/boot-support tests. Affinity is inherited by the
negative-control subprocesses.

Guard self-tests cover a valid copy, fake documented knob, missing canonical
knob, missing alias, newly accepted source knob, duplicate row, ignored comment,
and empty document. Failures must exit 1 at the named assertion, rather than
merely producing any exception.

Local proof artifacts (ignored `build/`, not committed):
`build/docsregen-proof/docs-drift.log`, `config-parser.log`,
`negative-fake-knob.log`, `negative-example.log`.
Serverless binary SHA-256:
`1c48c69a35285dd9337ab34b1128ba7a7f9d0d386c36143a0d11a909a6c98a74`.

## Throwaway negative controls, completed

A copy of CONFIGURATION.md with one fake knob row failed exactly:

```text
exit=1
FAIL knob set matches parser: documented but not parsed: docs-drift-fake-knob
```

Reproduce without changing the checkout:

```bash
taskset -c 112-127 python3 - <<'PY'
from pathlib import Path
import subprocess
import sys
import tempfile
with tempfile.TemporaryDirectory(prefix='docs-drift-negative-') as tmp:
    copy = Path(tmp) / 'CONFIGURATION.md'
    copy.write_text(Path('docs/CONFIGURATION.md').read_text() +
                   '\n| `docs-drift-fake-knob` | T | 0 or 1 | 0 | Boot | — | control |\n')
    result = subprocess.run([sys.executable, 'tests/docs_drift.py', '--document', str(copy)],
                            capture_output=True, text=True)
    print(result.stderr, end='')
    assert result.returncode == 1
    assert 'FAIL knob set matches parser: documented but not parsed: docs-drift-fake-knob' in result.stderr
PY
```

An independent copy with `docs-drift-fake-knob 1` inserted inside the worked
example failed the production parser and then its named example assertion:

```text
exit=1
unknown argument '--docs-drift-fake-knob' (see --help)
config parser test: documented config example must parse and validate
```

Both copies were removed automatically. The real example still passes. No
production mechanism was broken and no broken server binary was built/run.

## Exact mainline commands — not executed by this lane

Run from the mainline repository root, one boot at a time on the scheduled quiet
box. First build and extract the exact example, without hand-copying it:

```bash
taskset -c 112-127 make -j16
taskset -c 112-127 python3 - <<'PY'
from pathlib import Path
text = Path('docs/CONFIGURATION.md').read_text()
example = text.split('```conf\n', 1)[1].split('\n```', 1)[0]
Path('build/docs-example.conf').write_text(example + '\n')
PY
```

Terminal A, the worked example's exact boot command:

```bash
DOCS_DATA_DIR=$(mktemp -d /tmp/tomokv-docsregen.XXXXXX)
taskset -c 0-7 ./build/tomokv build/docs-example.conf --ratio 6:2 --dir "$DOCS_DATA_DIR"
```

Terminal B, verify the default posture, 68 canonical CONFIG entries plus nine
aliases (77 wire names), and immutability:

```bash
taskset -c 8-15 python3 - <<'PY'
import sys
sys.path.insert(0, 'tests')
import _lib
c = _lib.Conn('127.0.0.1', 6399)
assert c.must('PING') == b'PONG'
values = c.must('CONFIG', 'GET', '*')
config = dict(zip(values[::2], values[1::2]))
assert len(config) == 77, len(config)
for name, value in [('thread-mode', '2s'), ('overlap', '0'), ('read-local', '0'),
                    ('key-lb', '1'), ('client-lb', '1'), ('reorder', '0'), ('databases', '1'),
                    ('save', '3600 1 300 100 60 10000'), ('slowlog-log-slower-than', '10000')]:
    assert config[name.encode()] == value.encode(), (name, config.get(name.encode()))
    if name not in ('save', 'slowlog-log-slower-than'):
        reply = c.cmd('CONFIG', 'SET', name, value)
        assert isinstance(reply, _lib.RespError) and 'immutable' in str(reply), (name, reply)
info = _lib.info(c, 'server')
for name, value in [('thread_mode', '2s'), ('shards', '16'), ('io_threads', '6'),
                    ('ex_threads', '2'), ('read_local', '0'), ('overlap', '0'),
                    ('key_lb', '1'), ('client_lb', '1'), ('reorder', '0')]:
    assert info[name] == value, (name, info.get(name))
assert c.must('COMMAND', 'COUNT') == 245
c.close()
print('PASS worked-example live boot, CONFIG and INFO')
PY
redis-cli -p 6399 SHUTDOWN NOSAVE
```

Then verify the read-local claims with the existing non-vacuous lane-admission
battery. Run the following separately for `(MODE, OVERLAP, REORDER)` =
`(2s,0,0)`, `(2s,1,0)`, `(1s,0,0)`, `(1s,1,0)`, `(1s,0,1)`, `(1s,1,1)`.
Terminal A (set the first three assignments for each cell):

```bash
MODE=2s
OVERLAP=0
REORDER=0
DOCS_LANE_DIR=$(mktemp -d /tmp/tomokv-docsregen-lane.XXXXXX)
DOCS_MODE_ARGS=(--thread-mode "$MODE")
if [ "$MODE" = 2s ]; then DOCS_MODE_ARGS+=(--ratio 6:2); fi
taskset -c 0-7 ./build/tomokv build/docs-example.conf "${DOCS_MODE_ARGS[@]}" \
  --overlap "$OVERLAP" --reorder "$REORDER" --read-local 1 \
  --enable-debug-command yes --save '' --dir "$DOCS_LANE_DIR"
```

Terminal B, once the listener is ready:

```bash
redis-cli -p 6399 INFO server
taskset -c 8-15 python3 tests/read_local_lane.py 127.0.0.1 6399
redis-cli -p 6399 SHUTDOWN NOSAVE
```

Deciding receipts: requested `thread_mode`, `overlap`, `read_local:1`, effective
reorder; the battery must observe both lane-full and quota deferrals, exact clean
local hits with zero fallbacks, ordered values/RYOW, and restored admission.
No substitute throughput test is needed. In 2s the geometry remains 6 IO / 2 EX;
in 1s all eight selected threads are fused.

For the database range claim, an additional fresh boot and same-connection check:

```bash
DOCS_DB_DIR=$(mktemp -d /tmp/tomokv-docsregen-db.XXXXXX)
taskset -c 0-7 ./build/tomokv build/docs-example.conf --ratio 6:2 \
  --databases 4 --save '' --dir "$DOCS_DB_DIR"
```

In another terminal:

```bash
printf 'SELECT 3\nSET docsregen value\nGET docsregen\nSELECT 0\nGET docsregen\n' | redis-cli -p 6399
redis-cli -p 6399 CONFIG SET databases 1
redis-cli -p 6399 SHUTDOWN NOSAVE
```

Expect OK/OK/value/OK/nil and an immutable-parameter error. These are validation
requests only; no live success is claimed in this report.

After mainline incorporates the count change below (and other lanes' deltas),
run the normal scheduled gate:

```bash
tests/gate.sh iteration
```

## Gate accounting, by line

- New `configuration docs match parser` row: `tests/gate.sh:1198`, in
  `job_config_unit`, running the guard and its self-tests.
- `config_unit` is collected at **line 2742**, before the quick-tier exit at
  **line 2884**. Thus **+1 quick and +1 full**.
- Existing `Redis config quoting + mid-value #` row at line 1204 additionally
  executes the real documented-example parser/placement check. It remains one
  row; its added assertions do not add to the gate count.
- Synchronized mainline constants are 447 quick / 464 full. The resulting
  counts for this lane alone are **448 quick / 465 full**. Both `EXPECT_*`
  constants remain unchanged for the maintainer. The iteration tier uses the
  full correctness count; the existing optional NIC addition is unchanged.

## Remaining boundaries

SV17's source/conf references to absent historical notes remain outside this
lane: the WAITAOF error at `src/cmd/server_tail.cc:212`, and reference comments in
`tomokv.conf:91`, `:125`, `:170`, `:243`, `:386`. No source error text or runtime
configuration file was edited. The replacement docs cite existing source and
the requested external audit archive instead of those missing design files.

The production reader no longer retries, but `src/store/flatstore.h:943`, `:925`
and `src/core/ex_loop.h:1009`, `:1035` still perform per-operation sequence/epoch
validation. FINDINGS explicitly retains this as a concern against the supplied
no-seqlock law; this docs lane neither weakens that law nor changes the mechanism.
Grammar/semantic drift beyond the extracted name set still needs source review.
The serverless example check cannot prove kernel io_uring support, actual bind,
TLS setup, durability, or live concurrency behavior; mainline owns those checks.

## Diff from launch HEAD

The required diff includes upstream hexpirefix changes imported by the mandatory
merge; those `src/` changes are not authored by docsregen. Lane-only scope can be
reviewed with `git diff b47544aad --stat` and `git diff b47544aad -- src` (empty).

```text
 ARCHITECTURE-CONTROLPLANE.md                  | 486 +---------------------
 MEASURE-REQUEST-docsregen.md                  | 296 +++++++++++++
 MEASURE-REQUEST-hexpirefix.md                 | 288 +++++++++++++
 Makefile                                      |   2 +-
 README.md                                     |  39 +-
 docs/ARCHITECTURE.md                          |  73 +++-
 docs/CONFIGURATION.md                         | 575 +++++++++++---------------
 docs/FINDINGS.md                              | 298 +++++--------
 src/cmd/t_hash_ttl.cc                         |  10 +-
 tests/config_parser_test.cc                   |  61 +++
 tests/docs_drift.py                           | 139 +++++++
 tests/fixtures/nullrefresh-ledger-labels.json |  35 +-
 tests/gate.sh                                 |  13 +-
 tests/gate_measurements.json                  |   6 +-
 tests/hexpire_oom_checks.inc                  | 162 ++++++++
 tests/netcmd_unit.cc                          |   8 +-
 16 files changed, 1414 insertions(+), 1077 deletions(-)
```
