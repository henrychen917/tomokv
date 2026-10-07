// Shared read-local parse/RYOW classification. Included inside both ordinary and R7
// parse_and_dispatch template bodies, preserving their scopes, locals and lambda identities.
// No include guard: each parser instantiates this same source in its own context.
            if constexpr (Fused) {
                if (read_local_enabled) {
                    constexpr uint32_t kWriteHazards =
                        CmdFlags::Write | CmdFlags::SnapshotWrite |
                        CmdFlags::Transaction | CmdFlags::ScriptRoute;
                    constexpr uint32_t kNonPointRoutes =
                        CmdFlags::AllShards | CmdFlags::RandomShard |
                        CmdFlags::CursorShard | CmdFlags::ConfigRoute |
                        CmdFlags::MultiShard | CmdFlags::ScriptRoute |
                        CmdFlags::Blocking | CmdFlags::Transaction |
                        CmdFlags::StreamRoute | CmdFlags::SubcmdRoute;
                    constexpr uint32_t kReplaySensitiveClimon =
                        Server::kClimonMonitor | Server::kClimonTracking |
                        Server::kClimonReply;
                    const bool write_hazard = (spec->flags & kWriteHazards) != 0;
                    read_local_write_hazard = write_hazard;
                    const bool point_route =
                        (spec->flags & kNonPointRoutes) == 0 &&
                        spec->first_key > 0 && spec->last_key == spec->first_key &&
                        spec->key_step == 1;
                    if (point_route) {
                        op->hash = FlatStore::hash_key(
                            op->arg(static_cast<uint32_t>(spec->first_key)));
                        op->shard = srv_->router().shard_of(op->hash);
                        read_local_point_prehashed = true;
                    }
                    auto classify_owner_conflict = [&](auto&& overlaps) {
                        bool broad = false;
                        const bool conflict = rob.read_local_owner_conflicts_before(
                            rob.dispatch_id(), [&](const Op& owner) {
                                if (!overlaps(owner)) return false;
                                broad |= !read_local_owner_command_is_precise(owner);
                                return true;
                            });
                        return !conflict ? ReadLocalFallbackReason::None
                            : broad ? ReadLocalFallbackReason::ContextRoute
                                    : ReadLocalFallbackReason::ContextOwnerKey;
                    };
                    auto owner_conflict_for_hash = [&](uint64_t hash) {
                        return classify_owner_conflict([&](const Op& owner) {
                            return read_local_owner_command_touches_hash(owner, hash);
                        });
                    };
                    auto owner_conflict_for_command = [&]() {
                        return classify_owner_conflict([&](const Op& owner) {
                            return read_local_commands_overlap(*op, owner);
                        });
                    };

                    if (write_hazard) {
                        // Stage every historical v1 hazard before the stateful climon gate. A
                        // syntactic one-key owner route or blind MSET keyset can be refined now
                        // that arity is proved. Other multi-key writes remain conservative.
                        rob.mark_current_write();
                        const bool ordinary_point_write =
                            point_route &&
                            (spec->flags & (CmdFlags::Write | CmdFlags::SnapshotWrite)) != 0 &&
                            !(spec->flags & CmdFlags::ConnLocal);
                        if (ordinary_point_write) {
                            if (climon_armed_cached_ & kReplaySensitiveClimon) {
                                read_local_owner_conflict_reason =
                                    owner_conflict_for_hash(op->hash);
                                read_local_owner_conflict = read_local_owner_conflict_reason !=
                                    ReadLocalFallbackReason::None;
                            }
                            const bool reserve_owner_fenced_current =
                                read_local_owner_conflict &&
                                (climon_armed_cached_ & kReplaySensitiveClimon) != 0;
                            // An evicting maxmemory policy makes the write conservative, but it is
                            // still an ordinary one-owner route. Reserve that current append along
                            // with the demoted reads so the post-climon sequence remains infallible.
                            //
                            // TWO DIFFERENT QUESTIONS, ONE ANSWER USED FOR BOTH UNTIL NOW.
                            // "Which keys does this write touch" is answered by the eviction
                            // policy alone: with eviction off, an ordinary point write touches
                            // op->hash and nothing else, whatever the ROB's RYOW ring can hold.
                            // "Can the ring record this hash for LATER reads to be checked
                            // against" is a capacity question, and refine_current_write_hash
                            // answers no once sixteen writes are already in flight. Conjoining
                            // them made a full ring turn every further write into a demote-EVERY-
                            // pending-read wave: at 59% writes and pipeline 32 the ring overflows
                            // permanently and every single read on the connection is lowered to
                            // the owner queue (measured: 164000 of 164000 reads, INFO
                            // read_local_fallback_inflight_write). The selection below now asks
                            // only the keys question, which is the owner's rule verbatim -- a read
                            // is held back on explicit key conflict and on nothing else. Nothing
                            // is weakened: require_hash_match=true is already what an unfilled
                            // ring passes here on every ordinary point write.
                            const bool point_write_exact =
                                fused_executor_->read_local_point_writes_precise();
                            // Still gated: with an evicting policy the write may touch keys it
                            // never names, so it must stay a conservative ring generation and no
                            // later read may be cleared against its hash alone.
                            if (point_write_exact) {
                                (void)rob.refine_current_write_hash(op->hash);
                                op->mark_read_local_precise_write();
                            }
                            // DEMOTION-PLAN GATE. prepare() returns true
                            // without building a plan -- loop_ stays null, so active() is false
                            // and commit_reads() is its `if (!loop_) return;` no-op -- unless the
                            // current append must be reserved or a still-pending local read may
                            // overlap this write. Both predicates are single inline loads that
                            // prepare() itself performs first; deciding them here skips the
                            // 12-argument out-of-line call and its abort prologue on the common
                            // disjoint / no-pending-read point write. This is the exact negation
                            // of prepare()'s two true-early-outs for this call site (no intersect
                            // command, no fallback seeds, no filter miss): behaviour identical,
                            // measured -108 instr/op and -23 cyc/op on the armed SET at 1T.
                            const bool needs_demotion_plan =
                                (reserve_owner_fenced_current && op->shard >= 0) ||
                                (rob.has_pending_read_local() &&
                                 (!point_write_exact ||
                                  rob.read_local_pending_may_touch(op->hash)));
                            if (needs_demotion_plan &&
                                !read_local_demotion.prepare(
                                    *this, c, op->hash, point_write_exact, op->shard,
                                    ReadLocalFallbackReason::InflightWrite,
                                    reserve_owner_fenced_current))
                                break;
                            read_local_commit_at_ordinary = true;
                        } else if (read_local_command_is_precise_mset(*op) &&
                                   fused_executor_->read_local_point_writes_precise()) {
                            const uint32_t key_count = (op->argc() - 1) / 2;
                            bool intersect_filter_miss = false;
                            uint64_t filter = 0;
                            if (key_count <= ReadLocalRobState::kMaxPreciseKeysetKeys) {
                                const bool pending_reads = rob.has_pending_read_local();
                                bool pending_filter_hit = false;
                                for (uint32_t arg = 1; arg < op->argc(); arg += 2) {
                                    const uint64_t hash = FlatStore::hash_key(op->arg(arg));
                                    filter |= ReadLocalRobState::keyset_filter(hash);
                                    if (pending_reads && !pending_filter_hit)
                                        pending_filter_hit =
                                            rob.read_local_pending_may_touch(hash);
                                }
                                intersect_filter_miss =
                                    !pending_reads || !pending_filter_hit;
                            }
                            const bool keyset_precise =
                                rob.refine_current_write_keyset(filter, key_count);
                            if (keyset_precise) op->mark_read_local_precise_write();
                            if (!read_local_demotion.prepare(
                                    *this, c, 0, false, -1,
                                    ReadLocalFallbackReason::InflightWrite, false,
                                    nullptr, nullptr, 0,
                                    keyset_precise ? op : nullptr,
                                    keyset_precise && intersect_filter_miss))
                                break;
                            read_local_commit_before_lowering = true;
                        } else if (!read_local_demotion.prepare(
                                       *this, c, 0, false, -1,
                                       ReadLocalFallbackReason::InflightWrite)) {
                            break;
                        } else {
                            read_local_commit_before_lowering = true;
                        }
                    } else if ((spec->flags & CmdFlags::ReadLocalEligible) != 0) {
                        const bool mget = command_is_read_local_mget(*spec);
                        read_local_mget_candidate = mget;
                        // MGET owns a one-command latest-read boundary in both outcomes: local
                        // success publishes its freshly copied vector, while demotion resolves the
                        // whole command at this pass's pinned cut. Do not let an older local GET
                        // from the same pass complete at a newer world and then follow it with an
                        // MGET fallback at the older cut. Leave this frame unconsumed; after the
                        // existing local lane resolves, reparsing samples a fresh pass cut.
                        if (mget && rob.has_pending_read_local()) break;
                        if (!mget && !point_route) std::abort();
                        if (mget) {
                            op->hash = FlatStore::hash_key(op->arg(1));
                            op->shard = srv_->router().shard_of(op->hash);
                            read_local_point_prehashed = true;
                            read_local_lane_demand =
                                std::min<uint32_t>(op->argc() - 1, srv_->nshards());
                        }
                        read_local_owner_conflict_reason = owner_conflict_for_command();
                        read_local_owner_conflict = read_local_owner_conflict_reason !=
                            ReadLocalFallbackReason::None;
                        bool write_conflict = false;
                        bool mget_atomic_pending = false;
                        if (mget) {
                            // Sample only the pending-key filter here. An open group outlives the
                            // parse-to-execute gap, so that sample predicts the executor's answer;
                            // the table-mutation bit is one ~200 ns exchange bracket that has
                            // closed long before the executor reads, and sampling it on every
                            // touched shard rejected about 11% of MGETs for nothing the executor's
                            // own probe/validate would not have caught (mget_fallback_seq_churn).
                            for (uint32_t arg = 1; arg < op->argc(); arg++) {
                                const uint64_t hash = arg == 1
                                    ? op->hash : FlatStore::hash_key(op->arg(arg));
                                const int32_t shard = arg == 1
                                    ? op->shard : srv_->router().shard_of(hash);
                                read_local_pending_keys.add(hash);
                                write_conflict |= rob.read_local_write_conflicts(
                                    hash, read_local_command_touches_hash);
                                mget_atomic_pending |=
                                    srv_->shard(shard).store().foreign_read_key_unsafe(hash);
                            }
                        } else {
                            write_conflict = rob.read_local_write_conflicts(
                                op->hash, read_local_command_touches_hash);
                        }
                        read_local_eligible = extend_read_local_batch &&
                            !write_conflict && !read_local_owner_conflict;
                        if (extend_read_local_batch &&
                            (write_conflict || read_local_owner_conflict)) {
                            read_local_fallback_reason = write_conflict
                                ? read_local_write_fallback_reason(rob)
                                : read_local_owner_conflict_reason;
                            read_local_batch = false;
                        }
                        if (!extend_read_local_batch) {
                            read_local_eligible = true;
                            if (multi_session_watch_size(conn) != 0) {
                                read_local_fallback_reason =
                                    ReadLocalFallbackReason::Watch;
                                read_local_eligible = false;
                            } else if (c->blocked() || c->subscriber_mode()) {
                                read_local_fallback_reason =
                                    ReadLocalFallbackReason::ContextConnectionState;
                                read_local_eligible = false;
                            } else if (op->has_scatter_state() ||
                                       (spec->flags &
                                        (CmdFlags::ScriptRoute | CmdFlags::AllShards)) ||
                                       (!mget && (spec->flags & CmdFlags::MultiShard))) {
                                read_local_fallback_reason =
                                    ReadLocalFallbackReason::ContextRoute;
                                read_local_eligible = false;
                            } else if (write_conflict) {
                                read_local_fallback_reason =
                                    read_local_write_fallback_reason(rob);
                                read_local_eligible = false;
                            } else if (read_local_owner_conflict) {
                                read_local_fallback_reason = read_local_owner_conflict_reason;
                                read_local_eligible = false;
                            } else if (mget &&
                                       fused_executor_->read_local_keymiss_notify_armed()) {
                                // A notify-aware owner lookup can emit keymiss. Local MGET serves
                                // stable misses as nil, so keep the whole command on the unchanged
                                // owner/scatter path while key-miss notifications are configured.
                                read_local_fallback_reason =
                                    ReadLocalFallbackReason::ContextKeymissNotify;
                                read_local_eligible = false;
                            } else {
                                bool atomic_pending = mget_atomic_pending;
                                bool seq_churn = false;
                                if (!mget) {
                                    const uint64_t state = srv_->shard(op->shard)
                                                               .store()
                                                               .read_local_state_acquire();
                                    atomic_pending =
                                        srv_->shard(op->shard)
                                            .store()
                                            .foreign_read_key_unsafe(state, op->hash);
                                    seq_churn = !FlatStore::read_local_state_eligible(state);
                                }
                                if (atomic_pending) {
                                    read_local_fallback_reason =
                                        ReadLocalFallbackReason::AtomicPending;
                                    read_local_eligible = false;
                                } else if (seq_churn) {
                                    read_local_fallback_reason =
                                        ReadLocalFallbackReason::SeqChurn;
                                    read_local_eligible = false;
                                } else if (rob.pending_read_local_count() >= read_local_quota) {
                                    // LANE ADMISSION, fair share: the lane is under
                                    // pressure and this connection already holds its share of
                                    // it. DEFER -- see the lane-full arm below for the shape.
                                    // Deliberately does NOT re-arm the pressure window: a signal
                                    // the actuator itself produces cannot police the actuator
                                    // (measured: at the lane boundary the window fed by its own
                                    // quota deferrals stayed armed forever and deferred 0.8% of
                                    // reads where the lane itself refused 0.00008%). Only a real
                                    // lane-full event arms it, so the lane proves pressure again
                                    // every kReadLocalLanePressureRotations rotations.
                                    self_->read_local_stats().defer_quota++;
                                    break;
                                } else if (!fused_executor_->local_read_lane_has_room(
                                               read_local_lane_demand)) {
                                    // LANE ADMISSION, lane full: DEFER, never demote.
                                    // Nothing about this frame has been published -- the ROB
                                    // slot is acquired but not published, no lane entry, no
                                    // pending bit, no owner slot -- so leaving the bytes at rpos
                                    // and ending the pass is the same shape as the MGET
                                    // admission fence above. The pass reports Progress, so
                                    // more_input keeps the connection in active_ and the next
                                    // flush_ready re-parses it after this thread's own EX pass
                                    // has drained the lane. The active set supplies that next
                                    // visit in both O1 modes; no separate IFID queue is needed.
                                    // The former alternative, demoting the read to its shard
                                    // owner as an ordinary task, was the seed of the p128 and
                                    // 2048-connection pure-read collapse: 7/8 of those tasks
                                    // were cross-thread, every pending owner task suppresses the
                                    // receiving thread's lane tail-drain, its lane keeps a
                                    // residue and fills sooner, and the demotions feed back. A
                                    // read whose data is right here now waits one rotation
                                    // instead. The deferral arms the pressure window, so the
                                    // next rotation divides the lane fairly (quota arm above)
                                    // instead of refusing whichever connections it parses last.
                                    self_->read_local_stats().defer_lane_full++;
                                    fused_executor_->note_local_read_lane_full();
                                    break;
                                }
                            }
                        }
                        read_local_eligible_decided = true;
                        if (!read_local_eligible) {
                            if (read_local_fallback_reason ==
                                ReadLocalFallbackReason::None) std::abort();
                            // Keep the owner-routed read visible only to younger overlapping keys.
                            // Disjoint reads may execute locally; ROB retirement orders replies.
                            rob.extend_current_read_local_owner();
                            if (mget) {
                                // The MGET admission fence above reparses instead of reaching here
                                // with any older pending local read, so the intersect set is empty.
                                if (!read_local_demotion.prepare(
                                        *this, c, 0, false, -1,
                                        ReadLocalFallbackReason::ContextOwnerKey,
                                        false, nullptr, nullptr, 0, op, true))
                                    break;
                                read_local_commit_before_lowering = true;
                            } else {
                                const bool reserve_owner_fenced_current =
                                    read_local_owner_conflict &&
                                    (climon_armed_cached_ & kReplaySensitiveClimon) != 0;
                                if (!read_local_demotion.prepare(
                                        *this, c, op->hash, true, op->shard,
                                        ReadLocalFallbackReason::ContextOwnerKey,
                                        reserve_owner_fenced_current))
                                    break;
                                read_local_commit_at_ordinary = true;
                            }
                        }
                    } else if (!(spec->flags & CmdFlags::ConnLocal)) {
                        read_local_owner_conflict_reason = point_route
                            ? owner_conflict_for_hash(op->hash)
                            : classify_owner_conflict([](const Op&) { return true; });
                        read_local_owner_conflict = read_local_owner_conflict_reason !=
                            ReadLocalFallbackReason::None;
                        if (read_local_owner_conflict)
                            rob.extend_current_read_local_owner();
                        const bool reserve_owner_fenced_current =
                            read_local_owner_conflict && point_route &&
                            (climon_armed_cached_ & kReplaySensitiveClimon) != 0;
                        if (!read_local_demotion.prepare(
                                *this, c, point_route ? op->hash : 0,
                                point_route, point_route ? op->shard : -1,
                                point_route ? ReadLocalFallbackReason::ContextOwnerKey
                                            : ReadLocalFallbackReason::ContextRoute,
                                reserve_owner_fenced_current))
                            break;
                        if (point_route) read_local_commit_at_ordinary = true;
                        else read_local_commit_before_lowering = true;
                    }
                }
            }
