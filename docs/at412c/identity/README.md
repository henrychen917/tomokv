# Final identity audit

PRE objects: build/at412/pre-source/build, commit 7ae703778.
POST objects: build/, production source f7204660e, final make all.

GET/SET/INCR/MGET/MSET handler bodies: **24/24 relocation-equal**. The audit
preserves member offsets and canonicalizes named relocations. Its wrapper fails
on any mismatch in this requested set.

The raw ccfix audit reports 18,342/18,669 common bodies equal, 1,274/1,378 hot
bodies equal and 1,224/1,232 handlers equal. Its strict assertion fails on the
104 flush_ready/r7_flush_ready instantiations containing D4′'s cold resume arm;
the wrapper accepts exactly that list and INFO/DEBUG handlers. The extended
list is 1,327/1,448 equal: besides resume it includes changed preparation,
script completion, script completion tail targets and owner Place dispatch,
including one db0 owner lambda. These are listed in hot-bodies.json. Linked
sections differ; the exact-image control is the POST-layout/PAD-A pair.

No claim of whole-program or whole-hot-path byte identity is made. All 48
bounded ordinary-command scopes separately pass the zero-added-instructions
requirement (../instructions/).
