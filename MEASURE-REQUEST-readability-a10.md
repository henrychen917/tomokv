## readability-a10

Branch `cx-readability-a10`; source baseline `7595a6705a`; frozen release
`5c36312818`. All source edits are confined to the 18 assigned files. No push.
No code tokens, literals, names, layouts, definitions, includes or tool markers
changed. Historical rationale is in [the decision log](docs/decisions/readability-a10.md).
No throughput measurement or performance claim is made.

### Delivered counts

| Item | Count |
| --- | ---: |
| Existing comment blocks rewritten | 160 |
| New comment blocks | 32 |
| Comment blocks removed | 0 |
| Contract blocks added/completed | 46 |
| Phase landmarks | 5 |
| Owned files with headers | 18 / 18 |
| Dated decision-log entries | 41 |
| Local/internal renames | 0 |
| Interface-first splits attempted / kept / reverted | 0 / 0 / 0 |

A comment block is the comments between consecutive unchanged preprocessing tokens;
whitespace-only differences are ignored. Contracts, headers and landmarks overlap
these block counts. The 46 contracts include expanded existing ownership comments
and supplementary contracts below the length threshold. The code-line inventory
finds [14 functions over 50 non-comment lines](docs/decisions/readability-a10-function-census.txt), all covered; the sole function over
150 lines is tracking_client_subcommand, with five phases. Macro-expanded writeback
retirement also has contracts on both template wrappers.

The interface-first inventory finds Client (347 in-class code lines), WbEngine
(592), Rob (485) and Ring (242). Client::migration_protocol_idle is a file-path patch
site in tools/archive/tools/flipfix6_diag.py. WbEngine has live file-path readers in
tests/wbland_checks.py and tests/racefix.py. Rob is explicitly comments-only for
A20; Ring is below the approximately 300-line threshold. No class is split, and
no definition or experiment flag moves. The erroneous numbered flush_ready pointer
in rob.h now names the AOF-fence/bounded-serving step by content.

### Binary and token proof

The maintained frozen PRE is
`/home/user/Projects/bins/readability-pre-5c363128/tomokv`; it was not rebuilt.
The final source commit is `9738303dc5`.

```sh
export LC_ALL=C TOMO_INFO_GIT_SHA1=5c363128 TOMO_INFO_GIT_DIRTY=0
taskset -c 84-111 make -j28 all
/home/user/Projects/calib/binary-neutral.sh /home/user/Projects/bins/readability-pre-5c363128/tomokv build/tomokv
```

```text
IDENTICAL (11167504 bytes after stripping)
```

`make -q all` exits 0. The comparator strips debug/symbol tables and the build-ID
note, then compares every remaining byte; this is binary identity under the
programme's specified comparator, not an assertion that debug-bearing ELF files
have the same hash.

[Token evidence](docs/decisions/readability-a10-token-proof.json) records per-file
SHA-256 digests and counts. `tools/source_tokens.py.lex` compares spelled tokens
without alias normalization against both `7595a6705a` and `5c36312818`:
54,159 / 54,159 identical. All 569 string/character/raw-string literal tokens are
byte-identical. All three TOMO_TOOL_ANCHOR/BIND markers remain byte-identical at
their original token boundary. The rename table is empty. This also proves include
and definition order is unchanged. No R7 generated block changed.

| Owned file (all have a header) | Tokens | Literals | Existing blocks rewritten | New blocks |
| --- | ---: | ---: | ---: | ---: |
| `src/cmd/client_pause.h` | 163 | 0 | 0 | 1 |
| `src/cmd/clientcompat.cc` | 1835 | 10 | 4 | 2 |
| `src/cmd/climon.cc` | 10186 | 186 | 9 | 2 |
| `src/cmd/network_config.h` | 489 | 28 | 1 | 0 |
| `src/cmd/tracking.cc` | 8177 | 62 | 15 | 6 |
| `src/net/conn.h` | 5437 | 14 | 27 | 3 |
| `src/net/epoll.h` | 361 | 1 | 4 | 0 |
| `src/net/errorstats.h` | 734 | 19 | 1 | 2 |
| `src/net/idle_buffers.h` | 1035 | 2 | 3 | 1 |
| `src/net/query_limit_stats.h` | 61 | 0 | 1 | 0 |
| `src/net/resp.h` | 6295 | 135 | 20 | 3 |
| `src/net/resp3.h` | 866 | 24 | 2 | 0 |
| `src/net/rob.h` | 4660 | 18 | 38 | 1 |
| `src/net/tls.cc` | 3985 | 47 | 1 | 2 |
| `src/net/tls.h` | 814 | 0 | 2 | 2 |
| `src/net/unix_listener.h` | 692 | 8 | 4 | 1 |
| `src/net/uring.h` | 2206 | 6 | 12 | 1 |
| `src/net/wb.h` | 6163 | 9 | 16 | 5 |

### Verification status

The pinned clang-format 18.1.8 `make format` and `make format-check` passed before
each source commit (418 files); formatter token/literal/anchor guards remained on.
`git diff --check` passed. No generated envelope was stale. EXPECT_QUICK and
EXPECT_FULL were not edited; no row is added/retired (DQ = DF = 0).

Gate jobs use `LC_ALL=C`, pins `TOMO_INFO_GIT_SHA1=5c363128` /
`TOMO_INFO_GIT_DIRTY=0`, `GATE_PROOF_NO_RATES=1`, outer taskset 84-111,
`--server-cores 84-109 --server-smt '' --load-cores 110-111 --load-smt ''
--ports 25400-25499`. The planner gives one correctness slot, eight server threads
at ratio 6:2 and 16 shards; prerequisite builds use the permitted allocation.
Only selected whole jobs run. These partial ledgers cannot earn a release receipt.

The actual `GATE_ONLY_JOBS` selections were:

| Run / log prefix under build/readability-a10 | Selected jobs |
| --- | --- |
| gate-source | `abba_selftest reorder_sync` |
| gate-proof | `source_identity cmd_metadata reorder_identity wbland_units rob_portable netfix_idle_buffers multidb-2s-0-1 multidb-1s-1-1 trackfix_order notifycompat racefix_counters` |
| gate-final | `wbland_units tracking_redirect` |
| gate-selftest-retry | `abba_selftest` |

Each invocation is `taskset -c 84-111 bash tests/gate.sh iteration` with the
common arguments above and its own `GATE_LEDGER` path; the interface appends
`.partial`. Build-only prerequisites are selected by the gate dependency graph.

The first `abba_selftest` attempt hit its existing 660-second row budget while
`tests/gates_test.py` was running. Earlier suites in that job, including all 12
label-fixture controls, passed. This timeout is retained in
`build/readability-a10/gate-source.ledger.partial`; it is not a passing receipt.
The same run's `reorder_sync` row passed. The isolated retry passed in 572.91 seconds
with the original 660-second budget and unchanged assertions.

The main selected run, `build/gate-run.P18yVX`, completed **23 ok, 0 FAIL**.
Its ledger is `build/readability-a10/gate-proof.ledger.partial`.

| Job | Result | Scope established |
| --- | --- | --- |
| release | PASS | Release build and layout locks |
| production_units | PASS (build and up-to-date queries) | All 61 primary targets plus extra build recipes |
| racefix_tsan_build | Build succeeded | TSan diagnostics for both runtime modes |
| source_identity | PASS | 61 C++ translation units in both namespaces, six C units and stable assertion controls |
| cmd_metadata | PASS | Dynamic command-source inventory |
| rob_portable | PASS | Portable completion and missing-fence negative control |
| multidb-1s-1-1 | 3 PASS | Live parked/wake controls, namespace compatibility, SWAPDB serial order and XREAD wake |
| multidb-2s-0-1 | 3 PASS | Same coverage in split mode |
| reorder_identity | PASS | 352/352 identical bodies; missing-symbol/opcode controls reject broken twins |
| racefix_counters | PASS | Both thread modes, zero TSan reports/runtime failures |
| wbland_units | 2 PASS | Policy clauses/paths and source-removal controls |
| netfix_idle_buffers | PASS | TCP/TLS × epoll/io_uring × both modes, Redis oracle and broken-policy control |
| notifycompat | 7 PASS | All notification compatibility cases against Redis 7.4 |
| trackfix_order | PASS | All 16 configurations, each 30 assertions passed |
| reorder_sync (earlier run) | PASS | R7 parity, lexer controls and all 62 lottery insertion sites |

The final-source refresh, `build/gate-run.giPboS`, completed **4 ok, 0 FAIL**:
release, both writeback rows and `tracking_redirect`. Its 65 build-readiness
markers cover the 61 primary production targets plus the parked/no-wake arms,
blockfix-cost pair and two blockfix2 units. The REDIRECT schedule builder and all
runtime configurations passed.

[Build-query evidence](docs/decisions/readability-a10-build-proof.json) records
**68/68 successful `make -q` queries**: `all`, each of the 61 primary targets,
the two exact recursive `all` commands behind the phony `mdbqsbr-live-arms`
aggregator, and four supplemental blockfix targets. The final `make -j28 all`
and frozen-release binary comparison also passed after the final source commit.

The isolated retry, `build/gate-run.XTwUag`, completed **1 ok, 0 FAIL**.
`tests/gates_test.py` passed **83 tests** (311.832 seconds), and
`tests/gate_ledger_fixture.py`, invoked by gate_receipt's self-test, passed all
**12 tests**. Every later helper in the same whole job completed successfully.
[All four partial ledgers](docs/decisions/readability-a10-gate-results.json) retain
the initial timeout as well as the successful retry; no failed attempt is hidden.

**NOT RUN:** full iteration/quick/full gate certification, throughput benchmarks,
ABBA measurements, NIC tier, unselected correctness jobs, and archived/manual
historical campaigns. Production-unit targets outside the selected jobs were
built and queried, not executed as a complete runtime suite. Every requested
live source-reader check whose current inputs include an edited file ran.

Disposable scheduled tracking/REDIRECT sources, objects and binaries, R7 twin
binary/disassembly copies, the completed idle-buffer mutant source, the first
self-test's abandoned fixtures and the completed TSan compiler cache were removed.
Build prerequisites and proof logs remain under build/. The worktree is about
23.5 GB apparent size (du reports 23G allocated), below the 30 GB limit. All
committed lane files are below 1 MB. No push or gate-count edit is made.

### A1 source-reader coverage

The triage was filtered for live source readers, then checked for literal paths
and dynamic inventories (`src/cmd/*.cc`, whole-source assertion/identity scans).
This table records the consuming gate jobs; final verdicts are in the result table.

| A1 live reader/check | Edited inputs / coverage | Gate job |
| --- | --- | --- |
| tools/source_tokens.py; tests/source_tokens_test.py | Spelled tokens and all marker bindings, including tracking.cc and uring.h | reorder_sync plus per-file token proof |
| tests/r7shadow_sync.py; tests/r7shadow_sync_test.py; tools/reorder_sync.py | Whole-source policy inventory; generated parity and stale-copy controls | reorder_sync |
| tools/lottery_build.py | Tracking event/forward seams and TLS SSL_accept/SSL_read seams; all 62 insertion sites and missing/duplicate controls | reorder_sync |
| tools/source_identity.py; tools/assert_map.py; tests/tomo_assert_checks.py | All owned production headers/translation units, both namespaces, stable assertion maps | source_identity; release/production builds |
| tests/cmdmeta_coverage.py | Dynamic scan of every command .cc file, including three edited command implementations | cmd_metadata |
| tests/rob_portable_control.py | rob.h portable MGET fence-clear mutant | rob_portable |
| tests/wbland_checks.py | wb.h source/phase policy, clauses/paths and source-removal controls | wbland_units |
| tests/mdbqsbr_live.py | uring.h kWaitTimeoutMs binding and parked/wake controls | multidb-1s-1-1; multidb-2s-0-1 |
| tests/netfix_idle_buffers.py | idle_buffers.h recent-peak mutant and runtime matrix | netfix_idle_buffers |
| tests/racefix.py | wb.h counter-write location inventory against rebuilt TSan diagnostics | racefix_counters |
| tools/notifycompat_schedule.py | tracking.cc and climon.cc disposable schedule injection | tracking_redirect |
| tools/trackfix_schedule.py | tracking.cc and climon.cc disposable delayed-write schedule injection | trackfix_order |
| tests/reorder_receipt.py; tests/reorder_noop.py; tests/r7shadow_noop.py; tests/r7shadow_pad.py | Linked FIFO/R7 identity and negative controls; shared canonical role readers | reorder_identity |
| tests/gates_test.py; tests/gate_ledger_fixture.py | Scheduler/parser controls; 12 label-fixture controls called by gate_receipt self-test | abba_selftest |

The existing R7 identity job creates `fifo-twin`, labelled **PAD kind A: FIFO
behaviour at candidate text size/layout**. It is used for identity and negative
controls; no readability measurement or new PAD arm is requested.

No additional source patch run is needed for tools/rlfence_artifacts.py: its live
path is ELF role analysis. The rob.h reference in prepare_alt hashes a historical
FROZEN_POST archive after applying an archived patch, not this worktree's source.
Likewise the retained tools/ttlstate_proof.py historical source-editing CLI is
outside A1's live ELF-helper scope. Historical benchmarking/manual campaigns and
archived patch tools were not replayed. tests/gate.sh's tls.cc mention is its TSan
build source list, covered by racefix_tsan_build. Unedited command registries used
by the ACL/command generators are outside the changed-input set; the dynamic
command coverage scan is included above.

### Contract evidence

Citations name the implementation branch or operation supporting the stated claim and its production caller. Whole-tree caller searches included tests, tooling, R7 generated envelopes and other subsystems. Caller roles refer to production ownership; standalone units construct or emulate that ownership. Failure claims distinguish returned errors from uncaught allocation exceptions. Comments do not promise atomicity where the wrapper has no synchronization.

| Contract | Claims checked | Evidence |
| --- | --- | --- |
| ErrorStats | Owns 128 bounded entries and aggregate counters. Record, INFO and reset lock the same mutex; saturation disables detail, not totals. | `src/net/errorstats.h:14`, `src/net/errorstats.h:40`, `src/net/errorstats.h:86`, `src/net/errorstats.h:104` |
| ErrorStatsProbe | Paired stack guard changes a thread-local suppression count, without publishing state; the disposable tracking parser is its production caller. | `src/net/errorstats.h:30`, `src/net/errorstats.h:33`, `src/cmd/tracking.cc:215` |
| IdleBuffers | Owns IO-local peak samples. Cron/migration/close call visit/forget; a relaxed CAS coalesces purges. Map insertion can throw; failed realloc retains allocation. | `src/net/idle_buffers.h:23`, `src/net/idle_buffers.h:48`, `src/core/io_loop.h:5348`, `src/core/io_loop.h:1875`, `src/core/io_loop.h:5563` |
| IdleBuffers::visit | Caller supplies kernel/OpenSSL pins; ROB quiescence excludes borrowed argv/direct output. Returns a receive-cancellation request, preserves failed reallocs, and samples capacity/cursors locally. | `src/net/idle_buffers.h:65`, `src/net/idle_buffers.h:96`, `src/net/idle_buffers.h:121`, `src/core/io_loop.h:5352` |
| LateUnixListener | Boot owns retained fd and pathname; configuration backs borrowed path_. Destructor closes/unlinks; successful attach precedes fd transfer. No worker publication in open. | `src/net/unix_listener.h:24`, `src/main.cc:368`, `src/main.cc:626`, `src/core/genthread.cc:265`, `src/core/rl2s.cc:315`, `src/core/reorder.cc:3377` |
| LateUnixListener::open | Runs after recovery/before listener activation in all four boot paths. Empty path succeeds; repeated owned open fails; errors/partial cleanup are explicit. Probe/unlink has no atomic process exclusion. | `src/net/unix_listener.h:43`, `src/main.cc:573`, `src/core/genthread.cc:254`, `src/core/rl2s.cc:304`, `src/core/reorder.cc:3366` |
| TlsContext | Owns SSL_CTX; main creates the shared context before worker startup, per-connection initialization borrows native(). Checked failures report null/error; no wrapper mutation lock. | `src/net/tls.h:46`, `src/main.cc:255`, `src/net/tls.cc:245`, `src/net/tls.cc:357` |
| TlsConn | IoLoop owns SSL/BIO state in slots; socket and retry plaintext are borrowed. WANT preserves reservations for retry; result enum directs teardown. Destructor frees SSL/BIO and cleanses secrets; joined cleanup is exclusive. | `src/net/tls.h:65`, `src/core/io_loop.h:5811`, `src/net/tls.cc:249`, `src/net/tls.cc:481`, `src/core/shutdown.cc:52` |
| TlsContext::create | Config-derived boot factory; checked protocol/cipher/cert/CA errors return null with context released by unique_ptr. Allocation can throw; publication happens outside the factory. | `src/net/tls.cc:187`, `src/main.cc:255`, `src/net/tls.cc:195` |
| EpollSet | Owns fd/batch; loop owns batch access, but migration source can call destination registration hooks. epoll_ctl has no wrapper lock. Separate reuseport listeners; syscall failures/empty waits/close are explicit. | `src/net/epoll.h:51`, `src/core/io_loop.h:245`, `src/core/io_loop.h:1789`, `src/core/thread.h:448`, `src/core/io_loop.h:99` |
| RespInlineDecoder | Stateless parsing helper with exclusive caller-owned outputs. Input is borrowed; successful decode transfers its malloc block to Op. Syntax/OOM return Error, without publication. | `src/net/resp.h:86`, `src/net/resp.h:163`, `src/net/resp.h:209`, `src/net/resp.h:177` |
| RespInlineDecoder::split | Null-output count pass followed by decode pass into argc slots/end-p bytes. Input/reply are untouched, failures may leave partial outputs, and the function allocates/waits/publishes nothing. | `src/net/resp.h:100`, `src/net/resp.h:163` |
| RespFrontier | Owns realloc-grown offsets, not input bytes. push preserves prior storage on failure; finish resets and frees capacity above 512. Caller must serialize and avoid shallow copies; Client transfers as a whole. | `src/net/resp.h:424`, `src/net/resp.h:436`, `src/net/resp.h:447`, `src/net/conn.h:910`, `src/core/io_loop.h:1815` |
| resp_resume | Caller exclusively owns Op/frontier/input; offsets are frame-relative. Completion advances pos and borrows slices; incomplete retains pos/progress; malformed/OOM returns Error. Caller pins/publishes later. | `src/net/resp.h:539`, `src/net/resp.h:339`, `src/core/io_loop.h:3747`, `src/core/reorder.cc:2268` |
| resp_parse_t | Requires empty argv and stable input; resume requires frontier/multibulk input. Result/cursor rules, limited versus constant fast bounds and cold exceptional limits follow branches; caller retains borrowed bytes. | `src/net/resp.h:598`, `src/net/resp.h:339`, `src/core/io_loop.h:3747`, `src/net/conn.h:338` |
| format_reply_code | Valid ReplyCode and kReplyCodeMax caller storage required. Fixed table copies inline; integer loop is out-of-line. No publication or bounds check. | `src/net/resp.h:897`, `src/net/resp.h:877`, `src/net/wb.h:41`, `src/net/resp.h:913` |
| Session | Connection-owned selected database; ConnLocal selection executes on IO and parser captures routing into Op. No internal synchronization. | `src/net/conn.h:67`, `src/net/conn.h:756`, `src/cmd/multidb.cc:718`, `src/core/io_loop.h:3704` |
| ReplySegment | Descriptor distinguishes owned Buf, borrowed shard value and external Static bytes; queue consumes Buf and uses supplied release callback for Borrow. Copying metadata does not copy payload ownership. | `src/net/conn.h:99`, `src/net/conn.h:197`, `src/net/conn.h:276` |
| SegmentQueue | Connection owner serializes queue changes; owned payloads stay independent of growing metadata. Explicit consume/truncate/release_all return Borrows, destructor frees Buf/metadata only. malloc failures are unchecked; caller preserves iovecs. | `src/net/conn.h:114`, `src/net/conn.h:144`, `src/net/conn.h:214`, `src/net/conn.h:231`, `src/net/conn.h:253` |
| Client | Owns buffers/segments/ROB/MultiSession; IoLoop closes fd and owns TLS slots. IO cursor access and joined shutdown are exclusive; workers borrow pinned ranges and release-publish Done. Ownership uses release/acquire; capacity/read-space backpressure and safe release fences are explicit. | `src/net/conn.h:300`, `src/net/conn.h:306`, `src/net/conn.h:653`, `src/net/conn.h:794`, `src/core/shutdown.cc:52`, `src/core/ex_loop.h:1510` |
| Client::read_space_impl | IO caller fences growth with ROB quiescence/no outstanding receive pointer. Query and inline bounds allow detection byte; failed growth retains storage; no room returns null/zero for retry. | `src/net/conn.h:376`, `src/core/io_loop.h:1007`, `src/core/io_loop.h:1029`, `src/core/reorder.cc:1687` |
| Ring | Owns native/eventfd mailbox/deferred CQEs, borrows shutdown fd. Issuer performs SQ/CQ; coordinator drains after join. Mutex publishes mailbox tags; native submission uses liburing. Init/SQE shortage and quiescent teardown contracts follow branches. | `src/net/uring.h:85`, `src/net/uring.h:237`, `src/net/uring.h:399`, `src/net/uring.h:157`, `src/core/shutdown.cc:100`, `src/core/shutdown.cc:180` |
| Ring::RegisteredFd | Borrows Ring; task-local registration ends before post-join queue teardown. Failed registration leaves guard empty; unregister failure aborts. No new cross-thread publication. | `src/net/uring.h:170`, `src/core/io_loop.h:603`, `src/core/reorder.cc:813`, `src/core/io_loop.h:604`, `src/core/shutdown.cc:180` |
| ReadLocalArmStats | Borrowed ThreadCtx-embedded counters; arming, sidecar allocation and write commitment increment on owning parser/read-local role. Adoption replaces pointer. Unarmed streams do not commit records; cross-thread observation is not established by this struct. | `src/net/rob.h:70`, `src/core/thread.h:198`, `src/core/io_loop.h:1881`, `src/net/rob.h:802`, `src/net/rob.h:662`, `src/net/rob.h:966` |
| ReadLocalRobState | Rob owns lazily allocated sidecar; parser/read-local role accesses generations locally. Retired prefix pruning uses flush id; stale records conservatively conflict. nothrow failure resets arming; no retry/lock protocol is added. | `src/net/rob.h:81`, `src/net/rob.h:715`, `src/net/rob.h:655`, `src/net/rob.h:468`, `src/net/rob.h:862` |
| ReadLocalPendingFilter | Four owned words hold two bits per key. Local mutation has no synchronization or allocation; misses skip exact checks, hits require them. | `src/net/rob.h:153`, `src/net/rob.h:287`, `src/net/rob.h:421` |
| Rob | Power-of-two/eight-slot constraints, lazy chunk ownership and optional sidecar. IO issues/drains, joined coordinator may drain ready prefix. Done acquire and dispatch/flush release stores provide stated fences; full window returns null, chunk new can throw, sidecar has false fallback. | `src/net/rob.h:184`, `src/net/rob.h:254`, `src/net/rob.h:688`, `src/net/rob.h:727`, `src/net/rob.h:655`, `src/core/shutdown.cc:171` |
| Rob::drain | Stops at first non-Done op; acquire orders reply before sink, then Free and final flush release. Sink finishes using Op before reuse; IO and joined coordinator supply callbacks. | `src/net/rob.h:688`, `src/net/wb.h:266`, `src/core/shutdown.cc:168` |
| WbEngine | IO owner plus joined shutdown coordinator with rebound callbacks. Borrowed Ring/contexts/config/signals must outlive use. Client owns output, engine owns deferred strings; Done acquire orders staging. Partial/WANT/EAGAIN/SQE failures retain work; fatal/limit paths and allocation behavior stay explicit. | `src/net/wb.h:59`, `src/net/wb.h:76`, `src/core/io_loop.h:121`, `src/cmd/flip_liveness.inc:314`, `src/core/shutdown.cc:69`, `src/net/wb.h:943` |
| WbEngine::DeferredOob | Owns frame strings behind exclusive dispatch frontier; queue releases eligible frames after flush, including joined cleanup. | `src/net/wb.h:62`, `src/net/wb.h:128`, `src/net/wb.h:744`, `src/core/shutdown.cc:171` |
| WbEngine::serve_suppressing_impl | IO caller binds dependencies; Done acquire precedes suppression and retirement hook, discarded borrows are released. Plain-retire enables tracking. Limit closure controls submit_allowed; staged work retries and bool reports work. No allocation catch. | `src/net/wb.h:259`, `src/cmd/climon.cc:730`, `src/cmd/climon.cc:760`, `src/net/rob.h:688` |
| WbEngine::pump_tls | IO or joined coordinator sends ciphertext head then encrypts pinned plaintext. Separate Client/BIO cursors; borrowed segments and mismatched retry pins abort. WANT/SQE/inflight retain work; TLS failure returns false and caller checks TLS state. | `src/net/wb.h:460`, `src/net/wb.h:943`, `src/core/io_loop.h:1266`, `src/core/shutdown.cc:169` |
| WbEngine::serve_impl | IO/joined ordinary or kTLS retirement acquires Done, calls special hooks, stages bytes/borrow/CRLF. Compile-time accounting/submit/TlsNoBorrow choices govern limits, deferred pumping and copies; bound callbacks and pins remain required. | `src/net/wb.h:770`, `src/net/wb.h:845`, `src/net/wb.h:166`, `src/core/shutdown.cc:171` |
| WbEngine::serve_tls_impl | Same caller/Done/acquire/limit contract; copy borrowed values, append CRLF, release reference. Pending ciphertext counts toward pumping; WANT/SQE shortfall keeps staged work. | `src/net/wb.h:866`, `src/net/wb.h:200`, `src/core/shutdown.cc:168` |
| WbEngine::on_send_complete | IO or joined coordinator consumes byte-count/errno CQE, clears send pin, accounts/releases consumed borrows. Retryable errors retain output and optional followup; fatal errors return false. Does not retire replies. | `src/net/wb.h:560`, `src/core/io_loop.h:1257`, `src/core/reorder.cc:1891`, `src/core/shutdown.cc:106` |
| WbEngine::on_tls_send_complete | Same exclusive callers (joined followup disabled); clear pin, consume BIO ciphertext without plaintext advancement. Retry/failure/closing-output branches hand remaining lifetime to caller. | `src/net/wb.h:620`, `src/core/io_loop.h:1277`, `src/core/reorder.cc:1951`, `src/core/shutdown.cc:110` |
| tracking_prepare_multi::Context | Borrowed stack visitor state; synchronous multi_tracking_children does not retain context. Snapshot/caching are copied values, used on connection IO. | `src/cmd/clientcompat.cc:59`, `src/cmd/multi.inc:2818`, `src/cmd/multi.inc:2870` |
| tracking_finish_multi::Context | Borrowed loop/client/optional batch for synchronous visitor; calling IO keeps them alive without pointer publication. | `src/cmd/clientcompat.cc:96`, `src/cmd/multi.inc:2818`, `src/core/io_loop.h:150`, `src/cmd/multi.inc:3187` |
| notify_multi_before | Committed subscription processing on IO follows finalized acquire and borrows acquire-loaded batch. Ordered selected route bits are consumed; tracking retained. Empty/OOM/budget exhaustion returns no chain and counts drops when selected; shared reservation uses relaxed CAS/fetch_sub, not recipient publication. | `src/cmd/clientcompat.cc:174`, `src/cmd/multi.inc:2988`, `src/cmd/multi.inc:3103`, `src/cmd/notify.inc:295`, `src/core/server.h:3475` |
| command_client_pause | IO and MULTI owner callers borrow Op/reply sink; unknown command false, invalid arguments synchronous reply. Time cut/monotonic fallback, relaxed deadline/mode and armed acq_rel refresh; optional peer wake, no park in helper. | `src/cmd/climon.cc:217`, `src/cmd/multi.inc:3052`, `src/cmd/multi_execute.inc:269`, `src/core/server.h:2507`, `src/core/server.h:3619` |
| climon_start_client_unblock | Requesting IO validates unpublished CLIENT slot; local/missing Sync. Remote request retained, ROB release-published and barrier armed until retirement. ID transport mutex publishes; wake-channel saturation spins, duplicate pending aborts, allocations can throw. | `src/cmd/climon.cc:1042`, `src/cmd/climon.cc:1283`, `src/net/rob.h:254`, `src/core/pubsub.inc:120`, `src/core/thread.h:650` |
| climon_start_client_kill | Requesting IO builds owned filter; argument errors Sync, valid input starts scatter. Release-published slot/barrier/result path delegates to shared helper; allocation/wake-space behavior follows transport. | `src/cmd/climon.cc:1139`, `src/cmd/climon.cc:1226`, `src/core/pubsub.inc:120`, `src/net/rob.h:254` |
| climon_start_client_command | Validated MONITOR/CLIENT caller on connection IO, unpublished slot. Sync returns through pubsub_start_command to dispatch/finish_prebuilt; Async helper publishes and installs barriers. Fallback binds/unbinds local and snapshot context; validation, allocation and transport behaviors remain delegated. | `src/cmd/climon.cc:1271`, `src/core/pubsub.inc:1364`, `src/core/io_loop.h:4019` |
| tracking_register_read | IO gate and EXEC preparation borrow enabled state/op; state owns strings/observations/receipt until retirement. BCAST/eligibility/CACHING/invalid probe rules precede allocation. Queueing preserves registry spec; subsequent dispatch publishes selection. | `src/cmd/tracking.cc:180`, `src/cmd/climon.cc:632`, `src/cmd/clientcompat.cc:86`, `src/cmd/tracking.cc:293`, `src/core/io_loop.h:3939`, `src/core/reorder.cc:2460` |
| tracking_handle_event | Borrowed local/queued event, receiving IO owns tables. Re-resolve migration IDs, match rejection generation/target, no transported foreign Client. Missing destinations discard/report; mutex publication and wake-space spin come from pubsub_post. | `src/cmd/tracking.cc:700`, `src/cmd/tracking.cc:633`, `src/cmd/climon.cc:1492`, `src/core/pubsub.inc:986`, `src/core/pubsub.inc:120`, `src/core/thread.h:650` |
| tracking_client_subcommand | Validated CLIENT on IO/IO-local EXEC children. Owned maps/prefixes; unknown NotHandled, invalid Sync. ON generation acq_rel and arming refresh; current ROB slot can defer OK behind PubSub/config readiness, EXEC children Sync. Uncaught allocations except timer helper catch. | `src/cmd/tracking.cc:868`, `src/cmd/tracking.cc:95`, `src/cmd/climon.cc:1369`, `src/cmd/multi.inc:3050`, `src/cmd/clientcompat.cc:114`, `src/cmd/clientcompat.cc:19`, `src/core/server.h:3370` |

### Additional header and ordering evidence

| Location | Claim | Evidence |
| --- | --- | --- |
| client_pause.h | Deadline pointer is release-published by command_bind_server and acquire-loaded before relaxed deadline access; Server owns storage. Store expiry callers consult it. | `src/cmd/t_server.cc:4036`, `src/cmd/client_pause.h:16`, `src/core/server.h:2522`, `src/store/flatstore.h:1284` |
| network_config.h | Normalization writes caller outputs without installing config. Mutability comes from ConfigValue.immutable and the CONFIG table/apply path; net-io/unix/TLS context settings shown here are immutable while timeout is not. | `src/cmd/network_config.h:24`, `src/cmd/t_server.cc:374`, `src/cmd/t_server.cc:443`, `src/cmd/t_server.cc:422`, `src/cmd/t_server.cc:493`, `src/cmd/t_server.cc:474`, `src/cmd/t_server.cc:870`, `src/cmd/t_server.cc:944` |
| query_limit_stats.h | Relaxed disconnect tally carries no connection-state publication. IoLoop overflow close paths record it; INFO and RESETSTAT load/reset it relaxed. | `src/net/query_limit_stats.h:13`, `src/core/io_loop.h:983`, `src/core/io_loop.h:987`, `src/cmd/t_server.cc:3328`, `src/cmd/t_server.cc:4021` |
| resp3.h | Included after the RESP2 builders; protocol-selecting overloads emit sink bytes or fixed reply codes. TRACKING supplies push frames, while request parsing is shared. | `src/net/resp.h:931`, `src/net/resp3.h:13`, `src/net/resp3.h:73`, `src/cmd/tracking.cc:462`, `src/core/io_loop.h:3747` |
| rob.h landmark | The corrected pointer names the AOF reply fence and bounded serving FIFO. Local pending slots cease at local execution/demotion, independent of later reply retirement. | `src/net/rob.h:329`, `src/core/io_loop.h:774`, `src/core/io_loop.h:5067` |
| tracking.cc boundaries | Global membership filter has set/load operations and stays monotonic across flush. BCAST flush follows notification drain and precedes bounded reply serving; transport uses a mutex. | `src/cmd/tracking.cc:57`, `src/cmd/tracking.cc:673`, `src/core/pubsub.inc:1008`, `src/core/io_loop.h:5051`, `src/core/thread.h:650` |

### A19 proposals (not implemented)

| Current cross-file name | Proposed name | Reason / constraint |
| --- | --- | --- |
| Client::ifid_thread / set_ifid_thread | io_owner_id / set_io_owner_id | Names the ownership value and publication edge; touches migration and core callers. |
| ClimonConn / ClimonPending | ClientControlState / ClientControlRequest | Shared CLIENT/MONITOR/TRACKING state extends beyond monitoring. |
| WbEngine | ReplyWriter | Covers retirement, frame staging and socket progress; requires updating tool role bindings/readers. |
| Rob::dispatch_id / flush_id | next_issue_id / next_retire_id | Makes the exclusive-frontier convention explicit across IO/executor code. |
| ReadLocalRobState | ReadLocalWriteHistory | Names the owned sidecar's write-history role; coordinate with A20 scaffolding work. |
| UrKind | IoCompletionKind | Distinguishes completion tags from command kinds; encoded values must stay unchanged. |

The decision log retains historical measurements as inherited provenance, with
no validation claim from this lane. Full iteration, benchmarks and merging remain
maintainer work. No new server behavior or correctness-law exception is introduced.
