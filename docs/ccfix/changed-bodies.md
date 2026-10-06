# Every changed object-function body

This is an exhaustive index of the 89 unequal/additional/removed object-function occurrences. Sizes are object symbol sizes; address operands are compared by their resolved targets. See `changed-bodies-with-reasons.json` for each exact mangled symbol, full demangled name, byte sizes, and reason. Incidental compiler changes are disclosed, not treated as semantic feature changes or measured improvements.

1. `db0/src/cmd/acl.o` — `void tomo_db0::reply_map_header<tomo_db0::Op::Sink&>(tomo_db0::Op::Sink&, unsigned long, bool)` (276 → 381 bytes). Compiler consequence in the changed ACL TU: error construction/rejection edits change inlining, local code/data placement, or local-clone target identity; no direct source edit to this body.

2. `db0/src/cmd/acl.o` — `tomo_db0::acl_command_entry(tomo_db0::IoLoop&, tomo_db0::Client&, tomo_db0::Op&)` (12668 → 12700 bytes). CC13: prepend ERR to the ACL LOAD diagnostic; its exception/cleanup body moves with that code.

3. `db0/src/cmd/acl.o` — `tomo_db0::acl_command_entry(tomo_db0::IoLoop&, tomo_db0::Client&, tomo_db0::Op&) [clone .cold]` (685 → 685 bytes). CC13: prepend ERR to the ACL LOAD diagnostic; its exception/cleanup body moves with that code.

4. `db0/src/cmd/acl.o` — `tomo_db0::acl_finish_dispatch_denial(tomo_db0::IoLoop&, tomo_db0::Client&, tomo_db0::Op&, unsigned int, tomo_db0::AclDeniedReason, unsigned int)` (604 → 600 bytes). CC18: update rejected_calls instead of calls on rejection.

5. `db0/src/cmd/acl.o` — `tomo_db0::IoLoop::pubsub_finish_pending(unsigned long)` (3398 → 3398 bytes). Compiler consequence in the changed ACL TU: error construction/rejection edits change inlining, local code/data placement, or local-clone target identity; no direct source edit to this body.

6. `db0/src/cmd/acl.o` — `void std::__introsort_loop<__gnu_cxx::__normal_iterator<tomo_db0::(anonymous namespace)::AclLogEntry*, std::vector<tomo_db0::(anonymous namespace)::AclLogEntry, std::allocator<tomo_db0::(anonymous namespace)::AclLogEntry> > >, long, __gnu_cxx::__ops::_Iter_comp_iter<tomo_db0::(anonymous namespace)::acl_reply_log(tomo_db0::Op&)::{lambda(tomo_db0::(anonymous namespace)::AclLogEntry const&, tomo_db0::(anonymous namespace)::AclLogEntry const&)#1}> >(__gnu_cxx::__normal_iterator<tomo_db0::(anonymous namespace)::AclLogEntry*, std::vector<tomo_db0::(anonymous namespace)::AclLogEntry, std::allocator<tomo_db0::(anonymous namespace)::AclLogEntry> > >, __gnu_cxx::__normal_iterator<tomo_db0::(anonymous namespace)::AclLogEntry*, std::vector<tomo_db0::(anonymous namespace)::AclLogEntry, std::allocator<tomo_db0::(anonymous namespace)::AclLogEntry> > >, long, __gnu_cxx::__ops::_Iter_comp_iter<tomo_db0::(anonymous namespace)::acl_reply_log(tomo_db0::Op&)::{lambda(tomo_db0::(anonymous namespace)::AclLogEntry const&, tomo_db0::(anonymous namespace)::AclLogEntry const&)#1}>)` (2178 → 2143 bytes). Compiler consequence in the changed ACL TU: error construction/rejection edits change inlining, local code/data placement, or local-clone target identity; no direct source edit to this body.

7. `db0/src/cmd/acl.o` — `std::enable_if<std::__and_<std::__not_<std::__is_tuple_like<tomo_db0::(anonymous namespace)::AclLogEntry> >, std::is_move_constructible<tomo_db0::(anonymous namespace)::AclLogEntry>, std::is_move_assignable<tomo_db0::(anonymous namespace)::AclLogEntry> >::value, void>::type std::swap<tomo_db0::(anonymous namespace)::AclLogEntry>(tomo_db0::(anonymous namespace)::AclLogEntry&, tomo_db0::(anonymous namespace)::AclLogEntry&)` (1011 → 851 bytes). Compiler consequence in the changed ACL TU: error construction/rejection edits change inlining, local code/data placement, or local-clone target identity; no direct source edit to this body.

8. `db0/src/cmd/t_server.o` — `tomo_db0::(anonymous namespace)::StatBaseline::~StatBaseline()` (49 → 98 bytes). CC18: own, aggregate, reset, and destroy the two additional baseline vectors.

9. `db0/src/cmd/t_server.o` — `tomo_db0::(anonymous namespace)::StatBaseline::~StatBaseline()` (49 → 98 bytes). CC18: own, aggregate, reset, and destroy the two additional baseline vectors.

10. `db0/src/cmd/t_server.o` — `tomo_db0::(anonymous namespace)::cmd_info(tomo_db0::Shard&, tomo_db0::Op&)` (16161 → 16031 bytes). CC18: aggregate and emit the three counters, with no timing fields; exception cleanup follows the new vectors.

11. `db0/src/cmd/t_server.o` — `tomo_db0::(anonymous namespace)::cmd_info(tomo_db0::Shard&, tomo_db0::Op&) [clone .cold]` (349 → 369 bytes). CC18: aggregate and emit the three counters, with no timing fields; exception cleanup follows the new vectors.

12. `db0/src/cmd/t_server.o` — `void tomo_db0::reply_map_header<tomo_db0::Op::Sink&>(tomo_db0::Op::Sink&, unsigned long, bool)` (381 → 593 bytes). Compiler consequence in the changed administrative TU: new baseline vector operations/data placement and inlining budget; no direct source edit to this body. Ordinary command bodies are separately checked.

13. `db0/src/cmd/t_server.o` — `tomo_db0::kvobj_external_bytes(tomo_db0::KvObj const*)` (1463 → 1606 bytes). Compiler consequence in the changed administrative TU: new baseline vector operations/data placement and inlining budget; no direct source edit to this body. Ordinary command bodies are separately checked.

14. `db0/src/cmd/t_server.o` — `tomo_db0::serialize_notify_flags[abi:cxx11](unsigned int)` (634 → 586 bytes). CC12: canonical flag order; n only in the non-A branch.

15. `db0/src/cmd/t_server.o` — `tomo_db0::cfg_parse_save_schedule(char const*, unsigned long, std::vector<tomo_db0::SaveClause, std::allocator<tomo_db0::SaveClause> >&)` (1928 → 2056 bytes). Compiler consequence in the changed administrative TU: new baseline vector operations/data placement and inlining budget; no direct source edit to this body. Ordinary command bodies are separately checked.

16. `db0/src/cmd/t_server.o` — `tomo_db0::command_config_resetstat()` (2029 → 2199 bytes). CC18: own, aggregate, reset, and destroy the two additional baseline vectors.

17. `db0/src/cmd/t_server.o` — `tomo_db0::command_config_resetstat() [clone .cold]` (64 → 61 bytes). CC18: own, aggregate, reset, and destroy the two additional baseline vectors.

18. `db0/src/cmd/t_server.o` — `tomo_db0::command_client_disconnected(tomo_db0::Client*)` (689 → 689 bytes). Compiler consequence in the changed administrative TU: new baseline vector operations/data placement and inlining budget; no direct source edit to this body. Ordinary command bodies are separately checked.

19. `db0/src/cmd/t_server.o` — `tomo_db0::command_client_migration_reserve(unsigned int)` (393 → 393 bytes). Compiler consequence in the changed administrative TU: new baseline vector operations/data placement and inlining budget; no direct source edit to this body. Ordinary command bodies are separately checked.

20. `db0/src/cmd/t_server.o` — `tomo_db0::Compact::capacity_bytes() const` (200 → 0 bytes). Compiler consequence in the changed administrative TU: new baseline vector operations/data placement and inlining budget; no direct source edit to this body. Ordinary command bodies are separately checked.

21. `db0/src/cmd/t_server.o` — `std::_Vector_base<unsigned long, std::allocator<unsigned long> >::~_Vector_base()` (33 → 0 bytes). Compiler consequence in the changed administrative TU: new baseline vector operations/data placement and inlining budget; no direct source edit to this body. Ordinary command bodies are separately checked.

22. `db0/src/cmd/t_server.o` — `std::_Vector_base<unsigned long, std::allocator<unsigned long> >::~_Vector_base()` (33 → 0 bytes). Compiler consequence in the changed administrative TU: new baseline vector operations/data placement and inlining budget; no direct source edit to this body. Ordinary command bodies are separately checked.

23. `db0/src/cmd/t_server.o` — `std::vector<unsigned long, std::allocator<unsigned long> >::operator=(std::vector<unsigned long, std::allocator<unsigned long> > const&) [clone .isra.0]` (0 → 453 bytes). Compiler consequence in the changed administrative TU: new baseline vector operations/data placement and inlining budget; no direct source edit to this body. Ordinary command bodies are separately checked.

24. `db0/src/cmd/t_server.o` — `__tls_init` (152 → 152 bytes). Compiler consequence in the changed administrative TU: new baseline vector operations/data placement and inlining budget; no direct source edit to this body. Ordinary command bodies are separately checked.

25. `db0/src/cmd/xshard.o` — `tomo_db0::(anonymous namespace)::classify_keys(tomo_db0::Op const&, tomo_db0::(anonymous namespace)::Kind, tomo_db0::(anonymous namespace)::XshardKeyHints const&, tomo_db0::(anonymous namespace)::XshardKeyPlan&)` (947 → 945 bytes). Compiler consequence in the changed notification/auth TU: added cold classifier and removed suppression change inlining, local code/data placement, or local-clone identity; no direct source edit to this body.

26. `db0/src/cmd/xshard.o` — `tomo_db0::(anonymous namespace)::notify_event_name(tomo_db0::NotifyEventId)` (1072 → 1072 bytes). Compiler consequence in the changed notification/auth TU: added cold classifier and removed suppression change inlining, local code/data placement, or local-clone identity; no direct source edit to this body.

27. `db0/src/cmd/xshard.o` — `tomo_db0::notify_flat_emit(void*, unsigned int, tomo_db0::NotifyEventId, tomo_db0::Slice)` (426 → 329 bytes). CC11: admit keymiss only for a read lookup in the armed emitter.

28. `db0/src/cmd/xshard.o` — `tomo_db0::auth_dispatch_entry(tomo_db0::IoLoop&, tomo_db0::Client&, tomo_db0::Op&, unsigned int)` (780 → 764 bytes). CC18: update rejected_calls instead of calls on rejection.

29. `db0/src/cmd/xshard.o` — `tomo_db0::notify_flat_enabled(void*, unsigned int)` (247 → 199 bytes). CC11: remove command-flag suppression after the unchanged disabled-mask prefix.

30. `db0/src/cmd/xshard.o` — `tomo_db0::notify_keymiss_read_lookup(tomo_db0::Op const&, tomo_db0::Slice)` (0 → 652 bytes). CC11: new armed-path source-argument lookup classifier.

31. `db0/src/cmd/xshard.o` — `tomo_db0::IoLoop::pubsub_handle_home_request(tomo_db0::PubSubEvent&)` (4939 → 5165 bytes). Compiler consequence in the changed notification/auth TU: added cold classifier and removed suppression change inlining, local code/data placement, or local-clone identity; no direct source edit to this body.

32. `db0/src/cmd/xshard.o` — `tomo_db0::FlatStore::atomic_collapse_read_local(unsigned long, unsigned long)` (6828 → 6796 bytes). Compiler consequence in the changed notification/auth TU: added cold classifier and removed suppression change inlining, local code/data placement, or local-clone identity; no direct source edit to this body.

33. `db0/src/cmd/xshard.o` — `unsigned int& std::vector<unsigned int, std::allocator<unsigned int> >::emplace_back<unsigned int>(unsigned int&&) [clone .isra.0]` (371 → 352 bytes). Compiler consequence in the changed notification/auth TU: added cold classifier and removed suppression change inlining, local code/data placement, or local-clone identity; no direct source edit to this body.

34. `db0/src/main.o` — `tomo_db0::AofProducer::~AofProducer()` (2721 → 2722 bytes). Compiler consequence of the boot-only allocation change and the +1 inline budget used to retain PRE executor/IO bodies; no direct source edit to this body.

35. `db0/src/main.o` — `tomo_db0::AofProducer::~AofProducer()` (2721 → 2722 bytes). Compiler consequence of the boot-only allocation change and the +1 inline budget used to retain PRE executor/IO bodies; no direct source edit to this body.

36. `db0/src/main.o` — `tomo_db0::IoLoop::quiesce_accepts_for_conversion()` (677 → 664 bytes). Compiler consequence of the boot-only allocation change and the +1 inline budget used to retain PRE executor/IO bodies; no direct source edit to this body.

37. `db0/src/main.o` — `tomo_db0::Server::init(tomo_db0::Config const&, tomo_db0::AofReplayPlan const*)` (11945 → 11993 bytes). CC18: boot allocation now reserves three counter planes while preserving the calls-plane offset.

38. `db0/src/main.o` — `std::thread::_State_impl<std::thread::_Invoker<std::tuple<main::{lambda()#2}> > >::_M_run()` (2799 → 2799 bytes). Compiler consequence of the boot-only allocation change and the +1 inline budget used to retain PRE executor/IO bodies; no direct source edit to this body.

39. `db0/src/main.o` — `std::thread::_State_impl<std::thread::_Invoker<std::tuple<main::{lambda()#4}> > >::_M_run()` (2141 → 2141 bytes). Compiler consequence of the boot-only allocation change and the +1 inline budget used to retain PRE executor/IO bodies; no direct source edit to this body.

40. `src/cmd/acl.o` — `tomo::(anonymous namespace)::acl_reply_denied(tomo::Client&, tomo::Op&, unsigned int, tomo::AclDeniedReason, unsigned int, tomo::ThreadCtx&, tomo::AclLogContext) [clone .constprop.0]` (1429 → 1389 bytes). Compiler consequence in the changed ACL TU: error construction/rejection edits change inlining, local code/data placement, or local-clone target identity; no direct source edit to this body.

41. `src/cmd/acl.o` — `tomo::acl_initialize(tomo::Server&, tomo::Config const&, std::__cxx11::basic_string<char, std::char_traits<char>, std::allocator<char> >&)` (2632 → 2616 bytes). Compiler consequence in the changed ACL TU: error construction/rejection edits change inlining, local code/data placement, or local-clone target identity; no direct source edit to this body.

42. `src/cmd/acl.o` — `void tomo::reply_map_header<tomo::Op::Sink&>(tomo::Op::Sink&, unsigned long, bool)` (276 → 381 bytes). Compiler consequence in the changed ACL TU: error construction/rejection edits change inlining, local code/data placement, or local-clone target identity; no direct source edit to this body.

43. `src/cmd/acl.o` — `tomo::acl_command_entry(tomo::IoLoop&, tomo::Client&, tomo::Op&)` (12684 → 12700 bytes). CC13: prepend ERR to the ACL LOAD diagnostic; its exception/cleanup body moves with that code.

44. `src/cmd/acl.o` — `tomo::acl_finish_dispatch_denial(tomo::IoLoop&, tomo::Client&, tomo::Op&, unsigned int, tomo::AclDeniedReason, unsigned int)` (604 → 600 bytes). CC18: update rejected_calls instead of calls on rejection.

45. `src/cmd/acl.o` — `void std::__adjust_heap<__gnu_cxx::__normal_iterator<tomo::(anonymous namespace)::AclLogEntry*, std::vector<tomo::(anonymous namespace)::AclLogEntry, std::allocator<tomo::(anonymous namespace)::AclLogEntry> > >, long, tomo::(anonymous namespace)::AclLogEntry, __gnu_cxx::__ops::_Iter_comp_iter<tomo::(anonymous namespace)::acl_reply_log(tomo::Op&)::{lambda(tomo::(anonymous namespace)::AclLogEntry const&, tomo::(anonymous namespace)::AclLogEntry const&)#1}> >(__gnu_cxx::__normal_iterator<tomo::(anonymous namespace)::AclLogEntry*, std::vector<tomo::(anonymous namespace)::AclLogEntry, std::allocator<tomo::(anonymous namespace)::AclLogEntry> > >, long, long, tomo::(anonymous namespace)::AclLogEntry, __gnu_cxx::__ops::_Iter_comp_iter<tomo::(anonymous namespace)::acl_reply_log(tomo::Op&)::{lambda(tomo::(anonymous namespace)::AclLogEntry const&, tomo::(anonymous namespace)::AclLogEntry const&)#1}>) [clone .isra.0]` (2815 → 2816 bytes). Compiler consequence in the changed ACL TU: error construction/rejection edits change inlining, local code/data placement, or local-clone target identity; no direct source edit to this body.

46. `src/cmd/acl.o` — `std::enable_if<std::__and_<std::__not_<std::__is_tuple_like<tomo::(anonymous namespace)::AclLogEntry> >, std::is_move_constructible<tomo::(anonymous namespace)::AclLogEntry>, std::is_move_assignable<tomo::(anonymous namespace)::AclLogEntry> >::value, void>::type std::swap<tomo::(anonymous namespace)::AclLogEntry>(tomo::(anonymous namespace)::AclLogEntry&, tomo::(anonymous namespace)::AclLogEntry&)` (851 → 851 bytes). Compiler consequence in the changed ACL TU: error construction/rejection edits change inlining, local code/data placement, or local-clone target identity; no direct source edit to this body.

47. `src/cmd/t_server.o` — `tomo::(anonymous namespace)::cmd_config(tomo::Shard&, tomo::Op&)` (7671 → 7629 bytes). CC12/CC18: CONFIG uses changed flag serialization and reset-baseline code; compiler inlining changes this administrative handler.

48. `src/cmd/t_server.o` — `tomo::(anonymous namespace)::StatBaseline::~StatBaseline()` (49 → 98 bytes). CC18: own, aggregate, reset, and destroy the two additional baseline vectors.

49. `src/cmd/t_server.o` — `tomo::(anonymous namespace)::StatBaseline::~StatBaseline()` (49 → 98 bytes). CC18: own, aggregate, reset, and destroy the two additional baseline vectors.

50. `src/cmd/t_server.o` — `tomo::(anonymous namespace)::collect_config_updates(tomo::Op&, std::vector<std::pair<tomo::(anonymous namespace)::ConfigValue*, std::__cxx11::basic_string<char, std::char_traits<char>, std::allocator<char> > >, std::allocator<std::pair<tomo::(anonymous namespace)::ConfigValue*, std::__cxx11::basic_string<char, std::char_traits<char>, std::allocator<char> > > > >&)` (8600 → 8585 bytes). Compiler consequence in the changed administrative TU: new baseline vector operations/data placement and inlining budget; no direct source edit to this body. Ordinary command bodies are separately checked.

51. `src/cmd/t_server.o` — `tomo::(anonymous namespace)::collect_config_updates(tomo::Op&, std::vector<std::pair<tomo::(anonymous namespace)::ConfigValue*, std::__cxx11::basic_string<char, std::char_traits<char>, std::allocator<char> > >, std::allocator<std::pair<tomo::(anonymous namespace)::ConfigValue*, std::__cxx11::basic_string<char, std::char_traits<char>, std::allocator<char> > > > >&) [clone .cold]` (147 → 147 bytes). Compiler consequence in the changed administrative TU: new baseline vector operations/data placement and inlining budget; no direct source edit to this body. Ordinary command bodies are separately checked.

52. `src/cmd/t_server.o` — `tomo::(anonymous namespace)::cmd_info(tomo::Shard&, tomo::Op&)` (16215 → 16063 bytes). CC18: aggregate and emit the three counters, with no timing fields; exception cleanup follows the new vectors.

53. `src/cmd/t_server.o` — `tomo::(anonymous namespace)::cmd_info(tomo::Shard&, tomo::Op&) [clone .cold]` (353 → 369 bytes). CC18: aggregate and emit the three counters, with no timing fields; exception cleanup follows the new vectors.

54. `src/cmd/t_server.o` — `tomo::serialize_notify_flags[abi:cxx11](unsigned int)` (634 → 586 bytes). CC12: canonical flag order; n only in the non-A branch.

55. `src/cmd/t_server.o` — `tomo::cfg_parse_save_schedule(char const*, unsigned long, std::vector<tomo::SaveClause, std::allocator<tomo::SaveClause> >&)` (1928 → 2056 bytes). Compiler consequence in the changed administrative TU: new baseline vector operations/data placement and inlining budget; no direct source edit to this body. Ordinary command bodies are separately checked.

56. `src/cmd/t_server.o` — `tomo::command_client_connected(tomo::Client*, char const*, char const*, bool, unsigned long)` (1812 → 1812 bytes). Compiler consequence in the changed administrative TU: new baseline vector operations/data placement and inlining budget; no direct source edit to this body. Ordinary command bodies are separately checked.

57. `src/cmd/t_server.o` — `tomo::command_config_resetstat()` (2029 → 2199 bytes). CC18: own, aggregate, reset, and destroy the two additional baseline vectors.

58. `src/cmd/t_server.o` — `tomo::command_config_resetstat() [clone .cold]` (64 → 61 bytes). CC18: own, aggregate, reset, and destroy the two additional baseline vectors.

59. `src/cmd/t_server.o` — `tomo::command_client_disconnected(tomo::Client*)` (689 → 689 bytes). Compiler consequence in the changed administrative TU: new baseline vector operations/data placement and inlining budget; no direct source edit to this body. Ordinary command bodies are separately checked.

60. `src/cmd/t_server.o` — `tomo::command_client_migration_extract(tomo::Client*)` (864 → 864 bytes). Compiler consequence in the changed administrative TU: new baseline vector operations/data placement and inlining budget; no direct source edit to this body. Ordinary command bodies are separately checked.

61. `src/cmd/t_server.o` — `tomo::command_client_migration_install(void*)` (645 → 645 bytes). Compiler consequence in the changed administrative TU: new baseline vector operations/data placement and inlining budget; no direct source edit to this body. Ordinary command bodies are separately checked.

62. `src/cmd/t_server.o` — `tomo::command_client_migration_reserve(unsigned int)` (393 → 393 bytes). Compiler consequence in the changed administrative TU: new baseline vector operations/data placement and inlining budget; no direct source edit to this body. Ordinary command bodies are separately checked.

63. `src/cmd/t_server.o` — `tomo::cfg_client_output_buffer_limit_string[abi:cxx11](tomo::ClientOutputBufferLimits const&)` (5268 → 5051 bytes). Compiler consequence in the changed administrative TU: new baseline vector operations/data placement and inlining budget; no direct source edit to this body. Ordinary command bodies are separately checked.

64. `src/cmd/t_server.o` — `void tomo::reply_err<tomo::Op::Sink>(tomo::Op::Sink&&, char const*)` (973 → 774 bytes). Compiler consequence in the changed administrative TU: new baseline vector operations/data placement and inlining budget; no direct source edit to this body. Ordinary command bodies are separately checked.

65. `src/cmd/t_server.o` — `void tomo::reply_int<tomo::Op::Sink&>(tomo::Op::Sink&, long long)` (673 → 462 bytes). Compiler consequence in the changed administrative TU: new baseline vector operations/data placement and inlining budget; no direct source edit to this body. Ordinary command bodies are separately checked.

66. `src/cmd/t_server.o` — `tomo::Server::flipctl_debug_dump[abi:cxx11]() const` (2430 → 2537 bytes). Compiler consequence in the changed administrative TU: new baseline vector operations/data placement and inlining budget; no direct source edit to this body. Ordinary command bodies are separately checked.

67. `src/cmd/t_server.o` — `std::_Vector_base<unsigned long, std::allocator<unsigned long> >::~_Vector_base()` (33 → 0 bytes). Compiler consequence in the changed administrative TU: new baseline vector operations/data placement and inlining budget; no direct source edit to this body. Ordinary command bodies are separately checked.

68. `src/cmd/t_server.o` — `std::_Vector_base<unsigned long, std::allocator<unsigned long> >::~_Vector_base()` (33 → 0 bytes). Compiler consequence in the changed administrative TU: new baseline vector operations/data placement and inlining budget; no direct source edit to this body. Ordinary command bodies are separately checked.

69. `src/cmd/t_server.o` — `std::vector<unsigned long, std::allocator<unsigned long> >::operator=(std::vector<unsigned long, std::allocator<unsigned long> > const&) [clone .isra.0]` (0 → 453 bytes). Compiler consequence in the changed administrative TU: new baseline vector operations/data placement and inlining budget; no direct source edit to this body. Ordinary command bodies are separately checked.

70. `src/cmd/t_server.o` — `std::__cxx11::basic_string<char, std::char_traits<char>, std::allocator<char> > std::operator+<char, std::char_traits<char>, std::allocator<char> >(std::__cxx11::basic_string<char, std::char_traits<char>, std::allocator<char> >&&, std::__cxx11::basic_string<char, std::char_traits<char>, std::allocator<char> >&&)` (1118 → 849 bytes). Compiler consequence in the changed administrative TU: new baseline vector operations/data placement and inlining budget; no direct source edit to this body. Ordinary command bodies are separately checked.

71. `src/cmd/xshard.o` — `tomo::(anonymous namespace)::parse_mpop(tomo::Op&, tomo::(anonymous namespace)::Kind, unsigned int&, bool&, unsigned long&)` (933 → 901 bytes). Compiler consequence in the changed notification/auth TU: added cold classifier and removed suppression change inlining, local code/data placement, or local-clone identity; no direct source edit to this body.

72. `src/cmd/xshard.o` — `tomo::(anonymous namespace)::WorkError tomo::(anonymous namespace)::apply_image<false>(tomo::Shard&, tomo::Slice, unsigned long, tomo::(anonymous namespace)::ObjectImage const&, bool) [clone .isra.0]` (611 → 611 bytes). Compiler consequence in the changed notification/auth TU: added cold classifier and removed suppression change inlining, local code/data placement, or local-clone identity; no direct source edit to this body.

73. `src/cmd/xshard.o` — `tomo::(anonymous namespace)::notify_make_publication(unsigned char, unsigned int, unsigned char, tomo::NotifyEventId, tomo::Slice, std::__cxx11::basic_string<char, std::char_traits<char>, std::allocator<char> >&, std::__cxx11::basic_string<char, std::char_traits<char>, std::allocator<char> >&) [clone .constprop.0] [clone .isra.0]` (1422 → 1330 bytes). Compiler consequence in the changed notification/auth TU: added cold classifier and removed suppression change inlining, local code/data placement, or local-clone identity; no direct source edit to this body.

74. `src/cmd/xshard.o` — `tomo::(anonymous namespace)::notify_make_publication(unsigned char, unsigned int, unsigned char, tomo::NotifyEventId, tomo::Slice, std::__cxx11::basic_string<char, std::char_traits<char>, std::allocator<char> >&, std::__cxx11::basic_string<char, std::char_traits<char>, std::allocator<char> >&) [clone .constprop.0] [clone .isra.0] [clone .cold]` (127 → 118 bytes). Compiler consequence in the changed notification/auth TU: added cold classifier and removed suppression change inlining, local code/data placement, or local-clone identity; no direct source edit to this body.

75. `src/cmd/xshard.o` — `tomo::(anonymous namespace)::execute_atomic_direct_rename(tomo::Task const&, tomo::Shard&, tomo::Op&, unsigned int)` (1466 → 1394 bytes). Compiler consequence in the changed notification/auth TU: added cold classifier and removed suppression change inlining, local code/data placement, or local-clone identity; no direct source edit to this body.

76. `src/cmd/xshard.o` — `tomo::(anonymous namespace)::normalize_multi_blocking_pop(tomo::MultiCommand&)` (3329 → 3361 bytes). Compiler consequence in the changed notification/auth TU: added cold classifier and removed suppression change inlining, local code/data placement, or local-clone identity; no direct source edit to this body.

77. `src/cmd/xshard.o` — `tomo::notify_flat_emit(void*, unsigned int, tomo::NotifyEventId, tomo::Slice)` (426 → 329 bytes). CC11: admit keymiss only for a read lookup in the armed emitter.

78. `src/cmd/xshard.o` — `tomo::multi_execute_task(tomo::Server&, tomo::Task const&, tomo::Shard&, unsigned int, unsigned int, tomo::AofOwnerContext*)` (11880 → 11848 bytes). Compiler consequence in the changed notification/auth TU: added cold classifier and removed suppression change inlining, local code/data placement, or local-clone identity; no direct source edit to this body.

79. `src/cmd/xshard.o` — `tomo::multi_execute_task(tomo::Server&, tomo::Task const&, tomo::Shard&, unsigned int, unsigned int, tomo::AofOwnerContext*) [clone .cold]` (256 → 256 bytes). Compiler consequence in the changed notification/auth TU: added cold classifier and removed suppression change inlining, local code/data placement, or local-clone identity; no direct source edit to this body.

80. `src/cmd/xshard.o` — `tomo::auth_dispatch_entry(tomo::IoLoop&, tomo::Client&, tomo::Op&, unsigned int)` (780 → 764 bytes). CC18: update rejected_calls instead of calls on rejection.

81. `src/cmd/xshard.o` — `tomo::notify_flat_enabled(void*, unsigned int)` (247 → 199 bytes). CC11: remove command-flag suppression after the unchanged disabled-mask prefix.

82. `src/cmd/xshard.o` — `tomo::notify_keymiss_read_lookup(tomo::Op const&, tomo::Slice)` (0 → 611 bytes). CC11: new armed-path source-argument lookup classifier.

83. `src/cmd/xshard.o` — `tomo::IoLoop::pubsub_home_add_pattern(std::__cxx11::basic_string<char, std::char_traits<char>, std::allocator<char> > const&, tomo::IoLoop::PubSubRef const&)` (1702 → 1456 bytes). Compiler consequence in the changed notification/auth TU: added cold classifier and removed suppression change inlining, local code/data placement, or local-clone identity; no direct source edit to this body.

84. `src/cmd/xshard.o` — `tomo::FlatStore::retire_obj(tomo::KvObj*)` (598 → 454 bytes). Compiler consequence in the changed notification/auth TU: added cold classifier and removed suppression change inlining, local code/data placement, or local-clone identity; no direct source edit to this body.

85. `src/cmd/xshard.o` — `tomo::FlatStore::foreign_read_poison_open()` (873 → 769 bytes). Compiler consequence in the changed notification/auth TU: added cold classifier and removed suppression change inlining, local code/data placement, or local-clone identity; no direct source edit to this body.

86. `src/main.o` — `tomo::IoLoop::quiesce_accepts_for_conversion()` (677 → 664 bytes). Compiler consequence of the boot-only allocation change and the +1 inline budget used to retain PRE executor/IO bodies; no direct source edit to this body.

87. `src/main.o` — `tomo::Server::init(tomo::Config const&, tomo::AofReplayPlan const*)` (12072 → 12088 bytes). CC18: boot allocation now reserves three counter planes while preserving the calls-plane offset.

88. `src/main.o` — `std::thread::_State_impl<std::thread::_Invoker<std::tuple<tomokv_multidb_main(int, char**)::{lambda()#2}> > >::_M_run()` (2767 → 2767 bytes). Compiler consequence of the boot-only allocation change and the +1 inline budget used to retain PRE executor/IO bodies; no direct source edit to this body.

89. `src/main.o` — `std::thread::_State_impl<std::thread::_Invoker<std::tuple<tomokv_multidb_main(int, char**)::{lambda()#4}> > >::_M_run()` (2141 → 2141 bytes). Compiler consequence of the boot-only allocation change and the +1 inline budget used to retain PRE executor/IO bodies; no direct source edit to this body.
