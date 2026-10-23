# Linked body differences

Strict gate instruction/address normalization; local clone multiplicity retained. Identity is a proxy.

| Function | Headline sizes | Merged sizes | Reason |
|---|---|---|---|
| `tomo::ExLoopT<true>::drain_local_reads_bounded_impl<false>(unsigned int)::{lambda(unsigned int)#1}::operator()(unsigned int) const` | [328] | [328] | fliplisten changes this body; merged compiler propagation differs from isolated POST. |
| `tomo::ExLoopT<true>::drain_local_reads_bounded_impl<true>(unsigned int)::{lambda(unsigned int)#1}::operator()(unsigned int) const` | [328] | [328] | fliplisten changes this body; merged compiler propagation differs from isolated POST. |
| `tomo_db0::ExLoopT<true>::drain_local_reads_bounded_impl<false>(unsigned int)::{lambda(unsigned int)#1}::operator()(unsigned int) const` | [328] | [328] | fliplisten changes this body; merged compiler propagation differs from isolated POST. |
| `tomo_db0::ExLoopT<true>::drain_local_reads_bounded_impl<true>(unsigned int)::{lambda(unsigned int)#1}::operator()(unsigned int) const` | [328] | [328] | fliplisten changes this body; merged compiler propagation differs from isolated POST. |
| `unsigned int tomo_db0::FlatStore::scan_home<tomo_db0::(anonymous namespace)::cmd_scan(tomo_db0::Shard&, tomo_db0::Op&)::{lambda(tomo_db0::KvObj*)#1}>(int, unsigned int, tomo_db0::(anonymous namespace)::cmd_scan(tomo_db0::Shard&, tomo_db0::Op&)::{lambda(tomo_db0::KvObj*)#1}&, bool)` | [1567] | [1567] | Exact linked body from txnfix, bugs5, compat3, trackfix, fliplisten; lane change retained. |
| `void tomo::IoLoop::on_cqe<true, true, true>(io_uring_cqe*)` | [865] | [865] | Exact linked body from txnfix, trackfix, netfix; lane change retained. |
| `wave5_pad_a` | [] | [329075] | Unedited body: compiler/link layout propagation in merged source; no single optimizer decision isolated. |
