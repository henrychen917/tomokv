// Owns read-local admission and RYOW classification inside IoLoop::parse_and_dispatch
// in io_loop.h and the R7 parser in reorder.cc. It shares each enclosing parser's locals;
// there is no include guard because both template bodies instantiate these statements.
// Only the connection's IO owner enters, after arity checks and database-map stamping.
// Build reservations before stateful hooks; publication belongs to the enclosing parser.
// Retry exits leave the current frame unconsumed. Full local lanes defer reads; explicit
// key conflicts and conservative routes use the owner/demotion protocol.
if constexpr (Fused) {
    if (read_local_enabled) {
        // Phase 1: classify the command and its older owner-route conflicts.
        constexpr uint32_t kWriteHazards = CmdFlags::Write | CmdFlags::SnapshotWrite |
                                           CmdFlags::Transaction | CmdFlags::ScriptRoute;
        constexpr uint32_t kNonPointRoutes = CmdFlags::AllShards | CmdFlags::RandomShard |
                                             CmdFlags::CursorShard | CmdFlags::ConfigRoute |
                                             CmdFlags::MultiShard | CmdFlags::ScriptRoute |
                                             CmdFlags::Blocking | CmdFlags::Transaction |
                                             CmdFlags::StreamRoute | CmdFlags::SubcmdRoute;
        constexpr uint32_t kReplaySensitiveClimon =
            Server::kClimonMonitor | Server::kClimonTracking | Server::kClimonReply;
        const bool write_hazard = (spec->flags & kWriteHazards) != 0;
        read_local_write_hazard = write_hazard;
        const bool point_route = (spec->flags & kNonPointRoutes) == 0 && spec->first_key > 0 &&
                                 spec->last_key == spec->first_key && spec->key_step == 1;
        if (point_route) {
            op->hash = FlatStore::hash_key(op->arg(static_cast<uint32_t>(spec->first_key)));
            op->shard = srv_->router().shard_of(op->hash);
            read_local_point_prehashed = true;
        }
        auto classify_owner_conflict = [&](auto&& overlaps) {
            bool broad = false;
            const bool conflict =
                rob.read_local_owner_conflicts_before(rob.dispatch_id(), [&](const Op& owner) {
                    if (!overlaps(owner)) return false;
                    broad |= !read_local_owner_command_is_precise(owner);
                    return true;
                });
            return !conflict ? ReadLocalFallbackReason::None
                   : broad   ? ReadLocalFallbackReason::ContextRoute
                             : ReadLocalFallbackReason::ContextOwnerKey;
        };
        auto owner_conflict_for_hash = [&](uint64_t hash) {
            return classify_owner_conflict([&](const Op& owner) {
                return read_local_owner_command_touches_hash(owner, hash);
            });
        };
        auto owner_conflict_for_command = [&]() {
            return classify_owner_conflict(
                [&](const Op& owner) { return read_local_commands_overlap(*op, owner); });
        };

        // Phase 2: stage write hazards and reserve any conflicting read demotion.
        if (write_hazard) {
            // Stage write hazards before the stateful climon gate. Arity validation allows a
            // one-key owner route or blind MSET keyset to refine the conservative write marker;
            // other multi-key writes remain conservative.
            rob.mark_current_write();
            const bool ordinary_point_write =
                point_route && (spec->flags & (CmdFlags::Write | CmdFlags::SnapshotWrite)) != 0 &&
                !(spec->flags & CmdFlags::ConnLocal);
            if (ordinary_point_write) {
                if (climon_armed_cached_ & kReplaySensitiveClimon) {
                    read_local_owner_conflict_reason = owner_conflict_for_hash(op->hash);
                    read_local_owner_conflict =
                        read_local_owner_conflict_reason != ReadLocalFallbackReason::None;
                }
                const bool reserve_owner_fenced_current =
                    read_local_owner_conflict &&
                    (climon_armed_cached_ & kReplaySensitiveClimon) != 0;
                // An evicting maxmemory policy can mutate unnamed keys, so its write remains
                // conservative even on a one-owner route. Reserve the current append with the demoted
                // reads to make the post-climon commit infallible.
                //
                // Key precision and write-ring capacity are distinct: with eviction off, a point write
                // touches only op->hash even if the ring cannot record another hash for later reads.
                // Select older pending reads by key overlap; a full RYOW ring must not turn that
                // selection into a demotion of unrelated reads. refine_current_write_hash separately
                // records whether later reads can use a precise descriptor.
                const bool point_write_exact = fused_executor_->read_local_point_writes_precise();
                // Still gated: with an evicting policy the write may touch keys it
                // never names, so it must stay a conservative ring generation and no
                // later read may be cleared against its hash alone.
                if (point_write_exact) {
                    (void)rob.refine_current_write_hash(op->hash);
                    op->mark_read_local_precise_write();
                }
                // A demotion plan is needed only to reserve the current owner append or to move a
                // possibly overlapping pending local read. Otherwise prepare() returns with loop_ null
                // and commit_reads() has no work. These predicates match prepare()'s early exits for
                // this point-write call (no intersect command or fallback seeds), avoiding its cold
                // allocation/reservation path when the pending-key filter proves absence.
                const bool needs_demotion_plan =
                    (reserve_owner_fenced_current && op->shard >= 0) ||
                    (rob.has_pending_read_local() &&
                     (!point_write_exact || rob.read_local_pending_may_touch(op->hash)));
                if (needs_demotion_plan &&
                    !read_local_demotion.prepare(*this, c, op->hash, point_write_exact, op->shard,
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
                            pending_filter_hit = rob.read_local_pending_may_touch(hash);
                    }
                    intersect_filter_miss = !pending_reads || !pending_filter_hit;
                }
                const bool keyset_precise = rob.refine_current_write_keyset(filter, key_count);
                if (keyset_precise) op->mark_read_local_precise_write();
                if (!read_local_demotion.prepare(*this, c, 0, false, -1,
                                                 ReadLocalFallbackReason::InflightWrite, false,
                                                 nullptr, nullptr, 0, keyset_precise ? op : nullptr,
                                                 keyset_precise && intersect_filter_miss))
                    break;
                read_local_commit_before_lowering = true;
            } else if (!read_local_demotion.prepare(*this, c, 0, false, -1,
                                                    ReadLocalFallbackReason::InflightWrite)) {
                break;
            } else {
                read_local_commit_before_lowering = true;
            }
        } else if ((spec->flags & CmdFlags::ReadLocalEligible) != 0) {
            // Phase 3: evaluate local-read safety and capacity before admitting this read.
            const bool mget = command_is_read_local_mget(*spec);
            read_local_mget_candidate = mget;
            // MGET owns a one-command latest-read boundary in both outcomes: local
            // success publishes its freshly copied vector, while demotion resolves the
            // whole command at this pass's pinned cut. Do not let an older local GET
            // from the same pass complete at a newer world and then follow it with an
            // MGET fallback at the older cut. Leave this frame unconsumed; after the
            // local lane resolves, reparsing samples a fresh pass cut.
            if (mget) {
                if (rob.has_pending_read_local()) break;
                op->hash = FlatStore::hash_key(op->arg(1));
                op->shard = srv_->router().shard_of(op->hash);
                read_local_point_prehashed = true;
                read_local_lane_demand = std::min<uint32_t>(op->argc() - 1, srv_->nshards());
            } else if (!point_route)
                std::abort();
            read_local_owner_conflict_reason = owner_conflict_for_command();
            read_local_owner_conflict =
                read_local_owner_conflict_reason != ReadLocalFallbackReason::None;
            bool write_conflict = false;
            bool mget_atomic_pending = false;
            if (mget) {
                // Sample the pending-key filter here: an open group can outlive the parse-to-execute
                // gap. Leave the transient table-mutation check to the executor's probe/validation,
                // which observes the store when the read is actually attempted.
                for (uint32_t arg = 1; arg < op->argc(); arg++) {
                    const uint64_t hash = arg == 1 ? op->hash : FlatStore::hash_key(op->arg(arg));
                    const int32_t shard = arg == 1 ? op->shard : srv_->router().shard_of(hash);
                    read_local_pending_keys.add(hash);
                    write_conflict |=
                        rob.read_local_write_conflicts(hash, read_local_command_touches_hash);
                    mget_atomic_pending |= srv_->shard(shard).store().foreign_read_key_unsafe(hash);
                }
            } else {
                write_conflict =
                    rob.read_local_write_conflicts(op->hash, read_local_command_touches_hash);
            }
            if (extend_read_local_batch) {
                read_local_eligible = !write_conflict && !read_local_owner_conflict;
                if (!read_local_eligible) {
                    read_local_fallback_reason = write_conflict
                                                     ? read_local_write_fallback_reason(rob)
                                                     : read_local_owner_conflict_reason;
                    read_local_batch = false;
                }
            } else {
                read_local_eligible = true;
                if (slowlog_arm_.latency_tracking) {
                    // Timing requires owner execution, but this read still participates
                    // in the boot-latched session-ordering protocol. In particular its
                    // owner slot must survive a later switch back to local execution.
                    read_local_fallback_reason = ReadLocalFallbackReason::ContextRoute;
                    read_local_eligible = false;
                } else if (multi_session_watch_size(conn) != 0) {
                    read_local_fallback_reason = ReadLocalFallbackReason::Watch;
                    read_local_eligible = false;
                } else if (c->blocked() || c->subscriber_mode()) {
                    read_local_fallback_reason = ReadLocalFallbackReason::ContextConnectionState;
                    read_local_eligible = false;
                } else if (op->has_scatter_state() ||
                           (spec->flags & (CmdFlags::ScriptRoute | CmdFlags::AllShards)) ||
                           (!mget && (spec->flags & CmdFlags::MultiShard))) {
                    read_local_fallback_reason = ReadLocalFallbackReason::ContextRoute;
                    read_local_eligible = false;
                } else if (write_conflict) {
                    read_local_fallback_reason = read_local_write_fallback_reason(rob);
                    read_local_eligible = false;
                } else if (read_local_owner_conflict) {
                    read_local_fallback_reason = read_local_owner_conflict_reason;
                    read_local_eligible = false;
                } else if (mget && fused_executor_->read_local_keymiss_notify_armed()) {
                    // A notify-aware owner lookup can emit keymiss. Local MGET serves
                    // stable misses as nil, so keep the whole command on the
                    // owner/scatter path while key-miss notifications are configured.
                    read_local_fallback_reason = ReadLocalFallbackReason::ContextKeymissNotify;
                    read_local_eligible = false;
                } else {
                    bool atomic_pending = mget_atomic_pending;
                    bool seq_churn = false;
                    if (!mget) {
                        const uint64_t state =
                            srv_->shard(op->shard).store().read_local_state_acquire();
                        atomic_pending =
                            srv_->shard(op->shard).store().foreign_read_key_unsafe(state, op->hash);
                        seq_churn = !FlatStore::read_local_state_eligible(state);
                    }
                    if (atomic_pending) {
                        read_local_fallback_reason = ReadLocalFallbackReason::AtomicPending;
                        read_local_eligible = false;
                    } else if (seq_churn) {
                        read_local_fallback_reason = ReadLocalFallbackReason::SeqChurn;
                        read_local_eligible = false;
                    } else if (rob.pending_read_local_count() >= read_local_quota) {
                        // Fair-share admission: defer when this connection already holds its quota under
                        // lane pressure. Quota deferrals must not rearm the pressure window: feeding the
                        // actuator's own deferrals back into its signal would sustain pressure indefinitely.
                        // Only an actual full-lane refusal rearms it; pressure must be observed again within
                        // kReadLocalLanePressureRotations rotations.
                        self_->read_local_stats().defer_quota++;
                        break;
                    } else if (!fused_executor_->local_read_lane_has_room(read_local_lane_demand)) {
                        // A full local lane defers this frame without demoting it. Its ROB slot is acquired
                        // but unpublished; no lane entry, pending bit, or owner task exists yet. Leave bytes at
                        // rpos and return Progress so active_ retries after a local-lane drain in either O1 mode.
                        // Demoting on capacity pressure can create a feedback loop: remote owner tasks delay
                        // the receiving thread's lane drain, leaving less room and causing more demotions.
                        // The deferral instead arms the pressure window so the next rotation shares capacity
                        // among connections rather than repeatedly refusing the last ones parsed.
                        self_->read_local_stats().defer_lane_full++;
                        fused_executor_->note_local_read_lane_full();
                        break;
                    }
                }
            }
            read_local_eligible_decided = true;
            if (!read_local_eligible) {
                if (read_local_fallback_reason == ReadLocalFallbackReason::None) std::abort();
                // Keep the owner-routed read visible only to younger overlapping keys.
                // Disjoint reads may execute locally; ROB retirement orders replies.
                rob.extend_current_read_local_owner();
                if (mget) {
                    // The MGET admission fence above reparses instead of reaching here
                    // with any older pending local read, so the intersect set is empty.
                    if (!read_local_demotion.prepare(*this, c, 0, false, -1,
                                                     ReadLocalFallbackReason::ContextOwnerKey,
                                                     false, nullptr, nullptr, 0, op, true))
                        break;
                    read_local_commit_before_lowering = true;
                } else {
                    const bool reserve_owner_fenced_current =
                        read_local_owner_conflict &&
                        (climon_armed_cached_ & kReplaySensitiveClimon) != 0;
                    if (!read_local_demotion.prepare(*this, c, op->hash, true, op->shard,
                                                     ReadLocalFallbackReason::ContextOwnerKey,
                                                     reserve_owner_fenced_current))
                        break;
                    read_local_commit_at_ordinary = true;
                }
            }
        } else if (!(spec->flags & CmdFlags::ConnLocal)) {
            read_local_owner_conflict_reason =
                point_route ? owner_conflict_for_hash(op->hash)
                            : classify_owner_conflict([](const Op&) { return true; });
            read_local_owner_conflict =
                read_local_owner_conflict_reason != ReadLocalFallbackReason::None;
            // Phase 4: preserve owner-route ordering for other read commands.
            // Every owner read is an ordering predecessor, even without an older
            // conflict or a pending local read to demote. Otherwise a younger GET
            // can run first and return an older value. The owner-slot overlap check
            // remains precise for point routes and conservative for broad routes.
            rob.extend_current_read_local_owner();
            const bool reserve_owner_fenced_current =
                read_local_owner_conflict && point_route &&
                (climon_armed_cached_ & kReplaySensitiveClimon) != 0;
            if (!read_local_demotion.prepare(*this, c, point_route ? op->hash : 0, point_route,
                                             point_route ? op->shard : -1,
                                             point_route ? ReadLocalFallbackReason::ContextOwnerKey
                                                         : ReadLocalFallbackReason::ContextRoute,
                                             reserve_owner_fenced_current))
                break;
            if (point_route)
                read_local_commit_at_ordinary = true;
            else
                read_local_commit_before_lowering = true;
        }
    }
}
