#!/usr/bin/env python3
"""Render the finite footprint/command-scope receipts, without running workloads."""
import ast, csv, hashlib, json, statistics
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
DOC = ROOT / 'docs/storefix5'
read = lambda path: json.loads(Path(path).read_text())
sha = lambda path: hashlib.sha256(Path(path).read_bytes()).hexdigest()
lines = ['# Store round-5 fixes', '', '## storefix5', '',
'''Worktree `/home/user/Projects/cx-storefix5`, branch `cx-storefix5`; PRE is
`ea48a6b2721a1d9e5964ab24a32e8b54df611bd5`. No push. The last item commit
contains idle-clock accounting and can be excluded independently. The preceding
commits contain RANDOMKEY, APPEND, and their zero-cost/harness controls.
Excluding the last item requires rebuilding and revalidating that two-item
variant: the combined POST instruction and footprint receipts do not apply to it.

All lane workloads and builds use CPUs 16–23, at most eight workers per make, and
ports 21600–21699. Server children inherit `LC_ALL=C`. Only finite correctness,
footprint and serverless instruction checks were run. No throughput result or
full iteration is claimed. Initial failed trials remain in the receipts.

The proof retains unresolved FIFO deadline failures, inherited Tcl/string-limit
failures and upstream Tcl maxmemory skips, detailed below. All eight standard
differential matrices pass (1,880 suite/seed runs), both engines' mode-equivalence
jobs pass, and all 96 maxmemory-off command scopes add zero instructions.

### Items and boundaries

| Item | PRE witness | POST result | Mechanism changed | Residual / freeze boundary |
|---|---|---|---|---|
| SO5.3 / SO5.7 RANDOMKEY | Gate witness reaps all 400 elapsed keys in one call despite a survivor on every shard; 1M-key footprint witness fails | Directed gate matrix checks empty/all-expired nil, expiry/PAUSE, uniform sampling, EXEC and namespace/SWAPDB images; 1M-key footprint passes | One shard selected by published namespace counts, bounded slot rejection, one retained key; dead handler removed and store tests call the executed sampler | The fast path uses at most 64 slot probes plus O(shards) routing. Probe-budget exhaustion (even on an ordinary image), sparse namespaces, pending MVCC records and EXEC retain resumable O(keys) scans. The pending side-key walk is inherited and not bounded by the physical-table budget. General O(1) over those images is **not delivered**. |
| SO5.6 APPEND | Production-linked malloc/copy spy detects one merged scratch allocation and fails | Same spy observes zero merged scratch allocations; live values, TTL, binary/integer input, encoding and errors pass | Allocate the final immutable external string and copy old bytes and suffix directly into it | Still O(old length), hence quadratic for repeated one-byte growth. No slack-space mutation or object-layout change. |
| ST5.3 / SO5.2 idle clock | Enabling maxmemory over 10k keys leaves INFO used_memory unchanged; footprint table below shows the hidden RSS | Exact node accounting, side-effect-free observations and deferred reclamation pass; all 16 limit/value/policy/mode cells pass | Charge each branch/leaf allocation to existing store accounting, reserve missing-path bytes before admission, subtract after clock destruction/grace | Nodes remain until maxmemory is disabled. Non-evictable retained metadata can eventually exhaust a budget under churn. Fixed process RSS, allocator retention and snapshot admission exceptions remain. This is not an RSS cap. |

RANDOMKEY counts are routing hints, never proof of emptiness. Empty candidates
visit each remaining shard at most once before nil. The sampler retains the
existing expiry notifications, snapshot pre-image handling, undecided/parked
visibility rules and CLIENT PAUSE expiry hold. It uses the existing store read
view; it does **not** add a new global RANDOMKEY snapshot guarantee. EXEC keeps
its fixed all-shard participant mask and a one-key reservoir per shard. A draft
that changed EXEC participants hung and was rejected (`randomkey-post-2s.log`).
The physical-table fallback yields every 256 scan homes; there is no vector of
all keys. It inherits SCAN's home/cluster traversal, so this is not a hard
wall-clock bound for an adversarial probe cluster. Making sparse namespaces or pending-only images uniformly sampleable
in expected O(1) would require a maintained visible-key sampling index and write
path work. A finite probe budget followed by a census does not establish an asymptotic expected-O(1) guarantee. That extension is stopped at the architecture/zero-cost boundary.

The final review also found a full-retirement-ring expiry stall in the shared
SCAN visitor, reached by RANDOMKEY's fallback. Its physical deletion could enter
`force_oldest_grace()`. The fast sampler could emit an expiry notification before
that deletion was possible. Both now check retirement capacity on the expired-key
branch: the key remains logically absent, its object remains resident, and the
event/AOF delete occurs once capacity returns. The shared visitor also protects
KEYS/SCAN from that same wait. No reader retries are introduced. The deterministic
store witness forces both sampler paths and asserts the capacity check actually
fires. PRE's original scan fails; removing either guard from POST independently
fails for its specific reason (`retirement-*.json`, `retirement/controls.json`).
The test helper now rejects a selected name that resolves to an invisible key,
instead of converting it to nil. A third negative control removes the sampler's
visibility filter: it passes with the old helper and fails with the strengthened
assertion (`retirement/masked-visibility-before.json`,
`retirement/no-visibility-guard.json`). The corrected storage job passes through
the gate interface (`gate-sampler-final.log`).

APPEND uses ordinary immutable insertion, retirement, metadata and publication
failure cleanup. Its allocation spy is the decisive PRE-failing witness:
external memcpy interception does not count compiler-inlined copies, so its
PRE byte total is not presented as a complete census. The smallest after-freeze
proposal is capacity-bearing raw storage with owner-only append eligibility:
read-local disarmed, no snapshot pre-image, no MVCC predecessor, no outstanding
borrow. Arming transitions must synchronize with eligible writers; checking a
flag once is insufficient. Otherwise retain COW; amortization with those readers armed needs an
immutable chunked/frozen-prefix design. Neither is implemented.

Idle nodes are allocated only while maxmemory is enabled. No node or clock is
allocated at maxmemory 0. Allocation estimates walk existing links without
installing nodes or updating stamps. Partial allocation failures retain charges
for the nodes actually installed. Runtime enable charges only after successful
construction; its existing bad_alloc error path is untouched (cfgfix2 owns it).
Disable keeps the retired tree charged until its owning store's QSBR reclaim
callback. Owner migration already drains/rebinds the retire sink. KV objects and
the listed locked structures retain their layouts. The cold scatter `GroupAux`
allocation grows from 80 to 136 bytes to hold RANDOMKEY's cursor and retained
key (`cold-layout.json`, `cold-layout-final.json`); KEYS and capture-safe FLUSH use that helper too.
Ordinary GET/SET/INCR/MGET/MSET do not allocate it.

### Arms

PAD-A is a **behaviour twin (A)**: PRE behaviour with POST's 136-byte cold
`GroupAux` layout and aggregate `.text` start and extent. A private PRE source
copy adds the unused cursor fields; both namespace builds assert the helper's
size. Unreachable trailing NOPs match the remaining text extent. Per-function
addresses are **not matched to POST**, so this control cannot isolate every
code-placement effect. No gain is inferred from it. The earlier extent-only
PAD is preserved as `build/storefix5/pad-a/extent-only-tomokv`, with receipts
named `pad-extent-only*`.
''', '| Arm | Path (under this worktree) | SHA-256 |', '|---|---|---|']
for name in ('PRE','POST','PAD-A'):
 p=ROOT/'build/storefix5'/name
 lines.append(f'| {name} | `build/storefix5/{name}` → `{p.resolve().relative_to(ROOT)}` | `{sha(p)}` |')
pad=read(DOC/'pad-a.json')
lines += ['', f"POST/PAD `.text`: {pad['text_size']:,} bytes at {pad['text_start']:,}; PAD adds {pad['padding_bytes']:,} bytes. Build/link commands and object choices: `budgets/retirement168000-link.json`, `pad-a.json`. Earlier footprint/control binary `55b996cc…` is preserved as `build/storefix5/arms/candidate/tomokv`; final POST is the `retirement168000` link. The preceding `09367b85…` arm remains available for the earlier receipts.", '',
'''### RANDOMKEY: 1M keys and sampling

Five finite single calls, followed by four connections × 16 calls. These are
final samples run serially after this lane's builds completed on the assigned
CPUs. Whole-box quietness was not certified; these are **not quiet-box latency
or throughput verdicts**. The
non-timing mechanism witness and bounded memory assertion carry the proof.
Receipts: `curves-release/{pre,post}-*.json`, `curves-release/redis-2s.json`. Earlier contended observations remain in `curves` and `curves-release-before-retirement`.
''', '| Arm | Single-call ms, min / median / max | RSS increase after singles, MiB | RSS increase after 4×16, MiB |', '|---|---:|---:|---:|']
for label,p in [(f'PRE {m}',DOC/f'curves-release/pre-{m}.json') for m in ('1s','2s')] + [(f'POST {m}',DOC/f'curves-release/post-{m}.json') for m in ('1s','2s')] + [('Redis 7.4',DOC/'curves-release/redis-2s.json')]:
 case=read(p)['cases']['randomkey_footprint'];r=case.get('result') or ast.literal_eval(case['error'])
 times=r['single_call_ms'];base=r['before']['used_memory_rss']
 lines.append(f"| {label} | {min(times):.4f} / {statistics.median(times):.4f} / {max(times):.4f} | {(r['single']['used_memory_rss']-base)/2**20:.3f} | {(r['after_four_clients_16_calls']['used_memory_rss']-base)/2**20:.3f} |")
chi=[]
for p in sorted((DOC/'curves-release').glob('redis-randomkey-*.json')):chi.append(read(p)['cases']['randomkey']['result']['chi2'])
distribution=read(DOC/'randomkey-final-distribution.json')['legs']
observed='; '.join(f"{mode}: {min(values):.4f}–{max(values):.4f}" for mode in ('1s','2s')
                  for values in [[r['randomkey']['chi2'] for r in distribution if r['leg'].startswith(mode)]])
lines += ['', 'Uniformity uses 32 named keys, 16,384 draws, chi-square with 31 degrees of freedom. The TomoKV assertion is chi-square < 100 and every key observed. All 32 final POST boots pass; observed ranges are '+observed+' (`randomkey-final-distribution.json`). Redis is measured without imposing that threshold: five fresh runs were '+', '.join(f'{v:.4f}' for v in chi)+'. These observations compare distribution quality; they do not prove exact uniformity for arbitrary evolving keyspaces.', '',
'''### APPEND curve

Median SLOWLOG command duration in microseconds for five one-byte appends per
initial size; all resulting values and TTLs are checked. `0` means below the
one-microsecond timer resolution, not zero work. Host activity and allocation
coldness can affect these small samples. The maintainer must repeat on a quiet box
before using the curve in a paper. Raw individual observations are retained.
''', '| Initial size | PRE 1s | POST 1s | PRE 2s | POST 2s | Redis 7.4 |', '|---|---:|---:|---:|---:|---:|']
curves=[read(DOC/p)['cases']['append']['result'] for p in ['curves-release/pre-1s.json','curves-release/post-1s.json','curves-release/pre-2s.json','curves-release/post-2s.json','curves-release/redis-2s.json']]
for size,label in [(16,'16 B'),(1024,'1 KiB'),(65536,'64 KiB'),(1048576,'1 MiB'),(4194304,'4 MiB')]:
 lines.append('| '+label+' | '+' | '.join(str(statistics.median(c[str(size)]['slowlog_command_us'])) for c in curves)+' |')
lines += ['', '''### Maxmemory footprint

16 shards, eight threads; split geometry is 6 io + 2 ex. Each cell boots fresh
with maxmemory already set, offers a bounded population, validates only expected
OOM replies, verifies used_memory near/below the accounting budget, records keys
and RSS, then flushes and removes its private data. Redis is single-threaded.
Values are 100 or 1000 bytes. Numbers below are RSS/maxmemory and retained keys;
raw used_memory, accepted/refused/evicted counts are in `memory/{pre,release,redis}`.
''', '| Mode | MiB | Policy | Value B | PRE RSS/limit; keys | POST RSS/limit; keys | Redis RSS/limit; keys |', '|---|---:|---|---:|---:|---:|---:|']
for mode in ('1s','2s'):
 for mb in (30,100):
  for policy in ('allkeys-lru','noeviction'):
   for val in (100,1000):
    cells=[]
    for arm,actual in [('pre',mode),('release',mode),('redis','2s')]:
     r=read(DOC/f'memory/{arm}/{actual}-{mb}mb-{policy}-{val}b.json')['cases']['memory_limit']['result']
     cells.append(f"{r['rss_over_limit']:.3f}; {r['keys']:,}")
    lines.append(f'| {mode} | {mb} | {policy} | {val} | '+' | '.join(cells)+' |')
headroom=[]
for p in (DOC/'memory/release').glob('*b.json'):
 r=read(p)['cases']['memory_limit']['result']
 assert r['after']['used_memory'] <= r['limit'], p
 headroom.append(r['limit']-r['after']['used_memory'])
assert len(headroom)==16
lines += ['', f'Every final POST observation is at or below the configured used_memory limit; remaining headroom is {min(headroom):,}–{max(headroom):,} bytes across the 16 cells. This stronger check uses the raw observations, without the cross-server helper’s allowance.']
lines += ['', '''Charging metadata reduces capacity; the formerly larger key count was not
free memory efficiency. Snapshot pre-images/retirement and allocator retention
still require headroom. Noeviction includes expected refused SETs. Allkeys-lru
cannot reclaim retained clock nodes without a structural change.

The historical eviction fixture assumed its 1 MiB setup budget retained 3000
keys; that became false once metadata was charged. Its setup now proves a full
unevicted cohort, then derives pressure from accounted bytes. LFU uses 1000-B
values so retained metadata does not consume the whole pressure budget; 100-B
values are covered above. Existing age, LFU-frequency, hot-survivor, touch/no-touch,
lane and conservation assertions remain. The initial eight red rows and the
fixture's subsequent integer-encoding error are retained, followed by eight
green corrected rows (`gate-eviction-final.log`). All eight eviction jobs also
pass on the final frozen POST in `gate-live-final.log`. No tolerance was widened.

The notification battery had a second fixed-budget assumption: it seeded 160
keys, lowered maxmemory to 16 KiB, and only then armed eviction notifications.
With the clock charged, that limit is below the retained metadata; the seeds can
be gone before arming, and all later SETs can return OOM. Both atomic settings
failed loudly in `gate-inventory-final.log`. The fixture now proves the full
unevicted cohort under a setup budget, arms delivery, then derives pressure from
observed used_memory. It retains the original bounded trigger attempts, event
name check and mandatory fired/evicted counter advances. Complete PRE and POST
job reruns in both modes are recorded as `gate-notify-*-final.log`.

### After-freeze structural alternatives

`tools/storefix5_clock_geometry.cc` allocates 50,000 actual jemalloc object-size
blocks with 16-byte keys using eight pinned allocator threads, then replays the
**same addresses** into unchanged clocks grouped per shard, per owner or once
per process. Assignment is synthetic deterministic round-robin, not the live
server's random key hashing. This measures allocated node bytes, not live-server RSS or concurrent
shared-tree correctness. `clock-geometry.csv` contains both 16- and 128-shard
cases and all four value sizes. The 128-shard cases below show the address-sharing
multiplier. A stamp column is the exact size-class delta for adding a 4-byte word
to these allocation requests; other key lengths/TTLs can cross other classes.
''', '| Allocation source | Value B | Per-shard B/key | Per-owner B/key | Process-wide B/key | 4-B stamp class delta B/key |', '|---|---:|---:|---:|---:|---:|']
for r in csv.DictReader((DOC/'clock-geometry.csv').open()):
 if r['shards']=='128':lines.append('| '+r['source']+' | '+r['value_bytes']+' | '+' | '.join(f"{float(r[k]):.2f}" for k in ['per_shard_B_per_key','per_owner_B_per_key','process_B_per_key','stamp_class_delta_B_per_key'])+' |')
lines += ['', '''The audit's live-server measurements corroborate the mechanism: T1d measured
17.5 B/key with one shard per owner versus 144.8 B/key at eight; T1h found 410,
810, 6,370 and 31,714 leaves for 50k external values at 1/1, 2/2, 16/16 and
16/128 thread/shard geometries. T1f measured 549.5/880.3/1650.5 B/key RSS at
100/180/1000-byte values. These audit geometries are not substituted for this
lane's 16-shard matrix.

Expected hot-path costs, not measured timings: an object stamp replaces four
dependent radix-pointer loads with a direct stamp load and the existing rare
CAS/update, but changes header layout and cache-line sharing. A process-wide
tree retains the lookup chain, needs multi-writer CAS node publication and safe
lifetime management, and introduces shared-node contention. A per-owner tree
retains the chain and single-owner allocation, but parser-built headers still
share pages across owners; migration must transfer/rebind stamp ownership in the
same critical section as all other shard-owned structures. None is implemented.

### Command-scope zero-cost proof

The finite ptrace census links production objects and counts named production
functions/assembly only, excluding fixture, shared-library and syscall work.
No server/listener, load generator, PMU rate or wall-clock score is used.
PRE and POST receipts include both namespaces, 1s/2s, atomic 0/1, batch 1/32:
80 ordinary scopes plus 16 fresh-key SET scopes. **No positive delta in all 96.**
GET is a hit; ordinary SET replaces a value; the additional SET scopes insert.
`counts/pre`, `pre-insert`, `retirement168000-full`, `retirement168000-insert` retain totals,
per-function counts, trace sites and link receipts.

Cold-unit growth originally changed GCC inlining/register allocation. The bounded
compile controls are in `budgets/`: xshard 164393 / db0 168000, db0 t_string 14099.
The equivalent MOVE-name check now runs only after its Renamenx classification,
removing unrelated string decoding from MGET/MSET. A superseded control still
added one instruction to fresh db0 SET; the final 14099 control removes it. This
is instruction evidence only; cycles/IPC/rate remain the maintainer's verdict. The final retirement guards crossed the db0 inlining boundary again; the 168000 control restores the PRE find body and the complete census below.
''', '| Namespace | Command | POST−PRE instructions/op range (all modes, batches, atomic settings) |', '|---|---|---:|']
key=lambda r:tuple(r[k] for k in ('namespace','command','mode','batch','atomic'))
for prior,post,insert in [('pre','retirement168000-full',False),('pre-insert','retirement168000-insert',True)]:
 old={key(r):r for r in read(DOC/f'counts/{prior}/counts.json')['rows']};new=read(DOC/f'counts/{post}/counts.json')['rows']
 assert len(old) == len(new) == (16 if insert else 80)
 assert all(r['total'] <= old[key(r)]['total'] for r in new)
 for ns in ('normal','db0'):
  for command in (['SET'] if insert else ['GET','SET','INCR','MGET','MSET']):
   delta=[(r['total']-old[key(r)]['total'])/r['batch'] for r in new if r['namespace']==ns and r['command']==command]
   lines.append(f"| {ns} | {command}{' insert' if insert else ' replacement' if command=='SET' else ''} | {min(delta):g} … {max(delta):g} |")
lines += ['', 'With maxmemory = 1 GiB/allkeys-lru, GET-hit and SET-insert costs are quantified separately (32 scopes, atomic 0/1 give the same deltas). Cold first node creation is outside the warm command scope; finite admission/footprint checks above include it.', '', '| Namespace | Command | Mode | Batch | PRE instructions/op | POST instructions/op | Delta/op |', '|---|---|---|---:|---:|---:|---:|']
old={key(r):r for r in read(DOC/'counts/pre-memory/counts.json')['rows']}
enabled=read(DOC/'counts/retirement168000-memory/counts.json')['rows']
assert len(old) == len(enabled) == 32
deltas={key(r): (r['total']-old[key(r)]['total'])/r['batch'] for r in enabled}
assert all(deltas[key(r)] == deltas[key(r)[:-1]+(1-r['atomic'],)] for r in enabled)
for r in enabled:
 if r['atomic']:continue
 a=old[key(r)]['total']/r['batch'];b=r['total']/r['batch']
 lines.append(f"| {r['namespace']} | {r['command']} | {r['mode']} | {r['batch']} | {a:g} | {b:g} | {b-a:g} |")
lines += ['', '''### Gate and proof ledger

The selected-job interface normally requires eight server CPUs plus disjoint
client CPUs. This lane owns only eight. The explicit
`--shared-correctness-cpus` adapter requires selected quick/iteration jobs,
`GATE_PROOF_NO_RATES=1`, exactly the same eight physical CPUs, no SMT, and one
slot. Complete gate/ABBA/NIC/receipt modes still reject it. Planner rejection
controls and mode-equivalence geometry checks are recorded. This is a partial
correctness run, never an EXPECT/full-gate receipt.

Final proof status is recorded in `gate-summary.json` and the individual logs.
Native prerequisites are built before their gate jobs; the initial native run
hit the 900-second build watchdog and correctly failed rows lacking unit-ready
markers. Live AOF equality checks themselves passed in that run. The final
retry uses fresh prerequisites; no missing marker is waived. An initial final
quiet-job selection exited 2 before running any job because build-only TSAN
prerequisites must be selected through their consuming jobs. The consumers are
in the extra run, and the ASAN/quiet-core jobs have a separate serial retry.

Tcl `unit/keyspace` and `unit/type/string` use the existing named passing
manifest (37 + 80 assertions per mode). RANDOMKEY and APPEND semantics were
already required there; the new cost/accounting witnesses are promoted in the
storefix5 job. The unfiltered three-file Tcl job also runs in both modes and
reports its unsupported baseline failures. **unit/maxmemory assertion bodies:
NOT RUN**: all nine start_server blocks carry upstream `external:skip`; the
external runner reports zero assertions. The skips are not counted as passes.
The finite memory matrix, maxmemory/maxmemrace/eviction jobs supply the separate
executed coverage. No upstream assertion or tag was removed to manufacture a
Tcl pass.

`rootcompat-stringlimit` reports 24 failures above the 32-bit value representation
on both PRE and POST; normal configured-limit cases agree. Changing that
representation needs a layout change and is outside this lane. The failure is
reported, not hidden or weakened. Other proof failures are listed separately in
the final ledger.

DQ=+2 / DF=+2. `collect_job storefix5` at line 6507 is before the quick-tier exit
at line 6852 and emits
one 1s row and one 2s row, each covering both engines × atomic 0/1 × read-local
0/1 × databases 1/16. EXPECT constants remain 1046 / 1063. The maintainer's
new counts for this lane alone are **1048 / 1065**. No other public row was added.

NOT RUN: performance benchmarks, load generators, full iteration/ABBA and quiet
latency curves, by the lane's runtime boundary. Pending or failed correctness
checks are not represented as passes. Preloaded data is deleted after completed
runs; build artifacts and receipts remain under the lane worktree.

### Maintainer measurement request

Use PRE, POST and PAD-A above, on the quiet box, with the gate's instrument.
Run the 14 unchanged generic cells in `docs/lbplanner/generic-cells.txt`:
`h05 h06 p8g p8s d1g_l0 d1s_l0 m8g_l0 v1g_l0 d128g_l0 d32g_l1 d8s_l1 d32s_l1 x9_32_l1 x9_32_l0`.
Add split 2s GET and SET at p1 and p32, with maxmemory 0 and 1 GiB/allkeys-lru,
16 shards and ratio 6:2, at the same offered load for every arm. Use the same
key/value population and connection count for all three arms; maxmemory-on
population must fit in POST without eviction for the ordinary-cost cells.
Record cycles/op, instructions/op, IPC and the gate's rate/tail score. The
verdict is matched-load rate/tail regression, not instruction count alone.
PAD-A matches the cold helper layout and aggregate text extent described above;
it does not match individual function placement.

Repeat the finite RANDOMKEY check at 1M keys and the one-byte APPEND curve at
16 B / 1 KiB / 64 KiB / 1 MiB / 4 MiB on a quiet box against Redis 7.4. Record
individual command latency and RSS/high-water changes; do not infer flat APPEND
cost or universal O(1) RANDOMKEY from the restricted fast path. For maxmemory,
compare used_memory, RSS/limit, accepted/refused/evicted counts and keys retained
at 30/100 MiB × allkeys-lru/noeviction × 100/1000 B in both modes. The decisive
memory result is that clock nodes are charged and admission respects that total;
RSS still includes explicitly unaccounted process/allocator headroom.

Finite-check command templates (repeat with each arm and both modes; PRE's
RANDOMKEY footprint assertion is expected to fail):

```sh
LC_ALL=C taskset -c 16-23 python3 tools/storefix5_checks.py --binary build/storefix5/POST --mode 2s --port 21600 --cases randomkey_footprint,append --output build/storefix5/quiet-post-2s.json
LC_ALL=C taskset -c 16-23 python3 tools/storefix5_memory.py quiet-post --binary build/storefix5/POST --port 21630
LC_ALL=C taskset -c 16-23 python3 tools/storefix5_memory.py quiet-redis --binary /home/user/Projects/redis/src/redis-server --redis --port 21630
```

For Redis's curve, use the first command with the oracle binary and `--redis`.
The memory helper covers the complete limit/policy/value matrix and both TomoKV
modes; its Redis matrix runs once because Redis has no split/fused mode.
''']
proof = [
    '### Selected-job results and controls', '',
    '`python3 tests/gates_test.py`: **77 tests PASS**, plus 14 embedded identity tests '
    '(`gates-test-final.log`). '
    'Planner checks: 25 PASS and 12 measurement-boundary checks PASS. '
    '`make all` plus every `job_production_units` target and its supplemental makefiles: '
    '**four build invocations PASS, 59 freshness checks PASS**. '
    'The freshly linked root executable and frozen POST have byte-identical `.text` and '
    '`.rlfence` sections (`production-units-release.json`, `release-code-identity.json`).', '',
    'The table preserves failed and superseded attempts. Counts are public gate rows, '
    'not individual assertions or unique tests; repeated prerequisites are included. '
    'Each job’s original ledger and Tcl assertion names are in `gate-summary.json`; '
    'raw text artifacts are preserved in `gate-receipts.tar.gz` with a hashed inventory '
    'in `gate-receipts.json`.', '',
    '| Gate log in `docs/storefix5/` | Arm SHA prefix | Result | Disposition |',
    '|---|---|---|---|',
]
dispositions = {
    'gate-pre-witness.log': 'Expected PRE failures in both mode rows; release build passed.',
    'gate-live.log': 'Eight eviction setup failures; corrected fixture reruns retained below.',
    'gate-units.log': 'Initial production-build watchdog; dependent missing-marker failures; rerun below.',
    'gate-asan-release.log': 'ASAN build/five batteries/replyoff passed; six zc rows failed quiet-core preflight; serial retry below.',
    'gate-store-extra.log': 'One inherited rootcompat-stringlimit row fails; 78 rows pass.',
    'gate-stringlimit-pre.log': 'Same 24 above-32-bit representation assertions fail on PRE.',
    'gate-tcl-unfiltered-pre.log': 'Per mode: 10 COPY/DEBUG DIGEST and two replication failures; maxmemory has no executed assertion.',
    'gate-tcl-unfiltered.log': 'Same inherited Tcl assertion failures and external skips as PRE.',
    'gate-tcl-unfiltered-final.log': 'Exact same 10 keyspace + 2 string failures per mode as PRE; maxmemory has zero executed assertions.',
    'gate-extra-final.log': '16 missing paired-witness failures, FIFO p99, FLUSH deadline, inherited stringlimit; separate reruns/controls below.',
    'gate-native-final.log': 'Native jobs passed; storage_units is repeated below after strengthening the sampler-result assertion.',
    'gate-quiet-final.log': 'Selection exited 2 before any jobs: build-only prerequisites require consuming jobs; serial retry below.',
    'gate-quiet-final-retry.log': 'ASAN build and five batteries, zero-copy release/ASAN, and split-local units passed serially.',
    'gate-differ-uring-final.log': 'Four matrices passed: 231/235/235/239 rows (940 total); mode equivalence rejected shared CPUs before boot; corrected harness retry below.',
    'gate-differ-epoll-final.log': 'Four matrices passed: 231/235/235/239 rows (940 total), plus mode equivalence.',
    'gate-equivalence-uring-final.log': 'Mode equivalence passes with the guarded shared-CPU affinity fix; ordinary/performance callers still reject overlap.',
    'gate-sampler-final.log': 'All storage rows pass with the strengthened selected-key visibility assertion.',
    'gate-txn-pairing-final.log': 'All 18 rows pass after pairing the fresh native witnesses beside the frozen candidate.',
    'gate-flush-deadline-pre-final.log': 'Isolated PRE: both namespace rows, all eight legs each, pass the unchanged deadline.',
    'gate-flush-deadline-post-final.log': 'Isolated POST: same complete job passes; earlier overlapping-run misses remain recorded.',
    'gate-inventory-final.log': 'All other related jobs pass; notification eviction fixture hit its obsolete 16 KiB setup assumption; complete reruns below.',
    'gate-fifo-pre-final.log': 'Complete PRE control reproduces the p99 failure class; crossed fused outcomes remain unresolved as detailed below.',
    'gate-inventory-fused-final.log': 'Fused debug, SORT, reply suppression, ASAN and zero-copy jobs pass.',
    'gate-feature-product-final.log': 'All 35 feature cells pass, including the documented fused/flip refusal controls.',
    'gate-notify-pre-1s-final.log': 'Complete PRE notification job passes with the accounted-cohort fixture; both atomic settings execute.',
    'gate-notify-pre-2s-final.log': 'Complete PRE notification job passes with the accounted-cohort fixture; both atomic settings execute.',
    'gate-notify-post-1s-final.log': 'Complete POST notification job passes with the accounted-cohort fixture; both atomic settings execute.',
    'gate-notify-post-2s-final.log': 'Complete POST notification job passes with the accounted-cohort fixture; both atomic settings execute.',
    'gate-differ-uring-serial.log': 'Superseded after the retirement-ring defect was found: first 235-leg matrix passed; next matrix was stopped.',
    'gate-differ-uring-before-retirement.log': 'Preserved copy of the superseded serial attempt, not another run.',
}
for run in read(DOC/'gate-summary.json')['runs']:
    name = Path(run['log']).name
    verdict = f"{run['passed']} ok / {run['failed']} FAIL" if run['complete'] else 'INCOMPLETE'
    if name == 'gate-quiet-final.log' and not run['jobs']:
        verdict = 'NOT RUN (selection exited 2)'
    disposition = dispositions.get(name, 'Completed selected jobs.' if run['complete'] else 'Pending serial completion.')
    if name in ('gate-differ-uring.log', 'gate-differ-epoll.log'):
        disposition = 'Stopped after the POST compiler control changed; superseded.'
    elif name in ('gate-differ-uring-release.log', 'gate-differ-epoll-release.log'):
        disposition = 'First leg hit the 900-second watchdog under competing lane work; stopped and repeated serially.'
    elif name.endswith('-before-retirement.log'):
        disposition = 'Preserved copy of the pre-retirement-fix attempt, not another run; superseded.'
    elif name in ('gate-live-release.log', 'gate-native-release.log', 'gate-quiet-release.log'):
        disposition = 'Completed on the preceding POST; superseded by final-arm runs.'
    proof.append(f"| `{name}` | `{run['sha256'][:12]}` | {verdict} | {disposition} |")
fifo_path = DOC / 'fifo-pre-post-final.json'
if fifo_path.exists():
    fifo = read(fifo_path)
    pre_rows = {r['leg']: r for r in fifo['PRE']['legs']}
    post_rows = {r['leg']: r for r in fifo['POST']['legs']}
    proof += ['',
        'The FIFO live job retains its original p99 ≤ three derived FIFO cycles assertion. '
        'PRE and POST both ran all 16 sixty-second legs on the assigned shared eight-core geometry. '
        f"They share {len(fifo['common_failures'])} failing legs; "
        f"{len(fifo['PRE_only_failures'])} fail only on PRE and "
        f"{len(fifo['POST_only_failures'])} only on POST. "
        'This demonstrates the baseline failure class but does **not** establish no regression '
        'for the crossed fused results. The FIFO row remains red/unresolved; no deadline or '
        'duration was changed. A maintainer check on the gate’s reviewed disjoint CPU geometry '
        'is still required before a timing no-regression claim. '
        'Receipts: `fifo-pre-post-final.json` and the raw gate logs.', '',
        '| FIFO leg: databases / mode / atomic / engine | PRE | POST |',
        '|---|---|---|']
    def fifo_cell(row):
        if row['status'] != 'FAIL':
            return row['status']
        if row['errors']:
            error = ast.literal_eval(row['errors'][0])
            if isinstance(error, tuple) and error[0] == 'plain p99 exceeds three FIFO cycles':
                return f'FAIL: {error[1]*1000:.3f} > {error[2]*1000:.3f} ms'
        return 'FAIL (see raw receipt)'
    for leg in sorted(pre_rows.keys() | post_rows.keys()):
        proof.append('| ' + leg.removeprefix('fifo-').replace('-', ' / ') + ' | ' +
                     ' | '.join(fifo_cell(rows.get(leg, {'status': 'NOT RUN'}))
                                for rows in (pre_rows, post_rows)) + ' |')
proof += ['',
    'Frozen PRE and PAD-A both fail the RANDOMKEY all-shard sweep and idle-clock visibility '
    'witnesses in both modes. The frozen production-linked APPEND witness fails PRE with '
    'one merged scratch allocation and passes POST with zero '
    '(`append/pre-frozen-result.json`, `append/post-retirement-result.json`, '
    '`pad-final-{1s,2s}.json`).', '',
]
rendered = '\n'.join(lines)
rendered = rendered.replace('### Maintainer measurement request', '\n'.join(proof)+'\n### Maintainer measurement request')
(ROOT/'MEASURE-REQUEST-storefix5.md').write_text(rendered.rstrip()+'\n')
print('Wrote', ROOT/'MEASURE-REQUEST-storefix5.md')
