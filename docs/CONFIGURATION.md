# Configuration

Regenerated from `src/core/config.h` (Config, `parse_config_args`, and
`EncodingConfig::settings`) and [tomokv.conf](../tomokv.conf), checked against
`src/cmd/t_server.cc:308` for CONFIG and `src/cmd/t_server.cc:2013` for INFO.
The tables cover **68 canonical CONFIG entries, seven additional boot directives,
and nine encoding aliases**. Each accepted spelling has its own row.
`tests/docs_drift.py` compares these names with the parser; it does not validate
the prose, defaults, grammar, or INFO mappings.

Pass the config file as the **first positional argument**, then CLI overrides:
`./build/tomokv local.conf --port 7000` (`src/main.cc:164`). File lines use
`name value...`; only a trimmed line beginning with `#` is a comment. Single and
double quotes follow the loader's Redis-style token grammar; double quotes
recognize escapes including `\xHH` (`src/core/config.h:1235`).

**R** marks a Redis-compatible name/grammar; the row explicitly records TomoKV
limits or differences in behavior, defaults, and mutability. It is not a claim
of complete Redis equivalence. **T** marks a TomoKV-only directive/alias.
**Live** means CONFIG SET is supported; **Boot/GET** means CONFIG GET reports it
but SET refuses it; **Boot** means absent from the CONFIG table. INFO `—` means
no direct setting field; where useful, a row explicitly labels a related counter.
INFO server mappings are at `src/cmd/t_server.cc:2029`; persistence counters at
`:2209`, slowlog/latency counters at `:2356`, and `wb_policy` at
`src/core/wb_rule.h:31`. Use CONFIG GET for values without an INFO setting field.

Grammar shorthand: **u32** = unsigned decimal 0..4294967295; **u64** = unsigned
decimal 0..18446744073709551615; **i64** = signed decimal -9223372036854775808..
9223372036854775807. **Memory** = decimal bytes (optional `b`), decimal `k/m/g`,
or binary `kb/mb/gb`, case-insensitive. It accepts no signs or surrounding
whitespace; overflow follows the parser's unsigned saturation/multiply behavior
(`src/core/config.h:70`, `:452`, `:464`, `:479`). Encoding and stream exceptions
are specified below. Use Redis's yes/no spellings for shared boolean settings;
CONFIG SET also accepts 0/1 (`src/cmd/t_server.cc:505`).

## Threads, placement, and execution

Defaults: `src/core/config.h:292`, `:329`, `:350`, `:366`, `:375`, `:387`, `:427`;
annotated reference: `tomokv.conf:105`. Placement validation additionally checks
the allowed CPU set and complete SMT sibling units (`src/core/placement.h:73`).

| Name | Kind | Type / grammar | Default | Change | INFO field | Semantics / parser anchor |
| --- | --- | --- | --- | --- | --- | --- |
| `thread-mode` | T | `2s` or `1s`; aliases `split`, `fused` | `2s` | Boot/GET | `thread_mode` | Separate IO/executor roles or both on each thread; `src/core/config.h:783`. |
| `ratio` | T | Positive `io:ex` counts | Unset; even split in 2s | Boot | `io_threads`, `ex_threads` (current) | Whole-server role counts; rejected in 1s; `src/core/config.h:810`, `:1163`. |
| `place` | T | Comma-separated `ifid@CPU` / `ex@CPU` | Derived from allowed CPUs | Boot | `thread_cpus` | Explicit placement; mutually exclusive with ratio within a source, CLI replaces file choice; `src/core/config.h:1063`. |
| `shards` | T | `-1` or integer 1..256 | `-1` → min(8 × executors, 256) | Boot | `shards` | Initial migration units; resolved before recovery; `src/core/config.h:441`, `:826`. |
| `shard-home` | T | Complete comma-separated `shard:executor_tid` map | Round-robin | Boot | `shard_home`; `shard_owners` (current) | Dense placement thread IDs, not CPU IDs; empty owners allowed; `src/core/config.h:1055`, `src/core/placement.h:178`. |
| `no-pin` | T | Valueless CLI switch | Absent: pinning on | Boot | `pin_threads` | Disable worker CPU pinning; `src/core/config.h:1056`. |
| `overlap` | T | u32, 0 or 1 | `0` | Boot/GET | `overlap`, `overlap_enabled` | 2s owner prefetch and IO overlap; eligible 1s owner batches prefetch regardless; `src/core/config.h:326`, `:795`. |
| `read-local` | T | u32, 0 or 1 | `0` | Boot/GET | `read_local` | Eligible GET/MGET on the parsing thread in both modes; `src/core/config.h:801`, `src/main.cc:325`. |
| `reorder` | T | u32, 0 or 1 | `0` | Boot/GET | `reorder`, `reorder_retired` | 1s shadow priority; 2s resolves to 0; `src/core/config.h:437`, `:836`. |
| `wb-policy` | T | Literal `0` or `1` | `1` | Boot/GET | `wb_policy` (Writeback) | Flush-all or composite half rule; `src/core/config.h:843`, `src/core/wb_rule.h:25`. |
| `key-lb` | T | u32, 0 or 1 | `1` | Boot/GET | `key_lb` | Sample key demand and rebalance shard ownership; `src/core/config.h:851`, `src/core/server.h:1272`. |
| `key-lb-damping` | T | canonical signed decimal, -1..2147483647 | `-1` | Boot/GET | `tomokv_keylb_damping_band_pct`, `tomokv_keylb_damping_fire_pct`, `tomokv_keylb_damping_ticks` | 0 keeps the original key planner and allocates no damping sidecar; -1 derives damping from the decision window; positive N sets the level. Residual-band objective and bounded recent-move damping; `src/core/lbplanner.cc`. |
| `client-lb` | T | u32, 0 or 1 | `1` | Boot/GET | `client_lb` | Census client demand and move connections between IO owners; `src/core/config.h:857`, `src/core/server.h:529`. |
| `flip-auto` | T | u32, 0 or 1 | `0` | Boot/GET | `flip_auto`, `flip_fingerprint_window` (derived) | Automatic IO/executor split controller; 1s rejects 1; `src/core/config.h:863`, `:1168`. |
| `hash` | T | `mix64` or `siphash` | `mix64` | Boot | `hash` | Select key hash implementation; `src/core/config.h:1057`. |
| `zc-min` | T | u32 bytes | `16384` | Live | `zc_min` | Single GET borrow threshold (0 disables); scatter cutover has a separate zero caveat below; `src/core/config.h:1042`. |
| `atomic` | T | u32, 0 or 1 | `0` | Live | `atomic` | Enable the optional multi-key epoch-MVCC path; EXEC/script atomic machinery has separate admission; `src/core/config.h:1049`, `src/cmd/scatter_engine.inc:1742`. |

The file-only spelling `pin yes` leaves the default alone; `pin no` translates
to the valueless `--no-pin`. A later `pin yes` does not undo an earlier `pin no`
(`src/core/config.h:1342`). `--help` prints usage and exits; it is not a knob.

Read-local works with overlap 0 or 1 in both modes; split IO remains shard-less
(`src/core/rl2s.cc:72`, `:213`). A quota refusal or full lane **defers the frame,
never demotes it**: bytes remain unconsumed until lane work drains
(`src/core/io_loop.h:3443`). Safety/ordering failures can still require owner
execution. RYOW uses the connection's live write-ring predicate, including its
arming fence, precise hashes/keysets and conservative overflow generation
(`src/net/rob.h:557`, `:644`). See [Local reads](ARCHITECTURE.md#local-reads).

`reorder_retired=1` in 2s describes mode restriction, not removal of the 1s
mechanism (`src/cmd/t_server.cc:2038`). Neither writeback deferrals nor reorder's
pick bound is a wall-time latency guarantee; see `src/core/wb_rule.h:75` and
`src/core/reorder.h:441`.

## Network and TLS

automatically and falls back to OpenSSL; there is no `tls-ktls` switch. TLS 1.2
can offload both TX and RX. TLS 1.3 retains OpenSSL's receive record layer so
KeyUpdate and other post-handshake messages cannot enter the RESP parser. TomoKV
does **not** install a TLS 1.3 RX key from the initial client traffic secret or
promote TLS 1.3 to its raw receive path. With OpenSSL 3.0 this means userspace RX;
if a newer OpenSSL installs RX itself, its record layer remains responsible for
control records and re-keying.

TLS 1.3 TX offload is retained when OpenSSL and the kernel support it. On OpenSSL
3.0/3.1, TomoKV reinstalls the TX key on requested KeyUpdates using the updated
server traffic secret; this requires a kernel that supports replacing `TLS_TX`
keys on an established socket. AES-128-GCM, AES-256-GCM, ChaCha20-Poly1305 and
AES-128-CCM are covered. A failed reinstall closes the connection before further
application writes and reports `kTLS TX re-key failed`; kernels without TX re-key
support cannot claim TLS 1.3 KeyUpdate compatibility with TX offload. OpenSSL
3.2+ owns TX re-keying in its record layer. Software TLS needs no kernel TLS
support and keeps the same RESP behavior.
`INFO STATS` exposes cumulative `tls_ktls_rx_declined_13` (successful socket-BIO
TLS 1.3 handshakes retained by OpenSSL) and `tls_ktls_tx_rekeys` (successful TX
reinstalls by TomoKV's OpenSSL 3.0/3.1 compatibility path). Neither counts failed
handshakes. `tls_ktls_active` still means **bidirectional raw offload**, so a TLS
1.3 TX-only connection contributes to `tls_ktls_fallback`, not that gauge.
Paper wording for the OpenSSL 3.0 build, after the directed kernel checks pass:
“TLS 1.2/1.3 with kernel TLS TX offload on kernels supporting TX re-keying; RX
offload for TLS 1.2, with TLS 1.3 RX and KeyUpdate handled by OpenSSL.” Do not
claim TomoKV implements TLS 1.3 RX offload with re-key handling. See
[tls.cc](../src/net/tls.cc) and the directed [KeyUpdate witness](../tests/ktls_keyupdate.cc).
Unterminated inline requests have Redis's fixed 64 KiB `PROTO_INLINE_MAX_SIZE` bound and close with `ERR Protocol error: too big inline request`. Redis 7.4 does not expose a `proto-max-inline` CONFIG option. TomoKV's receive cursors remain 32-bit even when `client-query-buffer-limit` is set above that representation limit.
Defaults: `src/core/config.h:316`, `:395`; reference: `tomokv.conf:27`.
All TLS fields are boot-only. A nonzero TLS port needs a certificate and key;
client-auth yes/optional also needs a CA file or directory. Enabled TCP and TLS
ports must differ (`src/core/config.h:1182`). Empty TLS protocol/cipher settings
select the built-in defaults, not the example file paths in tomokv.conf
(`src/net/tls.cc:37`, `:148`).

| Name | Kind | Type / grammar | Default | Change | INFO field | Semantics / parser anchor |
| --- | --- | --- | --- | --- | --- | --- |
| `port` | R | Integer 0..65535 | `6379` | Boot/GET | `tcp_port` | Plain TCP listener; 0 disables it; `src/core/config.h:603`. |
| `bind` | R | Single address string | `127.0.0.1` | Boot/GET | — | Single IPv4 bind address, not Redis's address list; `src/core/config.h:646`, `src/core/io_loop.h:162`. |
| `unixsocket` | R | Path string | Unset | Boot/GET | — | Optional Unix listener; `src/core/config.h:647`. |
| `unixsocketperm` | R | Octal mode 0..777 | `0` | Boot/GET | — | 0 preserves umask; otherwise chmod the socket; `src/core/config.h:125`, `:648`. |
| `net-io` | T | `uring` or `epoll` (case-insensitive) | `uring` | Boot/GET | `net_io`, `multiplexing_api` | Network engine also selects uring/syscall persistence; `src/core/config.h:445`, `:974`. |
| `maxclients` | R | Integer 1..4294967295 | `10000` | Live | — | Accept admission ceiling; concurrent acceptors can overshoot; `src/core/config.h:654`, `tomokv.conf:59`. |
| `timeout` | R | Integer 0..2147483647 seconds | `0` | Live | — | Idle normal-client timeout, 0 off; blocked/pubsub exempt; `src/core/config.h:660`, `tomokv.conf:64`. |
| `tcp-keepalive` | R | Integer 0..2147483647 seconds | `300` | Live | — | TCP keepalive for newly accepted clients; 0 off; `src/core/config.h:666`. |
| `tcp-backlog` | R | Integer 0..2147483647 | `511` | Boot/GET | — | listen backlog, kernel may cap it; `src/core/config.h:672`, `src/cmd/t_server.cc:615`. |
| `client-output-buffer-limit` | R | Repeated `class hard soft seconds`; memory bytes, seconds 0..2147483647 | `normal 0 0 0`; `replica 256mb 64mb 60`; `pubsub 32mb 8mb 60` | Live | — | Classes normal, replica/slave, pubsub; replica round-trips as slave but is inert; `src/core/config.h:182`, `:678`. |
| `tls-port` | R | Integer 0..65535 | `0` | Boot/GET | — | Independent TLS listener; 0 allocates no TLS context; `src/core/config.h:611`. |
| `tls-cert-file` | R | PEM path | Unset | Boot/GET | — | Server certificate chain; `src/core/config.h:619`. |
| `tls-key-file` | R | PEM path | Unset | Boot/GET | — | Server private key; `src/core/config.h:620`. |
| `tls-ca-cert-file` | R | PEM path | Unset | Boot/GET | — | Trusted client CA file; `src/core/config.h:621`. |
| `tls-ca-cert-dir` | R | CA directory path | Unset | Boot/GET | — | Trusted client CA directory; `src/core/config.h:622`. |
| `tls-auth-clients` | R | `yes`, `no`, `optional` (case-insensitive) | `yes` | Boot/GET | — | Require, omit, or optionally verify client certificates; `src/core/config.h:623`. |
| `tls-protocols` | R | Quoted space-separated TLSv1/TLSv1.1/TLSv1.2/TLSv1.3, case-insensitive | Empty → TLSv1.2 + TLSv1.3 | Boot/GET | — | Allowed protocol versions; `src/core/config.h:634`, `src/net/tls.cc:37`. |
| `tls-ciphers` | R | OpenSSL cipher-list string | Empty → `ECDHE-ECDSA-AES128-GCM-SHA256:ECDHE-RSA-AES128-GCM-SHA256` | Boot/GET | — | TLS ≤1.2 cipher list; `src/core/config.h:635`, `src/net/tls.cc:150`. |
| `tls-ciphersuites` | R | OpenSSL TLS 1.3 suite-list string | Empty → `TLS_AES_128_GCM_SHA256` | Boot/GET | — | TLS 1.3 suites; `src/core/config.h:636`, `src/net/tls.cc:157`. |
| `tls-prefer-server-ciphers` | R | `yes` or `no` (case-insensitive) | `no` | Boot/GET | — | Prefer server cipher order; `src/core/config.h:637`. |

Output limits count TomoKV's growable buffers and retained borrow segments;
hard closes at `>=`, soft closes after a continuous interval `> seconds`,
and zero disables each threshold (`tomokv.conf:94`, `src/core/io_loop.h:5306`).

## Persistence, databases, and memory

Defaults: `src/core/config.h:342`, `:360`, `:371`; reference: `tomokv.conf:187`,
`:246`, `:292`. `dir`, `dbfilename`, and `tcp-backlog` are explicitly rejected
by CONFIG SET even though their table entries lack the immutable flag
(`src/cmd/t_server.cc:615`).

| Name | Kind | Type / grammar | Default | Change | INFO field | Semantics / parser anchor |
| --- | --- | --- | --- | --- | --- | --- |
| `dir` | R | Nonempty directory path | `.` | Boot/GET | — | Persistence directory; `src/core/config.h:953`, `:1211`. |
| `dbfilename` | R | Nonempty filename without `/` | `dump.tomo` | Boot/GET | — | Snapshot filename; `<dir>/<dbfilename>` auto-loads at boot when AOF recovery supplied no base or increment plan; `src/core/config.h:954`, `src/main.cc:249`. |
| `save` | R | Repeatable positive seconds / u64 changes pairs; empty string disables | `3600 1 300 100 60 10000` | Live | Related: `rdb_changes_since_last_save`, `rdb_scheduled_saves` | Periodic snapshot clauses; first clause in a new source replaces prior source's schedule; `src/core/config.h:145`, `:905`. |
| `appendonly` | R | `yes` or `no` (case-insensitive) | `no` | Boot/GET | `aof_enabled` | Enable multipart AOF; runtime toggle unsupported; `src/core/config.h:955`. |
| `appendfsync` | R | `always`, `everysec`, `no` (case-insensitive) | `everysec` | Live | Related: `aof_fsyncs` | AOF batch sync policy; `src/core/config.h:964`, `tomokv.conf:273`. |
| `appendfilename` | R | Nonempty name without `/` | `appendonly.aof` | Boot/GET | — | AOF name prefix; `src/core/config.h:983`, `:1216`. |
| `appenddirname` | R | Nonempty name without `/` | `appendonlydir` | Boot/GET | — | Multipart AOF subdirectory under dir; `src/core/config.h:984`, `:1216`. |
| `auto-aof-rewrite-percentage` | R | u32 percent | `100` | Live | Related: `aof_auto_rewrite_triggers` | Growth trigger, 0 disables automatic rewrite; `src/core/config.h:985`. |
| `auto-aof-rewrite-min-size` | R | Memory, u64 bytes | `64mb` (67108864) | Live | Related: `aof_current_size` | Minimum size for automatic rewrite; `src/core/config.h:991`. |
| `aof-use-rdb-preamble` | R | Only `yes` (case-insensitive) | `yes` | Live, fixed value | — | Base is a TomoKV snapshot, not a Redis RDB; `no` refused; `src/core/config.h:997`, `src/cmd/t_server.cc:609`. |
| `aof-timestamp-enabled` | R | `yes` or `no` (case-insensitive) | `no` | Live | — | Write AOF timestamp annotations; `src/core/config.h:1004`. |
| `aof-load-truncated` | R | `yes` or `no` (case-insensitive) | `yes` | Live, next AOF load | — | Discard only an incomplete final increment tail, or refuse recovery; older increments remain strict. CONFIG SET stores the next-load policy and CONFIG REWRITE persists it; `src/core/config.h:1048`, `tomokv.conf:287`. |
| `databases` | R | Integer 1..256 | `1` | Boot/GET | Related: `dbN` (Keyspace) | Logical namespaces in the shared store; SELECT 0..N−1; `src/core/config.h:933`, `src/cmd/t_server.cc:395`. |
| `proto-max-bulk-len` | R | Memory, 1048576..4294901759 bytes | `512mb` (536870912) | Live | — | Request bulk-length bound, capped by TomoKV's Slice ABI; `src/core/config.h:140`, `:941`. |
| `client-query-buffer-limit` | R | Memory syntax, 1048576..9223372036854775807; zero is rejected | `1gb` (1073741824) | Live | — | Bound on pending input plus queued MULTI arguments; overflow closes the connection without a reply, before AUTH too; `src/core/config.h:965`, `tomokv.conf:306`. |
| `maxmemory` | R | Memory, u64 bytes | `0` | Live | — | Store memory ceiling, 0 unlimited; not a process RSS cap; `src/core/config.h:869`. |
| `maxmemory-policy` | R | `noeviction`, `allkeys-lru`, `allkeys-lfu`, `allkeys-random`, `volatile-lru`, `volatile-lfu`, `volatile-random`, `volatile-ttl` | `noeviction` | Live | — | Eviction policy; `src/core/config.h:875`, `src/store/eviction.h:36`. |
| `maxmemory-samples` | R | Integer 1..64 | `5` | Live | — | Eviction sample width; `src/core/config.h:882`. |

Recovery uses AOF first when enabled; when no AOF base or increment recovery
plan exists, startup tries `<dir>/<dbfilename>`. Missing snapshot means empty startup; unreadable or invalid
snapshot fails startup (`src/main.cc:236`, `:249`). Choose a fresh directory for
an empty example. The save schedule describes periodic saves; it alone does not
establish shutdown durability (see `src/cmd/server_tail.cc:249`, `src/main.cc:65`).

### DBSIZE and INFO keyspace publication

In both database images, plain `DBSIZE` and INFO's keyspace section read
per-shard published counters. Each owner publishes at an executor batch boundary:
the count can lag its owner's mutations by **one batch boundary**, with no fixed
wall-clock bound while an owner is busy. A pipeline can observe the preceding
batch's count. `DBSIZE NOW` is TomoKV's exact-on-demand extension; it scatters to
all owners and counts the selected logical database after earlier dispatched
work. Neither mode reaps expired-but-resident keys merely to count them.

INFO emits `dbN:keys=K,expires=E,avg_ttl=T` for each nonempty logical database. `keys` and
`expires` have the same one-boundary publication lag. `avg_ttl` is a nonnegative
millisecond estimate: with `databases 1`, at publication the owner samples at most 16 expiry-index
slots, using a cursor separate from active expiry, then INFO subtracts the current
wall clock from that sample's mean deadline. It is zero when no keys have an
expiry or no sample has been recorded; an empty sample retains the preceding
estimate. It is an estimate, not an exact average
over every deadline; polling INFO visits no objects. All existing structure-size
locks remain unchanged; each store has a 16-byte cold sampling sidecar.

With `databases > 1`, each shard has 256 owner-private physical-namespace rows
and separate published key/expiry pairs and mean deadlines. Key and deadline
mutations update only owner-private rows; the batch boundary publishes dirty
rows. DBSIZE sums the selected physical row over the shards. INFO reads the
configured logical-to-physical map once, then the corresponding published rows.
This costs O(shards × configured databases), independent of the key population.
The multi-DB TTL estimate subtracts wall time from the published mean deadline,
clamping at zero. SWAPDB relabels the same physical counters; MOVE and FLUSHDB
account only for their affected namespaces. See [the ST2 completion report](../MEASURE-REQUEST-storesize2.md).

The INFO field definitions and section routing are in [INFO.md](INFO.md).

## Collection encodings

The seven canonical rows and nine aliases come directly from
`src/core/config.h:247`; defaults are at `:256`, parsing at `:534`, and shard
limit application at `:269`. Reference comments: `tomokv.conf:304`.
**Count64** means canonical decimal 0..9223372036854775807 (no leading `+` or
redundant zeroes). Hash/zset memory limits accept empty strings and bare units
as zero, with a 9223372036854775807 ceiling. Legacy compact aliases instead take
bare u32 decimal, including leading zeroes. Internal collection limits saturate
at u32; a CONFIG update does not eagerly rebuild existing collections.

| Name | Kind | Type / grammar | Default | Change | INFO field | Semantics / parser anchor |
| --- | --- | --- | --- | --- | --- | --- |
| `hash-max-listpack-entries` | R | Count64 | `512` | Live | — | Compact hash entry ceiling; `src/core/config.h:248`. |
| `hash-max-listpack-value` | R | Memory ≤9223372036854775807 | `64` | Live | — | Compact hash field/value byte ceiling; `src/core/config.h:249`. |
| `list-max-listpack-size` | R | Canonical signed 32-bit decimal | `-2` | Live | — | -1..-5: 4/8/16/32/64 KiB; smaller negatives clamp to 64 KiB; nonnegative count with 8 KiB ceiling, 0 allows one element; `src/core/config.h:250`, `src/store/typeval.h:33`. |
| `set-max-listpack-entries` | R | Count64 | `128` | Live | — | Compact string-set entry ceiling; `src/core/config.h:251`. |
| `set-max-listpack-value` | R | Count64, no memory suffix | `64` | Live | — | Compact string-set element byte ceiling; `src/core/config.h:252`. |
| `zset-max-listpack-entries` | R | Count64 | `128` | Live | — | Compact sorted-set entry ceiling; `src/core/config.h:253`. |
| `zset-max-listpack-value` | R | Memory ≤9223372036854775807 | `64` | Live | — | Compact sorted-set member byte ceiling; `src/core/config.h:254`. |
| `hash-max-ziplist-entries` | R | Count64 | `512` | Live | — | Alias of hash-max-listpack-entries; `src/core/config.h:248`. |
| `hash-max-ziplist-value` | R | Memory ≤9223372036854775807 | `64` | Live | — | Alias of hash-max-listpack-value; `src/core/config.h:249`. |
| `list-max-ziplist-size` | R | Canonical signed 32-bit decimal | `-2` | Live | — | Alias of list-max-listpack-size; `src/core/config.h:250`. |
| `zset-max-ziplist-entries` | R | Count64 | `128` | Live | — | Alias of zset-max-listpack-entries; `src/core/config.h:253`. |
| `zset-max-ziplist-value` | R | Memory ≤9223372036854775807 | `64` | Live | — | Alias of zset-max-listpack-value; `src/core/config.h:254`. |
| `hash-max-compact-entries` | T | u32 decimal | `512` | Live | — | Legacy alias of hash-max-listpack-entries; `src/core/config.h:248`. |
| `hash-max-compact-value` | T | u32 decimal bytes | `64` | Live | — | Legacy alias of hash-max-listpack-value; `src/core/config.h:249`. |
| `zset-max-compact-entries` | T | u32 decimal | `128` | Live | — | Legacy alias of zset-max-listpack-entries; `src/core/config.h:253`. |
| `zset-max-compact-value` | T | u32 decimal bytes | `64` | Live | — | Legacy alias of zset-max-listpack-value; `src/core/config.h:254`. |
| `hll-sparse-max-bytes` | R | Memory, 0..4294967295 bytes | `3000` | Boot/GET | — | Sparse HLL promotion cutoff; 0 forces dense on sparse growth; `src/core/config.h:1022`, `tomokv.conf:333`. |
| `stream-node-max-bytes` | R | Memory, 0..4294967295; empty/bare unit = 0 | `4096` | Live | — | Stream macro-node byte rollover, 0 disables this axis; `src/core/config.h:503`, `:1031`, `src/store/typeval.h:50`. |
| `stream-node-max-entries` | R | Canonical decimal 0..4294967295 | `100` | Live | — | Stream macro-node entry rollover, 0 disables this axis; `src/core/config.h:1031`, `src/store/typeval.h:50`. |

Aliases share canonical CONFIG storage (`src/cmd/t_server.cc:428`). CONFIG GET
with `*` emits the 68 canonical names plus nine aliases (`:1380`). Integer sets
retain a separate fixed 128-entry bound (`tomokv.conf:330`); the string-set
listpack controls do not change it. Use the listed defaults when reproducing
results, rather than assuming every default equals the Redis reference.

## Security, notifications, and observability

Defaults: `src/core/config.h:333`, `:383`, `:389`, `:411`;
reference: `tomokv.conf:202`, `:344`, `:376`.

| Name | Kind | Type / grammar | Default | Change | INFO field | Semantics / parser anchor |
| --- | --- | --- | --- | --- | --- | --- |
| `requirepass` | R | String | Empty | Live | — | Default-user password; existing connections keep their authentication latch until RESET; `src/core/config.h:704`, `tomokv.conf:346`. |
| `protected-mode` | R | `yes`, `no`, `1`, `0` (boot literals) | `yes` | Live | — | Refuse non-loopback clients without a configured password; GET emits yes/no; `src/core/config.h:762`. |
| `enable-debug-command` | R | `no`, `yes`, `local` (boot literals) | `no` | Boot/GET | — | DEBUG access policy; local allows loopback/Unix clients; `src/core/config.h:773`. |
| `aclfile` | R | Path string | Unset | Boot/GET | — | ACL LOAD/SAVE path; mutually exclusive with inline users; `src/core/config.h:705`, `:1203`. |
| `user` | R | Repeatable `name rule...` | No inline definitions | Boot | — | Redis root ACL rules; selectors are unsupported; use ACL SETUSER live; `src/core/config.h:706`, `tomokv.conf:356`. |
| `acl-pubsub-default` | R | `allchannels` or `resetchannels` (case-insensitive) | `resetchannels` | Live | — | Channel permission of new/reset users; `src/core/config.h:724`. |
| `acllog-max-len` | R | u64 | `128` | Live | — | ACL LOG capacity per IO thread; 0 disables storage; `src/core/config.h:733`. |
| `notify-keyspace-events` | R | Flag string: `K E g $ l s h z x e t d m n A`; empty off | Empty | Live | — | K/E channel kinds, event classes; A expands to g$lshzxetd and excludes m/n; `src/core/config.h:889`, `src/cmd/notify.h:66`. |
| `tracking-table-max-keys` | R | u64 | `1000000` | Boot/GET | — | Remembered-key bound per IO owner, 0 unlimited; allocated on CLIENT TRACKING use; `src/core/config.h:899`, `src/cmd/t_server.cc:391`. |
| `slowlog-log-slower-than` | R | i64 microseconds ≥-1 | `10000` | Live | Related: `slowlog_batches_timed`, `slowlog_entries_recorded` | -1 disables log, 0 logs all; default arms batch timing; `src/core/config.h:739`, `src/cmd/slowlog.h:27`. |
| `slowlog-max-len` | R | u64 | `128` | Live | — | Entries per recording thread; SLOWLOG LEN may exceed this number; 0 retains none; `src/core/config.h:747`, `tomokv.conf:393`. |
| `latency-monitor-threshold` | R | Canonical decimal 0..4294967295 milliseconds | `0` | Live | Related: `latency_events_recorded` | Command latency samples, 0 off; shares timing arming with slowlog; `src/core/config.h:753`, `src/cmd/slowlog.h:27`. |

## CONFIG and limits of this reference

CONFIG GET/SET use the table in `src/cmd/t_server.cc:308`. REWRITE requires a
startup file (`src/cmd/server_tail.cc:674`), preserves its directives outside
that table (`:681`), canonicalizes encoding aliases (`:694`), and quotes/escapes
values (`:653`, `:723`). It writes save clauses separately and skips the fixed
AOF preamble declaration (`:643`, `:707`). This is not an export of CLI-only
placement overrides. See [FINDINGS](FINDINGS.md#configuration-round-tripping).

The single-GET zero-copy gate and scatter gather cutover differ at zero:
`src/cmd/t_string.cc:354` tests whether zc-min is enabled, whereas
`src/cmd/scatter_engine.inc:2985` takes `min(zc-min, ValueSlot::kInline)`.
Thus zero cannot be advertised as disabling all scatter borrow allocations.

## Worked example

Save the following as `build/docs-example.conf` (create `build/` first). It
uses real directives and leaves the shipped save/slowlog defaults armed:

```conf
bind 127.0.0.1
port 6399
thread-mode 2s
shards 16
overlap 0
read-local 0
key-lb 1
key-lb-damping -1
client-lb 1
reorder 0
save 3600 1
save 300 100
save 60 10000
slowlog-log-slower-than 10000
```

Mainline verification command, from the repository root, with a fresh data
directory and the gate's eight-core 6 IO + 2 executor geometry:

```bash
DOCS_DATA_DIR=$(mktemp -d /tmp/tomokv-docsregen.XXXXXX)
taskset -c 0-7 ./build/tomokv build/docs-example.conf --ratio 6:2 --dir "$DOCS_DATA_DIR"
```

From another terminal: `redis-cli -p 6399 PING`,
`redis-cli -p 6399 CONFIG GET databases`, and `redis-cli -p 6399 INFO server`.
Expect PONG, databases=1, thread_mode=2s, shards=16, overlap=0, read_local=0,
key_lb=1, client_lb=1, reorder=0. Stop with `redis-cli -p 6399 SHUTDOWN NOSAVE`.
The parser and serverless geometry check can validate this example without a
listener; live boot and these replies are maintainer-run checks.
