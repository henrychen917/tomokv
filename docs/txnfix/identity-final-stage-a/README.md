# Stage A identity at the IO-signal commit

POST runtime source: ace6d0c07. The binary was linked immediately before committing the same runtime changes; its embedded Git version can therefore name the preceding commit. SHA-256: `2a0eefaafa8eb2ce4e249c0e812140baf77d206f21e0b6b7f89fe8843552d07c`. No source or object was rebuilt during this inventory.

Hot relocation-normalized object bodies: 1177/1204 equal. Full canonical inventory: 15667/16472 equal; 805 changed. Handler bodies: 1199/1210 equal, including every GET/SET handler. The two inventories use different matching/classification rules; their denominators are not interchangeable.

All 27 changed hot bodies are listed below. Their hot source was not intentionally changed; shared cold definitions changed compiler decisions. That attribution is an inference and does not establish identical executed instructions. The loop headers are byte-identical to PRE. Main-command performance and the strict static bar remain unaccepted.

| Object | Body | Bytes PRE → POST |
|---|---|---|
| `db0/src/cmd/xshard.o` | `tomo_db0::FlatStore::find_in(int, unsigned long, tomo_db0::Slice) const` | 554 → 446 |
| `db0/src/cmd/xshard.o` | `tomo_db0::FlatStore::erase_in_read_local(int, unsigned long, tomo_db0::Slice, bool*)` | 732 → 606 |
| `db0/src/cmd/xshard.o` | `tomo_db0::FlatStore::insert_into_read_local(int, unsigned long, tomo_db0::KvObj*, bool)` | 1602 → 1493 |
| `db0/src/cmd/xshard.o` | `tomo_db0::FlatStore::insert_into(int, unsigned long, tomo_db0::KvObj*, bool)` | 975 → 899 |
| `db0/src/cmd/xshard.o` | `tomo_db0::FlatStore::erase_in(int, unsigned long, tomo_db0::Slice, bool*)` | 692 → 564 |
| `db0/src/cmd/xshard.o` | `tomo_db0::FlatStore::erase_notify(unsigned long, tomo_db0::Slice, tomo_db0::FlatNotifySink*, tomo_db0::FlatStore::EraseEvent)` | 933 → 673 |
| `db0/src/cmd/xshard.o` | `tomo_db0::FlatStore::insert_notify(unsigned long, tomo_db0::KvObj*, tomo_db0::FlatNotifySink*)` | 941 → 737 |
| `db0/src/cmd/xshard.o` | `tomo_db0::FlatStore::find(unsigned long, tomo_db0::Slice)` | 1017 → 806 |
| `db0/src/cmd/xshard.o` | `tomo_db0::FlatStore::find_notify(unsigned long, tomo_db0::Slice, tomo_db0::FlatNotifySink*)` | 942 → 782 |
| `db0/src/core/genthread.o` | `tomo_db0::IoLoop::DispatchResult tomo_db0::IoLoop::parse_and_dispatch<true, 0u, false>(tomo_db0::Client*) [clone .isra.0]` | 9538 → 9522 |
| `db0/src/core/reorder.o` | `tomo_db0::IoLoop::DispatchResult tomo_db0::IoLoop::parse_and_dispatch<true, 0u, false>(tomo_db0::Client*) [clone .isra.0]` | 9522 → 9538 |
| `db0/src/core/reorder.o` | `tomo_db0::WbEngine::serve_tls_impl<true, true, true, false, true>(tomo_db0::Client&, tomo_db0::TlsConn&, bool*)::{lambda(tomo_db0::Op&)#1}::operator()(tomo_db0::Op&) const` | 1244 → 1016 |
| `db0/src/core/reorder.o` | `tomo_db0::WbEngine::serve_impl<true, true, true, true, false, true>(tomo_db0::Client&, bool*)::{lambda(tomo_db0::Op&)#1}::operator()(tomo_db0::Op&) const` | 1212 → 984 |
| `db0/src/core/reorder.o` | `tomo_db0::WbEngine::serve_impl<true, true, false, true, false, true>(tomo_db0::Client&, bool*)::{lambda(tomo_db0::Op&)#1}::operator()(tomo_db0::Op&) const` | 1212 → 984 |
| `db0/src/core/reorder.o` | `bool tomo_db0::ExLoopT<true>::execute<false, false>(tomo_db0::Task const&)` | 3623 → 3557 |
| `src/cmd/xshard.o` | `tomo::FlatStore::find_in(int, unsigned long, tomo::Slice) const` | 630 → 346 |
| `src/cmd/xshard.o` | `tomo::FlatStore::erase_in_read_local(int, unsigned long, tomo::Slice, bool*)` | 871 → 538 |
| `src/cmd/xshard.o` | `tomo::FlatStore::insert_into(int, unsigned long, tomo::KvObj*, bool)` | 1014 → 942 |
| `src/cmd/xshard.o` | `tomo::FlatStore::erase_in(int, unsigned long, tomo::Slice, bool*)` | 783 → 580 |
| `src/cmd/xshard.o` | `tomo::FlatStore::find_notify(unsigned long, tomo::Slice, tomo::FlatNotifySink*)` | 846 → 782 |
| `src/cmd/xshard.o` | `tomo::FlatStore::erase(unsigned long, tomo::Slice)` | 1109 → 543 |
| `src/cmd/xshard.o` | `tomo::FlatStore::insert_read_local(unsigned long, tomo::KvObj*)` | 1590 → 1287 |
| `src/cmd/xshard.o` | `tomo::FlatStore::erase_notify(unsigned long, tomo::Slice, tomo::FlatNotifySink*, tomo::FlatStore::EraseEvent)` | 812 → 673 |
| `src/core/reorder.o` | `unsigned int tomo::ExLoopT<true>::r7_sweep<32u, true, false, false>()` | 1536 → 1338 |
| `src/core/rl2s.o` | `tomo::IoLoop::DispatchResult tomo::IoLoop::parse_and_dispatch<false, 32u, true>(tomo::Client*)` | 20932 → 20939 |
| `src/snapshot/snapshot.o` | `tomo::FlatStore::find_in(int, unsigned long, tomo::Slice) const` | 540 → 346 |
| `src/snapshot/snapshot.o` | `tomo::FlatStore::erase_in(int, unsigned long, tomo::Slice, bool*)` | 621 → 580 |

The hot filter does not include the complete scatter interpreter. Its expected Stage A identity also fails:

| Body | Bytes PRE → POST |
|---|---|
| `tomo_db0::xshard_execute(tomo_db0::Task const&, tomo_db0::Shard&, tomo_db0::Op&, unsigned int)` | 23329 → 23778 |
| `tomo::xshard_execute(tomo::Task const&, tomo::Shard&, tomo::Op&, unsigned int)` | 21176 → 21439 |

scatter_engine.inc is unchanged. atomic_has_records, atomic_needs_version and atomic_has_script_intent retain identical source, but their callers are not all identical. See full/changed-bodies-with-reasons.json for every changed body and its source-level reason or explicit unresolved compiler attribution. It is an inventory, not a claim that all 805 changes are understood at instruction level.

The dedicated TLS notification has one load/test/conditional branch in the empty IO hook. Outlining reduced the prefix through the old cleanup-empty check from 19 instructions to 14 and the frame from 0x238 to 8 bytes in both namespaces. That improves this local path only. The new 64-byte-aligned TLS flag also raises ELF TLS alignment from 16 to 64 and moves 27 of 35 pre-existing named TLS symbols modulo a cache line. See ../tls-layout-final-stage-a.json. A layout control is required before accepting cost; none has been built.

All locked sizes and every pre-existing field offset, including the Server admission-barrier byte, are equal in both namespaces. AtomicScriptIntent=32 and AtomicPendingState=1352. Only the new Server cold tail adds 24,640 bytes. See ../layouts-final-stage-a.json.
