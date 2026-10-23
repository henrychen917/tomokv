# txnorder2b saved-work review

Resumed at bbcbb6252. No later wrapper WIP commit or tracked working edit was
present. The merged comparison base is a7dfb9d23, introduced by 73e35f754;
the already completed merge is retained, including the private EXEC mover
overlay and the headline moverfix rows. No merge or old proof is claimed anew.

All fourteen paths saved by 397403586 were reviewed:

| Path | Decision and reason |
|---|---|
| `tests/gate.sh` | Keep. The busy-owner witness has its own selectable job, dependency and collection entry. Splitting the job adds no additional row. Protected EXPECT assignments are unchanged. |
| `tests/execatomic.py` | Keep. Rearming uses fresh keys and connections, at most four attempts; data failure never rearms, and the final missing-cut attempt fails. No data assertion or tolerance was relaxed. |
| `tests/_differ_ccfix.py` | Keep. TO-B COPY/STORE waits behind a held blind writer at ARRIVE. A separate MGET supplies the exact predecessor/missing-notification witness while held; the dependent command must stay blocked, then its exact reply and destination are compared with the oracle after release. |
| `drivers/pad.py` | Keep. The type-A arm uses PRE behaviour with the candidate-sized unused Server tail. The receipt explicitly limits its text claim to aggregate size, not function placement. |
| `drivers/runtime.py` | Keep and finish isolation. Run-specific data and receipt paths prevent the continuation overwriting older evidence. Also remap the plan's `owner-data` AOF directories, which the saved edit omitted. |
| `drivers/watch-oracle.py` | Keep. Ports 27892/27893 avoid the reproduction's 27890/27891 and stay inside this lane. |
| `episodes-R1.log` | Keep; explicit completion order UWV supplements PASS. |
| `episodes-R2.log` | Keep; explicit completion order UVW supplements PASS. |
| `episodes-R3.log` | Keep; explicit completion order WUV supplements PASS. |
| `episodes-R4.log` | Keep; explicit completion order WUV supplements PASS. |
| `episodes-R5.log` | Keep; explicit completion order UVW supplements PASS. |
| `episodes-R6.log` | Keep; explicit completion order UVW supplements PASS. |
| `episodes-R7.log` | Keep; explicit completion order UVF supplements PASS. |
| `episodes-R12.log` | Keep. The production-predicate state explorer supersedes the weaker fair-round permutation count; all seven shape state/transition counts are disclosed. |

Both paths saved by bbcbb6252 were reviewed:

* `src/cmd/multi.inc`: keep the single-key preflight removal. The only install
  still enters `prepare_write_key`, which checks the unit records, claims and
  snapshot before installation. Multi-key commands still preflight the complete
  set before their first install. This removes duplicate work, not a gate.
* `drivers/runtime.py`: keep run identifiers and the explicit Redis 7.4 binary.
  Removing the old `/redis74` to `/redis` substitution restores the requested
  oracle; the redis-cli executable is only a wire client.

Interrupted ledgers and RUNNING receipts are historical partial evidence, not
completed passes. The final report selects receipts explicitly by binary digest
and retains failed predecessors. Large raw artifacts are inventoried with
SHA-256 before removal; executable arms remain only in ignored `build/`.
