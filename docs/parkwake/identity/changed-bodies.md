# Linked body differences, PRE vs POST

Strict gate normalizer (docs/wave9/identity.py, tools/wave12_normalize.py). Identity is a proxy.

| Function group | PRE bytes | POST bytes | Hot | Intended | Data displacement only |
|---|---|---|---|---|---|
| `bool tomo::ExLoopT<false>::execute<false, false>(tomo::Task const&)` | [4127] | [4126] | yes | yes |  |
| `bool tomo::ExLoopT<false>::execute_latency<false, false>(tomo::Task const&)` | [2987] | [2989] | yes | yes |  |
| `bool tomo::ExLoopT<false>::execute_timed<false, false>(tomo::Task const&)` | [3034] | [3036] | yes | yes |  |
| `bool tomo::ExLoopT<true>::execute<false, false>(tomo::Task const&)` | [4107] | [4109] | yes | yes |  |
| `bool tomo::ExLoopT<true>::execute<false, true>(tomo::Task const&)` | [3960] | [3960] | yes | yes |  |
| `bool tomo::ExLoopT<true>::execute<true, false>(tomo::Task const&)` | [4107] | [4109] | yes | yes |  |
| `bool tomo::ExLoopT<true>::execute<true, true>(tomo::Task const&)` | [3960] | [3960] | yes | yes |  |
| `bool tomo::ExLoopT<true>::execute_latency<false, false>(tomo::Task const&)` | [3305] | [3297] | yes | yes |  |
| `bool tomo::ExLoopT<true>::execute_latency<false, true>(tomo::Task const&)` | [3124] | [3140] | yes | yes |  |
| `bool tomo::ExLoopT<true>::execute_latency<true, false>(tomo::Task const&)` | [3305] | [3297] | yes | yes |  |
| `bool tomo::ExLoopT<true>::execute_latency<true, true>(tomo::Task const&)` | [3124] | [3140] | yes | yes |  |
| `bool tomo::ExLoopT<true>::execute_timed<false, false>(tomo::Task const&)` | [3325] | [3317] | yes | yes |  |
| `bool tomo::ExLoopT<true>::execute_timed<false, true>(tomo::Task const&)` | [3160] | [3175] | yes | yes |  |
| `bool tomo::ExLoopT<true>::execute_timed<true, false>(tomo::Task const&)` | [3325] | [3317] | yes | yes |  |
| `bool tomo::ExLoopT<true>::execute_timed<true, true>(tomo::Task const&)` | [3160] | [3175] | yes | yes |  |
| `bool tomo::ExLoopT<true>::service_txn_boundary<true>()` | [2793] | [2443] |  |  |  |
| `bool tomo::IoLoop::finish_client_transfer<false>(tomo::Client*) [clone .isra.0]` | [913, 338, 656, 357] | [357, 338, 357, 357] |  |  |  |
| `bool tomo::IoLoop::finish_client_transfer<false>(tomo::Client*) [clone .isra.0] [clone .cold]` | [40, 40, 40, 40] | [40, 40, 40, 40] |  |  |  |
| `bool tomo_db0::ExLoopT<false>::execute<false, false>(tomo_db0::Task const&)` | [4224] | [4224] | yes | yes |  |
| `bool tomo_db0::ExLoopT<false>::execute_latency<false, false>(tomo_db0::Task const&)` | [2986] | [2988] | yes | yes |  |
| `bool tomo_db0::ExLoopT<false>::execute_timed<false, false>(tomo_db0::Task const&)` | [3033] | [3035] | yes | yes |  |
| `bool tomo_db0::ExLoopT<true>::execute<false, false>(tomo_db0::Task const&)` | [4107] | [4109] | yes | yes |  |
| `bool tomo_db0::ExLoopT<true>::execute<false, true>(tomo_db0::Task const&)` | [3960] | [3960] | yes | yes |  |
| `bool tomo_db0::ExLoopT<true>::execute<true, false>(tomo_db0::Task const&)` | [4107] | [4109] | yes | yes |  |
| `bool tomo_db0::ExLoopT<true>::execute<true, true>(tomo_db0::Task const&)` | [3960] | [3960] | yes | yes |  |
| `bool tomo_db0::ExLoopT<true>::execute_latency<false, false>(tomo_db0::Task const&)` | [3304] | [3296] | yes | yes |  |
| `bool tomo_db0::ExLoopT<true>::execute_latency<false, true>(tomo_db0::Task const&)` | [3123] | [3139] | yes | yes |  |
| `bool tomo_db0::ExLoopT<true>::execute_latency<true, false>(tomo_db0::Task const&)` | [3304] | [3296] | yes | yes |  |
| `bool tomo_db0::ExLoopT<true>::execute_latency<true, true>(tomo_db0::Task const&)` | [3123] | [3139] | yes | yes |  |
| `bool tomo_db0::ExLoopT<true>::execute_timed<false, false>(tomo_db0::Task const&)` | [3324] | [3316] | yes | yes |  |
| `bool tomo_db0::ExLoopT<true>::execute_timed<false, true>(tomo_db0::Task const&)` | [3159] | [3174] | yes | yes |  |
| `bool tomo_db0::ExLoopT<true>::execute_timed<true, false>(tomo_db0::Task const&)` | [3324] | [3316] | yes | yes |  |
| `bool tomo_db0::ExLoopT<true>::execute_timed<true, true>(tomo_db0::Task const&)` | [3159] | [3174] | yes | yes |  |
| `bool tomo_db0::IoLoop::finish_client_transfer<false>(tomo_db0::Client*) [clone .isra.0]` | [1103, 338, 1103, 357] | [357, 338, 357, 357] |  |  |  |
| `bool tomo_db0::IoLoop::finish_client_transfer<false>(tomo_db0::Client*) [clone .isra.0] [clone .cold]` | [40, 40, 40, 40] | [40, 40, 40, 40] |  |  |  |
| `int tomo_db0::Ring::submit_and_wait<false>(unsigned int, unsigned int, int) [clone .isra.0]` | [339] | [339, 339] |  |  |  |
| `json_append_data` | [1980] | [1980] |  |  | yes |
| `main` | [8826] | [8845] |  |  |  |
| `main.cold` | [5709] | [5709] |  |  |  |
| `math_random` | [404] | [404] |  |  | yes |
| `mp_decode_to_lua_type.part.0` | [1446] | [1446] |  |  | yes |
| `std::vector<tomo::Client*, std::allocator<tomo::Client*> >::resize(unsigned long)` | [] | [469] |  |  |  |
| `std::vector<tomo_db0::Client*, std::allocator<tomo_db0::Client*> >::resize(unsigned long)` | [] | [469] |  |  |  |
| `tomo::(anonymous namespace)::blocking_notify_sender(tomo::Server&, tomo::ThreadCtx&, tomo::Ring&, tomo::Client*)` | [495] | [533] |  | yes |  |
| `tomo::(anonymous namespace)::blocking_notify_sender(tomo::Server&, tomo::ThreadCtx&, tomo::Ring&, tomo::Client*) [clone .cold]` | [] | [62] |  | yes |  |
| `tomo::(anonymous namespace)::cmd_info(tomo::Shard&, tomo::Op&)` | [17588] | [17588] |  |  | yes |
| `tomo::(anonymous namespace)::command_key_args(tomo::MultiQueuedCommand const&, std::vector<unsigned int, std::allocator<unsigned int> >&)` | [1805] | [1805] |  |  | yes |
| `tomo::(anonymous namespace)::execute_plain_element_mover(tomo::Task const&, tomo::Shard&, tomo::Op&) [clone .isra.0]` | [2707] | [2707] |  |  | yes |
| `tomo::(anonymous namespace)::free_state_contents(tomo::ScatterState&) [clone .part.0]` | [1045] | [1029] |  |  |  |
| `tomo::(anonymous namespace)::geo_encode(double, double)` | [168] | [168] |  |  | yes |
| `tomo::(anonymous namespace)::geohashDecode(tomo::(anonymous namespace)::GeoHashRange, tomo::(anonymous namespace)::GeoHashRange, tomo::(anonymous namespace)::GeoHashBits, tomo::(anonymous namespace)::GeoHashArea*) [clone .constprop.0] [clone .isra.0]` | [314] | [314] |  |  | yes |
| `tomo::(anonymous namespace)::geohashEncode(tomo::(anonymous namespace)::GeoHashRange const*, tomo::(anonymous namespace)::GeoHashRange const*, double, double, unsigned char, tomo::(anonymous namespace)::GeoHashBits*) [clone .constprop.0] [clone .isra.0]` | [334] | [334] |  |  | yes |
| `tomo::(anonymous namespace)::parse_search(tomo::Op&, tomo::(anonymous namespace)::GeoSearchOptions&, std::vector<tomo::ZsetEntry, std::allocator<tomo::ZsetEntry> > const&)::{lambda(unsigned int)#1}::operator()(unsigned int) const` | [358] | [358] |  |  | yes |
| `tomo::(anonymous namespace)::parse_zset_operation(tomo::Op&, tomo::(anonymous namespace)::Kind, unsigned int&, std::vector<double, std::allocator<double> >&, tomo::(anonymous namespace)::ZAggregate&, bool&, unsigned long&) [clone .constprop.0]` | [2324] | [2324] |  |  | yes |
| `tomo::(anonymous namespace)::prepare_commands(tomo::Server&, tomo::MultiExecState&, std::vector<tomo::MultiQueuedCommand, std::allocator<tomo::MultiQueuedCommand> >&)` | [11691] | [11691] |  |  | yes |
| `tomo::(anonymous namespace)::script_random(lua_State*)` | [475] | [475] |  |  | yes |
| `tomo::(anonymous namespace)::store_xstring_selected(bool, tomo::Shard&, tomo::Slice, unsigned long, tomo::Slice, long, bool, bool)` | [181] | [181] |  |  | yes |
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
| `tomo::ExLoopT<false>::run()` | [9256] | [9544] | yes | yes |  |
| `tomo::ExLoopT<false>::service_notify_retries()` | [] | [174] |  | yes |  |
| `tomo::ExLoopT<true>::flip_control_pass()` | [1193] | [1174] |  | yes |  |
| `tomo::ExLoopT<true>::flip_quiesced() const` | [562] | [588] |  | yes |  |
| `tomo::ExLoopT<true>::notify_sender_to(tomo::Client*, unsigned int)` | [355] | [865] |  | yes |  |
| `tomo::ExLoopT<true>::run()` | [8936] | [9236] | yes | yes |  |
| `tomo::ExLoopT<true>::service_notify_retries()` | [] | [174] |  | yes |  |
| `tomo::FlipController::debug_dump[abi:cxx11]() const` | [6458] | [6458] |  |  | yes |
| `tomo::FlipController::seek_after_reading(tomo::Server&, unsigned int, unsigned long, double)` | [1281] | [1281] |  |  | yes |
| `tomo::IoLoop::DispatchResult tomo::IoLoop::parse_and_dispatch<false, 0u, false>(tomo::Client*)` | [12146] | [12084] | yes |  |  |
| `tomo::IoLoop::DispatchResult tomo::IoLoop::parse_and_dispatch<false, 32u, true>(tomo::Client*)` | [19214] | [19246] | yes |  |  |
| `tomo::IoLoop::DispatchResult tomo::IoLoop::parse_and_dispatch<true, 0u, false>(tomo::Client*) [clone .isra.0]` | [9929, 10298, 9912, 11140] | [9929, 10298, 9912, 10811] | yes |  |  |
| `tomo::IoLoop::DispatchResult tomo::IoLoop::parse_and_dispatch<true, 0u, false>(tomo::Client*) [clone .isra.0] [clone .cold]` | [526, 611, 522, 596] | [526, 611, 522, 600] | yes |  |  |
| `tomo::IoLoop::climon_copy_client_filter(tomo::PubSubEvent&, tomo::PubSubEvent const&)` | [383] | [380] |  |  |  |
| `tomo::IoLoop::climon_monitor_stop(tomo::Client*, unsigned long)` | [345] | [181] |  |  |  |
| `tomo::IoLoop::climon_start_client_command(tomo::Client*, tomo::Op&)` | [1779] | [1789] |  | yes |  |
| `tomo::IoLoop::climon_start_client_kill(tomo::Client*, tomo::Op&)` | [2634] | [2463] |  |  |  |
| `tomo::IoLoop::climon_start_client_kill(tomo::Client*, tomo::Op&) [clone .cold]` | [378] | [378] |  |  |  |
| `tomo::IoLoop::database_control_pass()` | [1066] | [1132] |  | yes |  |
| `tomo::IoLoop::lb_control_pass()` | [3954] | [4015] |  | yes |  |
| `tomo::IoLoop::reap_dead()` | [1740] | [1239] |  |  |  |
| `tomo::LbAutotune::KeyDamping::update(double, tomo::LbAutotune::QuietJitter&, unsigned int&, unsigned int, int, unsigned long, unsigned long, unsigned long)` | [957] | [957] |  |  | yes |
| `tomo::LbAutotune::QuietJitter::band(unsigned int) const [clone .isra.0]` | [167] | [167] |  |  | yes |
| `tomo::MultiExecState::~MultiExecState()` | [2047] | [2031] |  |  |  |
| `tomo::PubSubEvent::~PubSubEvent()` | [603] | [603] |  |  |  |
| `tomo::Ring::msg_to(tomo::Ring&, unsigned long) [clone .isra.0]` | [653, 653, 979] | [653, 653, 653, 979] |  |  |  |
| `tomo::Ring::msg_to(tomo::Ring&, unsigned long) [clone .isra.0] [clone .cold]` | [40, 40, 40] | [40, 40, 40, 40] |  |  |  |
| `tomo::Server::defer_completion_notice(unsigned int, tomo::Client*)` | [] | [531] |  | yes |  |
| `tomo::Server::lb_controller_tick(unsigned int, unsigned long)::{lambda(double, tomo::LbAutotune::QuietJitter&, unsigned int&, unsigned int)#1}::operator()(double, tomo::LbAutotune::QuietJitter&, unsigned int&, unsigned int) const` | [559] | [559] |  |  | yes |
| `tomo::Server::lb_controller_tick_pad(unsigned int, unsigned long)::{lambda(double, tomo::LbAutotune::QuietJitter&, unsigned int&, unsigned int)#1}::operator()(double, tomo::LbAutotune::QuietJitter&, unsigned int&, unsigned int) const` | [559] | [559] |  |  | yes |
| `tomo::Server::lb_debug_move_client(unsigned long, unsigned int, std::__cxx11::basic_string<char, std::char_traits<char>, std::allocator<char> >&)` | [724] | [782] |  | yes |  |
| `tomo::Server::monitor_controllers()` | [921] | [1459] |  | yes |  |
| `tomo::Server::monitor_controllers() [clone .cold]` | [] | [45] |  | yes |  |
| `tomo::Server::monitor_controllers()::{lambda(unsigned int)#1}::operator()(unsigned int) const` | [] | [1291] |  | yes |  |
| `tomo::Server::monitor_controllers()::{lambda(unsigned int)#1}::operator()(unsigned int) const [clone .cold]` | [] | [22] |  | yes |  |
| `tomo::Server::~Server()` | [2281] | [2329] |  |  |  |
| `tomo::auth_dispatch_entry(tomo::IoLoop&, tomo::Client&, tomo::Op&, unsigned int)` | [1191] | [1287] |  |  |  |
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
| `tomo::multi_execute_task(tomo::Server&, tomo::Task const&, tomo::Shard&, unsigned int, unsigned int, tomo::AofOwnerContext*, tomo::MultiRetryPromoter const*)` | [9532] | [9538] |  | yes |  |
| `tomo::multi_execute_task_tracked(tomo::Server&, tomo::Task const&, tomo::Shard&, unsigned int, unsigned int, tomo::AofOwnerContext*, tomo::MultiRetryPromoter const*)` | [8228] | [8237] |  | yes |  |
| `tomo::multi_retire(tomo::Client&, tomo::Op&, std::vector<tomo::MultiExecState*, std::allocator<tomo::MultiExecState*> >&)` | [2057] | [2060] |  | yes |  |
| `tomo::multi_retry_lane_note_pending()` | [] | [14] |  | yes |  |
| `tomo::multidb_flush(tomo::Shard&, unsigned char) [clone .cold]` | [67] | [67] |  |  |  |
| `tomo::notify_record_slow(tomo::Shard&, tomo::Op&, unsigned int, unsigned int, tomo::NotifyEventId, tomo::Slice)` | [2169] | [2169] |  |  | yes |
| `tomo::notify_reserve_chain(tomo::Server&, std::unique_ptr<tomo::PubSubNotificationChain, std::default_delete<tomo::PubSubNotificationChain> >, std::shared_ptr<tomo::NotifyExpiryCompletion>)` | [476] | [507] |  |  |  |
| `tomo::notify_reserve_chain(tomo::Server&, std::unique_ptr<tomo::PubSubNotificationChain, std::default_delete<tomo::PubSubNotificationChain> >, std::shared_ptr<tomo::NotifyExpiryCompletion>) [clone .cold]` | [267] | [267] |  |  |  |
| `tomo::parse_double_strict(tomo::Slice, double&)` | [487] | [487] |  |  | yes |
| `tomo::redis_double_text(char*, unsigned long, double) [clone .isra.0]` | [1043, 1043, 1043, 1043, 1043] | [1043, 1043, 1043, 1043, 1043] |  |  | yes |
| `tomo::stream_parse_xreadgroup(tomo::Op&, tomo::StreamXreadGroupArgs&)` | [1169] | [1169] |  |  | yes |
| `tomo::xshard_multi_child_complete(tomo::ScatterState&, tomo::Op&, unsigned int)` | [743] | [768] |  |  |  |
| `tomo_db0::(anonymous namespace)::blocking_notify_sender(tomo_db0::Server&, tomo_db0::ThreadCtx&, tomo_db0::Ring&, tomo_db0::Client*)` | [495] | [932] |  | yes |  |
| `tomo_db0::(anonymous namespace)::blocking_notify_sender(tomo_db0::Server&, tomo_db0::ThreadCtx&, tomo_db0::Ring&, tomo_db0::Client*) [clone .cold]` | [] | [62] |  | yes |  |
| `tomo_db0::(anonymous namespace)::classify_keys(tomo_db0::Op const&, tomo_db0::(anonymous namespace)::Kind, tomo_db0::(anonymous namespace)::XshardKeyHints const&, tomo_db0::(anonymous namespace)::XshardKeyPlan&)` | [945] | [961] |  |  |  |
| `tomo_db0::(anonymous namespace)::cmd_info(tomo_db0::Shard&, tomo_db0::Op&)` | [17336] | [17336] |  |  | yes |
| `tomo_db0::(anonymous namespace)::command_key_args(tomo_db0::MultiQueuedCommand const&, std::vector<unsigned int, std::allocator<unsigned int> >&)` | [2404] | [2404] |  |  | yes |
| `tomo_db0::(anonymous namespace)::execute_plain_element_mover(tomo_db0::Task const&, tomo_db0::Shard&, tomo_db0::Op&) [clone .isra.0]` | [3494] | [3494] |  |  | yes |
| `tomo_db0::(anonymous namespace)::geo_encode(double, double)` | [168] | [168] |  |  | yes |
| `tomo_db0::(anonymous namespace)::geohashDecode(tomo_db0::(anonymous namespace)::GeoHashRange, tomo_db0::(anonymous namespace)::GeoHashRange, tomo_db0::(anonymous namespace)::GeoHashBits, tomo_db0::(anonymous namespace)::GeoHashArea*) [clone .constprop.0] [clone .isra.0]` | [314] | [314] |  |  | yes |
| `tomo_db0::(anonymous namespace)::geohashEncode(tomo_db0::(anonymous namespace)::GeoHashRange const*, tomo_db0::(anonymous namespace)::GeoHashRange const*, double, double, unsigned char, tomo_db0::(anonymous namespace)::GeoHashBits*) [clone .constprop.0] [clone .isra.0]` | [334] | [334] |  |  | yes |
| `tomo_db0::(anonymous namespace)::parse_search(tomo_db0::Op&, tomo_db0::(anonymous namespace)::GeoSearchOptions&, std::vector<tomo_db0::ZsetEntry, std::allocator<tomo_db0::ZsetEntry> > const&)::{lambda(unsigned int)#1}::operator()(unsigned int) const` | [358] | [358] |  |  | yes |
| `tomo_db0::(anonymous namespace)::parse_zset_operation(tomo_db0::Op&, tomo_db0::(anonymous namespace)::Kind, unsigned int&, std::vector<double, std::allocator<double> >&, tomo_db0::(anonymous namespace)::ZAggregate&, bool&, unsigned long&) [clone .constprop.0]` | [2349] | [2349] |  |  | yes |
| `tomo_db0::(anonymous namespace)::prepare_commands(tomo_db0::Server&, tomo_db0::MultiExecState&, std::vector<tomo_db0::MultiQueuedCommand, std::allocator<tomo_db0::MultiQueuedCommand> >&)` | [13197] | [13197] |  |  | yes |
| `tomo_db0::(anonymous namespace)::script_random(lua_State*)` | [509] | [509] |  |  | yes |
| `tomo_db0::(anonymous namespace)::store_xstring_selected(bool, tomo_db0::Shard&, tomo_db0::Slice, unsigned long, tomo_db0::Slice, long, bool, bool)` | [181] | [181] |  |  | yes |
| `tomo_db0::DatabaseMap::drain_deadline_start(tomo_db0::Server&, unsigned long, unsigned long)` | [] | [313] |  | yes |  |
| `tomo_db0::DatabaseMap::note_drain_waiting()` | [] | [5] |  | yes |  |
| `tomo_db0::DatabaseMap::publish(std::unique_ptr<tomo_db0::DatabaseMap::Map, std::default_delete<tomo_db0::DatabaseMap::Map> >)` | [498] | [498] |  |  |  |
| `tomo_db0::DatabaseMap::state()` | [341] | [325] |  |  |  |
| `tomo_db0::DatabaseMap::~DatabaseMap()` | [229] | [229] |  |  |  |
| `tomo_db0::DebugSleepCoordinator<128u, 50u>::exclusive(unsigned int, unsigned int, void*, void (*)(void*, unsigned int))` | [575] | [] |  | yes |  |
| `tomo_db0::ExLoopT<false>::flip_quiesced() const` | [656] | [684] |  | yes |  |
| `tomo_db0::ExLoopT<false>::notify_sender_to(tomo_db0::Client*, unsigned int)` | [355] | [865] |  | yes |  |
| `tomo_db0::ExLoopT<false>::run()` | [9046] | [9158] | yes | yes |  |
| `tomo_db0::ExLoopT<false>::service_notify_retries()` | [] | [174] |  | yes |  |
| `tomo_db0::ExLoopT<true>::flip_quiesced() const` | [704] | [704] |  | yes |  |
| `tomo_db0::ExLoopT<true>::notify_sender_to(tomo_db0::Client*, unsigned int)` | [355] | [865] |  | yes |  |
| `tomo_db0::ExLoopT<true>::run()` | [8666] | [8785] | yes | yes |  |
| `tomo_db0::ExLoopT<true>::service_notify_retries()` | [] | [174] |  | yes |  |
| `tomo_db0::FlatStore::atomic_tripwire_ticket(unsigned long, tomo_db0::Slice) const [clone .isra.0]` | [837] | [784] |  |  |  |
| `tomo_db0::FlipController::debug_dump[abi:cxx11]() const` | [6458] | [6458] |  |  | yes |
| `tomo_db0::FlipController::seek_after_reading(tomo_db0::Server&, unsigned int, unsigned long, double)` | [1281] | [1281] |  |  | yes |
| `tomo_db0::IoLoop::DispatchResult tomo_db0::IoLoop::parse_and_dispatch<false, 32u, false>(tomo_db0::Client*) [clone .isra.0]` | [19203] | [19203] | yes |  |  |
| `tomo_db0::IoLoop::DispatchResult tomo_db0::IoLoop::parse_and_dispatch<false, 32u, true>(tomo_db0::Client*)` | [19998] | [19998] | yes |  |  |
| `tomo_db0::IoLoop::DispatchResult tomo_db0::IoLoop::parse_and_dispatch<true, 0u, false>(tomo_db0::Client*) [clone .isra.0]` | [9804, 11407, 9804, 11067] | [9804, 11372, 9804, 10897] | yes |  |  |
| `tomo_db0::IoLoop::DispatchResult tomo_db0::IoLoop::parse_and_dispatch<true, 0u, false>(tomo_db0::Client*) [clone .isra.0] [clone .cold]` | [525, 592, 525, 596] | [525, 599, 525, 592] | yes |  |  |
| `tomo_db0::IoLoop::DispatchResult tomo_db0::IoLoop::parse_and_dispatch<true, 32u, false>(tomo_db0::Client*) [clone .isra.0]` | [19168, 18673] | [19168, 18673] | yes |  |  |
| `tomo_db0::IoLoop::DispatchResult tomo_db0::IoLoop::parse_and_dispatch<true, 32u, true>(tomo_db0::Client*)` | [20014] | [20014] | yes |  |  |
| `tomo_db0::IoLoop::climon_copy_client_filter(tomo_db0::PubSubEvent&, tomo_db0::PubSubEvent const&)` | [639] | [383] |  |  |  |
| `tomo_db0::IoLoop::climon_start_client_command(tomo_db0::Client*, tomo_db0::Op&)` | [1779] | [1789] |  | yes |  |
| `tomo_db0::IoLoop::lb_control_pass()` | [4983] | [5048] |  | yes |  |
| `tomo_db0::IoLoop::reap_dead()` | [1740] | [1239] |  |  |  |
| `tomo_db0::LbAutotune::KeyDamping::update(double, tomo_db0::LbAutotune::QuietJitter&, unsigned int&, unsigned int, int, unsigned long, unsigned long, unsigned long)` | [957] | [957] |  |  | yes |
| `tomo_db0::LbAutotune::QuietJitter::band(unsigned int) const [clone .isra.0]` | [167] | [167] |  |  | yes |
| `tomo_db0::MonitorScriptLine* std::__move_merge<__gnu_cxx::__normal_iterator<tomo_db0::MonitorScriptLine*, std::vector<tomo_db0::MonitorScriptLine, std::allocator<tomo_db0::MonitorScriptLine> > >, tomo_db0::MonitorScriptLine*, __gnu_cxx::__ops::_Iter_comp_iter<tomo_db0::IoLoop::climon_monitor_script_deliver(unsigned long, std::vector<tomo_db0::MonitorScriptLine, std::allocator<tomo_db0::MonitorScriptLine> >&)::{lambda(auto:1 const&, auto:2 const&)#1}> >(__gnu_cxx::__normal_iterator<tomo_db0::MonitorScriptLine*, std::vector<tomo_db0::MonitorScriptLine, std::allocator<tomo_db0::MonitorScriptLine> > >, __gnu_cxx::__normal_iterator<tomo_db0::MonitorScriptLine*, std::vector<tomo_db0::MonitorScriptLine, std::allocator<tomo_db0::MonitorScriptLine> > >, __gnu_cxx::__normal_iterator<tomo_db0::MonitorScriptLine*, std::vector<tomo_db0::MonitorScriptLine, std::allocator<tomo_db0::MonitorScriptLine> > >, __gnu_cxx::__normal_iterator<tomo_db0::MonitorScriptLine*, std::vector<tomo_db0::MonitorScriptLine, std::allocator<tomo_db0::MonitorScriptLine> > >, tomo_db0::MonitorScriptLine*, __gnu_cxx::__ops::_Iter_comp_iter<tomo_db0::IoLoop::climon_monitor_script_deliver(unsigned long, std::vector<tomo_db0::MonitorScriptLine, std::allocator<tomo_db0::MonitorScriptLine> >&)::{lambda(auto:1 const&, auto:2 const&)#1}>) [clone .isra.0]` | [1016] | [1000] |  |  |  |
| `tomo_db0::Ring::msg_to(tomo_db0::Ring&, unsigned long) [clone .isra.0]` | [653, 653, 979] | [653, 653, 653, 979] |  |  |  |
| `tomo_db0::Ring::msg_to(tomo_db0::Ring&, unsigned long) [clone .isra.0] [clone .cold]` | [40, 40, 40] | [40, 40, 40, 40] |  |  |  |
| `tomo_db0::Server::defer_completion_notice(unsigned int, tomo_db0::Client*)` | [] | [531] |  | yes |  |
| `tomo_db0::Server::flip_begin(unsigned int, unsigned int, unsigned int, std::__cxx11::basic_string<char, std::char_traits<char>, std::allocator<char> >&, unsigned long)` | [6307] | [6311] |  |  |  |
| `tomo_db0::Server::lb_controller_tick(unsigned int, unsigned long)::{lambda(double, tomo_db0::LbAutotune::QuietJitter&, unsigned int&, unsigned int)#1}::operator()(double, tomo_db0::LbAutotune::QuietJitter&, unsigned int&, unsigned int) const` | [559] | [559] |  |  | yes |
| `tomo_db0::Server::lb_controller_tick_pad(unsigned int, unsigned long)::{lambda(double, tomo_db0::LbAutotune::QuietJitter&, unsigned int&, unsigned int)#1}::operator()(double, tomo_db0::LbAutotune::QuietJitter&, unsigned int&, unsigned int) const` | [559] | [559] |  |  | yes |
| `tomo_db0::Server::lb_debug_move_client(unsigned long, unsigned int, std::__cxx11::basic_string<char, std::char_traits<char>, std::allocator<char> >&)` | [721] | [779] |  | yes |  |
| `tomo_db0::Server::monitor_controllers()` | [925] | [1442] |  | yes |  |
| `tomo_db0::Server::monitor_controllers() [clone .cold]` | [] | [44] |  | yes |  |
| `tomo_db0::Server::monitor_controllers()::{lambda(unsigned int)#1}::operator()(unsigned int) const` | [] | [1291] |  | yes |  |
| `tomo_db0::Server::monitor_controllers()::{lambda(unsigned int)#1}::operator()(unsigned int) const [clone .cold]` | [] | [22] |  | yes |  |
| `tomo_db0::Server::~Server()` | [2376] | [2440] |  |  |  |
| `tomo_db0::cfgfix_rebind(tomo_db0::Server&, unsigned int, unsigned short, std::__cxx11::basic_string<char, std::char_traits<char>, std::allocator<char> > const&, std::__cxx11::basic_string<char, std::char_traits<char>, std::allocator<char> >&, int)` | [3428] | [4086] |  | yes |  |
| `tomo_db0::cfgfix_rebind(tomo_db0::Server&, unsigned int, unsigned short, std::__cxx11::basic_string<char, std::char_traits<char>, std::allocator<char> > const&, std::__cxx11::basic_string<char, std::char_traits<char>, std::allocator<char> >&, int) [clone .cold]` | [108] | [215] |  | yes |  |
| `tomo_db0::cfgfix_rebind(tomo_db0::Server&, unsigned int, unsigned short, std::__cxx11::basic_string<char, std::char_traits<char>, std::allocator<char> > const&, std::__cxx11::basic_string<char, std::char_traits<char>, std::allocator<char> >&, int)::{lambda(void*, unsigned int)#1}::_FUN(void*, unsigned int)` | [] | [292] |  | yes |  |
| `tomo_db0::command_client_pause(tomo_db0::Server&, tomo_db0::Op&, unsigned long)` | [808] | [] |  | yes |  |
| `tomo_db0::command_client_pause(tomo_db0::Server&, tomo_db0::Op&, unsigned long) [clone .cold]` | [128] | [] |  | yes |  |
| `tomo_db0::command_client_pause(tomo_db0::Server&, tomo_db0::Op&, unsigned long, unsigned int)` | [] | [1019] |  | yes |  |
| `tomo_db0::command_client_pause(tomo_db0::Server&, tomo_db0::Op&, unsigned long, unsigned int) [clone .cold]` | [] | [128] |  | yes |  |
| `tomo_db0::dtoa::grisu2_digits(double, char*, int&)` | [1043] | [1043] |  |  | yes |
| `tomo_db0::info_stats_build_fields(std::__cxx11::basic_string<char, std::char_traits<char>, std::allocator<char> >&)` | [981] | [981] |  |  | yes |
| `tomo_db0::multi_exec_io_commands(tomo_db0::IoLoop&, tomo_db0::MultiExecState&)` | [2562] | [2562] |  | yes |  |
| `tomo_db0::multi_exec_io_commands(tomo_db0::IoLoop&, tomo_db0::MultiExecState&) [clone .cold]` | [222] | [222] |  | yes |  |
| `tomo_db0::multi_execute_task(tomo_db0::Server&, tomo_db0::Task const&, tomo_db0::Shard&, unsigned int, unsigned int, tomo_db0::AofOwnerContext*, tomo_db0::MultiRetryPromoter const*)` | [9403] | [9235] |  | yes |  |
| `tomo_db0::multi_execute_task(tomo_db0::Server&, tomo_db0::Task const&, tomo_db0::Shard&, unsigned int, unsigned int, tomo_db0::AofOwnerContext*, tomo_db0::MultiRetryPromoter const*) [clone .cold]` | [382] | [383] |  | yes |  |
| `tomo_db0::multi_execute_task_tracked(tomo_db0::Server&, tomo_db0::Task const&, tomo_db0::Shard&, unsigned int, unsigned int, tomo_db0::AofOwnerContext*, tomo_db0::MultiRetryPromoter const*)` | [8303] | [8312] |  | yes |  |
| `tomo_db0::multi_retire(tomo_db0::Client&, tomo_db0::Op&, std::vector<tomo_db0::MultiExecState*, std::allocator<tomo_db0::MultiExecState*> >&)` | [2095] | [2098] |  | yes |  |
| `tomo_db0::multi_retry_lane_note_pending()` | [] | [14] |  | yes |  |
| `tomo_db0::notify_record_slow(tomo_db0::Shard&, tomo_db0::Op&, unsigned int, unsigned int, tomo_db0::NotifyEventId, tomo_db0::Slice)` | [2034] | [2034] |  |  | yes |
| `tomo_db0::parse_double_strict(tomo_db0::Slice, double&)` | [503] | [503] |  |  | yes |
| `tomo_db0::redis_double_text(char*, unsigned long, double) [clone .isra.0]` | [1043, 1043, 1043, 1043, 1043] | [1043, 1043, 1043, 1043, 1043] |  |  | yes |
| `tomo_db0::stream_parse_xreadgroup(tomo_db0::Op&, tomo_db0::StreamXreadGroupArgs&)` | [1169] | [1169] |  |  | yes |
| `tomokv_multidb_main(int, char**)` | [12532] | [12564] |  |  |  |
| `tomokv_multidb_main(int, char**) [clone .cold]` | [5242] | [5242] |  |  |  |
| `unsigned int tomo::ExLoopT<false>::sweep<32u, true, false, false>()` | [1968] | [2017] | yes | yes |  |
| `unsigned int tomo::ExLoopT<true>::fused_pass_impl<32u, true, false, false>()` | [3466] | [3559] | yes | yes |  |
| `unsigned int tomo::ExLoopT<true>::fused_pass_impl<32u, true, false, true>()` | [3846] | [3956] | yes | yes |  |
| `unsigned int tomo::ExLoopT<true>::r7_fused_pass_impl<32u, true, false, false>()` | [3607] | [3705] | yes | yes |  |
| `unsigned int tomo::ExLoopT<true>::r7_fused_pass_impl<32u, true, false, true>()` | [3927] | [4005] | yes | yes |  |
| `unsigned int tomo::ExLoopT<true>::r7_sweep<32u, true, false, false>()` | [1227] | [924] | yes | yes |  |
| `unsigned int tomo::ExLoopT<true>::r7_sweep<32u, true, false, true>()` | [1147] | [1194] | yes | yes |  |
| `unsigned int tomo::ExLoopT<true>::sweep<32u, true, false, false>()` | [1227] | [1275] | yes | yes |  |
| `unsigned int tomo::ExLoopT<true>::sweep<32u, true, false, true>()` | [1510] | [1558] | yes | yes |  |
| `unsigned int tomo::IoLoop::flush_ready<false, true, true, false, true>()` | [2462] | [2385] | yes |  |  |
| `unsigned int tomo::IoLoop::flush_ready<false, true, true, true, true>()` | [2462] | [2385] | yes |  |  |
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
| `unsigned int tomo_db0::IoLoop::flip_control_pass<false>()` | [5285] | [5585] |  |  |  |
| `unsigned int tomo_db0::IoLoop::flip_control_pass<true>()` | [5285] | [5499] |  |  |  |
| `unsigned int tomo_db0::multi_owner_pass_entry_impl<false>(tomo_db0::IoLoop&)` | [13515] | [13802] |  | yes |  |
| `unsigned long tomo::FlatStore::scan<tomo::xshard_execute(tomo::Task const&, tomo::Shard&, tomo::Op&, unsigned int)::{lambda(tomo::KvObj*)#1}>(unsigned long, unsigned int, tomo::xshard_execute(tomo::Task const&, tomo::Shard&, tomo::Op&, unsigned int)::{lambda(tomo::KvObj*)#1}&&, bool) [clone .constprop.0]` | [3807] | [3774] | yes |  |  |
| `unsigned long tomo::kvobj_external_bytes<false>(tomo::KvObj const*, void const*, tomo::KvObj const*) [clone .isra.0]` | [1606, 1351, 306, 306, 306, 1431, 490, 306, 306, 306, 826, 1111, 810, 618, 306, 746, 1606, 1606, 810, 1606, 1606, 810] | [1606, 1351, 306, 306, 306, 1431, 490, 306, 306, 306, 826, 1111, 810, 618, 306, 746, 1606, 1606, 810, 1606, 1606, 810] |  |  |  |
| `void std::__merge_adaptive<__gnu_cxx::__normal_iterator<tomo_db0::MonitorScriptLine*, std::vector<tomo_db0::MonitorScriptLine, std::allocator<tomo_db0::MonitorScriptLine> > >, long, tomo_db0::MonitorScriptLine*, __gnu_cxx::__ops::_Iter_comp_iter<tomo_db0::IoLoop::climon_monitor_script_deliver(unsigned long, std::vector<tomo_db0::MonitorScriptLine, std::allocator<tomo_db0::MonitorScriptLine> >&)::{lambda(auto:1 const&, auto:2 const&)#1}> >(__gnu_cxx::__normal_iterator<tomo_db0::MonitorScriptLine*, std::vector<tomo_db0::MonitorScriptLine, std::allocator<tomo_db0::MonitorScriptLine> > >, __gnu_cxx::__normal_iterator<tomo_db0::MonitorScriptLine*, std::vector<tomo_db0::MonitorScriptLine, std::allocator<tomo_db0::MonitorScriptLine> > >, __gnu_cxx::__normal_iterator<tomo_db0::MonitorScriptLine*, std::vector<tomo_db0::MonitorScriptLine, std::allocator<tomo_db0::MonitorScriptLine> > >, long, long, tomo_db0::MonitorScriptLine*, __gnu_cxx::__ops::_Iter_comp_iter<tomo_db0::IoLoop::climon_monitor_script_deliver(unsigned long, std::vector<tomo_db0::MonitorScriptLine, std::allocator<tomo_db0::MonitorScriptLine> >&)::{lambda(auto:1 const&, auto:2 const&)#1}>) [clone .isra.0]` | [792] | [847] |  |  |  |
| `void tomo::(anonymous namespace)::cmd_geoadd<false>(tomo::Shard&, tomo::Op&)` | [4178] | [4178] |  |  | yes |
| `void tomo::(anonymous namespace)::cmd_geoadd<true>(tomo::Shard&, tomo::Op&)` | [4381] | [4381] |  |  | yes |
| `void tomo::(anonymous namespace)::cmd_zadd_generic<false>(tomo::Shard&, tomo::Op&, bool)` | [6184] | [6184] |  |  | yes |
| `void tomo::(anonymous namespace)::cmd_zadd_generic<true>(tomo::Shard&, tomo::Op&, bool)` | [6283] | [6283] |  |  | yes |
| `void tomo::IoLoop::adopt_client<false, false>(tomo::Client*, bool, bool)` | [965] | [1476] |  |  |  |
| `void tomo::IoLoop::adopt_client<true, true>(tomo::Client*, bool, bool)` | [1126] | [1110] |  |  |  |
| `void tomo::IoLoop::cancel_client_transfer<false>(tomo::Client*)` | [308] | [671] |  |  |  |
| `void tomo::IoLoop::on_recv<false, false, false>(tomo::Client*, int)` | [1364] | [800] |  |  |  |
| `void tomo::IoLoop::on_recv<true, false, false>(tomo::Client*, int)` | [1364] | [816] |  |  |  |
| `void tomo::IoLoop::r7_run_loop<false, false, false, true, false>()` | [5840] | [5938] |  | yes |  |
| `void tomo::IoLoop::r7_run_loop<false, false, true, true, false>()` | [5606] | [5769] |  | yes |  |
| `void tomo::IoLoop::r7_run_loop<false, true, false, true, false>()` | [5884] | [5977] |  | yes |  |
| `void tomo::IoLoop::r7_run_loop<false, true, true, true, false>()` | [5606] | [5769] |  | yes |  |
| `void tomo::IoLoop::r7_run_loop<true, false, false, true, false>()` | [5917] | [6016] |  | yes |  |
| `void tomo::IoLoop::r7_run_loop<true, false, true, true, false>()` | [5606] | [5769] |  | yes |  |
| `void tomo::IoLoop::r7_run_loop<true, true, false, true, false>()` | [5950] | [6073] |  | yes |  |
| `void tomo::IoLoop::r7_run_loop<true, true, true, true, false>()` | [5606] | [5769] |  | yes |  |
| `void tomo::IoLoop::run_loop<false, false, false, false, false>()` | [7170] | [7352] | yes | yes |  |
| `void tomo::IoLoop::run_loop<false, false, false, true, false>()` | [5753] | [5524] | yes | yes |  |
| `void tomo::IoLoop::run_loop<false, false, false, true, true>()` | [7259] | [7402] | yes | yes |  |
| `void tomo::IoLoop::run_loop<false, false, true, false, false>()` | [6205] | [6391] | yes | yes |  |
| `void tomo::IoLoop::run_loop<false, false, true, true, false>()` | [5665] | [5805] | yes | yes |  |
| `void tomo::IoLoop::run_loop<false, false, true, true, true>()` | [6283] | [6439] | yes | yes |  |
| `void tomo::IoLoop::run_loop<false, true, false, false, false>()` | [7608] | [7786] | yes | yes |  |
| `void tomo::IoLoop::run_loop<false, true, false, true, false>()` | [5815] | [5573] | yes | yes |  |
| `void tomo::IoLoop::run_loop<false, true, false, true, true>()` | [7706] | [7863] | yes | yes |  |
| `void tomo::IoLoop::run_loop<false, true, true, false, false>()` | [6205] | [6391] | yes | yes |  |
| `void tomo::IoLoop::run_loop<false, true, true, true, false>()` | [5665] | [5805] | yes | yes |  |
| `void tomo::IoLoop::run_loop<false, true, true, true, true>()` | [6283] | [6439] | yes | yes |  |
| `void tomo::IoLoop::run_loop<true, false, false, false, false>()` | [7671] | [7859] | yes | yes |  |
| `void tomo::IoLoop::run_loop<true, false, false, true, false>()` | [5829] | [5625] | yes | yes |  |
| `void tomo::IoLoop::run_loop<true, false, false, true, true>()` | [7749] | [7911] | yes | yes |  |
| `void tomo::IoLoop::run_loop<true, false, true, false, false>()` | [6237] | [6423] | yes | yes |  |
| `void tomo::IoLoop::run_loop<true, false, true, true, false>()` | [5678] | [5770] | yes | yes |  |
| `void tomo::IoLoop::run_loop<true, false, true, true, true>()` | [6311] | [6467] | yes | yes |  |
| `void tomo::IoLoop::run_loop<true, true, false, false, false>()` | [8069] | [8245] | yes | yes |  |
| `void tomo::IoLoop::run_loop<true, true, false, true, false>()` | [5479] | [5671] | yes | yes |  |
| `void tomo::IoLoop::run_loop<true, true, false, true, true>()` | [8129] | [8277] | yes | yes |  |
| `void tomo::IoLoop::run_loop<true, true, true, false, false>()` | [6237] | [6423] | yes | yes |  |
| `void tomo::IoLoop::run_loop<true, true, true, true, false>()` | [5678] | [5818] | yes | yes |  |
| `void tomo::IoLoop::run_loop<true, true, true, true, true>()` | [6311] | [6467] | yes | yes |  |
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
| `void tomo_db0::IoLoop::r7_run_loop<false, false, false, true, false>()` | [5985] | [5747] |  | yes |  |
| `void tomo_db0::IoLoop::r7_run_loop<false, false, true, true, false>()` | [5481] | [5544] |  | yes |  |
| `void tomo_db0::IoLoop::r7_run_loop<false, true, false, true, false>()` | [6018] | [5769] |  | yes |  |
| `void tomo_db0::IoLoop::r7_run_loop<false, true, true, true, false>()` | [5481] | [5544] |  | yes |  |
| `void tomo_db0::IoLoop::r7_run_loop<true, false, false, true, false>()` | [6051] | [5813] |  | yes |  |
| `void tomo_db0::IoLoop::r7_run_loop<true, false, true, true, false>()` | [5478] | [5544] |  | yes |  |
| `void tomo_db0::IoLoop::r7_run_loop<true, true, false, true, false>()` | [6097] | [5829] |  | yes |  |
| `void tomo_db0::IoLoop::r7_run_loop<true, true, true, true, false>()` | [5478] | [5544] |  | yes |  |
| `void tomo_db0::IoLoop::run_loop<false, false, false, false, false>()` | [6918] | [7019] | yes | yes |  |
| `void tomo_db0::IoLoop::run_loop<false, false, false, true, false>()` | [5704] | [5602] | yes | yes |  |
| `void tomo_db0::IoLoop::run_loop<false, false, false, true, true>()` | [7029] | [7081] | yes | yes |  |
| `void tomo_db0::IoLoop::run_loop<false, false, true, false, false>()` | [5951] | [6043] | yes | yes |  |
| `void tomo_db0::IoLoop::run_loop<false, false, true, true, false>()` | [5626] | [5686] | yes | yes |  |
| `void tomo_db0::IoLoop::run_loop<false, false, true, true, true>()` | [5998] | [6088] | yes | yes |  |
| `void tomo_db0::IoLoop::run_loop<false, true, false, false, false>()` | [7347] | [7462] | yes | yes |  |
| `void tomo_db0::IoLoop::run_loop<false, true, false, true, false>()` | [5760] | [5662] | yes | yes |  |
| `void tomo_db0::IoLoop::run_loop<false, true, false, true, true>()` | [7453] | [7498] | yes | yes |  |
| `void tomo_db0::IoLoop::run_loop<false, true, true, false, false>()` | [5951] | [6043] | yes | yes |  |
| `void tomo_db0::IoLoop::run_loop<false, true, true, true, false>()` | [5626] | [5686] | yes | yes |  |
| `void tomo_db0::IoLoop::run_loop<false, true, true, true, true>()` | [5998] | [6088] | yes | yes |  |
| `void tomo_db0::IoLoop::run_loop<true, false, false, false, false>()` | [7400] | [7493] | yes | yes |  |
| `void tomo_db0::IoLoop::run_loop<true, false, false, true, false>()` | [5622] | [5684] | yes | yes |  |
| `void tomo_db0::IoLoop::run_loop<true, false, false, true, true>()` | [7508] | [7555] | yes | yes |  |
| `void tomo_db0::IoLoop::run_loop<true, false, true, false, false>()` | [5983] | [6075] | yes | yes |  |
| `void tomo_db0::IoLoop::run_loop<true, false, true, true, false>()` | [5639] | [5699] | yes | yes |  |
| `void tomo_db0::IoLoop::run_loop<true, false, true, true, true>()` | [6042] | [6132] | yes | yes |  |
| `void tomo_db0::IoLoop::run_loop<true, true, false, false, false>()` | [7793] | [7889] | yes | yes |  |
| `void tomo_db0::IoLoop::run_loop<true, true, false, true, false>()` | [5668] | [5730] | yes | yes |  |
| `void tomo_db0::IoLoop::run_loop<true, true, false, true, true>()` | [7900] | [7931] | yes | yes |  |
| `void tomo_db0::IoLoop::run_loop<true, true, true, false, false>()` | [5983] | [6075] | yes | yes |  |
| `void tomo_db0::IoLoop::run_loop<true, true, true, true, false>()` | [5639] | [5574] | yes | yes |  |
| `void tomo_db0::IoLoop::run_loop<true, true, true, true, true>()` | [6042] | [6132] | yes | yes |  |
| `void tomo_db0::cmd_xshard_only_impl<false>(tomo_db0::Shard&, tomo_db0::Op&)` | [16757] | [16757] | yes |  | yes |
| `void tomo_db0::cmd_xshard_only_impl<true>(tomo_db0::Shard&, tomo_db0::Op&)` | [18094] | [18094] | yes |  | yes |
