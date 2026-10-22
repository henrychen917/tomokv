# txnorder2 instruction audit

PRE is merged `origin/cpp` **a7dfb9d23**, SHA-256
`97ea4e0638863ac87b289290bd489d8ef93e5fc4808ad49bc71dfbd05a9c739e`.
POST production source is **9d6e99d0d**, SHA-256
`5bfa95e74b42c78c0b70fa0e3983c89582b66dc8d4a1570262968ec84e5f447f`.
The final object inputs remained unchanged during all 160 path fixtures.

These are **serverless instruction audits, not performance measurements**.
Each fixture checks exact data/replies and a bounded number of owner turns.
`paths-final2c/*/runs.json` counts instructions in named production routines;
calls outside that set are excluded. NOPs are counted. The skipped scan-home
helpers must pass exact canonical body identity before the scan audit runs.
`instruction-summary.json` contains every PRE/POST pair and function delta.

## One EXEC containing two INCRs

`drivers/probe-exec.cc` queues MULTI and both INCRs before the start marker.
The counted region includes EXEC preparation, the scheduled owner turns,
decision and retirement. It excludes networking, prior command queueing and
later record reclamation. One shape has two keys on one shard; the other has
one key on each of two owners. Atomic mode is 1, with no competing operation.

The second audit follows **all calls, including indirect calls and libraries**.
It counts debugger instruction steps in that region, including fixture glue.
Single-stepping the Linux vDSO clock retry loop interferes with its vvar
sequence validation: the first attempt exhausted 500,000 steps. That failed
attempt is retained by digest. The completed audit runs each vDSO call to
return and records it separately: **PRE 0, POST 1 call per EXEC**. Thus the
following figures exclude that clock body and kernel work; they are not
claimed as complete hardware retired-instruction counts. REP single-step
iterations are also disclosed (16 in fused, 32 in split, equal in both arms).

| Namespace | Mode | Shape | PRE steps/EXEC | POST steps/EXEC | Delta |
|---|---|---|---:|---:|---:|
| normal | 1s | single shard | 21,945 | 26,705 | +4,760 |
| normal | 1s | two owners | 22,640 | 27,972 | +5,332 |
| normal | 2s | single shard | 25,908 | 30,653 | +4,745 |
| normal | 2s | two owners | 26,657 | 31,959 | +5,302 |
| DB0 | 1s | single shard | 20,086 | 24,809 | +4,723 |
| DB0 | 1s | two owners | 20,711 | 25,986 | +5,275 |
| DB0 | 2s | single shard | 24,012 | 28,724 | +4,712 |
| DB0 | 2s | two owners | 24,695 | 29,948 | +5,253 |

All sixteen executions completed with the exact two-element reply. Commands,
fixture SHA-256s, excluded clock counts and REP counts are in
`exec-instructions-final2c/results.json`; the driver is
`drivers/exec-instructions.py`. Large per-PC traces/logs are hashed in the
cleanup inventory rather than committed.

### Costs removed and costs retained

* `822d7f310`/`b117daa4d`: remove the eager command clock from a connection
  holding a MultiSession. A successful EXEC takes its age once at admission;
  retries preserve that age. Retry clocks are on the retry path.
* `48029f52d`/`cc7813c32`: avoid a separate ARRIVE turn for a single-shard write unit;
  retain the all-owner barrier for a cross-owner write unit. Reduce duplicate
  command/key work and avoid a duplicate-index allocation for a one-key child.
* `bbcbb6252`, reviewed in `8a5d1244a`: remove the duplicate single-key
  preflight. `prepare_write_key` still checks the claim, version and snapshot
  before the sole install. Multi-key children still preflight every key before
  the first install. In the named-routine audit this reduces normal 2s single
  shard EXEC from **11,859 to 10,698** instructions and two-owner EXEC from
  **12,731 to 11,629**. DB0 moves **11,365 to 10,218** and **12,133 to 11,045**.
  Receipts: `paths-final/exec/runs.json` and `paths-final2c/exec/runs.json`.
* `e16c7d9bc`: blind atomic MSET never enters group-attempt allocation or its
  barrier witness; the witness is restricted to MSETNX.

The remaining EXEC mechanism includes the admission age and sequence,
per-shard claim storage and placement, the PLACING/EXECUTING decision,
cross-owner ARRIVE, version-order touch checks and read intents, immutable
private write records, and decision/lifetime joins. Removing those mechanisms
would remove the approved ordering or lifetime guarantee. This does **not**
claim that every remaining compiler instruction is irreducible: main-command
spillover and cold-state allocation remain explicit merit inputs.

## Ordinary command paths

With a MultiSession present but no unit in flight, the session-entry audit is
equal in both namespaces and both modes: **GET/SET 202 → 202**, **MGET/MSET
214 → 214**. It observes no eager age clock. This is the session dispatch
region, not the entire network operation.

The following totals use the named-routine fixture boundary, two fragments,
and 2s. The complete JSON also includes 1s, existing/missing keys, preparation,
stream routing and both namespaces.

| Cell | PRE | POST | Delta |
|---|---:|---:|---:|
| normal MGET, missing | 3,027 | 2,997 | −30 |
| DB0 MGET, missing | 3,087 | 3,023 | −64 |
| normal plain MSET | 2,831 | 2,806 | −25 |
| DB0 plain MSET | 2,898 | 2,843 | −55 |
| normal DEL / UNLINK | 2,793 | 2,768 | −25 |
| DB0 DEL / UNLINK | 2,850 | 2,793 | −57 |
| normal atomic MSET | 3,949 | 3,960 | **+11** |
| DB0 atomic MSET | 4,051 | 4,019 | −32 |
| normal KEYS / RANDOMKEY | 81,109 / 81,069 | 81,102 / 81,062 | −7 / −7 |
| DB0 KEYS / RANDOMKEY | 86,164 / 86,120 | 86,161 / 86,117 | −3 / −3 |

`9d6e99d0d` keeps DB0's cold atomic-owner argument on the stack. The store is
included in the count. This removes the extra MGET instruction per fragment
without a runtime knob. DB0's `xshard_execute` MGET body is **322 → 322** over
two fragments; DEL/UNLINK are **462 → 462**. Normal DEL/UNLINK are **452 → 450**.
Cold-call and ±64 budget trials did not remove the MGET spill; the retained
stack form did. See `mget-trials/results.json` and final path receipts.

The KEYS/RANDOMKEY scan-home helper bodies are canonical-identical in both
namespaces (`paths-final2c/identical-skipped-scan-helpers.json`). The caller
split therefore does not hide changed scan work. The normal execute caller
drops four instructions over two fragments; the DB0 caller is equal.

Residuals are not called unavoidable: DB0 plain MSET's execute body is
**502 → 504**, offset by a larger preparation reduction. Normal atomic MSET
has **+11** named instructions in 2s and **+16** in 1s; the split breakdown is
flush **190 → 206**, completion **126 → 134**, retirement **57 → 59**, execute
**790 → 788**, prepare **1,239 → 1,235**, debug-defer helper **29 → 20**. The
group-aware commit/finalization dispatch accounts for the positive terms.
Per-unit budget trials did not restore every unedited body. Keep these cells
in the maintainer's main-command merit run; no rate or cycles benefit is
inferred from these instruction figures.
