# Reverified against 98c69316d

All anchors below were read from this lane, not inferred from the investigation's
line numbers. The baseline source is frozen in `build/publishfix/pre/source`.

- `src/core/server.h:2566`: increment in-flight before drawing tickets, both SC.
  `:2571`: load drawn before the acq_rel decrement; the non-last path returns.
  `:2583`: release CAS publishes only that old drawn value. `:2625`: read cuts
  use the SC safe watermark. The fix adds only the investigation 5.1 loop.
- `src/cmd/scatter_engine.inc:2053`: cross-owner MGET takes the watermark cut;
  `:2062`: safe behind drawn records `atomic_commit_holds`.
- `src/cmd/atomics_glue.inc:393`: register_snapshot confirms the current safe
  watermark; it does not promote a reader to the raw ticket sequence.
- `src/store/flatstore_atomic.inc:1110-1151`: own-connection visibility is exempt
  from the foreign cut; foreign undecided/above-cut entries are excluded; the
  remaining highest epoch wins. The two writers in crossing use distinct clients.
- `src/cmd/scatter_engine.inc:4053-4062`: a batch reserves, stores each group
  epoch, then publishes. `:4064-4097`: the same ticket order feeds AOF decisions
  and only then completes replies. Acknowledgement does not repair the watermark.
- `src/persist/aof.cc:700-758`: resolve_groups ranks staged groups by ticket and
  writes that ticket to each group record. `:1159-1164`: boot recovery restores
  both counters. This is the only other safe-watermark writer.
- `tests/aoforder.py:111-145` at PRE: both OK replies precede live MGET; either
  complete winner is accepted, followed by unchanged replay/restart equality.
- `tests/execfix_unit.cc:269-287` and `tests/atomic_survivors_unit.cc:226-240`
  demonstrate bare-Server reserve/publish brackets without listeners.

The Appendix A model compares its rechecked sequence with shared safe. The added
EXACT FIX enumeration also models 5.1 literally (compare with local drawn and
adopt newer). Two/three committers visit 180/8675 states, with zero safety failures
and zero orphaned final states. This is bounded SC interleaving evidence, not a
complete C++ weak-memory proof. The zero-count acquire reads follow the sequence
load; the reserve SC ordering and decrement release sequence carry stored epochs
to the release watermark CAS. No reader retry, new field, or layout change is used.
