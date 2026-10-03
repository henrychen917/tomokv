# rlfence2 — h05 layout attribution

PAD-A and ALT are ready for mainline. **ALT restores PRE's literal instruction
bytes, function addresses, sizes, and loop-head alignments for the h05 fused
`run_loop`, `flush_ready`, and GET parser.** PAD-A retains the measured POST's
exact layout while restoring the old fence behavior. Both PADs have independent
planned-patch verification and negative controls. Performance remains pending.

Worktree/branch: `/home/user/Projects/cx-rlfence`, `cx-rlfence`.
Read `MEASURE-REQUEST-rlfence.md` first. Fetched and merged `origin/cpp`
(`b47544aad`) in **20af0bbd0**, before implementation. Implementation/proof
commits: **15cd7faa4**, **47bf4838d**, **4b9da2708**.
All builds used `taskset -c 112-127 make -j16`; serverless execution was also
pinned there. No server, load generator, benchmark, gate, or push was run.

## Frozen comparison and ready arms

`build/tomokv` remains the actual measured POST, from `7dc81148e`, with the
original one-statement fix. The upstream merge includes an unrelated hash-TTL
fix; rebuilding POST from the merged tree would change the experiment. ALT is
therefore an overlay of that same frozen source, with the patch in
`docs/rlfence2/alt.patch`. The working production header retains the original fix.

The headline is `/home/user/Projects/bench-bins/tomokv-headline-e279aeb4c`.
The lane's original `build/tomokv-rlfence-pre` has a different whole-file SHA,
but **all executable/allocated bytes, symbol addresses, relocation targets,
and program headers match the headline**, excluding the debug-dependent build
ID. Only DWARF sections and the build ID differ. The complete comparison is
`docs/rlfence2/headline-pre-identity.json`; this is stronger than matching a
commit name or total text size.

| Arm | Binary relative to this worktree | `.text` bytes | Other new executable bytes | Measured rate/tails |
|---|---|---:|---:|---|
| PRE/headline | absolute headline path above | 7,554,449 | 0 | Reference, mainline |
| POST | `build/tomokv` | 7,554,209 | 0 | Four historical h05 readings below; new comparison pending |
| PAD-A, **A: behaviour twin** | `build/rlfence-pad/tomokv` | 7,554,209 | 0 | Pending mainline |
| ALT | `build/rlfence-alt/tomokv` | 7,554,609 | `.rlfence`: 112 | Pending mainline |
| ALT-PAD-A, **A: behaviour twin** | `build/rlfence-alt-pad/tomokv` | 7,554,609 | `.rlfence`: 112 | Available control |

```text
9d1aabd59c9b760695e8119871f7d0de21b2f661529dcc469fa7df867627e08d  PRE/headline
933e6857b8529adc195f7b8fe4e09223f2b3855881726ae7e175e943998ae155  POST
e0550c1361734c18cfa5f43cacbb495eaf4548a0e5f0d58777aa5e79b3d9146c  PAD-A
11b43279251f578b7a2c78d0e05c61765823260f3f19123484508dc9a569c018  ALT
2f26b81bc13c3285fb1c61958a3acbd320fa30e85c5d920a2629d68920aeb540  ALT-PAD-A
```

`docs/rlfence2/SHA256SUMS` verifies the actual paths. Neither PAD is an inverse
control. POST is −240 `.text` bytes versus PRE; ALT is +160 `.text` bytes and
+112 island bytes versus PRE. No PAD-B is supplied.

## PAD proof

The fixed statement emits a load, register bit test, conditional branch, and
covered-fence store in four physical completion helpers: two database variants
times the two drain policies. Each helper has two alias names.

POST contains this sequence in each helper:

```asm
mov  0x68(%rdx),%rax
bt   %rax,%rcx
jae  continuation
movq $-1,0x68(%rdx)
continuation:
```

PAD-A changes `73 08` to `eb 08`: an unconditional jump to the **same**
continuation. This removes only the new fence store's effect. Pending-bit/filter
retirement, per-op completion, owner publication, and reply retirement retain
their original behavior. The planned branch addresses are:

| Variant | POST/PAD-A branch | ALT/ALT-PAD-A branch |
|---|---:|---:|
| `tomo_db0`, policy false | `0x3029c1` | `0x751c89` |
| `tomo_db0`, policy true | `0x306c31` | `0x751ca5` |
| `tomo`, policy false | `0x689241` | `0x751cc1` |
| `tomo`, policy true | `0x68d471` | `0x751cdd` |

For **each** candidate/PAD pair:

- The complete **10,028-entry function address/size table** and every section
  descriptor are equal. Full symbol tables and file length are equal too.
- Exactly **four bytes** differ. Restoring the four planned opcodes reproduces
  the entire candidate file, including code, data, relocations, headers, and debug
  information. No broad displacement masking is used for this proof.
- The verifier independently reconstructs the plan from the candidate's decoded
  instructions. It rejects an omitted retarget, a symbol value moved by one
  byte, and an unrelated one-byte `.text` edit at their designated assertions.
- Source/call closure accounts for **both completion call sites in all four
  instantiations: eight direct calls to the patched helpers**. This also checks
  that an extra inlined copy of a source completion site is not being overlooked.

Committed receipts and compressed complete tables are under
`docs/rlfence2/{pad-a,alt-pad}/`: `planned-retargets.json`, `proof.json`,
`negative-controls.json`, `closure-proof.json`, and `POST-*.tsv.gz`.
Uncompressed candidate and PAD tables, disassembly-bearing plans, and corrupt
nonexecutable `*.NEVER-RUN` controls remain beside each binary under `build/`.
ALT's verifier additionally covers every byte of `.rlfence` and pairs each entry
jump with its return continuation.

## What moved in the measured POST

The headline h05 boot has `databases=1` by default and therefore selects
`tomo_db0`. It uses TCP/uring without TLS or Unix sockets. The fused
`run_loop<false,false,false,true,0,false>` entry is shared across overlap modes;
its template `Pipeline=0` does not mean the benchmark used overlap 0.

ELF virtual addresses below are relative to the executable's load base.
Sizes are bytes. The full objdump comparison and backward-branch inventories
are `build/rlfence2-audit/`; committed copies are `docs/rlfence2/io-audit.json.gz`,
`io-changes.json`, and `io-diffs/`.

| Function | PRE address / size | POST address / size | Change |
|---|---|---|---|
| db0 ordinary fused `run_loop` | `0x3241d0` / 5,011 | `0x324200` / 5,011 | +48 address; same instruction shape |
| db0 fused `flush_ready<false,false,true,false,true,false>` | `0x3235d0` / 3,062 | `0x323600` / 3,062 | +48 address; same instruction shape |
| db0 `parse_and_dispatch<false,32,false,false>` | `0x312be0` / 19,296 | `0x312c10` / 19,296 | +48 address; same instruction shape |
| namespaced ordinary fused `run_loop` | `0x6aa6f0` / 5,045 | `0x6afc20` / 5,045 | +21,808 address; reordered placement |
| namespaced matching `flush_ready` | `0x6a9ad0` / 3,094 | `0x6af000` / 3,094 | +21,808 address; reordered placement |
| namespaced matching GET parser | `0x6992c0` / 19,021 | `0x699210` / 18,951 | −176 address; −70 size; quota check outlined |
| Each of four completion helpers | 294 | 310 | +16 each; new fence sequence plus changed padding |

The principal source-identified steady loop heads move as follows. These are
static loop heads, not a new sample-based ranking of instruction hotness.

| h05 loop head | PRE | POST | Offset mod 64, PRE → POST | ALT |
|---|---:|---:|---:|---:|
| `run_loop +0x90`, stop/role check (`io_loop.h:529`) | `0x324260` | `0x324290` | 32 → 16 | `0x324260` |
| `flush_ready +0x70`, active-client walk | `0x323640` | `0x323670` | 0 → 48 | `0x323640` |
| parser `+0x1b0`, next-frame loop (`io_loop.h:2985`) | `0x312d90` | `0x312dc0` | 16 → 0 | `0x312d90` |

All three retain 16-byte alignment. Their cache-line placement changes; that
does not by itself predict which placement is faster.

The broader comparison passes **325/334** normalized IO/GET bodies. Normalization
resolves external addresses but retains instructions, registers, member offsets,
internal branch offsets, and padding. The nine exceptions are fully retained:

- Namespaced ordinary/TLS fused parsers lose 70/39 bytes and each gains an
  out-of-line `read_local_lane_quota` call.
- Two db0 TLS parser clones change from 10,118→10,144 and 10,208→10,150 bytes;
  `flip_fingerprint_note` versus `flip_fingerprint_note_sampled` call edges
  expose the changed wrapper inlining decisions.
- Namespaced Unix uring loop variants grow 16/8 bytes, replacing two/one
  `read_local_epoch` calls with inline code.
- One namespaced R7 flush grows 3,100→3,155 bytes: deque `push_back` becomes an
  inline fast path plus `_M_push_back_aux`. One db0 R7 flush shrinks
  3,362→3,123 bytes: buffer reset becomes `reset_rbuf_at_quiescence`, replacing
  inline realloc/free/memmove code.
- A db0 split-local Unix/epoll loop shrinks 5,655→5,647 bytes and gains an
  out-of-line `read_local_epoch` call.

Thus unchanged source in the IO loop does **not** imply unchanged machine code.
For h05 specifically, the fence statement is unreachable with read-local 0;
the observed code-placement change is a plausible attribution to test, not a
measured causal conclusion or a claim about a particular cache/predictor event.

## ALT spelling and its scope

`docs/rlfence2/alt.patch` changes only `rob.h` and its compiler/link placement
settings in the overlay Makefile. For the native BMI/64-slot build, one inline
assembler operation replaces the existing five-byte pending-mask ANDN with a
five-byte jump. A 28-byte island performs the covered-fence test/store, the same
ANDN, and a jump back. Four islands occupy 112 bytes in `.rlfence` and inherit
their COMDAT groups. They touch no stack and declare the modified memory,
temporary register, and flags. Other capacities/architectures retain the C++ fix.

The entry assertion, final pending mask, clear-on-empty filter, and covered versus
uncovered fence results are unchanged. The fence store precedes pending cleanup
inside this owner-local call; both finish before any Done publication or parser
resumption. There is no callback or intervening observer inside the call. No
retry, lock, object field, runtime knob, or allocation is introduced.

The db0 fused TU uses `large-unit-insns=128873` instead of 128880 and 16 bytes
of unexecuted input-section padding. Those compile-time settings compensate
for the preceding TLS clone's change. They are verified placement controls,
not values chosen from a throughput run. All four completion helpers retain
their PRE size, 294 bytes.

`docs/rlfence2/alt-h05-proof.json` requires **literal byte equality at the same
addresses** for all three h05 IO functions above. The clean GET handler also
matches literally; the other three GET handler variants retain their addresses
and normalized instructions. The source recipe was reconstructed independently
and compared with the actual build inputs (`alt-source-receipt.json`).

**This neutrality claim is scoped to those h05 functions.** ALT is not a whole
binary layout twin of PRE. Its broader comparison is **329/334**; the remaining
TLS/epoll/R7 changes are recorded in `alt-io-changes.json` and
`alt-io-audit.json.gz`. The extra island jumps may also cost read-local-on cells.
ALT remains a measurement candidate until mainline measures it.

## Serverless validation and reproduction

Current POST and ALT both pass the existing fence witness: all three completion
sites, 128 slot positions, partial/mixed/empty masks, p8/p32 with no retirement,
immediate rearming, and retained same-key RYOW. Both pass the existing write-ring
suite, including four 200k-frame soaks. Production ALT builds compile both
database variants and all existing footprint locks.

The actual ALT witness ELF was converted into its own exact-layout PAD-A (five
emitted islands). It fails symmetry at `all three completion sites clear the
covered MGET fence before retirement`, and independently fails pipeline with
`N=8 lane_completions=1 retired=0`. This executes the generated alternative
mechanism and its removed-store control without a server.

The Python live harness's serverless positive replay passes p8/p32 with zero
skips. Its old, never-armed, and stale-reply traces fail at their designated
assertions; never-armed exhausts three fresh arms. Logs and receipts are committed
under `docs/rlfence2/`. These are serverless results, not live boot/gate evidence.

Recheck frozen artifacts without executing a server:

```bash
cd /home/user/Projects/cx-rlfence
taskset -c 112-127 sha256sum -c docs/rlfence2/SHA256SUMS
taskset -c 112-127 python3 tools/rlfence_artifacts.py verify \
  build/tomokv build/rlfence-pad/tomokv docs/rlfence2/pad-a/planned-retargets.json
taskset -c 112-127 python3 tools/rlfence_artifacts.py verify \
  build/rlfence-alt/tomokv build/rlfence-alt-pad/tomokv \
  docs/rlfence2/alt-pad/planned-retargets.json
taskset -c 112-127 python3 tools/rlfence_artifacts.py h05-proof \
  /home/user/Projects/bench-bins/tomokv-headline-e279aeb4c \
  build/rlfence-alt/tomokv build/rlfence-alt/audit-final/audit.json \
  build/rlfence-alt/h05-proof.json
```

The `pad SOURCE OUTPUT` subcommand regenerates the PAD, plans, tables and all
three corrupt controls. `closure SOURCE RECEIPT` rechecks the eight call edges.
For a fresh source build, choose unused paths; the preparation command refuses
to overwrite an existing overlay:

```bash
taskset -c 112-127 python3 tools/rlfence_artifacts.py prepare-alt build/rlfence-alt-fresh-src
taskset -c 112-127 make -j16 -C build/rlfence-alt-fresh-src \
  BUILD_ROOT="$PWD/build/rlfence-alt-fresh" all build/rlfence-unit build/read-local-write-ring-unit
taskset -c 112-127 build/rlfence-alt-fresh-src/build/rlfence-unit
taskset -c 112-127 build/rlfence-alt-fresh-src/build/read-local-write-ring-unit
```

A different build path can change DWARF/build ID and whole-file SHA; re-run the
address/instruction proof against that binary. The supplied frozen SHA values
identify the measurement arms above.

## Exact mainline measurement request — NOT RUN

Measure **POST, PAD-A, ALT against the frozen headline on the same 14 generic
cells**, using mainline's gate instrument on the scheduled quiet box. The cell
file is copied byte-for-byte from the historical result's embedded source:
`docs/rlfence2/generic-merit-cells.txt`, SHA-256
`de0e56e4696f780543c5adea21aa7d7283c12fa22110be6064370a69a2a68dc6`.

Preserve the historical performance geometry: server cores **0–31**, load cores
**32–111**, no SMT, 20-second windows, 2M keys, 512 total connections, uring,
atomic 1, overlap 1, reorder 0, default balancers, save disabled. All 14 cells
are fused. h05 is GET/64 B/p32/read-local 0/**8 instances**; its runner boot uses
**256 shards**. This is the recorded performance geometry, distinct from the
8-core/16-shard/6:2 correctness gate geometry. Keep the existing depth-1 exemption
and cell pins; do not re-pin or change offered load during this attribution run.

Run from mainline so its current instrument and standing controls are used:

```bash
(
  set -u
  rlfence_lane=/home/user/Projects/cx-rlfence
  cd /home/user/Projects/tomokv-cpp || exit 1
  (cd "$rlfence_lane" && sha256sum -c docs/rlfence2/SHA256SUMS) || exit 1
  rlfence_cells=h05,h06,p8g,p8s,d1g_l0,d1s_l0,d32s_l1,d8s_l1,d32g_l1,x9_32_l1,x9_32_l0,m8g_l0,v1g_l0,d128g_l0
  rlfence_status=0
  for rlfence_arm in POST PAD-A ALT; do
    case "$rlfence_arm" in
      POST)  rlfence_binary="$rlfence_lane/build/tomokv" ;;
      PAD-A) rlfence_binary="$rlfence_lane/build/rlfence-pad/tomokv" ;;
      ALT)   rlfence_binary="$rlfence_lane/build/rlfence-alt/tomokv" ;;
    esac
    rlfence_rc=0
    python3 tests/abbagate.py --subset full --build-reference 0 \
      --cells "$rlfence_lane/docs/rlfence2/generic-merit-cells.txt" \
      --only "$rlfence_cells" \
      --reference-binary /home/user/Projects/bench-bins/tomokv-headline-e279aeb4c \
      --candidate-binary "$rlfence_binary" \
      --server-cores 0-31 --server-smt '' --load-cores 32-111 --load-smt '' \
      --ports 7933-7940 --port 7933 \
      --output "$rlfence_lane/build/rlfence2-measure-$rlfence_arm" \
      > "$rlfence_lane/build/rlfence2-measure-$rlfence_arm.log" 2>&1 || rlfence_rc=$?
    printf '%s exit=%s\n' "$rlfence_arm" "$rlfence_rc"
    if [ "$rlfence_rc" -ne 0 ]; then rlfence_status=$rlfence_rc; fi
  done
  exit "$rlfence_status"
)
```

Retain each ABBA arm's rate, tails, spread, validity and trust status. Attach the
gate's PMU/profile evidence for cycles/op, instructions/op and IPC where collected;
instruction count or text size alone is not the verdict. ALT-PAD-A is ready at the
path above if mainline needs the corresponding ALT layout/mechanism control.

The maintainer's historical h05 deltas were −2.79%, −2.32%, +2.05%, −2.85%
(median −2.55%, mean −1.48%). They are not four valid gate passes: the retained
logs include UNTRUSTED status and a candidate spread beyond 2%. Keep those flags
when reporting the historical readings; this lane did not produce new rates.

Decision: at the same offered load, **POST and PAD-A moving together while ALT
returns to the reference band supports the layout attribution**. POST/PAD-A
disagreement on h05 cannot be credited to the fence mechanism, which that cell
cannot execute. If the effect does not reproduce, report that outcome. All 14
generic cells must remain within mainline's valid comparison band; do not average
away a regressing read-local-on cell. Record results in
`MEASURE-RESULT-rlfence2.md`, including invalid blocks and the arm SHAs.

Gate delta for this lane: **+0 quick / +0 full**. No gate rows, witness semantics,
or expected-count constants were edited by rlfence2. The mandated merge carries
upstream's existing gate edits. Live correctness, measurement, gate and merge
remain mainline-owned. This lane stops after the committed request.
