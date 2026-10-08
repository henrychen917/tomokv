2026-10-08 versionstr2: **PASS**. See [the current changed-body inventory](versionstr2/changed-bodies.md) and [proof summary](versionstr2/proof/summary.json). The predecessor inventory below is retained as historical failed evidence.

Every changed emitted body, including duplicate destructor symbols. Unaccepted drift is a blocker.

| Object | Body | PRE bytes | POST bytes | Reason / status |
| --- | --- | ---: | ---: | --- |
| `db0/src/cmd/server_tail.o` | `tomo_db0::(anonymous namespace)::cmd_lolwut(tomo_db0::Shard&, tomo_db0::Op&)` | 770 | 770 | LOLWUT footer reports the TomoKV identity constant |
| `db0/src/cmd/t_server.o` | `tomo_db0::(anonymous namespace)::cmd_info(tomo_db0::Shard&, tomo_db0::Op&)` | 16580 | 16596 | INFO reports separate Redis compatibility and TomoKV identity constants |
| `db0/src/cmd/t_server.o` | `tomo_db0::(anonymous namespace)::cmd_info(tomo_db0::Shard&, tomo_db0::Op&) [clone .cold]` | 338 | 338 | INFO reports separate Redis compatibility and TomoKV identity constants |
| `db0/src/cmd/t_server.o` | `tomo_db0::(anonymous namespace)::cmd_hello(tomo_db0::Shard&, tomo_db0::Op&)` | 2491 | 2491 | HELLO reports the numeric Redis compatibility constant |
| `db0/src/core/genthread.o` | `tomo_db0::print_version(_IO_FILE*)` | 0 | 37 | shared cold product/compatibility version formatter |
| `db0/src/core/genthread.o` | `void tomo_db0::print_boot_presentation<tomo_db0::Server>(tomo_db0::Server&, _IO_FILE*)` | 515 | 526 | cold boot banner prints both versions before the existing geometry line |
| `db0/src/core/reorder.o` | `tomo_db0::print_version(_IO_FILE*)` | 0 | 37 | shared cold product/compatibility version formatter |
| `db0/src/core/reorder.o` | `void tomo_db0::print_boot_presentation<tomo_db0::Server>(tomo_db0::Server&, _IO_FILE*)` | 515 | 526 | cold boot banner prints both versions before the existing geometry line |
| `db0/src/core/rl2s.o` | `tomo_db0::print_version(_IO_FILE*)` | 0 | 37 | shared cold product/compatibility version formatter |
| `db0/src/core/rl2s.o` | `void tomo_db0::print_boot_presentation<tomo_db0::Server>(tomo_db0::Server&, _IO_FILE*)` | 515 | 526 | cold boot banner prints both versions before the existing geometry line |
| `db0/src/main.o` | `tomo_db0::AofProducer::~AofProducer()` | 2721 | 2722 | UNACCEPTED: unexplained by the audit; inferred compiler drift after the cold parser edit. Source body unchanged. |
| `db0/src/main.o` | `tomo_db0::AofProducer::~AofProducer()` | 2721 | 2722 | UNACCEPTED: unexplained by the audit; inferred compiler drift after the cold parser edit. Source body unchanged. |
| `db0/src/main.o` | `tomo_db0::print_version(_IO_FILE*)` | 0 | 37 | shared cold product/compatibility version formatter |
| `db0/src/main.o` | `tomo_db0::parse_config_args(std::vector<char const*, std::allocator<char const*> > const&, tomo_db0::Config&, tomo_db0::ConfigParseState&, int, char const*)` | 13253 | 13333 | cold CLI parser handles --version/-v before server initialization |
| `db0/src/main.o` | `void tomo_db0::print_boot_presentation<tomo_db0::Server>(tomo_db0::Server&, _IO_FILE*)` | 515 | 526 | cold boot banner prints both versions before the existing geometry line |
| `db0/src/main.o` | `tomo_db0::FlatStore::hash_key(tomo_db0::Slice) [clone .isra.0]` | 845 | 781 | UNACCEPTED: unexplained by the audit; inferred compiler drift after the cold parser edit. Source body unchanged. |
| `db0/src/main.o` | `tomo_db0::WbEngine::serve_impl<false, true, false, false, false, false>(tomo_db0::Client&, bool*)::{lambda(tomo_db0::Op&)#1}::operator()(tomo_db0::Op&) const` | 537 | 824 | UNACCEPTED: unexplained by the audit; inferred compiler drift after the cold parser edit. Source body unchanged. |
| `db0/src/main.o` | `tomo_db0::WbEngine::serve_impl<false, true, false, true, false, false>(tomo_db0::Client&, bool*)::{lambda(tomo_db0::Op&)#1}::operator()(tomo_db0::Op&) const` | 537 | 824 | UNACCEPTED: unexplained by the audit; inferred compiler drift after the cold parser edit. Source body unchanged. |
| `db0/src/main.o` | `tomo_db0::WbEngine::serve_impl<false, true, true, false, false, false>(tomo_db0::Client&, bool*)::{lambda(tomo_db0::Op&)#1}::operator()(tomo_db0::Op&) const` | 824 | 537 | UNACCEPTED: unexplained by the audit; inferred compiler drift after the cold parser edit. Source body unchanged. |
| `db0/src/main.o` | `tomo_db0::WbEngine::serve_impl<false, true, true, true, false, false>(tomo_db0::Client&, bool*)::{lambda(tomo_db0::Op&)#1}::operator()(tomo_db0::Op&) const` | 824 | 537 | UNACCEPTED: unexplained by the audit; inferred compiler drift after the cold parser edit. Source body unchanged. |
| `src/cmd/server_tail.o` | `tomo::(anonymous namespace)::cmd_lolwut(tomo::Shard&, tomo::Op&)` | 770 | 770 | LOLWUT footer reports the TomoKV identity constant |
| `src/cmd/t_server.o` | `tomo::(anonymous namespace)::cmd_info(tomo::Shard&, tomo::Op&)` | 16864 | 16864 | INFO reports separate Redis compatibility and TomoKV identity constants |
| `src/cmd/t_server.o` | `tomo::(anonymous namespace)::cmd_info(tomo::Shard&, tomo::Op&) [clone .cold]` | 345 | 345 | INFO reports separate Redis compatibility and TomoKV identity constants |
| `src/cmd/t_server.o` | `tomo::(anonymous namespace)::cmd_hello(tomo::Shard&, tomo::Op&)` | 2229 | 2229 | HELLO reports the numeric Redis compatibility constant |
| `src/core/genthread.o` | `tomo::print_version(_IO_FILE*)` | 0 | 37 | shared cold product/compatibility version formatter |
| `src/core/genthread.o` | `void tomo::print_boot_presentation<tomo::Server>(tomo::Server&, _IO_FILE*)` | 521 | 532 | cold boot banner prints both versions before the existing geometry line |
| `src/core/reorder.o` | `tomo::print_version(_IO_FILE*)` | 0 | 37 | shared cold product/compatibility version formatter |
| `src/core/reorder.o` | `void tomo::print_boot_presentation<tomo::Server>(tomo::Server&, _IO_FILE*)` | 521 | 532 | cold boot banner prints both versions before the existing geometry line |
| `src/core/rl2s.o` | `tomo::print_version(_IO_FILE*)` | 0 | 37 | shared cold product/compatibility version formatter |
| `src/core/rl2s.o` | `void tomo::print_boot_presentation<tomo::Server>(tomo::Server&, _IO_FILE*)` | 521 | 532 | cold boot banner prints both versions before the existing geometry line |
| `src/main.o` | `tomo::print_version(_IO_FILE*)` | 0 | 37 | shared cold product/compatibility version formatter |
| `src/main.o` | `tomo::parse_config_args(std::vector<char const*, std::allocator<char const*> > const&, tomo::Config&, tomo::ConfigParseState&, int, char const*)` | 12567 | 12647 | cold CLI parser handles --version/-v before server initialization |
| `src/main.o` | `void tomo::print_boot_presentation<tomo::Server>(tomo::Server&, _IO_FILE*)` | 521 | 532 | cold boot banner prints both versions before the existing geometry line |
