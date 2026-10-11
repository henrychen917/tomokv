The final build restores every one of the twelve selected hot drifts.
`ccfix_audit`: **1208/1208** selected hot bodies equal. `lbstall`: **601/601 +
603/603** equal. The full ccfix command still exits 1 because its narrow
non-hot-handler allowlist does not include the deliberately changed DEBUG
handler. It is retained unchanged. The only six changed handler bodies are
DEBUG and INFO (including INFO cold clones), in both namespaces.

The full inventory compares 16656 emitted bodies: 16077 equal and 579
changed. Every changed body has an attribution in
`full/changed-bodies-with-reasons.json`. An unresolved attribution remains
unresolved; selected-hot equality does not imply whole-binary identity or
performance acceptance. No rate, IPC, or cycles/op was measured.

| Object | Function | PRE bytes | Rejected Stage B | Final bytes |
|---|---|---:|---:|---:|
| `db0/src/cmd/xshard.o` | `tomo_db0::FlatStore::find_notify(unsigned long, tomo_db0::Slice, tomo_db0::FlatNotifySink*)` | 942 | 878 | 942 |
| `db0/src/cmd/xshard.o` | `tomo_db0::FlatStore::erase_notify(unsigned long, tomo_db0::Slice, tomo_db0::FlatNotifySink*, tomo_db0::FlatStore::EraseEvent)` | 933 | 869 | 933 |
| `db0/src/cmd/xshard.o` | `tomo_db0::FlatStore::erase_in_read_local(int, unsigned long, tomo_db0::Slice, bool*)` | 732 | 606 | 732 |
| `db0/src/cmd/xshard.o` | `tomo_db0::FlatStore::insert_into_read_local(int, unsigned long, tomo_db0::KvObj*, bool)` | 1602 | 1493 | 1602 |
| `db0/src/core/reorder.o` | `unsigned int tomo_db0::ExLoopT<true>::r7_fused_sweep_impl<32u, true, false, false>()` | 796 | 729 | 796 |
| `src/cmd/xshard.o` | `tomo::FlatStore::find_notify(unsigned long, tomo::Slice, tomo::FlatNotifySink*)` | 846 | 782 | 846 |
| `src/cmd/xshard.o` | `tomo::FlatStore::insert_into(int, unsigned long, tomo::KvObj*, bool)` | 1014 | 942 | 1014 |
| `src/cmd/xshard.o` | `tomo::FlatStore::erase_notify(unsigned long, tomo::Slice, tomo::FlatNotifySink*, tomo::FlatStore::EraseEvent)` | 812 | 737 | 812 |
| `src/cmd/xshard.o` | `tomo::FlatStore::erase_in(int, unsigned long, tomo::Slice, bool*)` | 783 | 580 | 783 |
| `src/cmd/xshard.o` | `tomo::FlatStore::find_in(int, unsigned long, tomo::Slice) const` | 630 | 540 | 630 |
| `src/core/rl2s.o` | `tomo::IoLoop::DispatchResult tomo::IoLoop::parse_and_dispatch<false, 32u, true>(tomo::Client*)` | 21058 | 21083 | 21058 |
| `src/core/rl2s.o` | `tomo::IoLoop::DispatchResult tomo::IoLoop::parse_and_dispatch<true, 0u, false>(tomo::Client*) [clone .isra.0]` | 12093 | 11931 | 12093 |

The three IO-template repairs retain their established compiler budgets and
restore one cleanup call by folding intent release into `atomic_free_unit_intent`.
The nine storage repairs use xshard large-unit-insns 138200 / 136800, with the
ordinary gather lambda and key-anchor cleanup kept at PRE's outlining boundary.
The final DB0 t_server budget is 31850: SCAN, RANDOMKEY, CONFIG, and all other
unrelated handlers match PRE. The rejected 31800 trial perturbed RANDOMKEY;
its separate inventory remains under `identity-placement-31800/`.

The ordinary scatter constructor, destructor and xshard_destroy are canonically
identical. The complete 386-function scatter/state-helper inventory and both disassemblies
are in `../scatter-all-certified/`. MGET traces are in `../scatter-certified/`; they
execute production objects directly without workers, listeners, or a timing
instrument. Trace counts include the named scatter functions; calls into other
families are stepped over. They are not whole-operation performance counts.
The complete ordinary-path *identical sequence* claim remains unproven: a
sampled count and branch placement argument cannot establish that universal claim.

The final group-preparation hint (`8d1be3901`) leaves the selected hot set unchanged. The 188 paired final traces (180 preparation shapes and eight MGET paths) enter no group helper and have no named-function instruction increase. The broader source and disassembly review is in `../scatter-cost.md`; these sampled counts do not establish universal sequence identity.
