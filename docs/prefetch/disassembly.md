# PRE inline fallback inventory

Frozen ef5204b2e, GCC 13.3 release -O2. Enumerated by DWARF inline-function labels from objdump -dwlC, not only direct calls. Every listed body has zero prefetch instructions anywhere in its body. ExLoopT<false> is the plain 2s executor; ExLoopT<true> serves 1s and read-local-capable 2s. The two namespaces are the independently linked database runtimes.

| PRE address | Inline fallback-containing body | Bucket prefetch instructions |
|---|---|---|
| `0xd3ae0` | `unsigned int tomo_db0::ThreadCtx::drain_tasks_unmasked<false, tomo_db0::ExLoopT<false>::drain_tasks<32u, false>(bool)::{lambda(tomo_db0::Task const&)#1}&>(tomo_db0::ExLoopT<false>::drain_tasks<32u, false>(bool)::{lambda(tomo_db0::Task const&)#1}&)` | 0 |
| `0xd4370` | `unsigned int tomo_db0::ThreadCtx::drain_tasks<false, tomo_db0::ExLoopT<false>::drain_tasks<32u, false>(bool)::{lambda(tomo_db0::Task const&)#1}&>(tomo_db0::ExLoopT<false>::drain_tasks<32u, false>(bool)::{lambda(tomo_db0::Task const&)#1}&)` | 0 |
| `0xd4c30` | `unsigned int tomo_db0::ExLoopT<false>::drain_tasks<32u, false>(bool)` | 0 |
| `0xd5630` | `tomo_db0::ExLoopT<false>::run()` | 0 |
| `0x33f6a0` | `unsigned int tomo_db0::ThreadCtx::drain_tasks_unmasked<false, tomo_db0::ExLoopT<true>::drain_tasks<32u, false>(bool)::{lambda(tomo_db0::Task const&)#1}&>(tomo_db0::ExLoopT<true>::drain_tasks<32u, false>(bool)::{lambda(tomo_db0::Task const&)#1}&)` | 0 |
| `0x3400c0` | `unsigned int tomo_db0::ThreadCtx::drain_tasks<false, tomo_db0::ExLoopT<true>::drain_tasks<32u, false>(bool)::{lambda(tomo_db0::Task const&)#1}&>(tomo_db0::ExLoopT<true>::drain_tasks<32u, false>(bool)::{lambda(tomo_db0::Task const&)#1}&)` | 0 |
| `0x340b10` | `unsigned int tomo_db0::ExLoopT<true>::drain_tasks<32u, false>(bool)` | 0 |
| `0x3423d0` | `tomo_db0::ThreadCtx::drain_task_producer_chunks<false, tomo_db0::ExLoopT<true>::drain_tasks_read_local_interleaved<false>(bool, bool&)::{lambda(tomo_db0::Task const&)#1}&, tomo_db0::ExLoopT<true>::drain_tasks_read_local_interleaved<false>(bool, bool&)::{lambda()#2}&>(unsigned int, tomo_db0::ExLoopT<true>::drain_tasks_read_local_interleaved<false>(bool, bool&)::{lambda(tomo_db0::Task const&)#1}&, tomo_db0::ExLoopT<true>::drain_tasks_read_local_interleaved<false>(bool, bool&)::{lambda()#2}&, bool)::{lambda(unsigned int)#1}::operator()(unsigned int) const` | 0 |
| `0x342e10` | `unsigned int tomo_db0::ExLoopT<true>::drain_tasks_read_local_interleaved<false>(bool, bool&)` | 0 |
| `0x3dae20` | `tomo_db0::ExLoopT<true>::r7_drain_tasks_impl<false, 32u, false>(bool)::{lambda(tomo_db0::Task const*, unsigned int, tomo_db0::ReorderResult)#1}::operator()(tomo_db0::Task const*, unsigned int, tomo_db0::ReorderResult) const` | 0 |
| `0x3db2d0` | `tomo_db0::ExLoopT<true>::r7_drain_tasks_impl<true, 32u, false>(bool)::{lambda(tomo_db0::Task const*, unsigned int, tomo_db0::ReorderResult)#1}::operator()(tomo_db0::Task const*, unsigned int, tomo_db0::ReorderResult) const` | 0 |
| `0x3dc240` | `void tomo_db0::r7::ShadowReorderQueues<32ul>::submit<tomo_db0::ExLoopT<true>::r7_drain_tasks_impl<true, 32u, false>(bool)::{lambda(tomo_db0::Task const*, unsigned int, tomo_db0::ReorderResult)#1}>(tomo_db0::Task const*, unsigned int, tomo_db0::ExLoopT<true>::r7_drain_tasks_impl<true, 32u, false>(bool)::{lambda(tomo_db0::Task const*, unsigned int, tomo_db0::ReorderResult)#1}&)` | 0 |
| `0x3dd860` | `void tomo_db0::r7::ExReorderQueues<32ul>::submit<tomo_db0::ExLoopT<true>::r7_drain_tasks_impl<false, 32u, false>(bool)::{lambda(tomo_db0::Task const*, unsigned int, tomo_db0::ReorderResult)#1}>(tomo_db0::Task const*, unsigned int, tomo_db0::ExLoopT<true>::r7_drain_tasks_impl<false, 32u, false>(bool)::{lambda(tomo_db0::Task const*, unsigned int, tomo_db0::ReorderResult)#1}&)` | 0 |
| `0x483980` | `unsigned int tomo::ThreadCtx::drain_tasks_unmasked<false, tomo::ExLoopT<false>::drain_tasks<32u, false>(bool)::{lambda(tomo::Task const&)#1}&>(tomo::ExLoopT<false>::drain_tasks<32u, false>(bool)::{lambda(tomo::Task const&)#1}&)` | 0 |
| `0x484210` | `unsigned int tomo::ThreadCtx::drain_tasks<false, tomo::ExLoopT<false>::drain_tasks<32u, false>(bool)::{lambda(tomo::Task const&)#1}&>(tomo::ExLoopT<false>::drain_tasks<32u, false>(bool)::{lambda(tomo::Task const&)#1}&)` | 0 |
| `0x484ad0` | `unsigned int tomo::ExLoopT<false>::drain_tasks<32u, false>(bool)` | 0 |
| `0x4854d0` | `tomo::ExLoopT<false>::run()` | 0 |
| `0x704ad0` | `unsigned int tomo::ThreadCtx::drain_tasks_unmasked<false, tomo::ExLoopT<true>::drain_tasks<32u, false>(bool)::{lambda(tomo::Task const&)#1}&>(tomo::ExLoopT<true>::drain_tasks<32u, false>(bool)::{lambda(tomo::Task const&)#1}&)` | 0 |
| `0x7054f0` | `unsigned int tomo::ThreadCtx::drain_tasks<false, tomo::ExLoopT<true>::drain_tasks<32u, false>(bool)::{lambda(tomo::Task const&)#1}&>(tomo::ExLoopT<true>::drain_tasks<32u, false>(bool)::{lambda(tomo::Task const&)#1}&)` | 0 |
| `0x705f40` | `unsigned int tomo::ExLoopT<true>::drain_tasks<32u, false>(bool)` | 0 |
| `0x707800` | `tomo::ThreadCtx::drain_task_producer_chunks<false, tomo::ExLoopT<true>::drain_tasks_read_local_interleaved<false>(bool, bool&)::{lambda(tomo::Task const&)#1}&, tomo::ExLoopT<true>::drain_tasks_read_local_interleaved<false>(bool, bool&)::{lambda()#2}&>(unsigned int, tomo::ExLoopT<true>::drain_tasks_read_local_interleaved<false>(bool, bool&)::{lambda(tomo::Task const&)#1}&, tomo::ExLoopT<true>::drain_tasks_read_local_interleaved<false>(bool, bool&)::{lambda()#2}&, bool)::{lambda(unsigned int)#1}::operator()(unsigned int) const` | 0 |
| `0x708240` | `unsigned int tomo::ExLoopT<true>::drain_tasks_read_local_interleaved<false>(bool, bool&)` | 0 |
| `0x7a2bf0` | `tomo::ExLoopT<true>::r7_drain_tasks_impl<false, 32u, false>(bool)::{lambda(tomo::Task const*, unsigned int, tomo::ReorderResult)#1}::operator()(tomo::Task const*, unsigned int, tomo::ReorderResult) const` | 0 |
| `0x7a30a0` | `tomo::ExLoopT<true>::r7_drain_tasks_impl<true, 32u, false>(bool)::{lambda(tomo::Task const*, unsigned int, tomo::ReorderResult)#1}::operator()(tomo::Task const*, unsigned int, tomo::ReorderResult) const` | 0 |
| `0x7a4010` | `void tomo::r7::ExReorderQueues<32ul>::submit<tomo::ExLoopT<true>::r7_drain_tasks_impl<false, 32u, false>(bool)::{lambda(tomo::Task const*, unsigned int, tomo::ReorderResult)#1}>(tomo::Task const*, unsigned int, tomo::ExLoopT<true>::r7_drain_tasks_impl<false, 32u, false>(bool)::{lambda(tomo::Task const*, unsigned int, tomo::ReorderResult)#1}&)` | 0 |
| `0x7a5340` | `void tomo::r7::ShadowReorderQueues<32ul>::submit<tomo::ExLoopT<true>::r7_drain_tasks_impl<true, 32u, false>(bool)::{lambda(tomo::Task const*, unsigned int, tomo::ReorderResult)#1}>(tomo::Task const*, unsigned int, tomo::ExLoopT<true>::r7_drain_tasks_impl<true, 32u, false>(bool)::{lambda(tomo::Task const*, unsigned int, tomo::ReorderResult)#1}&)` | 0 |

POST retains two table hints in each of these new out-of-line bodies:

| Body | Hint address | Instruction |
|---|---|---|
| `tomo_db0::ExLoopT<false>::prefetch_exec_slots(tomo_db0::Task const*, unsigned int)` | `0xca27e` | `41 0f 18 0c c1 prefetcht0 (%r9,%rax,8)` |
| `tomo_db0::ExLoopT<false>::prefetch_exec_slots(tomo_db0::Task const*, unsigned int)` | `0xca2d3` | `41 0f 18 0c c1 prefetcht0 (%r9,%rax,8)` |
| `tomo_db0::ExLoopT<true>::prefetch_exec_slots(tomo_db0::Task const*, unsigned int)` | `0x32bfde` | `41 0f 18 0c c1 prefetcht0 (%r9,%rax,8)` |
| `tomo_db0::ExLoopT<true>::prefetch_exec_slots(tomo_db0::Task const*, unsigned int)` | `0x32c033` | `41 0f 18 0c c1 prefetcht0 (%r9,%rax,8)` |
| `tomo::ExLoopT<false>::prefetch_exec_slots(tomo::Task const*, unsigned int)` | `0x47a65e` | `41 0f 18 0c c1 prefetcht0 (%r9,%rax,8)` |
| `tomo::ExLoopT<false>::prefetch_exec_slots(tomo::Task const*, unsigned int)` | `0x47a6b3` | `41 0f 18 0c c1 prefetcht0 (%r9,%rax,8)` |
| `tomo::ExLoopT<true>::prefetch_exec_slots(tomo::Task const*, unsigned int)` | `0x6f185e` | `41 0f 18 0c c1 prefetcht0 (%r9,%rax,8)` |
| `tomo::ExLoopT<true>::prefetch_exec_slots(tomo::Task const*, unsigned int)` | `0x6f18b3` | `41 0f 18 0c c1 prefetcht0 (%r9,%rax,8)` |

The fused prefetch_owner_batch bodies are unchanged by the linked identity audit. Snapshot drains execute their separate per-task path and have no fallback walk. R7 emit closures, queue submissions, ordinary masked/unmasked transport drains and the embedded split run body are included above.
