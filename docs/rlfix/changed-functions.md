All 34 changed emitted bodies from the unmodified full audit. A zero size means absent in that arm.

| Object | Function | PRE bytes | POST bytes |
|---|---|---:|---:|
| `db0/src/core/genthread.o` | `void tomo_db0::IoLoop::adopt_client<true, false>(tomo_db0::Client*, bool, bool)` | 2047 | 1951 |
| `db0/src/core/genthread.o` | `void tomo_db0::IoLoop::adopt_client<true, true>(tomo_db0::Client*, bool, bool)` | 2047 | 1951 |
| `db0/src/core/genthread.o` | `tomo_db0::IoLoop::pubsub_reply_ping(tomo_db0::Op&) [clone .isra.0]` | 395 | 597 |
| `db0/src/core/genthread.o` | `tomo_db0::IoLoop::pubsub_start_numpat(tomo_db0::Client*, tomo_db0::Op&)` | 1117 | 1282 |
| `db0/src/core/genthread.o` | `tomo_db0::IoLoop::ReadLocalDemotionPlan::prepare(tomo_db0::IoLoop&, tomo_db0::Client*, unsigned long, bool, int, tomo_db0::ReadLocalFallbackReason, bool, unsigned long const*, tomo_db0::ReadLocalFallbackReason const*, unsigned int, tomo_db0::Op const*, bool)` | 6232 | 6629 |
| `db0/src/core/genthread.o` | `tomo_db0::IoLoop::pubsub_handle_home_request(tomo_db0::PubSubEvent&)` | 4491 | 4475 |
| `db0/src/core/genthread.o` | `tomo_db0::IoLoop::quiesce_accepts_for_conversion()` | 677 | 664 |
| `db0/src/core/genthread.o` | `tomo_db0::ExLoopT<true>::prepare_local_read(tomo_db0::Op&, tomo_db0::FlatStore*, bool, tomo_db0::FlatStore::ReadLocalPrefetchCapture const*)` | 1675 | 2249 |
| `db0/src/core/genthread.o` | `bool tomo_db0::WbEngine::pump<false, false>(tomo_db0::Client&)` | 1173 | 886 |
| `db0/src/core/genthread.o` | `tomo_db0::FlatStore::random_volatile_candidate()` | 931 | 867 |
| `db0/src/core/genthread.o` | `tomo_db0::IoLoop::flip_candidate_clients_ready(std::__cxx11::basic_string<char, std::char_traits<char>, std::allocator<char> >&) const` | 786 | 640 |
| `db0/src/core/genthread.o` | `bool std::operator==<char, std::char_traits<char>, std::allocator<char> >(std::__cxx11::basic_string<char, std::char_traits<char>, std::allocator<char> > const&, std::__cxx11::basic_string<char, std::char_traits<char>, std::allocator<char> > const&)` | 0 | 67 |
| `db0/src/core/reorder.o` | `tomo_db0::u64_to_dec(char*, unsigned long)` | 160 | 0 |
| `db0/src/core/reorder.o` | `tomo_db0::IoLoop::ReadLocalDemotionPlan::prepare(tomo_db0::IoLoop&, tomo_db0::Client*, unsigned long, bool, int, tomo_db0::ReadLocalFallbackReason, bool, unsigned long const*, tomo_db0::ReadLocalFallbackReason const*, unsigned int, tomo_db0::Op const*, bool)` | 6128 | 6582 |
| `db0/src/core/reorder.o` | `tomo_db0::ExLoopT<true>::prepare_local_read(tomo_db0::Op&, tomo_db0::FlatStore*, bool, tomo_db0::FlatStore::ReadLocalPrefetchCapture const*)` | 1675 | 2249 |
| `db0/src/core/rl2s.o` | `tomo_db0::IoLoop::ReadLocalDemotionPlan::prepare(tomo_db0::IoLoop&, tomo_db0::Client*, unsigned long, bool, int, tomo_db0::ReadLocalFallbackReason, bool, unsigned long const*, tomo_db0::ReadLocalFallbackReason const*, unsigned int, tomo_db0::Op const*, bool)` | 6116 | 6756 |
| `db0/src/core/rl2s.o` | `tomo_db0::ExLoopT<true>::prepare_local_read(tomo_db0::Op&, tomo_db0::FlatStore*, bool, tomo_db0::FlatStore::ReadLocalPrefetchCapture const*)` | 1848 | 2530 |
| `src/core/genthread.o` | `tomo::weighted_lb_partition(std::vector<tomo::WeightedLbItem, std::allocator<tomo::WeightedLbItem> > const&, std::vector<unsigned int, std::allocator<unsigned int> > const&, std::vector<tomo::WeightedLbAssignment, std::allocator<tomo::WeightedLbAssignment> >&)` | 6102 | 6036 |
| `src/core/genthread.o` | `tomo::IoLoop::lb_control_pass()` | 3557 | 3621 |
| `src/core/genthread.o` | `tomo::IoLoop::pubsub_reply_ping(tomo::Op&) [clone .isra.0]` | 395 | 597 |
| `src/core/genthread.o` | `tomo::IoLoop::ReadLocalDemotionPlan::prepare(tomo::IoLoop&, tomo::Client*, unsigned long, bool, int, tomo::ReadLocalFallbackReason, bool, unsigned long const*, tomo::ReadLocalFallbackReason const*, unsigned int, tomo::Op const*, bool)` | 6100 | 6672 |
| `src/core/genthread.o` | `tomo::ExLoopT<true>::prepare_local_read(tomo::Op&, tomo::FlatStore*, bool, tomo::FlatStore::ReadLocalPrefetchCapture const*)` | 1675 | 2249 |
| `src/core/genthread.o` | `void tomo::reply_err<tomo::Op::Sink>(tomo::Op::Sink&&, char const*)` | 781 | 973 |
| `src/core/reorder.o` | `tomo::u64_to_dec(char*, unsigned long)` | 160 | 0 |
| `src/core/reorder.o` | `tomo::IoLoop::ReadLocalDemotionPlan::prepare(tomo::IoLoop&, tomo::Client*, unsigned long, bool, int, tomo::ReadLocalFallbackReason, bool, unsigned long const*, tomo::ReadLocalFallbackReason const*, unsigned int, tomo::Op const*, bool)` | 6295 | 6599 |
| `src/core/reorder.o` | `tomo::ExLoopT<true>::prepare_local_read(tomo::Op&, tomo::FlatStore*, bool, tomo::FlatStore::ReadLocalPrefetchCapture const*)` | 1675 | 2249 |
| `src/core/reorder.o` | `tomo::FlatStore::atomic_collapse(unsigned long, unsigned long)` | 7039 | 7093 |
| `src/core/reorder.o` | `tomo::FlatStore::atomic_collapse_read_local(unsigned long, unsigned long)` | 7820 | 7872 |
| `src/core/reorder.o` | `void std::deque<tomo::PubSubEvent*, std::allocator<tomo::PubSubEvent*> >::_M_insert_aux<std::_Deque_iterator<tomo::PubSubEvent*, tomo::PubSubEvent*&, tomo::PubSubEvent**> >(std::_Deque_iterator<tomo::PubSubEvent*, tomo::PubSubEvent*&, tomo::PubSubEvent**>, std::_Deque_iterator<tomo::PubSubEvent*, tomo::PubSubEvent*&, tomo::PubSubEvent**>, std::_Deque_iterator<tomo::PubSubEvent*, tomo::PubSubEvent*&, tomo::PubSubEvent**>, unsigned long)` | 2519 | 2727 |
| `src/core/rl2s.o` | `unsigned int tomo::IoLoop::flip_control_pass<false>()` | 5851 | 5393 |
| `src/core/rl2s.o` | `unsigned int tomo::IoLoop::flip_control_pass<true>()` | 5579 | 5393 |
| `src/core/rl2s.o` | `tomo::IoLoop::ReadLocalDemotionPlan::prepare(tomo::IoLoop&, tomo::Client*, unsigned long, bool, int, tomo::ReadLocalFallbackReason, bool, unsigned long const*, tomo::ReadLocalFallbackReason const*, unsigned int, tomo::Op const*, bool)` | 6331 | 6894 |
| `src/core/rl2s.o` | `void tomo::IoLoop::cancel_client_transfer<false>(tomo::Client*)` | 0 | 308 |
| `src/core/rl2s.o` | `tomo::ExLoopT<true>::prepare_local_read(tomo::Op&, tomo::FlatStore*, bool, tomo::FlatStore::ReadLocalPrefetchCapture const*)` | 1848 | 2530 |
