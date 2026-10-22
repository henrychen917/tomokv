{"object": "src/core/reorder.o", "params": "--param inline-unit-growth=0 --param large-unit-insns=147829", "unit": 114487, "changed": 37, "hot_changed": 9, "A": 31, "B": 5, "C": 0, "D": 1, "hotA": 5, "hotB": 4, "hotCD": 0, "path": "/home/user/Projects/cx-wave3/build/wave3/trials/post/src_core_reorder.o.82c78e2eaa1c.o"}
    HOT B T=respresume code 18137->18373 lanes=respresume,mkfix eq=- tomo::IoLoop::DispatchResult tomo::IoLoop::parse_and_dispatch<false, 32u, false>(tomo::Client*)
    HOT A T=respresume code 9784->9925 lanes=respresume eq=respresume tomo::IoLoop::DispatchResult tomo::IoLoop::parse_and_dispatch<true, 0u, false>(tomo::Client*) [clone .isra.0]
    HOT A T=respresume code 44->117 lanes=respresume eq=respresume tomo::IoLoop::DispatchResult tomo::IoLoop::parse_and_dispatch<true, 0u, false>(tomo::Client*) [clone .isra.0] 
    HOT B T=respresume code 18173->18386 lanes=respresume,mkfix eq=- tomo::IoLoop::DispatchResult tomo::IoLoop::parse_and_dispatch<true, 32u, false>(tomo::Client*)
    HOT B T=respresume code 18152->18389 lanes=respresume,mkfix eq=- tomo::IoLoop::DispatchResult tomo::IoLoop::r7_parse_and_dispatch<false, 32u, false>(tomo::Client*)
    HOT B T=respresume code 18281->18465 lanes=respresume,mkfix eq=- tomo::IoLoop::DispatchResult tomo::IoLoop::r7_parse_and_dispatch<true, 32u, false>(tomo::Client*)
    HOT A T=rlfix code 1675->2249 lanes=rlfix eq=rlfix tomo::ExLoopT<true>::prepare_local_read(tomo::Op&, tomo::FlatStore*, bool, tomo::FlatStore::ReadLocalPrefetchC
    HOT A T=PRE code 451->451 lanes=mkfix eq=mkfix tomo::IoLoop::init(tomo::Server*, tomo::ThreadCtx*, char const*, unsigned short, int, tomo::TlsContext const*,
    HOT A T=PRE code 451->451 lanes=mkfix eq=mkfix tomo::IoLoop::init(tomo::Server*, tomo::ThreadCtx*, char const*, unsigned short, int, tomo::TlsContext const*,
    D T=new code 1158->1190 lanes=wave2 eq=respresume,rlfix,mkfix,aoforder,hexpread tomo::FlatStore::snapshot_prepare_write(unsigned long, tomo::Slice)
{"object": "src/core/reorder.o", "params": "--param inline-unit-growth=0 --param large-unit-insns=147500", "unit": 114487, "changed": 44, "hot_changed": 10, "A": 30, "B": 6, "C": 6, "D": 2, "hotA": 5, "hotB": 4, "hotCD": 1, "path": "/home/user/Projects/cx-wave3/build/wave3/trials/post/src_core_reorder.o.1a2e194e3e8f.o"}
    HOT C T=new code 2960->2897 lanes=- eq=- unsigned int tomo::IoLoop::r7_flush_ready<false, true, true, false, true, false>()
    HOT B T=respresume code 18137->18373 lanes=respresume,mkfix eq=- tomo::IoLoop::DispatchResult tomo::IoLoop::parse_and_dispatch<false, 32u, false>(tomo::Client*)
    HOT A T=respresume code 9784->9925 lanes=respresume eq=respresume tomo::IoLoop::DispatchResult tomo::IoLoop::parse_and_dispatch<true, 0u, false>(tomo::Client*) [clone .isra.0]
    HOT A T=respresume code 44->117 lanes=respresume eq=respresume tomo::IoLoop::DispatchResult tomo::IoLoop::parse_and_dispatch<true, 0u, false>(tomo::Client*) [clone .isra.0] 
    HOT B T=respresume code 18173->18386 lanes=respresume,mkfix eq=- tomo::IoLoop::DispatchResult tomo::IoLoop::parse_and_dispatch<true, 32u, false>(tomo::Client*)
    HOT B T=respresume code 18152->18389 lanes=respresume,mkfix eq=- tomo::IoLoop::DispatchResult tomo::IoLoop::r7_parse_and_dispatch<false, 32u, false>(tomo::Client*)
    HOT B T=respresume code 18281->18465 lanes=respresume,mkfix eq=- tomo::IoLoop::DispatchResult tomo::IoLoop::r7_parse_and_dispatch<true, 32u, false>(tomo::Client*)
    HOT A T=rlfix code 1675->2249 lanes=rlfix eq=rlfix tomo::ExLoopT<true>::prepare_local_read(tomo::Op&, tomo::FlatStore*, bool, tomo::FlatStore::ReadLocalPrefetchC
    HOT A T=PRE code 451->451 lanes=mkfix eq=mkfix tomo::IoLoop::init(tomo::Server*, tomo::ThreadCtx*, char const*, unsigned short, int, tomo::TlsContext const*,
    HOT A T=PRE code 451->451 lanes=mkfix eq=mkfix tomo::IoLoop::init(tomo::Server*, tomo::ThreadCtx*, char const*, unsigned short, int, tomo::TlsContext const*,
    C T=new code 2733->2733 lanes=- eq=- void tomo::IoLoop::adopt_client<false, false>(tomo::Client*, bool, bool)
    D T=new code 3581->3678 lanes=respresume eq=- tomo::IoLoop::close_client(tomo::Client*, bool)
    C T=new code 1668->1684 lanes=- eq=- bool tomo::IoLoop::r7_drive_tls<false, true>(tomo::Client*) [clone .isra.0]
    D T=new code 3557->3525 lanes=respresume eq=- tomo::IoLoop::lb_control_pass()
    C T=new code 1324->1068 lanes=- eq=- tomo::IoLoop::pubsub_append_ack(tomo::Op::Sink&, bool, bool, bool, std::__cxx11::basic_string<char, std::char_
    C T=new code 2094->1886 lanes=- eq=- tomo::IoLoop::deferred_timer_pass(unsigned long)
    C T=new code 2942->2797 lanes=- eq=- tomo::Server::flip_smt_pairing_error[abi:cxx11](unsigned int) const::{lambda(unsigned int)#1}::operator()(unsi
{"object": "src/core/reorder.o", "params": "--param inline-unit-growth=0 --param large-unit-insns=147520", "unit": 114487, "changed": 46, "hot_changed": 13, "A": 30, "B": 6, "C": 8, "D": 2, "hotA": 5, "hotB": 4, "hotCD": 4, "path": "/home/user/Projects/cx-wave3/build/wave3/trials/post/src_core_reorder.o.6afe799eefd9.o"}
    HOT C T=new code 2944->2881 lanes=- eq=- unsigned int tomo::IoLoop::r7_flush_ready<false, true, true, false, false, false>()
    HOT C T=new code 2960->2897 lanes=- eq=- unsigned int tomo::IoLoop::r7_flush_ready<false, true, true, false, true, false>()
    HOT C T=new code 2944->2881 lanes=- eq=- unsigned int tomo::IoLoop::r7_flush_ready<false, true, true, true, false, false>()
    HOT C T=new code 2960->2897 lanes=- eq=- unsigned int tomo::IoLoop::r7_flush_ready<false, true, true, true, true, false>()
    HOT B T=respresume code 18137->18373 lanes=respresume,mkfix eq=- tomo::IoLoop::DispatchResult tomo::IoLoop::parse_and_dispatch<false, 32u, false>(tomo::Client*)
    HOT A T=respresume code 9784->9925 lanes=respresume eq=respresume tomo::IoLoop::DispatchResult tomo::IoLoop::parse_and_dispatch<true, 0u, false>(tomo::Client*) [clone .isra.0]
    HOT A T=respresume code 44->117 lanes=respresume eq=respresume tomo::IoLoop::DispatchResult tomo::IoLoop::parse_and_dispatch<true, 0u, false>(tomo::Client*) [clone .isra.0] 
    HOT B T=respresume code 18173->18386 lanes=respresume,mkfix eq=- tomo::IoLoop::DispatchResult tomo::IoLoop::parse_and_dispatch<true, 32u, false>(tomo::Client*)
    HOT B T=respresume code 18152->18389 lanes=respresume,mkfix eq=- tomo::IoLoop::DispatchResult tomo::IoLoop::r7_parse_and_dispatch<false, 32u, false>(tomo::Client*)
    HOT B T=respresume code 18281->18465 lanes=respresume,mkfix eq=- tomo::IoLoop::DispatchResult tomo::IoLoop::r7_parse_and_dispatch<true, 32u, false>(tomo::Client*)
    HOT A T=rlfix code 1675->2249 lanes=rlfix eq=rlfix tomo::ExLoopT<true>::prepare_local_read(tomo::Op&, tomo::FlatStore*, bool, tomo::FlatStore::ReadLocalPrefetchC
    HOT A T=PRE code 451->451 lanes=mkfix eq=mkfix tomo::IoLoop::init(tomo::Server*, tomo::ThreadCtx*, char const*, unsigned short, int, tomo::TlsContext const*,
    HOT A T=PRE code 451->451 lanes=mkfix eq=mkfix tomo::IoLoop::init(tomo::Server*, tomo::ThreadCtx*, char const*, unsigned short, int, tomo::TlsContext const*,
    C T=new code 2733->2733 lanes=- eq=- void tomo::IoLoop::adopt_client<false, false>(tomo::Client*, bool, bool)
    D T=new code 3581->3678 lanes=respresume eq=- tomo::IoLoop::close_client(tomo::Client*, bool)
    C T=new code 1668->1684 lanes=- eq=- bool tomo::IoLoop::r7_drive_tls<false, true>(tomo::Client*) [clone .isra.0]
    D T=new code 3557->3525 lanes=respresume eq=- tomo::IoLoop::lb_control_pass()
    C T=new code 1324->1068 lanes=- eq=- tomo::IoLoop::pubsub_append_ack(tomo::Op::Sink&, bool, bool, bool, std::__cxx11::basic_string<char, std::char_
    C T=new code 2942->2797 lanes=- eq=- tomo::Server::flip_smt_pairing_error[abi:cxx11](unsigned int) const::{lambda(unsigned int)#1}::operator()(unsi
{"object": "src/core/reorder.o", "params": "--param inline-unit-growth=0 --param large-unit-insns=147540", "unit": 114487, "changed": 43, "hot_changed": 10, "A": 30, "B": 6, "C": 5, "D": 2, "hotA": 5, "hotB": 4, "hotCD": 1, "path": "/home/user/Projects/cx-wave3/build/wave3/trials/post/src_core_reorder.o.fcea1ef28b4a.o"}
    HOT C T=new code 2960->2897 lanes=- eq=- unsigned int tomo::IoLoop::r7_flush_ready<false, true, true, false, true, false>()
    HOT B T=respresume code 18137->18373 lanes=respresume,mkfix eq=- tomo::IoLoop::DispatchResult tomo::IoLoop::parse_and_dispatch<false, 32u, false>(tomo::Client*)
    HOT A T=respresume code 9784->9925 lanes=respresume eq=respresume tomo::IoLoop::DispatchResult tomo::IoLoop::parse_and_dispatch<true, 0u, false>(tomo::Client*) [clone .isra.0]
    HOT A T=respresume code 44->117 lanes=respresume eq=respresume tomo::IoLoop::DispatchResult tomo::IoLoop::parse_and_dispatch<true, 0u, false>(tomo::Client*) [clone .isra.0] 
    HOT B T=respresume code 18173->18386 lanes=respresume,mkfix eq=- tomo::IoLoop::DispatchResult tomo::IoLoop::parse_and_dispatch<true, 32u, false>(tomo::Client*)
    HOT B T=respresume code 18152->18389 lanes=respresume,mkfix eq=- tomo::IoLoop::DispatchResult tomo::IoLoop::r7_parse_and_dispatch<false, 32u, false>(tomo::Client*)
    HOT B T=respresume code 18281->18465 lanes=respresume,mkfix eq=- tomo::IoLoop::DispatchResult tomo::IoLoop::r7_parse_and_dispatch<true, 32u, false>(tomo::Client*)
    HOT A T=rlfix code 1675->2249 lanes=rlfix eq=rlfix tomo::ExLoopT<true>::prepare_local_read(tomo::Op&, tomo::FlatStore*, bool, tomo::FlatStore::ReadLocalPrefetchC
    HOT A T=PRE code 451->451 lanes=mkfix eq=mkfix tomo::IoLoop::init(tomo::Server*, tomo::ThreadCtx*, char const*, unsigned short, int, tomo::TlsContext const*,
    HOT A T=PRE code 451->451 lanes=mkfix eq=mkfix tomo::IoLoop::init(tomo::Server*, tomo::ThreadCtx*, char const*, unsigned short, int, tomo::TlsContext const*,
    C T=new code 2733->2733 lanes=- eq=- void tomo::IoLoop::adopt_client<false, false>(tomo::Client*, bool, bool)
    D T=new code 3581->3678 lanes=respresume eq=- tomo::IoLoop::close_client(tomo::Client*, bool)
    C T=new code 1668->1684 lanes=- eq=- bool tomo::IoLoop::r7_drive_tls<false, true>(tomo::Client*) [clone .isra.0]
    D T=new code 3557->3525 lanes=respresume eq=- tomo::IoLoop::lb_control_pass()
    C T=new code 1324->1068 lanes=- eq=- tomo::IoLoop::pubsub_append_ack(tomo::Op::Sink&, bool, bool, bool, std::__cxx11::basic_string<char, std::char_
    C T=new code 2942->2797 lanes=- eq=- tomo::Server::flip_smt_pairing_error[abi:cxx11](unsigned int) const::{lambda(unsigned int)#1}::operator()(unsi
{"object": "src/core/reorder.o", "params": "--param inline-unit-growth=0 --param large-unit-insns=147560", "unit": 114487, "changed": 44, "hot_changed": 12, "A": 30, "B": 6, "C": 6, "D": 2, "hotA": 5, "hotB": 4, "hotCD": 3, "path": "/home/user/Projects/cx-wave3/build/wave3/trials/post/src_core_reorder.o.0ea8c0e8fd91.o"}
    HOT C T=new code 2944->2881 lanes=- eq=- unsigned int tomo::IoLoop::r7_flush_ready<false, true, true, false, false, false>()
    HOT C T=new code 2960->2897 lanes=- eq=- unsigned int tomo::IoLoop::r7_flush_ready<false, true, true, false, true, false>()
    HOT C T=new code 2944->2881 lanes=- eq=- unsigned int tomo::IoLoop::r7_flush_ready<false, true, true, true, false, false>()
    HOT B T=respresume code 18137->18373 lanes=respresume,mkfix eq=- tomo::IoLoop::DispatchResult tomo::IoLoop::parse_and_dispatch<false, 32u, false>(tomo::Client*)
    HOT A T=respresume code 9784->9925 lanes=respresume eq=respresume tomo::IoLoop::DispatchResult tomo::IoLoop::parse_and_dispatch<true, 0u, false>(tomo::Client*) [clone .isra.0]
    HOT A T=respresume code 44->117 lanes=respresume eq=respresume tomo::IoLoop::DispatchResult tomo::IoLoop::parse_and_dispatch<true, 0u, false>(tomo::Client*) [clone .isra.0] 
    HOT B T=respresume code 18173->18386 lanes=respresume,mkfix eq=- tomo::IoLoop::DispatchResult tomo::IoLoop::parse_and_dispatch<true, 32u, false>(tomo::Client*)
    HOT B T=respresume code 18152->18389 lanes=respresume,mkfix eq=- tomo::IoLoop::DispatchResult tomo::IoLoop::r7_parse_and_dispatch<false, 32u, false>(tomo::Client*)
    HOT B T=respresume code 18281->18465 lanes=respresume,mkfix eq=- tomo::IoLoop::DispatchResult tomo::IoLoop::r7_parse_and_dispatch<true, 32u, false>(tomo::Client*)
    HOT A T=rlfix code 1675->2249 lanes=rlfix eq=rlfix tomo::ExLoopT<true>::prepare_local_read(tomo::Op&, tomo::FlatStore*, bool, tomo::FlatStore::ReadLocalPrefetchC
    HOT A T=PRE code 451->451 lanes=mkfix eq=mkfix tomo::IoLoop::init(tomo::Server*, tomo::ThreadCtx*, char const*, unsigned short, int, tomo::TlsContext const*,
    HOT A T=PRE code 451->451 lanes=mkfix eq=mkfix tomo::IoLoop::init(tomo::Server*, tomo::ThreadCtx*, char const*, unsigned short, int, tomo::TlsContext const*,
    C T=new code 2733->2733 lanes=- eq=- void tomo::IoLoop::adopt_client<false, false>(tomo::Client*, bool, bool)
    D T=new code 3581->3678 lanes=respresume eq=- tomo::IoLoop::close_client(tomo::Client*, bool)
    C T=new code 1668->1684 lanes=- eq=- bool tomo::IoLoop::r7_drive_tls<false, true>(tomo::Client*) [clone .isra.0]
    D T=new code 3557->3525 lanes=respresume eq=- tomo::IoLoop::lb_control_pass()
    C T=new code 1324->1068 lanes=- eq=- tomo::IoLoop::pubsub_append_ack(tomo::Op::Sink&, bool, bool, bool, std::__cxx11::basic_string<char, std::char_
{"object": "src/core/reorder.o", "params": "--param inline-unit-growth=0 --param large-unit-insns=147580", "unit": 114487, "changed": 41, "hot_changed": 9, "A": 30, "B": 6, "C": 3, "D": 2, "hotA": 5, "hotB": 4, "hotCD": 0, "path": "/home/user/Projects/cx-wave3/build/wave3/trials/post/src_core_reorder.o.825efa1db9e7.o"}
    HOT B T=respresume code 18137->18373 lanes=respresume,mkfix eq=- tomo::IoLoop::DispatchResult tomo::IoLoop::parse_and_dispatch<false, 32u, false>(tomo::Client*)
    HOT A T=respresume code 9784->9925 lanes=respresume eq=respresume tomo::IoLoop::DispatchResult tomo::IoLoop::parse_and_dispatch<true, 0u, false>(tomo::Client*) [clone .isra.0]
    HOT A T=respresume code 44->117 lanes=respresume eq=respresume tomo::IoLoop::DispatchResult tomo::IoLoop::parse_and_dispatch<true, 0u, false>(tomo::Client*) [clone .isra.0] 
    HOT B T=respresume code 18173->18386 lanes=respresume,mkfix eq=- tomo::IoLoop::DispatchResult tomo::IoLoop::parse_and_dispatch<true, 32u, false>(tomo::Client*)
    HOT B T=respresume code 18152->18389 lanes=respresume,mkfix eq=- tomo::IoLoop::DispatchResult tomo::IoLoop::r7_parse_and_dispatch<false, 32u, false>(tomo::Client*)
    HOT B T=respresume code 18281->18465 lanes=respresume,mkfix eq=- tomo::IoLoop::DispatchResult tomo::IoLoop::r7_parse_and_dispatch<true, 32u, false>(tomo::Client*)
    HOT A T=rlfix code 1675->2249 lanes=rlfix eq=rlfix tomo::ExLoopT<true>::prepare_local_read(tomo::Op&, tomo::FlatStore*, bool, tomo::FlatStore::ReadLocalPrefetchC
    HOT A T=PRE code 451->451 lanes=mkfix eq=mkfix tomo::IoLoop::init(tomo::Server*, tomo::ThreadCtx*, char const*, unsigned short, int, tomo::TlsContext const*,
    HOT A T=PRE code 451->451 lanes=mkfix eq=mkfix tomo::IoLoop::init(tomo::Server*, tomo::ThreadCtx*, char const*, unsigned short, int, tomo::TlsContext const*,
    C T=new code 2733->2733 lanes=- eq=- void tomo::IoLoop::adopt_client<false, false>(tomo::Client*, bool, bool)
    D T=new code 3581->3678 lanes=respresume eq=- tomo::IoLoop::close_client(tomo::Client*, bool)
    C T=new code 1668->1684 lanes=- eq=- bool tomo::IoLoop::r7_drive_tls<false, true>(tomo::Client*) [clone .isra.0]
    D T=new code 3557->3525 lanes=respresume eq=- tomo::IoLoop::lb_control_pass()
    C T=new code 1324->1068 lanes=- eq=- tomo::IoLoop::pubsub_append_ack(tomo::Op::Sink&, bool, bool, bool, std::__cxx11::basic_string<char, std::char_
{"object": "src/core/reorder.o", "params": "--param inline-unit-growth=0 --param large-unit-insns=147600", "unit": 114487, "changed": 43, "hot_changed": 12, "A": 30, "B": 6, "C": 5, "D": 2, "hotA": 5, "hotB": 4, "hotCD": 3, "path": "/home/user/Projects/cx-wave3/build/wave3/trials/post/src_core_reorder.o.d28e7a71cf8b.o"}
    HOT C T=new code 2944->2881 lanes=- eq=- unsigned int tomo::IoLoop::r7_flush_ready<false, true, true, false, false, false>()
    HOT C T=new code 2960->2897 lanes=- eq=- unsigned int tomo::IoLoop::r7_flush_ready<false, true, true, false, true, false>()
    HOT C T=new code 2944->2881 lanes=- eq=- unsigned int tomo::IoLoop::r7_flush_ready<false, true, true, true, false, false>()
    HOT B T=respresume code 18137->18373 lanes=respresume,mkfix eq=- tomo::IoLoop::DispatchResult tomo::IoLoop::parse_and_dispatch<false, 32u, false>(tomo::Client*)
    HOT A T=respresume code 9784->9925 lanes=respresume eq=respresume tomo::IoLoop::DispatchResult tomo::IoLoop::parse_and_dispatch<true, 0u, false>(tomo::Client*) [clone .isra.0]
    HOT A T=respresume code 44->117 lanes=respresume eq=respresume tomo::IoLoop::DispatchResult tomo::IoLoop::parse_and_dispatch<true, 0u, false>(tomo::Client*) [clone .isra.0] 
    HOT B T=respresume code 18173->18386 lanes=respresume,mkfix eq=- tomo::IoLoop::DispatchResult tomo::IoLoop::parse_and_dispatch<true, 32u, false>(tomo::Client*)
    HOT B T=respresume code 18152->18389 lanes=respresume,mkfix eq=- tomo::IoLoop::DispatchResult tomo::IoLoop::r7_parse_and_dispatch<false, 32u, false>(tomo::Client*)
    HOT B T=respresume code 18281->18465 lanes=respresume,mkfix eq=- tomo::IoLoop::DispatchResult tomo::IoLoop::r7_parse_and_dispatch<true, 32u, false>(tomo::Client*)
    HOT A T=rlfix code 1675->2249 lanes=rlfix eq=rlfix tomo::ExLoopT<true>::prepare_local_read(tomo::Op&, tomo::FlatStore*, bool, tomo::FlatStore::ReadLocalPrefetchC
    HOT A T=PRE code 451->451 lanes=mkfix eq=mkfix tomo::IoLoop::init(tomo::Server*, tomo::ThreadCtx*, char const*, unsigned short, int, tomo::TlsContext const*,
    HOT A T=PRE code 451->451 lanes=mkfix eq=mkfix tomo::IoLoop::init(tomo::Server*, tomo::ThreadCtx*, char const*, unsigned short, int, tomo::TlsContext const*,
    C T=new code 2733->2733 lanes=- eq=- void tomo::IoLoop::adopt_client<false, false>(tomo::Client*, bool, bool)
    D T=new code 3581->3678 lanes=respresume eq=- tomo::IoLoop::close_client(tomo::Client*, bool)
    C T=new code 1668->1684 lanes=- eq=- bool tomo::IoLoop::r7_drive_tls<false, true>(tomo::Client*) [clone .isra.0]
    D T=new code 3557->3525 lanes=respresume eq=- tomo::IoLoop::lb_control_pass()
{"object": "src/core/reorder.o", "params": "--param inline-unit-growth=0 --param large-unit-insns=147620", "unit": 114487, "changed": 40, "hot_changed": 9, "A": 30, "B": 6, "C": 2, "D": 2, "hotA": 5, "hotB": 4, "hotCD": 0, "path": "/home/user/Projects/cx-wave3/build/wave3/trials/post/src_core_reorder.o.d6e9030411d1.o"}
    HOT B T=respresume code 18137->18373 lanes=respresume,mkfix eq=- tomo::IoLoop::DispatchResult tomo::IoLoop::parse_and_dispatch<false, 32u, false>(tomo::Client*)
    HOT A T=respresume code 9784->9925 lanes=respresume eq=respresume tomo::IoLoop::DispatchResult tomo::IoLoop::parse_and_dispatch<true, 0u, false>(tomo::Client*) [clone .isra.0]
    HOT A T=respresume code 44->117 lanes=respresume eq=respresume tomo::IoLoop::DispatchResult tomo::IoLoop::parse_and_dispatch<true, 0u, false>(tomo::Client*) [clone .isra.0] 
    HOT B T=respresume code 18173->18386 lanes=respresume,mkfix eq=- tomo::IoLoop::DispatchResult tomo::IoLoop::parse_and_dispatch<true, 32u, false>(tomo::Client*)
    HOT B T=respresume code 18152->18389 lanes=respresume,mkfix eq=- tomo::IoLoop::DispatchResult tomo::IoLoop::r7_parse_and_dispatch<false, 32u, false>(tomo::Client*)
    HOT B T=respresume code 18281->18465 lanes=respresume,mkfix eq=- tomo::IoLoop::DispatchResult tomo::IoLoop::r7_parse_and_dispatch<true, 32u, false>(tomo::Client*)
    HOT A T=rlfix code 1675->2249 lanes=rlfix eq=rlfix tomo::ExLoopT<true>::prepare_local_read(tomo::Op&, tomo::FlatStore*, bool, tomo::FlatStore::ReadLocalPrefetchC
    HOT A T=PRE code 451->451 lanes=mkfix eq=mkfix tomo::IoLoop::init(tomo::Server*, tomo::ThreadCtx*, char const*, unsigned short, int, tomo::TlsContext const*,
    HOT A T=PRE code 451->451 lanes=mkfix eq=mkfix tomo::IoLoop::init(tomo::Server*, tomo::ThreadCtx*, char const*, unsigned short, int, tomo::TlsContext const*,
    C T=new code 2733->2733 lanes=- eq=- void tomo::IoLoop::adopt_client<false, false>(tomo::Client*, bool, bool)
    D T=new code 3581->3678 lanes=respresume eq=- tomo::IoLoop::close_client(tomo::Client*, bool)
    C T=new code 1668->1684 lanes=- eq=- bool tomo::IoLoop::r7_drive_tls<false, true>(tomo::Client*) [clone .isra.0]
    D T=new code 3557->3525 lanes=respresume eq=- tomo::IoLoop::lb_control_pass()
{"object": "src/core/reorder.o", "params": "--param inline-unit-growth=0 --param large-unit-insns=147640", "unit": 114487, "changed": 40, "hot_changed": 9, "A": 31, "B": 6, "C": 2, "D": 1, "hotA": 5, "hotB": 4, "hotCD": 0, "path": "/home/user/Projects/cx-wave3/build/wave3/trials/post/src_core_reorder.o.691c4e80c580.o"}
    HOT B T=respresume code 18137->18373 lanes=respresume,mkfix eq=- tomo::IoLoop::DispatchResult tomo::IoLoop::parse_and_dispatch<false, 32u, false>(tomo::Client*)
    HOT A T=respresume code 9784->9925 lanes=respresume eq=respresume tomo::IoLoop::DispatchResult tomo::IoLoop::parse_and_dispatch<true, 0u, false>(tomo::Client*) [clone .isra.0]
    HOT A T=respresume code 44->117 lanes=respresume eq=respresume tomo::IoLoop::DispatchResult tomo::IoLoop::parse_and_dispatch<true, 0u, false>(tomo::Client*) [clone .isra.0] 
    HOT B T=respresume code 18173->18386 lanes=respresume,mkfix eq=- tomo::IoLoop::DispatchResult tomo::IoLoop::parse_and_dispatch<true, 32u, false>(tomo::Client*)
    HOT B T=respresume code 18152->18389 lanes=respresume,mkfix eq=- tomo::IoLoop::DispatchResult tomo::IoLoop::r7_parse_and_dispatch<false, 32u, false>(tomo::Client*)
    HOT B T=respresume code 18281->18465 lanes=respresume,mkfix eq=- tomo::IoLoop::DispatchResult tomo::IoLoop::r7_parse_and_dispatch<true, 32u, false>(tomo::Client*)
    HOT A T=rlfix code 1675->2249 lanes=rlfix eq=rlfix tomo::ExLoopT<true>::prepare_local_read(tomo::Op&, tomo::FlatStore*, bool, tomo::FlatStore::ReadLocalPrefetchC
    HOT A T=PRE code 451->451 lanes=mkfix eq=mkfix tomo::IoLoop::init(tomo::Server*, tomo::ThreadCtx*, char const*, unsigned short, int, tomo::TlsContext const*,
    HOT A T=PRE code 451->451 lanes=mkfix eq=mkfix tomo::IoLoop::init(tomo::Server*, tomo::ThreadCtx*, char const*, unsigned short, int, tomo::TlsContext const*,
    C T=new code 2733->2733 lanes=- eq=- void tomo::IoLoop::adopt_client<false, false>(tomo::Client*, bool, bool)
    C T=new code 1668->1684 lanes=- eq=- bool tomo::IoLoop::r7_drive_tls<false, true>(tomo::Client*) [clone .isra.0]
    D T=new code 3557->3525 lanes=respresume eq=- tomo::IoLoop::lb_control_pass()
{"object": "src/core/reorder.o", "params": "--param inline-unit-growth=0 --param large-unit-insns=147660", "unit": 114487, "changed": 38, "hot_changed": 9, "A": 31, "B": 6, "C": 1, "D": 0, "hotA": 5, "hotB": 4, "hotCD": 0, "path": "/home/user/Projects/cx-wave3/build/wave3/trials/post/src_core_reorder.o.6ffc7030ffc2.o"}
    HOT B T=respresume code 18137->18373 lanes=respresume,mkfix eq=- tomo::IoLoop::DispatchResult tomo::IoLoop::parse_and_dispatch<false, 32u, false>(tomo::Client*)
    HOT A T=respresume code 9784->9925 lanes=respresume eq=respresume tomo::IoLoop::DispatchResult tomo::IoLoop::parse_and_dispatch<true, 0u, false>(tomo::Client*) [clone .isra.0]
    HOT A T=respresume code 44->117 lanes=respresume eq=respresume tomo::IoLoop::DispatchResult tomo::IoLoop::parse_and_dispatch<true, 0u, false>(tomo::Client*) [clone .isra.0] 
    HOT B T=respresume code 18173->18386 lanes=respresume,mkfix eq=- tomo::IoLoop::DispatchResult tomo::IoLoop::parse_and_dispatch<true, 32u, false>(tomo::Client*)
    HOT B T=respresume code 18152->18389 lanes=respresume,mkfix eq=- tomo::IoLoop::DispatchResult tomo::IoLoop::r7_parse_and_dispatch<false, 32u, false>(tomo::Client*)
    HOT B T=respresume code 18281->18465 lanes=respresume,mkfix eq=- tomo::IoLoop::DispatchResult tomo::IoLoop::r7_parse_and_dispatch<true, 32u, false>(tomo::Client*)
    HOT A T=rlfix code 1675->2249 lanes=rlfix eq=rlfix tomo::ExLoopT<true>::prepare_local_read(tomo::Op&, tomo::FlatStore*, bool, tomo::FlatStore::ReadLocalPrefetchC
    HOT A T=PRE code 451->451 lanes=mkfix eq=mkfix tomo::IoLoop::init(tomo::Server*, tomo::ThreadCtx*, char const*, unsigned short, int, tomo::TlsContext const*,
    HOT A T=PRE code 451->451 lanes=mkfix eq=mkfix tomo::IoLoop::init(tomo::Server*, tomo::ThreadCtx*, char const*, unsigned short, int, tomo::TlsContext const*,
    C T=new code 1668->1684 lanes=- eq=- bool tomo::IoLoop::r7_drive_tls<false, true>(tomo::Client*) [clone .isra.0]
{"object": "src/core/reorder.o", "params": "--param inline-unit-growth=0 --param large-unit-insns=147680", "unit": 114487, "changed": 40, "hot_changed": 9, "A": 31, "B": 6, "C": 2, "D": 1, "hotA": 5, "hotB": 4, "hotCD": 0, "path": "/home/user/Projects/cx-wave3/build/wave3/trials/post/src_core_reorder.o.3b998559dd53.o"}
    HOT B T=respresume code 18137->18373 lanes=respresume,mkfix eq=- tomo::IoLoop::DispatchResult tomo::IoLoop::parse_and_dispatch<false, 32u, false>(tomo::Client*)
    HOT A T=respresume code 9784->9925 lanes=respresume eq=respresume tomo::IoLoop::DispatchResult tomo::IoLoop::parse_and_dispatch<true, 0u, false>(tomo::Client*) [clone .isra.0]
    HOT A T=respresume code 44->117 lanes=respresume eq=respresume tomo::IoLoop::DispatchResult tomo::IoLoop::parse_and_dispatch<true, 0u, false>(tomo::Client*) [clone .isra.0] 
    HOT B T=respresume code 18173->18386 lanes=respresume,mkfix eq=- tomo::IoLoop::DispatchResult tomo::IoLoop::parse_and_dispatch<true, 32u, false>(tomo::Client*)
    HOT B T=respresume code 18152->18389 lanes=respresume,mkfix eq=- tomo::IoLoop::DispatchResult tomo::IoLoop::r7_parse_and_dispatch<false, 32u, false>(tomo::Client*)
    HOT B T=respresume code 18281->18465 lanes=respresume,mkfix eq=- tomo::IoLoop::DispatchResult tomo::IoLoop::r7_parse_and_dispatch<true, 32u, false>(tomo::Client*)
    HOT A T=rlfix code 1675->2249 lanes=rlfix eq=rlfix tomo::ExLoopT<true>::prepare_local_read(tomo::Op&, tomo::FlatStore*, bool, tomo::FlatStore::ReadLocalPrefetchC
    HOT A T=PRE code 451->451 lanes=mkfix eq=mkfix tomo::IoLoop::init(tomo::Server*, tomo::ThreadCtx*, char const*, unsigned short, int, tomo::TlsContext const*,
    HOT A T=PRE code 451->451 lanes=mkfix eq=mkfix tomo::IoLoop::init(tomo::Server*, tomo::ThreadCtx*, char const*, unsigned short, int, tomo::TlsContext const*,
    C T=new code 2733->2733 lanes=- eq=- void tomo::IoLoop::adopt_client<false, false>(tomo::Client*, bool, bool)
    C T=new code 1668->1684 lanes=- eq=- bool tomo::IoLoop::r7_drive_tls<false, true>(tomo::Client*) [clone .isra.0]
    D T=new code 3557->3525 lanes=respresume eq=- tomo::IoLoop::lb_control_pass()
{"object": "src/core/reorder.o", "params": "--param inline-unit-growth=0 --param large-unit-insns=147700", "unit": 114487, "changed": 38, "hot_changed": 9, "A": 31, "B": 6, "C": 1, "D": 0, "hotA": 5, "hotB": 4, "hotCD": 0, "path": "/home/user/Projects/cx-wave3/build/wave3/trials/post/src_core_reorder.o.47476aa0e079.o"}
    HOT B T=respresume code 18137->18373 lanes=respresume,mkfix eq=- tomo::IoLoop::DispatchResult tomo::IoLoop::parse_and_dispatch<false, 32u, false>(tomo::Client*)
    HOT A T=respresume code 9784->9925 lanes=respresume eq=respresume tomo::IoLoop::DispatchResult tomo::IoLoop::parse_and_dispatch<true, 0u, false>(tomo::Client*) [clone .isra.0]
    HOT A T=respresume code 44->117 lanes=respresume eq=respresume tomo::IoLoop::DispatchResult tomo::IoLoop::parse_and_dispatch<true, 0u, false>(tomo::Client*) [clone .isra.0] 
    HOT B T=respresume code 18173->18386 lanes=respresume,mkfix eq=- tomo::IoLoop::DispatchResult tomo::IoLoop::parse_and_dispatch<true, 32u, false>(tomo::Client*)
    HOT B T=respresume code 18152->18389 lanes=respresume,mkfix eq=- tomo::IoLoop::DispatchResult tomo::IoLoop::r7_parse_and_dispatch<false, 32u, false>(tomo::Client*)
    HOT B T=respresume code 18281->18465 lanes=respresume,mkfix eq=- tomo::IoLoop::DispatchResult tomo::IoLoop::r7_parse_and_dispatch<true, 32u, false>(tomo::Client*)
    HOT A T=rlfix code 1675->2249 lanes=rlfix eq=rlfix tomo::ExLoopT<true>::prepare_local_read(tomo::Op&, tomo::FlatStore*, bool, tomo::FlatStore::ReadLocalPrefetchC
    HOT A T=PRE code 451->451 lanes=mkfix eq=mkfix tomo::IoLoop::init(tomo::Server*, tomo::ThreadCtx*, char const*, unsigned short, int, tomo::TlsContext const*,
    HOT A T=PRE code 451->451 lanes=mkfix eq=mkfix tomo::IoLoop::init(tomo::Server*, tomo::ThreadCtx*, char const*, unsigned short, int, tomo::TlsContext const*,
    C T=new code 1668->1684 lanes=- eq=- bool tomo::IoLoop::r7_drive_tls<false, true>(tomo::Client*) [clone .isra.0]
{"object": "src/core/reorder.o", "params": "--param inline-unit-growth=0 --param large-unit-insns=147720", "unit": 114487, "changed": 39, "hot_changed": 9, "A": 32, "B": 6, "C": 0, "D": 1, "hotA": 5, "hotB": 4, "hotCD": 0, "path": "/home/user/Projects/cx-wave3/build/wave3/trials/post/src_core_reorder.o.ffa750b3ab4b.o"}
    HOT B T=respresume code 18137->18373 lanes=respresume,mkfix eq=- tomo::IoLoop::DispatchResult tomo::IoLoop::parse_and_dispatch<false, 32u, false>(tomo::Client*)
    HOT A T=respresume code 9784->9925 lanes=respresume eq=respresume tomo::IoLoop::DispatchResult tomo::IoLoop::parse_and_dispatch<true, 0u, false>(tomo::Client*) [clone .isra.0]
    HOT A T=respresume code 44->117 lanes=respresume eq=respresume tomo::IoLoop::DispatchResult tomo::IoLoop::parse_and_dispatch<true, 0u, false>(tomo::Client*) [clone .isra.0] 
    HOT B T=respresume code 18173->18386 lanes=respresume,mkfix eq=- tomo::IoLoop::DispatchResult tomo::IoLoop::parse_and_dispatch<true, 32u, false>(tomo::Client*)
    HOT B T=respresume code 18152->18389 lanes=respresume,mkfix eq=- tomo::IoLoop::DispatchResult tomo::IoLoop::r7_parse_and_dispatch<false, 32u, false>(tomo::Client*)
    HOT B T=respresume code 18281->18465 lanes=respresume,mkfix eq=- tomo::IoLoop::DispatchResult tomo::IoLoop::r7_parse_and_dispatch<true, 32u, false>(tomo::Client*)
    HOT A T=rlfix code 1675->2249 lanes=rlfix eq=rlfix tomo::ExLoopT<true>::prepare_local_read(tomo::Op&, tomo::FlatStore*, bool, tomo::FlatStore::ReadLocalPrefetchC
    HOT A T=PRE code 451->451 lanes=mkfix eq=mkfix tomo::IoLoop::init(tomo::Server*, tomo::ThreadCtx*, char const*, unsigned short, int, tomo::TlsContext const*,
    HOT A T=PRE code 451->451 lanes=mkfix eq=mkfix tomo::IoLoop::init(tomo::Server*, tomo::ThreadCtx*, char const*, unsigned short, int, tomo::TlsContext const*,
    D T=respresume code 2047->2112 lanes=respresume eq=- void tomo::IoLoop::adopt_client<true, false>(tomo::Client*, bool, bool)
{"object": "src/core/reorder.o", "params": "--param inline-unit-growth=0 --param large-unit-insns=147740", "unit": 114487, "changed": 38, "hot_changed": 9, "A": 31, "B": 6, "C": 1, "D": 0, "hotA": 5, "hotB": 4, "hotCD": 0, "path": "/home/user/Projects/cx-wave3/build/wave3/trials/post/src_core_reorder.o.520ed7168601.o"}
    HOT B T=respresume code 18137->18373 lanes=respresume,mkfix eq=- tomo::IoLoop::DispatchResult tomo::IoLoop::parse_and_dispatch<false, 32u, false>(tomo::Client*)
    HOT A T=respresume code 9784->9925 lanes=respresume eq=respresume tomo::IoLoop::DispatchResult tomo::IoLoop::parse_and_dispatch<true, 0u, false>(tomo::Client*) [clone .isra.0]
    HOT A T=respresume code 44->117 lanes=respresume eq=respresume tomo::IoLoop::DispatchResult tomo::IoLoop::parse_and_dispatch<true, 0u, false>(tomo::Client*) [clone .isra.0] 
    HOT B T=respresume code 18173->18386 lanes=respresume,mkfix eq=- tomo::IoLoop::DispatchResult tomo::IoLoop::parse_and_dispatch<true, 32u, false>(tomo::Client*)
    HOT B T=respresume code 18152->18389 lanes=respresume,mkfix eq=- tomo::IoLoop::DispatchResult tomo::IoLoop::r7_parse_and_dispatch<false, 32u, false>(tomo::Client*)
    HOT B T=respresume code 18281->18465 lanes=respresume,mkfix eq=- tomo::IoLoop::DispatchResult tomo::IoLoop::r7_parse_and_dispatch<true, 32u, false>(tomo::Client*)
    HOT A T=rlfix code 1675->2249 lanes=rlfix eq=rlfix tomo::ExLoopT<true>::prepare_local_read(tomo::Op&, tomo::FlatStore*, bool, tomo::FlatStore::ReadLocalPrefetchC
    HOT A T=PRE code 451->451 lanes=mkfix eq=mkfix tomo::IoLoop::init(tomo::Server*, tomo::ThreadCtx*, char const*, unsigned short, int, tomo::TlsContext const*,
    HOT A T=PRE code 451->451 lanes=mkfix eq=mkfix tomo::IoLoop::init(tomo::Server*, tomo::ThreadCtx*, char const*, unsigned short, int, tomo::TlsContext const*,
    C T=new code 1668->1684 lanes=- eq=- bool tomo::IoLoop::r7_drive_tls<false, true>(tomo::Client*) [clone .isra.0]
{"object": "src/core/reorder.o", "params": "--param inline-unit-growth=0 --param large-unit-insns=147760", "unit": 114487, "changed": 37, "hot_changed": 9, "A": 30, "B": 5, "C": 0, "D": 2, "hotA": 3, "hotB": 4, "hotCD": 2, "path": "/home/user/Projects/cx-wave3/build/wave3/trials/post/src_core_reorder.o.c2373e2ba94b.o"}
    HOT B T=respresume code 18137->18373 lanes=respresume,mkfix eq=- tomo::IoLoop::DispatchResult tomo::IoLoop::parse_and_dispatch<false, 32u, false>(tomo::Client*)
    HOT D T=new code 9784->9976 lanes=respresume eq=- tomo::IoLoop::DispatchResult tomo::IoLoop::parse_and_dispatch<true, 0u, false>(tomo::Client*) [clone .isra.0]
    HOT D T=respresume code 44->117 lanes=respresume eq=- tomo::IoLoop::DispatchResult tomo::IoLoop::parse_and_dispatch<true, 0u, false>(tomo::Client*) [clone .isra.0] 
    HOT B T=respresume code 18173->18386 lanes=respresume,mkfix eq=- tomo::IoLoop::DispatchResult tomo::IoLoop::parse_and_dispatch<true, 32u, false>(tomo::Client*)
    HOT B T=respresume code 18152->18389 lanes=respresume,mkfix eq=- tomo::IoLoop::DispatchResult tomo::IoLoop::r7_parse_and_dispatch<false, 32u, false>(tomo::Client*)
    HOT B T=respresume code 18281->18465 lanes=respresume,mkfix eq=- tomo::IoLoop::DispatchResult tomo::IoLoop::r7_parse_and_dispatch<true, 32u, false>(tomo::Client*)
    HOT A T=rlfix code 1675->2249 lanes=rlfix eq=rlfix tomo::ExLoopT<true>::prepare_local_read(tomo::Op&, tomo::FlatStore*, bool, tomo::FlatStore::ReadLocalPrefetchC
    HOT A T=PRE code 451->451 lanes=mkfix eq=mkfix tomo::IoLoop::init(tomo::Server*, tomo::ThreadCtx*, char const*, unsigned short, int, tomo::TlsContext const*,
    HOT A T=PRE code 451->451 lanes=mkfix eq=mkfix tomo::IoLoop::init(tomo::Server*, tomo::ThreadCtx*, char const*, unsigned short, int, tomo::TlsContext const*,
{"object": "src/core/reorder.o", "params": "--param inline-unit-growth=0 --param large-unit-insns=147780", "unit": 114487, "changed": 38, "hot_changed": 9, "A": 31, "B": 6, "C": 1, "D": 0, "hotA": 5, "hotB": 4, "hotCD": 0, "path": "/home/user/Projects/cx-wave3/build/wave3/trials/post/src_core_reorder.o.919a908bb1fa.o"}
    HOT B T=respresume code 18137->18373 lanes=respresume,mkfix eq=- tomo::IoLoop::DispatchResult tomo::IoLoop::parse_and_dispatch<false, 32u, false>(tomo::Client*)
    HOT A T=respresume code 9784->9925 lanes=respresume eq=respresume tomo::IoLoop::DispatchResult tomo::IoLoop::parse_and_dispatch<true, 0u, false>(tomo::Client*) [clone .isra.0]
    HOT A T=respresume code 44->117 lanes=respresume eq=respresume tomo::IoLoop::DispatchResult tomo::IoLoop::parse_and_dispatch<true, 0u, false>(tomo::Client*) [clone .isra.0] 
    HOT B T=respresume code 18173->18386 lanes=respresume,mkfix eq=- tomo::IoLoop::DispatchResult tomo::IoLoop::parse_and_dispatch<true, 32u, false>(tomo::Client*)
    HOT B T=respresume code 18152->18389 lanes=respresume,mkfix eq=- tomo::IoLoop::DispatchResult tomo::IoLoop::r7_parse_and_dispatch<false, 32u, false>(tomo::Client*)
    HOT B T=respresume code 18281->18465 lanes=respresume,mkfix eq=- tomo::IoLoop::DispatchResult tomo::IoLoop::r7_parse_and_dispatch<true, 32u, false>(tomo::Client*)
    HOT A T=rlfix code 1675->2249 lanes=rlfix eq=rlfix tomo::ExLoopT<true>::prepare_local_read(tomo::Op&, tomo::FlatStore*, bool, tomo::FlatStore::ReadLocalPrefetchC
    HOT A T=PRE code 451->451 lanes=mkfix eq=mkfix tomo::IoLoop::init(tomo::Server*, tomo::ThreadCtx*, char const*, unsigned short, int, tomo::TlsContext const*,
    HOT A T=PRE code 451->451 lanes=mkfix eq=mkfix tomo::IoLoop::init(tomo::Server*, tomo::ThreadCtx*, char const*, unsigned short, int, tomo::TlsContext const*,
    C T=new code 1668->1684 lanes=- eq=- bool tomo::IoLoop::r7_drive_tls<false, true>(tomo::Client*) [clone .isra.0]
{"object": "src/core/reorder.o", "params": "--param inline-unit-growth=0 --param large-unit-insns=147800", "unit": 114487, "changed": 36, "hot_changed": 9, "A": 32, "B": 4, "C": 0, "D": 0, "hotA": 5, "hotB": 4, "hotCD": 0, "path": "/home/user/Projects/cx-wave3/build/wave3/trials/post/src_core_reorder.o.18101805d405.o"}
    HOT B T=respresume code 18137->18373 lanes=respresume,mkfix eq=- tomo::IoLoop::DispatchResult tomo::IoLoop::parse_and_dispatch<false, 32u, false>(tomo::Client*)
    HOT A T=respresume code 9784->9925 lanes=respresume eq=respresume tomo::IoLoop::DispatchResult tomo::IoLoop::parse_and_dispatch<true, 0u, false>(tomo::Client*) [clone .isra.0]
    HOT A T=respresume code 44->117 lanes=respresume eq=respresume tomo::IoLoop::DispatchResult tomo::IoLoop::parse_and_dispatch<true, 0u, false>(tomo::Client*) [clone .isra.0] 
    HOT B T=respresume code 18173->18386 lanes=respresume,mkfix eq=- tomo::IoLoop::DispatchResult tomo::IoLoop::parse_and_dispatch<true, 32u, false>(tomo::Client*)
    HOT B T=respresume code 18152->18389 lanes=respresume,mkfix eq=- tomo::IoLoop::DispatchResult tomo::IoLoop::r7_parse_and_dispatch<false, 32u, false>(tomo::Client*)
    HOT B T=respresume code 18281->18465 lanes=respresume,mkfix eq=- tomo::IoLoop::DispatchResult tomo::IoLoop::r7_parse_and_dispatch<true, 32u, false>(tomo::Client*)
    HOT A T=rlfix code 1675->2249 lanes=rlfix eq=rlfix tomo::ExLoopT<true>::prepare_local_read(tomo::Op&, tomo::FlatStore*, bool, tomo::FlatStore::ReadLocalPrefetchC
    HOT A T=PRE code 451->451 lanes=mkfix eq=mkfix tomo::IoLoop::init(tomo::Server*, tomo::ThreadCtx*, char const*, unsigned short, int, tomo::TlsContext const*,
    HOT A T=PRE code 451->451 lanes=mkfix eq=mkfix tomo::IoLoop::init(tomo::Server*, tomo::ThreadCtx*, char const*, unsigned short, int, tomo::TlsContext const*,
{"object": "src/core/reorder.o", "params": "--param inline-unit-growth=0 --param large-unit-insns=147820", "unit": 114487, "changed": 39, "hot_changed": 9, "A": 31, "B": 7, "C": 0, "D": 1, "hotA": 5, "hotB": 4, "hotCD": 0, "path": "/home/user/Projects/cx-wave3/build/wave3/trials/post/src_core_reorder.o.1643bd737cf4.o"}
    HOT B T=respresume code 18137->18373 lanes=respresume,mkfix eq=- tomo::IoLoop::DispatchResult tomo::IoLoop::parse_and_dispatch<false, 32u, false>(tomo::Client*)
    HOT A T=respresume code 9784->9925 lanes=respresume eq=respresume tomo::IoLoop::DispatchResult tomo::IoLoop::parse_and_dispatch<true, 0u, false>(tomo::Client*) [clone .isra.0]
    HOT A T=respresume code 44->117 lanes=respresume eq=respresume tomo::IoLoop::DispatchResult tomo::IoLoop::parse_and_dispatch<true, 0u, false>(tomo::Client*) [clone .isra.0] 
    HOT B T=respresume code 18173->18386 lanes=respresume,mkfix eq=- tomo::IoLoop::DispatchResult tomo::IoLoop::parse_and_dispatch<true, 32u, false>(tomo::Client*)
    HOT B T=respresume code 18152->18389 lanes=respresume,mkfix eq=- tomo::IoLoop::DispatchResult tomo::IoLoop::r7_parse_and_dispatch<false, 32u, false>(tomo::Client*)
    HOT B T=respresume code 18281->18465 lanes=respresume,mkfix eq=- tomo::IoLoop::DispatchResult tomo::IoLoop::r7_parse_and_dispatch<true, 32u, false>(tomo::Client*)
    HOT A T=rlfix code 1675->2249 lanes=rlfix eq=rlfix tomo::ExLoopT<true>::prepare_local_read(tomo::Op&, tomo::FlatStore*, bool, tomo::FlatStore::ReadLocalPrefetchC
    HOT A T=PRE code 451->451 lanes=mkfix eq=mkfix tomo::IoLoop::init(tomo::Server*, tomo::ThreadCtx*, char const*, unsigned short, int, tomo::TlsContext const*,
    HOT A T=PRE code 451->451 lanes=mkfix eq=mkfix tomo::IoLoop::init(tomo::Server*, tomo::ThreadCtx*, char const*, unsigned short, int, tomo::TlsContext const*,
    D T=new code 1158->1190 lanes=wave2 eq=respresume,rlfix,mkfix,aoforder,hexpread tomo::FlatStore::snapshot_prepare_write(unsigned long, tomo::Slice)
{"object": "src/core/reorder.o", "params": "--param inline-unit-growth=0 --param large-unit-insns=147840", "unit": 114487, "changed": 39, "hot_changed": 9, "A": 32, "B": 5, "C": 0, "D": 2, "hotA": 5, "hotB": 4, "hotCD": 0, "path": "/home/user/Projects/cx-wave3/build/wave3/trials/post/src_core_reorder.o.a63b3f42bd7e.o"}
    HOT B T=respresume code 18137->18373 lanes=respresume,mkfix eq=- tomo::IoLoop::DispatchResult tomo::IoLoop::parse_and_dispatch<false, 32u, false>(tomo::Client*)
    HOT A T=respresume code 9784->9925 lanes=respresume eq=respresume tomo::IoLoop::DispatchResult tomo::IoLoop::parse_and_dispatch<true, 0u, false>(tomo::Client*) [clone .isra.0]
    HOT A T=respresume code 44->117 lanes=respresume eq=respresume tomo::IoLoop::DispatchResult tomo::IoLoop::parse_and_dispatch<true, 0u, false>(tomo::Client*) [clone .isra.0] 
    HOT B T=respresume code 18173->18386 lanes=respresume,mkfix eq=- tomo::IoLoop::DispatchResult tomo::IoLoop::parse_and_dispatch<true, 32u, false>(tomo::Client*)
    HOT B T=respresume code 18152->18389 lanes=respresume,mkfix eq=- tomo::IoLoop::DispatchResult tomo::IoLoop::r7_parse_and_dispatch<false, 32u, false>(tomo::Client*)
    HOT B T=respresume code 18281->18465 lanes=respresume,mkfix eq=- tomo::IoLoop::DispatchResult tomo::IoLoop::r7_parse_and_dispatch<true, 32u, false>(tomo::Client*)
    HOT A T=rlfix code 1675->2249 lanes=rlfix eq=rlfix tomo::ExLoopT<true>::prepare_local_read(tomo::Op&, tomo::FlatStore*, bool, tomo::FlatStore::ReadLocalPrefetchC
    HOT A T=PRE code 451->451 lanes=mkfix eq=mkfix tomo::IoLoop::init(tomo::Server*, tomo::ThreadCtx*, char const*, unsigned short, int, tomo::TlsContext const*,
    HOT A T=PRE code 451->451 lanes=mkfix eq=mkfix tomo::IoLoop::init(tomo::Server*, tomo::ThreadCtx*, char const*, unsigned short, int, tomo::TlsContext const*,
    D T=respresume code 2047->2112 lanes=respresume eq=- void tomo::IoLoop::adopt_client<true, false>(tomo::Client*, bool, bool)
    D T=new code 1158->1190 lanes=wave2 eq=respresume,rlfix,mkfix,aoforder,hexpread tomo::FlatStore::snapshot_prepare_write(unsigned long, tomo::Slice)
{"object": "src/core/reorder.o", "params": "--param inline-unit-growth=0 --param large-unit-insns=147860", "unit": 114487, "changed": 39, "hot_changed": 9, "A": 33, "B": 5, "C": 0, "D": 1, "hotA": 5, "hotB": 4, "hotCD": 0, "path": "/home/user/Projects/cx-wave3/build/wave3/trials/post/src_core_reorder.o.ff40f01bf42a.o"}
    HOT B T=respresume code 18137->18373 lanes=respresume,mkfix eq=- tomo::IoLoop::DispatchResult tomo::IoLoop::parse_and_dispatch<false, 32u, false>(tomo::Client*)
    HOT A T=respresume code 9784->9925 lanes=respresume eq=respresume tomo::IoLoop::DispatchResult tomo::IoLoop::parse_and_dispatch<true, 0u, false>(tomo::Client*) [clone .isra.0]
    HOT A T=respresume code 44->117 lanes=respresume eq=respresume tomo::IoLoop::DispatchResult tomo::IoLoop::parse_and_dispatch<true, 0u, false>(tomo::Client*) [clone .isra.0] 
    HOT B T=respresume code 18173->18386 lanes=respresume,mkfix eq=- tomo::IoLoop::DispatchResult tomo::IoLoop::parse_and_dispatch<true, 32u, false>(tomo::Client*)
    HOT B T=respresume code 18152->18389 lanes=respresume,mkfix eq=- tomo::IoLoop::DispatchResult tomo::IoLoop::r7_parse_and_dispatch<false, 32u, false>(tomo::Client*)
    HOT B T=respresume code 18281->18465 lanes=respresume,mkfix eq=- tomo::IoLoop::DispatchResult tomo::IoLoop::r7_parse_and_dispatch<true, 32u, false>(tomo::Client*)
    HOT A T=rlfix code 1675->2249 lanes=rlfix eq=rlfix tomo::ExLoopT<true>::prepare_local_read(tomo::Op&, tomo::FlatStore*, bool, tomo::FlatStore::ReadLocalPrefetchC
    HOT A T=PRE code 451->451 lanes=mkfix eq=mkfix tomo::IoLoop::init(tomo::Server*, tomo::ThreadCtx*, char const*, unsigned short, int, tomo::TlsContext const*,
    HOT A T=PRE code 451->451 lanes=mkfix eq=mkfix tomo::IoLoop::init(tomo::Server*, tomo::ThreadCtx*, char const*, unsigned short, int, tomo::TlsContext const*,
    D T=new code 1158->1190 lanes=wave2 eq=respresume,rlfix,mkfix,aoforder,hexpread tomo::FlatStore::snapshot_prepare_write(unsigned long, tomo::Slice)
{"object": "src/core/reorder.o", "params": "--param inline-unit-growth=0 --param large-unit-insns=147880", "unit": 114487, "changed": 40, "hot_changed": 9, "A": 32, "B": 6, "C": 0, "D": 2, "hotA": 5, "hotB": 4, "hotCD": 0, "path": "/home/user/Projects/cx-wave3/build/wave3/trials/post/src_core_reorder.o.a62ce265bcdb.o"}
    HOT B T=respresume code 18137->18373 lanes=respresume,mkfix eq=- tomo::IoLoop::DispatchResult tomo::IoLoop::parse_and_dispatch<false, 32u, false>(tomo::Client*)
    HOT A T=respresume code 9784->9925 lanes=respresume eq=respresume tomo::IoLoop::DispatchResult tomo::IoLoop::parse_and_dispatch<true, 0u, false>(tomo::Client*) [clone .isra.0]
    HOT A T=respresume code 44->117 lanes=respresume eq=respresume tomo::IoLoop::DispatchResult tomo::IoLoop::parse_and_dispatch<true, 0u, false>(tomo::Client*) [clone .isra.0] 
    HOT B T=respresume code 18173->18386 lanes=respresume,mkfix eq=- tomo::IoLoop::DispatchResult tomo::IoLoop::parse_and_dispatch<true, 32u, false>(tomo::Client*)
    HOT B T=respresume code 18152->18389 lanes=respresume,mkfix eq=- tomo::IoLoop::DispatchResult tomo::IoLoop::r7_parse_and_dispatch<false, 32u, false>(tomo::Client*)
    HOT B T=respresume code 18281->18465 lanes=respresume,mkfix eq=- tomo::IoLoop::DispatchResult tomo::IoLoop::r7_parse_and_dispatch<true, 32u, false>(tomo::Client*)
    HOT A T=rlfix code 1675->2249 lanes=rlfix eq=rlfix tomo::ExLoopT<true>::prepare_local_read(tomo::Op&, tomo::FlatStore*, bool, tomo::FlatStore::ReadLocalPrefetchC
    HOT A T=PRE code 451->451 lanes=mkfix eq=mkfix tomo::IoLoop::init(tomo::Server*, tomo::ThreadCtx*, char const*, unsigned short, int, tomo::TlsContext const*,
    HOT A T=PRE code 451->451 lanes=mkfix eq=mkfix tomo::IoLoop::init(tomo::Server*, tomo::ThreadCtx*, char const*, unsigned short, int, tomo::TlsContext const*,
    D T=respresume code 2047->2112 lanes=respresume eq=- void tomo::IoLoop::adopt_client<true, false>(tomo::Client*, bool, bool)
    D T=new code 1158->1190 lanes=wave2 eq=respresume,rlfix,mkfix,aoforder,hexpread tomo::FlatStore::snapshot_prepare_write(unsigned long, tomo::Slice)
{"object": "src/core/reorder.o", "params": "--param inline-unit-growth=0 --param large-unit-insns=147900", "unit": 114487, "changed": 40, "hot_changed": 9, "A": 33, "B": 6, "C": 0, "D": 1, "hotA": 5, "hotB": 4, "hotCD": 0, "path": "/home/user/Projects/cx-wave3/build/wave3/trials/post/src_core_reorder.o.838a060007ec.o"}
    HOT B T=respresume code 18137->18373 lanes=respresume,mkfix eq=- tomo::IoLoop::DispatchResult tomo::IoLoop::parse_and_dispatch<false, 32u, false>(tomo::Client*)
    HOT A T=respresume code 9784->9925 lanes=respresume eq=respresume tomo::IoLoop::DispatchResult tomo::IoLoop::parse_and_dispatch<true, 0u, false>(tomo::Client*) [clone .isra.0]
    HOT A T=respresume code 44->117 lanes=respresume eq=respresume tomo::IoLoop::DispatchResult tomo::IoLoop::parse_and_dispatch<true, 0u, false>(tomo::Client*) [clone .isra.0] 
    HOT B T=respresume code 18173->18386 lanes=respresume,mkfix eq=- tomo::IoLoop::DispatchResult tomo::IoLoop::parse_and_dispatch<true, 32u, false>(tomo::Client*)
    HOT B T=respresume code 18152->18389 lanes=respresume,mkfix eq=- tomo::IoLoop::DispatchResult tomo::IoLoop::r7_parse_and_dispatch<false, 32u, false>(tomo::Client*)
    HOT B T=respresume code 18281->18465 lanes=respresume,mkfix eq=- tomo::IoLoop::DispatchResult tomo::IoLoop::r7_parse_and_dispatch<true, 32u, false>(tomo::Client*)
    HOT A T=rlfix code 1675->2249 lanes=rlfix eq=rlfix tomo::ExLoopT<true>::prepare_local_read(tomo::Op&, tomo::FlatStore*, bool, tomo::FlatStore::ReadLocalPrefetchC
    HOT A T=PRE code 451->451 lanes=mkfix eq=mkfix tomo::IoLoop::init(tomo::Server*, tomo::ThreadCtx*, char const*, unsigned short, int, tomo::TlsContext const*,
    HOT A T=PRE code 451->451 lanes=mkfix eq=mkfix tomo::IoLoop::init(tomo::Server*, tomo::ThreadCtx*, char const*, unsigned short, int, tomo::TlsContext const*,
    D T=new code 1158->1190 lanes=wave2 eq=respresume,rlfix,mkfix,aoforder,hexpread tomo::FlatStore::snapshot_prepare_write(unsigned long, tomo::Slice)
{"object": "src/core/reorder.o", "params": "--param inline-unit-growth=0 --param large-unit-insns=147920", "unit": 114487, "changed": 41, "hot_changed": 9, "A": 33, "B": 6, "C": 0, "D": 2, "hotA": 5, "hotB": 4, "hotCD": 0, "path": "/home/user/Projects/cx-wave3/build/wave3/trials/post/src_core_reorder.o.46ebd1205978.o"}
    HOT B T=respresume code 18137->18373 lanes=respresume,mkfix eq=- tomo::IoLoop::DispatchResult tomo::IoLoop::parse_and_dispatch<false, 32u, false>(tomo::Client*)
    HOT A T=respresume code 9784->9925 lanes=respresume eq=respresume tomo::IoLoop::DispatchResult tomo::IoLoop::parse_and_dispatch<true, 0u, false>(tomo::Client*) [clone .isra.0]
    HOT A T=respresume code 44->117 lanes=respresume eq=respresume tomo::IoLoop::DispatchResult tomo::IoLoop::parse_and_dispatch<true, 0u, false>(tomo::Client*) [clone .isra.0] 
    HOT B T=respresume code 18173->18386 lanes=respresume,mkfix eq=- tomo::IoLoop::DispatchResult tomo::IoLoop::parse_and_dispatch<true, 32u, false>(tomo::Client*)
    HOT B T=respresume code 18152->18389 lanes=respresume,mkfix eq=- tomo::IoLoop::DispatchResult tomo::IoLoop::r7_parse_and_dispatch<false, 32u, false>(tomo::Client*)
    HOT B T=respresume code 18281->18465 lanes=respresume,mkfix eq=- tomo::IoLoop::DispatchResult tomo::IoLoop::r7_parse_and_dispatch<true, 32u, false>(tomo::Client*)
    HOT A T=rlfix code 1675->2249 lanes=rlfix eq=rlfix tomo::ExLoopT<true>::prepare_local_read(tomo::Op&, tomo::FlatStore*, bool, tomo::FlatStore::ReadLocalPrefetchC
    HOT A T=PRE code 451->451 lanes=mkfix eq=mkfix tomo::IoLoop::init(tomo::Server*, tomo::ThreadCtx*, char const*, unsigned short, int, tomo::TlsContext const*,
    HOT A T=PRE code 451->451 lanes=mkfix eq=mkfix tomo::IoLoop::init(tomo::Server*, tomo::ThreadCtx*, char const*, unsigned short, int, tomo::TlsContext const*,
    D T=respresume code 2047->2112 lanes=respresume eq=- void tomo::IoLoop::adopt_client<true, false>(tomo::Client*, bool, bool)
    D T=new code 1158->1190 lanes=wave2 eq=respresume,rlfix,mkfix,aoforder,hexpread tomo::FlatStore::snapshot_prepare_write(unsigned long, tomo::Slice)
{"object": "src/core/reorder.o", "params": "--param inline-unit-growth=0 --param large-unit-insns=147940", "unit": 114487, "changed": 43, "hot_changed": 9, "A": 35, "B": 6, "C": 0, "D": 2, "hotA": 5, "hotB": 4, "hotCD": 0, "path": "/home/user/Projects/cx-wave3/build/wave3/trials/post/src_core_reorder.o.6fdad72bdbba.o"}
    HOT B T=respresume code 18137->18373 lanes=respresume,mkfix eq=- tomo::IoLoop::DispatchResult tomo::IoLoop::parse_and_dispatch<false, 32u, false>(tomo::Client*)
    HOT A T=respresume code 9784->9925 lanes=respresume eq=respresume tomo::IoLoop::DispatchResult tomo::IoLoop::parse_and_dispatch<true, 0u, false>(tomo::Client*) [clone .isra.0]
    HOT A T=respresume code 44->117 lanes=respresume eq=respresume tomo::IoLoop::DispatchResult tomo::IoLoop::parse_and_dispatch<true, 0u, false>(tomo::Client*) [clone .isra.0] 
    HOT B T=respresume code 18173->18386 lanes=respresume,mkfix eq=- tomo::IoLoop::DispatchResult tomo::IoLoop::parse_and_dispatch<true, 32u, false>(tomo::Client*)
    HOT B T=respresume code 18152->18389 lanes=respresume,mkfix eq=- tomo::IoLoop::DispatchResult tomo::IoLoop::r7_parse_and_dispatch<false, 32u, false>(tomo::Client*)
    HOT B T=respresume code 18281->18465 lanes=respresume,mkfix eq=- tomo::IoLoop::DispatchResult tomo::IoLoop::r7_parse_and_dispatch<true, 32u, false>(tomo::Client*)
    HOT A T=rlfix code 1675->2249 lanes=rlfix eq=rlfix tomo::ExLoopT<true>::prepare_local_read(tomo::Op&, tomo::FlatStore*, bool, tomo::FlatStore::ReadLocalPrefetchC
    HOT A T=PRE code 451->451 lanes=mkfix eq=mkfix tomo::IoLoop::init(tomo::Server*, tomo::ThreadCtx*, char const*, unsigned short, int, tomo::TlsContext const*,
    HOT A T=PRE code 451->451 lanes=mkfix eq=mkfix tomo::IoLoop::init(tomo::Server*, tomo::ThreadCtx*, char const*, unsigned short, int, tomo::TlsContext const*,
    D T=respresume code 2047->2112 lanes=respresume eq=- void tomo::IoLoop::adopt_client<true, false>(tomo::Client*, bool, bool)
    D T=new code 1158->1190 lanes=wave2 eq=respresume,rlfix,mkfix,aoforder,hexpread tomo::FlatStore::snapshot_prepare_write(unsigned long, tomo::Slice)
{"object": "src/core/reorder.o", "params": "--param inline-unit-growth=0 --param large-unit-insns=147960", "unit": 114487, "changed": 44, "hot_changed": 9, "A": 35, "B": 6, "C": 0, "D": 3, "hotA": 5, "hotB": 4, "hotCD": 0, "path": "/home/user/Projects/cx-wave3/build/wave3/trials/post/src_core_reorder.o.ad96ac563ba8.o"}
    HOT B T=respresume code 18137->18373 lanes=respresume,mkfix eq=- tomo::IoLoop::DispatchResult tomo::IoLoop::parse_and_dispatch<false, 32u, false>(tomo::Client*)
    HOT A T=respresume code 9784->9925 lanes=respresume eq=respresume tomo::IoLoop::DispatchResult tomo::IoLoop::parse_and_dispatch<true, 0u, false>(tomo::Client*) [clone .isra.0]
    HOT A T=respresume code 44->117 lanes=respresume eq=respresume tomo::IoLoop::DispatchResult tomo::IoLoop::parse_and_dispatch<true, 0u, false>(tomo::Client*) [clone .isra.0] 
    HOT B T=respresume code 18173->18386 lanes=respresume,mkfix eq=- tomo::IoLoop::DispatchResult tomo::IoLoop::parse_and_dispatch<true, 32u, false>(tomo::Client*)
    HOT B T=respresume code 18152->18389 lanes=respresume,mkfix eq=- tomo::IoLoop::DispatchResult tomo::IoLoop::r7_parse_and_dispatch<false, 32u, false>(tomo::Client*)
    HOT B T=respresume code 18281->18465 lanes=respresume,mkfix eq=- tomo::IoLoop::DispatchResult tomo::IoLoop::r7_parse_and_dispatch<true, 32u, false>(tomo::Client*)
    HOT A T=rlfix code 1675->2249 lanes=rlfix eq=rlfix tomo::ExLoopT<true>::prepare_local_read(tomo::Op&, tomo::FlatStore*, bool, tomo::FlatStore::ReadLocalPrefetchC
    HOT A T=PRE code 451->451 lanes=mkfix eq=mkfix tomo::IoLoop::init(tomo::Server*, tomo::ThreadCtx*, char const*, unsigned short, int, tomo::TlsContext const*,
    HOT A T=PRE code 451->451 lanes=mkfix eq=mkfix tomo::IoLoop::init(tomo::Server*, tomo::ThreadCtx*, char const*, unsigned short, int, tomo::TlsContext const*,
    D T=new code 2047->2144 lanes=respresume eq=- void tomo::IoLoop::adopt_client<true, false>(tomo::Client*, bool, bool)
    D T=new code 2047->2144 lanes=respresume eq=- void tomo::IoLoop::r7_adopt_client<true, true>(tomo::Client*, bool, bool)
    D T=new code 1158->1190 lanes=wave2 eq=respresume,rlfix,mkfix,aoforder,hexpread tomo::FlatStore::snapshot_prepare_write(unsigned long, tomo::Slice)
{"object": "src/core/reorder.o", "params": "--param inline-unit-growth=0 --param large-unit-insns=147980", "unit": 114487, "changed": 43, "hot_changed": 10, "A": 35, "B": 6, "C": 1, "D": 1, "hotA": 5, "hotB": 4, "hotCD": 1, "path": "/home/user/Projects/cx-wave3/build/wave3/trials/post/src_core_reorder.o.458dcb05bc50.o"}
    HOT B T=respresume code 18137->18373 lanes=respresume,mkfix eq=- tomo::IoLoop::DispatchResult tomo::IoLoop::parse_and_dispatch<false, 32u, false>(tomo::Client*)
    HOT A T=respresume code 9784->9925 lanes=respresume eq=respresume tomo::IoLoop::DispatchResult tomo::IoLoop::parse_and_dispatch<true, 0u, false>(tomo::Client*) [clone .isra.0]
    HOT A T=respresume code 44->117 lanes=respresume eq=respresume tomo::IoLoop::DispatchResult tomo::IoLoop::parse_and_dispatch<true, 0u, false>(tomo::Client*) [clone .isra.0] 
    HOT B T=respresume code 18173->18386 lanes=respresume,mkfix eq=- tomo::IoLoop::DispatchResult tomo::IoLoop::parse_and_dispatch<true, 32u, false>(tomo::Client*)
    HOT B T=respresume code 18152->18389 lanes=respresume,mkfix eq=- tomo::IoLoop::DispatchResult tomo::IoLoop::r7_parse_and_dispatch<false, 32u, false>(tomo::Client*)
    HOT B T=respresume code 18281->18465 lanes=respresume,mkfix eq=- tomo::IoLoop::DispatchResult tomo::IoLoop::r7_parse_and_dispatch<true, 32u, false>(tomo::Client*)
    HOT A T=rlfix code 1675->2249 lanes=rlfix eq=rlfix tomo::ExLoopT<true>::prepare_local_read(tomo::Op&, tomo::FlatStore*, bool, tomo::FlatStore::ReadLocalPrefetchC
    HOT C T=new code 1412->1614 lanes=- eq=- unsigned int tomo::ExLoopT<true>::sweep<32u, true, false, false>()
    HOT A T=PRE code 451->451 lanes=mkfix eq=mkfix tomo::IoLoop::init(tomo::Server*, tomo::ThreadCtx*, char const*, unsigned short, int, tomo::TlsContext const*,
    HOT A T=PRE code 451->451 lanes=mkfix eq=mkfix tomo::IoLoop::init(tomo::Server*, tomo::ThreadCtx*, char const*, unsigned short, int, tomo::TlsContext const*,
    D T=new code 1158->1190 lanes=wave2 eq=respresume,rlfix,mkfix,aoforder,hexpread tomo::FlatStore::snapshot_prepare_write(unsigned long, tomo::Slice)
{"object": "src/core/reorder.o", "params": "--param inline-unit-growth=0 --param large-unit-insns=148000", "unit": 114487, "changed": 45, "hot_changed": 10, "A": 35, "B": 6, "C": 1, "D": 3, "hotA": 5, "hotB": 4, "hotCD": 1, "path": "/home/user/Projects/cx-wave3/build/wave3/trials/post/src_core_reorder.o.9795d88cf3fd.o"}
    HOT B T=respresume code 18137->18373 lanes=respresume,mkfix eq=- tomo::IoLoop::DispatchResult tomo::IoLoop::parse_and_dispatch<false, 32u, false>(tomo::Client*)
    HOT A T=respresume code 9784->9925 lanes=respresume eq=respresume tomo::IoLoop::DispatchResult tomo::IoLoop::parse_and_dispatch<true, 0u, false>(tomo::Client*) [clone .isra.0]
    HOT A T=respresume code 44->117 lanes=respresume eq=respresume tomo::IoLoop::DispatchResult tomo::IoLoop::parse_and_dispatch<true, 0u, false>(tomo::Client*) [clone .isra.0] 
    HOT B T=respresume code 18173->18386 lanes=respresume,mkfix eq=- tomo::IoLoop::DispatchResult tomo::IoLoop::parse_and_dispatch<true, 32u, false>(tomo::Client*)
    HOT B T=respresume code 18152->18389 lanes=respresume,mkfix eq=- tomo::IoLoop::DispatchResult tomo::IoLoop::r7_parse_and_dispatch<false, 32u, false>(tomo::Client*)
    HOT B T=respresume code 18281->18465 lanes=respresume,mkfix eq=- tomo::IoLoop::DispatchResult tomo::IoLoop::r7_parse_and_dispatch<true, 32u, false>(tomo::Client*)
    HOT A T=rlfix code 1675->2249 lanes=rlfix eq=rlfix tomo::ExLoopT<true>::prepare_local_read(tomo::Op&, tomo::FlatStore*, bool, tomo::FlatStore::ReadLocalPrefetchC
    HOT C T=new code 1412->1614 lanes=- eq=- unsigned int tomo::ExLoopT<true>::sweep<32u, true, false, false>()
    HOT A T=PRE code 451->451 lanes=mkfix eq=mkfix tomo::IoLoop::init(tomo::Server*, tomo::ThreadCtx*, char const*, unsigned short, int, tomo::TlsContext const*,
    HOT A T=PRE code 451->451 lanes=mkfix eq=mkfix tomo::IoLoop::init(tomo::Server*, tomo::ThreadCtx*, char const*, unsigned short, int, tomo::TlsContext const*,
    D T=new code 2047->2144 lanes=respresume eq=- void tomo::IoLoop::adopt_client<true, false>(tomo::Client*, bool, bool)
    D T=new code 2047->2144 lanes=respresume eq=- void tomo::IoLoop::r7_adopt_client<true, true>(tomo::Client*, bool, bool)
    D T=new code 1158->1190 lanes=wave2 eq=respresume,rlfix,mkfix,aoforder,hexpread tomo::FlatStore::snapshot_prepare_write(unsigned long, tomo::Slice)
{"object": "src/core/reorder.o", "params": "--param inline-unit-growth=0 --param large-unit-insns=148020", "unit": 114487, "changed": 44, "hot_changed": 11, "A": 35, "B": 6, "C": 1, "D": 2, "hotA": 6, "hotB": 4, "hotCD": 1, "path": "/home/user/Projects/cx-wave3/build/wave3/trials/post/src_core_reorder.o.654ab012fed0.o"}
    HOT B T=respresume code 18137->18373 lanes=respresume,mkfix eq=- tomo::IoLoop::DispatchResult tomo::IoLoop::parse_and_dispatch<false, 32u, false>(tomo::Client*)
    HOT A T=respresume code 9784->9925 lanes=respresume eq=respresume tomo::IoLoop::DispatchResult tomo::IoLoop::parse_and_dispatch<true, 0u, false>(tomo::Client*) [clone .isra.0]
    HOT A T=respresume code 44->117 lanes=respresume eq=respresume tomo::IoLoop::DispatchResult tomo::IoLoop::parse_and_dispatch<true, 0u, false>(tomo::Client*) [clone .isra.0] 
    HOT B T=respresume code 18173->18386 lanes=respresume,mkfix eq=- tomo::IoLoop::DispatchResult tomo::IoLoop::parse_and_dispatch<true, 32u, false>(tomo::Client*)
    HOT B T=respresume code 18152->18389 lanes=respresume,mkfix eq=- tomo::IoLoop::DispatchResult tomo::IoLoop::r7_parse_and_dispatch<false, 32u, false>(tomo::Client*)
    HOT B T=respresume code 18281->18465 lanes=respresume,mkfix eq=- tomo::IoLoop::DispatchResult tomo::IoLoop::r7_parse_and_dispatch<true, 32u, false>(tomo::Client*)
    HOT A T=rlfix code 1675->2249 lanes=rlfix eq=rlfix tomo::ExLoopT<true>::prepare_local_read(tomo::Op&, tomo::FlatStore*, bool, tomo::FlatStore::ReadLocalPrefetchC
    HOT C T=new code 1412->1614 lanes=- eq=- unsigned int tomo::ExLoopT<true>::sweep<32u, true, false, false>()
    HOT A T=respresume code 1412->1614 lanes=respresume eq=respresume unsigned int tomo::ExLoopT<true>::r7_sweep<32u, true, false, false>()
    HOT A T=PRE code 451->451 lanes=mkfix eq=mkfix tomo::IoLoop::init(tomo::Server*, tomo::ThreadCtx*, char const*, unsigned short, int, tomo::TlsContext const*,
    HOT A T=PRE code 451->451 lanes=mkfix eq=mkfix tomo::IoLoop::init(tomo::Server*, tomo::ThreadCtx*, char const*, unsigned short, int, tomo::TlsContext const*,
    D T=respresume code 2047->2112 lanes=respresume eq=- void tomo::IoLoop::adopt_client<true, false>(tomo::Client*, bool, bool)
    D T=new code 1158->1190 lanes=wave2 eq=respresume,rlfix,mkfix,aoforder,hexpread tomo::FlatStore::snapshot_prepare_write(unsigned long, tomo::Slice)
{"object": "src/core/reorder.o", "params": "--param inline-unit-growth=0 --param large-unit-insns=148040", "unit": 114487, "changed": 46, "hot_changed": 11, "A": 36, "B": 6, "C": 1, "D": 3, "hotA": 6, "hotB": 4, "hotCD": 1, "path": "/home/user/Projects/cx-wave3/build/wave3/trials/post/src_core_reorder.o.5bda2e5d5fad.o"}
    HOT B T=respresume code 18137->18373 lanes=respresume,mkfix eq=- tomo::IoLoop::DispatchResult tomo::IoLoop::parse_and_dispatch<false, 32u, false>(tomo::Client*)
    HOT A T=respresume code 9784->9925 lanes=respresume eq=respresume tomo::IoLoop::DispatchResult tomo::IoLoop::parse_and_dispatch<true, 0u, false>(tomo::Client*) [clone .isra.0]
    HOT A T=respresume code 44->117 lanes=respresume eq=respresume tomo::IoLoop::DispatchResult tomo::IoLoop::parse_and_dispatch<true, 0u, false>(tomo::Client*) [clone .isra.0] 
    HOT B T=respresume code 18173->18386 lanes=respresume,mkfix eq=- tomo::IoLoop::DispatchResult tomo::IoLoop::parse_and_dispatch<true, 32u, false>(tomo::Client*)
    HOT B T=respresume code 18152->18389 lanes=respresume,mkfix eq=- tomo::IoLoop::DispatchResult tomo::IoLoop::r7_parse_and_dispatch<false, 32u, false>(tomo::Client*)
    HOT B T=respresume code 18281->18465 lanes=respresume,mkfix eq=- tomo::IoLoop::DispatchResult tomo::IoLoop::r7_parse_and_dispatch<true, 32u, false>(tomo::Client*)
    HOT A T=rlfix code 1675->2249 lanes=rlfix eq=rlfix tomo::ExLoopT<true>::prepare_local_read(tomo::Op&, tomo::FlatStore*, bool, tomo::FlatStore::ReadLocalPrefetchC
    HOT C T=new code 1412->1614 lanes=- eq=- unsigned int tomo::ExLoopT<true>::sweep<32u, true, false, false>()
    HOT A T=respresume code 1412->1614 lanes=respresume eq=respresume unsigned int tomo::ExLoopT<true>::r7_sweep<32u, true, false, false>()
    HOT A T=PRE code 451->451 lanes=mkfix eq=mkfix tomo::IoLoop::init(tomo::Server*, tomo::ThreadCtx*, char const*, unsigned short, int, tomo::TlsContext const*,
    HOT A T=PRE code 451->451 lanes=mkfix eq=mkfix tomo::IoLoop::init(tomo::Server*, tomo::ThreadCtx*, char const*, unsigned short, int, tomo::TlsContext const*,
    D T=respresume code 2047->2112 lanes=respresume eq=- void tomo::IoLoop::adopt_client<true, false>(tomo::Client*, bool, bool)
    D T=new code 2047->2144 lanes=respresume eq=- void tomo::IoLoop::r7_adopt_client<true, true>(tomo::Client*, bool, bool)
    D T=new code 1158->1190 lanes=wave2 eq=respresume,rlfix,mkfix,aoforder,hexpread tomo::FlatStore::snapshot_prepare_write(unsigned long, tomo::Slice)
{"object": "src/core/reorder.o", "params": "--param inline-unit-growth=0 --param large-unit-insns=148060", "unit": 114487, "changed": 46, "hot_changed": 11, "A": 37, "B": 6, "C": 1, "D": 2, "hotA": 6, "hotB": 4, "hotCD": 1, "path": "/home/user/Projects/cx-wave3/build/wave3/trials/post/src_core_reorder.o.6803d1a90892.o"}
    HOT B T=respresume code 18137->18373 lanes=respresume,mkfix eq=- tomo::IoLoop::DispatchResult tomo::IoLoop::parse_and_dispatch<false, 32u, false>(tomo::Client*)
    HOT A T=respresume code 9784->9925 lanes=respresume eq=respresume tomo::IoLoop::DispatchResult tomo::IoLoop::parse_and_dispatch<true, 0u, false>(tomo::Client*) [clone .isra.0]
    HOT A T=respresume code 44->117 lanes=respresume eq=respresume tomo::IoLoop::DispatchResult tomo::IoLoop::parse_and_dispatch<true, 0u, false>(tomo::Client*) [clone .isra.0] 
    HOT B T=respresume code 18173->18386 lanes=respresume,mkfix eq=- tomo::IoLoop::DispatchResult tomo::IoLoop::parse_and_dispatch<true, 32u, false>(tomo::Client*)
    HOT B T=respresume code 18152->18389 lanes=respresume,mkfix eq=- tomo::IoLoop::DispatchResult tomo::IoLoop::r7_parse_and_dispatch<false, 32u, false>(tomo::Client*)
    HOT B T=respresume code 18281->18465 lanes=respresume,mkfix eq=- tomo::IoLoop::DispatchResult tomo::IoLoop::r7_parse_and_dispatch<true, 32u, false>(tomo::Client*)
    HOT A T=rlfix code 1675->2249 lanes=rlfix eq=rlfix tomo::ExLoopT<true>::prepare_local_read(tomo::Op&, tomo::FlatStore*, bool, tomo::FlatStore::ReadLocalPrefetchC
    HOT C T=new code 1412->1614 lanes=- eq=- unsigned int tomo::ExLoopT<true>::sweep<32u, true, false, false>()
    HOT A T=respresume code 1412->1614 lanes=respresume eq=respresume unsigned int tomo::ExLoopT<true>::r7_sweep<32u, true, false, false>()
    HOT A T=PRE code 451->451 lanes=mkfix eq=mkfix tomo::IoLoop::init(tomo::Server*, tomo::ThreadCtx*, char const*, unsigned short, int, tomo::TlsContext const*,
    HOT A T=PRE code 451->451 lanes=mkfix eq=mkfix tomo::IoLoop::init(tomo::Server*, tomo::ThreadCtx*, char const*, unsigned short, int, tomo::TlsContext const*,
    D T=respresume code 2047->2112 lanes=respresume eq=- void tomo::IoLoop::adopt_client<true, false>(tomo::Client*, bool, bool)
    D T=new code 1158->1190 lanes=wave2 eq=respresume,rlfix,mkfix,aoforder,hexpread tomo::FlatStore::snapshot_prepare_write(unsigned long, tomo::Slice)
{"object": "src/core/reorder.o", "params": "--param inline-unit-growth=0 --param large-unit-insns=148080", "unit": 114487, "changed": 47, "hot_changed": 12, "A": 37, "B": 6, "C": 2, "D": 2, "hotA": 6, "hotB": 4, "hotCD": 2, "path": "/home/user/Projects/cx-wave3/build/wave3/trials/post/src_core_reorder.o.4ed3f87a6943.o"}
    HOT C T=new code 2372->2628 lanes=- eq=- unsigned int tomo::IoLoop::r7_flush_ready<false, false, true, true, false, false>()
    HOT B T=respresume code 18137->18373 lanes=respresume,mkfix eq=- tomo::IoLoop::DispatchResult tomo::IoLoop::parse_and_dispatch<false, 32u, false>(tomo::Client*)
    HOT A T=respresume code 9784->9925 lanes=respresume eq=respresume tomo::IoLoop::DispatchResult tomo::IoLoop::parse_and_dispatch<true, 0u, false>(tomo::Client*) [clone .isra.0]
    HOT A T=respresume code 44->117 lanes=respresume eq=respresume tomo::IoLoop::DispatchResult tomo::IoLoop::parse_and_dispatch<true, 0u, false>(tomo::Client*) [clone .isra.0] 
    HOT B T=respresume code 18173->18386 lanes=respresume,mkfix eq=- tomo::IoLoop::DispatchResult tomo::IoLoop::parse_and_dispatch<true, 32u, false>(tomo::Client*)
    HOT B T=respresume code 18152->18389 lanes=respresume,mkfix eq=- tomo::IoLoop::DispatchResult tomo::IoLoop::r7_parse_and_dispatch<false, 32u, false>(tomo::Client*)
    HOT B T=respresume code 18281->18465 lanes=respresume,mkfix eq=- tomo::IoLoop::DispatchResult tomo::IoLoop::r7_parse_and_dispatch<true, 32u, false>(tomo::Client*)
    HOT A T=rlfix code 1675->2249 lanes=rlfix eq=rlfix tomo::ExLoopT<true>::prepare_local_read(tomo::Op&, tomo::FlatStore*, bool, tomo::FlatStore::ReadLocalPrefetchC
    HOT C T=new code 1412->1614 lanes=- eq=- unsigned int tomo::ExLoopT<true>::sweep<32u, true, false, false>()
    HOT A T=respresume code 1412->1614 lanes=respresume eq=respresume unsigned int tomo::ExLoopT<true>::r7_sweep<32u, true, false, false>()
    HOT A T=PRE code 451->451 lanes=mkfix eq=mkfix tomo::IoLoop::init(tomo::Server*, tomo::ThreadCtx*, char const*, unsigned short, int, tomo::TlsContext const*,
    HOT A T=PRE code 451->451 lanes=mkfix eq=mkfix tomo::IoLoop::init(tomo::Server*, tomo::ThreadCtx*, char const*, unsigned short, int, tomo::TlsContext const*,
    D T=respresume code 2047->2112 lanes=respresume eq=- void tomo::IoLoop::adopt_client<true, false>(tomo::Client*, bool, bool)
    D T=new code 1158->1190 lanes=wave2 eq=respresume,rlfix,mkfix,aoforder,hexpread tomo::FlatStore::snapshot_prepare_write(unsigned long, tomo::Slice)
{"object": "src/core/reorder.o", "params": "--param inline-unit-growth=0 --param large-unit-insns=148100", "unit": 114487, "changed": 48, "hot_changed": 13, "A": 36, "B": 6, "C": 3, "D": 3, "hotA": 6, "hotB": 4, "hotCD": 3, "path": "/home/user/Projects/cx-wave3/build/wave3/trials/post/src_core_reorder.o.7c7166e861e0.o"}
    HOT C T=new code 2372->2628 lanes=- eq=- unsigned int tomo::IoLoop::r7_flush_ready<false, false, true, true, false, false>()
    HOT B T=respresume code 18137->18373 lanes=respresume,mkfix eq=- tomo::IoLoop::DispatchResult tomo::IoLoop::parse_and_dispatch<false, 32u, false>(tomo::Client*)
    HOT A T=respresume code 9784->9925 lanes=respresume eq=respresume tomo::IoLoop::DispatchResult tomo::IoLoop::parse_and_dispatch<true, 0u, false>(tomo::Client*) [clone .isra.0]
    HOT A T=respresume code 44->117 lanes=respresume eq=respresume tomo::IoLoop::DispatchResult tomo::IoLoop::parse_and_dispatch<true, 0u, false>(tomo::Client*) [clone .isra.0] 
    HOT B T=respresume code 18173->18386 lanes=respresume,mkfix eq=- tomo::IoLoop::DispatchResult tomo::IoLoop::parse_and_dispatch<true, 32u, false>(tomo::Client*)
    HOT B T=respresume code 18152->18389 lanes=respresume,mkfix eq=- tomo::IoLoop::DispatchResult tomo::IoLoop::r7_parse_and_dispatch<false, 32u, false>(tomo::Client*)
    HOT B T=respresume code 18281->18465 lanes=respresume,mkfix eq=- tomo::IoLoop::DispatchResult tomo::IoLoop::r7_parse_and_dispatch<true, 32u, false>(tomo::Client*)
    HOT C T=new code 1737->1721 lanes=- eq=- bool tomo::IoLoop::drive_tls<true, false>(tomo::Client*) [clone .isra.0]
    HOT A T=rlfix code 1675->2249 lanes=rlfix eq=rlfix tomo::ExLoopT<true>::prepare_local_read(tomo::Op&, tomo::FlatStore*, bool, tomo::FlatStore::ReadLocalPrefetchC
    HOT C T=new code 1412->1614 lanes=- eq=- unsigned int tomo::ExLoopT<true>::sweep<32u, true, false, false>()
    HOT A T=respresume code 1412->1614 lanes=respresume eq=respresume unsigned int tomo::ExLoopT<true>::r7_sweep<32u, true, false, false>()
    HOT A T=PRE code 451->451 lanes=mkfix eq=mkfix tomo::IoLoop::init(tomo::Server*, tomo::ThreadCtx*, char const*, unsigned short, int, tomo::TlsContext const*,
    HOT A T=PRE code 451->451 lanes=mkfix eq=mkfix tomo::IoLoop::init(tomo::Server*, tomo::ThreadCtx*, char const*, unsigned short, int, tomo::TlsContext const*,
    D T=new code 2047->2144 lanes=respresume eq=- void tomo::IoLoop::adopt_client<true, false>(tomo::Client*, bool, bool)
    D T=new code 2047->2144 lanes=respresume eq=- void tomo::IoLoop::r7_adopt_client<true, true>(tomo::Client*, bool, bool)
    D T=new code 1158->1190 lanes=wave2 eq=respresume,rlfix,mkfix,aoforder,hexpread tomo::FlatStore::snapshot_prepare_write(unsigned long, tomo::Slice)
