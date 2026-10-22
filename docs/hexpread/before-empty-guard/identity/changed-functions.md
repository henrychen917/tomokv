# Changed emitted functions

Exact opcodes plus relocation targets; no error-callee or instruction masking.

| Object | Function | Bytes PRE → POST | Scope |
|---|---|---|---|
| `db0/src/cmd/server_tail.o` | `tomo_db0::ExpireIndex::erase(unsigned long) [clone .isra.0]` | 369 → 369 | OUTSIDE requested scope |
| `db0/src/cmd/server_tail.o` | `tomo_db0::ExpireIndex::erase(unsigned long) [clone .isra.0] [clone .cold]` | 5 → 0 | OUTSIDE requested scope |
| `db0/src/cmd/server_tail.o` | `tomo_db0::(anonymous namespace)::cmd_object(tomo_db0::Shard&, tomo_db0::Op&)` | 1216 → 1104 | read / added helper |
| `db0/src/cmd/server_tail.o` | `tomo_db0::(anonymous namespace)::reply_help(tomo_db0::Op&, char const* const*, unsigned long)` | 837 → 993 | OUTSIDE requested scope |
| `db0/src/cmd/server_tail.o` | `tomo_db0::(anonymous namespace)::cmd_failover(tomo_db0::Shard&, tomo_db0::Op&)` | 274 → 450 | OUTSIDE requested scope |
| `db0/src/cmd/server_tail.o` | `tomo_db0::(anonymous namespace)::cmd_shutdown(tomo_db0::Shard&, tomo_db0::Op&)` | 1148 → 1319 | OUTSIDE requested scope |
| `db0/src/cmd/server_tail.o` | `tomo_db0::(anonymous namespace)::cmd_shutdown(tomo_db0::Shard&, tomo_db0::Op&) [clone .cold]` | 48 → 48 | OUTSIDE requested scope |
| `db0/src/cmd/server_tail.o` | `tomo_db0::(anonymous namespace)::cmd_object_notify(tomo_db0::Shard&, tomo_db0::Op&)` | 1216 → 1120 | read / added helper |
| `db0/src/cmd/server_tail.o` | `tomo_db0::kvobj_external_bytes(tomo_db0::KvObj const*)` | 1287 → 1482 | OUTSIDE requested scope |
| `db0/src/cmd/server_tail.o` | `tomo_db0::server_tail_config_subcommand(tomo_db0::Op&)` | 12324 → 12653 | OUTSIDE requested scope |
| `db0/src/cmd/server_tail.o` | `tomo_db0::server_tail_config_subcommand(tomo_db0::Op&) [clone .cold]` | 525 → 528 | OUTSIDE requested scope |
| `db0/src/cmd/server_tail.o` | `tomo_db0::FlatStore::find_notify(unsigned long, tomo_db0::Slice, tomo_db0::FlatNotifySink*)` | 1784 → 999 | OUTSIDE requested scope |
| `db0/src/cmd/server_tail.o` | `tomo_db0::FlatStore::live_or_expire(int, unsigned long, tomo_db0::Slice, tomo_db0::KvObj*)` | 300 → 0 | OUTSIDE requested scope |
| `db0/src/cmd/server_tail.o` | `tomo_db0::FlatStore::atomic_resolve_internal(unsigned long, tomo_db0::Slice, unsigned long, bool)` | 2399 → 2379 | OUTSIDE requested scope |
| `db0/src/cmd/server_tail.o` | `tomo_db0::FlatStore::find(unsigned long, tomo_db0::Slice)` | 1017 → 1118 | OUTSIDE requested scope |
| `db0/src/cmd/server_tail.o` | `tomo_db0::FlatStore::erase_in(int, unsigned long, tomo_db0::Slice, bool*) [clone .isra.0]` | 1887 → 1887 | OUTSIDE requested scope |
| `db0/src/cmd/server_tail.o` | `void tomo_db0::reply_int<tomo_db0::Op::Sink>(tomo_db0::Op::Sink&&, long long)` | 462 → 673 | OUTSIDE requested scope |
| `db0/src/cmd/server_tail.o` | `void tomo_db0::reply_int<tomo_db0::Op::Sink&>(tomo_db0::Op::Sink&, long long)` | 462 → 673 | OUTSIDE requested scope |
| `db0/src/cmd/t_hash.o` | `tomo_db0::HashFieldMap::erase(tomo_db0::Slice)` | 4057 → 3987 | OUTSIDE requested scope |
| `db0/src/cmd/t_hash.o` | `void tomo_db0::(anonymous namespace)::cmd_hexists<false>(tomo_db0::Shard&, tomo_db0::Op&)` | 207 → 260 | read / added helper |
| `db0/src/cmd/t_hash.o` | `void tomo_db0::(anonymous namespace)::cmd_hexists<true>(tomo_db0::Shard&, tomo_db0::Op&)` | 207 → 260 | read / added helper |
| `db0/src/cmd/t_hash.o` | `void tomo_db0::(anonymous namespace)::cmd_hstrlen<false>(tomo_db0::Shard&, tomo_db0::Op&)` | 217 → 265 | read / added helper |
| `db0/src/cmd/t_hash.o` | `void tomo_db0::(anonymous namespace)::cmd_hstrlen<true>(tomo_db0::Shard&, tomo_db0::Op&)` | 217 → 265 | read / added helper |
| `db0/src/cmd/t_hash.o` | `void tomo_db0::(anonymous namespace)::cmd_hrandfield<false>(tomo_db0::Shard&, tomo_db0::Op&)` | 2369 → 2385 | read / added helper |
| `db0/src/cmd/t_hash.o` | `void tomo_db0::(anonymous namespace)::cmd_hrandfield<true>(tomo_db0::Shard&, tomo_db0::Op&)` | 2369 → 2385 | read / added helper |
| `db0/src/cmd/t_hash.o` | `void tomo_db0::(anonymous namespace)::generic_getall<false>(tomo_db0::Shard&, tomo_db0::Op&, tomo_db0::(anonymous namespace)::GetAllMode)` | 1772 → 1846 | read / added helper |
| `db0/src/cmd/t_hash.o` | `void tomo_db0::(anonymous namespace)::generic_getall<true>(tomo_db0::Shard&, tomo_db0::Op&, tomo_db0::(anonymous namespace)::GetAllMode)` | 1772 → 1846 | read / added helper |
| `db0/src/cmd/t_hash.o` | `tomo_db0::(anonymous namespace)::hash_snapshot_read(tomo_db0::SnapshotSaveCursor&, unsigned char*, unsigned long, unsigned long&)` | 1812 → 1911 | OUTSIDE requested scope |
| `db0/src/cmd/t_hash.o` | `tomo_db0::(anonymous namespace)::hash_snapshot_begin(tomo_db0::KvObj const&, tomo_db0::SnapshotSaveCursor&, unsigned char&)` | 21 → 1516 | OUTSIDE requested scope |
| `db0/src/cmd/t_hash.o` | `tomo_db0::(anonymous namespace)::hash_snapshot_begin(tomo_db0::KvObj const&, tomo_db0::SnapshotSaveCursor&, unsigned char&) [clone .part.0]` | 1871 → 0 | OUTSIDE requested scope |
| `db0/src/cmd/t_hash.o` | `void tomo_db0::(anonymous namespace)::cmd_hget<false>(tomo_db0::Shard&, tomo_db0::Op&)` | 495 → 527 | read / added helper |
| `db0/src/cmd/t_hash.o` | `void tomo_db0::(anonymous namespace)::cmd_hget<true>(tomo_db0::Shard&, tomo_db0::Op&)` | 495 → 527 | read / added helper |
| `db0/src/cmd/t_hash.o` | `void tomo_db0::(anonymous namespace)::cmd_hlen<false>(tomo_db0::Shard&, tomo_db0::Op&)` | 170 → 218 | read / added helper |
| `db0/src/cmd/t_hash.o` | `void tomo_db0::(anonymous namespace)::cmd_hlen<true>(tomo_db0::Shard&, tomo_db0::Op&)` | 170 → 218 | read / added helper |
| `db0/src/cmd/t_hash.o` | `void tomo_db0::(anonymous namespace)::cmd_hmget<false>(tomo_db0::Shard&, tomo_db0::Op&)` | 591 → 639 | read / added helper |
| `db0/src/cmd/t_hash.o` | `void tomo_db0::(anonymous namespace)::cmd_hmget<true>(tomo_db0::Shard&, tomo_db0::Op&)` | 591 → 639 | read / added helper |
| `db0/src/cmd/t_hash.o` | `void tomo_db0::(anonymous namespace)::cmd_hscan<false>(tomo_db0::Shard&, tomo_db0::Op&)` | 2439 → 2487 | read / added helper |
| `db0/src/cmd/t_hash.o` | `void tomo_db0::(anonymous namespace)::cmd_hscan<false>(tomo_db0::Shard&, tomo_db0::Op&) [clone .cold]` | 124 → 124 | read / added helper |
| `db0/src/cmd/t_hash.o` | `void tomo_db0::(anonymous namespace)::cmd_hscan<true>(tomo_db0::Shard&, tomo_db0::Op&)` | 2439 → 2487 | read / added helper |
| `db0/src/cmd/t_hash.o` | `void tomo_db0::(anonymous namespace)::cmd_hscan<true>(tomo_db0::Shard&, tomo_db0::Op&) [clone .cold]` | 124 → 124 | read / added helper |
| `db0/src/cmd/t_hash.o` | `tomo_db0::hash_read_visit(tomo_db0::KvObj const*, unsigned long, unsigned long, void*, void (*)(void*, tomo_db0::Slice, tomo_db0::Slice))` | 0 → 974 | read / added helper |
| `db0/src/cmd/t_hash.o` | `tomo_db0::kvobj_external_bytes(tomo_db0::KvObj const*)` | 313 → 380 | OUTSIDE requested scope |
| `db0/src/cmd/t_hash.o` | `tomo_db0::FlatStore::choose_victim(tomo_db0::Slice)` | 2016 → 2016 | OUTSIDE requested scope |
| `db0/src/cmd/t_hash.o` | `void tomo_db0::HashFieldMap::scan_home<tomo_db0::hash_read_visit(tomo_db0::KvObj const*, unsigned long, unsigned long, void*, void (*)(void*, tomo_db0::Slice, tomo_db0::Slice))::{lambda(tomo_db0::HashFieldMap::Node const&)#2}>(int, unsigned int, tomo_db0::hash_read_visit(tomo_db0::KvObj const*, unsigned long, unsigned long, void*, void (*)(void*, tomo_db0::Slice, tomo_db0::Slice))::{lambda(tomo_db0::HashFieldMap::Node const&)#2}&) const` | 0 → 118 | read / added helper |
| `db0/src/cmd/t_hash.o` | `tomo_db0::CollectionRef::end() const` | 0 → 421 | OUTSIDE requested scope |
| `db0/src/cmd/t_hash_ttl.o` | `tomo_db0::hash_ttl_on_access(tomo_db0::Shard&, tomo_db0::Op&, tomo_db0::KvObj*, bool)` | 1226 → 1354 | read / added helper |
| `db0/src/cmd/t_hash_ttl.o` | `tomo_db0::FlatStore::atomic_read_owns_value(unsigned long, tomo_db0::Slice, tomo_db0::KvObj const*) const` | 0 → 1321 | read / added helper |
| `src/cmd/server_tail.o` | `tomo::ExpireIndex::erase(unsigned long) [clone .isra.0]` | 369 → 369 | OUTSIDE requested scope |
| `src/cmd/server_tail.o` | `tomo::ExpireIndex::erase(unsigned long) [clone .isra.0] [clone .cold]` | 5 → 0 | OUTSIDE requested scope |
| `src/cmd/server_tail.o` | `tomo::(anonymous namespace)::cmd_object(tomo::Shard&, tomo::Op&)` | 1216 → 1104 | read / added helper |
| `src/cmd/server_tail.o` | `tomo::(anonymous namespace)::cmd_failover(tomo::Shard&, tomo::Op&)` | 274 → 450 | OUTSIDE requested scope |
| `src/cmd/server_tail.o` | `tomo::(anonymous namespace)::cmd_shutdown(tomo::Shard&, tomo::Op&)` | 1319 → 1319 | OUTSIDE requested scope |
| `src/cmd/server_tail.o` | `tomo::(anonymous namespace)::cmd_object_notify(tomo::Shard&, tomo::Op&)` | 1216 → 1120 | read / added helper |
| `src/cmd/server_tail.o` | `tomo::(anonymous namespace)::reply_map_pair_int(tomo::Op::Sink&, char const*, unsigned long long)` | 478 → 705 | OUTSIDE requested scope |
| `src/cmd/server_tail.o` | `tomo::kvobj_external_bytes(tomo::KvObj const*)` | 1287 → 1482 | OUTSIDE requested scope |
| `src/cmd/server_tail.o` | `tomo::server_tail_config_subcommand(tomo::Op&)` | 12508 → 12717 | OUTSIDE requested scope |
| `src/cmd/server_tail.o` | `tomo::server_tail_config_subcommand(tomo::Op&) [clone .cold]` | 540 → 528 | OUTSIDE requested scope |
| `src/cmd/server_tail.o` | `tomo::FlatStore::find_notify(unsigned long, tomo::Slice, tomo::FlatNotifySink*)` | 1033 → 569 | OUTSIDE requested scope |
| `src/cmd/server_tail.o` | `tomo::FlatStore::live_or_expire(int, unsigned long, tomo::Slice, tomo::KvObj*)` | 300 → 0 | OUTSIDE requested scope |
| `src/cmd/server_tail.o` | `tomo::FlatStore::erase_in_read_local(int, unsigned long, tomo::Slice, bool*) [clone .isra.0]` | 0 → 1042 | OUTSIDE requested scope |
| `src/cmd/server_tail.o` | `tomo::FlatStore::find(unsigned long, tomo::Slice)` | 553 → 1644 | OUTSIDE requested scope |
| `src/cmd/server_tail.o` | `tomo::FlatStore::erase_in(int, unsigned long, tomo::Slice, bool*) [clone .isra.0]` | 1684 → 0 | OUTSIDE requested scope |
| `src/cmd/t_hash.o` | `tomo::HashFieldMap::set(tomo::Slice, tomo::Slice)` | 2205 → 2260 | OUTSIDE requested scope |
| `src/cmd/t_hash.o` | `tomo::HashFieldMap::erase(tomo::Slice)` | 4006 → 4354 | OUTSIDE requested scope |
| `src/cmd/t_hash.o` | `void tomo::(anonymous namespace)::cmd_hexists<false>(tomo::Shard&, tomo::Op&)` | 208 → 260 | read / added helper |
| `src/cmd/t_hash.o` | `void tomo::(anonymous namespace)::cmd_hexists<true>(tomo::Shard&, tomo::Op&)` | 208 → 260 | read / added helper |
| `src/cmd/t_hash.o` | `void tomo::(anonymous namespace)::cmd_hstrlen<false>(tomo::Shard&, tomo::Op&)` | 217 → 265 | read / added helper |
| `src/cmd/t_hash.o` | `void tomo::(anonymous namespace)::cmd_hstrlen<true>(tomo::Shard&, tomo::Op&)` | 217 → 265 | read / added helper |
| `src/cmd/t_hash.o` | `void tomo::(anonymous namespace)::cmd_hrandfield<false>(tomo::Shard&, tomo::Op&)` | 2369 → 2385 | read / added helper |
| `src/cmd/t_hash.o` | `void tomo::(anonymous namespace)::cmd_hrandfield<true>(tomo::Shard&, tomo::Op&)` | 2369 → 2385 | read / added helper |
| `src/cmd/t_hash.o` | `void tomo::(anonymous namespace)::generic_getall<false>(tomo::Shard&, tomo::Op&, tomo::(anonymous namespace)::GetAllMode)` | 1712 → 1786 | read / added helper |
| `src/cmd/t_hash.o` | `void tomo::(anonymous namespace)::generic_getall<true>(tomo::Shard&, tomo::Op&, tomo::(anonymous namespace)::GetAllMode)` | 1712 → 1786 | read / added helper |
| `src/cmd/t_hash.o` | `tomo::(anonymous namespace)::hash_snapshot_read(tomo::SnapshotSaveCursor&, unsigned char*, unsigned long, unsigned long&)` | 1876 → 1783 | OUTSIDE requested scope |
| `src/cmd/t_hash.o` | `tomo::(anonymous namespace)::hash_snapshot_begin(tomo::KvObj const&, tomo::SnapshotSaveCursor&, unsigned char&)` | 21 → 1365 | OUTSIDE requested scope |
| `src/cmd/t_hash.o` | `tomo::(anonymous namespace)::hash_snapshot_begin(tomo::KvObj const&, tomo::SnapshotSaveCursor&, unsigned char&) [clone .part.0]` | 1580 → 0 | OUTSIDE requested scope |
| `src/cmd/t_hash.o` | `void tomo::(anonymous namespace)::cmd_hdel<true>(tomo::Shard&, tomo::Op&)` | 1038 → 1294 | OUTSIDE requested scope |
| `src/cmd/t_hash.o` | `void tomo::(anonymous namespace)::cmd_hget<false>(tomo::Shard&, tomo::Op&)` | 495 → 527 | read / added helper |
| `src/cmd/t_hash.o` | `void tomo::(anonymous namespace)::cmd_hget<true>(tomo::Shard&, tomo::Op&)` | 495 → 527 | read / added helper |
| `src/cmd/t_hash.o` | `void tomo::(anonymous namespace)::cmd_hlen<false>(tomo::Shard&, tomo::Op&)` | 253 → 218 | read / added helper |
| `src/cmd/t_hash.o` | `void tomo::(anonymous namespace)::cmd_hlen<true>(tomo::Shard&, tomo::Op&)` | 253 → 218 | read / added helper |
| `src/cmd/t_hash.o` | `tomo::(anonymous namespace)::hash_get(tomo::CollectionRef const&, tomo::Slice, tomo::Slice&)` | 302 → 557 | read / added helper |
| `src/cmd/t_hash.o` | `void tomo::(anonymous namespace)::cmd_hmget<false>(tomo::Shard&, tomo::Op&)` | 607 → 655 | read / added helper |
| `src/cmd/t_hash.o` | `void tomo::(anonymous namespace)::cmd_hmget<true>(tomo::Shard&, tomo::Op&)` | 607 → 655 | read / added helper |
| `src/cmd/t_hash.o` | `void tomo::(anonymous namespace)::cmd_hscan<false>(tomo::Shard&, tomo::Op&)` | 2455 → 2503 | read / added helper |
| `src/cmd/t_hash.o` | `void tomo::(anonymous namespace)::cmd_hscan<false>(tomo::Shard&, tomo::Op&) [clone .cold]` | 124 → 124 | read / added helper |
| `src/cmd/t_hash.o` | `void tomo::(anonymous namespace)::cmd_hscan<true>(tomo::Shard&, tomo::Op&)` | 2455 → 2503 | read / added helper |
| `src/cmd/t_hash.o` | `void tomo::(anonymous namespace)::cmd_hscan<true>(tomo::Shard&, tomo::Op&) [clone .cold]` | 124 → 124 | read / added helper |
| `src/cmd/t_hash.o` | `tomo::hash_read_visit(tomo::KvObj const*, unsigned long, unsigned long, void*, void (*)(void*, tomo::Slice, tomo::Slice))` | 0 → 974 | read / added helper |
| `src/cmd/t_hash.o` | `tomo::kvobj_external_bytes(tomo::KvObj const*)` | 383 → 380 | OUTSIDE requested scope |
| `src/cmd/t_hash.o` | `void tomo::reply_int<tomo::Op::Sink>(tomo::Op::Sink&&, long long)` | 85 → 462 | OUTSIDE requested scope |
| `src/cmd/t_hash.o` | `void tomo::reply_int<tomo::Op::Sink>(tomo::Op::Sink&&, long long) [clone .part.0]` | 369 → 0 | OUTSIDE requested scope |
| `src/cmd/t_hash.o` | `tomo::HashFieldMap::field_hash(tomo::Slice) const [clone .isra.0]` | 301 → 0 | OUTSIDE requested scope |
| `src/cmd/t_hash.o` | `void tomo::HashFieldMap::scan_home<tomo::hash_read_visit(tomo::KvObj const*, unsigned long, unsigned long, void*, void (*)(void*, tomo::Slice, tomo::Slice))::{lambda(tomo::HashFieldMap::Node const&)#2}>(int, unsigned int, tomo::hash_read_visit(tomo::KvObj const*, unsigned long, unsigned long, void*, void (*)(void*, tomo::Slice, tomo::Slice))::{lambda(tomo::HashFieldMap::Node const&)#2}&) const` | 0 → 118 | read / added helper |
| `src/cmd/t_hash.o` | `tomo::CollectionRef::end() const` | 0 → 445 | OUTSIDE requested scope |
| `src/cmd/t_hash_ttl.o` | `void tomo::(anonymous namespace)::hread_generic<false>(tomo::Shard&, tomo::Op&, tomo::(anonymous namespace)::Read)` | 2172 → 2044 | read / added helper |
| `src/cmd/t_hash_ttl.o` | `void tomo::(anonymous namespace)::hread_generic<false>(tomo::Shard&, tomo::Op&, tomo::(anonymous namespace)::Read) [clone .cold]` | 129 → 129 | read / added helper |
| `src/cmd/t_hash_ttl.o` | `void tomo::(anonymous namespace)::hread_generic<true>(tomo::Shard&, tomo::Op&, tomo::(anonymous namespace)::Read)` | 2637 → 2507 | read / added helper |
| `src/cmd/t_hash_ttl.o` | `void tomo::(anonymous namespace)::hread_generic<true>(tomo::Shard&, tomo::Op&, tomo::(anonymous namespace)::Read) [clone .cold]` | 125 → 125 | read / added helper |
| `src/cmd/t_hash_ttl.o` | `tomo::hash_ttl_on_access(tomo::Shard&, tomo::Op&, tomo::KvObj*, bool)` | 1889 → 1905 | read / added helper |
| `src/cmd/t_hash_ttl.o` | `tomo::FlatStore::find_notify(unsigned long, tomo::Slice, tomo::FlatNotifySink*)` | 1312 → 1177 | OUTSIDE requested scope |
| `src/cmd/t_hash_ttl.o` | `tomo::FlatStore::erase_notify(unsigned long, tomo::Slice, tomo::FlatNotifySink*, tomo::FlatStore::EraseEvent) [clone .isra.0]` | 1544 → 1420 | OUTSIDE requested scope |
| `src/cmd/t_hash_ttl.o` | `tomo::FlatStore::erase_in_read_local(int, unsigned long, tomo::Slice, bool*)` | 1314 → 1207 | OUTSIDE requested scope |
| `src/cmd/t_hash_ttl.o` | `tomo::FlatStore::insert_into_read_local(int, unsigned long, tomo::KvObj*, bool)` | 2469 → 2293 | OUTSIDE requested scope |
| `src/cmd/t_hash_ttl.o` | `tomo::FlatStore::atomic_resolve_internal(unsigned long, tomo::Slice, unsigned long, bool)` | 3336 → 3130 | OUTSIDE requested scope |
| `src/cmd/t_hash_ttl.o` | `tomo::KvObj::key() const` | 0 → 149 | OUTSIDE requested scope |
| `src/cmd/t_hash_ttl.o` | `tomo::Slice::key_eq(tomo::Slice const&) const` | 0 → 235 | OUTSIDE requested scope |
| `src/cmd/t_hash_ttl.o` | `tomo::FlatStore::atomic_read_owns_value(unsigned long, tomo::Slice, tomo::KvObj const*) const` | 0 → 1317 | read / added helper |
| `src/cmd/hexpread.o` | `_GLOBAL__sub_I__ZN4tomo8hexpread9parse_i64ENS_5SliceERl` | 0 → 47 | read / added helper |
| `src/cmd/hexpread.o` | `void tomo::reply_bulk<tomo::Op::Sink>(tomo::Op::Sink&&, tomo::Slice) [clone .isra.0]` | 0 → 477 | read / added helper |
| `src/cmd/hexpread.o` | `void tomo::reply_map_header<tomo::Op::Sink>(tomo::Op::Sink&&, unsigned long, bool)` | 0 → 749 | read / added helper |
| `src/cmd/hexpread.o` | `tomo::hash_parked_reply(tomo::Shard&, tomo::Op&)` | 0 → 788 | read / added helper |
| `src/cmd/hexpread.o` | `void tomo::reply_array_header<tomo::Op::Sink>(tomo::Op::Sink&&, unsigned long)` | 0 → 444 | read / added helper |
| `src/cmd/hexpread.o` | `tomo::atomic_tripwire_samekey(tomo::AtomicTripwireSamekey)` | 0 → 233 | read / added helper |
| `src/cmd/hexpread.o` | `tomo::Op::Sink::append(char const*, unsigned long)` | 0 → 533 | read / added helper |
| `src/cmd/hexpread.o` | `tomo::hexpread::reply_scan(tomo::Op&, unsigned long, std::vector<tomo::hexpread::ScanItem, std::allocator<tomo::hexpread::ScanItem> > const&, bool)` | 0 → 883 | read / added helper |
| `src/cmd/hexpread.o` | `tomo::hexpread::HashReadView::random(unsigned long, unsigned long)` | 0 → 232 | read / added helper |
| `src/cmd/hexpread.o` | `tomo::hexpread::filtered_cmd_hget(tomo::Shard&, tomo::Op&, tomo::KvObj*, tomo::hexpread::HashReadView&)` | 0 → 820 | read / added helper |
| `src/cmd/hexpread.o` | `tomo::hexpread::filtered_cmd_hlen(tomo::Shard&, tomo::Op&, tomo::KvObj*, tomo::hexpread::HashReadView&)` | 0 → 542 | read / added helper |
| `src/cmd/hexpread.o` | `tomo::hexpread::filtered_cmd_hmget(tomo::Shard&, tomo::Op&, tomo::KvObj*, tomo::hexpread::HashReadView&)` | 0 → 1118 | read / added helper |
| `src/cmd/hexpread.o` | `tomo::hexpread::filtered_cmd_hscan(tomo::Shard&, tomo::Op&, tomo::KvObj*, tomo::hexpread::HashReadView&)` | 0 → 416 | read / added helper |
| `src/cmd/hexpread.o` | `tomo::hexpread::filtered_cmd_hscan(tomo::Shard&, tomo::Op&, tomo::KvObj*, tomo::hexpread::HashReadView&) [clone .cold]` | 0 → 106 | read / added helper |
| `src/cmd/hexpread.o` | `tomo::hexpread::hash_ttl_read_view(tomo::Shard&, tomo::Op&, tomo::KvObj*&, tomo::hexpread::HashReadView&)` | 0 → 328 | read / added helper |
| `src/cmd/hexpread.o` | `tomo::hexpread::parse_scan_options(tomo::Op&, tomo::hexpread::ScanOptions&)` | 0 → 1004 | read / added helper |
| `src/cmd/hexpread.o` | `tomo::hexpread::filtered_cmd_hexists(tomo::Shard&, tomo::Op&, tomo::KvObj*, tomo::hexpread::HashReadView&)` | 0 → 479 | read / added helper |
| `src/cmd/hexpread.o` | `tomo::hexpread::filtered_cmd_hstrlen(tomo::Shard&, tomo::Op&, tomo::KvObj*, tomo::hexpread::HashReadView&)` | 0 → 654 | read / added helper |
| `src/cmd/hexpread.o` | `tomo::hexpread::filtered_select_unique(tomo::hexpread::HashReadView&, unsigned int, unsigned int, std::vector<unsigned int, std::allocator<unsigned int> >&)` | 0 → 2318 | read / added helper |
| `src/cmd/hexpread.o` | `tomo::hexpread::filtered_select_unique(tomo::hexpread::HashReadView&, unsigned int, unsigned int, std::vector<unsigned int, std::allocator<unsigned int> >&) [clone .cold]` | 0 → 192 | read / added helper |
| `src/cmd/hexpread.o` | `tomo::hexpread::filtered_cmd_hrandfield(tomo::Shard&, tomo::Op&, tomo::KvObj*, tomo::hexpread::HashReadView&)` | 0 → 3108 | read / added helper |
| `src/cmd/hexpread.o` | `tomo::hexpread::filtered_cmd_hrandfield(tomo::Shard&, tomo::Op&, tomo::KvObj*, tomo::hexpread::HashReadView&) [clone .cold]` | 0 → 139 | read / added helper |
| `src/cmd/hexpread.o` | `tomo::hexpread::filtered_generic_getall(tomo::Shard&, tomo::Op&, tomo::hexpread::GetAllMode, tomo::KvObj*, tomo::hexpread::HashReadView&)` | 0 → 986 | read / added helper |
| `src/cmd/hexpread.o` | `tomo::hexpread::parse_i64(tomo::Slice, long&)` | 0 → 327 | read / added helper |
| `src/cmd/hexpread.o` | `tomo::FlatStore::atomic_resolve_internal(unsigned long, tomo::Slice, unsigned long, bool)` | 0 → 2769 | read / added helper |
| `src/cmd/hexpread.o` | `void tomo::reply_err<tomo::Op::Sink>(tomo::Op::Sink&&, char const*)` | 0 → 973 | read / added helper |
| `src/cmd/hexpread.o` | `tomo::hexpread::HashReadView::field_live(tomo::Slice) const` | 0 → 575 | read / added helper |
| `src/cmd/hexpread.o` | `tomo::FlatStore::atomic_read_owns_value(unsigned long, tomo::Slice, tomo::KvObj const*) const` | 0 → 1317 | read / added helper |
| `src/cmd/hexpread.o` | `tomo::FlatStore::find_in(int, unsigned long, tomo::Slice) const` | 0 → 630 | read / added helper |
| `src/cmd/hexpread.o` | `std::_Hashtable<unsigned int, unsigned int, std::allocator<unsigned int>, std::__detail::_Identity, std::equal_to<unsigned int>, std::hash<unsigned int>, std::__detail::_Mod_range_hashing, std::__detail::_Default_ranged_hash, std::__detail::_Prime_rehash_policy, std::__detail::_Hashtable_traits<false, true, true> >::_M_rehash(unsigned long, unsigned long const&)` | 0 → 339 | read / added helper |
| `src/cmd/hexpread.o` | `std::unique_ptr<tomo::atomic_tripwire_detail::State, std::default_delete<tomo::atomic_tripwire_detail::State> >::~unique_ptr()` | 0 → 183 | read / added helper |
| `src/cmd/hexpread.o` | `std::unique_ptr<tomo::atomic_tripwire_detail::State, std::default_delete<tomo::atomic_tripwire_detail::State> >::~unique_ptr()` | 0 → 183 | read / added helper |
| `src/cmd/hexpread.o` | `std::vector<tomo::hexpread::ScanItem, std::allocator<tomo::hexpread::ScanItem> >::~vector()` | 0 → 33 | read / added helper |
| `src/cmd/hexpread.o` | `std::vector<tomo::hexpread::ScanItem, std::allocator<tomo::hexpread::ScanItem> >::~vector()` | 0 → 33 | read / added helper |
| `src/cmd/hexpread.o` | `std::vector<unsigned int, std::allocator<unsigned int> >::~vector()` | 0 → 33 | read / added helper |
| `src/cmd/hexpread.o` | `std::vector<unsigned int, std::allocator<unsigned int> >::~vector()` | 0 → 33 | read / added helper |
| `src/cmd/hexpread.o` | `tomo::hexpread::filtered_cmd_hscan(tomo::Shard&, tomo::Op&, tomo::KvObj*, tomo::hexpread::HashReadView&)::{lambda(void*, tomo::Slice, tomo::Slice)#1}::_FUN(void*, tomo::Slice, tomo::Slice)` | 0 → 581 | read / added helper |
| `src/cmd/hexpread.o` | `tomo::hexpread::filtered_cmd_hrandfield(tomo::Shard&, tomo::Op&, tomo::KvObj*, tomo::hexpread::HashReadView&)::{lambda(void*, tomo::Slice, tomo::Slice)#1}::_FUN(void*, tomo::Slice, tomo::Slice)` | 0 → 549 | read / added helper |
| `src/cmd/hexpread.o` | `tomo::hexpread::filtered_generic_getall(tomo::Shard&, tomo::Op&, tomo::hexpread::GetAllMode, tomo::KvObj*, tomo::hexpread::HashReadView&)::{lambda(void*, tomo::Slice, tomo::Slice)#1}::_FUN(void*, tomo::Slice, tomo::Slice)` | 0 → 210 | read / added helper |
| `src/cmd/hexpread.o` | `tomo::FlatStore::atomic_resolve_internal(unsigned long, tomo::Slice, unsigned long, bool)::{lambda(tomo::AtomicEntry&, tomo::KvObj*, bool)#1}::operator()(tomo::AtomicEntry&, tomo::KvObj*, bool) const` | 0 → 1067 | read / added helper |
| `src/cmd/objectpread.o` | `_GLOBAL__sub_I__ZN4tomo20object_read_no_touchERNS_5ShardEmNS_5SliceE` | 0 → 47 | read / added helper |
| `src/cmd/objectpread.o` | `tomo::ExpireIndex::collapse_empty()` | 0 → 139 | read / added helper |
| `src/cmd/objectpread.o` | `tomo::ExpireIndex::erase(unsigned long) [clone .isra.0]` | 0 → 369 | read / added helper |
| `src/cmd/objectpread.o` | `tomo::ExpireIndex::erase(unsigned long) [clone .isra.0] [clone .cold]` | 0 → 5 | read / added helper |
| `src/cmd/objectpread.o` | `tomo::kvobj_external_bytes(tomo::KvObj const*)` | 0 → 1606 | read / added helper |
| `src/cmd/objectpread.o` | `tomo::object_read_no_touch(tomo::Shard&, unsigned long, tomo::Slice)` | 0 → 2645 | read / added helper |
| `src/cmd/objectpread.o` | `tomo::object_read_no_touch(tomo::Shard&, unsigned long, tomo::Slice) [clone .cold]` | 0 → 5 | read / added helper |
| `src/cmd/objectpread.o` | `tomo::atomic_tripwire_samekey(tomo::AtomicTripwireSamekey)` | 0 → 233 | read / added helper |
| `src/cmd/objectpread.o` | `tomo::kvobj_free_with_capacity(tomo::KvObj*, unsigned long)` | 0 → 772 | read / added helper |
| `src/cmd/objectpread.o` | `tomo::FlatStore::retire_obj(tomo::KvObj*)` | 0 → 901 | read / added helper |
| `src/cmd/objectpread.o` | `tomo::FlatStore::erase_in_read_local(int, unsigned long, tomo::Slice, bool*) [clone .isra.0]` | 0 → 1298 | read / added helper |
| `src/cmd/objectpread.o` | `tomo::FlatStore::atomic_resolve_internal(unsigned long, tomo::Slice, unsigned long, bool)` | 0 → 2769 | read / added helper |
| `src/cmd/objectpread.o` | `tomo::FlatStore::read_local_reclaim_object(void*, void*, unsigned long)` | 0 → 1145 | read / added helper |
| `src/cmd/objectpread.o` | `tomo::FlatStore::find_in(int, unsigned long, tomo::Slice) const` | 0 → 630 | read / added helper |
| `src/cmd/objectpread.o` | `std::unique_ptr<tomo::atomic_tripwire_detail::State, std::default_delete<tomo::atomic_tripwire_detail::State> >::~unique_ptr()` | 0 → 183 | read / added helper |
| `src/cmd/objectpread.o` | `std::unique_ptr<tomo::atomic_tripwire_detail::State, std::default_delete<tomo::atomic_tripwire_detail::State> >::~unique_ptr()` | 0 → 183 | read / added helper |
| `src/cmd/objectpread.o` | `tomo::FlatStore::atomic_resolve_internal(unsigned long, tomo::Slice, unsigned long, bool)::{lambda(tomo::AtomicEntry&, tomo::KvObj*, bool)#1}::operator()(tomo::AtomicEntry&, tomo::KvObj*, bool) const` | 0 → 1067 | read / added helper |
| `db0/src/cmd/hexpread.o` | `_GLOBAL__sub_I__ZN8tomo_db08hexpread9parse_i64ENS_5SliceERl` | 0 → 47 | read / added helper |
| `db0/src/cmd/hexpread.o` | `void tomo_db0::reply_bulk<tomo_db0::Op::Sink>(tomo_db0::Op::Sink&&, tomo_db0::Slice) [clone .isra.0]` | 0 → 477 | read / added helper |
| `db0/src/cmd/hexpread.o` | `void tomo_db0::reply_map_header<tomo_db0::Op::Sink>(tomo_db0::Op::Sink&&, unsigned long, bool)` | 0 → 749 | read / added helper |
| `db0/src/cmd/hexpread.o` | `tomo_db0::hash_parked_reply(tomo_db0::Shard&, tomo_db0::Op&)` | 0 → 788 | read / added helper |
| `db0/src/cmd/hexpread.o` | `void tomo_db0::reply_array_header<tomo_db0::Op::Sink>(tomo_db0::Op::Sink&&, unsigned long)` | 0 → 444 | read / added helper |
| `db0/src/cmd/hexpread.o` | `tomo_db0::atomic_tripwire_samekey(tomo_db0::AtomicTripwireSamekey)` | 0 → 233 | read / added helper |
| `db0/src/cmd/hexpread.o` | `tomo_db0::Op::Sink::append(char const*, unsigned long)` | 0 → 533 | read / added helper |
| `db0/src/cmd/hexpread.o` | `tomo_db0::hexpread::reply_scan(tomo_db0::Op&, unsigned long, std::vector<tomo_db0::hexpread::ScanItem, std::allocator<tomo_db0::hexpread::ScanItem> > const&, bool)` | 0 → 867 | read / added helper |
| `db0/src/cmd/hexpread.o` | `tomo_db0::hexpread::HashReadView::random(unsigned long, unsigned long)` | 0 → 232 | read / added helper |
| `db0/src/cmd/hexpread.o` | `tomo_db0::hexpread::filtered_cmd_hget(tomo_db0::Shard&, tomo_db0::Op&, tomo_db0::KvObj*, tomo_db0::hexpread::HashReadView&)` | 0 → 820 | read / added helper |
| `db0/src/cmd/hexpread.o` | `tomo_db0::hexpread::filtered_cmd_hlen(tomo_db0::Shard&, tomo_db0::Op&, tomo_db0::KvObj*, tomo_db0::hexpread::HashReadView&)` | 0 → 542 | read / added helper |
| `db0/src/cmd/hexpread.o` | `tomo_db0::hexpread::filtered_cmd_hmget(tomo_db0::Shard&, tomo_db0::Op&, tomo_db0::KvObj*, tomo_db0::hexpread::HashReadView&)` | 0 → 1136 | read / added helper |
| `db0/src/cmd/hexpread.o` | `tomo_db0::hexpread::filtered_cmd_hscan(tomo_db0::Shard&, tomo_db0::Op&, tomo_db0::KvObj*, tomo_db0::hexpread::HashReadView&)` | 0 → 425 | read / added helper |
| `db0/src/cmd/hexpread.o` | `tomo_db0::hexpread::filtered_cmd_hscan(tomo_db0::Shard&, tomo_db0::Op&, tomo_db0::KvObj*, tomo_db0::hexpread::HashReadView&) [clone .cold]` | 0 → 106 | read / added helper |
| `db0/src/cmd/hexpread.o` | `tomo_db0::hexpread::hash_ttl_read_view(tomo_db0::Shard&, tomo_db0::Op&, tomo_db0::KvObj*&, tomo_db0::hexpread::HashReadView&)` | 0 → 328 | read / added helper |
| `db0/src/cmd/hexpread.o` | `tomo_db0::hexpread::parse_scan_options(tomo_db0::Op&, tomo_db0::hexpread::ScanOptions&)` | 0 → 1069 | read / added helper |
| `db0/src/cmd/hexpread.o` | `tomo_db0::hexpread::filtered_cmd_hexists(tomo_db0::Shard&, tomo_db0::Op&, tomo_db0::KvObj*, tomo_db0::hexpread::HashReadView&)` | 0 → 479 | read / added helper |
| `db0/src/cmd/hexpread.o` | `tomo_db0::hexpread::filtered_cmd_hstrlen(tomo_db0::Shard&, tomo_db0::Op&, tomo_db0::KvObj*, tomo_db0::hexpread::HashReadView&)` | 0 → 654 | read / added helper |
| `db0/src/cmd/hexpread.o` | `tomo_db0::hexpread::filtered_select_unique(tomo_db0::hexpread::HashReadView&, unsigned int, unsigned int, std::vector<unsigned int, std::allocator<unsigned int> >&)` | 0 → 2318 | read / added helper |
| `db0/src/cmd/hexpread.o` | `tomo_db0::hexpread::filtered_select_unique(tomo_db0::hexpread::HashReadView&, unsigned int, unsigned int, std::vector<unsigned int, std::allocator<unsigned int> >&) [clone .cold]` | 0 → 192 | read / added helper |
| `db0/src/cmd/hexpread.o` | `tomo_db0::hexpread::filtered_cmd_hrandfield(tomo_db0::Shard&, tomo_db0::Op&, tomo_db0::KvObj*, tomo_db0::hexpread::HashReadView&)` | 0 → 3108 | read / added helper |
| `db0/src/cmd/hexpread.o` | `tomo_db0::hexpread::filtered_cmd_hrandfield(tomo_db0::Shard&, tomo_db0::Op&, tomo_db0::KvObj*, tomo_db0::hexpread::HashReadView&) [clone .cold]` | 0 → 139 | read / added helper |
| `db0/src/cmd/hexpread.o` | `tomo_db0::hexpread::filtered_generic_getall(tomo_db0::Shard&, tomo_db0::Op&, tomo_db0::hexpread::GetAllMode, tomo_db0::KvObj*, tomo_db0::hexpread::HashReadView&)` | 0 → 986 | read / added helper |
| `db0/src/cmd/hexpread.o` | `tomo_db0::hexpread::parse_i64(tomo_db0::Slice, long&)` | 0 → 327 | read / added helper |
| `db0/src/cmd/hexpread.o` | `tomo_db0::FlatStore::atomic_resolve_internal(unsigned long, tomo_db0::Slice, unsigned long, bool)` | 0 → 3713 | read / added helper |
| `db0/src/cmd/hexpread.o` | `void tomo_db0::reply_err<tomo_db0::Op::Sink>(tomo_db0::Op::Sink&&, char const*)` | 0 → 973 | read / added helper |
| `db0/src/cmd/hexpread.o` | `tomo_db0::hexpread::HashReadView::field_live(tomo_db0::Slice) const` | 0 → 575 | read / added helper |
| `db0/src/cmd/hexpread.o` | `tomo_db0::FlatStore::atomic_read_owns_value(unsigned long, tomo_db0::Slice, tomo_db0::KvObj const*) const` | 0 → 2335 | read / added helper |
| `db0/src/cmd/hexpread.o` | `std::_Hashtable<unsigned int, unsigned int, std::allocator<unsigned int>, std::__detail::_Identity, std::equal_to<unsigned int>, std::hash<unsigned int>, std::__detail::_Mod_range_hashing, std::__detail::_Default_ranged_hash, std::__detail::_Prime_rehash_policy, std::__detail::_Hashtable_traits<false, true, true> >::_M_rehash(unsigned long, unsigned long const&)` | 0 → 339 | read / added helper |
| `db0/src/cmd/hexpread.o` | `std::unique_ptr<tomo_db0::atomic_tripwire_detail::State, std::default_delete<tomo_db0::atomic_tripwire_detail::State> >::~unique_ptr()` | 0 → 183 | read / added helper |
| `db0/src/cmd/hexpread.o` | `std::unique_ptr<tomo_db0::atomic_tripwire_detail::State, std::default_delete<tomo_db0::atomic_tripwire_detail::State> >::~unique_ptr()` | 0 → 183 | read / added helper |
| `db0/src/cmd/hexpread.o` | `std::vector<tomo_db0::hexpread::ScanItem, std::allocator<tomo_db0::hexpread::ScanItem> >::~vector()` | 0 → 33 | read / added helper |
| `db0/src/cmd/hexpread.o` | `std::vector<tomo_db0::hexpread::ScanItem, std::allocator<tomo_db0::hexpread::ScanItem> >::~vector()` | 0 → 33 | read / added helper |
| `db0/src/cmd/hexpread.o` | `std::vector<unsigned int, std::allocator<unsigned int> >::~vector()` | 0 → 33 | read / added helper |
| `db0/src/cmd/hexpread.o` | `std::vector<unsigned int, std::allocator<unsigned int> >::~vector()` | 0 → 33 | read / added helper |
| `db0/src/cmd/hexpread.o` | `tomo_db0::hexpread::filtered_cmd_hscan(tomo_db0::Shard&, tomo_db0::Op&, tomo_db0::KvObj*, tomo_db0::hexpread::HashReadView&)::{lambda(void*, tomo_db0::Slice, tomo_db0::Slice)#1}::_FUN(void*, tomo_db0::Slice, tomo_db0::Slice)` | 0 → 581 | read / added helper |
| `db0/src/cmd/hexpread.o` | `tomo_db0::hexpread::filtered_cmd_hrandfield(tomo_db0::Shard&, tomo_db0::Op&, tomo_db0::KvObj*, tomo_db0::hexpread::HashReadView&)::{lambda(void*, tomo_db0::Slice, tomo_db0::Slice)#1}::_FUN(void*, tomo_db0::Slice, tomo_db0::Slice)` | 0 → 533 | read / added helper |
| `db0/src/cmd/hexpread.o` | `tomo_db0::hexpread::filtered_generic_getall(tomo_db0::Shard&, tomo_db0::Op&, tomo_db0::hexpread::GetAllMode, tomo_db0::KvObj*, tomo_db0::hexpread::HashReadView&)::{lambda(void*, tomo_db0::Slice, tomo_db0::Slice)#1}::_FUN(void*, tomo_db0::Slice, tomo_db0::Slice)` | 0 → 208 | read / added helper |
| `db0/src/cmd/hexpread.o` | `tomo_db0::FlatStore::atomic_resolve_internal(unsigned long, tomo_db0::Slice, unsigned long, bool)::{lambda(tomo_db0::AtomicEntry&, tomo_db0::KvObj*, bool)#1}::operator()(tomo_db0::AtomicEntry&, tomo_db0::KvObj*, bool) const` | 0 → 1067 | read / added helper |
| `db0/src/cmd/objectpread.o` | `_GLOBAL__sub_I__ZN8tomo_db020object_read_no_touchERNS_5ShardEmNS_5SliceE` | 0 → 47 | read / added helper |
| `db0/src/cmd/objectpread.o` | `tomo_db0::ExpireIndex::collapse_empty()` | 0 → 139 | read / added helper |
| `db0/src/cmd/objectpread.o` | `tomo_db0::ExpireIndex::erase(unsigned long) [clone .isra.0]` | 0 → 369 | read / added helper |
| `db0/src/cmd/objectpread.o` | `tomo_db0::ExpireIndex::erase(unsigned long) [clone .isra.0] [clone .cold]` | 0 → 5 | read / added helper |
| `db0/src/cmd/objectpread.o` | `tomo_db0::kvobj_external_bytes(tomo_db0::KvObj const*)` | 0 → 1606 | read / added helper |
| `db0/src/cmd/objectpread.o` | `tomo_db0::object_read_no_touch(tomo_db0::Shard&, unsigned long, tomo_db0::Slice)` | 0 → 1737 | read / added helper |
| `db0/src/cmd/objectpread.o` | `tomo_db0::object_read_no_touch(tomo_db0::Shard&, unsigned long, tomo_db0::Slice) [clone .cold]` | 0 → 5 | read / added helper |
| `db0/src/cmd/objectpread.o` | `tomo_db0::atomic_tripwire_samekey(tomo_db0::AtomicTripwireSamekey)` | 0 → 233 | read / added helper |
| `db0/src/cmd/objectpread.o` | `tomo_db0::kvobj_free_with_capacity(tomo_db0::KvObj*, unsigned long)` | 0 → 772 | read / added helper |
| `db0/src/cmd/objectpread.o` | `tomo_db0::FlatStore::retire_obj_read_local(tomo_db0::KvObj*)` | 0 → 512 | read / added helper |
| `db0/src/cmd/objectpread.o` | `tomo_db0::FlatStore::atomic_resolve_internal(unsigned long, tomo_db0::Slice, unsigned long, bool)` | 0 → 3713 | read / added helper |
| `db0/src/cmd/objectpread.o` | `tomo_db0::FlatStore::read_local_reclaim_object(void*, void*, unsigned long)` | 0 → 1145 | read / added helper |
| `db0/src/cmd/objectpread.o` | `tomo_db0::FlatStore::erase_in(int, unsigned long, tomo_db0::Slice, bool*) [clone .isra.0]` | 0 → 2445 | read / added helper |
| `db0/src/cmd/objectpread.o` | `std::unique_ptr<tomo_db0::atomic_tripwire_detail::State, std::default_delete<tomo_db0::atomic_tripwire_detail::State> >::~unique_ptr()` | 0 → 183 | read / added helper |
| `db0/src/cmd/objectpread.o` | `std::unique_ptr<tomo_db0::atomic_tripwire_detail::State, std::default_delete<tomo_db0::atomic_tripwire_detail::State> >::~unique_ptr()` | 0 → 183 | read / added helper |
| `db0/src/cmd/objectpread.o` | `tomo_db0::FlatStore::atomic_resolve_internal(unsigned long, tomo_db0::Slice, unsigned long, bool)::{lambda(tomo_db0::AtomicEntry&, tomo_db0::KvObj*, bool)#1}::operator()(tomo_db0::AtomicEntry&, tomo_db0::KvObj*, bool) const` | 0 → 1067 | read / added helper |
