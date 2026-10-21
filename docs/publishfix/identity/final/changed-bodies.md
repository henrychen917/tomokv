# Every changed object body against PRE

Compiler: the same default release toolchain/flags as PRE, with only the two documented xshard budgets re-derived. All 1,211 command handlers and 1,218 selected hot bodies compare equal. Of 16,641 emitted object bodies, 16,631 compare equal. These tools normalize relocations and resolved targets; linked addresses necessarily move.

| Object | Body | Bytes PRE → POST | Reason |
| --- | --- | --- | --- |
| `db0/src/cmd/xshard.o` | `tomo_db0::xshard_flush_commits(tomo_db0::Server&, tomo_db0::ThreadCtx&, tomo_db0::Ring&, void*, void (*)(void*, tomo_db0::Client*))` | 1494 → 1530 | Inlines the repaired publisher for the detached commit batch, before AOF completion and reply publication. |
| `db0/src/cmd/xshard.o` | `tomo_db0::xshard_flush_commits(tomo_db0::Server&, tomo_db0::ThreadCtx&, tomo_db0::Ring&, void*, void (*)(void*, tomo_db0::Client*)) [clone .cold]` | 15 → 15 | Exception/cleanup target offsets follow the changed xshard_flush_commits body; size stays 15 bytes. |
| `db0/src/cmd/xshard.o` | `tomo_db0::Server::atomic_commit_publish()` | 57 → 86 | The requested last-decrementer sequence recheck and zero-count catch-up loop. |
| `db0/src/main.o` | `tomo_db0::Server::init(tomo_db0::Config const&, tomo_db0::AofReplayPlan const*)::{lambda(void*)#1}::_FUN(void*)` | 106 → 121 | The shard clear callback calls atomic_commit(), inlining the repaired publisher (server.h:340). |
| `src/cmd/xshard.o` | `tomo::(anonymous namespace)::normalize_multi_blocking_pop(tomo::MultiCommand&)` | 3308 → 3454 | Unedited helper: GCC inlining/partition spillover from the enlarged shared publisher; retained after 16 compile-only budget trials for merit review. |
| `src/cmd/xshard.o` | `tomo::(anonymous namespace)::normalize_multi_blocking_pop(tomo::MultiCommand&) [clone .cold]` | 45 → 45 | Cold exception/cleanup companion of the unedited normalize_multi_blocking_pop body; follows its changed inlining/partition layout. |
| `src/cmd/xshard.o` | `tomo::xshard_flush_commits(tomo::Server&, tomo::ThreadCtx&, tomo::Ring&, void*, void (*)(void*, tomo::Client*))` | 1494 → 1530 | Inlines the repaired publisher for the detached commit batch, before AOF completion and reply publication. |
| `src/cmd/xshard.o` | `tomo::xshard_flush_commits(tomo::Server&, tomo::ThreadCtx&, tomo::Ring&, void*, void (*)(void*, tomo::Client*)) [clone .cold]` | 15 → 15 | Exception/cleanup target offsets follow the changed xshard_flush_commits body; size stays 15 bytes. |
| `src/cmd/xshard.o` | `tomo::Server::atomic_commit_publish()` | 57 → 86 | The requested last-decrementer sequence recheck and zero-count catch-up loop. |
| `src/main.o` | `tomo::Server::init(tomo::Config const&, tomo::AofReplayPlan const*)::{lambda(void*)#1}::_FUN(void*)` | 106 → 121 | The shard clear callback calls atomic_commit(), inlining the repaired publisher (server.h:340). |
