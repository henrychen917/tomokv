# Static identity and layout control

PRE ef5204b2e, POST WATCH-count fix only; full hashes are binaries.sha256.
All eight locked public layouts are enforced by the successful production build.
No struct or allocator layout was changed. .text: PRE 8,124,983 bytes; POST and
PAD-A 8,125,079 bytes (+96). PAD-A preserves every POST function address and size.

`tools/ccfix_audit.py` compares 18,040 object bodies: 18,034 equal, six changed.
All 1,213 command handlers and all 1,316 selected hot bodies are identical under
its relocation-aware byte comparison. The six changes are the two WATCH-count
functions, generic classify_keys, generic xshard_prepare plus its cold split,
and generic pubsub_handle_home_request. Only WATCH counting was edited; the
other changes are compiler propagation, fully inventoried rather than waived.

The gate's unchanged reorder_noop linked normalizer, including literal pools,
selects 333 bodies: 331 identical, generic xshard_prepare and its cold split
differ. The 12 specifically named GET/SET and captured-local-MGET bodies are
identical. This is not a claim that the complete MGET/MSET preparation path is
byte-identical: xshard_prepare is shared by them and has compiler drift. The
registered command handlers are identical in the object audit. Merit must judge
the composed path; no identity difference is treated as an acceptance or veto.

`tools/txnfix_scatter_audit.py` retains both complete scatter-object inventories
and disassemblies. All changed linked bodies (including literal/address
propagation) are listed in linked-identity.json; the executable reproduction is
linked_identity.py. There is no instruction-count or performance claim.

PAD-A restores the validated 37-byte relocation-free PRE WATCH-count leaves
inside the POST functions and fills only each unused tail with NOPs. Its
semantics fail all eight databases-16 WATCH legs, with databases-1 controls
passing, exactly like PRE. The byte manifest is arms.json. The distinct
broken-writer binary exists only to falsify AT4.19 and is not a merit arm.
