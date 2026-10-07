# Every changed emitted body

All ordinary command, parse, dispatch and writeback bodies are preserved.
Literal bytes and relocation-resolved identity are separate tests; neither this
list nor the inventory hides added/deleted bodies or renamed clones.

| Object | Body | PRE bytes | POST bytes | Reason |
|---|---|---:|---:|---|
| `db0/src/cmd/lbsignals.o` | `tomo_db0::lbsignals_format(tomo_db0::LbSnapshot const&, std::__cxx11::basic_string<char, std::char_traits<char>, std::allocator<char> >&)` | 907 | 666 | CT18: remove the rejected DEBUG split estimator and its three derived values. |
| `db0/src/cmd/lbsignals.o` | `tomo_db0::lbsignals_info_section(tomo_db0::Server&, std::__cxx11::basic_string<char, std::char_traits<char>, std::allocator<char> >&)` | 2714 | 2646 | CT17/CT18: rename six client counters and remove the rejected INFO estimator. |
| `db0/src/cmd/t_server.o` | `tomo_db0::(anonymous namespace)::cmd_info(tomo_db0::Shard&, tomo_db0::Op&)` | 16371 | 16371 | CT16: remove duplicate trigger fields and duplicate formatting arguments. |
| `db0/src/core/lbplanner.o` | `tomo_db0::Server::lb_controller_tick(unsigned int, unsigned long)::{lambda(double, tomo_db0::LbAutotune::QuietJitter&, unsigned int&, unsigned int)#1}::operator()(double, tomo_db0::LbAutotune::QuietJitter&, unsigned int&, unsigned int) const` | 575 | 559 | CT19: remove the unreachable ratio == 0 disjunct; includes the corresponding existing PAD controller. |
| `db0/src/core/lbplanner.o` | `tomo_db0::Server::lb_controller_tick_pad(unsigned int, unsigned long)::{lambda(double, tomo_db0::LbAutotune::QuietJitter&, unsigned int&, unsigned int)#1}::operator()(double, tomo_db0::LbAutotune::QuietJitter&, unsigned int&, unsigned int) const` | 575 | 559 | CT19: remove the unreachable ratio == 0 disjunct; includes the corresponding existing PAD controller. |
| `src/cmd/lbsignals.o` | `tomo::lbsignals_format(tomo::LbSnapshot const&, std::__cxx11::basic_string<char, std::char_traits<char>, std::allocator<char> >&)` | 907 | 666 | CT18: remove the rejected DEBUG split estimator and its three derived values. |
| `src/cmd/lbsignals.o` | `tomo::lbsignals_info_section(tomo::Server&, std::__cxx11::basic_string<char, std::char_traits<char>, std::allocator<char> >&)` | 2714 | 2646 | CT17/CT18: rename six client counters and remove the rejected INFO estimator. |
| `src/cmd/t_server.o` | `tomo::(anonymous namespace)::cmd_info(tomo::Shard&, tomo::Op&)` | 16667 | 16667 | CT16: remove duplicate trigger fields and duplicate formatting arguments. |
| `src/core/lbplanner.o` | `tomo::Server::lb_controller_tick(unsigned int, unsigned long)::{lambda(double, tomo::LbAutotune::QuietJitter&, unsigned int&, unsigned int)#1}::operator()(double, tomo::LbAutotune::QuietJitter&, unsigned int&, unsigned int) const` | 575 | 559 | CT19: remove the unreachable ratio == 0 disjunct; includes the corresponding existing PAD controller. |
| `src/core/lbplanner.o` | `tomo::Server::lb_controller_tick_pad(unsigned int, unsigned long)::{lambda(double, tomo::LbAutotune::QuietJitter&, unsigned int&, unsigned int)#1}::operator()(double, tomo::LbAutotune::QuietJitter&, unsigned int&, unsigned int) const` | 575 | 559 | CT19: remove the unreachable ratio == 0 disjunct; includes the corresponding existing PAD controller. |

Six additional bodies differ only in relocation displacements (all target identities agree):

| Object | Body | Reason |
|---|---|---|
| `db0/src/core/lbplanner.o` | `tomo_db0::Server::lb_controller_tick(unsigned int, unsigned long)` | Only relocation displacements differ; instructions and exact relocation target identities agree. |
| `db0/src/core/lbplanner.o` | `tomo_db0::Server::lb_controller_tick_pad(unsigned int, unsigned long)` | Only relocation displacements differ; instructions and exact relocation target identities agree. |
| `db0/src/core/lbplanner.o` | `tomo_db0::IoLoop::lb_control_pass_pad()` | Only relocation displacements differ; instructions and exact relocation target identities agree. |
| `src/core/lbplanner.o` | `tomo::Server::lb_controller_tick(unsigned int, unsigned long)` | Only relocation displacements differ; instructions and exact relocation target identities agree. |
| `src/core/lbplanner.o` | `tomo::Server::lb_controller_tick_pad(unsigned int, unsigned long)` | Only relocation displacements differ; instructions and exact relocation target identities agree. |
| `src/core/lbplanner.o` | `tomo::IoLoop::lb_control_pass_pad()` | Only relocation displacements differ; instructions and exact relocation target identities agree. |

The linked R7 inventory reports three further address-label differences, not instruction or control-flow changes. Each is one LEA of an unnamed 18-entry UrKind jump table. The byte-identical object bodies resolve all 54 entries to the same offsets within the same functions. `tools/deadcode2_linked.py` checks the bound, load/add/jump sequence, complete normalized bodies, and every destination; it does not change the existing normalizer.

- `void tomo_db0::IoLoop::run_loop<false, false, false, false, (unsigned char)0, false>()`
- `void tomo_db0::IoLoop::run_loop<false, false, true, false, (unsigned char)0, false>()`
- `void tomo_db0::IoLoop::run_loop<true, false, false, false, (unsigned char)0, false>()`
