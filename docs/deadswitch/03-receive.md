# 3 — Receive-chunk duplicate: DEAD spelling; canonical buffer quantity used

PRE: `dab740964`, `build/deadswitch/pre/tomokv`.
POST: `build/deadswitch/03-receive/tomokv` (includes byte-identical candidate 1).

The complete source inventory has six uses: `io_loop.h` at 863, 881, 918,
2475 and generated `reorder.cc` at 1448, 1549. Four feed
`Client::read_space(size_t, ...)`, two feed `TlsSession::reserve_input(char*&,
size_t)`. Every PRE expression denotes the same namespace-scope `uint32_t`
constant, 16 * 1024. `conn.h`'s `kRbufInitial` is `size_t` with exactly that value;
all six callees already accept `size_t`, so the replacement also preserves the
converted argument type. There are no addresses, overload distinctions, or
other consumers of the old name. The accompanying grep receipt includes tests
and tooling; `tests/r7shadow_sync.py` confirms the generated copies remain current.

The full emitted-body and hot audits compare directly with PRE, not just the
previous candidate. The linked audit additionally compares every loadable ELF
section and its address/size/alignment, excluding only the build-ID note. They
show no production-code or runtime-data difference. Debug information changes
because the old constant name disappears; that is not a whole-file identity claim.

Gate rows +0/+0. No compiler-budget adjustment or PAD.
