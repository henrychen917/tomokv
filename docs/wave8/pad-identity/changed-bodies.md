# Linked body differences

Strict gate instruction/address normalization; local clone multiplicity retained. Identity is a proxy.

| Function | Headline sizes | Merged sizes | Reason |
|---|---|---|---|
| `tomo::ExLoopT<true>::drain_local_reads_bounded_impl<false>(unsigned int)::{lambda(unsigned int)#1}::operator()(unsigned int) const` | [328] | [328] | Composition of lualibs, latencyfix; residual instructions/layout require merit review. |
| `tomo::ExLoopT<true>::drain_local_reads_bounded_impl<true>(unsigned int)::{lambda(unsigned int)#1}::operator()(unsigned int) const` | [328] | [328] | Composition of lualibs, latencyfix; residual instructions/layout require merit review. |
| `tomo_db0::ExLoopT<true>::drain_local_reads_bounded_impl<false>(unsigned int)::{lambda(unsigned int)#1}::operator()(unsigned int) const` | [328] | [328] | Composition of lualibs, latencyfix; residual instructions/layout require merit review. |
| `tomo_db0::ExLoopT<true>::drain_local_reads_bounded_impl<true>(unsigned int)::{lambda(unsigned int)#1}::operator()(unsigned int) const` | [328] | [328] | Composition of lualibs, latencyfix; residual instructions/layout require merit review. |
| `tomo_wave8_pad_a` | [] | [156128] | Unedited body: compiler/link layout propagation in merged source; no single optimizer decision isolated. |
