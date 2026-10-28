// Shared executor body. Included in the ordinary and exact-timed templates
// so ordinary callback symbol ownership and inlining match the original API.
        Server::ClientWorkScope client_work(*srv_, self_->id());
        // Forwarding, rather than a request epoch, resolves the route-read/enqueue race.  This check
        // must precede every shard dereference, including tagged MULTI and ownerless cleanup tasks.
        if (forward_stale_task<IofusedPrivateQueue>(t)) return true;
        if (multi_task_tagged(t)) {
            Shard& shard = srv_->shard(t.shard);
            shard.set_cached_now_ms(cached_now_ms_, cached_lru_clock_);
            // PROGRAM ORDER: a transaction fragment must not run past an older same-connection
            // task parked in atomic_deferred_/xshard_retries_ on this shard. This branch used to
            // skip the check entirely, so a pipelined EXEC's child executed before the
            // connection's earlier cross-shard DEL fragment that was deferred here, and the
            // transaction read the pre-DEL world (the seed-19 differ divergence). An ownerless
            // teardown fragment (null client, the WATCH-disconnect path) belongs to no
            // connection and carries no program order -- and has no ROB to consult.
            if (t.client) {
                Op& carrier = t.client->rob().at(t.op_id);
                if (has_parked_predecessor(t, carrier, t.shard)) {
                    atomic_deferred_.push_back(t);
                    return true;
                }
                // PROGRAM ORDER, THE OTHER HALF: an older same-connection cross-shard unit that
                // has already INSTALLED here but has not yet DECIDED. Nothing is parked, so the
                // check above cannot see it, yet its physically installed candidate may still be
                // withdrawn -- MSETNX under --atomic 1 installs first and only then discovers an
                // existing key on another owner, and any group can still fail on OOM/maxmemory.
                // A transaction fragment reads through the store's own-connection RYOW overlay
                // (atomic_resolve_internal's own_private arm), which is keyed on the CONNECTION
                // and therefore also exposes that other unit's undecided candidate. Running here
                // let an EXEC clone a value that was never committed and install it as its own
                // candidate, which then committed with a real ticket: a withdrawn MSETNX value
                // laundered into an acknowledged transaction write, visible to every connection
                // and permanent (tests/multirace.py).
                // Deferring here rather than in prepare_write_key() is what makes it safe. This
                // fragment has installed nothing yet on this owner, so parking it cannot hold a
                // half-applied command; and the predecessor can never wait on it, because on
                // every shard the older unit's fragment is drained first and, if it is itself
                // parked, parked_predecessor_in() holds this younger fragment behind it. Putting
                // the hold in prepare_write_key() deadlocked: the transaction held partial
                // installs while waiting on an older group whose order-blind key probe then
                // waited on those installs.
                if (__builtin_expect(shard.store().atomic_has_records(), false) &&
                    shard.store().atomic_has_foreign_unit_undecided(
                        t.client->id(),
                        [&t](const void* epoch) { return multi_task_owns_epoch(t, epoch); })) {
                    shard.stats().atomic_exec_order_holds++;
                    atomic_deferred_.push_back(t);
                    return true;
                }
            }
            // The no-touch answer is PER TASK; a MULTI body inherits the transaction owner's.
            if (__builtin_expect(maxmemory_enabled_, false)) {
                const bool no_touch = t.client && t.client->rob().at(t.op_id).no_touch();
                shard.set_no_touch(no_touch);
                if (no_touch) srv_->climon_note_no_touch();
            }
            const MultiTaskResult result = finish_multi_store(shard, execute_multi_unit(t, shard,
                [](void* loop, MultiOwnerRetryNode& next) {
                    static_cast<ExLoopT*>(loop)->promote_multi_retry(next);
                }));
            if (result == MultiTaskResult::RetrySoon) {
                queue_fast_multi_retry(t);
                return true;
            }
            if (result == MultiTaskResult::Retry) {
                queue_multi_retry(t);
                return true;
            }
            if (result == MultiTaskResult::Final) {
                Op& public_op = t.client->rob().at(t.op_id);
                if constexpr (Timed) slowlog_complete(public_op);
                if (aof_manager_ &&
                    aof_manager_->defer_completion(self_->id(), public_op, t.client)) return true;
                public_op.state.store(OpState::Done, std::memory_order_release);
                notify_sender(t.client);
            }
            return true;
        }
        if (!t.client) {
            Shard& cleanup = srv_->shard(t.shard);
            cleanup.set_cached_now_ms(cached_now_ms_, cached_lru_clock_);
            // An ownerless cleanup pass belongs to no connection: clear the per-task no-touch
            // answer so a NO-TOUCH client cannot leave it armed for whatever runs next.
            if (__builtin_expect(maxmemory_enabled_, false)) cleanup.set_no_touch(false);
            xshard_cleanup_shard(*srv_, cleanup, 32);
            cleanup.publish_size();
            return true;
        }
        Op& op = t.client->rob().at(t.op_id);
        const int32_t shard_id = t.shard >= 0 ? t.shard : op.shard;
        Shard& sh = srv_->shard(shard_id);
        if constexpr (Fused && !ReadLocalNoEvict) {
            if (__builtin_expect(
                    maxmemory_enabled_ && read_local_enabled() &&
                    op.read_local_precise_write() &&
                    sh.store().maxmemory_policy() != MaxmemoryPolicy::NoEviction,
                    false)) {
                ReadLocalPreciseWriteGuard no_evict(sh.store());
                if constexpr (LatencyTracking)
                    return execute_latency<IofusedPrivateQueue, true>(t);
                else if constexpr (Timed)
                    return execute_timed<IofusedPrivateQueue, true>(t);
                else
                    return execute<IofusedPrivateQueue, true>(t);
            }
        }
        sh.set_cached_now_ms(cached_now_ms_, cached_lru_clock_);
        // CLIENT NO-TOUCH. maxmemory_enabled_ is this loop's own per-pass value, so with the
        // default (maxmemory off) this is one predicted-not-taken test on a register -- and the
        // read path in FlatStore never loads the byte at all, because its && short-circuits.
        if (__builtin_expect(maxmemory_enabled_, false)) {
            const bool no_touch = op.no_touch();
            sh.set_no_touch(no_touch);
            if (no_touch) srv_->climon_note_no_touch();
        }
        if (op.has_blocking_state()) {
            sh.note_execution(self_->domain());
            note_lb_hash(sh, op.hash);
            if constexpr (IofusedPrivateQueue) {
                static_assert(Fused);
                return blocking_execute_iofused(*srv_, *self_, ring_, t, sh, op);
            } else {
                return blocking_execute(*srv_, *self_, ring_, t, sh, op);
            }
        }
        // #77 TRIPWIRE A samples before any scheduler park. The first answer is retained across
        // retries; the debug registry qualifies begin-plain transitions when execution arrives.
        if (__builtin_expect(atomic_tripwire_enabled(), false))
            xshard_tripwire_fragment_begin(t, sh, op);
        // The helper's plain/no-hazard arm is an immediate false. Keep that
        // predicate here so ordinary commands do not enter its scatter frame.
        // A WATCH-blocked writer acquires the hazard bit below before retry;
        // scatter tasks still enter even without it (including debug holds).
        // Pin the compact exact-timed fused body's no-hazard fallthrough.
        if (has_parked_predecessor(t, op, shard_id) ||
            ((Timed && Fused
                ? __builtin_expect(t.scatter || op.atomic_hazard(), false)
                : (t.scatter || op.atomic_hazard())) &&
             xshard_task_should_defer(*srv_, sh, t, op))) {
            atomic_deferred_.push_back(t);
            return true;
        }
        if (!t.scatter && (op.spec->flags & (CmdFlags::Write | CmdFlags::SnapshotWrite)) &&
            __builtin_expect(sh.has_watches(), false) && !multi_plain_write_ready(sh, op))
            return false;
        // Records the op AND whether it was executed from this shard's home L3 domain. One compare
        // and one increment, no atomics — the shard has a single owner.
        sh.note_execution(self_->domain());

        if (!t.scatter) self_->note_command(op.spec->id);
        if (__builtin_expect(srv_->climon_armed() & Server::kClimonTracking, false))
            tracking_observe_read(sh, op);

        if (t.scatter) {
            const ScatterTaskResult result = [&] {
                if constexpr (LatencyTracking) return sh.has_watches()
                    ? latency_watch_execute(t, sh, op, self_->id())
                    : latency_xshard_execute(t, sh, op, self_->id());
                else return sh.has_watches()
                    ? watch_execute_scatter(t, sh, op, self_->id())
                    : xshard_execute(t, sh, op, self_->id());
            }();
            if (result == ScatterTaskResult::Defer) {
                atomic_deferred_.push_back(t);
                return true;
            }
            if (result == ScatterTaskResult::Retry) return false;
            if (lb_sample_rate_) {
                struct LbVisit { ExLoopT* loop; Shard* shard; } visit{this, &sh};
                xshard_visit_task_hashes(t, &visit, [](void* context, uint64_t hash) {
                    auto* visit = static_cast<LbVisit*>(context);
                    visit->loop->note_lb_hash(*visit->shard, hash);
                });
            }
            if (__builtin_expect(sh.has_blocking_waiters(), false))
                blocking_scatter_mutation_published(t, sh, op);
            if (__builtin_expect(aof_manager_ != nullptr, false)) {
                AofOwnerContext context{self_->id(), &ring_, &self_->sig()};
                xshard_aof_emit(t, sh, op, context);
            }
            sh.publish_size();
            const ScatterFinish finished = [&] {
                if constexpr (IofusedPrivateQueue) {
                    static_assert(Fused);
                    return xshard_complete_iofused(*srv_, *self_, ring_, t, op);
                } else {
                    return xshard_complete(*srv_, *self_, ring_, t, op);
                }
            }();
            if (finished == ScatterFinish::Waiting) return true;
            if (finished == ScatterFinish::Retry) return false;
            if (finished == ScatterFinish::CommitQueued) {
                xshard_queue_commit(*srv_, *self_, t);
                xshard_commit_pending_ = true;
                return true;
            }
        } else if (__builtin_expect(op.spec->flags & CmdFlags::DenyOom, false) &&
                   !sh.store().budget_admit(op.arg(static_cast<uint32_t>(op.spec->first_key)))) {
            // Growth gate (wrinkle fix 2026-08-25): collection growth mutates behind a stable
            // KvObj and never crosses insert-admission, so an HSET-only workload could blow
            // through maxmemory unbounded. One predicted-false flag test per op when disabled.
            // Scatter tasks bypass it -- their writes replace whole objects through insert-level
            // admission in their owner pass.
            reply_maxmemory_oom(op);
            if constexpr (Fused) l4prebuild_discard_set(op);
        } else {
            // A null pending-entry list is the sole common-path branch. With no cross-shard window,
            // handlers take their original path with no epoch loads, allocations, or cleanup work.
            const bool scoped_foreign_write = read_local_enabled() &&
                (op.spec->flags & (CmdFlags::Write | CmdFlags::SnapshotWrite)) &&
                (op.local_xshard() || (op.spec->flags & CmdFlags::ScriptRoute));
            if (__builtin_expect(
                    sh.store().atomic_has_records() || scoped_foreign_write, false)) {
                PlainForeignReadScope foreign_scope;
                const bool execute_handler = xshard_plain_prepare(
                    *srv_, sh, op, t.client->id(), foreign_scope);
                const bool defer_blocking =
                    __builtin_expect(sh.has_blocking_waiters(), false);
                if (defer_blocking) blocking_defer_plain_publication(true);
                if (execute_handler) {
                    if (__builtin_expect(sh.has_watches(), false)) watch_execute_handler(sh, op);
                    else op.spec->handler(sh, op);
                }
                else if constexpr (Fused) l4prebuild_discard_set(op);
                xshard_plain_finish(sh, foreign_scope);
                if (defer_blocking) {
                    blocking_defer_plain_publication(false);
                    if (execute_handler) blocking_plain_mutation_published(sh, op);
                }
            } else {
                if (__builtin_expect(sh.has_watches(), false)) watch_execute_handler(sh, op);
                else op.spec->handler(sh, op);
            }
        }
        if (!t.scatter) note_lb_hash(sh, op.hash);
        if (!t.scatter && __builtin_expect(aof_manager_ != nullptr, false)) {
            AofOwnerContext context{self_->id(), &ring_, &self_->sig()};
            if (op.local_xshard()) xshard_aof_emit_local(sh, op, context);
            else                   aof_record_local_op(sh, op, context);
        }

        if (__builtin_expect(op.spec->flags & CmdFlags::NotifySelected, false))
            notify_tracking_commit(op);

        if constexpr (Timed) slowlog_complete(op);

        // The optional persistence path owns Done until this pass's post and durability
        // boundary. Merely delaying notify_sender cannot protect an IO already serving.
        if (__builtin_expect(aof_manager_ != nullptr, false) &&
            aof_manager_->defer_completion(self_->id(), op, t.client)) return true;

        // Release pairs with the IO thread's acquire on Done: everything the handler wrote into
        // op.reply becomes visible through this one store.
        op.state.store(OpState::Done, std::memory_order_release);
#ifdef TOMO_CORE_CONCURRENCY_TEST
        if (test_after_done_) test_after_done_(t.client);
#endif

        // Notify the connection's io thread; the claim flag dedupes a burst into one post.
        // EXECUTOR-ISSUED SENDS ARE A CLOSED DOOR: the exwb mode (executor
        // sends its own completed prefix) was built, measured #1 in zero cells across every size
        // and pipe depth, and deleted 2026-08-24 -- send work rides the scarce ex role, nearly
        // free at p1 and ruinous at p32. Flush-at-head-from-ex was separately built twice and
        // reverted twice before that (fixed sender 8.1-8.5M get_p32 vs 4.1-4.7M with wedges).
        notify_sender(t.client);
        return true;
