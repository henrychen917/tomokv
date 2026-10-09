# 7 — Duplicate literal-copy threshold: DEAD spelling; one named threshold

`Buf::append` and `Op::Sink::append` now use `kInlineLiteralMax` from `slice.h`.
It is 16 bytes, excluding the terminating NUL, just as both PRE literals were.
The runtime-length copy policy and every other unrelated 16-byte quantity are
unchanged. `constant-spellings.txt` includes the tests/tools literal-pattern grep.

PRE is `dab740964`; POST is `build/deadswitch/07-literal/tomokv` and includes
the previously byte-proved candidates 1, 3 and 4. Both namespaces were rebuilt
with the unchanged Makefile flags and budgets. Direct comparison against PRE
gives **1492/1492 hot bodies, 17078/17078 full emitted bodies, no changes**.
All loadable ELF section contents, addresses, sizes and alignments match PRE
(build-ID excluded). Full debug ELF hashes differ because source/debug metadata
changes; no executable/layout difference is being hidden by that distinction.

The production instantiations themselves are the compile/code-generation test:
they exercise the literal overloads in both sinks and both namespaces, with all
emitted functions accounted for. Gate rows +0/+0. No PAD or compiler adjustment.
