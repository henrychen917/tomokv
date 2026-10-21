# ntfix4 compile-only budget derivation

References: a fresh normal build of `bce4eb0aa`, and the frozen ntfix3 objects/binary from `f361de8ed` (SHA-256 `2a102311d91b99bcff78af38742c1176bec5634ae9f1875af8cb74e645d9075b`). Eight headline recompiles reproduce every reference body. There are 56 merged-source trials across all eight receive/dispatch units. All compilation uses CPUs 80–95, at most sixteen compiler children, with the normal production command and only the recorded inlining-budget substitution plus an IPA dump. No trial runs a server.

Initial IPA-size growth is +127 in main, +142 in genthread, and +172 in rl2s/reorder. Round 1 tries the headline budget plus that growth and adjacent candidates; rounds 2 and 3 narrow the four units that benefit from a budget change. Main and db0 rl2s reproduce the same bodies at the headline and headroom-preserving values. Src rl2s gets four additional residual hot differences at either alternative, so its headline budget stays.

Selection minimizes hot differences from both references (ntfix3 is eligible only for bodies that lane changed), then other residual bodies, then total changes. Interior plateau values are preferred when available. Every difference is retained, including the dispatcher compositions. The original `max-inline-insns-auto=14` for db0 reorder and `=18` for db0 main remain.

| Object | Headline budget | Selected | Residual hot before → after | Other residual before → after |
|---|---:|---:|---:|---:|
| `src/main.o` | 147428 | 147428 | 0 → 0 | 0 → 0 |
| `db0/src/main.o` | 147449 | 147449 | 0 → 0 | 0 → 0 |
| `src/core/genthread.o` | 129975 | 130084 | 2 → 2 | 5 → 3 |
| `db0/src/core/genthread.o` | 130179 | 130316 | 2 → 2 | 5 → 1 |
| `src/core/rl2s.o` | 162716 | 162716 | 4 → 4 | 0 → 0 |
| `db0/src/core/rl2s.o` | 162334 | 162334 | 4 → 4 | 0 → 0 |
| `src/core/reorder.o` | 147778 | 147950 | 4 → 4 | 5 → 1 |
| `db0/src/core/reorder.o` | 148779 | 148944 | 7 → 4 | 5 → 0 |

The 20 residual hot bodies are ordinary/R7 dispatchers containing both ntfix and wave3 changes; they do not equal either original build. The three extra unedited db0 reorder hot differences in the initial merged build are restored by the selected budget. Remaining non-hot compiler differences in these eight units are `pubsub_start_publish`, `snapshot_control_pass`, `atomic_prepare_capacity_read_local`, db0 `FlatStore::hash_key`, and a `std::__introsort_loop` clone. The complete final-build inventory adds every emitted object copy, clone, and cold receive/writeback helper, with reasons. Identity is a proxy; none of these results establishes performance merit.

`trials/*/*.json` retain exact compiler commands, source/object hashes, IPA sizes, every changed body, and both reference matches. `selected.json` identifies the chosen objects; the final normal build is compared separately.
