# Every changed emitted function body (N1/N2 candidate)

| Object | Function | PRE bytes | Candidate bytes |
|---|---|---:|---:|
| `db0/src/cmd/acl.o` | `tomo_db0::(anonymous namespace)::acl_reply_log(tomo_db0::Op&)` | 6351 | 6016 |
| `db0/src/cmd/acl.o` | `tomo_db0::acl_command_entry(tomo_db0::IoLoop&, tomo_db0::Client&, tomo_db0::Op&)` | 12173 | 12209 |
| `db0/src/cmd/acl.o` | `tomo_db0::acl_command_entry(tomo_db0::IoLoop&, tomo_db0::Client&, tomo_db0::Op&) [clone .cold]` | 679 | 679 |
| `db0/src/cmd/acl.o` | `tomo_db0::IoLoop::close_client(tomo_db0::Client*, bool)` | 7388 | 7453 |
| `db0/src/cmd/acl.o` | `tomo_db0::IoLoop::pubsub_finish_pending(unsigned long)` | 3382 | 3398 |
| `db0/src/cmd/acl.o` | `void tomo_db0::reply_int<tomo_db0::Op::Sink&>(tomo_db0::Op::Sink&, long long)` | 366 | 255 |
| `db0/src/cmd/acl.o` | `tomo_db0::Rob<64u>::quiesced() const` | 0 | 22 |
| `db0/src/cmd/climon.o` | `tomo_db0::IoLoop::close_client(tomo_db0::Client*, bool)` | 4754 | 4755 |
| `db0/src/cmd/climon.o` | `tomo_db0::IoLoop::client_routing_install(void*, tomo_db0::Client*, unsigned int)` | 818 | 770 |
| `db0/src/cmd/climon.o` | `tomo_db0::IoLoop::pubsub_home_add_pattern(std::__cxx11::basic_string<char, std::char_traits<char>, std::allocator<char> > const&, tomo_db0::IoLoop::PubSubRef const&)` | 1456 | 1247 |
| `db0/src/cmd/climon.o` | `tomo_db0::IoLoop::climon_start_client_kill(tomo_db0::Client*, tomo_db0::Op&)` | 2904 | 2862 |
| `db0/src/cmd/climon.o` | `tomo_db0::IoLoop::client_routing_commit_extract(tomo_db0::IoLoop::ClientMigration&, std::vector<tomo_db0::PubSubEvent*, std::allocator<tomo_db0::PubSubEvent*> >&)` | 1555 | 1493 |
| `db0/src/cmd/climon.o` | `tomo_db0::WbEngine::flush_deferred_oob(tomo_db0::Client&)` | 472 | 396 |
| `db0/src/cmd/climon.o` | `bool tomo_db0::WbEngine::pump_tls<false, false>(tomo_db0::Client&, tomo_db0::TlsConn&)` | 1401 | 1481 |
| `db0/src/cmd/climon.o` | `tomo_db0::Rob<64u>::quiesced() const` | 0 | 22 |
| `db0/src/cmd/climon.o` | `std::_Hashtable<tomo_db0::Client*, std::pair<tomo_db0::Client* const, std::deque<tomo_db0::WbEngine::DeferredOob, std::allocator<tomo_db0::WbEngine::DeferredOob> > >, std::allocator<std::pair<tomo_db0::Client* const, std::deque<tomo_db0::WbEngine::DeferredOob, std::allocator<tomo_db0::WbEngine::DeferredOob> > > >, std::__detail::_Select1st, std::equal_to<tomo_db0::Client*>, std::hash<tomo_db0::Client*>, std::__detail::_Mod_range_hashing, std::__detail::_Default_ranged_hash, std::__detail::_Prime_rehash_policy, std::__detail::_Hashtable_traits<false, false, true> >::_M_find_before_node(unsigned long, tomo_db0::Client* const&, unsigned long) const [clone .isra.0]` | 0 | 71 |
| `db0/src/cmd/climon.o` | `std::_Hashtable<unsigned long, std::pair<unsigned long const, tomo_db0::IoLoop::ClimonConn>, std::allocator<std::pair<unsigned long const, tomo_db0::IoLoop::ClimonConn> >, std::__detail::_Select1st, std::equal_to<unsigned long>, std::hash<unsigned long>, std::__detail::_Mod_range_hashing, std::__detail::_Default_ranged_hash, std::__detail::_Prime_rehash_policy, std::__detail::_Hashtable_traits<false, false, true> >::_M_find_before_node(unsigned long, unsigned long const&, unsigned long) const [clone .isra.0]` | 0 | 71 |
| `db0/src/cmd/xshard.o` | `tomo_db0::kvobj_free(tomo_db0::KvObj*) [clone .part.0]` | 351 | 383 |
| `db0/src/cmd/xshard.o` | `tomo_db0::(anonymous namespace)::classify_keys(tomo_db0::Op const&, tomo_db0::(anonymous namespace)::Kind, tomo_db0::(anonymous namespace)::XshardKeyHints const&, tomo_db0::(anonymous namespace)::XshardKeyPlan&)` | 979 | 947 |
| `db0/src/cmd/xshard.o` | `tomo_db0::(anonymous namespace)::notify_event_name(tomo_db0::NotifyEventId)` | 1072 | 1072 |
| `db0/src/cmd/xshard.o` | `tomo_db0::xshard_plain_prepare(tomo_db0::Server&, tomo_db0::Shard&, tomo_db0::Op&, unsigned long, tomo_db0::PlainForeignReadScope&)` | 7646 | 7454 |
| `db0/src/cmd/xshard.o` | `tomo_db0::xshard_plain_prepare(tomo_db0::Server&, tomo_db0::Shard&, tomo_db0::Op&, unsigned long, tomo_db0::PlainForeignReadScope&) [clone .cold]` | 236 | 242 |
| `db0/src/cmd/xshard.o` | `tomo_db0::IoLoop::close_client(tomo_db0::Client*, bool)` | 8160 | 8216 |
| `db0/src/cmd/xshard.o` | `unsigned int& std::vector<unsigned int, std::allocator<unsigned int> >::emplace_back<unsigned int>(unsigned int&&) [clone .isra.0]` | 352 | 371 |
| `db0/src/core/genthread.o` | `tomo_db0::IoLoop::epoll_recv(tomo_db0::Client*)` | 717 | 733 |
| `db0/src/core/genthread.o` | `tomo_db0::IoLoop::close_client(tomo_db0::Client*, bool)` | 3662 | 3715 |
| `db0/src/core/genthread.o` | `tomo_db0::IoLoop::DispatchResult tomo_db0::IoLoop::parse_and_dispatch<true, 0u, false>(tomo_db0::Client*) [clone .isra.0]` | 9906 | 9890 |
| `db0/src/core/genthread.o` | `tomo_db0::IoLoop::DispatchResult tomo_db0::IoLoop::parse_and_dispatch<true, 0u, false>(tomo_db0::Client*) [clone .isra.0] [clone .cold]` | 117 | 117 |
| `db0/src/core/genthread.o` | `tomo_db0::IoLoop::pubsub_start_numpat(tomo_db0::Client*, tomo_db0::Op&)` | 1117 | 1282 |
| `db0/src/core/genthread.o` | `bool tomo_db0::WbEngine::pump_tls<false, false>(tomo_db0::Client&, tomo_db0::TlsConn&)` | 1656 | 1720 |
| `db0/src/core/lbplanner.o` | `tomo_db0::IoLoop::epoll_recv(tomo_db0::Client*)` | 717 | 733 |
| `db0/src/core/reorder.o` | `tomo_db0::IoLoop::epoll_recv(tomo_db0::Client*)` | 717 | 733 |
| `db0/src/core/reorder.o` | `void tomo_db0::IoLoop::r7_run_loop<true, true, false, true, false>()` | 4816 | 4851 |
| `db0/src/core/reorder.o` | `tomo_db0::IoLoop::close_client(tomo_db0::Client*, bool)` | 3911 | 3972 |
| `db0/src/core/reorder.o` | `tomo_db0::IoLoop::DispatchResult tomo_db0::IoLoop::r7_parse_and_dispatch<false, 32u, false>(tomo_db0::Client*)` | 18345 | 18394 |
| `db0/src/core/reorder.o` | `unsigned int tomo_db0::ExLoopT<true>::fused_pass_impl<32u, true, false, false>()` | 4180 | 4033 |
| `db0/src/core/reorder.o` | `unsigned int tomo_db0::ExLoopT<true>::r7_fused_pass_impl<32u, true, false, false>()` | 4180 | 4033 |
| `db0/src/core/reorder.o` | `unsigned int tomo_db0::ExLoopT<true>::r7_fused_sweep_impl<32u, true, false, false>()` | 796 | 729 |
| `db0/src/core/reorder.o` | `bool tomo_db0::ExLoopT<true>::execute<false, false>(tomo_db0::Task const&)` | 3631 | 3565 |
| `db0/src/core/reorder.o` | `bool tomo_db0::WbEngine::pump_tls<false, false>(tomo_db0::Client&, tomo_db0::TlsConn&)` | 1848 | 1944 |
| `db0/src/core/reorder.o` | `tomo_db0::FlatStore::budget_admit(tomo_db0::Slice)` | 1011 | 1011 |
| `db0/src/core/reorder.o` | `unsigned int tomo_db0::FlatStore::scan_home<tomo_db0::Shard::lb_scan_bucket_bytes(unsigned int)::{lambda(tomo_db0::KvObj*)#1}>(int, unsigned int, tomo_db0::Shard::lb_scan_bucket_bytes(unsigned int)::{lambda(tomo_db0::KvObj*)#1}&, bool)` | 820 | 964 |
| `db0/src/core/reorder.o` | `tomo_db0::Rob<64u>::quiesced() const` | 0 | 22 |
| `db0/src/core/reorder.o` | `tomo_db0::IoLoop::flip_io_drained() const` | 708 | 704 |
| `db0/src/core/rl2s.o` | `tomo_db0::IoLoop::epoll_recv(tomo_db0::Client*)` | 717 | 733 |
| `db0/src/core/rl2s.o` | `tomo_db0::IoLoop::close_client(tomo_db0::Client*, bool)` | 4317 | 4373 |
| `db0/src/core/rl2s.o` | `bool tomo_db0::WbEngine::pump_tls<false, false>(tomo_db0::Client&, tomo_db0::TlsConn&)` | 2069 | 2149 |
| `db0/src/main.o` | `tomo_db0::IoLoop::epoll_recv(tomo_db0::Client*)` | 1098 | 1114 |
| `db0/src/main.o` | `tomo_db0::IoLoop::close_client(tomo_db0::Client*, bool)` | 4717 | 4777 |
| `db0/src/main.o` | `bool tomo_db0::WbEngine::pump_tls<false, false>(tomo_db0::Client&, tomo_db0::TlsConn&)` | 2069 | 2149 |
| `src/cmd/acl.o` | `tomo::(anonymous namespace)::acl_reply_log(tomo::Op&)` | 6016 | 5667 |
| `src/cmd/acl.o` | `tomo::IoLoop::close_client(tomo::Client*, bool)` | 7102 | 7162 |
| `src/cmd/acl.o` | `tomo::IoLoop::pubsub_finish_pending(unsigned long)` | 3382 | 3398 |
| `src/cmd/acl.o` | `tomo::Rob<64u>::quiesced() const` | 0 | 22 |
| `src/cmd/acl.o` | `tomo::(anonymous namespace)::AclLogEntry& std::deque<tomo::(anonymous namespace)::AclLogEntry, std::allocator<tomo::(anonymous namespace)::AclLogEntry> >::emplace_front<tomo::(anonymous namespace)::AclLogEntry>(tomo::(anonymous namespace)::AclLogEntry&&) [clone .isra.0]` | 1064 | 771 |
| `src/cmd/acl.o` | `void std::__adjust_heap<__gnu_cxx::__normal_iterator<tomo::(anonymous namespace)::AclLogEntry*, std::vector<tomo::(anonymous namespace)::AclLogEntry, std::allocator<tomo::(anonymous namespace)::AclLogEntry> > >, long, tomo::(anonymous namespace)::AclLogEntry, __gnu_cxx::__ops::_Iter_comp_iter<tomo::(anonymous namespace)::acl_reply_log(tomo::Op&)::{lambda(tomo::(anonymous namespace)::AclLogEntry const&, tomo::(anonymous namespace)::AclLogEntry const&)#1}> >(__gnu_cxx::__normal_iterator<tomo::(anonymous namespace)::AclLogEntry*, std::vector<tomo::(anonymous namespace)::AclLogEntry, std::allocator<tomo::(anonymous namespace)::AclLogEntry> > >, long, long, tomo::(anonymous namespace)::AclLogEntry, __gnu_cxx::__ops::_Iter_comp_iter<tomo::(anonymous namespace)::acl_reply_log(tomo::Op&)::{lambda(tomo::(anonymous namespace)::AclLogEntry const&, tomo::(anonymous namespace)::AclLogEntry const&)#1}>) [clone .isra.0]` | 2815 | 2816 |
| `src/cmd/acl.o` | `void std::__introsort_loop<__gnu_cxx::__normal_iterator<tomo::(anonymous namespace)::AclLogEntry*, std::vector<tomo::(anonymous namespace)::AclLogEntry, std::allocator<tomo::(anonymous namespace)::AclLogEntry> > >, long, __gnu_cxx::__ops::_Iter_comp_iter<tomo::(anonymous namespace)::acl_reply_log(tomo::Op&)::{lambda(tomo::(anonymous namespace)::AclLogEntry const&, tomo::(anonymous namespace)::AclLogEntry const&)#1}> >(__gnu_cxx::__normal_iterator<tomo::(anonymous namespace)::AclLogEntry*, std::vector<tomo::(anonymous namespace)::AclLogEntry, std::allocator<tomo::(anonymous namespace)::AclLogEntry> > >, __gnu_cxx::__normal_iterator<tomo::(anonymous namespace)::AclLogEntry*, std::vector<tomo::(anonymous namespace)::AclLogEntry, std::allocator<tomo::(anonymous namespace)::AclLogEntry> > >, long, __gnu_cxx::__ops::_Iter_comp_iter<tomo::(anonymous namespace)::acl_reply_log(tomo::Op&)::{lambda(tomo::(anonymous namespace)::AclLogEntry const&, tomo::(anonymous namespace)::AclLogEntry const&)#1}>)` | 2143 | 2178 |
| `src/cmd/climon.o` | `tomo::IoLoop::close_client(tomo::Client*, bool)` | 4627 | 4684 |
| `src/cmd/climon.o` | `bool tomo::WbEngine::pump_tls<false, false>(tomo::Client&, tomo::TlsConn&)` | 1401 | 1481 |
| `src/cmd/climon.o` | `void tomo::reply_err<tomo::Op::Sink>(tomo::Op::Sink&&, char const*)` | 781 | 550 |
| `src/cmd/climon.o` | `tomo::Rob<64u>::quiesced() const` | 0 | 22 |
| `src/cmd/xshard.o` | `tomo::(anonymous namespace)::classify_keys(tomo::Op const&, tomo::(anonymous namespace)::Kind, tomo::(anonymous namespace)::XshardKeyHints const&, tomo::(anonymous namespace)::XshardKeyPlan&)` | 947 | 963 |
| `src/cmd/xshard.o` | `tomo::(anonymous namespace)::assemble_final(tomo::Client&, tomo::Op&, tomo::ScatterState&, void*, void (*)(void*, int, char const*), void (*)(void*))` | 7107 | 7109 |
| `src/cmd/xshard.o` | `void tomo::(anonymous namespace)::bitfield_generic<true>(tomo::Shard&, tomo::Op&, bool)` | 2933 | 2882 |
| `src/cmd/xshard.o` | `tomo::(anonymous namespace)::notify_event_name(tomo::NotifyEventId)` | 1072 | 1072 |
| `src/cmd/xshard.o` | `tomo::(anonymous namespace)::normalize_multi_blocking_pop(tomo::MultiCommand&)` | 3454 | 3308 |
| `src/cmd/xshard.o` | `tomo::(anonymous namespace)::normalize_multi_blocking_pop(tomo::MultiCommand&) [clone .cold]` | 45 | 45 |
| `src/cmd/xshard.o` | `tomo::IoLoop::close_client(tomo::Client*, bool)` | 8160 | 8216 |
| `src/cmd/xshard.o` | `tomo::(anonymous namespace)::prepare_sort_deref(tomo::ScatterState&, tomo::Op&)::{lambda(tomo::SortPattern const&, tomo::Slice, bool, unsigned long)#1}::operator()(tomo::SortPattern const&, tomo::Slice, bool, unsigned long) const [clone .constprop.0]` | 3715 | 3686 |
| `src/cmd/xshard.o` | `tomo::(anonymous namespace)::prepare_sort_deref(tomo::ScatterState&, tomo::Op&)::{lambda(tomo::SortPattern const&, tomo::Slice, bool, unsigned long)#1}::operator()(tomo::SortPattern const&, tomo::Slice, bool, unsigned long) const [clone .constprop.0] [clone .cold]` | 162 | 162 |
| `src/core/genthread.o` | `tomo::IoLoop::epoll_recv(tomo::Client*)` | 717 | 733 |
| `src/core/genthread.o` | `unsigned int tomo::IoLoop::flush_ready<false, true, true, false, false, false>()` | 2881 | 2572 |
| `src/core/genthread.o` | `tomo::IoLoop::close_client(tomo::Client*, bool)` | 3010 | 3065 |
| `src/core/genthread.o` | `void tomo::IoLoop::run_loop<true, true, false, true, false>()` | 5149 | 5177 |
| `src/core/genthread.o` | `bool tomo::WbEngine::pump_tls<false, false>(tomo::Client&, tomo::TlsConn&)` | 1401 | 1481 |
| `src/core/genthread.o` | `tomo::ThreadCtx::publish_read_local_parked(unsigned long)` | 36 | 0 |
| `src/core/genthread.o` | `std::thread::_State_impl<std::thread::_Invoker<std::tuple<tomo::run_fused_server(tomo::Server&, tomo::SnapshotLoadPlan const*, std::vector<std::unique_ptr<tomo::AofReplayPlan, std::default_delete<tomo::AofReplayPlan> >, std::allocator<std::unique_ptr<tomo::AofReplayPlan, std::default_delete<tomo::AofReplayPlan> > > > const&, tomo::SnapshotLoadPlan const*, tomo::TlsContext*, tomo::LateUnixListener&, tomo::ShutdownReportFinalLine&)::{lambda()#2}> > >::_M_run()` | 4551 | 4573 |
| `src/core/genthread.o` | `std::thread::_State_impl<std::thread::_Invoker<std::tuple<tomo::run_fused_server(tomo::Server&, tomo::SnapshotLoadPlan const*, std::vector<std::unique_ptr<tomo::AofReplayPlan, std::default_delete<tomo::AofReplayPlan> >, std::allocator<std::unique_ptr<tomo::AofReplayPlan, std::default_delete<tomo::AofReplayPlan> > > > const&, tomo::SnapshotLoadPlan const*, tomo::TlsContext*, tomo::LateUnixListener&, tomo::ShutdownReportFinalLine&)::{lambda()#2}> > >::_M_run() [clone .cold]` | 332 | 332 |
| `src/core/lbplanner.o` | `tomo::IoLoop::epoll_recv(tomo::Client*)` | 717 | 733 |
| `src/core/reorder.o` | `tomo::IoLoop::epoll_recv(tomo::Client*)` | 717 | 733 |
| `src/core/reorder.o` | `void tomo::IoLoop::adopt_client<true, false>(tomo::Client*, bool, bool)` | 2079 | 2112 |
| `src/core/reorder.o` | `tomo::IoLoop::close_client(tomo::Client*, bool)` | 3742 | 3795 |
| `src/core/reorder.o` | `tomo::IoLoop::lb_control_pass()` | 3557 | 3621 |
| `src/core/reorder.o` | `void tomo::IoLoop::r7_adopt_client<true, true>(tomo::Client*, bool, bool)` | 2112 | 2144 |
| `src/core/reorder.o` | `bool tomo::WbEngine::pump_tls<false, false>(tomo::Client&, tomo::TlsConn&)` | 1656 | 1720 |
| `src/core/reorder.o` | `void std::deque<tomo::PubSubEvent*, std::allocator<tomo::PubSubEvent*> >::_M_insert_aux<std::_Deque_iterator<tomo::PubSubEvent*, tomo::PubSubEvent*&, tomo::PubSubEvent**> >(std::_Deque_iterator<tomo::PubSubEvent*, tomo::PubSubEvent*&, tomo::PubSubEvent**>, std::_Deque_iterator<tomo::PubSubEvent*, tomo::PubSubEvent*&, tomo::PubSubEvent**>, std::_Deque_iterator<tomo::PubSubEvent*, tomo::PubSubEvent*&, tomo::PubSubEvent**>, unsigned long)` | 2692 | 2583 |
| `src/core/rl2s.o` | `tomo::IoLoop::epoll_recv(tomo::Client*)` | 717 | 733 |
| `src/core/rl2s.o` | `tomo::IoLoop::close_client(tomo::Client*, bool)` | 4317 | 4373 |
| `src/core/rl2s.o` | `tomo::IoLoop::DispatchResult tomo::IoLoop::parse_and_dispatch<false, 32u, true>(tomo::Client*)` | 21207 | 21138 |
| `src/core/rl2s.o` | `tomo::IoLoop::DispatchResult tomo::IoLoop::parse_and_dispatch<true, 32u, true>(tomo::Client*)` | 21112 | 21049 |
| `src/core/rl2s.o` | `tomo::Server::flip_begin(unsigned int, unsigned int, unsigned int, std::__cxx11::basic_string<char, std::char_traits<char>, std::allocator<char> >&)` | 6362 | 6382 |
| `src/core/rl2s.o` | `bool tomo::WbEngine::pump_tls<false, false>(tomo::Client&, tomo::TlsConn&)` | 2069 | 2149 |
| `src/main.o` | `tomo::IoLoop::epoll_recv(tomo::Client*)` | 1098 | 1114 |
| `src/main.o` | `tomo::IoLoop::close_client(tomo::Client*, bool)` | 4717 | 4777 |
| `src/main.o` | `bool tomo::WbEngine::pump_tls<false, false>(tomo::Client&, tomo::TlsConn&)` | 2069 | 2149 |
