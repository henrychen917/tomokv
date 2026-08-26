// blocking.inc -- owner-only FIFO waiters for blocking list and sorted-set commands.
//
// This file is textually included by xshard.cc after scatter_engine.inc, xshard_commands.inc and
// atomics_glue.inc.  That placement is intentional: resumed BLMOVE/BRPOPLPUSH operations reuse the
// existing scatter state, and atomic publication can name its exact touched-key groups without
// exporting their layout or creating a second transaction engine.

namespace tomo {

enum class BlockingKind : uint8_t {
    Blpop, Brpop, Blmove, Brpoplpush, Blmpop, Bzmpop, Bzpopmin, Bzpopmax, Xread,
};

enum class BlockingPhase : uint8_t {
    Probe, NeedRegister, Registering, Parked, NeedSelected, Claimed,
    MoveRequested, Transferred, Completed, Cancelled,
};

enum class BlockingProbe : uint8_t { Empty, Ready, WrongType };

struct BlockingKey {
    std::string key;
    uint64_t hash = 0;
    int32_t shard = -1;
    BlockingProbe probe = BlockingProbe::Empty;  // written only by this key's owner
    StreamID cursor{};
    StreamID wake_upper{};
    bool cursor_latest = false;
    bool cursor_resolved = true;
    bool wake_bounded = false;
};

struct BlockingGroup {
    int32_t shard = -1;
    std::vector<uint32_t> keys;
};

struct BlockingState {
    ~BlockingState() { notify_discard_batch(notify.exchange(nullptr)); }
    std::atomic<uint32_t> refs{1};       // the Op/scatter owner plus one per registry alias
    std::atomic<uint32_t> active_tasks{0};
    std::atomic<uint32_t> pending{0};
    std::atomic<uint32_t> candidate{UINT32_MAX};
    std::atomic<BlockingPhase> phase{BlockingPhase::Probe};
    std::atomic<bool> counted{false};
    std::atomic<bool> cancel_requested{false};
    Server* server = nullptr;
    Client* client = nullptr;
    uint64_t op_id = 0;
    int64_t deadline_ms = 0;             // zero is forever
    BlockingKind kind = BlockingKind::Blpop;
    bool pop_left = true;
    uint64_t count = 1;
    uint32_t selected = UINT32_MAX;
    uint32_t xread_first_id = 0;
    std::vector<BlockingKey> keys;
    std::vector<BlockingGroup> groups;
    std::atomic<NotifyBatch*> notify{nullptr};
};

namespace {

struct BlockingEntry {
    BlockingState* state = nullptr;
    uint32_t key_index = 0;
};

struct BlockingQueue {
    std::string key;
    uint64_t hash = 0;
    std::deque<BlockingEntry> waiters;
};

void blocking_state_retain(BlockingState* state) {
    state->refs.fetch_add(1, std::memory_order_relaxed);
}

void blocking_state_release(BlockingState* state) {
    if (state && state->refs.fetch_sub(1, std::memory_order_acq_rel) == 1) delete state;
}

bool blocking_phase_live(BlockingPhase phase) {
    return phase == BlockingPhase::Registering || phase == BlockingPhase::Parked;
}

void blocking_atomic_min(std::atomic<uint32_t>& value, uint32_t candidate) {
    uint32_t current = value.load(std::memory_order_relaxed);
    while (candidate < current &&
           !value.compare_exchange_weak(current, candidate, std::memory_order_acq_rel,
                                        std::memory_order_relaxed)) {}
}

BlockingGroup* blocking_group_for(BlockingState& state, int32_t shard) {
    for (BlockingGroup& group : state.groups) if (group.shard == shard) return &group;
    return nullptr;
}

Slice blocking_key_slice(const BlockingKey& key) {
    return Slice(key.key.data(), static_cast<uint32_t>(key.key.size()));
}

bool blocking_is_list(BlockingKind kind) {
    return kind != BlockingKind::Bzmpop && kind != BlockingKind::Bzpopmin &&
           kind != BlockingKind::Bzpopmax && kind != BlockingKind::Xread;
}

bool blocking_is_move(BlockingKind kind) {
    return kind == BlockingKind::Blmove || kind == BlockingKind::Brpoplpush;
}

bool blocking_parse_timeout(Slice input, double& seconds) {
    if (!input.n) return false;
    const char* end = input.p + input.n;
    const auto parsed = std::from_chars(input.p, end, seconds, std::chars_format::general);
    return parsed.ec == std::errc{} && parsed.ptr == end && std::isfinite(seconds);
}

bool blocking_parse_positive_count(Op& op, Slice input, uint64_t& count) {
    int64_t parsed = 0;
    if (!parse_i64(input, parsed)) {
        reply_err(op.sink(), "ERR value is not an integer or out of range");
        return false;
    }
    if (parsed < 1) {
        reply_err(op.sink(), "ERR count should be greater than 0");
        return false;
    }
    count = static_cast<uint64_t>(parsed);
    return true;
}

bool blocking_classify(Op& op, BlockingKind& kind) {
    const char* name = op.spec->name;
    if (!std::strcmp(name, "BLPOP")) kind = BlockingKind::Blpop;
    else if (!std::strcmp(name, "BRPOP")) kind = BlockingKind::Brpop;
    else if (!std::strcmp(name, "BLMOVE")) kind = BlockingKind::Blmove;
    else if (!std::strcmp(name, "BRPOPLPUSH")) kind = BlockingKind::Brpoplpush;
    else if (!std::strcmp(name, "BLMPOP")) kind = BlockingKind::Blmpop;
    else if (!std::strcmp(name, "BZMPOP")) kind = BlockingKind::Bzmpop;
    else if (!std::strcmp(name, "BZPOPMIN")) kind = BlockingKind::Bzpopmin;
    else if (!std::strcmp(name, "BZPOPMAX")) kind = BlockingKind::Bzpopmax;
    else if (!std::strcmp(name, "XREAD")) kind = BlockingKind::Xread;
    else return false;
    return true;
}

bool blocking_validate(Op& op, BlockingState& state, uint32_t& first_key,
                       uint32_t& key_count, uint32_t& timeout_arg) {
    first_key = 1;
    key_count = 0;
    timeout_arg = 0;
    state.count = 1;
    state.pop_left = true;

    switch (state.kind) {
        case BlockingKind::Blpop:
        case BlockingKind::Brpop:
        case BlockingKind::Bzpopmin:
        case BlockingKind::Bzpopmax:
            timeout_arg = op.argc() - 1;
            key_count = op.argc() - 2;
            state.pop_left = state.kind == BlockingKind::Blpop ||
                             state.kind == BlockingKind::Bzpopmin;
            break;
        case BlockingKind::Blmove:
            first_key = 1;
            key_count = 1;  // only the source blocks; destination is part of resumed LMOVE
            timeout_arg = 5;
            if (!(op.arg(3).eq_icase("left") || op.arg(3).eq_icase("right")) ||
                !(op.arg(4).eq_icase("left") || op.arg(4).eq_icase("right"))) {
                reply_syntax(op.sink());
                return false;
            }
            state.pop_left = op.arg(3).eq_icase("left");
            break;
        case BlockingKind::Brpoplpush:
            first_key = 1;
            key_count = 1;
            timeout_arg = 3;
            state.pop_left = false;
            break;
        case BlockingKind::Blmpop:
        case BlockingKind::Bzmpop: {
            int64_t parsed_keys = 0;
            if (!parse_i64(op.arg(2), parsed_keys)) {
                reply_err(op.sink(), "ERR value is not an integer or out of range");
                return false;
            }
            if (parsed_keys < 1) {
                reply_err(op.sink(), "ERR numkeys should be greater than 0");
                return false;
            }
            if (static_cast<uint64_t>(parsed_keys) > UINT32_MAX) {
                reply_syntax(op.sink());
                return false;
            }
            key_count = static_cast<uint32_t>(parsed_keys);
            first_key = 3;
            timeout_arg = 1;
            const uint64_t edge_arg64 = static_cast<uint64_t>(first_key) + key_count;
            if (edge_arg64 >= op.argc()) { reply_syntax(op.sink()); return false; }
            const uint32_t edge_arg = static_cast<uint32_t>(edge_arg64);
            if (state.kind == BlockingKind::Blmpop) {
                if (op.arg(edge_arg).eq_icase("left")) state.pop_left = true;
                else if (op.arg(edge_arg).eq_icase("right")) state.pop_left = false;
                else { reply_syntax(op.sink()); return false; }
            } else {
                if (op.arg(edge_arg).eq_icase("min")) state.pop_left = true;
                else if (op.arg(edge_arg).eq_icase("max")) state.pop_left = false;
                else { reply_syntax(op.sink()); return false; }
            }
            uint32_t tail = edge_arg + 1;
            if (tail != op.argc()) {
                if (tail + 2 != op.argc() || !op.arg(tail).eq_icase("count") ||
                    !blocking_parse_positive_count(op, op.arg(tail + 1), state.count)) {
                    if (op.reply.empty()) reply_syntax(op.sink());
                    return false;
                }
            }
            break;
        }
        case BlockingKind::Xread: {
            StreamXreadArgs parsed;
            if (!stream_parse_xread(op, parsed)) return false;
            if (!parsed.block) {
                reply_err(op.sink(), "ERR internal blocking routing error");
                return false;
            }
            first_key = parsed.first_key;
            key_count = parsed.key_count;
            state.xread_first_id = parsed.first_id;
            state.count = parsed.count;
            timeout_arg = UINT32_MAX;
            if (parsed.block_ms) {
                timespec now{};
                ::clock_gettime(CLOCK_REALTIME, &now);
                const uint64_t now_ms = static_cast<uint64_t>(now.tv_sec) * 1000 +
                                        static_cast<uint64_t>(now.tv_nsec / 1000000);
                if (parsed.block_ms > static_cast<uint64_t>(INT64_MAX) - now_ms) {
                    reply_err(op.sink(), "ERR timeout is out of range");
                    return false;
                }
                state.deadline_ms = static_cast<int64_t>(now_ms + parsed.block_ms);
            }
            break;
        }
    }

    if (!key_count || static_cast<uint64_t>(first_key) + key_count > op.argc()) {
        reply_syntax(op.sink());
        return false;
    }
    if (state.kind == BlockingKind::Xread) return true;
    double seconds = 0;
    if (!blocking_parse_timeout(op.arg(timeout_arg), seconds)) {
        reply_err(op.sink(), "ERR timeout is not a float or out of range");
        return false;
    }
    if (seconds < 0) {
        reply_err(op.sink(), "ERR timeout is negative");
        return false;
    }
    if (seconds > static_cast<double>(INT64_MAX) / 1000.0) {
        reply_err(op.sink(), "ERR timeout is out of range");
        return false;
    }
    if (seconds != 0) {
        timespec now{};
        ::clock_gettime(CLOCK_REALTIME, &now);
        const int64_t now_ms = static_cast<int64_t>(now.tv_sec) * 1000 + now.tv_nsec / 1000000;
        const int64_t delay = static_cast<int64_t>(std::ceil(seconds * 1000.0));
        if (delay > INT64_MAX - now_ms) {
            reply_err(op.sink(), "ERR timeout is out of range");
            return false;
        }
        state.deadline_ms = now_ms + delay;
    }
    return true;
}

void blocking_notify_sender(Server& server, ThreadCtx& self, Ring& ring, Client* client) {
    ThreadCtx& sender = server.thread(client->ifid_thread());
    const uint32_t slot = client->wb_slot();
    if (slot != Client::kNoWbSlot) {
        std::atomic_thread_fence(std::memory_order_seq_cst);
        if (sender.ready().set(slot)) sender.wake_if_parked(ring, self.sig());
        return;
    }
    bool expected = false;
    if (!client->retire_queued().compare_exchange_strong(
            expected, true, std::memory_order_acq_rel)) return;
    if (!sender.post_client(self.id(), client, ring, self.sig())) {
        self.sig().notify_drop++;
        client->retire_queued().store(false, std::memory_order_release);
    }
}

thread_local ThreadCtx* blocking_tls_self = nullptr;
thread_local Ring* blocking_tls_ring = nullptr;
thread_local bool blocking_tls_defer_plain = false;

void blocking_count_parked(BlockingState& state) {
    if (!state.counted.exchange(true, std::memory_order_acq_rel))
        state.server->blocking_client_parked();
}

void blocking_reply_timeout(Op& op, BlockingKind kind) {
    if (blocking_is_move(kind)) reply_nil(op.sink());
    else reply_null_array(op.sink());
}

void blocking_finish_cancelled(BlockingState& state, ThreadCtx* self, Ring* ring) {
    Op& op = state.client->rob().at(state.op_id);
    if (op.state.exchange(OpState::Done, std::memory_order_acq_rel) != OpState::Done &&
        self && ring)
        blocking_notify_sender(*state.server, *self, *ring, state.client);
}

void blocking_task_done(BlockingState& state, ThreadCtx& self, Ring& ring) {
    if (state.active_tasks.fetch_sub(1, std::memory_order_acq_rel) != 1) return;
    BlockingPhase phase = state.phase.load(std::memory_order_acquire);
    if (state.cancel_requested.load(std::memory_order_acquire)) {
        state.phase.store(BlockingPhase::Cancelled, std::memory_order_release);
        phase = BlockingPhase::Cancelled;
    }
    if (phase == BlockingPhase::Cancelled) {
        blocking_finish_cancelled(state, &self, &ring);
    } else if (phase == BlockingPhase::Completed) {
        Op& op = state.client->rob().at(state.op_id);
        if (op.state.exchange(OpState::Done, std::memory_order_acq_rel) != OpState::Done)
            blocking_notify_sender(*state.server, self, ring, state.client);
    }
}

BlockingProbe blocking_probe_key(Shard& shard, const BlockingState& state,
                                 BlockingKey& key) {
    KvObj* object = shard.notify_carrier()
        ? shard.store_find<true>(key.hash, blocking_key_slice(key))
        : shard.store().find(key.hash, blocking_key_slice(key));
    if (!object) {
        if (state.kind == BlockingKind::Xread && key.cursor_latest && !key.cursor_resolved) {
            key.cursor = {};
            key.cursor_resolved = true;
        }
        return BlockingProbe::Empty;
    }
    const Type wanted = state.kind == BlockingKind::Xread ? Type::Stream :
                        blocking_is_list(state.kind) ? Type::List : Type::Zset;
    if (static_cast<Type>(object->type) != wanted) return BlockingProbe::WrongType;
    if (state.kind == BlockingKind::Xread) {
        if (key.cursor_latest && !key.cursor_resolved) {
            if (!stream_object_last_id(object, key.cursor)) return BlockingProbe::WrongType;
            key.cursor_resolved = true;
        }
        if (!stream_object_has_live_after(object, key.cursor)) return BlockingProbe::Empty;
        // Freeze this key at the owner-side readiness observation. Re-entry is asynchronous: a
        // pipelined second XADD may execute before the scatter rerun, but Redis wakes the waiter
        // for the first publication rather than widening that already-claimed reply.
        if (!stream_object_last_id(object, key.wake_upper)) return BlockingProbe::WrongType;
        key.wake_bounded = true;
        return BlockingProbe::Ready;
    }
    return CollectionRef(object).entries() ? BlockingProbe::Ready : BlockingProbe::Empty;
}

// Not-ready queue policy. FIFO kinds (lists, zsets) BLOCK: the front waiter owns the next push,
// and a later waiter must not jump it. Stream waiters (XREAD BLOCK, later) are SKIPPED: each
// waits on its own cursor into the same collection, so "not ready" is a property of the waiter,
// not the key, and a stalled cursor must not strand an already-satisfiable waiter behind it.
bool blocking_skip_when_not_ready(BlockingKind kind) {
    return kind == BlockingKind::Xread;
}

bool blocking_pick(const BlockingState& state, uint32_t& selected, bool& wrong_type) {
    selected = UINT32_MAX;
    wrong_type = false;
    for (uint32_t i = 0; i < state.keys.size(); i++) {
        if (state.keys[i].probe == BlockingProbe::WrongType) {
            wrong_type = true;
            return true;
        }
        if (state.keys[i].probe == BlockingProbe::Ready) {
            selected = i;
            return true;
        }
    }
    return false;
}

bool blocking_post_groups(BlockingState& state, ThreadCtx& self, Ring& ring,
                          BlockingPhase phase) {
    uint32_t needed[kMaxThreads] = {};
    uint32_t participants[kMaxThreads];
    uint32_t nparticipants = 0;
    for (const BlockingGroup& group : state.groups) {
        const uint32_t owner = state.server->worker_of_shard(group.shard);
        if (needed[owner]++ == 0) participants[nparticipants++] = owner;
    }
    for (uint32_t i = 0; i < nparticipants; i++) {
        const uint32_t owner = participants[i];
        if (state.server->thread(owner).task_free_slots(self.id()) < needed[owner]) return false;
    }

    state.pending.store(static_cast<uint32_t>(state.groups.size()), std::memory_order_relaxed);
    state.active_tasks.fetch_add(static_cast<uint32_t>(state.groups.size()),
                                 std::memory_order_relaxed);
    state.phase.store(phase, std::memory_order_release);
    for (const BlockingGroup& group : state.groups) {
        const uint32_t owner_id = state.server->worker_of_shard(group.shard);
        ThreadCtx& owner = state.server->thread(owner_id);
        const Task task{state.client, state.op_id, group.shard,
                        reinterpret_cast<ScatterState*>(&state)};
        if (!owner.post_task_quiet(self.id(), task, self.sig())) std::abort();
    }
    for (uint32_t i = 0; i < nparticipants; i++) {
        ThreadCtx& owner = state.server->thread(participants[i]);
        owner.flush_task_notify(self.id(), ring, self.sig());
    }
    return true;
}

bool blocking_post_selected(BlockingState& state, ThreadCtx& self, Ring& ring) {
    const int32_t shard = state.keys[state.selected].shard;
    ThreadCtx& owner = state.server->thread(state.server->worker_of_shard(shard));
    if (owner.task_free_slots(self.id()) == 0) return false;
    state.active_tasks.fetch_add(1, std::memory_order_relaxed);
    state.phase.store(BlockingPhase::Claimed, std::memory_order_release);
    const Task task{state.client, state.op_id, shard, reinterpret_cast<ScatterState*>(&state)};
    if (!owner.post_task_quiet(self.id(), task, self.sig())) std::abort();
    owner.flush_task_notify(self.id(), ring, self.sig());
    return true;
}

void blocking_request_move(BlockingState& state, ThreadCtx& self, Ring& ring) {
    state.phase.store(BlockingPhase::MoveRequested, std::memory_order_release);
    blocking_notify_sender(*state.server, self, ring, state.client);
}

void blocking_publish_completion(BlockingState& state, ThreadCtx& self, Ring& ring) {
    state.phase.store(BlockingPhase::Completed, std::memory_order_release);
    // Probe/registration barriers count Tasks separately from their pending phase. The owner that
    // drops pending to zero may run before another participant has executed task_done(), so reply
    // retirement must wait for the final raw Client reference too. Registry wakeups have no active
    // Tasks and can publish immediately.
    if (state.active_tasks.load(std::memory_order_acquire) != 0) return;
    Op& op = state.client->rob().at(state.op_id);
    if (op.state.exchange(OpState::Done, std::memory_order_acq_rel) != OpState::Done)
        blocking_notify_sender(*state.server, self, ring, state.client);
}

void blocking_finish_error(BlockingState& state, ThreadCtx& self, Ring& ring) {
    Op& op = state.client->rob().at(state.op_id);
    reply_wrongtype(op.sink());
    blocking_publish_completion(state, self, ring);
}

void blocking_fail_registration_oom(BlockingState& state, Op& op,
                                    ThreadCtx& self, Ring& ring) {
    BlockingPhase expected = BlockingPhase::Registering;
    if (!state.phase.compare_exchange_strong(
            expected, BlockingPhase::Completed, std::memory_order_acq_rel,
            std::memory_order_acquire)) return;
    reply_err(op.sink(), "ERR out of memory");
    blocking_publish_completion(state, self, ring);
}

bool blocking_run_direct(BlockingState& state, Shard& shard, ThreadCtx& self, Ring& ring) {
    BlockingKey& key = state.keys[state.selected];
    const Slice key_slice = blocking_key_slice(key);
    Op& op = state.client->rob().at(state.op_id);
    bool plain_active = false;
    if (shard.store().atomic_has_record(key.hash, key_slice)) {
        const WorkError prepared = begin_plain_version(
            *state.server, shard, key_slice, key.hash, state.server->atomic_snapshot(),
            state.client->id());
        if (prepared != WorkError::None) {
            reply_work_error(op, prepared);
            blocking_publish_completion(state, self, ring);
            return true;
        }
        plain_active = true;
    }
    std::vector<std::string> members;
    std::vector<double> scores;
    XshardPopResult result;
    if (blocking_is_list(state.kind)) {
        result = xshard_pop_list(shard, key_slice, key.hash, state.pop_left, state.count, members);
    } else {
        result = xshard_pop_zset(shard, key_slice, key.hash, !state.pop_left, state.count,
                                 members, scores);
    }
    if (plain_active) shard.store().atomic_finish_plain();
    if (result == XshardPopResult::Missing) return false;
    if (result == XshardPopResult::WrongType) {
        reply_wrongtype(op.sink());
    } else if (result == XshardPopResult::Oom) {
        reply_err(op.sink(), "ERR out of memory");
    } else if (state.kind == BlockingKind::Blpop || state.kind == BlockingKind::Brpop) {
        reply_array_header(op.sink(), 2);
        reply_bulk(op.sink(), key_slice);
        reply_bulk(op.sink(), Slice(members[0].data(), static_cast<uint32_t>(members[0].size())));
    } else if (state.kind == BlockingKind::Bzpopmin ||
               state.kind == BlockingKind::Bzpopmax) {
        reply_array_header(op.sink(), 3);
        reply_bulk(op.sink(), key_slice);
        reply_bulk(op.sink(), Slice(members[0].data(), static_cast<uint32_t>(members[0].size())));
        reply_double(op.sink(), scores[0]);
    } else {
        reply_array_header(op.sink(), 2);
        reply_bulk(op.sink(), key_slice);
        reply_array_header(op.sink(), members.size());
        for (size_t i = 0; i < members.size(); i++) {
            if (state.kind == BlockingKind::Bzmpop) reply_array_header(op.sink(), 2);
            reply_bulk(op.sink(),
                       Slice(members[i].data(), static_cast<uint32_t>(members[i].size())));
            if (state.kind == BlockingKind::Bzmpop) reply_double(op.sink(), scores[i]);
        }
    }
    blocking_publish_completion(state, self, ring);
    return true;
}

bool blocking_dispatch_selected(BlockingState& state, Shard& shard, ThreadCtx& self, Ring& ring) {
    if (blocking_is_move(state.kind) || state.kind == BlockingKind::Xread) {
        blocking_request_move(state, self, ring);
        return true;
    }
    if (state.keys[state.selected].shard == shard.id()) {
        if (blocking_run_direct(state, shard, self, ring)) return true;
        state.phase.store(BlockingPhase::NeedRegister, std::memory_order_release);
        return blocking_post_groups(state, self, ring, BlockingPhase::Registering);
    }
    state.phase.store(BlockingPhase::NeedSelected, std::memory_order_release);
    return blocking_post_selected(state, self, ring);
}

class BlockingRegistry {
public:
    ~BlockingRegistry() {
        for (BlockingQueue& queue : queues_)
            while (!queue.waiters.empty()) {
                BlockingState* state = queue.waiters.front().state;
                queue.waiters.pop_front();
                blocking_state_release(state);
            }
    }

    bool add(Shard& shard, BlockingState& state, uint32_t key_index) {
        const BlockingKey& key = state.keys[key_index];
        // Duplicate keys in one command are one registry alias at their earliest argument position.
        for (const BlockingQueue& queue : queues_)
            if (queue.hash == key.hash && queue.key == key.key)
                for (const BlockingEntry& waiter : queue.waiters)
                    if (waiter.state == &state) return true;
        BlockingQueue* queue = find(key.hash, blocking_key_slice(key));
        try {
            if (!queue) {
                queues_.push_back(BlockingQueue{key.key, key.hash, {}});
                queue = &queues_.back();
            }
            queue->waiters.push_back(BlockingEntry{&state, key_index});
        } catch (const std::bad_alloc&) {
            if (queue && queue->waiters.empty()) erase_empty();
            return false;
        }
        blocking_state_retain(&state);
        shard.blocking_waiter_added();
        state.server->blocking_waiter_added();
        return true;
    }

    uint32_t publish(Shard& shard, uint64_t hash, Slice key, int64_t now_ms,
                     ThreadCtx& self, Ring& ring) {
        BlockingQueue* queue = find(hash, key);
        if (!queue) return 0;
        const uint32_t work = service(shard, *queue, now_ms, self, ring);
        erase_empty();
        return work;
    }

    uint32_t sweep(Shard& shard, int64_t now_ms, bool check_values,
                   ThreadCtx& self, Ring& ring) {
        uint32_t work = 0;
        for (BlockingQueue& queue : queues_) {
            // Deadline/stale scan covers EVERY entry, not just the front: a waiter parked behind
            // a longer-lived one still times out at ITS deadline (redis semantics), and dead
            // entries (disconnects, completions from other queues) must not accumulate mid-queue
            // behind a forever-waiter.
            size_t i = 0;
            while (i < queue.waiters.size()) {
                BlockingState& state = *queue.waiters[i].state;
                BlockingPhase phase = state.phase.load(std::memory_order_acquire);
                if (state.cancel_requested.load(std::memory_order_acquire) &&
                    blocking_phase_live(phase)) {
                    if (state.phase.compare_exchange_strong(
                            phase, BlockingPhase::Cancelled, std::memory_order_acq_rel,
                            std::memory_order_acquire) &&
                        state.active_tasks.load(std::memory_order_acquire) == 0)
                        blocking_finish_cancelled(state, &self, &ring);
                    phase = state.phase.load(std::memory_order_acquire);
                }
                if (!blocking_phase_live(phase)) {
                    remove_at_from_shard(shard, queue, i);
                    work++;
                    continue;
                }
                if (phase == BlockingPhase::Parked && state.deadline_ms &&
                    now_ms >= state.deadline_ms) {
                    BlockingPhase expected = BlockingPhase::Parked;
                    if (state.phase.compare_exchange_strong(
                            expected, BlockingPhase::Completed, std::memory_order_acq_rel)) {
                        Op& op = state.client->rob().at(state.op_id);
                        blocking_reply_timeout(op, state.kind);
                        remove_at_from_shard(shard, queue, i);
                        blocking_publish_completion(state, self, ring);
                        work++;
                        continue;
                    }
                }
                i++;
            }
            if (check_values && !queue.waiters.empty())
                work += service(shard, queue, now_ms, self, ring);
        }
        erase_empty();
        return work;
    }

private:
    BlockingQueue* find(uint64_t hash, Slice key) {
        for (BlockingQueue& queue : queues_)
            if (queue.hash == hash && queue.key.size() == key.n &&
                (!key.n || std::memcmp(queue.key.data(), key.p, key.n) == 0)) return &queue;
        return nullptr;
    }

    void remove_at_from_shard(Shard& shard, BlockingQueue& queue, size_t index) {
        BlockingState* state = queue.waiters[index].state;
        queue.waiters.erase(queue.waiters.begin() + static_cast<ptrdiff_t>(index));
        shard.blocking_waiter_removed();
        state->server->blocking_waiter_removed();
        blocking_state_release(state);
    }

    void remove_front_from_shard(Shard& shard, BlockingQueue& queue) {
        remove_at_from_shard(shard, queue, 0);
    }

    uint32_t service(Shard& shard, BlockingQueue& queue, int64_t,
                     ThreadCtx& self, Ring& ring) {
        uint32_t work = 0;
        size_t i = 0;
        while (i < queue.waiters.size()) {
            BlockingEntry entry = queue.waiters[i];
            BlockingState& state = *entry.state;
            BlockingPhase phase = state.phase.load(std::memory_order_acquire);
            if (!blocking_phase_live(phase)) {
                remove_at_from_shard(shard, queue, i);
                work++;
                continue;
            }
            BlockingKey& key = state.keys[entry.key_index];
            if (blocking_probe_key(shard, state, key) != BlockingProbe::Ready) {
                // Tri-state, not boolean: FIFO kinds stop the queue here (the front waiter owns
                // the next push); skip-kinds (streams, later) step past a waiter whose own cursor
                // is not satisfiable without stranding the ones behind it.
                if (blocking_skip_when_not_ready(state.kind)) { i++; continue; }
                return work;
            }
            if (phase == BlockingPhase::Registering) {
                blocking_atomic_min(state.candidate, entry.key_index);
                if (state.phase.load(std::memory_order_acquire) != BlockingPhase::Registering)
                    continue;
                return work + 1;
            }
            BlockingPhase expected = BlockingPhase::Parked;
            if (!state.phase.compare_exchange_strong(
                    expected, BlockingPhase::Claimed, std::memory_order_acq_rel)) continue;
            state.selected = entry.key_index;
            remove_at_from_shard(shard, queue, i);
            if (blocking_is_move(state.kind)) {
                blocking_request_move(state, self, ring);
                return work + 1;
            }
            if (state.kind == BlockingKind::Xread) {
                blocking_request_move(state, self, ring);
                work++;
                continue;
            }
            if (!blocking_run_direct(state, shard, self, ring)) {
                state.phase.store(BlockingPhase::Parked, std::memory_order_release);
                return work + 1;
            }
            // Consume sequentially on the owner while the collection stays non-empty. This is
            // still FIFO handoff (one claimed context at a time), but a multi-element LPUSH/ZADD
            // does not strand later waiters behind data made ready by the same committed write.
            // The scan resumes at the same index: the served entry's removal shifted the next
            // waiter into position i.
            work++;
        }
        return work;
    }

    void erase_empty() {
        for (size_t i = 0; i < queues_.size();) {
            if (!queues_[i].waiters.empty()) { i++; continue; }
            queues_[i] = std::move(queues_.back());
            queues_.pop_back();
        }
    }

    std::vector<BlockingQueue> queues_;
};

// Registry destruction runs only after all executor and IO threads have joined. Gauge values are no
// longer observable then; release the context refs without pretending an owner is still publishing.
void blocking_registry_destroy(BlockingRegistry* registry) { delete registry; }

BlockingRegistry* blocking_registry_get(Shard& shard, bool create) {
    void*& slot = shard.blocking_registry_slot();
    if (!slot && create) slot = new (std::nothrow) BlockingRegistry;
    return static_cast<BlockingRegistry*>(slot);
}

void blocking_reset_probes(BlockingState& state) {
    for (BlockingKey& key : state.keys) key.probe = BlockingProbe::Empty;
    state.candidate.store(UINT32_MAX, std::memory_order_relaxed);
}

bool blocking_finish_probe(BlockingState& state, Shard& shard, ThreadCtx& self, Ring& ring) {
    if (state.cancel_requested.load(std::memory_order_acquire)) {
        state.phase.store(BlockingPhase::Cancelled, std::memory_order_release);
        return true;
    }
    uint32_t selected = UINT32_MAX;
    bool wrong_type = false;
    if (blocking_pick(state, selected, wrong_type)) {
        BlockingPhase expected = BlockingPhase::Probe;
        const BlockingPhase desired = wrong_type ? BlockingPhase::Completed
                                                 : BlockingPhase::Claimed;
        if (!state.phase.compare_exchange_strong(
                expected, desired, std::memory_order_acq_rel,
                std::memory_order_acquire)) return true;
        if (wrong_type) { blocking_finish_error(state, self, ring); return true; }
        state.selected = selected;
        return blocking_dispatch_selected(state, shard, self, ring);
    }
    blocking_reset_probes(state);
    BlockingPhase expected = BlockingPhase::Probe;
    if (!state.phase.compare_exchange_strong(
            expected, BlockingPhase::NeedRegister, std::memory_order_acq_rel,
            std::memory_order_acquire)) return true;
    return blocking_post_groups(state, self, ring, BlockingPhase::Registering);
}

bool blocking_finish_registration(BlockingState& state, Shard& shard,
                                  ThreadCtx& self, Ring& ring) {
    if (state.cancel_requested.load(std::memory_order_acquire)) {
        state.phase.store(BlockingPhase::Cancelled, std::memory_order_release);
        return true;
    }
    uint32_t selected = UINT32_MAX;
    bool wrong_type = false;
    const bool picked = blocking_pick(state, selected, wrong_type);
    const uint32_t signaled = state.candidate.load(std::memory_order_acquire);
    if (!picked && signaled != UINT32_MAX) selected = signaled;
    if (wrong_type) {
        BlockingPhase expected = BlockingPhase::Registering;
        if (state.phase.compare_exchange_strong(
                expected, BlockingPhase::Completed, std::memory_order_acq_rel,
                std::memory_order_acquire))
            blocking_finish_error(state, self, ring);
        return true;
    }
    if (selected != UINT32_MAX) {
        BlockingPhase expected = BlockingPhase::Registering;
        if (!state.phase.compare_exchange_strong(
                expected, BlockingPhase::Claimed, std::memory_order_acq_rel,
                std::memory_order_acquire)) return true;
        state.selected = selected;
        return blocking_dispatch_selected(state, shard, self, ring);
    }
    BlockingPhase expected = BlockingPhase::Registering;
    if (!state.phase.compare_exchange_strong(
            expected, BlockingPhase::Parked, std::memory_order_acq_rel,
            std::memory_order_acquire)) return true;
    blocking_count_parked(state);
    return true;
}

}  // namespace

Shard::~Shard() {
    blocking_registry_destroy(static_cast<BlockingRegistry*>(blocking_registry_));
}

void blocking_bind_executor(Server* server, ThreadCtx* self, Ring* ring) {
    (void)server;
    blocking_tls_self = self;
    blocking_tls_ring = ring;
}

BlockingPrepare blocking_prepare(Server& server, Client& client, Op& op, uint64_t op_id,
                                 BlockingDispatch& dispatch) {
    auto* state = new (std::nothrow) BlockingState;
    if (!state) { reply_err(op.sink(), "ERR out of memory"); return BlockingPrepare::Error; }
    state->server = &server;
    state->client = &client;
    state->op_id = op_id;
    if (!blocking_classify(op, state->kind)) {
        delete state;
        reply_err(op.sink(), "ERR internal blocking routing error");
        return BlockingPrepare::Error;
    }
    uint32_t first_key = 0, key_count = 0, timeout_arg = 0;
    if (!blocking_validate(op, *state, first_key, key_count, timeout_arg)) {
        (void)timeout_arg;
        delete state;
        return BlockingPrepare::Error;
    }
    try {
        state->keys.reserve(key_count);
        for (uint32_t i = 0; i < key_count; i++) {
            const Slice key = op.arg(first_key + i);
            const uint64_t hash = FlatStore::hash_key(key);
            const int32_t shard = server.router().shard_of(hash);
            BlockingKey blocking_key;
            blocking_key.key.assign(key.p, key.n);
            blocking_key.hash = hash;
            blocking_key.shard = shard;
            if (state->kind == BlockingKind::Xread) {
                if (!stream_parse_xread_id(op.arg(state->xread_first_id + i),
                                           blocking_key.cursor,
                                           blocking_key.cursor_latest)) {
                    delete state;
                    reply_err(op.sink(), "ERR Invalid stream ID specified as stream command argument");
                    return BlockingPrepare::Error;
                }
                blocking_key.cursor_resolved = !blocking_key.cursor_latest;
            }
            state->keys.push_back(std::move(blocking_key));
            BlockingGroup* group = blocking_group_for(*state, shard);
            if (!group) {
                state->groups.push_back(BlockingGroup{shard, {}});
                group = &state->groups.back();
            }
            group->keys.push_back(i);
        }
    } catch (const std::bad_alloc&) {
        delete state;
        reply_err(op.sink(), "ERR out of memory");
        return BlockingPrepare::Error;
    }
    dispatch.state = state;
    dispatch.nshards = static_cast<uint32_t>(state->groups.size());
    return BlockingPrepare::Ready;
}

int32_t blocking_dispatch_shard(const BlockingDispatch& dispatch, uint32_t index) {
    return dispatch.state && index < dispatch.state->groups.size()
        ? dispatch.state->groups[index].shard : -1;
}

void blocking_destroy_unpublished(BlockingState* state) { blocking_state_release(state); }

void blocking_start(BlockingState* state, uint32_t tasks) {
    state->pending.store(tasks, std::memory_order_relaxed);
    state->active_tasks.store(tasks, std::memory_order_relaxed);
    state->phase.store(BlockingPhase::Probe, std::memory_order_release);
}

bool blocking_execute(Server&, ThreadCtx& self, Ring& ring, const Task& task,
                      Shard& shard, Op& op) {
    const bool notify = (op.spec->flags & CmdFlags::NotifySelected) != 0;
    NotifyExecutionScope notify_scope(shard, op, notify);
    BlockingState& state = *op.blocking_state();
    if (state.cancel_requested.load(std::memory_order_acquire)) {
        state.phase.store(BlockingPhase::Cancelled, std::memory_order_release);
        blocking_task_done(state, self, ring);
        return true;
    }
    const BlockingPhase phase = state.phase.load(std::memory_order_acquire);
    if (phase == BlockingPhase::Cancelled) {
        blocking_task_done(state, self, ring);
        return true;
    }
    if (phase == BlockingPhase::NeedRegister) {
        if (!blocking_post_groups(state, self, ring, BlockingPhase::Registering)) return false;
        blocking_task_done(state, self, ring);
        return true;
    }
    if (phase == BlockingPhase::NeedSelected) {
        if (!blocking_post_selected(state, self, ring)) return false;
        blocking_task_done(state, self, ring);
        return true;
    }
    if (phase == BlockingPhase::Claimed) {
        bool complete = true;
        if (blocking_is_move(state.kind) || state.kind == BlockingKind::Xread) {
            blocking_request_move(state, self, ring);
        } else if (!blocking_run_direct(state, shard, self, ring)) {
            blocking_reset_probes(state);
            state.phase.store(BlockingPhase::NeedRegister, std::memory_order_release);
            complete = blocking_post_groups(state, self, ring, BlockingPhase::Registering);
        }
        if (!complete) return false;
        blocking_task_done(state, self, ring);
        return true;
    }

    BlockingGroup* group = blocking_group_for(state, task.shard);
    if (!group) std::abort();
    if (phase == BlockingPhase::Probe) {
        for (uint32_t index : group->keys)
            state.keys[index].probe = blocking_probe_key(shard, state, state.keys[index]);
        if (state.pending.fetch_sub(1, std::memory_order_acq_rel) == 1 &&
            !blocking_finish_probe(state, shard, self, ring)) return false;
        blocking_task_done(state, self, ring);
        return true;
    }
    if (phase == BlockingPhase::Registering) {
        BlockingRegistry* registry = blocking_registry_get(shard, true);
        if (!registry) {
            blocking_fail_registration_oom(state, op, self, ring);
            blocking_task_done(state, self, ring);
            return true;
        }
        for (uint32_t index : group->keys) {
            if (state.phase.load(std::memory_order_acquire) !=
                BlockingPhase::Registering) break;
            BlockingKey& key = state.keys[index];
            key.probe = blocking_probe_key(shard, state, key);
            if (key.probe == BlockingProbe::Empty && !registry->add(shard, state, index)) {
                blocking_fail_registration_oom(state, op, self, ring);
                blocking_task_done(state, self, ring);
                return true;
            }
        }
        if (state.phase.load(std::memory_order_acquire) == BlockingPhase::Registering &&
            state.pending.fetch_sub(1, std::memory_order_acq_rel) == 1 &&
            !blocking_finish_registration(state, shard, self, ring)) return false;
        blocking_task_done(state, self, ring);
        return true;
    }
    blocking_task_done(state, self, ring);
    return true;
}

BlockingSnapshotPrepare blocking_snapshot_prepare(const Task& task, Shard& shard, Op& op) {
    BlockingState& state = *op.blocking_state();
    BlockingGroup* group = blocking_group_for(state, task.shard);
    if (!group) return BlockingSnapshotPrepare::Error;
    for (uint32_t index : group->keys) {
        const BlockingKey& key = state.keys[index];
        const FlatStore::SnapshotWriteResult result =
            shard.store().snapshot_prepare_write(key.hash, blocking_key_slice(key));
        if (result == FlatStore::SnapshotWriteResult::Pending)
            return BlockingSnapshotPrepare::Pending;
        if (result == FlatStore::SnapshotWriteResult::Error)
            return BlockingSnapshotPrepare::Error;
    }
    return BlockingSnapshotPrepare::Ready;
}

void blocking_publish_key(Shard& shard, uint64_t hash, const char* key, uint32_t key_len) {
    if (blocking_tls_defer_plain || !shard.has_blocking_waiters() ||
        !blocking_tls_self || !blocking_tls_ring) return;
    BlockingRegistry* registry = blocking_registry_get(shard, false);
    if (!registry) return;
    const int64_t now = shard.now_ms();
    registry->publish(shard, hash, Slice(key, key_len), now, *blocking_tls_self, *blocking_tls_ring);
}

void blocking_publish_list_op(Shard& shard, Op& op) {
    blocking_publish_key(shard, op.hash, op.key().p, op.key().n);
}

void blocking_publish_zset_op(Shard& shard, Op& op) {
    blocking_publish_key(shard, op.hash, op.key().p, op.key().n);
}

void blocking_defer_plain_publication(bool defer) { blocking_tls_defer_plain = defer; }

void blocking_plain_mutation_published(Shard& shard, Op& op) {
    if (!shard.has_blocking_waiters()) return;
    const char* name = op.spec->name;
    if (!std::strcmp(name, "LPUSH") || !std::strcmp(name, "RPUSH") ||
        !std::strcmp(name, "LPUSHX") || !std::strcmp(name, "RPUSHX") ||
        !std::strcmp(name, "ZADD") || !std::strcmp(name, "ZINCRBY") ||
        !std::strcmp(name, "XADD"))
        blocking_publish_key(shard, op.hash, op.key().p, op.key().n);
    else if (!std::strcmp(name, "LMOVE") || !std::strcmp(name, "RPOPLPUSH")) {
        const Slice destination = op.arg(2);
        blocking_publish_key(shard, FlatStore::hash_key(destination),
                             destination.p, destination.n);
    }
}

uint32_t blocking_owner_cycle(Server&, ThreadCtx& self, Ring& ring, int64_t now_ms,
                              bool timeout_beat) {
    uint32_t work = 0;
    for (Shard* shard : self.shards()) {
        if (!shard->has_blocking_waiters()) continue;
        BlockingRegistry* registry = blocking_registry_get(*shard, false);
        if (!registry) continue;
        const bool dirty = shard->take_blocking_dirty();
        if (dirty || timeout_beat)
            work += registry->sweep(*shard, now_ms, dirty, self, ring);
    }
    return work;
}

void blocking_atomic_published(Server& server, ThreadCtx& self, Ring& ring,
                               ScatterState& state) {
    if (!state.atomic_apply || state.epoch.load(std::memory_order_acquire) == 0 ||
        state.aborted.load(std::memory_order_acquire)) return;
    bool owners[kMaxThreads] = {};
    for (uint32_t i = 0; i < state.nsub; i++) {
        Shard& shard = server.shard(state.groups[i].shard);
        if (!shard.has_blocking_waiters()) continue;
        shard.set_blocking_dirty();
        owners[server.worker_of_shard(shard.id())] = true;
    }
    for (uint32_t tid = 0; tid < server.nthreads(); tid++)
        if (owners[tid]) server.thread(tid).wake_if_parked(ring, self.sig());
}

void blocking_scatter_mutation_published(const Task& task, Shard& shard, Op& op) {
    if (!task.scatter || !shard.has_blocking_waiters()) return;
    ScatterState& state = *task.scatter;
    if (state.atomic_group || state.phase != 2 ||
        !(state.kind == Kind::Lmove || state.kind == Kind::Rpoplpush)) return;
    ShardGroup* group = group_for(state, shard.id());
    if (!group) return;
    for (uint32_t i = 0; i < group->count; i++) {
        const uint32_t pos = state.key_order[group->begin + i];
        const KeyRef& key = state.keys[pos];
        const Slice slice = op.arg(key.arg);
        blocking_publish_key(shard, key.hash, slice.p, slice.n);
    }
}

bool blocking_resume_move(Server& server, ThreadCtx& self, Ring& ring, Client& client,
                          ScatterArenaPool& pool) {
    if (!client.blocked()) return false;
    for (uint64_t id = client.rob().flush_id(), end = client.rob().dispatch_id(); id != end; id++) {
        Op& op = client.rob().at(id);
        BlockingState* block = op.blocking_state();
        if (!block || block->phase.load(std::memory_order_acquire) !=
                          BlockingPhase::MoveRequested ||
            block->active_tasks.load(std::memory_order_acquire) != 0) continue;
        ScatterDispatch dispatch;
        const ScatterPrepare prepared = xshard_prepare(
            server, op, pool, self.id(), client.id(), dispatch);
        if (prepared == ScatterPrepare::Backpressure) return false;
        if (prepared == ScatterPrepare::Error) {
            block->phase.store(BlockingPhase::Completed, std::memory_order_release);
            op.state.store(OpState::Done, std::memory_order_release);
            return true;
        }
        if (prepared != ScatterPrepare::Ready) {
            reply_err(op.sink(), "ERR internal blocking move routing error");
            block->phase.store(BlockingPhase::Completed, std::memory_order_release);
            op.state.store(OpState::Done, std::memory_order_release);
            return true;
        }
        uint32_t needed[kMaxThreads] = {};
        uint32_t participants[kMaxThreads];
        uint32_t nparticipants = 0;
        for (uint32_t i = 0; i < dispatch.nshards; i++) {
            const int32_t sid = xshard_dispatch_shard(dispatch, i);
            const uint32_t owner = server.worker_of_shard(sid);
            if (needed[owner]++ == 0) participants[nparticipants++] = owner;
        }
        for (uint32_t i = 0; i < nparticipants; i++) {
            const uint32_t owner = participants[i];
            if (server.thread(owner).task_free_slots(self.id()) < needed[owner]) {
                xshard_destroy(dispatch.state, pool, self.id());
                return false;
            }
        }
        dispatch.state->blocking_origin = block;
        block->phase.store(BlockingPhase::Transferred, std::memory_order_release);
        op.detach_blocking_state();
        op.attach_scatter_state(dispatch.state);
        if (dispatch.atomic_write) client.atomic_group_started();
        for (uint32_t i = 0; i < dispatch.nshards; i++) {
            const int32_t sid = xshard_dispatch_shard(dispatch, i);
            ThreadCtx& owner = server.thread(server.worker_of_shard(sid));
            const Task task{&client, id, sid, dispatch.state};
            if (!owner.post_task_quiet(self.id(), task, self.sig())) std::abort();
        }
        for (uint32_t i = 0; i < nparticipants; i++)
            server.thread(participants[i]).flush_task_notify(self.id(), ring, self.sig());
        return true;
    }
    return false;
}

bool blocking_cancel_client(Server& server, ThreadCtx& self, Ring& ring, Client& client) {
    bool finished_here = false;
    if (!client.blocked()) return false;
    for (uint64_t id = client.rob().flush_id(), end = client.rob().dispatch_id(); id != end; id++) {
        Op& op = client.rob().at(id);
        BlockingState* state = op.blocking_state();
        if (!state) continue;  // a transferred move completes through the ordinary scatter path
        state->cancel_requested.store(true, std::memory_order_release);
        BlockingPhase phase = state->phase.load(std::memory_order_acquire);
        bool owners[kMaxThreads] = {};
        for (const BlockingKey& key : state->keys) {
            Shard& shard = server.shard(key.shard);
            if (!shard.has_blocking_waiters()) continue;
            shard.set_blocking_dirty();
            owners[server.worker_of_shard(key.shard)] = true;
        }
        for (uint32_t tid = 0; tid < server.nthreads(); tid++)
            if (owners[tid]) server.thread(tid).wake_if_parked(ring, self.sig());
        // MoveRequested is handed exclusively to this IO after the requesting owner dropped its
        // final Task reference. It may have no registry alias to trigger an owner cleanup pass.
        if (phase == BlockingPhase::MoveRequested &&
            state->active_tasks.load(std::memory_order_acquire) == 0 &&
            state->phase.compare_exchange_strong(
                phase, BlockingPhase::Cancelled, std::memory_order_acq_rel,
                std::memory_order_acquire)) {
            blocking_finish_cancelled(*state, nullptr, nullptr);
            finished_here = true;
        }
    }
    return finished_here;
}

void blocking_retire(Server& server, Client& client, Op& op, ThreadCtx& thread) {
    BlockingState* state = op.blocking_state();
    if (!state) return;
    acl_recheck_blocking(client, op, thread);
    client.set_blocked(false);
    client.set_scatter_barrier(false);
    if (state->counted.exchange(false, std::memory_order_acq_rel))
        server.blocking_client_unparked();
    op.detach_blocking_state();
    blocking_state_release(state);
}

void blocking_scatter_retire(Server& server, Client& client, ScatterState& state) {
    BlockingState* block = state.blocking_origin;
    if (!block) return;
    client.set_blocked(false);
    client.set_scatter_barrier(false);
    if (block->counted.exchange(false, std::memory_order_acq_rel))
        server.blocking_client_unparked();
    state.blocking_origin = nullptr;
    blocking_state_release(block);
}

bool blocking_stream_bounds(const BlockingState* state, uint32_t key_index, StreamID& cursor,
                            StreamID& upper, bool& bounded) {
    if (!state || state->kind != BlockingKind::Xread || key_index >= state->keys.size() ||
        !state->keys[key_index].cursor_resolved) return false;
    cursor = state->keys[key_index].cursor;
    upper = state->keys[key_index].wake_upper;
    bounded = state->keys[key_index].wake_bounded;
    return true;
}

bool blocking_wants_dispatch(const Op& op) {
    return stream_xread_has_block_option(op);
}

}  // namespace tomo
