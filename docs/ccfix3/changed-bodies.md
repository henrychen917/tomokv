# Every changed body, PRE 9d957b9fb versus ccfix3

82 changed/added/removed occurrences. Two ordinary hot bodies remain unacceptable.

1. `db0/src/cmd/acl.o` — `void tomo_db0::reply_map_header<tomo_db0::Op::Sink&>(tomo_db0::Op::Sink&, unsigned long, bool)` (276 → 381 bytes). CC13/CC18: ACL LOAD prefix and cold rejection attribution; includes compiler changes within the ACL unit.

2. `db0/src/cmd/acl.o` — `tomo_db0::acl_command_entry(tomo_db0::IoLoop&, tomo_db0::Client&, tomo_db0::Op&)` (12668 → 12700 bytes). CC13/CC18: ACL LOAD prefix and cold rejection attribution; includes compiler changes within the ACL unit.

3. `db0/src/cmd/acl.o` — `tomo_db0::acl_command_entry(tomo_db0::IoLoop&, tomo_db0::Client&, tomo_db0::Op&) [clone .cold]` (685 → 685 bytes). CC13/CC18: ACL LOAD prefix and cold rejection attribution; includes compiler changes within the ACL unit.

4. `db0/src/cmd/acl.o` — `tomo_db0::acl_finish_dispatch_denial(tomo_db0::IoLoop&, tomo_db0::Client&, tomo_db0::Op&, unsigned int, tomo_db0::AclDeniedReason, unsigned int)` (604 → 600 bytes). CC13/CC18: ACL LOAD prefix and cold rejection attribution; includes compiler changes within the ACL unit.

5. `db0/src/cmd/acl.o` — `tomo_db0::IoLoop::pubsub_finish_pending(unsigned long)` (3398 → 3398 bytes). CC13/CC18: ACL LOAD prefix and cold rejection attribution; includes compiler changes within the ACL unit.

6. `db0/src/cmd/acl.o` — `void std::__introsort_loop<__gnu_cxx::__normal_iterator<tomo_db0::(anonymous namespace)::AclLogEntry*, std::vector<tomo_db0::(anonymous namespace)::AclLogEntry, std::allocator<tomo_db0::(anonymous namespace)::AclLogEntry> > >, long, __gnu_cxx::__ops::_Iter_comp_iter<tomo_db0::(anonymous namespace)::acl_reply_log(tomo_db0::Op&)::{lambda(tomo_db0::(anonymous namespace)::AclLogEntry const&, tomo_db0::(anonymous namespace)::AclLogEntry const&)#1}> >(__gnu_cxx::__normal_iterator<tomo_db0::(anonymous namespace)::AclLogEntry*, std::vector<tomo_db0::(anonymous namespace)::AclLogEntry, std::allocator<tomo_db0::(anonymous namespace)::AclLogEntry> > >, __gnu_cxx::__normal_iterator<tomo_db0::(anonymous namespace)::AclLogEntry*, std::vector<tomo_db0::(anonymous namespace)::AclLogEntry, std::allocator<tomo_db0::(anonymous namespace)::AclLogEntry> > >, long, __gnu_cxx::__ops::_Iter_comp_iter<tomo_db0::(anonymous namespace)::acl_reply_log(tomo_db0::Op&)::{lambda(tomo_db0::(anonymous namespace)::AclLogEntry const&, tomo_db0::(anonymous namespace)::AclLogEntry const&)#1}>)` (2178 → 2143 bytes). CC13/CC18: ACL LOAD prefix and cold rejection attribution; includes compiler changes within the ACL unit.

7. `db0/src/cmd/acl.o` — `std::enable_if<std::__and_<std::__not_<std::__is_tuple_like<tomo_db0::(anonymous namespace)::AclLogEntry> >, std::is_move_constructible<tomo_db0::(anonymous namespace)::AclLogEntry>, std::is_move_assignable<tomo_db0::(anonymous namespace)::AclLogEntry> >::value, void>::type std::swap<tomo_db0::(anonymous namespace)::AclLogEntry>(tomo_db0::(anonymous namespace)::AclLogEntry&, tomo_db0::(anonymous namespace)::AclLogEntry&)` (1011 → 851 bytes). CC13/CC18: ACL LOAD prefix and cold rejection attribution; includes compiler changes within the ACL unit.

8. `db0/src/cmd/t_server.o` — `tomo_db0::(anonymous namespace)::StatBaseline::~StatBaseline()` (49 → 98 bytes). CC18: round-1 counter storage/reset, calls and rejected_calls emission, no failed_calls field.

9. `db0/src/cmd/t_server.o` — `tomo_db0::(anonymous namespace)::StatBaseline::~StatBaseline()` (49 → 98 bytes). CC18: round-1 counter storage/reset, calls and rejected_calls emission, no failed_calls field.

10. `db0/src/cmd/t_server.o` — `tomo_db0::(anonymous namespace)::cmd_info(tomo_db0::Shard&, tomo_db0::Op&)` (16177 → 16015 bytes). CC18: round-1 counter storage/reset, calls and rejected_calls emission, no failed_calls field.

11. `db0/src/cmd/t_server.o` — `tomo_db0::(anonymous namespace)::cmd_info(tomo_db0::Shard&, tomo_db0::Op&) [clone .cold]` (349 → 344 bytes). CC18: round-1 counter storage/reset, calls and rejected_calls emission, no failed_calls field.

12. `db0/src/cmd/t_server.o` — `void tomo_db0::reply_map_header<tomo_db0::Op::Sink&>(tomo_db0::Op::Sink&, unsigned long, bool)` (381 → 593 bytes). Compiler inlining/outline change in the modified administrative unit; complete symbol and size disclosed, no ordinary handler exception granted.

13. `db0/src/cmd/t_server.o` — `tomo_db0::serialize_notify_flags[abi:cxx11](unsigned int)` (634 → 586 bytes). CC12: Redis flag order and suppression of n under A.

14. `db0/src/cmd/t_server.o` — `tomo_db0::cfg_parse_save_schedule(char const*, unsigned long, std::vector<tomo_db0::SaveClause, std::allocator<tomo_db0::SaveClause> >&)` (1928 → 2056 bytes). Compiler inlining/outline change in the modified administrative unit; complete symbol and size disclosed, no ordinary handler exception granted.

15. `db0/src/cmd/t_server.o` — `tomo_db0::command_config_resetstat()` (2029 → 2199 bytes). CC18: round-1 counter storage/reset, calls and rejected_calls emission, no failed_calls field.

16. `db0/src/cmd/t_server.o` — `tomo_db0::command_config_resetstat() [clone .cold]` (64 → 61 bytes). CC18: round-1 counter storage/reset, calls and rejected_calls emission, no failed_calls field.

17. `db0/src/cmd/t_server.o` — `std::_Vector_base<unsigned long, std::allocator<unsigned long> >::~_Vector_base()` (33 → 0 bytes). Compiler inlining/outline change in the modified administrative unit; complete symbol and size disclosed, no ordinary handler exception granted.

18. `db0/src/cmd/t_server.o` — `std::_Vector_base<unsigned long, std::allocator<unsigned long> >::~_Vector_base()` (33 → 0 bytes). Compiler inlining/outline change in the modified administrative unit; complete symbol and size disclosed, no ordinary handler exception granted.

19. `db0/src/cmd/t_server.o` — `std::vector<unsigned long, std::allocator<unsigned long> >::operator=(std::vector<unsigned long, std::allocator<unsigned long> > const&) [clone .isra.0]` (0 → 453 bytes). Compiler inlining/outline change in the modified administrative unit; complete symbol and size disclosed, no ordinary handler exception granted.

20. `db0/src/cmd/xshard.o` — `tomo_db0::kvobj_free(tomo_db0::KvObj*) [clone .part.0]` (351 → 383 bytes). Compiler outline/target-identity change in the notify implementation unit; selected hot bodies and ordinary handlers remain checked.

21. `db0/src/cmd/xshard.o` — `tomo_db0::(anonymous namespace)::classify_keys(tomo_db0::Op const&, tomo_db0::(anonymous namespace)::Kind, tomo_db0::(anonymous namespace)::XshardKeyHints const&, tomo_db0::(anonymous namespace)::XshardKeyPlan&)` (945 → 993 bytes). Compiler outline/target-identity change in the notify implementation unit; selected hot bodies and ordinary handlers remain checked.

22. `db0/src/cmd/xshard.o` — `tomo_db0::(anonymous namespace)::prepare_commands(tomo_db0::Server&, tomo_db0::MultiExecState&, std::vector<tomo_db0::MultiQueuedCommand, std::allocator<tomo_db0::MultiQueuedCommand> >&)` (11640 → 11640 bytes). Compiler outline/target-identity change in the notify implementation unit; selected hot bodies and ordinary handlers remain checked.

23. `db0/src/cmd/xshard.o` — `tomo_db0::(anonymous namespace)::parse_zrangestore_range(tomo_db0::Op&, tomo_db0::(anonymous namespace)::ImageRangeOptions const&, tomo_db0::(anonymous namespace)::ImageRangeSpec&) [clone .isra.0]` (1297 → 1230 bytes). Compiler outline/target-identity change in the notify implementation unit; selected hot bodies and ordinary handlers remain checked.

24. `db0/src/cmd/xshard.o` — `tomo_db0::(anonymous namespace)::parse_zrangestore_range(tomo_db0::Op&, tomo_db0::(anonymous namespace)::ImageRangeOptions const&, tomo_db0::(anonymous namespace)::ImageRangeSpec&) [clone .isra.0] [clone .cold]` (90 → 86 bytes). Compiler outline/target-identity change in the notify implementation unit; selected hot bodies and ordinary handlers remain checked.

25. `db0/src/cmd/xshard.o` — `tomo_db0::(anonymous namespace)::execute_atomic_direct_rename(tomo_db0::Task const&, tomo_db0::Shard&, tomo_db0::Op&, unsigned int)` (1404 → 1304 bytes). Compiler outline/target-identity change in the notify implementation unit; selected hot bodies and ordinary handlers remain checked.

26. `db0/src/cmd/xshard.o` — `tomo_db0::notify_flat_emit(void*, unsigned int, tomo_db0::NotifyEventId, tomo_db0::Slice)` (426 → 329 bytes). CC11: move source-read classification into the armed sink, preserving the disabled prefix.

27. `db0/src/cmd/xshard.o` — `tomo_db0::auth_dispatch_entry(tomo_db0::IoLoop&, tomo_db0::Client&, tomo_db0::Op&, unsigned int)` (780 → 764 bytes). Compiler outline/target-identity change in the notify implementation unit; selected hot bodies and ordinary handlers remain checked.

28. `db0/src/cmd/xshard.o` — `tomo_db0::notify_flat_enabled(void*, unsigned int)` (247 → 199 bytes). CC11: move source-read classification into the armed sink, preserving the disabled prefix.

29. `db0/src/cmd/xshard.o` — `tomo_db0::notify_keymiss_read_lookup(tomo_db0::Op const&, tomo_db0::Slice)` (0 → 652 bytes). CC11: move source-read classification into the armed sink, preserving the disabled prefix.

30. `db0/src/cmd/xshard.o` — `tomo_db0::FlatStore::atomic_collapse(unsigned long, unsigned long)` (6055 → 6023 bytes). Compiler outline/target-identity change in the notify implementation unit; selected hot bodies and ordinary handlers remain checked.

31. `db0/src/cmd/xshard.o` — `tomo_db0::FlatStore::atomic_collapse_read_local(unsigned long, unsigned long)` (6828 → 6780 bytes). Compiler outline/target-identity change in the notify implementation unit; selected hot bodies and ordinary handlers remain checked.

32. `db0/src/cmd/xshard.o` — `void std::__introsort_loop<__gnu_cxx::__normal_iterator<std::__cxx11::basic_string<char, std::char_traits<char>, std::allocator<char> >*, std::vector<std::__cxx11::basic_string<char, std::char_traits<char>, std::allocator<char> >, std::allocator<std::__cxx11::basic_string<char, std::char_traits<char>, std::allocator<char> > > > >, long, __gnu_cxx::__ops::_Iter_less_iter>(__gnu_cxx::__normal_iterator<std::__cxx11::basic_string<char, std::char_traits<char>, std::allocator<char> >*, std::vector<std::__cxx11::basic_string<char, std::char_traits<char>, std::allocator<char> >, std::allocator<std::__cxx11::basic_string<char, std::char_traits<char>, std::allocator<char> > > > >, __gnu_cxx::__normal_iterator<std::__cxx11::basic_string<char, std::char_traits<char>, std::allocator<char> >*, std::vector<std::__cxx11::basic_string<char, std::char_traits<char>, std::allocator<char> >, std::allocator<std::__cxx11::basic_string<char, std::char_traits<char>, std::allocator<char> > > > >, long, __gnu_cxx::__ops::_Iter_less_iter) [clone .isra.0]` (5840 → 5851 bytes). Compiler outline/target-identity change in the notify implementation unit; selected hot bodies and ordinary handlers remain checked.

33. `db0/src/main.o` — `tomo_db0::IoLoop::quiesce_accepts_for_conversion()` (664 → 677 bytes). Compiler inlining change in the modified boot/administrative unit; full body remains disclosed.

34. `db0/src/main.o` — `tomo_db0::Server::init(tomo_db0::Config const&, tomo_db0::AofReplayPlan const*)` (11945 → 11993 bytes). CC18: boot-only allocation of the retained three counter planes.

35. `db0/src/main.o` — `tomo_db0::WbEngine::serve_impl<false, true, false, true, false, false>(tomo_db0::Client&, bool*)::{lambda(tomo_db0::Op&)#1}::operator()(tomo_db0::Op&) const` (537 → 824 bytes). UNACCEPTED: ordinary writeback lambda inlining swaps between two specializations; no source change to this body.

36. `db0/src/main.o` — `tomo_db0::WbEngine::serve_impl<false, true, true, true, false, false>(tomo_db0::Client&, bool*)::{lambda(tomo_db0::Op&)#1}::operator()(tomo_db0::Op&) const` (824 → 537 bytes). UNACCEPTED: ordinary writeback lambda inlining swaps between two specializations; no source change to this body.

37. `src/cmd/acl.o` — `tomo::(anonymous namespace)::acl_reply_denied(tomo::Client&, tomo::Op&, unsigned int, tomo::AclDeniedReason, unsigned int, tomo::ThreadCtx&, tomo::AclLogContext) [clone .constprop.0]` (1429 → 1389 bytes). CC13/CC18: ACL LOAD prefix and cold rejection attribution; includes compiler changes within the ACL unit.

38. `src/cmd/acl.o` — `tomo::acl_initialize(tomo::Server&, tomo::Config const&, std::__cxx11::basic_string<char, std::char_traits<char>, std::allocator<char> >&)` (2632 → 2616 bytes). CC13/CC18: ACL LOAD prefix and cold rejection attribution; includes compiler changes within the ACL unit.

39. `src/cmd/acl.o` — `void tomo::reply_map_header<tomo::Op::Sink&>(tomo::Op::Sink&, unsigned long, bool)` (276 → 381 bytes). CC13/CC18: ACL LOAD prefix and cold rejection attribution; includes compiler changes within the ACL unit.

40. `src/cmd/acl.o` — `tomo::acl_command_entry(tomo::IoLoop&, tomo::Client&, tomo::Op&)` (12684 → 12700 bytes). CC13/CC18: ACL LOAD prefix and cold rejection attribution; includes compiler changes within the ACL unit.

41. `src/cmd/acl.o` — `tomo::acl_finish_dispatch_denial(tomo::IoLoop&, tomo::Client&, tomo::Op&, unsigned int, tomo::AclDeniedReason, unsigned int)` (604 → 600 bytes). CC13/CC18: ACL LOAD prefix and cold rejection attribution; includes compiler changes within the ACL unit.

42. `src/cmd/acl.o` — `void std::__adjust_heap<__gnu_cxx::__normal_iterator<tomo::(anonymous namespace)::AclLogEntry*, std::vector<tomo::(anonymous namespace)::AclLogEntry, std::allocator<tomo::(anonymous namespace)::AclLogEntry> > >, long, tomo::(anonymous namespace)::AclLogEntry, __gnu_cxx::__ops::_Iter_comp_iter<tomo::(anonymous namespace)::acl_reply_log(tomo::Op&)::{lambda(tomo::(anonymous namespace)::AclLogEntry const&, tomo::(anonymous namespace)::AclLogEntry const&)#1}> >(__gnu_cxx::__normal_iterator<tomo::(anonymous namespace)::AclLogEntry*, std::vector<tomo::(anonymous namespace)::AclLogEntry, std::allocator<tomo::(anonymous namespace)::AclLogEntry> > >, long, long, tomo::(anonymous namespace)::AclLogEntry, __gnu_cxx::__ops::_Iter_comp_iter<tomo::(anonymous namespace)::acl_reply_log(tomo::Op&)::{lambda(tomo::(anonymous namespace)::AclLogEntry const&, tomo::(anonymous namespace)::AclLogEntry const&)#1}>) [clone .isra.0]` (2815 → 2816 bytes). CC13/CC18: ACL LOAD prefix and cold rejection attribution; includes compiler changes within the ACL unit.

43. `src/cmd/acl.o` — `std::enable_if<std::__and_<std::__not_<std::__is_tuple_like<tomo::(anonymous namespace)::AclLogEntry> >, std::is_move_constructible<tomo::(anonymous namespace)::AclLogEntry>, std::is_move_assignable<tomo::(anonymous namespace)::AclLogEntry> >::value, void>::type std::swap<tomo::(anonymous namespace)::AclLogEntry>(tomo::(anonymous namespace)::AclLogEntry&, tomo::(anonymous namespace)::AclLogEntry&)` (851 → 851 bytes). CC13/CC18: ACL LOAD prefix and cold rejection attribution; includes compiler changes within the ACL unit.

44. `src/cmd/t_server.o` — `tomo::(anonymous namespace)::cmd_config(tomo::Shard&, tomo::Op&)` (7671 → 7629 bytes). Compiler inlining/outline change in the modified administrative unit; complete symbol and size disclosed, no ordinary handler exception granted.

45. `src/cmd/t_server.o` — `tomo::(anonymous namespace)::StatBaseline::~StatBaseline()` (49 → 98 bytes). CC18: round-1 counter storage/reset, calls and rejected_calls emission, no failed_calls field.

46. `src/cmd/t_server.o` — `tomo::(anonymous namespace)::StatBaseline::~StatBaseline()` (49 → 98 bytes). CC18: round-1 counter storage/reset, calls and rejected_calls emission, no failed_calls field.

47. `src/cmd/t_server.o` — `tomo::(anonymous namespace)::collect_config_updates(tomo::Op&, std::vector<std::pair<tomo::(anonymous namespace)::ConfigValue*, std::__cxx11::basic_string<char, std::char_traits<char>, std::allocator<char> > >, std::allocator<std::pair<tomo::(anonymous namespace)::ConfigValue*, std::__cxx11::basic_string<char, std::char_traits<char>, std::allocator<char> > > > >&)` (8600 → 8585 bytes). Compiler inlining/outline change in the modified administrative unit; complete symbol and size disclosed, no ordinary handler exception granted.

48. `src/cmd/t_server.o` — `tomo::(anonymous namespace)::collect_config_updates(tomo::Op&, std::vector<std::pair<tomo::(anonymous namespace)::ConfigValue*, std::__cxx11::basic_string<char, std::char_traits<char>, std::allocator<char> > >, std::allocator<std::pair<tomo::(anonymous namespace)::ConfigValue*, std::__cxx11::basic_string<char, std::char_traits<char>, std::allocator<char> > > > >&) [clone .cold]` (147 → 147 bytes). Compiler inlining/outline change in the modified administrative unit; complete symbol and size disclosed, no ordinary handler exception granted.

49. `src/cmd/t_server.o` — `tomo::(anonymous namespace)::cmd_info(tomo::Shard&, tomo::Op&)` (16215 → 16047 bytes). CC18: round-1 counter storage/reset, calls and rejected_calls emission, no failed_calls field.

50. `src/cmd/t_server.o` — `tomo::(anonymous namespace)::cmd_info(tomo::Shard&, tomo::Op&) [clone .cold]` (353 → 347 bytes). CC18: round-1 counter storage/reset, calls and rejected_calls emission, no failed_calls field.

51. `src/cmd/t_server.o` — `tomo::serialize_notify_flags[abi:cxx11](unsigned int)` (634 → 586 bytes). CC12: Redis flag order and suppression of n under A.

52. `src/cmd/t_server.o` — `tomo::cfg_parse_save_schedule(char const*, unsigned long, std::vector<tomo::SaveClause, std::allocator<tomo::SaveClause> >&)` (1928 → 2056 bytes). Compiler inlining/outline change in the modified administrative unit; complete symbol and size disclosed, no ordinary handler exception granted.

53. `src/cmd/t_server.o` — `tomo::command_config_resetstat()` (2029 → 2199 bytes). CC18: round-1 counter storage/reset, calls and rejected_calls emission, no failed_calls field.

54. `src/cmd/t_server.o` — `tomo::command_config_resetstat() [clone .cold]` (64 → 61 bytes). CC18: round-1 counter storage/reset, calls and rejected_calls emission, no failed_calls field.

55. `src/cmd/t_server.o` — `tomo::cfg_client_output_buffer_limit_string[abi:cxx11](tomo::ClientOutputBufferLimits const&)` (5305 → 5072 bytes). Compiler inlining/outline change in the modified administrative unit; complete symbol and size disclosed, no ordinary handler exception granted.

56. `src/cmd/t_server.o` — `void tomo::reply_int<tomo::Op::Sink>(tomo::Op::Sink&&, long long)` (673 → 462 bytes). Compiler inlining/outline change in the modified administrative unit; complete symbol and size disclosed, no ordinary handler exception granted.

57. `src/cmd/t_server.o` — `tomo::Server::flipctl_debug_dump[abi:cxx11]() const` (2430 → 2288 bytes). Compiler inlining/outline change in the modified administrative unit; complete symbol and size disclosed, no ordinary handler exception granted.

58. `src/cmd/t_server.o` — `std::_Vector_base<unsigned long, std::allocator<unsigned long> >::~_Vector_base()` (33 → 0 bytes). Compiler inlining/outline change in the modified administrative unit; complete symbol and size disclosed, no ordinary handler exception granted.

59. `src/cmd/t_server.o` — `std::_Vector_base<unsigned long, std::allocator<unsigned long> >::~_Vector_base()` (33 → 0 bytes). Compiler inlining/outline change in the modified administrative unit; complete symbol and size disclosed, no ordinary handler exception granted.

60. `src/cmd/t_server.o` — `std::vector<unsigned long, std::allocator<unsigned long> >::operator=(std::vector<unsigned long, std::allocator<unsigned long> > const&) [clone .isra.0]` (0 → 453 bytes). Compiler inlining/outline change in the modified administrative unit; complete symbol and size disclosed, no ordinary handler exception granted.

61. `src/cmd/t_server.o` — `std::__cxx11::basic_string<char, std::char_traits<char>, std::allocator<char> > std::operator+<char, std::char_traits<char>, std::allocator<char> >(std::__cxx11::basic_string<char, std::char_traits<char>, std::allocator<char> >&&, std::__cxx11::basic_string<char, std::char_traits<char>, std::allocator<char> >&&)` (1118 → 849 bytes). Compiler inlining/outline change in the modified administrative unit; complete symbol and size disclosed, no ordinary handler exception granted.

62. `src/cmd/xshard.o` — `tomo::(anonymous namespace)::WorkError tomo::(anonymous namespace)::apply_image<false>(tomo::Shard&, tomo::Slice, unsigned long, tomo::(anonymous namespace)::ObjectImage const&, bool) [clone .isra.0]` (611 → 611 bytes). Compiler outline/target-identity change in the notify implementation unit; selected hot bodies and ordinary handlers remain checked.

63. `src/cmd/xshard.o` — `tomo::(anonymous namespace)::BlockingRegistry::add(tomo::Shard&, tomo::BlockingState&, unsigned int)` (2542 → 2509 bytes). Compiler outline/target-identity change in the notify implementation unit; selected hot bodies and ordinary handlers remain checked.

64. `src/cmd/xshard.o` — `tomo::(anonymous namespace)::BlockingRegistry::add(tomo::Shard&, tomo::BlockingState&, unsigned int) [clone .cold]` (807 → 803 bytes). Compiler outline/target-identity change in the notify implementation unit; selected hot bodies and ordinary handlers remain checked.

65. `src/cmd/xshard.o` — `tomo::(anonymous namespace)::notify_make_publication(unsigned char, unsigned int, unsigned char, tomo::NotifyEventId, tomo::Slice, std::__cxx11::basic_string<char, std::char_traits<char>, std::allocator<char> >&, std::__cxx11::basic_string<char, std::char_traits<char>, std::allocator<char> >&) [clone .constprop.0] [clone .isra.0]` (1374 → 1314 bytes). Compiler outline/target-identity change in the notify implementation unit; selected hot bodies and ordinary handlers remain checked.

66. `src/cmd/xshard.o` — `tomo::(anonymous namespace)::notify_make_publication(unsigned char, unsigned int, unsigned char, tomo::NotifyEventId, tomo::Slice, std::__cxx11::basic_string<char, std::char_traits<char>, std::allocator<char> >&, std::__cxx11::basic_string<char, std::char_traits<char>, std::allocator<char> >&) [clone .constprop.0] [clone .isra.0] [clone .cold]` (129 → 118 bytes). Compiler outline/target-identity change in the notify implementation unit; selected hot bodies and ordinary handlers remain checked.

67. `src/cmd/xshard.o` — `tomo::(anonymous namespace)::normalize_multi_blocking_pop(tomo::MultiCommand&)` (3326 → 3308 bytes). Compiler outline/target-identity change in the notify implementation unit; selected hot bodies and ordinary handlers remain checked.

68. `src/cmd/xshard.o` — `tomo::notify_flat_emit(void*, unsigned int, tomo::NotifyEventId, tomo::Slice)` (426 → 329 bytes). CC11: move source-read classification into the armed sink, preserving the disabled prefix.

69. `src/cmd/xshard.o` — `tomo::auth_dispatch_entry(tomo::IoLoop&, tomo::Client&, tomo::Op&, unsigned int)` (780 → 764 bytes). Compiler outline/target-identity change in the notify implementation unit; selected hot bodies and ordinary handlers remain checked.

70. `src/cmd/xshard.o` — `tomo::notify_flat_enabled(void*, unsigned int)` (247 → 199 bytes). CC11: move source-read classification into the armed sink, preserving the disabled prefix.

71. `src/cmd/xshard.o` — `tomo::xshard_plain_prepare(tomo::Server&, tomo::Shard&, tomo::Op&, unsigned long, tomo::PlainForeignReadScope&)` (7358 → 7290 bytes). Compiler outline/target-identity change in the notify implementation unit; selected hot bodies and ordinary handlers remain checked.

72. `src/cmd/xshard.o` — `tomo::xshard_plain_prepare(tomo::Server&, tomo::Shard&, tomo::Op&, unsigned long, tomo::PlainForeignReadScope&) [clone .cold]` (246 → 242 bytes). Compiler outline/target-identity change in the notify implementation unit; selected hot bodies and ordinary handlers remain checked.

73. `src/cmd/xshard.o` — `tomo::notify_keymiss_read_lookup(tomo::Op const&, tomo::Slice)` (0 → 611 bytes). CC11: move source-read classification into the armed sink, preserving the disabled prefix.

74. `src/cmd/xshard.o` — `tomo::IoLoop::pubsub_home_add_pattern(std::__cxx11::basic_string<char, std::char_traits<char>, std::allocator<char> > const&, tomo::IoLoop::PubSubRef const&)` (1702 → 1456 bytes). Compiler outline/target-identity change in the notify implementation unit; selected hot bodies and ordinary handlers remain checked.

75. `src/cmd/xshard.o` — `tomo::FlatStore::start_rehash(unsigned int)` (982 → 812 bytes). Compiler outline/target-identity change in the notify implementation unit; selected hot bodies and ordinary handlers remain checked.

76. `src/cmd/xshard.o` — `tomo::FlatStore::read_local_table_mutation_begin() [clone .isra.0]` (0 → 84 bytes). Compiler outline/target-identity change in the notify implementation unit; selected hot bodies and ordinary handlers remain checked.

77. `src/cmd/xshard.o` — `tomo::FlatStore::read_local_table_mutation_begin() [clone .isra.0] [clone .cold]` (0 → 6 bytes). Compiler outline/target-identity change in the notify implementation unit; selected hot bodies and ordinary handlers remain checked.

78. `src/cmd/xshard.o` — `std::vector<std::__cxx11::basic_string<char, std::char_traits<char>, std::allocator<char> >, std::allocator<std::__cxx11::basic_string<char, std::char_traits<char>, std::allocator<char> > > >::insert(__gnu_cxx::__normal_iterator<std::__cxx11::basic_string<char, std::char_traits<char>, std::allocator<char> > const*, std::vector<std::__cxx11::basic_string<char, std::char_traits<char>, std::allocator<char> >, std::allocator<std::__cxx11::basic_string<char, std::char_traits<char>, std::allocator<char> > > > >, std::__cxx11::basic_string<char, std::char_traits<char>, std::allocator<char> > const&)` (1552 → 1091 bytes). Compiler outline/target-identity change in the notify implementation unit; selected hot bodies and ordinary handlers remain checked.

79. `src/cmd/xshard.o` — `tomo::(anonymous namespace)::prepare_sort_deref(tomo::ScatterState&, tomo::Op&)::{lambda(tomo::SortPattern const&, tomo::Slice, bool, unsigned long)#1}::operator()(tomo::SortPattern const&, tomo::Slice, bool, unsigned long) const [clone .constprop.0]` (3635 → 3686 bytes). Compiler outline/target-identity change in the notify implementation unit; selected hot bodies and ordinary handlers remain checked.

80. `src/cmd/xshard.o` — `tomo::(anonymous namespace)::prepare_sort_deref(tomo::ScatterState&, tomo::Op&)::{lambda(tomo::SortPattern const&, tomo::Slice, bool, unsigned long)#1}::operator()(tomo::SortPattern const&, tomo::Slice, bool, unsigned long) const [clone .constprop.0] [clone .cold]` (162 → 162 bytes). Compiler outline/target-identity change in the notify implementation unit; selected hot bodies and ordinary handlers remain checked.

81. `src/main.o` — `tomo::IoLoop::pubsub_start_publish(tomo::Client*, tomo::Op&, bool)` (1744 → 1749 bytes). Compiler inlining change in the modified boot/administrative unit; full body remains disclosed.

82. `src/main.o` — `tomo::Server::init(tomo::Config const&, tomo::AofReplayPlan const*)` (12072 → 12088 bytes). CC18: boot-only allocation of the retained three counter planes.
