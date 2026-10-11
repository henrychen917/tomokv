{"object": "db0/src/core/reorder.o", "params": "--param inline-unit-growth=0 --param large-unit-insns=147752", "unit": 113097, "hot_changed": 37, "A": 68, "B": 5, "C": 15, "D": 7, "AOF": 0, "R7": 4, "CF": 0, "neB4": 16, "Chot": 1, "Dhot": 3}
    HOT C T=new code 1244->1016 lanes=- tomo_db0::WbEngine::serve_tls_impl<true, true, true, false, true>(tomo_db0::Client&, tomo_db0::TlsCo
    HOT D T=new code 4132->4033 lanes=savefix unsigned int tomo_db0::ExLoopT<true>::fused_pass_impl<32u, true, false, false>()
    HOT D T=new code 4290->4306 lanes=savefix unsigned int tomo_db0::ExLoopT<true>::fused_pass_impl<32u, true, false, true>()
    HOT D T=new code 3472->3416 lanes=racefix bool tomo_db0::ExLoopT<true>::execute<false, true>(tomo_db0::Task const&)
    C T=new code 4723->4688 lanes=- void tomo_db0::IoLoop::r7_run_loop<false, false, false, true, false>()
    C T=new code 4698->4663 lanes=- void tomo_db0::IoLoop::r7_run_loop<false, false, true, true, false>()
    C T=new code 4771->4736 lanes=- void tomo_db0::IoLoop::r7_run_loop<false, true, false, true, false>()
    C T=new code 4698->4663 lanes=- void tomo_db0::IoLoop::r7_run_loop<false, true, true, true, false>()
    C T=new code 4787->4752 lanes=- void tomo_db0::IoLoop::r7_run_loop<true, false, false, true, false>()
    C T=new code 4714->4679 lanes=- void tomo_db0::IoLoop::r7_run_loop<true, false, true, true, false>()
    C T=new code 4851->4816 lanes=- void tomo_db0::IoLoop::r7_run_loop<true, true, false, true, false>()
    C T=new code 4714->4679 lanes=- void tomo_db0::IoLoop::r7_run_loop<true, true, true, true, false>()
    C T=new code 3645->3621 lanes=- tomo_db0::IoLoop::lb_control_pass()
    C T=new code 1306->1077 lanes=- tomo_db0::IoLoop::prepare_activation()
    C T=new code 2588->2623 lanes=- tomo_db0::FlatStore::choose_victim(tomo_db0::Slice)
    C T=new added 0->83 lanes=- tomo_db0::Server::flip_client_at(unsigned int, unsigned int) const
    C T=new added 0->68 lanes=- tomo_db0::ExLoopT<true>::shutdown_snapshot_blocks_tasks() const
    C T=new code 1244->1016 lanes=- tomo_db0::WbEngine::serve_tls_impl<true, true, true, false, true>(tomo_db0::Client&, tomo_db0::TlsCo
    C T=new code 1140->1159 lanes=- tomo_db0::run_fused_server_reordered(tomo_db0::Server&, tomo_db0::SnapshotLoadPlan const*, std::vect
    D T=new code 4432->4530 lanes=flipfix unsigned int tomo_db0::IoLoop::flip_control_pass<false>()
    D T=new code 4432->4530 lanes=flipfix unsigned int tomo_db0::IoLoop::flip_control_pass<true>()
    D T=new code 4132->4033 lanes=savefix unsigned int tomo_db0::ExLoopT<true>::fused_pass_impl<32u, true, false, false>()
    D T=new code 4290->4306 lanes=savefix unsigned int tomo_db0::ExLoopT<true>::fused_pass_impl<32u, true, false, true>()
    D T=new code 3472->3416 lanes=racefix bool tomo_db0::ExLoopT<true>::execute<false, true>(tomo_db0::Task const&)
    D T=new code 4484->4571 lanes=flipfix std::thread::_State_impl<std::thread::_Invoker<std::tuple<tomo_db0::run_fused_server_reordered(tomo_
    D T=new code 311->334 lanes=flipfix std::thread::_State_impl<std::thread::_Invoker<std::tuple<tomo_db0::run_fused_server_reordered(tomo_
{"object": "db0/src/core/reorder.o", "params": "--param inline-unit-growth=0 --param large-unit-insns=147900", "unit": 113097, "hot_changed": 37, "A": 68, "B": 5, "C": 9, "D": 7, "AOF": 0, "R7": 4, "CF": 0, "neB4": 15, "Chot": 1, "Dhot": 3}
    HOT C T=new code 1244->1016 lanes=- tomo_db0::WbEngine::serve_tls_impl<true, true, true, false, true>(tomo_db0::Client&, tomo_db0::TlsCo
    HOT D T=new code 9522->9602 lanes=clientfix tomo_db0::IoLoop::DispatchResult tomo_db0::IoLoop::parse_and_dispatch<true, 0u, false>(tomo_db0::Cli
    HOT D T=new code 4132->4033 lanes=savefix unsigned int tomo_db0::ExLoopT<true>::fused_pass_impl<32u, true, false, false>()
    HOT D T=new code 4290->4306 lanes=savefix unsigned int tomo_db0::ExLoopT<true>::fused_pass_impl<32u, true, false, true>()
    C T=new code 4771->4736 lanes=- void tomo_db0::IoLoop::r7_run_loop<false, true, false, true, false>()
    C T=new code 4787->4752 lanes=- void tomo_db0::IoLoop::r7_run_loop<true, false, false, true, false>()
    C T=new code 4851->4816 lanes=- void tomo_db0::IoLoop::r7_run_loop<true, true, false, true, false>()
    C T=new code 3645->3621 lanes=- tomo_db0::IoLoop::lb_control_pass()
    C T=new code 2588->2623 lanes=- tomo_db0::FlatStore::choose_victim(tomo_db0::Slice)
    C T=new added 0->83 lanes=- tomo_db0::Server::flip_client_at(unsigned int, unsigned int) const
    C T=new added 0->68 lanes=- tomo_db0::ExLoopT<true>::shutdown_snapshot_blocks_tasks() const
    C T=new code 1244->1016 lanes=- tomo_db0::WbEngine::serve_tls_impl<true, true, true, false, true>(tomo_db0::Client&, tomo_db0::TlsCo
    C T=new code 1140->1159 lanes=- tomo_db0::run_fused_server_reordered(tomo_db0::Server&, tomo_db0::SnapshotLoadPlan const*, std::vect
    D T=new code 4432->4577 lanes=flipfix unsigned int tomo_db0::IoLoop::flip_control_pass<false>()
    D T=new code 4432->4577 lanes=flipfix unsigned int tomo_db0::IoLoop::flip_control_pass<true>()
    D T=new code 9522->9602 lanes=clientfix tomo_db0::IoLoop::DispatchResult tomo_db0::IoLoop::parse_and_dispatch<true, 0u, false>(tomo_db0::Cli
    D T=new code 4132->4033 lanes=savefix unsigned int tomo_db0::ExLoopT<true>::fused_pass_impl<32u, true, false, false>()
    D T=new code 4290->4306 lanes=savefix unsigned int tomo_db0::ExLoopT<true>::fused_pass_impl<32u, true, false, true>()
    D T=new code 4484->4571 lanes=flipfix std::thread::_State_impl<std::thread::_Invoker<std::tuple<tomo_db0::run_fused_server_reordered(tomo_
    D T=new code 311->334 lanes=flipfix std::thread::_State_impl<std::thread::_Invoker<std::tuple<tomo_db0::run_fused_server_reordered(tomo_
{"object": "db0/src/core/reorder.o", "params": "--param inline-unit-growth=0 --param large-unit-insns=147979", "unit": 113097, "hot_changed": 37, "A": 70, "B": 4, "C": 4, "D": 5, "AOF": 0, "R7": 4, "CF": 0, "neB4": 10, "Chot": 1, "Dhot": 1}
    HOT C T=new code 1244->1016 lanes=- tomo_db0::WbEngine::serve_tls_impl<true, true, true, false, true>(tomo_db0::Client&, tomo_db0::TlsCo
    HOT D T=new code 4132->4033 lanes=savefix unsigned int tomo_db0::ExLoopT<true>::fused_pass_impl<32u, true, false, false>()
    C T=new code 4851->4816 lanes=- void tomo_db0::IoLoop::r7_run_loop<true, true, false, true, false>()
    C T=new added 0->83 lanes=- tomo_db0::Server::flip_client_at(unsigned int, unsigned int) const
    C T=new code 1244->1016 lanes=- tomo_db0::WbEngine::serve_tls_impl<true, true, true, false, true>(tomo_db0::Client&, tomo_db0::TlsCo
    C T=new code 1140->1159 lanes=- tomo_db0::run_fused_server_reordered(tomo_db0::Server&, tomo_db0::SnapshotLoadPlan const*, std::vect
    D T=new code 4432->4577 lanes=flipfix unsigned int tomo_db0::IoLoop::flip_control_pass<false>()
    D T=new code 4432->4577 lanes=flipfix unsigned int tomo_db0::IoLoop::flip_control_pass<true>()
    D T=new code 4132->4033 lanes=savefix unsigned int tomo_db0::ExLoopT<true>::fused_pass_impl<32u, true, false, false>()
    D T=new code 4484->4571 lanes=flipfix std::thread::_State_impl<std::thread::_Invoker<std::tuple<tomo_db0::run_fused_server_reordered(tomo_
    D T=new code 311->334 lanes=flipfix std::thread::_State_impl<std::thread::_Invoker<std::tuple<tomo_db0::run_fused_server_reordered(tomo_
{"object": "db0/src/core/reorder.o", "params": "--param inline-unit-growth=0 --param large-unit-insns=148020", "unit": 113097, "hot_changed": 37, "A": 71, "B": 4, "C": 3, "D": 4, "AOF": 0, "R7": 4, "CF": 0, "neB4": 11, "Chot": 1, "Dhot": 0}
    HOT C T=new code 1244->1016 lanes=- tomo_db0::WbEngine::serve_tls_impl<true, true, true, false, true>(tomo_db0::Client&, tomo_db0::TlsCo
    C T=new added 0->83 lanes=- tomo_db0::Server::flip_client_at(unsigned int, unsigned int) const
    C T=new code 1244->1016 lanes=- tomo_db0::WbEngine::serve_tls_impl<true, true, true, false, true>(tomo_db0::Client&, tomo_db0::TlsCo
    C T=new code 1140->1159 lanes=- tomo_db0::run_fused_server_reordered(tomo_db0::Server&, tomo_db0::SnapshotLoadPlan const*, std::vect
    D T=new code 4432->4577 lanes=flipfix unsigned int tomo_db0::IoLoop::flip_control_pass<false>()
    D T=new code 4432->4577 lanes=flipfix unsigned int tomo_db0::IoLoop::flip_control_pass<true>()
    D T=new code 4484->4571 lanes=flipfix std::thread::_State_impl<std::thread::_Invoker<std::tuple<tomo_db0::run_fused_server_reordered(tomo_
    D T=new code 311->334 lanes=flipfix std::thread::_State_impl<std::thread::_Invoker<std::tuple<tomo_db0::run_fused_server_reordered(tomo_
{"object": "db0/src/core/reorder.o", "params": "--param inline-unit-growth=0 --param large-unit-insns=148060", "unit": 113097, "hot_changed": 37, "A": 72, "B": 5, "C": 2, "D": 2, "AOF": 0, "R7": 4, "CF": 0, "neB4": 12, "Chot": 1, "Dhot": 0}
    HOT C T=new code 1244->1016 lanes=- tomo_db0::WbEngine::serve_tls_impl<true, true, true, false, true>(tomo_db0::Client&, tomo_db0::TlsCo
    C T=new code 1244->1016 lanes=- tomo_db0::WbEngine::serve_tls_impl<true, true, true, false, true>(tomo_db0::Client&, tomo_db0::TlsCo
    C T=new code 1140->1159 lanes=- tomo_db0::run_fused_server_reordered(tomo_db0::Server&, tomo_db0::SnapshotLoadPlan const*, std::vect
    D T=new code 4484->4571 lanes=flipfix std::thread::_State_impl<std::thread::_Invoker<std::tuple<tomo_db0::run_fused_server_reordered(tomo_
    D T=new code 311->334 lanes=flipfix std::thread::_State_impl<std::thread::_Invoker<std::tuple<tomo_db0::run_fused_server_reordered(tomo_
{"object": "db0/src/core/reorder.o", "params": "--param inline-unit-growth=0 --param large-unit-insns=148100", "unit": 113097, "hot_changed": 36, "A": 68, "B": 5, "C": 3, "D": 4, "AOF": 0, "R7": 4, "CF": 0, "neB4": 12, "Chot": 1, "Dhot": 0}
    HOT C T=new code 1244->1016 lanes=- tomo_db0::WbEngine::serve_tls_impl<true, true, true, false, true>(tomo_db0::Client&, tomo_db0::TlsCo
    C T=new added 0->83 lanes=- tomo_db0::Server::flip_client_at(unsigned int, unsigned int) const
    C T=new code 1244->1016 lanes=- tomo_db0::WbEngine::serve_tls_impl<true, true, true, false, true>(tomo_db0::Client&, tomo_db0::TlsCo
    C T=new code 1140->1159 lanes=- tomo_db0::run_fused_server_reordered(tomo_db0::Server&, tomo_db0::SnapshotLoadPlan const*, std::vect
    D T=new code 4432->4577 lanes=flipfix unsigned int tomo_db0::IoLoop::flip_control_pass<false>()
    D T=new code 4432->4577 lanes=flipfix unsigned int tomo_db0::IoLoop::flip_control_pass<true>()
    D T=new code 4484->4571 lanes=flipfix std::thread::_State_impl<std::thread::_Invoker<std::tuple<tomo_db0::run_fused_server_reordered(tomo_
    D T=new code 311->334 lanes=flipfix std::thread::_State_impl<std::thread::_Invoker<std::tuple<tomo_db0::run_fused_server_reordered(tomo_
{"object": "db0/src/core/reorder.o", "params": "--param inline-unit-growth=0 --param large-unit-insns=148150", "unit": 113097, "hot_changed": 35, "A": 69, "B": 4, "C": 2, "D": 4, "AOF": 0, "R7": 4, "CF": 0, "neB4": 11, "Chot": 0, "Dhot": 0}
    C T=new added 0->83 lanes=- tomo_db0::Server::flip_client_at(unsigned int, unsigned int) const
    C T=new code 1140->1159 lanes=- tomo_db0::run_fused_server_reordered(tomo_db0::Server&, tomo_db0::SnapshotLoadPlan const*, std::vect
    D T=new code 4432->4577 lanes=flipfix unsigned int tomo_db0::IoLoop::flip_control_pass<false>()
    D T=new code 4432->4577 lanes=flipfix unsigned int tomo_db0::IoLoop::flip_control_pass<true>()
    D T=new code 4484->4571 lanes=flipfix std::thread::_State_impl<std::thread::_Invoker<std::tuple<tomo_db0::run_fused_server_reordered(tomo_
    D T=new code 311->334 lanes=flipfix std::thread::_State_impl<std::thread::_Invoker<std::tuple<tomo_db0::run_fused_server_reordered(tomo_
{"object": "db0/src/core/reorder.o", "params": "--param inline-unit-growth=0 --param large-unit-insns=148200", "unit": 113097, "hot_changed": 34, "A": 67, "B": 5, "C": 2, "D": 4, "AOF": 0, "R7": 4, "CF": 0, "neB4": 12, "Chot": 0, "Dhot": 0}
    C T=new added 0->83 lanes=- tomo_db0::Server::flip_client_at(unsigned int, unsigned int) const
    C T=new code 1140->1159 lanes=- tomo_db0::run_fused_server_reordered(tomo_db0::Server&, tomo_db0::SnapshotLoadPlan const*, std::vect
    D T=new code 4432->4577 lanes=flipfix unsigned int tomo_db0::IoLoop::flip_control_pass<false>()
    D T=new code 4432->4577 lanes=flipfix unsigned int tomo_db0::IoLoop::flip_control_pass<true>()
    D T=new code 4484->4571 lanes=flipfix std::thread::_State_impl<std::thread::_Invoker<std::tuple<tomo_db0::run_fused_server_reordered(tomo_
    D T=new code 311->334 lanes=flipfix std::thread::_State_impl<std::thread::_Invoker<std::tuple<tomo_db0::run_fused_server_reordered(tomo_
{"object": "db0/src/core/reorder.o", "params": "--param inline-unit-growth=0 --param large-unit-insns=148250", "unit": 113097, "hot_changed": 33, "A": 68, "B": 5, "C": 1, "D": 2, "AOF": 0, "R7": 4, "CF": 0, "neB4": 12, "Chot": 0, "Dhot": 0}
    C T=new code 1140->1159 lanes=- tomo_db0::run_fused_server_reordered(tomo_db0::Server&, tomo_db0::SnapshotLoadPlan const*, std::vect
    D T=new code 4484->4571 lanes=flipfix std::thread::_State_impl<std::thread::_Invoker<std::tuple<tomo_db0::run_fused_server_reordered(tomo_
    D T=new code 311->334 lanes=flipfix std::thread::_State_impl<std::thread::_Invoker<std::tuple<tomo_db0::run_fused_server_reordered(tomo_
{"object": "db0/src/core/reorder.o", "params": "--param inline-unit-growth=0 --param large-unit-insns=148300", "unit": 113097, "hot_changed": 34, "A": 68, "B": 5, "C": 3, "D": 2, "AOF": 0, "R7": 4, "CF": 0, "neB4": 14, "Chot": 1, "Dhot": 0}
    HOT C T=new code 1195->1404 lanes=- unsigned int tomo_db0::ExLoopT<true>::drain_tasks_read_local_interleaved<false>(bool, bool&)
    C T=new code 1195->1404 lanes=- unsigned int tomo_db0::ExLoopT<true>::drain_tasks_read_local_interleaved<false>(bool, bool&)
    C T=new code 663->628 lanes=- tomo_db0::FlatStore::snapshot_progress(unsigned int, unsigned int)
    C T=new code 1140->1159 lanes=- tomo_db0::run_fused_server_reordered(tomo_db0::Server&, tomo_db0::SnapshotLoadPlan const*, std::vect
    D T=new code 4484->4571 lanes=flipfix std::thread::_State_impl<std::thread::_Invoker<std::tuple<tomo_db0::run_fused_server_reordered(tomo_
    D T=new code 311->334 lanes=flipfix std::thread::_State_impl<std::thread::_Invoker<std::tuple<tomo_db0::run_fused_server_reordered(tomo_
{"object": "db0/src/core/reorder.o", "params": "--param inline-unit-growth=0 --param large-unit-insns=148319", "unit": 113097, "hot_changed": 34, "A": 67, "B": 5, "C": 3, "D": 2, "AOF": 0, "R7": 4, "CF": 0, "neB4": 14, "Chot": 1, "Dhot": 0}
    HOT C T=new code 1195->1404 lanes=- unsigned int tomo_db0::ExLoopT<true>::drain_tasks_read_local_interleaved<false>(bool, bool&)
    C T=new code 1195->1404 lanes=- unsigned int tomo_db0::ExLoopT<true>::drain_tasks_read_local_interleaved<false>(bool, bool&)
    C T=new code 663->628 lanes=- tomo_db0::FlatStore::snapshot_progress(unsigned int, unsigned int)
    C T=new code 1140->1159 lanes=- tomo_db0::run_fused_server_reordered(tomo_db0::Server&, tomo_db0::SnapshotLoadPlan const*, std::vect
    D T=new code 4484->4571 lanes=flipfix std::thread::_State_impl<std::thread::_Invoker<std::tuple<tomo_db0::run_fused_server_reordered(tomo_
    D T=new code 311->334 lanes=flipfix std::thread::_State_impl<std::thread::_Invoker<std::tuple<tomo_db0::run_fused_server_reordered(tomo_
{"object": "db0/src/core/reorder.o", "params": "--param inline-unit-growth=0 --param large-unit-insns=148347", "unit": 113097, "hot_changed": 34, "A": 68, "B": 6, "C": 3, "D": 2, "AOF": 0, "R7": 4, "CF": 0, "neB4": 15, "Chot": 1, "Dhot": 0}
    HOT C T=new code 1195->1404 lanes=- unsigned int tomo_db0::ExLoopT<true>::drain_tasks_read_local_interleaved<false>(bool, bool&)
    C T=new code 1195->1404 lanes=- unsigned int tomo_db0::ExLoopT<true>::drain_tasks_read_local_interleaved<false>(bool, bool&)
    C T=new code 663->628 lanes=- tomo_db0::FlatStore::snapshot_progress(unsigned int, unsigned int)
    C T=new code 1140->1159 lanes=- tomo_db0::run_fused_server_reordered(tomo_db0::Server&, tomo_db0::SnapshotLoadPlan const*, std::vect
    D T=new code 4484->4571 lanes=flipfix std::thread::_State_impl<std::thread::_Invoker<std::tuple<tomo_db0::run_fused_server_reordered(tomo_
    D T=new code 311->334 lanes=flipfix std::thread::_State_impl<std::thread::_Invoker<std::tuple<tomo_db0::run_fused_server_reordered(tomo_
{"object": "db0/src/core/reorder.o", "params": "--param inline-unit-growth=0 --param large-unit-insns=148400", "unit": 113097, "hot_changed": 34, "A": 67, "B": 6, "C": 8, "D": 3, "AOF": 0, "R7": 4, "CF": 0, "neB4": 21, "Chot": 1, "Dhot": 1}
    HOT C T=new code 1195->1404 lanes=- unsigned int tomo_db0::ExLoopT<true>::drain_tasks_read_local_interleaved<false>(bool, bool&)
    HOT D T=new code 9522->9602 lanes=clientfix tomo_db0::IoLoop::DispatchResult tomo_db0::IoLoop::parse_and_dispatch<true, 0u, false>(tomo_db0::Cli
    C T=new code 3728->3933 lanes=- tomo_db0::IoLoop::pubsub_finish_pending(unsigned long)
    C T=new code 2828->2823 lanes=- tomo_db0::IoLoop::pubsub_reply_restricted(tomo_db0::Op&) [clone .isra.0]
    C T=new code 1195->1404 lanes=- unsigned int tomo_db0::ExLoopT<true>::drain_tasks_read_local_interleaved<false>(bool, bool&)
    C T=new code 663->628 lanes=- tomo_db0::FlatStore::snapshot_progress(unsigned int, unsigned int)
    C T=new removed 232->0 lanes=- std::__cxx11::basic_string<char, std::char_traits<char>, std::allocator<char> >::basic_string(std::_
    C T=new removed 232->0 lanes=- std::__cxx11::basic_string<char, std::char_traits<char>, std::allocator<char> >::basic_string(std::_
    C T=new code 1140->1159 lanes=- tomo_db0::run_fused_server_reordered(tomo_db0::Server&, tomo_db0::SnapshotLoadPlan const*, std::vect
    C T=new code 2942->3130 lanes=- tomo_db0::Server::flip_smt_pairing_error[abi:cxx11](unsigned int) const::{lambda(unsigned int)#1}::o
    D T=new code 9522->9602 lanes=clientfix tomo_db0::IoLoop::DispatchResult tomo_db0::IoLoop::parse_and_dispatch<true, 0u, false>(tomo_db0::Cli
    D T=new code 4484->4571 lanes=flipfix std::thread::_State_impl<std::thread::_Invoker<std::tuple<tomo_db0::run_fused_server_reordered(tomo_
    D T=new code 311->334 lanes=flipfix std::thread::_State_impl<std::thread::_Invoker<std::tuple<tomo_db0::run_fused_server_reordered(tomo_
