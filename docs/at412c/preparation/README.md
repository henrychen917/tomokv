# Preparation boundary

The script route now has its own compile-time specialization of the existing
preparation implementation. Classification hands it off before constructing
RuntimeLoadingGuard. The emitted ordinary entry tail-jumps to the script entry;
its FIFO call and argument liveness do not join ordinary arena setup. Scripts
have no reload containers. The ordinary specialization keeps the original
loader types and cleanup. Four formerly singleton helper leaves and SortOptions
copy stay explicitly inline when preparation has two instantiations.

This changes no command algorithm, claim protocol, admission predicate, slot
counting/release site, arena layout or published layout lock. The same source
body implements the two compiled routes. A script's empty reload members are
already initialized by ScatterState's constructor.

The selected production recipes use xshard IPA budgets 152000 (normal) and
150500 (db0); the final-source compile-only receipts are ../budgets-final/.
Batch-1 MGET/MSET scope deltas are in batch1.json: all twelve are negative
(-53 through -8 instructions). The script preparation smoke runs the production
linked fixture to exact reply/data completion in both namespaces, both modes,
and atomic 0/1. The final 48-pair and 16-pair script traces are recorded separately
in ../instructions/ and ../script-instructions/; these preliminary checks do not
substitute for them. No rate was measured.
