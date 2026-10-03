Lane `ktlsfix`, NET2, 2026-10-03. Worktree/branch: `cx-ktlsfix`.
Launch HEAD: `e279aeb4cf08ae2c39f26be679388b872fed4667`.
`git fetch origin cpp && git merge --no-edit origin/cpp` completed first: already up to date.
Implementation commits: `94fdf6cad` (build/gate the original witness), then
`701191701` (RX policy, TX re-key handling, directed tests and documentation).
No push, server, load generator, benchmark, or gate run. Every build and executable
serverless check ran under `taskset -c 112-127`; no test ran on cores 0-111.

**Implemented option:** the mainline default of declining TomoKV's manual TLS 1.3
RX offload. TLS 1.3 stays in OpenSSL's receive record layer; TLS 1.2 bidirectional
offload and eligible TLS 1.3 TX offload remain. This is not a new raw `recvmsg`
control-record implementation. An installed RX direction cannot simply be removed
and handed to the existing ciphertext BIO-pair transport. The old manual install
also never informed OpenSSL of its RX ownership/sequence state. Avoiding that
initial install uses the existing valid socket-BIO fallback and keeps OpenSSL
responsible for post-handshake messages. No root-only feature is needed for this
choice. A dedicated raw TLS 1.3 control-record/re-key layer was not implemented.

The requested fallback exposed a second, necessary part of this same defect:
OpenSSL 3.0.13 changes its userspace TX key on a requested KeyUpdate without
reinstalling the kernel TX key. Merely deleting the RX install would still break
that witness. The patch therefore installs updated TX keys from OpenSSL's
`SERVER_TRAFFIC_SECRET_N` callback on the old record layer, after the old-key
KeyUpdate and before the next application write. The serverless negative control
with just that callback disabled fails. OpenSSL 3.2+ retains its own re-key path;
the new compatibility-path counters/tests were verified on this box's 3.0.13.

Diagnosis anchors at launch HEAD:

| Anchor | Confirmed mechanism |
| --- | --- |
| `src/net/tls.cc:193-213` | Captures only `CLIENT_TRAFFIC_SECRET_0`. |
| `src/net/tls.cc:216-243` | HKDF derives the initial AES-128-GCM RX key/IV and installs `TLS_RX`; no successor key. |
| `src/net/tls.cc:347-354` | Successful manual RX plus native TX promotes the connection to `State::Ktls`. |
| `src/core/io_loop.h:845-889,1392-1395` | Raw receive path and exclusion of promoted connections from the SSL engine. |
| `tests/ktls_keyupdate.cc` | Existing client witness demands kTLS, requests an update, then checks PING; no original Makefile/gate reference. |

The kernel requires ancillary record-type handling for control messages and new
keys through the TLS socket options. This is a userspace responsibility, not
something raw receives provide automatically. [Linux kTLS documentation](https://docs.kernel.org/networking/tls.html).
OpenSSL's old key-update implementation derives/logs the new secret without a
kernel TX reinstall. [OpenSSL 3.0.13 `tls13_update_key`](https://github.com/openssl/openssl/blob/openssl-3.0.13/ssl/tls13_enc.c#L688).

Patch anchors in this branch:

| Anchor | Result |
| --- | --- |
| `Makefile:124,128` | Builds the live witness and the serverless unit. |
| `src/net/tls.cc:388-421` | Removes manual TLS 1.3 RX installation and prohibits TLS 1.3 raw promotion, including when a newer SSL library reports native RX. Counts successful socket-BIO TLS 1.3 handshakes retained by OpenSSL once. |
| `src/net/tls.cc:133-156,226-283` | TX reinstall, sequence reset to zero, SHA-256/SHA-384 and four eligible TLS 1.3 cipher families; process-lifetime relaxed counters. |
| `src/net/tls.cc:236-242,426-452` | Failed TX reinstall shuts down the socket and rejects further plaintext writes with an explicit diagnostic. |
| `src/cmd/t_server.cc:2341,2485` | INFO STATS: `tls_ktls_rx_declined_13` and `tls_ktls_tx_rekeys`. Existing active gauge remains bidirectional raw offload. |
| `tests/ktls_keyupdate_unit.cc:1-294` | Genuine OpenSSL handshakes/records over AF_UNIX socketpairs; only offload observations and kernel key installs are link-wrapped. No listener, child process, worker, or kernel TLS context. |
| `tests/ktls_keyupdate.cc` | Live TX and pure-userspace arms, sole-connection arming, both KeyUpdate types, repeated updates, PING/ECHO byte/order receipts, exact TX re-key deltas. |
| `tests/tls.py:285-328` | TLS 1.2 still requires bidirectional offload in that arm; TLS 1.3 requires OpenSSL RX and a new decline count. Existing client-reply suppression checks remain. |
| `docs/CONFIGURATION.md:198-229` | Transport policy, counter semantics, kernel prerequisite and paper wording. |

The unit's TX material oracle independently derives key/IV from the **peer's**
updated secret with OpenSSL's TLS13-KDF API; it does not reuse the implementation's
HKDF encoder. It covers AES-128-GCM, AES-256-GCM, ChaCha20-Poly1305 and AES-128-CCM,
checks distinct successive keys and zero record sequence, and injects `EBUSY` to
prove failed reinstalls reject application writes. Software-TLS cases cover
forced and automatic BIO-pair fallback, both KeyUpdate types and negotiated
512-byte maximum fragments (the live pure-userspace arm).

Validation actually executed:

```sh
taskset -c 112-127 make -j16 BUILD_ROOT=build/ktlsfix/pre
taskset -c 112-127 make -j16
taskset -c 112-127 make -j16 build/ktls-keyupdate build/ktls-keyupdate-unit
taskset -c 112-127 python3 tests/tls.py --generate build/ktlsfix/certs
for arm in rx-policy tls12 userspace tx-rekey tx-failure; do
  taskset -c 112-127 build/ktls-keyupdate-unit build/ktlsfix/certs "$arm"
done
```

Both complete server binaries built successfully, including both database variants
and the fused/split code. No compiler warnings/errors appeared. The same five
cases passed under ASAN+UBSAN, with leak detection and halt-on-error enabled:

```text
ok: NET2 rx-policy (TlsConn=136)
ok: NET2 tls12 (TlsConn=136)
ok: NET2 userspace (TlsConn=136)
ok: NET2 tx-rekey (TlsConn=136)
ok: NET2 tx-failure (TlsConn=136)
```

Logs: `build/ktlsfix/{pre-build,post-build,unit-build,post-unit,asan-unit,controls-build}.log`.
`bash -n tests/gate.sh`, Python byte compilation of `tests/tls.py`, `git diff --check`,
and a pinned `make -j16 -q all build/ktls-keyupdate build/ktls-keyupdate-unit` passed.

Two throwaway negative controls were built with
`taskset -c 112-127 make -j16 -f build/ktlsfix/controls.mk all`:

| Control | Exact check and observed exit/output |
| --- | --- |
| Original `tls.cc`/`tls.h`, copied from launch HEAD under `build/ktlsfix/nofix/src/net`, same current unit source | `taskset -c 112-127 build/ktlsfix/ktls-keyupdate-unit-nofix build/ktlsfix/certs rx-policy`: exit **1**, `FAIL rx-policy: TLS13_RX_DECLINED: no initial-secret TLS_RX install` |
| POST source with only `SERVER_TRAFFIC_SECRET_N ` replaced by an ignored label in the callback, under `build/ktlsfix/no-tx/tls.cc` | `taskset -c 112-127 build/ktlsfix/ktls-keyupdate-unit-no-tx build/ktlsfix/certs tx-rekey`: exit **1**, `FAIL tx-rekey: TLS13_TX_REKEY: both requested updates reinstall TX` |

Control build recipes and copied sources remain under `build/ktlsfix/`; none is
committed or was used with a server or production data. The original-code TLS 1.2
unit also passes and reports `TlsConn=136`. The archived original **live** witness
was rebuilt as `build/ktlsfix/ktls-keyupdate-live-pre` but was not run.

All requested layout locks compiled unchanged: Op 336 / Client 1984 / ThreadCtx
1408 / Shard 1440 / FlatStore 944 / Rob<64> 192 / AtomicEntry 144 / Config 624.
TlsConn also remains 136 bytes: its former 32-byte RX secret scratch now holds
transient derived TX key bytes, with the original flag slot used for a re-key
failure. No layout change, hence no PAD arm. No runtime knob was added. The
ordinary command/store/ordering/writeback implementations were not changed;
`io_loop.h`, `wb.h`, and `reorder.cc` were untouched, so the conditional wbland
clauses requirement was not triggered. Booting both modes and live Redis-visible
TLS behavior remain mainline checks; builds/unit checks are not substitutes for them.

Gate accounting (by actual line and collection position):

| `tests/gate.sh` row | Change |
| --- | --- |
| 2255: NET2 serverless RX policy and KeyUpdate controls | +1 |
| 2339: TLS 1.3 KeyUpdate survives (NET2) | +1 |
| 2345: TLS 1.3 userspace KeyUpdate survives (NET2) | +1 |
| 2323: existing live engagement row | Retained, explicitly pins TLS 1.2; +0. |

`collect_job tls` is line **2852**, before the quick exit at **2902**. Thus
quick **446 -> 449**, full **463 -> 466**, plus the existing optional `NIC_CHECKED`
full-tier addition. `EXPECT_QUICK`/`EXPECT_FULL` at 261-262 were **not edited**.
Both witness binaries are production-unit prerequisites with freshness markers;
TLS depends on those builds, and a missing/failed witness is a failed row.
Mainline must update its expected counts before using a green complete-gate result.

Mainline live request: **not executed in this lane**. No throughput claim is made.
Use the built POST `build/tomokv`, or rebuild with the prescribed pinned make.
The default software-kTLS rig is sufficient: loopback TCP, OpenSSL with kTLS and
kernel TLS with TX re-key support. No NIC/netns rig or root is inherently required.
If the module needs loading, the maintainer may need root for `modprobe tls`; a
netns/NIC reproduction also needs its usual privileges. An unavailable mechanism
must fail the live row, never skip or relax its assertions.

These exact commands run both transport arms and the existing TLS battery for each
engine/thread mode on fresh state, at gate geometry (8 cores, 16 shards, split 6:2;
fused omits the split-only ratio). Run only in mainline's scheduled quiet window:

```bash
cd /home/user/Projects/cx-ktlsfix
taskset -c 112-127 make -j16 all build/ktls-keyupdate build/ktls-keyupdate-unit
taskset -c 112-127 python3 tests/tls.py --generate build/ktlsfix/live-certs
set -e
KTLS_CERT_DIR="$PWD/build/ktlsfix/live-certs"
KTLS_PLAIN_PORT=16400
KTLS_TLS_PORT=16401
for mode in 2s 1s; do
  for engine in uring epoll; do
    KTLS_DATA_DIR=$(mktemp -d "$PWD/build/ktlsfix/live-$mode-$engine.XXXXXX")
    taskset -c 96-103 python3 - "$KTLS_PLAIN_PORT" "$KTLS_TLS_PORT" <<'PYPORT'
import socket, sys
for port in map(int, sys.argv[1:]):
    with socket.socket() as probe:
        probe.bind(('127.0.0.1', port))  # occupied port is a fatal error
PYPORT
    role=(--thread-mode "$mode")
    if [ "$mode" = 2s ]; then role+=(--ratio 6:2); else role+=(--flip-auto 0); fi
    taskset -c 0-7 build/tomokv "${role[@]}" --net-io "$engine" \
      --shards 16 --bind 127.0.0.1 --port "$KTLS_PLAIN_PORT" --tls-port "$KTLS_TLS_PORT" \
      --tls-cert-file "$KTLS_CERT_DIR/server.crt" --tls-key-file "$KTLS_CERT_DIR/server.key" \
      --tls-ca-cert-file "$KTLS_CERT_DIR/ca.crt" --tls-auth-clients no \
      --protected-mode no --save '' --appendonly no --dir "$KTLS_DATA_DIR" \
      >"$KTLS_DATA_DIR/server.log" 2>&1 &
    KTLS_PID=$!
    trap 'kill -TERM "$KTLS_PID" 2>/dev/null || true; wait "$KTLS_PID" 2>/dev/null || true' EXIT
    taskset -c 96-103 python3 - "$KTLS_PLAIN_PORT" <<'PY'
import socket, sys, time
for _ in range(100):
    try:
        with socket.create_connection(('127.0.0.1', int(sys.argv[1])), timeout=.2):
            break
    except OSError:
        time.sleep(.1)
else:
    raise SystemExit('FAIL: bounded server readiness')
PY
    kill -0 "$KTLS_PID"
    taskset -c 96-103 build/ktls-keyupdate 127.0.0.1 "$KTLS_TLS_PORT" tx
    taskset -c 96-103 build/ktls-keyupdate 127.0.0.1 "$KTLS_TLS_PORT" userspace
    taskset -c 96-103 python3 tests/tls.py 127.0.0.1 "$KTLS_TLS_PORT" "$KTLS_CERT_DIR" no \
      --plain-port "$KTLS_PLAIN_PORT" --full --expect-ktls yes
    kill -TERM "$KTLS_PID"
    wait "$KTLS_PID"
    trap - EXIT
  done
done
```

Decisive results: both `ok: NET2 live KeyUpdate tx` and
`ok: NET2 live KeyUpdate userspace`; each survives four successive updates and
byte/order receipts. TX's counter must increase exactly twice; userspace's must
not increase. The full battery must also prove TLS 1.2 bidirectional offload,
TLS 1.3 RX decline, reply suppression, record framing and coexistence.
For the original live counterexample, boot only `build/ktlsfix/pre/tomokv` with the
same fresh split command, and run
`taskset -c 96-103 build/ktlsfix/ktls-keyupdate-live-pre 127.0.0.1 16401`.
It must print its kTLS arming witness, then fail on the legal KeyUpdate; failure
before arming is insufficient evidence. This live PRE/POST result is still pending.
After updating the three counts in mainline, `tests/gate.sh iteration` is the
requested full correctness/performance gate; no perf number is supplied here.

Important compatibility limit: preserving TLS 1.3 TX requires actual kernel
`TLS_TX` replacement support. A kernel rejection is fatal and diagnosed, as tested;
this patch does not claim to make unsupported kernels re-key. The live TX counter
also specifically instruments the verified OpenSSL 3.0/3.1 compatibility path;
on an OpenSSL 3.2+ migration, native kernel re-key instrumentation must replace that
arming assertion rather than letting a userspace connection pass as offloaded.

Paper wording, **conditional on mainline's live checks**: “TLS 1.2/1.3 with kernel
TLS TX offload on kernels supporting TX re-keying; RX offload for TLS 1.2, with
TLS 1.3 RX and KeyUpdate handled by OpenSSL.” Do not claim TomoKV TLS 1.3 RX offload
with re-key handling, or verified kernel KeyUpdate survival from these mocked
kernel-boundary unit results alone.

Built artifact SHA-256:

```text
8775cd2edcd4c6eb8fca562862bcd4366859514d750c962268154c60cdb508a3  build/ktlsfix/pre/tomokv
94ad33e0a015ece9754456bc76af034ce9d243b93b03ef308f6b656f3c545110  build/tomokv
fe135c6e7b8442ea18d73c25825752a78de379f5183c57af6952f3df462fbf43  build/ktls-keyupdate
074fccc2bbb17eec59c24f21e2eeefefcddf406784083965639abfdaad622846  build/ktls-keyupdate-unit
```

`git diff e279aeb4cf08ae2c39f26be679388b872fed4667 --stat` (including this report):

```text
 MEASURE-REQUEST-ktlsfix.md   | 244 +++++++++++++++++++++++++++++++++++
 Makefile                     |  10 ++
 docs/CONFIGURATION.md        |  31 ++++-
 src/cmd/t_server.cc          |   3 +
 src/net/tls.cc               | 142 ++++++++++++++-------
 src/net/tls.h                |  15 ++-
 tests/gate.sh                |  39 ++++--
 tests/ktls_keyupdate.cc      |  90 ++++++++++---
 tests/ktls_keyupdate_unit.cc | 294 +++++++++++++++++++++++++++++++++++++++++++
 tests/tls.py                 |  28 +++--
 10 files changed, 806 insertions(+), 90 deletions(-)
```
