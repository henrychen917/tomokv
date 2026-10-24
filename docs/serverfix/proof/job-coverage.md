# Reply/configuration reference coverage

The retained `reply-texts-references.txt` and `config-behavior-references.txt`
contain the searches and line matches. The table maps behavior-bearing matches
to existing gate jobs; every listed job uses the gate's own whole-job interface.
The final run manifest and ledger provide their results and complete leg lists.

| Tests / behavior | Gate jobs |
|---|---|
| Physical file input, scalar types, generic CONFIG matrix | `serverfix_lines`, `serverfix_scalar`, `serverfix_config`, `config_unit`, `boot_grammar`, `netfix_config` |
| HELLO / RESP2 / RESP3 / limits | `serverfix_hello`, `respcompat`, `feature-split-0/1`, `feature-armed-0/1`, `netio-1s/2s`, all 12 `respresume-{fragment,cpu,neighbour}-{1s,2s}-{epoll,uring}` jobs |
| WAITAOF, CLIENT UNBLOCK, `s6.py`, `climon2.py`, server-tail commands | `serverfix_waitaof`, four feature jobs, both differential geometries and engines; `atomic_units` also covers the admin-command fixtures |
| HLL and PFSELFTEST | `serverfix_hll`, feature `servertail` battery, differential `hll` and `servertail` generators |
| Slowlog / identity / disabled state / credentials | `serverfix_slowlog`, `bugs5` (all eight declared legs, including its fresh legacy controls), `debug-0/1`, `authfix`, `auth` |
| ACL log / ACL policy / disabled state | `serverfix_acllog` (also runs the established ACL battery on four fresh candidate legs), `release_batteries`, `acl_metadata`, `acl_recheck`, `aclfix`, feature `aclsel`, differential `aclsel` / `aclkeys` / `compatintro` |
| Exact CONFIG unit diagnostics and NUL grammar | `netcmd_units`; the PRE unit job runs in an archived PRE production-source tree with the corrected current assertion, not a POST unit alongside a PRE server |
| `knobs.py`, AOF config / rewrite trigger inputs | `aof-epoll`, `aof-uring` |
| `iofix_hz.py` | `iofix-hz` |
| `evict_battery.py`, `read_local_lfu.py` | all eight `evict-{lruclock,lfu}-{split,armed}-{0,1}` jobs, plus `bugs5` |
| `notify.py`, `netcap.py`, `netcap_unit.cc` | `notify`, `netcap`, `netcmd_units`, differential `notify` |
| `bitfield`, `blocking`, `limits`, `stream`, `streamgroups`, `arity`, `edgeenc`, `infofix`, `climon2` | all four feature jobs and the corresponding differential generators |
| `txniso`, `xscript`, `atomic_plain` | `debug-0/1`, four `txnorder-{fused,split}-{0,1}` jobs |
| `compat3_lib`, `compat3_functions` | `compat3`; `compat2` retains the earlier full compatibility matrix |
| Core completion, WAIT lifecycle, reorder integration | `core_units`, `wait_units`, `reorder_sync`, `reorder_engagement`, `reorder_identity` |

`tests/debug.py` is invoked by `auth`, not the similarly named `debug-*`
jobs. Both were retained. The existing `differ_test.py` mock's uppercase
parameter spelling is for duplicate detection, which Redis also preserves;
that assertion was not changed.

Search matches without an applicable gate job:

- `redisgap.py`: **NOT RUN** as a standalone driver. It has no gate job and
  hard-codes CPUs 68–79 and ports 8120–8139, outside this lane's allocation.
  The current directed/oracle and CONFIG unit rows cover the affected parser
  behavior. Its legacy native-alias last-wins assertion is not an oracle claim.
- `replyschema.py`: **NOT RUN** as a standalone driver; no existing gate job
  references it. Its WAITAOF zero-replica case is asserted by the new lifecycle
  row and both existing differential geometries.
- `abba_workloads.py`, `lru_slow.sh`: **NOT RUN**; performance/load-generator
  work remains with the maintainer.
- ACL key-position and wake-unit matches concern command key metadata or the
  unchanged UNBLOCK error spelling. They introduce no changed assertion or
  standalone gate job in this lane. The live ACL wake jobs and differential
  ACL generators are included above.
- `atomic_torn.py`'s literal `CONFIG SET failed` is a local failure label for a
  valid `atomic` toggle, not a Redis reply assertion. Its rate-bearing
  `atomic_batteries`/ASAN variants are outside this selected correctness proof;
  no parser acceptance for that valid toggle changed.
