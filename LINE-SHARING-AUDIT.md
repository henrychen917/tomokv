# Hot-struct line-sharing audit (Opus, 2026-09-13, offsets from bench-bins/tomokv-headline-a363c2c5e via gdb ptype /o)
Law: an owner store per op into a line a peer reads per op (or vice versa) is a coherence transfer that nothing hides. 2s-only.
Worked example (already merged): ThreadCtx line 1 (64-127) held total_commands_ @120 next to the transport pointers @72-96 that
peers read when posting; swapping it out measured 2s GET +14.95% / SET +14.55%.

| # | struct | line | hot store field | peer field | store/op | peers | fix (size impact) |
|---|---|---|---|---|---|---|---|
| 1 | ThreadCtx | 10 (640-703) | task_notify_.words_[0] @696: owner exchange per drain pass (thread.h:612,678), peer fetch_or (480,522,551) | parked_ @688: read by EVERY producer on every push (thread.h:1096) | 1/pass + 1/edge | all N | move parked_ into the 1-byte hole at offset 7 beside ring_ (thread.h:1096 reads ring_ and parked_ on the same branch -> 1 line instead of 2). 1408 kept. |
| 2 | Op | 2 (128-191) | state @184: ex stores Done per op (ex_loop.h:1585) | same line: reply[96..119], direct, zc_* still being written by ex while io POLLS state (io_loop.h:4865,5020,5264) | 1 store + N polls | 1 | group completion flags at bytes 29-31 (reply_code_, reply_code_ok_, state); slide reply to 64. Op stays 336. |
| 3 | ThreadCtx | 11 (704-767) | client_notify_ @712, release_notify_ @728, transfer_notify_ @744: peer fetch_or; io posts releases per borrow batch (io_loop.h:4592) | nchan_ @760: owner reads it INSIDE the mask drain loop (thread.h:617,683,715) | 3 RMW/pass | all | move nchan_ into the 4-byte hole at 116 (read-mostly transport line it is used with). Size-neutral. |
| 4 | Client/Rob | 3 (192-255) | read_local_write_valid_ @200, _wide_ @208, _force_ @216, _arm_state_ @220, _unarmed_write_id_ @224, local_mget_fence_id_ @232: io stores per write op (rob.h:464,477-492) | dispatch_ @192: ex reads per drain run (ex_loop.h:1478) | 1-3/write | 1 ex | pair dispatch_+flush_ alone on line 3; push io-private read-local words to line 4. Rob 192 / Client 1984 kept. |
| 5 | Client/Rob | 4 (256-319) | read_local_owner_slots_ @272, read_local_state_ @280: io stores per read-local op (rob.h:247,411,464,502) | flush_ @256 (ex, ex_loop.h:1479), read_local_pending_slots_ @264 (ex reads per op, ex_loop.h:1486 -> rob.h:332-336) | 2-3/op | 1 ex | same reshuffle as #4; keep read_local_pending_slots_ with the frontier (two-sided); move _owner_slots_/_state_/_pending_filter_ to the io-private line. |
| 6 | Op | 0 (0-63) | io parse stores spec, shard, hash, rbuf_off, route_flags_ (0-28) | reply_code_ @29, reply_code_ok_ @30, reply[0..31]: ex-written per op | 5/op | 1 ex | subsumed by #2 (reply to 64 leaves only the 3 completion bytes on the parse line). |
| 7 | Shard | all | - | - | - | - | alignof(Shard)==8 and `new Shard` promises 16 (flatstore.h:3921): line grouping is base-dependent. Add an aligned operator new (alignas(64) would round 1440 -> 1472 and break the size lock). |
| 8 | Client | 30 (1920-1983) | retire_queued_ @1920: ex CAS per completion (ex_loop.h:2980), io store (io_loop.h:4616) | tls_slot_ @1980, acl_user_idx_ @1976: io reads per TLS/ACL op | 1/completion | 1 ex | PLAUSIBLE, TLS/ACL regimes only: leave. |
Notes: task_notify_ straddles 696-711 (word0 with parked_, word1 in line 11): #1 removes the worst half; a fully aligned mask
block costs +192 B and breaks the 1408 lock — not recommended. FlatStore is the model: FlatStoreLayoutLock (flatstore.h:3925-3975)
+ six static_asserts enforce >=64 B between the foreign-reader block, the owner counter block and the atomic-owner block for ANY
base, with an explicit gap member. ExQueue, Channel::blocked_, ThreadCtx::ready_, Rob::chunks_, Ring: checked, clean.
