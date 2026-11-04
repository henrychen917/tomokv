# Linked body differences, PRE vs POST

Strict gate normalizer (docs/wave9/identity.py, tools/wave12_normalize.py). Identity is a proxy.

| Function group | PRE bytes | POST bytes | Hot | Intended | Data displacement only |
|---|---|---|---|---|---|
| `bool tomo::ExLoopT<false>::execute<false, false>(tomo::Task const&)` | [4127] | [4126] | yes | yes |  |
| `bool tomo::ExLoopT<false>::execute_latency<false, false>(tomo::Task const&)` | [2987] | [2992] | yes | yes |  |
| `bool tomo::ExLoopT<false>::execute_timed<false, false>(tomo::Task const&)` | [3034] | [3039] | yes | yes |  |
| `bool tomo::ExLoopT<false>::service_txn_boundary<false>()` | [2851] | [2851] |  |  |  |
| `bool tomo::ExLoopT<true>::execute<false, false>(tomo::Task const&)` | [4107] | [4109] | yes | yes |  |
| `bool tomo::ExLoopT<true>::execute<false, true>(tomo::Task const&)` | [3960] | [3960] | yes | yes |  |
| `bool tomo::ExLoopT<true>::execute<true, false>(tomo::Task const&)` | [4107] | [4109] | yes | yes |  |
| `bool tomo::ExLoopT<true>::execute<true, true>(tomo::Task const&)` | [3960] | [3960] | yes | yes |  |
| `bool tomo::ExLoopT<true>::execute_latency<false, false>(tomo::Task const&)` | [3305] | [3300] | yes | yes |  |
| `bool tomo::ExLoopT<true>::execute_latency<false, true>(tomo::Task const&)` | [3124] | [3143] | yes | yes |  |
| `bool tomo::ExLoopT<true>::execute_latency<true, false>(tomo::Task const&)` | [3305] | [3300] | yes | yes |  |
| `bool tomo::ExLoopT<true>::execute_latency<true, true>(tomo::Task const&)` | [3124] | [3143] | yes | yes |  |
| `bool tomo::ExLoopT<true>::execute_timed<false, false>(tomo::Task const&)` | [3325] | [3320] | yes | yes |  |
| `bool tomo::ExLoopT<true>::execute_timed<false, true>(tomo::Task const&)` | [3160] | [3178] | yes | yes |  |
| `bool tomo::ExLoopT<true>::execute_timed<true, false>(tomo::Task const&)` | [3325] | [3320] | yes | yes |  |
| `bool tomo::ExLoopT<true>::execute_timed<true, true>(tomo::Task const&)` | [3160] | [3178] | yes | yes |  |
| `bool tomo::ExLoopT<true>::service_txn_boundary<false>()` | [2793] | [2809] |  |  |  |
| `bool tomo::ExLoopT<true>::service_txn_boundary<true>()` | [2793] | [2809] |  |  |  |
| `bool tomo::IoLoop::finish_client_transfer<false>(tomo::Client*) [clone .isra.0]` | [913, 338, 656, 357] | [357, 338, 357, 357] |  |  |  |
| `bool tomo::IoLoop::finish_client_transfer<false>(tomo::Client*) [clone .isra.0] [clone .cold]` | [40, 40, 40, 40] | [40, 40, 40, 40] |  |  |  |
| `bool tomo::blocking_resume_move_impl<false>(tomo::Server&, tomo::ThreadCtx&, tomo::Ring&, tomo::Client&, tomo::ScatterArenaPool&)` | [2928] | [3008] |  | yes |  |
| `bool tomo::blocking_resume_move_impl<true>(tomo::Server&, tomo::ThreadCtx&, tomo::Ring&, tomo::Client&, tomo::ScatterArenaPool&)` | [2928] | [3008] |  | yes |  |
| `bool tomo_db0::ExLoopT<false>::execute<false, false>(tomo_db0::Task const&)` | [4224] | [4224] | yes | yes |  |
| `bool tomo_db0::ExLoopT<false>::execute_latency<false, false>(tomo_db0::Task const&)` | [2986] | [2991] | yes | yes |  |
| `bool tomo_db0::ExLoopT<false>::execute_timed<false, false>(tomo_db0::Task const&)` | [3033] | [3038] | yes | yes |  |
| `bool tomo_db0::ExLoopT<false>::service_txn_boundary<false>()` | [2851] | [2851] |  |  |  |
| `bool tomo_db0::ExLoopT<true>::execute<false, false>(tomo_db0::Task const&)` | [4107] | [4109] | yes | yes |  |
| `bool tomo_db0::ExLoopT<true>::execute<false, true>(tomo_db0::Task const&)` | [3960] | [3960] | yes | yes |  |
| `bool tomo_db0::ExLoopT<true>::execute<true, false>(tomo_db0::Task const&)` | [4107] | [4109] | yes | yes |  |
| `bool tomo_db0::ExLoopT<true>::execute<true, true>(tomo_db0::Task const&)` | [3960] | [3960] | yes | yes |  |
| `bool tomo_db0::ExLoopT<true>::execute_latency<false, false>(tomo_db0::Task const&)` | [3304] | [3299] | yes | yes |  |
| `bool tomo_db0::ExLoopT<true>::execute_latency<false, true>(tomo_db0::Task const&)` | [3123] | [3142] | yes | yes |  |
| `bool tomo_db0::ExLoopT<true>::execute_latency<true, false>(tomo_db0::Task const&)` | [3304] | [3299] | yes | yes |  |
| `bool tomo_db0::ExLoopT<true>::execute_latency<true, true>(tomo_db0::Task const&)` | [3123] | [3142] | yes | yes |  |
| `bool tomo_db0::ExLoopT<true>::execute_timed<false, false>(tomo_db0::Task const&)` | [3324] | [3319] | yes | yes |  |
| `bool tomo_db0::ExLoopT<true>::execute_timed<false, true>(tomo_db0::Task const&)` | [3159] | [3177] | yes | yes |  |
| `bool tomo_db0::ExLoopT<true>::execute_timed<true, false>(tomo_db0::Task const&)` | [3324] | [3319] | yes | yes |  |
| `bool tomo_db0::ExLoopT<true>::execute_timed<true, true>(tomo_db0::Task const&)` | [3159] | [3177] | yes | yes |  |
| `bool tomo_db0::ExLoopT<true>::service_txn_boundary<false>()` | [2793] | [2809] |  |  |  |
| `bool tomo_db0::ExLoopT<true>::service_txn_boundary<true>()` | [2793] | [2809] |  |  |  |
| `bool tomo_db0::IoLoop::finish_client_transfer<false>(tomo_db0::Client*) [clone .isra.0]` | [1103, 338, 1103, 357] | [357, 338, 357, 357] |  |  |  |
| `bool tomo_db0::IoLoop::finish_client_transfer<false>(tomo_db0::Client*) [clone .isra.0] [clone .cold]` | [40, 40, 40, 40] | [40, 40, 40, 40] |  |  |  |
| `bool tomo_db0::blocking_resume_move_impl<false>(tomo_db0::Server&, tomo_db0::ThreadCtx&, tomo_db0::Ring&, tomo_db0::Client&, tomo_db0::ScatterArenaPool&)` | [2915] | [2995] |  | yes |  |
| `bool tomo_db0::blocking_resume_move_impl<true>(tomo_db0::Server&, tomo_db0::ThreadCtx&, tomo_db0::Ring&, tomo_db0::Client&, tomo_db0::ScatterArenaPool&)` | [2915] | [2995] |  | yes |  |
| `int tomo_db0::Ring::submit_and_wait<false>(unsigned int, unsigned int, int) [clone .isra.0]` | [339] | [339, 339] |  |  |  |
| `json_append_data` | [1980] | [1980] |  |  | yes |
| `main` | [8826] | [8853] |  |  |  |
| `main.cold` | [5709] | [5709] |  |  |  |
| `math_random` | [404] | [404] |  |  | yes |
| `std::vector<tomo::Client*, std::allocator<tomo::Client*> >::resize(unsigned long)` | [] | [469] |  |  |  |
| `std::vector<tomo_db0::Client*, std::allocator<tomo_db0::Client*> >::resize(unsigned long)` | [] | [469] |  |  |  |
| `str_format` | [2252] | [2252] |  |  | yes |
| `tomo::(anonymous namespace)::BlockingRegistry::service(tomo::Shard&, tomo::(anonymous namespace)::BlockingQueue&, long, tomo::ThreadCtx&, tomo::Ring&) [clone .isra.0]` | [841] | [1053] |  | yes |  |
| `tomo::(anonymous namespace)::BlockingRegistry::sweep(tomo::Shard&, long, bool, tomo::ThreadCtx&, tomo::Ring&)` | [1151] | [1341] |  | yes |  |
| `tomo::(anonymous namespace)::blocking_notify_sender(tomo::Server&, tomo::ThreadCtx&, tomo::Ring&, tomo::Client*)` | [495] | [533] |  | yes |  |
| `tomo::(anonymous namespace)::blocking_notify_sender(tomo::Server&, tomo::ThreadCtx&, tomo::Ring&, tomo::Client*) [clone .cold]` | [] | [62] |  | yes |  |
| `tomo::(anonymous namespace)::blocking_request_remap(tomo::BlockingState&, tomo::ThreadCtx&, tomo::Ring&)` | [195] | [211] |  |  |  |
| `tomo::(anonymous namespace)::cmd_debug_impl(tomo::Shard&, tomo::Op&)` | [8891] | [9164] |  |  |  |
| `tomo::(anonymous namespace)::cmd_debug_impl(tomo::Shard&, tomo::Op&) [clone .cold]` | [2103] | [2167] |  |  |  |
| `tomo::(anonymous namespace)::cmd_info(tomo::Shard&, tomo::Op&)` | [17588] | [17588] |  |  |  |
| `tomo::(anonymous namespace)::cmd_info(tomo::Shard&, tomo::Op&) [clone .cold]` | [3011] | [3011] |  |  |  |
| `tomo::(anonymous namespace)::command_key_args(tomo::MultiQueuedCommand const&, std::vector<unsigned int, std::allocator<unsigned int> >&)` | [1805] | [1805] |  |  | yes |
| `tomo::(anonymous namespace)::execute_flush(tomo::Task const&, tomo::Shard&, tomo::Op&) [clone .isra.0]` | [610] | [611] |  |  |  |
| `tomo::(anonymous namespace)::execute_plain_element_mover(tomo::Task const&, tomo::Shard&, tomo::Op&) [clone .isra.0]` | [2707] | [2707] |  |  | yes |
| `tomo::(anonymous namespace)::free_state_contents(tomo::ScatterState&) [clone .part.0]` | [1045] | [1029] |  |  |  |
| `tomo::(anonymous namespace)::geo_encode(double, double)` | [168] | [168] |  |  | yes |
| `tomo::(anonymous namespace)::geohashDecode(tomo::(anonymous namespace)::GeoHashRange, tomo::(anonymous namespace)::GeoHashRange, tomo::(anonymous namespace)::GeoHashBits, tomo::(anonymous namespace)::GeoHashArea*) [clone .constprop.0] [clone .isra.0]` | [314] | [314] |  |  | yes |
| `tomo::(anonymous namespace)::geohashEncode(tomo::(anonymous namespace)::GeoHashRange const*, tomo::(anonymous namespace)::GeoHashRange const*, double, double, unsigned char, tomo::(anonymous namespace)::GeoHashBits*) [clone .constprop.0] [clone .isra.0]` | [334] | [334] |  |  | yes |
| `tomo::(anonymous namespace)::parse_search(tomo::Op&, tomo::(anonymous namespace)::GeoSearchOptions&, std::vector<tomo::ZsetEntry, std::allocator<tomo::ZsetEntry> > const&)::{lambda(unsigned int)#1}::operator()(unsigned int) const` | [358] | [358] |  |  | yes |
| `tomo::(anonymous namespace)::parse_zset_operation(tomo::Op&, tomo::(anonymous namespace)::Kind, unsigned int&, std::vector<double, std::allocator<double> >&, tomo::(anonymous namespace)::ZAggregate&, bool&, unsigned long&) [clone .constprop.0]` | [2324] | [2324] |  |  | yes |
| `tomo::(anonymous namespace)::prepare_commands(tomo::Server&, tomo::MultiExecState&, std::vector<tomo::MultiQueuedCommand, std::allocator<tomo::MultiQueuedCommand> >&)` | [11691] | [11691] |  |  | yes |
| `tomo::(anonymous namespace)::prepare_debug_loadaof(tomo::Server&, tomo::Op&, unsigned int, tomo::Client*, std::unique_ptr<tomo::SnapshotLoadPlan, std::default_delete<tomo::SnapshotLoadPlan> >&, std::vector<std::unique_ptr<tomo::AofReplayPlan, std::default_delete<tomo::AofReplayPlan> >, std::allocator<std::unique_ptr<tomo::AofReplayPlan, std::default_delete<tomo::AofReplayPlan> > > >&)` | [896] | [960] |  | yes |  |
| `tomo::(anonymous namespace)::prepare_sort_deref(tomo::ScatterState&, tomo::Op&)::{lambda(tomo::SortPattern const&, tomo::Slice, bool, unsigned long)#1}::operator()(tomo::SortPattern const&, tomo::Slice, bool, unsigned long) const [clone .constprop.0]` | [3211] | [3127] |  |  |  |
| `tomo::(anonymous namespace)::prepare_sort_deref(tomo::ScatterState&, tomo::Op&)::{lambda(tomo::SortPattern const&, tomo::Slice, bool, unsigned long)#1}::operator()(tomo::SortPattern const&, tomo::Slice, bool, unsigned long) const [clone .constprop.0] [clone .cold]` | [162] | [166] |  |  |  |
| `tomo::(anonymous namespace)::script_random(lua_State*)` | [475] | [475] |  |  | yes |
| `tomo::(anonymous namespace)::store_xstring_selected(bool, tomo::Shard&, tomo::Slice, unsigned long, tomo::Slice, long, bool, bool)` | [181] | [181] |  |  | yes |
| `tomo::(anonymous namespace)::submit_large_frame_wake(tomo::AofOwnerContext*)` | [] | [68] |  | yes |  |
| `tomo::AofManager::drain_producer(unsigned int, unsigned int&, unsigned int&, tomo::Ring&, io_uring_sqe*&)` | [1567] | [1565] |  | yes |  |
| `tomo::AofManager::drain_producer(unsigned int, unsigned int&, unsigned int&, tomo::Ring&, io_uring_sqe*&) [clone .cold]` | [195] | [198] |  | yes |  |
| `tomo::AofManager::writer_pass(tomo::ThreadCtx&, tomo::Ring&, bool)` | [1494] | [1558] |  | yes |  |
| `tomo::AofManager::writer_pass(tomo::ThreadCtx&, tomo::Ring&, bool) [clone .cold]` | [114] | [114] |  | yes |  |
| `tomo::AofProducer::emit(unsigned char const*, unsigned long, bool, tomo::AofOwnerContext*, unsigned long)` | [482] | [523] |  | yes |  |
| `tomo::AofProducer::record_bytes(tomo::AofRecordKind, unsigned char, unsigned char, tomo::Slice, long, unsigned long, unsigned char const*, unsigned long, tomo::SnapshotTypeHooks const*, tomo::SnapshotSaveCursor*, tomo::AofOwnerContext*)` | [1677] | [1709] |  | yes |  |
| `tomo::AofProducer::record_bytes(tomo::AofRecordKind, unsigned char, unsigned char, tomo::Slice, long, unsigned long, unsigned char const*, unsigned long, tomo::SnapshotTypeHooks const*, tomo::SnapshotSaveCursor*, tomo::AofOwnerContext*) [clone .cold]` | [122] | [122] |  | yes |  |
| `tomo::DatabaseMap::bind_workers(unsigned int, tomo::Server*)` | [527] | [543] |  |  |  |
| `tomo::DatabaseMap::bind_workers(unsigned int, tomo::Server*) [clone .cold]` | [114] | [114] |  |  |  |
| `tomo::DatabaseMap::boundary_started()` | [172] | [172] |  |  |  |
| `tomo::DatabaseMap::drain_deadline_start(tomo::Server&, unsigned long, unsigned long)` | [] | [313] |  | yes |  |
| `tomo::DatabaseMap::join_workers(tomo::Server&, std::vector<std::thread, std::allocator<std::thread> >&)` | [888] | [888] |  |  |  |
| `tomo::DatabaseMap::monitor(tomo::Server&) [clone .part.0]` | [778] | [778] |  | yes |  |
| `tomo::DatabaseMap::note_drain_waiting()` | [] | [108] |  | yes |  |
| `tomo::DatabaseMap::publish(std::unique_ptr<tomo::DatabaseMap::Map, std::default_delete<tomo::DatabaseMap::Map> >)` | [923] | [923] |  |  |  |
| `tomo::DatabaseMap::state()` | [341] | [325] |  |  |  |
| `tomo::DatabaseMap::worker_exited(unsigned int)` | [49] | [49] |  |  |  |
| `tomo::DatabaseMap::~DatabaseMap()` | [229] | [229] |  |  |  |
| `tomo::DebugSleepCoordinator<128u, 50u>::exclusive(unsigned int, unsigned int, void*, void (*)(void*, unsigned int))` | [575] | [] |  | yes |  |
| `tomo::ExLoopT<false>::flip_control_pass()` | [1588] | [1573] |  | yes |  |
| `tomo::ExLoopT<false>::flip_quiesced() const` | [514] | [546] |  | yes |  |
| `tomo::ExLoopT<false>::notify_sender_to(tomo::Client*, unsigned int)` | [355] | [865] |  | yes |  |
| `tomo::ExLoopT<false>::run()` | [9256] | [9595] | yes | yes |  |
| `tomo::ExLoopT<false>::service_notify_retries()` | [] | [174] |  | yes |  |
| `tomo::ExLoopT<true>::flip_control_pass()` | [1193] | [1174] |  | yes |  |
| `tomo::ExLoopT<true>::flip_quiesced() const` | [562] | [588] |  | yes |  |
| `tomo::ExLoopT<true>::notify_sender_to(tomo::Client*, unsigned int)` | [355] | [865] |  | yes |  |
| `tomo::ExLoopT<true>::run()` | [8936] | [9261] | yes | yes |  |
| `tomo::ExLoopT<true>::service_notify_retries()` | [] | [174] |  | yes |  |
| `tomo::FlipController::debug_dump[abi:cxx11]() const` | [6458] | [6458] |  |  | yes |
| `tomo::FlipController::seek_after_reading(tomo::Server&, unsigned int, unsigned long, double)` | [1281] | [1281] |  |  | yes |
| `tomo::IoLoop::climon_copy_client_filter(tomo::PubSubEvent&, tomo::PubSubEvent const&)` | [383] | [380] |  |  |  |
| `tomo::IoLoop::climon_monitor_stop(tomo::Client*, unsigned long)` | [345] | [181] |  |  |  |
| `tomo::IoLoop::climon_start_client_command(tomo::Client*, tomo::Op&)` | [1779] | [1789] |  | yes |  |
| `tomo::IoLoop::climon_start_client_kill(tomo::Client*, tomo::Op&)` | [2634] | [2463] |  |  |  |
| `tomo::IoLoop::climon_start_client_kill(tomo::Client*, tomo::Op&) [clone .cold]` | [378] | [378] |  |  |  |
| `tomo::IoLoop::database_control_pass()` | [1066] | [1132] |  | yes |  |
| `tomo::IoLoop::lb_control_pass()` | [3954] | [4015] |  | yes |  |
| `tomo::IoLoop::pubsub_reply_ping(tomo::Op&) [clone .isra.0]` | [395, 438, 597, 597, 395] | [395, 503, 597, 597, 395] |  |  |  |
| `tomo::IoLoop::reap_dead()` | [1740] | [1239] |  |  |  |
| `tomo::LbAutotune::KeyDamping::update(double, tomo::LbAutotune::QuietJitter&, unsigned int&, unsigned int, int, unsigned long, unsigned long, unsigned long)` | [957] | [957] |  |  | yes |
| `tomo::LbAutotune::QuietJitter::band(unsigned int) const [clone .isra.0]` | [167] | [167] |  |  | yes |
| `tomo::MultiExecState::~MultiExecState()` | [2047] | [2031] |  |  |  |
| `tomo::PubSubEvent::~PubSubEvent()` | [603] | [603] |  |  |  |
| `tomo::Ring::msg_to(tomo::Ring&, unsigned long) [clone .isra.0]` | [653, 653, 979] | [653, 653, 653, 979] |  |  |  |
| `tomo::Ring::msg_to(tomo::Ring&, unsigned long) [clone .isra.0] [clone .cold]` | [40, 40, 40] | [40, 40, 40, 40] |  |  |  |
| `tomo::Server::defer_completion_notice(unsigned int, tomo::Client*)` | [] | [531] |  | yes |  |
| `tomo::Server::flipctl_debug_dump[abi:cxx11]() const` | [1769] | [1769] |  |  |  |
| `tomo::Server::lb_controller_tick(unsigned int, unsigned long)::{lambda(double, tomo::LbAutotune::QuietJitter&, unsigned int&, unsigned int)#1}::operator()(double, tomo::LbAutotune::QuietJitter&, unsigned int&, unsigned int) const` | [559] | [559] |  |  | yes |
| `tomo::Server::lb_controller_tick_pad(unsigned int, unsigned long)::{lambda(double, tomo::LbAutotune::QuietJitter&, unsigned int&, unsigned int)#1}::operator()(double, tomo::LbAutotune::QuietJitter&, unsigned int&, unsigned int) const` | [559] | [559] |  |  | yes |
| `tomo::Server::lb_debug_move_client(unsigned long, unsigned int, std::__cxx11::basic_string<char, std::char_traits<char>, std::allocator<char> >&)` | [724] | [782] |  | yes |  |
| `tomo::Server::monitor_controllers()` | [921] | [1459] |  | yes |  |
| `tomo::Server::monitor_controllers() [clone .cold]` | [] | [45] |  | yes |  |
| `tomo::Server::monitor_controllers()::{lambda(unsigned int)#1}::operator()(unsigned int) const` | [] | [1291] |  | yes |  |
| `tomo::Server::monitor_controllers()::{lambda(unsigned int)#1}::operator()(unsigned int) const [clone .cold]` | [] | [22] |  | yes |  |
| `tomo::Server::~Server()` | [2281] | [2329] |  |  |  |
| `tomo::Shard::watch_finish_unit(std::vector<tomo::TxnClaim, std::allocator<tomo::TxnClaim> > const&, void const*, tomo::MultiRetryPromoter const*)` | [178] | [182] |  |  |  |
| `tomo::SnapshotManager::post_chunk(unsigned int, std::unique_ptr<tomo::SnapshotChunk, std::default_delete<tomo::SnapshotChunk> >&, tomo::Ring&, tomo::LoopSignals&)` | [335] | [472] |  | yes |  |
| `tomo::SnapshotManager::writer_pass(tomo::ThreadCtx&, tomo::Ring&, bool)` | [980] | [1092] |  | yes |  |
| `tomo::SnapshotManager::writer_pass(tomo::ThreadCtx&, tomo::Ring&, bool)::{lambda(unsigned int)#1}::operator()(unsigned int) const` | [] | [226] |  | yes |  |
| `tomo::auth_dispatch_entry(tomo::IoLoop&, tomo::Client&, tomo::Op&, unsigned int)` | [1191] | [1287] |  |  |  |
| `tomo::blocking_atomic_published(tomo::Server&, tomo::ThreadCtx&, tomo::Ring&, tomo::ScatterState&)` | [429] | [445] |  | yes |  |
| `tomo::blocking_cancel_client(tomo::Server&, tomo::ThreadCtx&, tomo::Ring&, tomo::Client&) [clone .part.0]` | [706] | [689] |  |  |  |
| `tomo::blocking_execute(tomo::Server&, tomo::ThreadCtx&, tomo::Ring&, tomo::Task const&, tomo::Shard&, tomo::Op&)` | [2169] | [2367] |  |  |  |
| `tomo::blocking_execute(tomo::Server&, tomo::ThreadCtx&, tomo::Ring&, tomo::Task const&, tomo::Shard&, tomo::Op&) [clone .cold]` | [237] | [259] |  |  |  |
| `tomo::blocking_execute_iofused(tomo::Server&, tomo::ThreadCtx&, tomo::Ring&, tomo::Task const&, tomo::Shard&, tomo::Op&)` | [2169] | [2367] |  |  |  |
| `tomo::blocking_execute_iofused(tomo::Server&, tomo::ThreadCtx&, tomo::Ring&, tomo::Task const&, tomo::Shard&, tomo::Op&) [clone .cold]` | [237] | [259] |  |  |  |
| `tomo::blocking_key_created(void const*, tomo::Slice)` | [97] | [97] |  |  |  |
| `tomo::blocking_owner_dirty_pending(tomo::ThreadCtx&)` | [] | [83] |  | yes |  |
| `tomo::blocking_plain_mutation_published(tomo::Shard&, tomo::Op&)` | [152] | [152] |  |  |  |
| `tomo::blocking_publish_key(tomo::Shard&, unsigned long, char const*, unsigned int, unsigned char)` | [520] | [520] |  |  |  |
| `tomo::blocking_scatter_repark(tomo::Server&, tomo::ThreadCtx&, tomo::Ring&, tomo::ScatterState&)` | [174] | [180] |  |  |  |
| `tomo::blocking_scatter_retire(tomo::Server&, tomo::Client&, tomo::ScatterState&)` | [419] | [403] |  |  |  |
| `tomo::blocking_stream_removed(void const*, tomo::Slice, tomo::KvObj const*)` | [961] | [958] |  |  |  |
| `tomo::cfg_client_output_buffer_limit_string[abi:cxx11](tomo::ClientOutputBufferLimits const&)` | [3694] | [3720] |  |  |  |
| `tomo::cfgfix_rebind(tomo::Server&, unsigned int, unsigned short, std::__cxx11::basic_string<char, std::char_traits<char>, std::allocator<char> > const&, std::__cxx11::basic_string<char, std::char_traits<char>, std::allocator<char> >&, int)` | [3428] | [4118] |  | yes |  |
| `tomo::cfgfix_rebind(tomo::Server&, unsigned int, unsigned short, std::__cxx11::basic_string<char, std::char_traits<char>, std::allocator<char> > const&, std::__cxx11::basic_string<char, std::char_traits<char>, std::allocator<char> >&, int) [clone .cold]` | [108] | [215] |  | yes |  |
| `tomo::cfgfix_rebind(tomo::Server&, unsigned int, unsigned short, std::__cxx11::basic_string<char, std::char_traits<char>, std::allocator<char> > const&, std::__cxx11::basic_string<char, std::char_traits<char>, std::allocator<char> >&, int)::{lambda(void*, unsigned int)#1}::_FUN(void*, unsigned int)` | [] | [292] |  | yes |  |
| `tomo::command_client_pause(tomo::Server&, tomo::Op&, unsigned long)` | [808] | [] |  | yes |  |
| `tomo::command_client_pause(tomo::Server&, tomo::Op&, unsigned long) [clone .cold]` | [128] | [] |  | yes |  |
| `tomo::command_client_pause(tomo::Server&, tomo::Op&, unsigned long, unsigned int)` | [] | [1019] |  | yes |  |
| `tomo::command_client_pause(tomo::Server&, tomo::Op&, unsigned long, unsigned int) [clone .cold]` | [] | [128] |  | yes |  |
| `tomo::dtoa::grisu2_digits(double, char*, int&)` | [1043] | [1043] |  |  | yes |
| `tomo::info_stats_build_fields(std::__cxx11::basic_string<char, std::char_traits<char>, std::allocator<char> >&)` | [981] | [981] |  |  | yes |
| `tomo::multi_exec_io_commands(tomo::IoLoop&, tomo::MultiExecState&)` | [2468] | [2484] |  | yes |  |
| `tomo::multi_execute_task(tomo::Server&, tomo::Task const&, tomo::Shard&, unsigned int, unsigned int, tomo::AofOwnerContext*, tomo::MultiRetryPromoter const*)` | [9532] | [9551] |  | yes |  |
| `tomo::multi_execute_task_tracked(tomo::Server&, tomo::Task const&, tomo::Shard&, unsigned int, unsigned int, tomo::AofOwnerContext*, tomo::MultiRetryPromoter const*)` | [8228] | [8248] |  | yes |  |
| `tomo::multi_retire(tomo::Client&, tomo::Op&, std::vector<tomo::MultiExecState*, std::allocator<tomo::MultiExecState*> >&)` | [2057] | [2060] |  | yes |  |
| `tomo::multi_retry_lane_note_pending()` | [] | [14] |  | yes |  |
| `tomo::multidb_flush(tomo::Shard&, unsigned char) [clone .cold]` | [67] | [67] |  |  |  |
| `tomo::notify_record_slow(tomo::Shard&, tomo::Op&, unsigned int, unsigned int, tomo::NotifyEventId, tomo::Slice)` | [2169] | [2169] |  |  | yes |
| `tomo::notify_reserve_chain(tomo::Server&, std::unique_ptr<tomo::PubSubNotificationChain, std::default_delete<tomo::PubSubNotificationChain> >, std::shared_ptr<tomo::NotifyExpiryCompletion>)` | [476] | [534] |  |  |  |
| `tomo::notify_reserve_chain(tomo::Server&, std::unique_ptr<tomo::PubSubNotificationChain, std::default_delete<tomo::PubSubNotificationChain> >, std::shared_ptr<tomo::NotifyExpiryCompletion>) [clone .cold]` | [267] | [267] |  |  |  |
| `tomo::parse_double_strict(tomo::Slice, double&)` | [487] | [487] |  |  | yes |
| `tomo::redis_double_text(char*, unsigned long, double) [clone .isra.0]` | [1043, 1043, 1043, 1043, 1043] | [1043, 1043, 1043, 1043, 1043] |  |  | yes |
| `tomo_db0::(anonymous namespace)::BlockingRegistry::service(tomo_db0::Shard&, tomo_db0::(anonymous namespace)::BlockingQueue&, long, tomo_db0::ThreadCtx&, tomo_db0::Ring&) [clone .isra.0]` | [772] | [903] |  | yes |  |
| `tomo_db0::(anonymous namespace)::BlockingRegistry::sweep(tomo_db0::Shard&, long, bool, tomo_db0::ThreadCtx&, tomo_db0::Ring&)` | [744] | [904] |  | yes |  |
| `tomo_db0::(anonymous namespace)::blocking_notify_sender(tomo_db0::Server&, tomo_db0::ThreadCtx&, tomo_db0::Ring&, tomo_db0::Client*)` | [495] | [932] |  | yes |  |
| `tomo_db0::(anonymous namespace)::blocking_notify_sender(tomo_db0::Server&, tomo_db0::ThreadCtx&, tomo_db0::Ring&, tomo_db0::Client*) [clone .cold]` | [] | [62] |  | yes |  |
| `tomo_db0::(anonymous namespace)::classify_keys(tomo_db0::Op const&, tomo_db0::(anonymous namespace)::Kind, tomo_db0::(anonymous namespace)::XshardKeyHints const&, tomo_db0::(anonymous namespace)::XshardKeyPlan&)` | [945] | [958] |  |  |  |
| `tomo_db0::(anonymous namespace)::cmd_debug_impl(tomo_db0::Shard&, tomo_db0::Op&)` | [8806] | [9079] |  |  |  |
| `tomo_db0::(anonymous namespace)::cmd_debug_impl(tomo_db0::Shard&, tomo_db0::Op&) [clone .cold]` | [2071] | [2135] |  |  |  |
| `tomo_db0::(anonymous namespace)::cmd_info(tomo_db0::Shard&, tomo_db0::Op&)` | [17336] | [17336] |  |  |  |
| `tomo_db0::(anonymous namespace)::cmd_info(tomo_db0::Shard&, tomo_db0::Op&) [clone .cold]` | [2770] | [2770] |  |  |  |
| `tomo_db0::(anonymous namespace)::command_key_args(tomo_db0::MultiQueuedCommand const&, std::vector<unsigned int, std::allocator<unsigned int> >&)` | [2404] | [2404] |  |  | yes |
| `tomo_db0::(anonymous namespace)::execute_flush(tomo_db0::Task const&, tomo_db0::Shard&, tomo_db0::Op&) [clone .isra.0]` | [688] | [689] |  |  |  |
| `tomo_db0::(anonymous namespace)::execute_plain_element_mover(tomo_db0::Task const&, tomo_db0::Shard&, tomo_db0::Op&) [clone .isra.0]` | [3494] | [3494] |  |  | yes |
| `tomo_db0::(anonymous namespace)::geo_encode(double, double)` | [168] | [168] |  |  | yes |
| `tomo_db0::(anonymous namespace)::geohashDecode(tomo_db0::(anonymous namespace)::GeoHashRange, tomo_db0::(anonymous namespace)::GeoHashRange, tomo_db0::(anonymous namespace)::GeoHashBits, tomo_db0::(anonymous namespace)::GeoHashArea*) [clone .constprop.0] [clone .isra.0]` | [314] | [314] |  |  | yes |
| `tomo_db0::(anonymous namespace)::geohashEncode(tomo_db0::(anonymous namespace)::GeoHashRange const*, tomo_db0::(anonymous namespace)::GeoHashRange const*, double, double, unsigned char, tomo_db0::(anonymous namespace)::GeoHashBits*) [clone .constprop.0] [clone .isra.0]` | [334] | [334] |  |  | yes |
| `tomo_db0::(anonymous namespace)::manifest_name(std::__cxx11::basic_string<char, std::char_traits<char>, std::allocator<char> > const&)` | [920] | [685] |  |  |  |
| `tomo_db0::(anonymous namespace)::manifest_name(std::__cxx11::basic_string<char, std::char_traits<char>, std::allocator<char> > const&) [clone .cold]` | [40] | [40] |  |  |  |
| `tomo_db0::(anonymous namespace)::parse_search(tomo_db0::Op&, tomo_db0::(anonymous namespace)::GeoSearchOptions&, std::vector<tomo_db0::ZsetEntry, std::allocator<tomo_db0::ZsetEntry> > const&)::{lambda(unsigned int)#1}::operator()(unsigned int) const` | [358] | [358] |  |  | yes |
| `tomo_db0::(anonymous namespace)::parse_zset_operation(tomo_db0::Op&, tomo_db0::(anonymous namespace)::Kind, unsigned int&, std::vector<double, std::allocator<double> >&, tomo_db0::(anonymous namespace)::ZAggregate&, bool&, unsigned long&) [clone .constprop.0]` | [2349] | [2349] |  |  | yes |
| `tomo_db0::(anonymous namespace)::prepare_commands(tomo_db0::Server&, tomo_db0::MultiExecState&, std::vector<tomo_db0::MultiQueuedCommand, std::allocator<tomo_db0::MultiQueuedCommand> >&)` | [13197] | [13197] |  |  | yes |
| `tomo_db0::(anonymous namespace)::prepare_debug_loadaof(tomo_db0::Server&, tomo_db0::Op&, unsigned int, tomo_db0::Client*, std::unique_ptr<tomo_db0::SnapshotLoadPlan, std::default_delete<tomo_db0::SnapshotLoadPlan> >&, std::vector<std::unique_ptr<tomo_db0::AofReplayPlan, std::default_delete<tomo_db0::AofReplayPlan> >, std::allocator<std::unique_ptr<tomo_db0::AofReplayPlan, std::default_delete<tomo_db0::AofReplayPlan> > > >&)` | [508] | [578] |  | yes |  |
| `tomo_db0::(anonymous namespace)::script_random(lua_State*)` | [509] | [509] |  |  | yes |
| `tomo_db0::(anonymous namespace)::store_xstring_selected(bool, tomo_db0::Shard&, tomo_db0::Slice, unsigned long, tomo_db0::Slice, long, bool, bool)` | [181] | [181] |  |  | yes |
| `tomo_db0::(anonymous namespace)::submit_large_frame_wake(tomo_db0::AofOwnerContext*)` | [] | [68] |  | yes |  |
| `tomo_db0::AofManager::drain_producer(unsigned int, unsigned int&, unsigned int&, tomo_db0::Ring&, io_uring_sqe*&)` | [1719] | [1735] |  | yes |  |
| `tomo_db0::AofManager::drain_producer(unsigned int, unsigned int&, unsigned int&, tomo_db0::Ring&, io_uring_sqe*&) [clone .cold]` | [198] | [198] |  | yes |  |
| `tomo_db0::AofManager::writer_pass(tomo_db0::ThreadCtx&, tomo_db0::Ring&, bool)` | [1495] | [1562] |  | yes |  |
| `tomo_db0::AofManager::writer_pass(tomo_db0::ThreadCtx&, tomo_db0::Ring&, bool) [clone .cold]` | [114] | [114] |  | yes |  |
| `tomo_db0::AofProducer::emit(unsigned char const*, unsigned long, bool, tomo_db0::AofOwnerContext*, unsigned long)` | [482] | [523] |  | yes |  |
| `tomo_db0::AofProducer::record_bytes(tomo_db0::AofRecordKind, unsigned char, unsigned char, tomo_db0::Slice, long, unsigned long, unsigned char const*, unsigned long, tomo_db0::SnapshotTypeHooks const*, tomo_db0::SnapshotSaveCursor*, tomo_db0::AofOwnerContext*)` | [1645] | [1677] |  | yes |  |
| `tomo_db0::AofProducer::record_bytes(tomo_db0::AofRecordKind, unsigned char, unsigned char, tomo_db0::Slice, long, unsigned long, unsigned char const*, unsigned long, tomo_db0::SnapshotTypeHooks const*, tomo_db0::SnapshotSaveCursor*, tomo_db0::AofOwnerContext*) [clone .cold]` | [122] | [122] |  | yes |  |
| `tomo_db0::DatabaseMap::drain_deadline_start(tomo_db0::Server&, unsigned long, unsigned long)` | [] | [313] |  | yes |  |
| `tomo_db0::DatabaseMap::note_drain_waiting()` | [] | [5] |  | yes |  |
| `tomo_db0::DatabaseMap::publish(std::unique_ptr<tomo_db0::DatabaseMap::Map, std::default_delete<tomo_db0::DatabaseMap::Map> >)` | [498] | [498] |  |  |  |
| `tomo_db0::DatabaseMap::state()` | [341] | [325] |  |  |  |
| `tomo_db0::DatabaseMap::~DatabaseMap()` | [229] | [229] |  |  |  |
| `tomo_db0::DebugSleepCoordinator<128u, 50u>::exclusive(unsigned int, unsigned int, void*, void (*)(void*, unsigned int))` | [575] | [] |  | yes |  |
| `tomo_db0::ExLoopT<false>::flip_quiesced() const` | [656] | [684] |  | yes |  |
| `tomo_db0::ExLoopT<false>::notify_sender_to(tomo_db0::Client*, unsigned int)` | [355] | [865] |  | yes |  |
| `tomo_db0::ExLoopT<false>::run()` | [9046] | [9234] | yes | yes |  |
| `tomo_db0::ExLoopT<false>::service_notify_retries()` | [] | [174] |  | yes |  |
| `tomo_db0::ExLoopT<true>::flip_quiesced() const` | [704] | [704] |  | yes |  |
| `tomo_db0::ExLoopT<true>::notify_sender_to(tomo_db0::Client*, unsigned int)` | [355] | [865] |  | yes |  |
| `tomo_db0::ExLoopT<true>::run()` | [8666] | [8845] | yes | yes |  |
| `tomo_db0::ExLoopT<true>::service_notify_retries()` | [] | [174] |  | yes |  |
| `tomo_db0::FlatStore::atomic_install_plain(unsigned long, tomo_db0::Slice, void*&, tomo_db0::KvObj*&, unsigned long)` | [1172] | [986] |  |  |  |
| `tomo_db0::FlipController::debug_dump[abi:cxx11]() const` | [6458] | [6458] |  |  | yes |
| `tomo_db0::FlipController::seek_after_reading(tomo_db0::Server&, unsigned int, unsigned long, double)` | [1281] | [1281] |  |  | yes |
| `tomo_db0::IoLoop::DispatchResult tomo_db0::IoLoop::parse_and_dispatch<false, 32u, false>(tomo_db0::Client*) [clone .isra.0]` | [19203] | [19264] | yes |  |  |
| `tomo_db0::IoLoop::DispatchResult tomo_db0::IoLoop::parse_and_dispatch<false, 32u, false>(tomo_db0::Client*) [clone .isra.0] [clone .cold]` | [711] | [714] | yes |  |  |
| `tomo_db0::IoLoop::DispatchResult tomo_db0::IoLoop::parse_and_dispatch<false, 32u, true>(tomo_db0::Client*)` | [19998] | [20141] | yes |  |  |
| `tomo_db0::IoLoop::DispatchResult tomo_db0::IoLoop::parse_and_dispatch<true, 0u, false>(tomo_db0::Client*) [clone .isra.0]` | [9804, 11407, 9804, 11067] | [9804, 11423, 9804, 10897] | yes |  |  |
| `tomo_db0::IoLoop::DispatchResult tomo_db0::IoLoop::parse_and_dispatch<true, 0u, false>(tomo_db0::Client*) [clone .isra.0] [clone .cold]` | [525, 592, 525, 596] | [525, 592, 525, 592] | yes |  |  |
| `tomo_db0::IoLoop::DispatchResult tomo_db0::IoLoop::parse_and_dispatch<true, 32u, false>(tomo_db0::Client*) [clone .isra.0]` | [19168, 18673] | [19220, 18673] | yes |  |  |
| `tomo_db0::IoLoop::DispatchResult tomo_db0::IoLoop::parse_and_dispatch<true, 32u, false>(tomo_db0::Client*) [clone .isra.0] [clone .cold]` | [732, 732] | [719, 732] | yes |  |  |
| `tomo_db0::IoLoop::DispatchResult tomo_db0::IoLoop::parse_and_dispatch<true, 32u, true>(tomo_db0::Client*)` | [20014] | [20067] | yes |  |  |
| `tomo_db0::IoLoop::climon_copy_client_filter(tomo_db0::PubSubEvent&, tomo_db0::PubSubEvent const&)` | [639] | [383] |  |  |  |
| `tomo_db0::IoLoop::climon_start_client_command(tomo_db0::Client*, tomo_db0::Op&)` | [1779] | [1789] |  | yes |  |
| `tomo_db0::IoLoop::lb_control_pass()` | [4983] | [5048] |  | yes |  |
| `tomo_db0::IoLoop::reap_dead()` | [1740] | [1239] |  |  |  |
| `tomo_db0::LbAutotune::KeyDamping::update(double, tomo_db0::LbAutotune::QuietJitter&, unsigned int&, unsigned int, int, unsigned long, unsigned long, unsigned long)` | [957] | [957] |  |  | yes |
| `tomo_db0::LbAutotune::QuietJitter::band(unsigned int) const [clone .isra.0]` | [167] | [167] |  |  | yes |
| `tomo_db0::MonitorScriptLine* std::__move_merge<__gnu_cxx::__normal_iterator<tomo_db0::MonitorScriptLine*, std::vector<tomo_db0::MonitorScriptLine, std::allocator<tomo_db0::MonitorScriptLine> > >, tomo_db0::MonitorScriptLine*, __gnu_cxx::__ops::_Iter_comp_iter<tomo_db0::IoLoop::climon_monitor_script_deliver(unsigned long, std::vector<tomo_db0::MonitorScriptLine, std::allocator<tomo_db0::MonitorScriptLine> >&)::{lambda(auto:1 const&, auto:2 const&)#1}> >(__gnu_cxx::__normal_iterator<tomo_db0::MonitorScriptLine*, std::vector<tomo_db0::MonitorScriptLine, std::allocator<tomo_db0::MonitorScriptLine> > >, __gnu_cxx::__normal_iterator<tomo_db0::MonitorScriptLine*, std::vector<tomo_db0::MonitorScriptLine, std::allocator<tomo_db0::MonitorScriptLine> > >, __gnu_cxx::__normal_iterator<tomo_db0::MonitorScriptLine*, std::vector<tomo_db0::MonitorScriptLine, std::allocator<tomo_db0::MonitorScriptLine> > >, __gnu_cxx::__normal_iterator<tomo_db0::MonitorScriptLine*, std::vector<tomo_db0::MonitorScriptLine, std::allocator<tomo_db0::MonitorScriptLine> > >, tomo_db0::MonitorScriptLine*, __gnu_cxx::__ops::_Iter_comp_iter<tomo_db0::IoLoop::climon_monitor_script_deliver(unsigned long, std::vector<tomo_db0::MonitorScriptLine, std::allocator<tomo_db0::MonitorScriptLine> >&)::{lambda(auto:1 const&, auto:2 const&)#1}>) [clone .isra.0]` | [1016] | [1000] |  |  |  |
| `tomo_db0::PubSubEvent::~PubSubEvent()` | [603] | [603] |  |  |  |
| `tomo_db0::Ring::msg_to(tomo_db0::Ring&, unsigned long) [clone .isra.0]` | [653, 653, 979] | [653, 653, 653, 979] |  |  |  |
| `tomo_db0::Ring::msg_to(tomo_db0::Ring&, unsigned long) [clone .isra.0] [clone .cold]` | [40, 40, 40] | [40, 40, 40, 40] |  |  |  |
| `tomo_db0::Server::defer_completion_notice(unsigned int, tomo_db0::Client*)` | [] | [531] |  | yes |  |
| `tomo_db0::Server::flip_begin(unsigned int, unsigned int, unsigned int, std::__cxx11::basic_string<char, std::char_traits<char>, std::allocator<char> >&, unsigned long)` | [6307] | [6311] |  |  |  |
| `tomo_db0::Server::flipctl_debug_dump[abi:cxx11]() const` | [1883] | [1890] |  |  |  |
| `tomo_db0::Server::lb_controller_tick(unsigned int, unsigned long)::{lambda(double, tomo_db0::LbAutotune::QuietJitter&, unsigned int&, unsigned int)#1}::operator()(double, tomo_db0::LbAutotune::QuietJitter&, unsigned int&, unsigned int) const` | [559] | [559] |  |  | yes |
| `tomo_db0::Server::lb_controller_tick_pad(unsigned int, unsigned long)::{lambda(double, tomo_db0::LbAutotune::QuietJitter&, unsigned int&, unsigned int)#1}::operator()(double, tomo_db0::LbAutotune::QuietJitter&, unsigned int&, unsigned int) const` | [559] | [559] |  |  | yes |
| `tomo_db0::Server::lb_debug_move_client(unsigned long, unsigned int, std::__cxx11::basic_string<char, std::char_traits<char>, std::allocator<char> >&)` | [721] | [779] |  | yes |  |
| `tomo_db0::Server::monitor_controllers()` | [925] | [1442] |  | yes |  |
| `tomo_db0::Server::monitor_controllers() [clone .cold]` | [] | [44] |  | yes |  |
| `tomo_db0::Server::monitor_controllers()::{lambda(unsigned int)#1}::operator()(unsigned int) const` | [] | [1291] |  | yes |  |
| `tomo_db0::Server::monitor_controllers()::{lambda(unsigned int)#1}::operator()(unsigned int) const [clone .cold]` | [] | [22] |  | yes |  |
| `tomo_db0::Server::~Server()` | [2376] | [2440] |  |  |  |
| `tomo_db0::Shard::watch_finish_unit(std::vector<tomo_db0::TxnClaim, std::allocator<tomo_db0::TxnClaim> > const&, void const*, tomo_db0::MultiRetryPromoter const*)` | [210] | [214] |  |  |  |
| `tomo_db0::SnapshotManager::post_chunk(unsigned int, std::unique_ptr<tomo_db0::SnapshotChunk, std::default_delete<tomo_db0::SnapshotChunk> >&, tomo_db0::Ring&, tomo_db0::LoopSignals&)` | [335] | [472] |  | yes |  |
| `tomo_db0::SnapshotManager::writer_pass(tomo_db0::ThreadCtx&, tomo_db0::Ring&, bool)` | [980] | [1092] |  | yes |  |
| `tomo_db0::SnapshotManager::writer_pass(tomo_db0::ThreadCtx&, tomo_db0::Ring&, bool)::{lambda(unsigned int)#1}::operator()(unsigned int) const` | [] | [226] |  | yes |  |
| `tomo_db0::blocking_atomic_published(tomo_db0::Server&, tomo_db0::ThreadCtx&, tomo_db0::Ring&, tomo_db0::ScatterState&)` | [429] | [445] |  | yes |  |
| `tomo_db0::blocking_cancel_client(tomo_db0::Server&, tomo_db0::ThreadCtx&, tomo_db0::Ring&, tomo_db0::Client&) [clone .part.0]` | [706] | [689] |  |  |  |
| `tomo_db0::blocking_execute(tomo_db0::Server&, tomo_db0::ThreadCtx&, tomo_db0::Ring&, tomo_db0::Task const&, tomo_db0::Shard&, tomo_db0::Op&)` | [2409] | [2526] |  |  |  |
| `tomo_db0::blocking_execute(tomo_db0::Server&, tomo_db0::ThreadCtx&, tomo_db0::Ring&, tomo_db0::Task const&, tomo_db0::Shard&, tomo_db0::Op&) [clone .cold]` | [309] | [331] |  |  |  |
| `tomo_db0::blocking_execute_iofused(tomo_db0::Server&, tomo_db0::ThreadCtx&, tomo_db0::Ring&, tomo_db0::Task const&, tomo_db0::Shard&, tomo_db0::Op&)` | [2409] | [2526] |  |  |  |
| `tomo_db0::blocking_execute_iofused(tomo_db0::Server&, tomo_db0::ThreadCtx&, tomo_db0::Ring&, tomo_db0::Task const&, tomo_db0::Shard&, tomo_db0::Op&) [clone .cold]` | [309] | [331] |  |  |  |
| `tomo_db0::blocking_key_created(void const*, tomo_db0::Slice)` | [97] | [97] |  |  |  |
| `tomo_db0::blocking_owner_dirty_pending(tomo_db0::ThreadCtx&)` | [] | [83] |  | yes |  |
| `tomo_db0::blocking_plain_mutation_published(tomo_db0::Shard&, tomo_db0::Op&)` | [152] | [152] |  |  |  |
| `tomo_db0::blocking_publish_key(tomo_db0::Shard&, unsigned long, char const*, unsigned int, unsigned char)` | [271] | [271] |  |  |  |
| `tomo_db0::blocking_scatter_repark(tomo_db0::Server&, tomo_db0::ThreadCtx&, tomo_db0::Ring&, tomo_db0::ScatterState&)` | [174] | [180] |  |  |  |
| `tomo_db0::blocking_scatter_retire(tomo_db0::Server&, tomo_db0::Client&, tomo_db0::ScatterState&)` | [419] | [403] |  |  |  |
| `tomo_db0::blocking_stream_removed(void const*, tomo_db0::Slice, tomo_db0::KvObj const*)` | [829] | [840] |  |  |  |
| `tomo_db0::blocking_stream_removed(void const*, tomo_db0::Slice, tomo_db0::KvObj const*) [clone .cold]` | [25] | [25] |  |  |  |
| `tomo_db0::cfg_client_output_buffer_limit_string[abi:cxx11](tomo_db0::ClientOutputBufferLimits const&)` | [3899] | [3880] |  |  |  |
| `tomo_db0::cfgfix_rebind(tomo_db0::Server&, unsigned int, unsigned short, std::__cxx11::basic_string<char, std::char_traits<char>, std::allocator<char> > const&, std::__cxx11::basic_string<char, std::char_traits<char>, std::allocator<char> >&, int)` | [3428] | [4086] |  | yes |  |
| `tomo_db0::cfgfix_rebind(tomo_db0::Server&, unsigned int, unsigned short, std::__cxx11::basic_string<char, std::char_traits<char>, std::allocator<char> > const&, std::__cxx11::basic_string<char, std::char_traits<char>, std::allocator<char> >&, int) [clone .cold]` | [108] | [215] |  | yes |  |
| `tomo_db0::cfgfix_rebind(tomo_db0::Server&, unsigned int, unsigned short, std::__cxx11::basic_string<char, std::char_traits<char>, std::allocator<char> > const&, std::__cxx11::basic_string<char, std::char_traits<char>, std::allocator<char> >&, int)::{lambda(void*, unsigned int)#1}::_FUN(void*, unsigned int)` | [] | [292] |  | yes |  |
| `tomo_db0::command_client_pause(tomo_db0::Server&, tomo_db0::Op&, unsigned long)` | [808] | [] |  | yes |  |
| `tomo_db0::command_client_pause(tomo_db0::Server&, tomo_db0::Op&, unsigned long) [clone .cold]` | [128] | [] |  | yes |  |
| `tomo_db0::command_client_pause(tomo_db0::Server&, tomo_db0::Op&, unsigned long, unsigned int)` | [] | [1019] |  | yes |  |
| `tomo_db0::command_client_pause(tomo_db0::Server&, tomo_db0::Op&, unsigned long, unsigned int) [clone .cold]` | [] | [128] |  | yes |  |
| `tomo_db0::command_client_slowlog_identity(unsigned long, std::__cxx11::basic_string<char, std::char_traits<char>, std::allocator<char> >&, std::__cxx11::basic_string<char, std::char_traits<char>, std::allocator<char> >&)` | [399] | [397] |  |  |  |
| `tomo_db0::command_client_slowlog_identity(unsigned long, std::__cxx11::basic_string<char, std::char_traits<char>, std::allocator<char> >&, std::__cxx11::basic_string<char, std::char_traits<char>, std::allocator<char> >&) [clone .cold]` | [19] | [19] |  |  |  |
| `tomo_db0::dtoa::grisu2_digits(double, char*, int&)` | [1043] | [1043] |  |  | yes |
| `tomo_db0::info_stats_build_fields(std::__cxx11::basic_string<char, std::char_traits<char>, std::allocator<char> >&)` | [981] | [981] |  |  | yes |
| `tomo_db0::multi_exec_io_commands(tomo_db0::IoLoop&, tomo_db0::MultiExecState&)` | [2562] | [2562] |  | yes |  |
| `tomo_db0::multi_exec_io_commands(tomo_db0::IoLoop&, tomo_db0::MultiExecState&) [clone .cold]` | [222] | [222] |  | yes |  |
| `tomo_db0::multi_execute_task(tomo_db0::Server&, tomo_db0::Task const&, tomo_db0::Shard&, unsigned int, unsigned int, tomo_db0::AofOwnerContext*, tomo_db0::MultiRetryPromoter const*)` | [9403] | [9267] |  | yes |  |
| `tomo_db0::multi_execute_task(tomo_db0::Server&, tomo_db0::Task const&, tomo_db0::Shard&, unsigned int, unsigned int, tomo_db0::AofOwnerContext*, tomo_db0::MultiRetryPromoter const*) [clone .cold]` | [382] | [383] |  | yes |  |
| `tomo_db0::multi_execute_task_tracked(tomo_db0::Server&, tomo_db0::Task const&, tomo_db0::Shard&, unsigned int, unsigned int, tomo_db0::AofOwnerContext*, tomo_db0::MultiRetryPromoter const*)` | [8303] | [8323] |  | yes |  |
| `tomo_db0::multi_retire(tomo_db0::Client&, tomo_db0::Op&, std::vector<tomo_db0::MultiExecState*, std::allocator<tomo_db0::MultiExecState*> >&)` | [2095] | [2098] |  | yes |  |
| `tomo_db0::multi_retry_lane_note_pending()` | [] | [14] |  | yes |  |
| `tomo_db0::notify_record_slow(tomo_db0::Shard&, tomo_db0::Op&, unsigned int, unsigned int, tomo_db0::NotifyEventId, tomo_db0::Slice)` | [2034] | [2034] |  |  | yes |
| `tomo_db0::parse_double_strict(tomo_db0::Slice, double&)` | [503] | [503] |  |  | yes |
| `tomo_db0::redis_double_text(char*, unsigned long, double) [clone .isra.0]` | [1043, 1043, 1043, 1043, 1043] | [1043, 1043, 1043, 1043, 1043] |  |  | yes |
| `tomokv_multidb_main(int, char**)` | [12532] | [12564] |  |  |  |
| `tomokv_multidb_main(int, char**) [clone .cold]` | [5242] | [5242] |  |  |  |
| `unsigned int tomo::ExLoopT<false>::sweep<32u, true, false, false>()` | [1968] | [2017] | yes | yes |  |
| `unsigned int tomo::ExLoopT<true>::fused_pass_impl<32u, true, false, false>()` | [3466] | [3559] | yes | yes |  |
| `unsigned int tomo::ExLoopT<true>::fused_pass_impl<32u, true, false, true>()` | [3846] | [3956] | yes | yes |  |
| `unsigned int tomo::ExLoopT<true>::r7_fused_pass_impl<32u, true, false, false>()` | [3607] | [3689] | yes | yes |  |
| `unsigned int tomo::ExLoopT<true>::r7_fused_pass_impl<32u, true, false, true>()` | [3927] | [4005] | yes | yes |  |
| `unsigned int tomo::ExLoopT<true>::r7_sweep<32u, true, false, false>()` | [1227] | [924] | yes | yes |  |
| `unsigned int tomo::ExLoopT<true>::r7_sweep<32u, true, false, true>()` | [1147] | [1194] | yes | yes |  |
| `unsigned int tomo::ExLoopT<true>::sweep<32u, true, false, false>()` | [1227] | [1275] | yes | yes |  |
| `unsigned int tomo::ExLoopT<true>::sweep<32u, true, false, true>()` | [1510] | [1558] | yes | yes |  |
| `unsigned int tomo::IoLoop::flush_ready<true, false, false, false, false>()` | [5179] | [5215] | yes | yes |  |
| `unsigned int tomo::IoLoop::flush_ready<true, false, true, false, false, true>()` | [3839] | [3839] | yes | yes |  |
| `unsigned int tomo::IoLoop::flush_ready<true, false, true, false, false>()` | [2838] | [2838] | yes | yes |  |
| `unsigned int tomo::IoLoop::flush_ready<true, false, true, false, true, true>()` | [3775] | [3836] | yes | yes |  |
| `unsigned int tomo::IoLoop::flush_ready<true, false, true, false, true>()` | [2774] | [2774] | yes | yes |  |
| `unsigned int tomo::IoLoop::flush_ready<true, false, true, true, false, true>()` | [3839] | [3839] | yes | yes |  |
| `unsigned int tomo::IoLoop::flush_ready<true, false, true, true, false>()` | [2838] | [2838] | yes | yes |  |
| `unsigned int tomo::IoLoop::flush_ready<true, false, true, true, true, true>()` | [3775] | [3836] | yes | yes |  |
| `unsigned int tomo::IoLoop::flush_ready<true, false, true, true, true>()` | [2774] | [2774] | yes | yes |  |
| `unsigned int tomo::IoLoop::flush_ready<true, true, false, false, false>()` | [6048] | [6062] | yes | yes |  |
| `unsigned int tomo::IoLoop::flush_ready<true, true, true, false, false, true>()` | [3878] | [3894] | yes | yes |  |
| `unsigned int tomo::IoLoop::flush_ready<true, true, true, false, false>()` | [3303] | [3335] | yes | yes |  |
| `unsigned int tomo::IoLoop::flush_ready<true, true, true, false, true, true>()` | [3814] | [3798] | yes | yes |  |
| `unsigned int tomo::IoLoop::flush_ready<true, true, true, false, true>()` | [3255] | [3271] | yes | yes |  |
| `unsigned int tomo::IoLoop::flush_ready<true, true, true, true, false, true>()` | [3878] | [3894] | yes | yes |  |
| `unsigned int tomo::IoLoop::flush_ready<true, true, true, true, false>()` | [3303] | [3335] | yes | yes |  |
| `unsigned int tomo::IoLoop::flush_ready<true, true, true, true, true, true>()` | [3814] | [3798] | yes | yes |  |
| `unsigned int tomo::IoLoop::flush_ready<true, true, true, true, true>()` | [3255] | [3271] | yes | yes |  |
| `unsigned int tomo::IoLoop::r7_flush_ready<true, false, true, false, false, false>()` | [2950] | [2950] | yes | yes |  |
| `unsigned int tomo::IoLoop::r7_flush_ready<true, false, true, false, true, false>()` | [2950] | [2950] | yes | yes |  |
| `unsigned int tomo::IoLoop::r7_flush_ready<true, false, true, true, false, false>()` | [2950] | [2950] | yes | yes |  |
| `unsigned int tomo::IoLoop::r7_flush_ready<true, false, true, true, true, false>()` | [2950] | [2950] | yes | yes |  |
| `unsigned int tomo::IoLoop::r7_flush_ready<true, true, true, false, false, false>()` | [3463] | [3463] | yes | yes |  |
| `unsigned int tomo::IoLoop::r7_flush_ready<true, true, true, false, true, false>()` | [3463] | [3463] | yes | yes |  |
| `unsigned int tomo::IoLoop::r7_flush_ready<true, true, true, true, false, false>()` | [3463] | [3463] | yes | yes |  |
| `unsigned int tomo::IoLoop::r7_flush_ready<true, true, true, true, true, false>()` | [3463] | [3463] | yes | yes |  |
| `unsigned int tomo::multi_owner_pass_entry_impl<false>(tomo::IoLoop&)` | [12827] | [13113] |  | yes |  |
| `unsigned int tomo_db0::ExLoopT<false>::sweep<32u, true, false, false>()` | [1968] | [2017] | yes | yes |  |
| `unsigned int tomo_db0::ExLoopT<true>::fused_pass_impl<32u, true, false, false>()` | [3735] | [3833] | yes | yes |  |
| `unsigned int tomo_db0::ExLoopT<true>::fused_pass_impl<32u, true, false, true>()` | [3846] | [3956] | yes | yes |  |
| `unsigned int tomo_db0::ExLoopT<true>::r7_fused_pass_impl<32u, true, false, false>()` | [4169] | [4261] | yes | yes |  |
| `unsigned int tomo_db0::ExLoopT<true>::r7_fused_pass_impl<32u, true, false, true>()` | [4290] | [4233] | yes | yes |  |
| `unsigned int tomo_db0::ExLoopT<true>::r7_sweep<32u, true, false, false>()` | [1227] | [1275] | yes | yes |  |
| `unsigned int tomo_db0::ExLoopT<true>::r7_sweep<32u, true, false, true>()` | [1510] | [1558] | yes | yes |  |
| `unsigned int tomo_db0::ExLoopT<true>::sweep<32u, true, false, false>()` | [1227] | [1275] | yes | yes |  |
| `unsigned int tomo_db0::ExLoopT<true>::sweep<32u, true, false, true>()` | [1510] | [1558] | yes | yes |  |
| `unsigned int tomo_db0::IoLoop::flush_ready<true, false, false, false, false>()` | [5147] | [5183] | yes | yes |  |
| `unsigned int tomo_db0::IoLoop::flush_ready<true, false, true, false, false, true>()` | [3807] | [3807] | yes | yes |  |
| `unsigned int tomo_db0::IoLoop::flush_ready<true, false, true, false, false>()` | [2854] | [2854] | yes | yes |  |
| `unsigned int tomo_db0::IoLoop::flush_ready<true, false, true, false, true, true>()` | [3743] | [3804] | yes | yes |  |
| `unsigned int tomo_db0::IoLoop::flush_ready<true, false, true, false, true>()` | [2790] | [2790] | yes | yes |  |
| `unsigned int tomo_db0::IoLoop::flush_ready<true, false, true, true, false, true>()` | [3807] | [3807] | yes | yes |  |
| `unsigned int tomo_db0::IoLoop::flush_ready<true, false, true, true, false>()` | [2854] | [2854] | yes | yes |  |
| `unsigned int tomo_db0::IoLoop::flush_ready<true, false, true, true, true, true>()` | [3743] | [3804] | yes | yes |  |
| `unsigned int tomo_db0::IoLoop::flush_ready<true, false, true, true, true>()` | [2790] | [2790] | yes | yes |  |
| `unsigned int tomo_db0::IoLoop::flush_ready<true, true, false, false, false>()` | [6016] | [6030] | yes | yes |  |
| `unsigned int tomo_db0::IoLoop::flush_ready<true, true, true, false, false, true>()` | [3846] | [3862] | yes | yes |  |
| `unsigned int tomo_db0::IoLoop::flush_ready<true, true, true, false, false>()` | [3367] | [3367] | yes | yes |  |
| `unsigned int tomo_db0::IoLoop::flush_ready<true, true, true, false, true, true>()` | [3782] | [3766] | yes | yes |  |
| `unsigned int tomo_db0::IoLoop::flush_ready<true, true, true, false, true>()` | [3287] | [3319] | yes | yes |  |
| `unsigned int tomo_db0::IoLoop::flush_ready<true, true, true, true, false, true>()` | [3846] | [3862] | yes | yes |  |
| `unsigned int tomo_db0::IoLoop::flush_ready<true, true, true, true, false>()` | [3367] | [3367] | yes | yes |  |
| `unsigned int tomo_db0::IoLoop::flush_ready<true, true, true, true, true, true>()` | [3782] | [3766] | yes | yes |  |
| `unsigned int tomo_db0::IoLoop::flush_ready<true, true, true, true, true>()` | [3287] | [3319] | yes | yes |  |
| `unsigned int tomo_db0::IoLoop::r7_flush_ready<true, false, true, false, false, false>()` | [2982] | [2982] | yes | yes |  |
| `unsigned int tomo_db0::IoLoop::r7_flush_ready<true, false, true, false, true, false>()` | [2982] | [2982] | yes | yes |  |
| `unsigned int tomo_db0::IoLoop::r7_flush_ready<true, false, true, true, false, false>()` | [2982] | [2982] | yes | yes |  |
| `unsigned int tomo_db0::IoLoop::r7_flush_ready<true, false, true, true, true, false>()` | [2982] | [2982] | yes | yes |  |
| `unsigned int tomo_db0::IoLoop::r7_flush_ready<true, true, true, false, false, false>()` | [3479] | [3527] | yes | yes |  |
| `unsigned int tomo_db0::IoLoop::r7_flush_ready<true, true, true, false, true, false>()` | [3479] | [3527] | yes | yes |  |
| `unsigned int tomo_db0::IoLoop::r7_flush_ready<true, true, true, true, false, false>()` | [3479] | [3527] | yes | yes |  |
| `unsigned int tomo_db0::IoLoop::r7_flush_ready<true, true, true, true, true, false>()` | [3479] | [3527] | yes | yes |  |
| `unsigned int tomo_db0::multi_owner_pass_entry_impl<false>(tomo_db0::IoLoop&)` | [13515] | [13802] |  | yes |  |
| `unsigned long tomo::FlatStore::scan<tomo::xshard_execute(tomo::Task const&, tomo::Shard&, tomo::Op&, unsigned int)::{lambda(tomo::KvObj*)#1}>(unsigned long, unsigned int, tomo::xshard_execute(tomo::Task const&, tomo::Shard&, tomo::Op&, unsigned int)::{lambda(tomo::KvObj*)#1}&&, bool) [clone .constprop.0]` | [3807] | [3663] | yes |  |  |
| `unsigned long tomo::kvobj_external_bytes<false>(tomo::KvObj const*, void const*, tomo::KvObj const*) [clone .isra.0]` | [1606, 1351, 306, 306, 306, 1431, 490, 306, 306, 306, 826, 1111, 810, 618, 306, 746, 1606, 1606, 810, 1606, 1606, 810] | [1606, 1351, 306, 306, 306, 1431, 490, 306, 306, 306, 826, 1111, 810, 602, 306, 746, 1606, 1606, 810, 1606, 1606, 810] |  |  |  |
| `void std::__merge_adaptive<__gnu_cxx::__normal_iterator<tomo_db0::MonitorScriptLine*, std::vector<tomo_db0::MonitorScriptLine, std::allocator<tomo_db0::MonitorScriptLine> > >, long, tomo_db0::MonitorScriptLine*, __gnu_cxx::__ops::_Iter_comp_iter<tomo_db0::IoLoop::climon_monitor_script_deliver(unsigned long, std::vector<tomo_db0::MonitorScriptLine, std::allocator<tomo_db0::MonitorScriptLine> >&)::{lambda(auto:1 const&, auto:2 const&)#1}> >(__gnu_cxx::__normal_iterator<tomo_db0::MonitorScriptLine*, std::vector<tomo_db0::MonitorScriptLine, std::allocator<tomo_db0::MonitorScriptLine> > >, __gnu_cxx::__normal_iterator<tomo_db0::MonitorScriptLine*, std::vector<tomo_db0::MonitorScriptLine, std::allocator<tomo_db0::MonitorScriptLine> > >, __gnu_cxx::__normal_iterator<tomo_db0::MonitorScriptLine*, std::vector<tomo_db0::MonitorScriptLine, std::allocator<tomo_db0::MonitorScriptLine> > >, long, long, tomo_db0::MonitorScriptLine*, __gnu_cxx::__ops::_Iter_comp_iter<tomo_db0::IoLoop::climon_monitor_script_deliver(unsigned long, std::vector<tomo_db0::MonitorScriptLine, std::allocator<tomo_db0::MonitorScriptLine> >&)::{lambda(auto:1 const&, auto:2 const&)#1}>) [clone .isra.0]` | [792] | [847] |  |  |  |
| `void tomo::(anonymous namespace)::cmd_geoadd<false>(tomo::Shard&, tomo::Op&)` | [4178] | [4178] |  |  | yes |
| `void tomo::(anonymous namespace)::cmd_geoadd<true>(tomo::Shard&, tomo::Op&)` | [4381] | [4381] |  |  | yes |
| `void tomo::(anonymous namespace)::cmd_zadd_generic<false>(tomo::Shard&, tomo::Op&, bool)` | [6184] | [6184] |  |  | yes |
| `void tomo::(anonymous namespace)::cmd_zadd_generic<true>(tomo::Shard&, tomo::Op&, bool)` | [6283] | [6283] |  |  | yes |
| `void tomo::IoLoop::adopt_client<false, false>(tomo::Client*, bool, bool)` | [965] | [1476] |  |  |  |
| `void tomo::IoLoop::cancel_client_transfer<false>(tomo::Client*)` | [308] | [671] |  |  |  |
| `void tomo::IoLoop::on_recv<false, false, false>(tomo::Client*, int)` | [1364] | [800] |  |  |  |
| `void tomo::IoLoop::on_recv<true, false, false>(tomo::Client*, int)` | [1364] | [816] |  |  |  |
| `void tomo::IoLoop::r7_run_loop<false, false, false, true, false>()` | [5840] | [5933] |  | yes |  |
| `void tomo::IoLoop::r7_run_loop<false, false, true, true, false>()` | [5606] | [5802] |  | yes |  |
| `void tomo::IoLoop::r7_run_loop<false, true, false, true, false>()` | [5884] | [6001] |  | yes |  |
| `void tomo::IoLoop::r7_run_loop<false, true, true, true, false>()` | [5606] | [5802] |  | yes |  |
| `void tomo::IoLoop::r7_run_loop<true, false, false, true, false>()` | [5917] | [6033] |  | yes |  |
| `void tomo::IoLoop::r7_run_loop<true, false, true, true, false>()` | [5606] | [5802] |  | yes |  |
| `void tomo::IoLoop::r7_run_loop<true, true, false, true, false>()` | [5950] | [6058] |  | yes |  |
| `void tomo::IoLoop::r7_run_loop<true, true, true, true, false>()` | [5606] | [5802] |  | yes |  |
| `void tomo::IoLoop::run_loop<false, false, false, false, false>()` | [7170] | [7352] | yes | yes |  |
| `void tomo::IoLoop::run_loop<false, false, false, true, false>()` | [5753] | [5519] | yes | yes |  |
| `void tomo::IoLoop::run_loop<false, false, false, true, true>()` | [7259] | [7448] | yes | yes |  |
| `void tomo::IoLoop::run_loop<false, false, true, false, false>()` | [6205] | [6391] | yes | yes |  |
| `void tomo::IoLoop::run_loop<false, false, true, true, false>()` | [5665] | [5839] | yes | yes |  |
| `void tomo::IoLoop::run_loop<false, false, true, true, true>()` | [6283] | [6466] | yes | yes |  |
| `void tomo::IoLoop::run_loop<false, true, false, false, false>()` | [7608] | [7786] | yes | yes |  |
| `void tomo::IoLoop::run_loop<false, true, false, true, false>()` | [5815] | [5571] | yes | yes |  |
| `void tomo::IoLoop::run_loop<false, true, false, true, true>()` | [7706] | [7916] | yes | yes |  |
| `void tomo::IoLoop::run_loop<false, true, true, false, false>()` | [6205] | [6391] | yes | yes |  |
| `void tomo::IoLoop::run_loop<false, true, true, true, false>()` | [5665] | [5839] | yes | yes |  |
| `void tomo::IoLoop::run_loop<false, true, true, true, true>()` | [6283] | [6466] | yes | yes |  |
| `void tomo::IoLoop::run_loop<true, false, false, false, false>()` | [7671] | [7859] | yes | yes |  |
| `void tomo::IoLoop::run_loop<true, false, false, true, false>()` | [5829] | [5617] | yes | yes |  |
| `void tomo::IoLoop::run_loop<true, false, false, true, true>()` | [7749] | [7940] | yes | yes |  |
| `void tomo::IoLoop::run_loop<true, false, true, false, false>()` | [6237] | [6423] | yes | yes |  |
| `void tomo::IoLoop::run_loop<true, false, true, true, false>()` | [5678] | [5852] | yes | yes |  |
| `void tomo::IoLoop::run_loop<true, false, true, true, true>()` | [6311] | [6493] | yes | yes |  |
| `void tomo::IoLoop::run_loop<true, true, false, false, false>()` | [8069] | [8245] | yes | yes |  |
| `void tomo::IoLoop::run_loop<true, true, false, true, false>()` | [5479] | [5666] | yes | yes |  |
| `void tomo::IoLoop::run_loop<true, true, false, true, true>()` | [8129] | [8340] | yes | yes |  |
| `void tomo::IoLoop::run_loop<true, true, true, false, false>()` | [6237] | [6423] | yes | yes |  |
| `void tomo::IoLoop::run_loop<true, true, true, true, false>()` | [5678] | [5852] | yes | yes |  |
| `void tomo::IoLoop::run_loop<true, true, true, true, true>()` | [6311] | [6493] | yes | yes |  |
| `void tomo::cmd_xshard_only_impl<false>(tomo::Shard&, tomo::Op&)` | [16640] | [16640] | yes |  | yes |
| `void tomo::cmd_xshard_only_impl<true>(tomo::Shard&, tomo::Op&)` | [17797] | [17797] | yes |  | yes |
| `void tomo_db0::(anonymous namespace)::cmd_geoadd<false>(tomo_db0::Shard&, tomo_db0::Op&)` | [4326] | [4326] |  |  | yes |
| `void tomo_db0::(anonymous namespace)::cmd_geoadd<true>(tomo_db0::Shard&, tomo_db0::Op&)` | [4676] | [4676] |  |  | yes |
| `void tomo_db0::(anonymous namespace)::cmd_zadd_generic<false>(tomo_db0::Shard&, tomo_db0::Op&, bool)` | [6200] | [6200] |  |  | yes |
| `void tomo_db0::(anonymous namespace)::cmd_zadd_generic<true>(tomo_db0::Shard&, tomo_db0::Op&, bool)` | [6283] | [6283] |  |  | yes |
| `void tomo_db0::IoLoop::adopt_client<false, false>(tomo_db0::Client*, bool, bool)` | [965] | [1476] |  |  |  |
| `void tomo_db0::IoLoop::cancel_client_transfer<false>(tomo_db0::Client*)` | [308] | [671] |  |  |  |
| `void tomo_db0::IoLoop::on_recv<false, false, false>(tomo_db0::Client*, int)` | [1364] | [800] |  |  |  |
| `void tomo_db0::IoLoop::on_recv<true, false, false>(tomo_db0::Client*, int)` | [1364] | [816] |  |  |  |
| `void tomo_db0::IoLoop::r7_run_loop<false, false, false, true, false>()` | [5985] | [5771] |  | yes |  |
| `void tomo_db0::IoLoop::r7_run_loop<false, false, true, true, false>()` | [5481] | [5566] |  | yes |  |
| `void tomo_db0::IoLoop::r7_run_loop<false, true, false, true, false>()` | [6018] | [5808] |  | yes |  |
| `void tomo_db0::IoLoop::r7_run_loop<false, true, true, true, false>()` | [5481] | [5566] |  | yes |  |
| `void tomo_db0::IoLoop::r7_run_loop<true, false, false, true, false>()` | [6051] | [5833] |  | yes |  |
| `void tomo_db0::IoLoop::r7_run_loop<true, false, true, true, false>()` | [5478] | [5566] |  | yes |  |
| `void tomo_db0::IoLoop::r7_run_loop<true, true, false, true, false>()` | [6097] | [5870] |  | yes |  |
| `void tomo_db0::IoLoop::r7_run_loop<true, true, true, true, false>()` | [5478] | [5566] |  | yes |  |
| `void tomo_db0::IoLoop::run_loop<false, false, false, false, false>()` | [6918] | [7019] | yes | yes |  |
| `void tomo_db0::IoLoop::run_loop<false, false, false, true, false>()` | [5704] | [5632] | yes | yes |  |
| `void tomo_db0::IoLoop::run_loop<false, false, false, true, true>()` | [7029] | [7093] | yes | yes |  |
| `void tomo_db0::IoLoop::run_loop<false, false, true, false, false>()` | [5951] | [6043] | yes | yes |  |
| `void tomo_db0::IoLoop::run_loop<false, false, true, true, false>()` | [5626] | [5717] | yes | yes |  |
| `void tomo_db0::IoLoop::run_loop<false, false, true, true, true>()` | [5998] | [6090] | yes | yes |  |
| `void tomo_db0::IoLoop::run_loop<false, true, false, false, false>()` | [7347] | [7462] | yes | yes |  |
| `void tomo_db0::IoLoop::run_loop<false, true, false, true, false>()` | [5760] | [5693] | yes | yes |  |
| `void tomo_db0::IoLoop::run_loop<false, true, false, true, true>()` | [7453] | [7532] | yes | yes |  |
| `void tomo_db0::IoLoop::run_loop<false, true, true, false, false>()` | [5951] | [6043] | yes | yes |  |
| `void tomo_db0::IoLoop::run_loop<false, true, true, true, false>()` | [5626] | [5717] | yes | yes |  |
| `void tomo_db0::IoLoop::run_loop<false, true, true, true, true>()` | [5998] | [6090] | yes | yes |  |
| `void tomo_db0::IoLoop::run_loop<true, false, false, false, false>()` | [7400] | [7493] | yes | yes |  |
| `void tomo_db0::IoLoop::run_loop<true, false, false, true, false>()` | [5622] | [5710] | yes | yes |  |
| `void tomo_db0::IoLoop::run_loop<true, false, false, true, true>()` | [7508] | [7592] | yes | yes |  |
| `void tomo_db0::IoLoop::run_loop<true, false, true, false, false>()` | [5983] | [6075] | yes | yes |  |
| `void tomo_db0::IoLoop::run_loop<true, false, true, true, false>()` | [5639] | [5581] | yes | yes |  |
| `void tomo_db0::IoLoop::run_loop<true, false, true, true, true>()` | [6042] | [6134] | yes | yes |  |
| `void tomo_db0::IoLoop::run_loop<true, true, false, false, false>()` | [7793] | [7889] | yes | yes |  |
| `void tomo_db0::IoLoop::run_loop<true, true, false, true, false>()` | [5668] | [5757] | yes | yes |  |
| `void tomo_db0::IoLoop::run_loop<true, true, false, true, true>()` | [7900] | [7974] | yes | yes |  |
| `void tomo_db0::IoLoop::run_loop<true, true, true, false, false>()` | [5983] | [6075] | yes | yes |  |
| `void tomo_db0::IoLoop::run_loop<true, true, true, true, false>()` | [5639] | [5726] | yes | yes |  |
| `void tomo_db0::IoLoop::run_loop<true, true, true, true, true>()` | [6042] | [6134] | yes | yes |  |
| `void tomo_db0::cmd_xshard_only_impl<false>(tomo_db0::Shard&, tomo_db0::Op&)` | [16757] | [16757] | yes |  | yes |
| `void tomo_db0::cmd_xshard_only_impl<true>(tomo_db0::Shard&, tomo_db0::Op&)` | [18094] | [18094] | yes |  | yes |
