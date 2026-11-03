# Linked body differences, PRE vs POST

Strict gate normalizer (docs/wave9/identity.py, tools/wave12_normalize.py). Identity is a proxy.

| Function group | PRE bytes | POST bytes | Hot | Intended | Data displacement only |
|---|---|---|---|---|---|
| `ScopedSignalHandlers::disarm() [clone .isra.0]` | [250, 246] | [250] |  |  |  |
| `int tomo::Ring::submit_and_wait<false>(unsigned int, unsigned int, int) [clone .isra.0]` | [339] | [339, 339] |  |  |  |
| `int tomo_db0::Ring::submit_and_wait<false>(unsigned int, unsigned int, int) [clone .isra.0]` | [] | [339] |  |  |  |
| `main` | [8834] | [8826] |  |  |  |
| `main.cold` | [5709] | [5709] |  |  |  |
| `std::__detail::_MakeUniq<tomo::ThreadCtx>::__single_object std::make_unique<tomo::ThreadCtx>()` | [] | [473] |  |  |  |
| `std::__detail::_MakeUniq<tomo_db0::ThreadCtx>::__single_object std::make_unique<tomo_db0::ThreadCtx>()` | [] | [473] |  |  |  |
| `tomo::(anonymous namespace)::command_key_args(tomo::MultiQueuedCommand const&, std::vector<unsigned int, std::allocator<unsigned int> >&)` | [1805] | [1805] |  |  | yes |
| `tomo::(anonymous namespace)::execute_plain_element_mover(tomo::Task const&, tomo::Shard&, tomo::Op&) [clone .isra.0]` | [2707] | [2707] |  |  | yes |
| `tomo::(anonymous namespace)::prepare_commands(tomo::Server&, tomo::MultiExecState&, std::vector<tomo::MultiQueuedCommand, std::allocator<tomo::MultiQueuedCommand> >&)` | [11691] | [11691] |  |  | yes |
| `tomo::(anonymous namespace)::release_admission(tomo::MultiExecState&)` | [224] | [256] |  | yes |  |
| `tomo::(anonymous namespace)::release_admission(tomo::MultiExecState&) [clone .cold]` | [6] | [15] |  | yes |  |
| `tomo::(anonymous namespace)::store_xstring_selected(bool, tomo::Shard&, tomo::Slice, unsigned long, tomo::Slice, long, bool, bool)` | [181] | [181] |  |  | yes |
| `tomo::FlatStore::atomic_collapse(unsigned long, unsigned long)` | [9666] | [9437] |  |  |  |
| `tomo::IoLoop::lb_control_pass()` | [4334] | [3954] |  |  |  |
| `tomo::Server::atomic_credit_wait_arm(unsigned int)` | [] | [79] |  | yes |  |
| `tomo::Server::atomic_ring_credit_waiters(unsigned int, tomo::Ring*, bool)` | [] | [292] |  | yes |  |
| `tomo::Server::init(tomo::Config const&, tomo::AofReplayPlan const*)` | [13558] | [13166] |  |  |  |
| `tomo::Server::set_snapshot_atomic_barrier(bool)` | [] | [41] |  | yes |  |
| `tomo::SnapshotManager::start(tomo::Server&, tomo::ThreadCtx&, tomo::Ring&, bool, std::__cxx11::basic_string<char, std::char_traits<char>, std::allocator<char> >&, tomo::AofManager*, char const*, char const*, bool)` | [7194] | [7264] |  | yes |  |
| `tomo::SnapshotManager::start(tomo::Server&, tomo::ThreadCtx&, tomo::Ring&, bool, std::__cxx11::basic_string<char, std::char_traits<char>, std::allocator<char> >&, tomo::AofManager*, char const*, char const*, bool) [clone .cold]` | [343] | [364] |  | yes |  |
| `tomo::info_stats_build_fields(std::__cxx11::basic_string<char, std::char_traits<char>, std::allocator<char> >&)` | [981] | [981] |  |  | yes |
| `tomo::multidb_flush(tomo::Shard&, unsigned char) [clone .cold]` | [67] | [67] |  |  |  |
| `tomo::notify_record_slow(tomo::Shard&, tomo::Op&, unsigned int, unsigned int, tomo::NotifyEventId, tomo::Slice)` | [2169] | [2169] |  |  | yes |
| `tomo::notify_reserve_chain(tomo::Server&, std::unique_ptr<tomo::PubSubNotificationChain, std::default_delete<tomo::PubSubNotificationChain> >, std::shared_ptr<tomo::NotifyExpiryCompletion>)` | [497] | [476] |  |  |  |
| `tomo::notify_reserve_chain(tomo::Server&, std::unique_ptr<tomo::PubSubNotificationChain, std::default_delete<tomo::PubSubNotificationChain> >, std::shared_ptr<tomo::NotifyExpiryCompletion>) [clone .cold]` | [267] | [267] |  |  |  |
| `tomo::script_window_resume(tomo::Server&, tomo::ScatterArenaPool&, unsigned int, tomo::Client&)` | [261] | [300] |  | yes |  |
| `tomo::stream_parse_xreadgroup(tomo::Op&, tomo::StreamXreadGroupArgs&)` | [1169] | [1169] |  |  | yes |
| `tomo::xshard_destroy(tomo::ScatterState*, tomo::ScatterArenaPool&, unsigned int)` | [855] | [855] |  | yes |  |
| `tomo::xshard_destroy(tomo::ScatterState*, tomo::ScatterArenaPool&, unsigned int) [clone .cold]` | [5] | [19] |  | yes |  |
| `tomo_db0::(anonymous namespace)::classify_keys(tomo_db0::Op const&, tomo_db0::(anonymous namespace)::Kind, tomo_db0::(anonymous namespace)::XshardKeyHints const&, tomo_db0::(anonymous namespace)::XshardKeyPlan&)` | [995] | [945] |  |  |  |
| `tomo_db0::(anonymous namespace)::command_key_args(tomo_db0::MultiQueuedCommand const&, std::vector<unsigned int, std::allocator<unsigned int> >&)` | [2404] | [2404] |  |  | yes |
| `tomo_db0::(anonymous namespace)::execute_plain_element_mover(tomo_db0::Task const&, tomo_db0::Shard&, tomo_db0::Op&) [clone .isra.0]` | [3494] | [3494] |  |  | yes |
| `tomo_db0::(anonymous namespace)::prepare_commands(tomo_db0::Server&, tomo_db0::MultiExecState&, std::vector<tomo_db0::MultiQueuedCommand, std::allocator<tomo_db0::MultiQueuedCommand> >&)` | [13197] | [13197] |  |  | yes |
| `tomo_db0::(anonymous namespace)::release_admission(tomo_db0::MultiExecState&)` | [224] | [256] |  | yes |  |
| `tomo_db0::(anonymous namespace)::release_admission(tomo_db0::MultiExecState&) [clone .cold]` | [6] | [15] |  | yes |  |
| `tomo_db0::(anonymous namespace)::store_xstring_selected(bool, tomo_db0::Shard&, tomo_db0::Slice, unsigned long, tomo_db0::Slice, long, bool, bool)` | [181] | [181] |  |  | yes |
| `tomo_db0::Server::atomic_credit_wait_arm(unsigned int)` | [] | [79] |  | yes |  |
| `tomo_db0::Server::atomic_ring_credit_waiters(unsigned int, tomo_db0::Ring*, bool)` | [] | [292] |  | yes |  |
| `tomo_db0::Server::init(tomo_db0::Config const&, tomo_db0::AofReplayPlan const*)` | [13581] | [13153] |  |  |  |
| `tomo_db0::Server::set_snapshot_atomic_barrier(bool)` | [] | [41] |  | yes |  |
| `tomo_db0::SnapshotManager::start(tomo_db0::Server&, tomo_db0::ThreadCtx&, tomo_db0::Ring&, bool, std::__cxx11::basic_string<char, std::char_traits<char>, std::allocator<char> >&, tomo_db0::AofManager*, char const*, char const*, bool)` | [7260] | [7280] |  | yes |  |
| `tomo_db0::SnapshotManager::start(tomo_db0::Server&, tomo_db0::ThreadCtx&, tomo_db0::Ring&, bool, std::__cxx11::basic_string<char, std::char_traits<char>, std::allocator<char> >&, tomo_db0::AofManager*, char const*, char const*, bool) [clone .cold]` | [335] | [353] |  | yes |  |
| `tomo_db0::info_stats_build_fields(std::__cxx11::basic_string<char, std::char_traits<char>, std::allocator<char> >&)` | [981] | [981] |  |  | yes |
| `tomo_db0::notify_record_slow(tomo_db0::Shard&, tomo_db0::Op&, unsigned int, unsigned int, tomo_db0::NotifyEventId, tomo_db0::Slice)` | [2034] | [2034] |  |  | yes |
| `tomo_db0::script_window_resume(tomo_db0::Server&, tomo_db0::ScatterArenaPool&, unsigned int, tomo_db0::Client&)` | [239] | [271] |  | yes |  |
| `tomo_db0::stream_parse_xreadgroup(tomo_db0::Op&, tomo_db0::StreamXreadGroupArgs&)` | [1169] | [1169] |  |  | yes |
| `tomo_db0::xshard_destroy(tomo_db0::ScatterState*, tomo_db0::ScatterArenaPool&, unsigned int)` | [807] | [807] |  | yes |  |
| `tomo_db0::xshard_destroy(tomo_db0::ScatterState*, tomo_db0::ScatterArenaPool&, unsigned int) [clone .cold]` | [5] | [19] |  | yes |  |
| `tomokv_multidb_main(int, char**)` | [12428] | [12532] |  |  |  |
| `tomokv_multidb_main(int, char**) [clone .cold]` | [5606] | [5242] |  |  |  |
| `unsigned int tomo::IoLoop::flip_control_pass<false>()` | [5219] | [5235] |  |  |  |
| `unsigned int tomo::IoLoop::flip_control_pass<true>()` | [5235] | [5219] |  |  |  |
| `unsigned int tomo::IoLoop::flush_ready<false, true, true, false, true>()` | [2385] | [2462] | yes |  |  |
| `unsigned int tomo_db0::IoLoop::flush_ready<true, false, true, false, false>()` | [2806] | [2854] | yes |  |  |
| `unsigned int tomo_db0::IoLoop::flush_ready<true, false, true, true, false>()` | [2806] | [2854] | yes |  |  |
| `unsigned long tomo::FlatStore::scan<tomo::xshard_execute(tomo::Task const&, tomo::Shard&, tomo::Op&, unsigned int)::{lambda(tomo::KvObj*)#1}>(unsigned long, unsigned int, tomo::xshard_execute(tomo::Task const&, tomo::Shard&, tomo::Op&, unsigned int)::{lambda(tomo::KvObj*)#1}&&, bool) [clone .constprop.0]` | [3774] | [3807] | yes |  |  |
| `unsigned long tomo::kvobj_external_bytes<false>(tomo::KvObj const*, void const*, tomo::KvObj const*) [clone .isra.0]` | [1606, 1351, 306, 306, 306, 1431, 490, 306, 306, 306, 826, 1111, 810, 618, 306, 746, 1606, 1606, 810, 1606, 1606, 810] | [1606, 1351, 306, 306, 306, 1431, 490, 306, 306, 306, 826, 1111, 810, 618, 306, 746, 1606, 1606, 810, 1606, 1606, 810] |  |  |  |
| `void std::vector<std::thread, std::allocator<std::thread> >::_M_realloc_insert<tomokv_multidb_main(int, char**)::{lambda()#3}>(__gnu_cxx::__normal_iterator<std::thread*, std::vector<std::thread, std::allocator<std::thread> > >, tomokv_multidb_main(int, char**)::{lambda()#3}&&)` | [] | [403] |  |  |  |
| `void tomo::IoLoop::r7_run_loop<false, false, false, true, false>()` | [6028] | [5840] |  | yes |  |
| `void tomo::IoLoop::r7_run_loop<false, false, true, true, false>()` | [5551] | [5606] |  | yes |  |
| `void tomo::IoLoop::r7_run_loop<false, true, false, true, false>()` | [6060] | [5884] |  | yes |  |
| `void tomo::IoLoop::r7_run_loop<false, true, true, true, false>()` | [5551] | [5606] |  | yes |  |
| `void tomo::IoLoop::r7_run_loop<true, false, false, true, false>()` | [6091] | [5917] |  | yes |  |
| `void tomo::IoLoop::r7_run_loop<true, false, true, true, false>()` | [5551] | [5606] |  | yes |  |
| `void tomo::IoLoop::r7_run_loop<true, true, false, true, false>()` | [6111] | [5950] |  | yes |  |
| `void tomo::IoLoop::r7_run_loop<true, true, true, true, false>()` | [5551] | [5606] |  | yes |  |
| `void tomo::IoLoop::run_loop<false, false, false, false, false>()` | [7098] | [7170] | yes | yes |  |
| `void tomo::IoLoop::run_loop<false, false, false, true, false>()` | [5678] | [5753] | yes | yes |  |
| `void tomo::IoLoop::run_loop<false, false, false, true, true>()` | [7172] | [7259] | yes | yes |  |
| `void tomo::IoLoop::run_loop<false, false, true, false, false>()` | [6139] | [6205] | yes | yes |  |
| `void tomo::IoLoop::run_loop<false, false, true, true, false>()` | [5595] | [5665] | yes | yes |  |
| `void tomo::IoLoop::run_loop<false, false, true, true, true>()` | [6209] | [6283] | yes | yes |  |
| `void tomo::IoLoop::run_loop<false, true, false, false, false>()` | [7556] | [7608] | yes | yes |  |
| `void tomo::IoLoop::run_loop<false, true, false, true, false>()` | [5740] | [5815] | yes | yes |  |
| `void tomo::IoLoop::run_loop<false, true, false, true, true>()` | [7640] | [7706] | yes | yes |  |
| `void tomo::IoLoop::run_loop<false, true, true, false, false>()` | [6139] | [6205] | yes | yes |  |
| `void tomo::IoLoop::run_loop<false, true, true, true, false>()` | [5595] | [5665] | yes | yes |  |
| `void tomo::IoLoop::run_loop<false, true, true, true, true>()` | [6209] | [6283] | yes | yes |  |
| `void tomo::IoLoop::run_loop<true, false, false, false, false>()` | [7613] | [7671] | yes | yes |  |
| `void tomo::IoLoop::run_loop<true, false, false, true, false>()` | [5773] | [5829] | yes | yes |  |
| `void tomo::IoLoop::run_loop<true, false, false, true, true>()` | [7682] | [7749] | yes | yes |  |
| `void tomo::IoLoop::run_loop<true, false, true, false, false>()` | [6171] | [6237] | yes | yes |  |
| `void tomo::IoLoop::run_loop<true, false, true, true, false>()` | [5608] | [5678] | yes | yes |  |
| `void tomo::IoLoop::run_loop<true, false, true, true, true>()` | [6237] | [6311] | yes | yes |  |
| `void tomo::IoLoop::run_loop<true, true, false, false, false>()` | [7991] | [8069] | yes | yes |  |
| `void tomo::IoLoop::run_loop<true, true, false, true, false>()` | [5404] | [5479] | yes | yes |  |
| `void tomo::IoLoop::run_loop<true, true, false, true, true>()` | [8049] | [8129] | yes | yes |  |
| `void tomo::IoLoop::run_loop<true, true, true, false, false>()` | [6171] | [6237] | yes | yes |  |
| `void tomo::IoLoop::run_loop<true, true, true, true, false>()` | [5608] | [5678] | yes | yes |  |
| `void tomo::IoLoop::run_loop<true, true, true, true, true>()` | [6237] | [6311] | yes | yes |  |
| `void tomo::cmd_xshard_only_impl<false>(tomo::Shard&, tomo::Op&)` | [16640] | [16640] | yes |  | yes |
| `void tomo::cmd_xshard_only_impl<true>(tomo::Shard&, tomo::Op&)` | [17797] | [17797] | yes |  | yes |
| `void tomo_db0::IoLoop::r7_run_loop<false, false, false, true, false>()` | [5922] | [5985] |  | yes |  |
| `void tomo_db0::IoLoop::r7_run_loop<false, false, true, true, false>()` | [5434] | [5481] |  | yes |  |
| `void tomo_db0::IoLoop::r7_run_loop<false, true, false, true, false>()` | [5947] | [6018] |  | yes |  |
| `void tomo_db0::IoLoop::r7_run_loop<false, true, true, true, false>()` | [5434] | [5481] |  | yes |  |
| `void tomo_db0::IoLoop::r7_run_loop<true, false, false, true, false>()` | [5988] | [6051] |  | yes |  |
| `void tomo_db0::IoLoop::r7_run_loop<true, false, true, true, false>()` | [5434] | [5478] |  | yes |  |
| `void tomo_db0::IoLoop::r7_run_loop<true, true, false, true, false>()` | [6018] | [6097] |  | yes |  |
| `void tomo_db0::IoLoop::r7_run_loop<true, true, true, true, false>()` | [5434] | [5478] |  | yes |  |
| `void tomo_db0::IoLoop::run_loop<false, false, false, false, false>()` | [6844] | [6918] | yes | yes |  |
| `void tomo_db0::IoLoop::run_loop<false, false, false, true, false>()` | [5709] | [5704] | yes | yes |  |
| `void tomo_db0::IoLoop::run_loop<false, false, false, true, true>()` | [6961] | [7029] | yes | yes |  |
| `void tomo_db0::IoLoop::run_loop<false, false, true, false, false>()` | [5874] | [5951] | yes | yes |  |
| `void tomo_db0::IoLoop::run_loop<false, false, true, true, false>()` | [5543] | [5626] | yes | yes |  |
| `void tomo_db0::IoLoop::run_loop<false, false, true, true, true>()` | [5925] | [5998] | yes | yes |  |
| `void tomo_db0::IoLoop::run_loop<false, true, false, false, false>()` | [7302] | [7347] | yes | yes |  |
| `void tomo_db0::IoLoop::run_loop<false, true, false, true, false>()` | [5773] | [5760] | yes | yes |  |
| `void tomo_db0::IoLoop::run_loop<false, true, false, true, true>()` | [7381] | [7453] | yes | yes |  |
| `void tomo_db0::IoLoop::run_loop<false, true, true, false, false>()` | [5874] | [5951] | yes | yes |  |
| `void tomo_db0::IoLoop::run_loop<false, true, true, true, false>()` | [5543] | [5626] | yes | yes |  |
| `void tomo_db0::IoLoop::run_loop<false, true, true, true, true>()` | [5925] | [5998] | yes | yes |  |
| `void tomo_db0::IoLoop::run_loop<true, false, false, false, false>()` | [7343] | [7400] | yes | yes |  |
| `void tomo_db0::IoLoop::run_loop<true, false, false, true, false>()` | [5804] | [5622] | yes | yes |  |
| `void tomo_db0::IoLoop::run_loop<true, false, false, true, true>()` | [7450] | [7508] | yes | yes |  |
| `void tomo_db0::IoLoop::run_loop<true, false, true, false, false>()` | [5906] | [5983] | yes | yes |  |
| `void tomo_db0::IoLoop::run_loop<true, false, true, true, false>()` | [5556] | [5639] | yes | yes |  |
| `void tomo_db0::IoLoop::run_loop<true, false, true, true, true>()` | [5969] | [6042] | yes | yes |  |
| `void tomo_db0::IoLoop::run_loop<true, true, false, false, false>()` | [7729] | [7793] | yes | yes |  |
| `void tomo_db0::IoLoop::run_loop<true, true, false, true, false>()` | [5847] | [5668] | yes | yes |  |
| `void tomo_db0::IoLoop::run_loop<true, true, false, true, true>()` | [7814] | [7900] | yes | yes |  |
| `void tomo_db0::IoLoop::run_loop<true, true, true, false, false>()` | [5906] | [5983] | yes | yes |  |
| `void tomo_db0::IoLoop::run_loop<true, true, true, true, false>()` | [5556] | [5639] | yes | yes |  |
| `void tomo_db0::IoLoop::run_loop<true, true, true, true, true>()` | [5969] | [6042] | yes | yes |  |
| `void tomo_db0::cmd_xshard_only_impl<false>(tomo_db0::Shard&, tomo_db0::Op&)` | [16757] | [16757] | yes |  | yes |
| `void tomo_db0::cmd_xshard_only_impl<true>(tomo_db0::Shard&, tomo_db0::Op&)` | [18094] | [18094] | yes |  | yes |
