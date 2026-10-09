2026-10-08 versionstr2 changed-body inventory. PRE is `db86e5b4a`; POST production source is `bac3c0066`.

The unchanged proof tools compare 94 common objects. Eight emitted bodies change, all in the existing INFO/HELLO/LOLWUT functions. The two added objects are separately inventoried in `new-objects.json`: only `db0/src/core/version.o` emits code (the 136-byte `__wrap_main`).

| Object | Body | PRE bytes | POST bytes | Reason |
| --- | --- | ---: | ---: | --- |
| `db0/src/cmd/server_tail.o` | `tomo_db0::(anonymous namespace)::cmd_lolwut(tomo_db0::Shard&, tomo_db0::Op&)` | 770 | 770 | LOLWUT footer reports the TomoKV identity constant |
| `db0/src/cmd/t_server.o` | `tomo_db0::(anonymous namespace)::cmd_info(tomo_db0::Shard&, tomo_db0::Op&)` | 16580 | 16596 | INFO reports separate Redis compatibility and TomoKV identity constants |
| `db0/src/cmd/t_server.o` | `tomo_db0::(anonymous namespace)::cmd_info(tomo_db0::Shard&, tomo_db0::Op&) [clone .cold]` | 338 | 338 | INFO reports separate Redis compatibility and TomoKV identity constants |
| `db0/src/cmd/t_server.o` | `tomo_db0::(anonymous namespace)::cmd_hello(tomo_db0::Shard&, tomo_db0::Op&)` | 2459 | 2459 | HELLO reports the numeric Redis compatibility constant |
| `src/cmd/server_tail.o` | `tomo::(anonymous namespace)::cmd_lolwut(tomo::Shard&, tomo::Op&)` | 770 | 770 | LOLWUT footer reports the TomoKV identity constant |
| `src/cmd/t_server.o` | `tomo::(anonymous namespace)::cmd_info(tomo::Shard&, tomo::Op&)` | 16864 | 16864 | INFO reports separate Redis compatibility and TomoKV identity constants |
| `src/cmd/t_server.o` | `tomo::(anonymous namespace)::cmd_info(tomo::Shard&, tomo::Op&) [clone .cold]` | 345 | 345 | INFO reports separate Redis compatibility and TomoKV identity constants |
| `src/cmd/t_server.o` | `tomo::(anonymous namespace)::cmd_hello(tomo::Shard&, tomo::Op&)` | 2229 | 2229 | HELLO reports the numeric Redis compatibility constant |
| `db0/src/core/version.o` | `__wrap_main` | 0 | 136 | Cold entry: print identity and compatibility; exit for argv[1] --version/-v; otherwise forward unchanged argc/argv and exit status to main. |

Both INFO cold clones retain raw bytes; their resolved references change with the INFO body. Every `main.o`, WbEngine, FlatStore and AofProducer body matches PRE. There are no unexplained changes. `.text` grows by 160 bytes; ordinary instructions remain 1,136,538 in each arm. No performance gain or PAD arm is claimed.
