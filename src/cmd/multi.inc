#include "txn_retry_queue.h"
// multi.inc -- MULTI/EXEC/DISCARD/WATCH/UNWATCH on the epoch-MVCC seam.
//
// This file is textually included by xshard.cc.  It shares the command-image helpers in the same
// anonymous namespace and deliberately creates no extra translation unit.

#include "cmdmeta.h"

namespace tomo {

void multi_database_stats(Shard&, DatabaseStatsTable&, uint64_t cut, uint64_t origin_conn_id);

struct MultiQueuedCommand {
    const CommandSpec* spec = nullptr;
    std::vector<std::string> argv;
};

struct MultiWatchedKey {
    std::string key;
    uint64_t hash = 0;
    int32_t shard = -1;
    uint8_t ns = 0;
    uint8_t db = 0;
    bool claim_finalizes = false;
};

enum class MultiCommandKind : uint8_t {
    Local,
    Mget,
    Mset,
    Msetnx,
    Del,
    Exists,
    Ping,
    Echo,
    UnwatchReply,
    IoLocal,
    Scan,
    Xshard,
    Swapdb,
    Prebuilt,
    Unsupported,
    Admin,
    DebugSleep,
};

enum class MultiBlockingPop : uint8_t {
    None, Blpop, Brpop, Blmpop, Bzpopmin, Bzpopmax, Bzmpop
};

struct MultiValue {
    bool present = false;
    std::string value;
};

struct MultiCommand {
    static constexpr uint32_t kXshardStages = 4;
    static constexpr uint32_t kShardMaskWords = 4;

    MultiQueuedCommand queued;
    std::unique_ptr<Op> op;
    MultiCommandKind kind = MultiCommandKind::Unsupported;
    std::vector<uint32_t> key_args;
    std::vector<int32_t> key_shards;
    std::vector<int32_t> participants;
    std::vector<uint8_t> shard_done;
    std::vector<MultiValue> values;
    // Blocking collection commands are executed inside EXEC through a nonblocking LMPOP/ZMPOP
    // child. The normalized argv owns the slices installed in `op`; it allocates only for these
    // transaction-only slow-path commands.
    std::vector<std::string> exec_argv;
    MultiBlockingPop blocking_pop = MultiBlockingPop::None;
    uint8_t pop_reply_shape = static_cast<uint8_t>(PopReplyShape::Mpop);
    std::atomic<uint32_t> pending{0};
    std::atomic<uint32_t> stage{0};
    std::atomic<long long> integer{0};
    std::atomic<bool> condition_failed{false};
    std::atomic<bool> finished{false};
    ScatterState* scatter = nullptr;
    // ScatterState::groups is rebuilt between an xshard child's waves.  A barrier-only shard must
    // decide whether it belongs to the PUBLISHED wave without consulting that mutable table: the
    // last task from the prior wave is allowed to rewrite it before publishing command.stage.
    // Four 64-bit words cover the server's 256-shard maximum.  Four stages cover the longest child
    // today (SORT source -> dynamic gather -> STORE apply) with one spare stage for a future retry.
    std::array<std::array<uint64_t, kShardMaskWords>, kXshardStages> xshard_stage_groups{};
    uint32_t notify_order_base = 0;
    std::array<uint8_t, 2> swap_physical{};
    std::unique_ptr<DatabaseMap::Map> watch_map;
};

enum class MultiStateKind : uint8_t { Execute, WatchAdd, Unwatch, Close };
enum class MultiFinalReply : uint8_t { Exec, Ok, ExecAbort, ExecDiskError };

struct MultiWriteKey {
    std::string key;
    uint64_t hash = 0;
    int32_t shard = -1;
    uint8_t ns = 0;
    mutable bool signals_watch = true; // Not part of the hash/equality identity.
    bool claim_finalizes = false;
};

struct MultiWriteKeyHash {
    size_t operator()(const MultiWriteKey& key) const {
        return static_cast<size_t>(key.hash ^
            (static_cast<uint64_t>(static_cast<uint32_t>(key.shard)) *
             0x9e3779b97f4a7c15ULL));
    }
};

struct MultiWriteKeyEqual {
    bool operator()(const MultiWriteKey& left, const MultiWriteKey& right) const {
        return left.shard == right.shard && left.ns == right.ns && left.key == right.key;
    }
};

struct MultiSession {
    bool active = false;
    bool queue_error = false;
    uint64_t next_queue_op_id = 0;
    uint32_t last_attempts = 0;
    std::vector<MultiQueuedCommand> queue;
    uint64_t query_bytes = 0; // Redis query accounting: argv payload plus one pointer per arg
    void clear_queue() { queue.clear(); query_bytes = 0; }
    std::vector<MultiWatchedKey> watched;
    MultiExecState* pending = nullptr;       // prepared, but not yet published to owner queues
};

struct MultiOwnerRecordRefs {
    // `nodes` is also the pointer retained by every AtomicEntry installed on this executor. Writer
    // owners begin at one so cleanup cannot release the state's pre-count before the owner has run
    // all of its outer shard tasks through the transaction's final decision.
    uint32_t nodes = 0;
    uint32_t remaining = 0;
    bool completion_sentinel = false;
};

// EXEC MUST NEVER BE WEAKER THAN THE SAME COMMANDS RUN BARE.  A bare cross-shard read pins a read
// cut, so a transaction that carries one has to pin a cut too; SnapshotCut is the shared header
// that lets it do so through the connection-owning IO thread's ScatterArenaPool, which is the one
// object allowed to write that thread's published cleanup floor (see xshard.h).
struct alignas(8) MultiExecState : SnapshotCut {
    ~MultiExecState() {
        notify_discard_batch(notify.exchange(nullptr));
        for (auto& targets : database_watch)
            for (auto [client, generation] : targets) client->watch_unref();
    }
    MultiStateKind kind = MultiStateKind::Execute;
    MultiFinalReply final_reply = MultiFinalReply::Exec;
    Server* server = nullptr;
    Client* client = nullptr;
    uint32_t owner_io = 0;
    uint64_t origin_conn_id = 0;
    uint64_t watch_generation = 0;
    uint64_t admission_generation = 0;
    bool admitted = false;
    bool reset_watch = false;
    bool published = false;
    bool retired = false;
    // Set at prepare time when the transaction carries at least one READ whose fragments land on
    // more than one owner -- the only shape that can straddle a foreign ticket, and therefore the
    // only shape that pays for a cut.  A write-only or single-owner transaction registers nothing.
    bool exec_read_fanout = false;
    bool read_cut_sampled = false;
    bool read_only = true;
    std::vector<std::vector<TxnClaim>> claims;
    // THE TRANSACTION'S EXPIRY CUT, the time-axis twin of the read cut above.  Absolute
    // CLOCK_REALTIME milliseconds, stamped once before any fragment is posted and installed on
    // every owner that runs part of this transaction.  Redis reaches the same place from the other
    // direction: EXEC is the top-level call, the queued commands run nested inside it, and
    // server.mstime is only refreshed at nesting depth zero -- so a key cannot expire part-way
    // through a transaction.  Unconditional: a single-owner transaction spans several tasks too,
    // and its clock moved between them just as readily.
    int64_t now_cut_ms = 0;
    // TEST HOOK (DEBUG ATOMIC-FANOUT-DEFER), the MULTI half.  Deadline and lead shard are written
    // once on the owning IO thread before the tasks are posted and read by the owners through the
    // task handoff's release/acquire pair.  Zero in production.
    uint64_t debug_fanout_deadline = 0;
    uint64_t debug_place_deadline = 0;
    int32_t debug_fanout_lead = -1;
    std::vector<std::unique_ptr<MultiCommand>> commands;
    std::vector<MultiWatchedKey> watched;
    std::vector<MultiWriteKey> write_keys;
    DatabaseMap::Map database_map;
    std::unique_ptr<DatabaseMap::Map> database_publish;
    struct Swap { uint8_t first, second, physical_first, physical_second; };
    std::vector<Swap> database_swaps;
    std::vector<std::vector<std::pair<Client*, uint64_t>>> database_watch;
    std::unordered_set<MultiWriteKey, MultiWriteKeyHash, MultiWriteKeyEqual> write_key_set;
    std::vector<int32_t> shards;
    // IO builds these in transaction order. Each cursor has exactly one shard-owner writer.
    std::vector<std::vector<uint32_t>> shard_commands;
    std::vector<uint32_t> shard_cursors;
    std::vector<uint8_t> watch_shard_done;
    std::vector<uint8_t> execution_joined;
    std::vector<uint8_t> final_shard_done;
    std::vector<uint8_t> aof_shard_done;
    std::vector<uint8_t> execution_noted;
    std::vector<uint16_t> per_shard_intents;
    // A remote cancellation must not change a running collection handler's
    // selected object from its private clone to a mutable predecessor. The
    // parent word decides visibility immediately (cancelled remains epoch 0);
    // only this shard's owner releases its private overlay at finalization.
    std::unique_ptr<std::atomic<bool>[]> shard_aborted;
    std::vector<MultiOwnerRecordRefs> owner_record_refs;
    ScatterArenaPool scatter_pool;
    MultiDecision decision;
    bool doomed = false;               // published by finalized
    MultiRetryNode retry;
    uint64_t exec_op_id = UINT64_MAX;
    uint32_t attempt = 0;
    bool has_publication = false;
    bool publication_started = false; // IO-owned after all participant tasks finish
    std::atomic<bool> backoff{false};
    uint64_t retry_after_ns = 0;
    std::atomic<uint32_t> record_refs{0};
    bool record_refs_precounted = false;
    std::atomic<uint32_t> watch_refs{0};
    std::atomic<bool> watch_failed{false};
    std::atomic<bool> watch_phase_done{false};
    std::atomic<uint32_t> watch_pending{0};
    std::atomic<uint32_t> watch_arrived{0};
    std::atomic<uint32_t> lists_pending{0};
    std::atomic<bool> finalizer_claimed{false};
    std::atomic<bool> finalized{false};
    // Open between admission and the finalizer that decides this transaction on every owner. EXEC
    // force-admits a group at BOTH atomic settings, so this is the arm that keeps a plain-default
    // server's transactions out of a half-applied snapshot.
    std::atomic<bool> apply_open{false};
    std::atomic<uint32_t> tasks_pending{0};
    std::atomic<NotifyBatch*> notify{nullptr};
    std::shared_ptr<AofGroupDecision> aof_group;
    std::unique_ptr<TxnPlaceBlocker[]> place_blockers;
    std::unique_ptr<MultiOwnerRetryNode[]> owner_retries;
};

namespace {

void multi_enqueue_node(Server& server, uint32_t io, MultiRetryNode& node) {
    auto& lane = server.multi_retry_lane(io);
    auto* prior = lane.head.load(std::memory_order_relaxed);
    do { node.next = prior; }
    while (!lane.head.compare_exchange_weak(prior, &node,
                std::memory_order_seq_cst, std::memory_order_relaxed));
    // Pair with the one-time binder's SC store/load. If a startup fence reaches
    // a worker before it binds, the binder observes the queued head instead.
    if (auto* signal = lane.signal.load(std::memory_order_seq_cst))
        signal->store(true, std::memory_order_release);
}
void multi_enqueue_retry(MultiExecState& state) {
    state.retry.unit = &state;
    multi_enqueue_node(*state.server, state.owner_io, state.retry);
}

MultiDecision* multi_record_decision(const AtomicEntry& entry) {
    if (entry.plain())
        return entry.group_epoch ? reinterpret_cast<MultiDecision*>(entry.group_epoch) : nullptr;
    if (!entry.group->multi_child || !entry.group->multi_parent) return nullptr;
    return &const_cast<MultiExecState*>(
        static_cast<const MultiExecState*>(entry.group->multi_parent))->decision;
}

// An owner that sees the parent's won CAS may run before the finalizer reaches
// this child's epoch store. Help before find() can skip that committed image.
void multi_help_child(AtomicEntry& entry, uint64_t ticket) {
    if (!entry.group || !entry.group->multi_child || !ticket ||
        ticket == kAtomicCancelledEpoch) return;
    uint64_t zero = 0;
    entry.group->epoch.compare_exchange_strong(zero, ticket, std::memory_order_acq_rel);
}

uint64_t multi_cancel_decision(MultiDecision& decision, uint32_t shard,
                               TxnCounter cause = TxnCounter::Dooms) {
    uint64_t epoch = decision.epoch.load(std::memory_order_acquire);
    if (decision.phase.load(std::memory_order_acquire) == TxnPhase::Executing) {
        if (!epoch) decision.owner->server->note_txn(
            decision.owner->server->worker_of_shard(shard), TxnCounter::OrderViolations);
        return epoch;
    }
    if (!epoch && decision.epoch.compare_exchange_strong(
            epoch, kAtomicCancelledEpoch, std::memory_order_acq_rel)) {
        auto& state = *decision.owner;
        state.server->note_txn(state.server->worker_of_shard(shard), cause);
        decision.aborted.store(true, std::memory_order_release);
        return kAtomicCancelledEpoch;
    }
    return epoch;
}
}

void multi_cancel_record(AtomicEntry& entry, const ScatterState* self) {
    if (MultiDecision* decision = multi_record_decision(entry)) {
        if (self && self->multi_parent == decision->owner) return;
        const uint32_t shard = entry.plain()
            ? decision->owner->server->router().shard_of(entry.plain_hash)
            : entry.group->keys[entry.group->key_order[entry.begin]].shard;
        const auto epoch = decision->epoch.load(std::memory_order_acquire);
        multi_help_child(entry, epoch);
        // Scatter's visitor precedes its claim gate. Merely inspecting a
        // blocked candidate there is expected; a plain install reaching one is not.
        if (!self && !epoch && !decision->aborted.load(std::memory_order_acquire))
            decision->owner->server->note_txn(
                decision->owner->server->worker_of_shard(shard), TxnCounter::OrderViolations);
        return;
    }
    if (!entry.group || entry.group == self) return;
    ScatterState& script = *entry.group;
    if (script.group_attempt()) {
        const uint32_t shard = script.keys[script.key_order[entry.begin]].shard;
        if (!self) txn_group_cancel(script, shard);
        return;
    }
    if (script.kind != Kind::Script || script.aborted.load(std::memory_order_acquire)) return;
    uint64_t undecided = 0;
    if (script.epoch.compare_exchange_strong(undecided, kAtomicCancelledEpoch,
                                            std::memory_order_acq_rel)) {
        script.script_conflict.store(true, std::memory_order_release);
        script.aborted.store(true, std::memory_order_release);
    }
}

void multi_cancel_intent(AtomicScriptIntent& intent, const ScatterState* self) {
    UnitRef& unit = atomic_intent_unit(intent);
    // Group wildcard intents are lifetime anchors, not dependencies. Claims
    // gate writes on the actual keys; unrelated keys must ignore this anchor.
    if (unit.unit_kind == UnitRef::Kind::Group) return;
    if (unit.unit_kind != UnitRef::Kind::Txn ||
        (self && self->multi_parent == unit.unit)) return;
    auto& decision = *reinterpret_cast<MultiDecision*>(unit.epoch);
    const uint32_t shard = intent.kind == 2 ? intent.hash
        : decision.owner->server->router().shard_of(intent.hash);
    if (!self && !decision.epoch.load(std::memory_order_acquire) &&
        !decision.aborted.load(std::memory_order_acquire))
        decision.owner->server->note_txn(decision.owner->server->worker_of_shard(shard),
                                        TxnCounter::OrderViolations);
}

void atomic_cancel_unit_record(AtomicEntry& entry) { multi_cancel_record(entry); }
void atomic_cancel_unit_intent(AtomicScriptIntent& intent) { multi_cancel_intent(intent); }
void atomic_shutdown_unit_intent(AtomicScriptIntent& intent) {
    UnitRef& unit = atomic_intent_unit(intent);
    if (unit.unit_kind == UnitRef::Kind::Group) {
        auto& state = *static_cast<ScatterState*>(const_cast<void*>(unit.unit));
        uint64_t zero = 0;
        if (state.epoch.compare_exchange_strong(zero, kAtomicCancelledEpoch)) {
            state.aborted.store(true, std::memory_order_relaxed);
            aof_abort_scatter_group(state);
        }
        const uint32_t shard = intent.kind == 2 ? intent.hash
            : state.server->router().shard_of(intent.hash);
        state.server->note_txn(state.server->worker_of_shard(shard),
                               TxnCounter::IntentsLive, uint64_t{0} - 1);
        return;
    }
    if (unit.unit_kind != UnitRef::Kind::Txn) std::abort();
    auto& decision = *reinterpret_cast<MultiDecision*>(unit.epoch);
    auto& state = *decision.owner;
    uint64_t undecided = 0;
    if (decision.epoch.compare_exchange_strong(undecided, kAtomicCancelledEpoch,
                                               std::memory_order_relaxed)) {
        // All producers have stopped; shutdown cancels any undecided attempt.
        decision.aborted.store(true, std::memory_order_relaxed);
        aof_abort_group(state.aof_group);
    }
    const uint32_t shard = intent.kind == 2 ? intent.hash
        : state.server->router().shard_of(intent.hash);
    state.server->note_txn(state.server->worker_of_shard(shard),
                           TxnCounter::IntentsLive, uint64_t{0} - 1);
}

namespace {

thread_local const DatabaseMap::Map* multi_watch_map = nullptr;
struct MultiWatchMapScope {
    const DatabaseMap::Map* selected;
    const DatabaseMap::Map* previous = nullptr;
    explicit MultiWatchMapScope(const DatabaseMap::Map* map) : selected(map) {
        if (selected) { previous = multi_watch_map; multi_watch_map = selected; }
    }
    ~MultiWatchMapScope() { if (selected) multi_watch_map = previous; }
};
uint8_t watch_write_database(Server* server, uint8_t physical) {
    if (multi_watch_map) {
        for (unsigned logical = 0; logical < 256; ++logical)
            if ((*multi_watch_map)[logical] == physical) return logical;
        std::abort();
    }
    return server ? server->databases().logical(physical) : physical;
}
void watch_note_database(Shard::WatchReservation& reservation, Server* server, uint8_t physical) {
    const auto db = watch_write_database(server, physical);
    reservation.dirty_databases[db / 64] |= uint64_t{1} << (db % 64);
}

constexpr uintptr_t kMultiTaskTag = 1;

bool multi_name(const Op& op, const char* lower) { return op.cmd_name().eq_icase(lower); }

MultiSession* ensure_multi_session(Client& client) {
    if (client.multi_session()) return client.multi_session();
    auto* session = new (std::nothrow) MultiSession;
    if (session) client.set_multi_session(session);
    return session;
}

void release_admission(MultiExecState& state) {
    if (state.server)
        state.server->atomic_apply_close(state.owner_io, state.apply_open);
    if (!state.admitted) return;
    state.server->atomic_retire_group(state.owner_io, state.admission_generation);
    state.admitted = false;
}

// Does `group_epoch` name a word THIS transaction publishes through? A transaction is one logical
// unit spread over several epoch words: the plain per-key installs publish through `state.decision.epoch`,
// and every cross-shard command lowered inside the same EXEC keeps its own ScatterState and
// publishes through that one. Anything asking "is there an undecided record here that is not mine"
// has to accept all of them, or the transaction answers yes against its own RENAME/LMPOP child.
// `commands` and their scatter pointers are written by IO in prepare_commands() before the first
// fragment is posted, and cleared only by destroy_multi_children() at retirement, which cannot run
// while a fragment is still executing -- so this walk is stable on an owner thread.
bool multi_state_owns_epoch(const MultiExecState& state, const void* group_epoch) {
    if (!group_epoch) return false;
    if (group_epoch == static_cast<const void*>(&state.decision.epoch)) return true;
    for (const auto& command : state.commands)
        if (command && command->scatter &&
            group_epoch == static_cast<const void*>(&command->scatter->epoch))
            return true;
    return false;
}

bool multi_records_done(const MultiExecState& state) {
    if (state.record_refs.load(std::memory_order_acquire) != 0 ||
        state.watch_refs.load(std::memory_order_acquire) != 0) return false;
    for (const auto& command : state.commands)
        if (command->scatter && !xshard_multi_child_records_done(*command->scatter)) return false;
    return true;
}

void destroy_multi_children(MultiExecState& state) {
    for (const auto& command : state.commands) {
        if (command->op) latency_tracking_forget(*command->op);
        if (!command->scatter) continue;
        xshard_destroy(command->scatter, state.scatter_pool, state.owner_io);
        command->scatter = nullptr;
    }
    state.scatter_pool.reap_deferred();
}

void destroy_multi_state(MultiExecState* state) {
    if (!state) return;
    if (__builtin_expect(atomic_tripwire_enabled(), false))
        atomic_tripwire_forget_scope(state);
    if (!multi_records_done(*state)) std::abort();
    // The cut bracket is register-at-dispatch / unregister-at-retire, both on the connection's own
    // IO thread. Reaching destruction still holding it would mean this thread's published cleanup
    // floor is pinned to a dead transaction, so cleanup would stop advancing server-wide. That is
    // an engine invariant, not an input condition; make it loud rather than silently degrading.
    if (state->snapshot_registered) std::abort();
    notify_discard_batch(state->notify.exchange(nullptr, std::memory_order_acq_rel));
    destroy_multi_children(*state);
    release_admission(*state);
    delete state;
}

bool multi_engine_policy_refusal(const Op& op) {
    // Owner decision group 5: these are engine limitations, NOT Redis no_multi flags.
    // Whole-store replacement has no transaction-private image; subscription controls and
    // ACL need their IO-owned protocols, not a synchronous EXEC child handler.
    // Keep the existing safety boundary until those mechanisms have transaction lowering.
    return multi_name(op, "flushall") || multi_name(op, "flushdb") || multi_name(op, "acl") ||
           multi_name(op, "subscribe") || multi_name(op, "unsubscribe") ||
           multi_name(op, "psubscribe") || multi_name(op, "punsubscribe") ||
           multi_name(op, "ssubscribe") || multi_name(op, "sunsubscribe") ||
           (multi_name(op, "debug") && op.argc() == 2 &&
            (op.arg(1).eq_icase("reload") || op.arg(1).eq_icase("loadaof")));
}

bool queued_copy(const Op& op, MultiQueuedCommand& out) {
    out.spec = op.spec;
    try {
        out.argv.reserve(op.argc());
        for (uint32_t i = 0; i < op.argc(); i++)
            out.argv.emplace_back(op.arg(i).p, op.arg(i).n);
    } catch (const std::bad_alloc&) {
        return false;
    }
    return true;
}

bool has_name(const MultiQueuedCommand& queued, const char* lower) {
    return Slice(queued.argv[0].data(), static_cast<uint32_t>(queued.argv[0].size()))
        .eq_icase(lower);
}

MultiBlockingPop multi_blocking_pop(const MultiQueuedCommand& queued) {
    if (has_name(queued, "blpop")) return MultiBlockingPop::Blpop;
    if (has_name(queued, "brpop")) return MultiBlockingPop::Brpop;
    if (has_name(queued, "blmpop")) return MultiBlockingPop::Blmpop;
    if (has_name(queued, "bzpopmin")) return MultiBlockingPop::Bzpopmin;
    if (has_name(queued, "bzpopmax")) return MultiBlockingPop::Bzpopmax;
    if (has_name(queued, "bzmpop")) return MultiBlockingPop::Bzmpop;
    return MultiBlockingPop::None;
}

void command_key_args(const MultiQueuedCommand& queued, std::vector<uint32_t>& args) {
    const CommandSpec& spec = *queued.spec;
    // Script metadata extends through ARGV; only the declared KEYS can own an AOF fragment.
    if (spec.flags & CmdFlags::ScriptRoute) {
        int64_t count = 0;
        if (queued.argv.size() < 3 ||
            !parse_i64(Slice(queued.argv[2].data(), queued.argv[2].size()), count) ||
            count < 0 || static_cast<uint64_t>(count) > queued.argv.size() - 3) return;
        for (uint32_t i = 0; i < static_cast<uint32_t>(count); i++) args.push_back(3 + i);
        return;
    }
    if (spec.flags & CmdFlags::StreamRoute) {
        uint32_t streams = 1;
        while (streams < queued.argv.size() &&
               !Slice(queued.argv[streams].data(), queued.argv[streams].size()).eq_icase("streams"))
            streams++;
        if (streams == queued.argv.size() || ((queued.argv.size() - streams - 1) & 1u)) return;
        const uint32_t count = static_cast<uint32_t>((queued.argv.size() - streams - 1) / 2);
        for (uint32_t arg = streams + 1; arg < streams + 1 + count; arg++) args.push_back(arg);
        return;
    }
    const MultiBlockingPop blocking = multi_blocking_pop(queued);
    if (blocking == MultiBlockingPop::Blpop || blocking == MultiBlockingPop::Brpop ||
        blocking == MultiBlockingPop::Bzpopmin || blocking == MultiBlockingPop::Bzpopmax) {
        for (uint32_t arg = 1; arg + 1 < queued.argv.size(); arg++) args.push_back(arg);
        return;
    }
    if (blocking == MultiBlockingPop::Blmpop || blocking == MultiBlockingPop::Bzmpop) {
        int64_t parsed = 0;
        const Slice count(queued.argv[2].data(), static_cast<uint32_t>(queued.argv[2].size()));
        if (!parse_i64(count, parsed) || parsed < 1 ||
            static_cast<uint64_t>(parsed) > UINT32_MAX ||
            3 + static_cast<uint64_t>(parsed) >= queued.argv.size()) return;
        for (uint32_t arg = 3; arg < 3 + static_cast<uint32_t>(parsed); arg++)
            args.push_back(arg);
        return;
    }
    if (spec.first_key <= 0 || spec.key_step <= 0) return;
    const uint32_t last = spec.last_key < 0
        ? static_cast<uint32_t>(queued.argv.size() - 1)
        : std::min<uint32_t>(static_cast<uint32_t>(spec.last_key),
                             static_cast<uint32_t>(queued.argv.size() - 1));
    for (uint32_t arg = static_cast<uint32_t>(spec.first_key); arg <= last;
         arg += static_cast<uint32_t>(spec.key_step))
        args.push_back(arg);
    // SORT'S STORE DESTINATION IS AN OPTION WORD, NOT PART OF ITS REGISTRY KEY RANGE (1..1), so the
    // loop above misses it. A queued `SORT src STORE dst` therefore looked like a ONE-key command:
    // classify_multi_command() saw a single shard, called it Local, and EXEC ran the same-owner arm
    // on the SOURCE's shard -- which installed `dst` in the source's table. The key was then
    // invisible to every routed lookup (EXISTS/TYPE/LRANGE answer on dst's real owner) while KEYS
    // and DBSIZE still counted it, and a snapshot would have persisted it under the wrong shard.
    // Naming the destination here restores the ordinary lowering: same shard stays Local and is
    // correct; different shards fall through to xshard_prepare's two-hop apply. It also puts the
    // destination into add_write_key(), so WATCH on it now sees the write.
    // SORT_RO is excluded by name: STORE is a syntax error there, so it names no destination.
    if (has_name(queued, "sort")) {
        uint32_t store_arg = 0;
        for (uint32_t i = 2; i < queued.argv.size(); i++) {
            const Slice word(queued.argv[i].data(),
                             static_cast<uint32_t>(queued.argv[i].size()));
            // Mirror parse_sort_options' grammar exactly, because a BY or GET pattern may itself
            // be the word STORE and must not be mistaken for the option.
            if (word.eq_icase("limit") && i + 2 < queued.argv.size()) i += 2;
            else if ((word.eq_icase("by") || word.eq_icase("get")) && i + 1 < queued.argv.size()) i++;
            else if (word.eq_icase("store") && i + 1 < queued.argv.size()) store_arg = ++i;
        }
        if (store_arg) args.push_back(store_arg);   // last STORE wins, as the parser records it
    }
}

// True when a queued SORT will READ keys derived from its elements. Such a command touches shards
// that no key of the transaction names, so it cannot be executed as an ordinary one-key Local child:
// see the participation note in prepare_commands().
bool multi_sort_dereferences(const MultiQueuedCommand& queued) {
    if (!has_name(queued, "sort") && !has_name(queued, "sort_ro")) return false;
    const uint32_t argc = static_cast<uint32_t>(queued.argv.size());
    for (uint32_t i = 2; i < argc; i++) {
        const Slice word(queued.argv[i].data(), static_cast<uint32_t>(queued.argv[i].size()));
        // Mirror parse_sort_options' grammar so an option word appearing INSIDE a pattern is not
        // mistaken for the option itself.
        if (word.eq_icase("limit") && i + 2 < argc) { i += 2; continue; }
        if (!(word.eq_icase("by") || word.eq_icase("get")) || i + 1 >= argc) continue;
        const std::string& pattern = queued.argv[++i];
        // `#` is the element and a pattern with no '*' is a constant nil: neither reads a key.
        const bool self = word.eq_icase("get") && pattern.size() == 1 && pattern[0] == '#';
        if (!self && pattern.find('*') != std::string::npos) return true;
    }
    return false;
}

bool contains_shard(const std::vector<int32_t>& shards, int32_t shard) {
    return std::find(shards.begin(), shards.end(), shard) != shards.end();
}

void add_shard(std::vector<int32_t>& shards, int32_t shard) {
    if (!contains_shard(shards, shard)) shards.push_back(shard);
}

bool multi_xshard_stage_has_group(const MultiCommand& command, uint32_t stage, int32_t shard) {
    if (stage >= MultiCommand::kXshardStages || shard < 0 || shard >= 256) std::abort();
    const uint32_t sid = static_cast<uint32_t>(shard);
    return command.xshard_stage_groups[stage][sid >> 6] & (1ull << (sid & 63));
}

bool make_child_op(MultiCommand& command) {
    command.op = std::make_unique<Op>();
    command.op->reset();
    command.op->spec = command.queued.spec;
    for (const std::string& arg : command.queued.argv)
        if (!command.op->push_arg(Slice(arg.data(), static_cast<uint32_t>(arg.size()))))
            return false;
    return true;
}

bool validate_multi_blocking_timeout(Op& op, MultiBlockingPop kind) {
    const uint32_t timeout_arg = (kind == MultiBlockingPop::Blmpop ||
                                  kind == MultiBlockingPop::Bzmpop)
        ? 1 : op.argc() - 1;
    int64_t timeout_ms = 0;
    if (blocking_reply_timeout_error(op, parse_timeout_ms(op.arg(timeout_arg), timeout_ms)))
        return false;
    if (timeout_ms != 0) {
        timespec now{};
        ::clock_gettime(CLOCK_REALTIME, &now);
        const int64_t now_ms = static_cast<int64_t>(now.tv_sec) * 1000 + now.tv_nsec / 1000000;
        if (timeout_ms > INT64_MAX - now_ms) {
            reply_err(op.sink(), "ERR timeout is out of range");
            return false;
        }
    }
    return true;
}

bool normalize_multi_blocking_pop(MultiCommand& command) {
    const MultiBlockingPop kind = command.blocking_pop;
    const bool list = kind == MultiBlockingPop::Blpop || kind == MultiBlockingPop::Brpop ||
                      kind == MultiBlockingPop::Blmpop;
    const bool single = kind == MultiBlockingPop::Blpop || kind == MultiBlockingPop::Brpop ||
                        kind == MultiBlockingPop::Bzpopmin || kind == MultiBlockingPop::Bzpopmax;
    const char* alias = list ? "LMPOP" : "ZMPOP";
    const CommandSpec* spec = command_lookup(Slice(alias, 5));
    if (!spec) return false;
    if (command.queued.spec->flags & CmdFlags::NotifySelected)
        spec = command_notify_variant(spec);

    command.exec_argv.clear();
    if (single) {
        command.exec_argv.reserve(command.queued.argv.size() + 3);
        command.exec_argv.emplace_back(alias);
        command.exec_argv.push_back(std::to_string(command.queued.argv.size() - 2));
        for (uint32_t i = 1; i + 1 < command.queued.argv.size(); i++)
            command.exec_argv.push_back(command.queued.argv[i]);
        const bool right_or_max = kind == MultiBlockingPop::Brpop ||
                                  kind == MultiBlockingPop::Bzpopmax;
        command.exec_argv.emplace_back(list ? (right_or_max ? "RIGHT" : "LEFT")
                                            : (right_or_max ? "MAX" : "MIN"));
        command.exec_argv.emplace_back("COUNT");
        command.exec_argv.emplace_back("1");
        command.pop_reply_shape = static_cast<uint8_t>(
            list ? PopReplyShape::ListPair : PopReplyShape::ZsetTriple);
    } else {
        command.exec_argv.reserve(command.queued.argv.size() - 1);
        command.exec_argv.emplace_back(alias);
        for (uint32_t i = 2; i < command.queued.argv.size(); i++)
            command.exec_argv.push_back(command.queued.argv[i]);
        command.pop_reply_shape = static_cast<uint8_t>(PopReplyShape::Mpop);
    }

    command.op->reset();
    command.op->spec = spec;
    for (const std::string& arg : command.exec_argv)
        if (!command.op->push_arg(Slice(arg.data(), static_cast<uint32_t>(arg.size()))))
            return false;
    return true;
}

MultiCommandKind classify_multi_command(MultiCommand& command) {
    if (has_name(command.queued, "swapdb")) return MultiCommandKind::Swapdb;
    if (has_name(command.queued, "ping")) return MultiCommandKind::Ping;
    if (has_name(command.queued, "echo")) return MultiCommandKind::Echo;
    if (has_name(command.queued, "unwatch")) return MultiCommandKind::UnwatchReply;
    if (command.queued.spec->flags & CmdFlags::ConnLocal) return MultiCommandKind::IoLocal;
    if (command.queued.spec->flags & CmdFlags::ConfigRoute)
        return command_config_routes_all_shards(*command.op, true)
            ? MultiCommandKind::Unsupported : MultiCommandKind::Admin;
    // SubcmdRoute containers ride CursorShard only to reach the IO special-route hook; they are
    // not cursor commands. Their keyed forms have a truthful key range and fall through to Local;
    // their keyless subcommands answer on the IO thread.
    if (command.queued.spec->flags & CmdFlags::SubcmdRoute)
        return command.key_args.empty() ? MultiCommandKind::IoLocal : MultiCommandKind::Local;
    if ((command.queued.spec->flags & CmdFlags::CursorShard) &&
        !(command.queued.spec->flags & CmdFlags::StreamRoute)) return MultiCommandKind::Scan;
    // These six execute through a normalized nonblocking xshard child even when all keys happen
    // to share one owner. Calling their ordinary Blocking handler from EXEC would park the whole
    // transaction, which Redis never does.
    if (command.blocking_pop != MultiBlockingPop::None || has_name(command.queued, "move"))
        return MultiCommandKind::Unsupported;
    if (command.key_args.empty()) return MultiCommandKind::Unsupported;
    // A DEREFERENCING SORT IS NEVER LOCAL, however few keys it names. Its BY/GET patterns read keys
    // derived from the source's ELEMENTS, on shards this transaction never declared, and a Local
    // child is ordered only against the commands that share its one shard -- so an earlier MSET
    // still pending on a weight key's shard would be invisible to it. As an Xshard child it can
    // declare every shard as a participant and take the transaction's ordinary stage barrier.
    if (multi_sort_dereferences(command.queued)) return MultiCommandKind::Unsupported;
    bool same = true;
    for (size_t i = 1; i < command.key_shards.size(); i++)
        same &= command.key_shards[i] == command.key_shards[0];
    if (same) return MultiCommandKind::Local;
    if (has_name(command.queued, "mget")) return MultiCommandKind::Mget;
    if (has_name(command.queued, "mset")) return MultiCommandKind::Mset;
    if (has_name(command.queued, "msetnx")) return MultiCommandKind::Msetnx;
    if (has_name(command.queued, "del") || has_name(command.queued, "unlink"))
        return MultiCommandKind::Del;
    if (has_name(command.queued, "exists") || has_name(command.queued, "touch"))
        return MultiCommandKind::Exists;
    return MultiCommandKind::Unsupported;
}

bool state_writes_key(const MultiExecState& state, const MultiWatchedKey& watched) {
    for (const MultiWriteKey& key : state.write_keys)
        if (key.signals_watch && key.shard == watched.shard && key.ns == watched.ns &&
            key.key == watched.key) return true;
    return false;
}

void add_write_key(MultiExecState& state, const MultiCommand& command, uint32_t index) {
    if (!(command.queued.spec->flags & (CmdFlags::Write | CmdFlags::SnapshotWrite))) return;
    if (command.kind == MultiCommandKind::Unsupported) return;
    const uint32_t arg = command.key_args[index];
    const Slice key = command.op->arg(arg);
    const int32_t shard = command.key_shards[index];
    MultiWriteKey candidate{
        std::string(key.p, key.n), FlatStore::hash_key(key), shard,
        static_cast<uint8_t>(key.ns), !has_name(command.queued, "xreadgroup")};
    const auto [position, inserted] = state.write_key_set.emplace(candidate);
    if (!inserted) {
        if (candidate.signals_watch && !position->signals_watch) {
            position->signals_watch = true;
            for (auto& prior : state.write_keys)
                if (MultiWriteKeyEqual{}(prior, candidate)) { prior.signals_watch = true; break; }
        }
        return;
    }
    state.write_keys.push_back(std::move(candidate));
}

bool command_has_owner_work(const MultiCommand& command);

Slice txn_claim_slice(const TxnClaim& claim) {
    return claim.key.empty() ? Slice{} : Slice(claim.key.data() + 1,
        static_cast<uint32_t>(claim.key.size() - 1), static_cast<uint8_t>(claim.key[0]));
}

void txn_add_claim(std::vector<TxnClaim>& claims, Slice key, TxnClaimMode mode,
                   bool whole = false) {
    std::string owned = whole ? std::string{} : database_owned_key(key);
    for (auto& claim : claims) {
        if (claim.key == owned) {
            if (mode == TxnClaimMode::Write) claim.mode = mode;
            return;
        }
    }
    claims.push_back({std::move(owned), whole ? 0 : FlatStore::hash_key(key), mode});
}

void txn_cap_claims(std::vector<TxnClaim>& claims) {
    if (claims.size() <= kTxnClaimsPerShard) return;
    TxnClaimMode mode = TxnClaimMode::Read;
    for (const auto& claim : claims)
        if (claim.mode == TxnClaimMode::Write) mode = claim.mode;
    claims.clear();
    claims.push_back({{}, 0, mode});
}

void prepare_claims(MultiExecState& state) {
    for (const auto& command : state.commands) {
        if (!command_has_owner_work(*command)) continue;
        const auto* child = command->scatter;
        const bool loader = child && (child->kind == Kind::DebugReload || child->kind == Kind::DebugLoadAof);
        const bool writes = (command->queued.spec->flags &
            (CmdFlags::Write | CmdFlags::SnapshotWrite)) || (child && child->atomic_group) || loader;
        state.read_only &= !writes;
        const auto mode = writes ? TxnClaimMode::Write : TxnClaimMode::Read;
        for (size_t i = 0; i < command->key_args.size(); ++i)
            txn_add_claim(state.claims[command->key_shards[i]],
                          command->op->arg(command->key_args[i]), mode);
        if (child) for (uint32_t i = 0; i < child->key_count; ++i)
            txn_add_claim(state.claims[child->keys[i].shard],
                          command->op->arg(child->keys[i].arg), mode);
        const bool whole = loader || has_name(command->queued, "scan") ||
            (child && ((child->kind == Kind::Sort && child->sort_options.deref) ||
                       child->kind == Kind::AllShards || child->kind == Kind::DatabaseInfo ||
                       child->kind == Kind::DbsizeExact || child->kind == Kind::RandomKey ||
                       child->kind == Kind::Keys));
        if (whole) for (int32_t sid : command->participants)
            txn_add_claim(state.claims[sid], {},
                loader || (writes && child && child->kind == Kind::AllShards)
                    ? TxnClaimMode::Write : TxnClaimMode::Read, true);
    }
    // WATCH keys are part of placement's conflict set even when no queued
    // command accesses them. Inactive namespace aliases are validation-only.
    for (const auto& watched : state.watched) {
        if (state.database_map[watched.db] != watched.ns) continue;
        txn_add_claim(state.claims[watched.shard],
            Slice(watched.key.data(), watched.key.size(), watched.ns),
            state_writes_key(state, watched) ? TxnClaimMode::Write : TxnClaimMode::Read);
    }
    for (auto& claims : state.claims) txn_cap_claims(claims);
    // Exact claims already retire all decided reservations for that physical
    // key. Keep the cold sweep only for capped whole-shard claims, inactive
    // WATCH aliases and synthetic/unprepared cleanup states.
    if (!state.read_only) {
        const auto covered = [&](const auto& key) {
            for (const auto& claim : state.claims[key.shard])
                if (claim.key.size() == key.key.size() + 1 &&
                    static_cast<uint8_t>(claim.key[0]) == key.ns &&
                    claim.key.compare(1, std::string::npos, key.key) == 0) return true;
            return false;
        };
        for (auto& key : state.write_keys) key.claim_finalizes = covered(key);
        for (auto& key : state.watched) key.claim_finalizes = covered(key);
    }
}

bool prepare_commands(Server& server, MultiExecState& state,
                      std::vector<MultiQueuedCommand>& queue) {
    try {
        state.commands.reserve(queue.size());
        state.write_key_set.reserve(queue.size());
        state.database_map = server.databases().capture();
        auto routing_map = state.database_map;
        const bool swaps = !kSingleDatabase && std::any_of(queue.begin(), queue.end(),
            [](const auto& queued) { return has_name(queued, "swapdb"); });
        uint8_t logical_db = state.client->session().db_index;
        for (MultiQueuedCommand& queued : queue) {
            auto command = std::make_unique<MultiCommand>();
            if (swaps) command->watch_map = std::make_unique<DatabaseMap::Map>(routing_map);
            command->notify_order_base =
                static_cast<uint32_t>(state.commands.size()) * 0x10000u;
            command->queued = std::move(queued);
            command->blocking_pop = multi_blocking_pop(command->queued);
            command_key_args(command->queued, command->key_args);
            if (!make_child_op(*command)) return false;
            if constexpr (!kSingleDatabase) multidb_stamp(server, *command->op, logical_db, routing_map);
            command->key_shards.reserve(command->key_args.size());
            for (uint32_t arg : command->key_args) {
                const uint64_t hash = FlatStore::hash_key(command->op->arg(arg));
                command->key_shards.push_back(server.router().shard_of(hash));
            }
            command->kind = classify_multi_command(*command);
            uint32_t acl_denied_arg = UINT32_MAX;
            const AclDeniedReason acl_denied = acl_check_queued(
                state.client->acl_user_idx(), *command->queued.spec,
                command->queued.argv, &acl_denied_arg);
            if (acl_denied != AclDeniedReason::None) {
                const char* reason = acl_denied == AclDeniedReason::Command
                    ? "no permission to execute the command or subcommand"
                    : acl_denied == AclDeniedReason::Key
                        ? "no permission to touch the specified keys"
                        : acl_denied == AclDeniedReason::Channel
                            ? "no permission to access one of the channels used as arguments"
                            : "no permission";
                std::string message =
                    "NOPERM ACLs rules changed between the moment the transaction was accumulated and the EXEC call. This command is no longer allowed for the following reason: ";
                message += reason;
                reply_err(command->op->sink(), message.c_str());
                command->kind = MultiCommandKind::Prebuilt;
                command->key_args.clear();
                command->key_shards.clear();
                LoopSignals& signals = server.thread(state.owner_io).sig();
                if (acl_denied == AclDeniedReason::Command) signals.acl_access_denied_cmd++;
                else if (acl_denied == AclDeniedReason::Key) signals.acl_access_denied_key++;
                else if (acl_denied == AclDeniedReason::Channel)
                    signals.acl_access_denied_channel++;
                const uint32_t object_arg = acl_denied_arg < command->queued.argv.size()
                    ? acl_denied_arg : 0;
                const std::string& object = command->queued.argv[object_arg];
                const char* username = acl_username(state.client->acl_user_idx());
                acl_log_denial(server.thread(state.owner_io), *state.client, acl_denied,
                    AclLogContext::Multi,
                    Slice(object.data(), static_cast<uint32_t>(object.size())),
                    Slice(username, static_cast<uint32_t>(std::strlen(username))));
            }
            if (command->kind != MultiCommandKind::Prebuilt &&
                command->blocking_pop != MultiBlockingPop::None) {
                if (!validate_multi_blocking_timeout(*command->op, command->blocking_pop)) {
                    command->kind = MultiCommandKind::Prebuilt;
                    command->key_args.clear();
                    command->key_shards.clear();
                } else if (!normalize_multi_blocking_pop(*command)) {
                    return false;
                }
            }
            if (command->kind == MultiCommandKind::IoLocal &&
                has_name(command->queued, "select")) {
                uint8_t selected = logical_db;
                if (multidb_parse_index(command->op->arg(1), server.cfg().databases, selected))
                    logical_db = selected;
            }
            if (command->kind != MultiCommandKind::Prebuilt &&
                (has_name(command->queued, "mset") || has_name(command->queued, "msetnx")) &&
                (command->queued.argv.size() & 1u) == 0) {
                reply_err(command->op->sink(), has_name(command->queued, "mset")
                    ? "ERR wrong number of arguments for 'mset' command"
                    : "ERR wrong number of arguments for 'msetnx' command");
                command->kind = MultiCommandKind::Prebuilt;
                command->key_args.clear();
                command->key_shards.clear();
            }
            if constexpr (!kSingleDatabase) multidb_stamp(server, *command->op, command->op->db, routing_map);
            if (command->kind == MultiCommandKind::Swapdb) {
                if (!multidb_validate_swap(server, *command->op)) {
                    command->kind = MultiCommandKind::Prebuilt;
                } else {
                    uint8_t first = 0, second = 0;
                    multidb_parse_index(command->op->arg(1), server.cfg().databases, first);
                    multidb_parse_index(command->op->arg(2), server.cfg().databases, second);
                    if (first != second) {
                        command->swap_physical = {routing_map[first], routing_map[second]};
                        state.database_swaps.push_back({first, second, routing_map[first], routing_map[second]});
                        std::swap(routing_map[first], routing_map[second]);
                        ++routing_map.epoch;
                    }
                    reply_ok(command->op->sink());
                    if constexpr (kSingleDatabase) command->kind = MultiCommandKind::Prebuilt;
                }
            }
            if (state.client->resp3()) command->op->mark_resp3();
            if (command->kind == MultiCommandKind::Admin &&
                has_name(command->queued, "debug")) {
                uint64_t sleep_us = 0;
                const auto sleep = debug_sleep_prepare(
                    server, *state.client, *command->op, sleep_us);
                if (sleep == DebugSleepResult::Handled) command->kind = MultiCommandKind::Prebuilt;
                else if (sleep == DebugSleepResult::Deferred) {
                    command->kind = MultiCommandKind::DebugSleep;
                    command->integer.store(sleep_us, std::memory_order_relaxed);
                }
            }
            if (command->kind == MultiCommandKind::Scan &&
                !command_prepare_scan_route(server, *command->op))
                command->kind = MultiCommandKind::Prebuilt;
            if (command->kind == MultiCommandKind::Unsupported &&
                (command->queued.spec->flags &
                 (CmdFlags::MultiShard | CmdFlags::AllShards | CmdFlags::ConfigRoute))) {
                ScatterDispatch child_dispatch;
                const ScatterPrepare prepared = xshard_prepare(
                    server, *command->op, state.scatter_pool, state.owner_io,
                    state.origin_conn_id, child_dispatch, true, state.client);
                if (prepared == ScatterPrepare::Ready) {
                    command->kind = MultiCommandKind::Xshard;
                    command->scatter = child_dispatch.state;
                    if (has_name(command->queued, "move")) {
                        command->key_args.push_back(2);
                        command->key_shards.push_back(server.router().shard_of(
                            FlatStore::hash_key(command->op->arg(2))));
                    }
                    xshard_multi_child_bind(*command->scatter, &state);
                    xshard_multi_child_capture_groups(
                        *command->scatter, command->xshard_stage_groups[0]);
                    for (uint32_t i = 0; i < child_dispatch.nshards; i++)
                        add_shard(command->participants,
                                  xshard_dispatch_shard(child_dispatch, i));
                    // Phase two can route to a STORE/destination owner not present in the initial
                    // dispatch.  Use the lowering's exact key set: registry metadata for LMPOP,
                    // ZMPOP and option-bearing commands intentionally spans non-key arguments.
                    for (uint32_t i = 0; i < command->scatter->key_count; i++)
                        add_shard(command->participants, command->scatter->keys[i].shard);
                    // A dereferencing SORT reads shards no key of this transaction names, and which
                    // are not knowable until the source has been read. It therefore participates in
                    // EVERY shard: shards outside its scatter group hold the barrier only (the
                    // Xshard arm below waits on `finished` for a shard with no group of its own),
                    // which is what orders the dereference after every earlier command everywhere
                    // and before every later one.
                    if (multi_sort_dereferences(command->queued))
                        for (uint32_t sid = 0; sid < server.nshards(); sid++)
                            add_shard(command->participants, static_cast<int32_t>(sid));
                } else if (prepared == ScatterPrepare::Error) {
                    // Validation errors are execution-time array elements, just as they are when
                    // the same syntactically valid command is run outside MULTI.
                    command->kind = MultiCommandKind::Prebuilt;
                    command->key_args.clear();
                    command->key_shards.clear();
                }
            }
            if (command->kind == MultiCommandKind::Swapdb ||
                command->kind == MultiCommandKind::Admin ||
                command->kind == MultiCommandKind::DebugSleep) {
                for (uint32_t sid = 0; sid < server.nshards(); ++sid)
                    add_shard(command->participants, static_cast<int32_t>(sid));
            } else if (command->kind == MultiCommandKind::Local) {
                command->op->shard = command->key_shards[0];
                const uint32_t first = command->key_args[0];
                command->op->hash = FlatStore::hash_key(command->op->arg(first));
                if (command->queued.spec->flags & CmdFlags::MultiShard)
                    command->op->mark_local_xshard();
                add_shard(command->participants, command->key_shards[0]);
            } else if (command->kind == MultiCommandKind::Scan) {
                add_shard(command->participants, command->op->shard);
            } else if (command->kind == MultiCommandKind::Xshard) {
                // xshard_prepare supplied the exact phase-one participant set above.
                command->scatter->pop_reply_shape =
                    static_cast<PopReplyShape>(command->pop_reply_shape);
            } else if (command->kind == MultiCommandKind::Ping ||
                       command->kind == MultiCommandKind::Echo ||
                       command->kind == MultiCommandKind::UnwatchReply ||
                       command->kind == MultiCommandKind::IoLocal ||
                       command->kind == MultiCommandKind::Prebuilt) {
                add_shard(command->participants, 0);
            } else {
                for (int32_t shard : command->key_shards)
                    add_shard(command->participants, shard);
                if (command->participants.empty()) add_shard(command->participants, 0);
            }
            command->shard_done.assign(server.nshards(), 0);
            state.has_publication |= command->kind == MultiCommandKind::IoLocal &&
                (has_name(command->queued, "publish") || has_name(command->queued, "spublish"));
            // SCOPE: multi-owner READ fragments, nothing else.  Mget/Exists are reached only when
            // classify_multi_command already found the key set spanning more than one shard, and an
            // Xshard child carries its own participant count.  A single-owner read resolves inside
            // one owner task and cannot straddle anything (the same-owner control reads zero torn),
            // and a write must keep cloning from the newest committed value, so widening this test
            // would buy no isolation and cost the transaction a floor registration.
            const bool sort_deref_read = command->kind == MultiCommandKind::Xshard &&
                command->scatter && command->scatter->kind == Kind::Sort &&
                command->scatter->sort_options.deref;
            if (sort_deref_read) {
                // STORE makes SORT a write command, but its dynamic BY/GET wave is still a
                // multi-owner read and must borrow the transaction's one registered cut.
                state.exec_read_fanout = true;
            } else if (!(command->queued.spec->flags &
                         (CmdFlags::Write | CmdFlags::SnapshotWrite))) {
                if (command->kind == MultiCommandKind::Mget ||
                    command->kind == MultiCommandKind::Exists)
                    state.exec_read_fanout = true;
                else if (command->kind == MultiCommandKind::Xshard && command->scatter &&
                         command->scatter->nsub > 1)
                    state.exec_read_fanout = true;
            }
            if (command->kind == MultiCommandKind::Mget)
                command->values.resize(command->key_args.size());
            command->pending.store(static_cast<uint32_t>(command->participants.size()),
                                   std::memory_order_relaxed);
            for (size_t i = 0; i < command->key_args.size(); i++) add_write_key(state, *command, i);
            for (int32_t shard : command->participants) add_shard(state.shards, shard);
            const uint32_t command_index = static_cast<uint32_t>(state.commands.size());
            if (command_has_owner_work(*command)) {
                for (int32_t shard : command->participants)
                    state.shard_commands[static_cast<uint32_t>(shard)].push_back(command_index);
            }
            state.commands.push_back(std::move(command));
        }
        if (!state.database_swaps.empty()) {
            state.database_watch.resize(server.nshards());
            if (!server.databases().prepare_publish(routing_map, state.database_publish)) return false;
        }
        prepare_claims(state);
        if (state.read_only && state.shards.size() > 1) state.exec_read_fanout = true;
    } catch (const std::bad_alloc&) {
        return false;
    }
    return true;
}

MultiExecState* allocate_state(Server& server, Client& client, uint32_t owner_io,
                               MultiStateKind kind, uint64_t age_ns = 0) {
    auto* state = new (std::nothrow) MultiExecState;
    if (!state) return nullptr;
    state->decision.owner = state;
    if (kind == MultiStateKind::Execute) {
        state->decision.age_ns = age_ns ? age_ns : now_ns();
        state->decision.age_io = owner_io;
        state->decision.age_seq = ++server.multi_retry_lane(owner_io).age_seq;
    }
    state->server = &server;
    state->client = &client;
    state->owner_io = owner_io;
    state->retry.owner_io = owner_io;
    state->retry.unit = state;
    state->origin_conn_id = client.id();
    state->watch_generation = client.watch_generation();
    state->kind = kind;
    try {
        state->owner_record_refs.assign(server.nthreads(), MultiOwnerRecordRefs{});
        state->owner_retries = std::make_unique<MultiOwnerRetryNode[]>(server.nshards());
        state->shard_commands.resize(server.nshards());
        state->claims.resize(server.nshards());
        state->shard_cursors.assign(server.nshards(), 0);
        state->watch_shard_done.assign(server.nshards(), 0);
        if (kind == MultiStateKind::Execute)
            state->place_blockers = std::make_unique<TxnPlaceBlocker[]>(server.nshards());
        state->execution_joined.assign(server.nshards(), 0);
        state->final_shard_done.assign(server.nshards(), 0);
        state->aof_shard_done.assign(server.nshards(), 0);
        state->execution_noted.assign(server.nshards(), 0);
        state->per_shard_intents.assign(server.nshards(), 0);
        state->shard_aborted = std::make_unique<std::atomic<bool>[]>(server.nshards());
    } catch (const std::bad_alloc&) {
        delete state;
        return nullptr;
    }
    return state;
}

// WRITE_KEYS IS NOT THE SET OF EXECUTORS THAT INSTALL. It is the prepare-time registry key list,
// and a lowered LMPOP/ZMPOP has none: command_key_args() returns nothing for their numkeys form, so
// classify_multi_command() sends them down the Xshard arm and multi_execute_task() calls
// prepare_write_key() at phase two for a key SELECTED THEN, on whichever shard held a non-empty
// list. Deriving sentinels from write_keys therefore left that executor -- and, for a transaction
// whose only write is such a command, EVERY executor -- with no pin, which the install then
// aborted on. The outer task set is the exact and cheaper predicate: every executor that installs
// anything for this transaction must first have been given one of its shard tasks.
bool multi_state_may_install(const MultiExecState& state) {
    for (const auto& command : state.commands) {
        if (!command_has_owner_work(*command)) continue;
        if (command->queued.spec->flags & (CmdFlags::Write | CmdFlags::SnapshotWrite))
            return true;
    }
    return false;
}

void initialize_multi_owner_record_refs(MultiExecState& state) {
    if (state.kind != MultiStateKind::Execute || !multi_state_may_install(state)) return;
    if (state.record_refs.load(std::memory_order_relaxed) != 0 ||
        state.record_refs_precounted) std::abort();

    // Every outer shard task reaches the post-decision completion boundary even when WATCH or
    // EXECABORT skips its commands. Count all such tasks per executor so only its last one releases
    // the sentinel protecting whatever records earlier tasks may have installed.
    uint32_t owners = 0;
    for (int32_t shard : state.shards) {
        const uint32_t tid = state.server->worker_of_shard(shard);
        const uint32_t slot = state.server->executor_slot(tid);
        if (slot >= state.owner_record_refs.size()) std::abort();
        MultiOwnerRecordRefs& progress = state.owner_record_refs[slot];
        if (progress.remaining++) continue;
        if (progress.nodes || progress.completion_sentinel) std::abort();
        progress.nodes = 1;
        progress.completion_sentinel = true;
        owners++;
    }
    if (!owners) std::abort();
    state.record_refs_precounted = true;
    state.record_refs.store(owners, std::memory_order_release);
}

void complete_multi_owner_record_refs(MultiExecState& state, uint32_t owner_thread_id) {
    if (!state.record_refs_precounted) return;
    const uint32_t slot = state.server->executor_slot(owner_thread_id);
    if (slot >= state.owner_record_refs.size()) std::abort();
    MultiOwnerRecordRefs& progress = state.owner_record_refs[slot];
    if (!progress.remaining) std::abort();
    if (--progress.remaining != 0 || !progress.completion_sentinel) return;

    progress.completion_sentinel = false;
    if (!progress.nodes) std::abort();
    if (--progress.nodes == 0 &&
        state.record_refs.fetch_sub(1, std::memory_order_release) == 0) std::abort();
}

void clear_unpublished_multi_record_refs(MultiExecState& state) {
    if (!state.record_refs_precounted) return;
    uint32_t owners = 0;
    for (MultiOwnerRecordRefs& progress : state.owner_record_refs) {
        if (!progress.completion_sentinel) continue;
        // The caller proved no task was published, so only the prepare-time sentinel can be present.
        if (progress.nodes != 1) std::abort();
        progress.nodes = 0;
        progress.completion_sentinel = false;
        owners++;
    }
    if (state.record_refs.load(std::memory_order_relaxed) != owners) std::abort();
    state.record_refs.store(0, std::memory_order_relaxed);
    state.record_refs_precounted = false;
}

MultiExecState* prepare_unwatch_state(Server& server, Client& client, uint32_t owner_io,
                                      MultiSession& session, MultiStateKind kind,
                                      MultiFinalReply reply) {
    MultiExecState* state = allocate_state(server, client, owner_io, kind);
    if (!state) return nullptr;
    state->final_reply = reply;
    state->reset_watch = true;
    state->watched = std::move(session.watched);
    for (const MultiWatchedKey& key : state->watched) add_shard(state->shards, key.shard);
    state->watch_pending.store(static_cast<uint32_t>(state->shards.size()),
                               std::memory_order_relaxed);
    state->lists_pending.store(static_cast<uint32_t>(state->shards.size()),
                               std::memory_order_relaxed);
    state->tasks_pending.store(static_cast<uint32_t>(state->shards.size()),
                               std::memory_order_relaxed);
    return state;
}

void set_state_reply(MultiExecState& state, Op& public_op) {
    if (state.final_reply == MultiFinalReply::ExecDiskError) {
        state.server->aof().reply_write_error(public_op, true);
        return;
    }
    if (state.final_reply == MultiFinalReply::Ok) {
        reply_ok(public_op.sink());
        return;
    }
    if (state.final_reply == MultiFinalReply::ExecAbort) {
        reply_err(public_op.sink(),
                  "EXECABORT Transaction discarded because of previous errors.");
        return;
    }
    if (state.watch_failed.load(std::memory_order_acquire)) {
        reply_null_array(public_op.sink(), public_op.resp3());
        return;
    }
    if (state.decision.aborted.load(std::memory_order_acquire)) {
        reply_err(public_op.sink(), "EXECABORT Transaction discarded because of an execution error.");
        return;
    }
    reply_array_header(public_op.sink(), state.commands.size());
    for (const auto& command : state.commands)
        public_op.reply.append(command->op->reply.data(), command->op->reply.size());
}

void complete_child_zc(Shard& shard, Op& op) {
    if (!op.zc_ptr || op.zc_shard < 0) return;
    op.reply.append(op.zc_ptr, op.zc_len);
    op.reply.append("\r\n", 2);
    shard.store().unborrow(op.zc_ptr);
    op.zc_ptr = nullptr;
    op.zc_len = 0;
    op.zc_shard = -1;
}

bool load_clone(Shard& shard, Slice key, KvObj* visible, KvObj*& clone) {
    clone = nullptr;
    if (!visible) return true;
    ObjectImage image;
    if (!serialize_object(visible, image)) return false;
    return load_object_image(key, image, shard.type_limits(), clone) ==
               SnapshotHookStatus::Ok && clone;
}

// Violations of the install-time ordering invariant asserted in prepare_write_key() below. It is a
// bug counter, not a workload counter: every battery that exercises a transaction behind an
// undecided same-connection unit asserts it is EXACTLY zero, in both atomic modes. Namespace scope
// rather than Shard::Stats because Shard's layout is locked (sizeof(Shard) == 1440) and because a
// counter that is never incremented needs no per-shard line of its own.
// Internal linkage is right for the counter itself -- prepare_write_key() below is its only
// writer, and it lives in this file's anonymous namespace with the rest of the transaction
// helpers. The READER that INFO calls cannot: it is declared in multi.h and defined out beyond
// this anonymous namespace, next to multi_task_owns_epoch().
std::atomic<uint64_t> g_exec_order_late{0};

bool multi_touch_key(MultiExecState& state, Shard& shard, uint64_t hash, Slice key,
                     bool, bool wildcard = false) {
    if (state.read_only) return true;
    if (state.decision.aborted.load(std::memory_order_acquire)) return false;
    Server& server = *state.server;
    bool ready = true;
    shard.store().atomic_visit_unit_records(hash, key, wildcard, [&](AtomicEntry& entry) {
        if (multi_state_owns_epoch(state, entry.group_epoch)) return;
        uint64_t epoch = entry.group_epoch
            ? entry.group_epoch->load(std::memory_order_acquire) : entry.epoch;
        if (auto* decision = multi_record_decision(entry)) {
            epoch = decision->epoch.load(std::memory_order_acquire);
            multi_help_child(entry, epoch);
            if (decision->aborted.load(std::memory_order_acquire)) return;
        }
        if (epoch == kAtomicCancelledEpoch ||
            (entry.group_aborted && entry.group_aborted->load(std::memory_order_acquire))) return;
        if (!epoch && entry.group && entry.group->kind == Kind::Script) {
            multi_cancel_record(entry);
            epoch = entry.group_epoch->load(std::memory_order_acquire);
            if (epoch == kAtomicCancelledEpoch) return;
        }
        if (!epoch) {
            // Placement forbids every live foreign candidate at execution.
            server.note_txn(server.worker_of_shard(shard.id()), TxnCounter::OrderViolations);
            if (entry.origin_conn_id == state.origin_conn_id)
                g_exec_order_late.fetch_add(1, std::memory_order_relaxed);
            ready = false;
        } else if (entry.origin_conn_id != state.origin_conn_id &&
                   epoch > server.atomic_snapshot() &&
                   !(server.atomic_publish_quiescent() && epoch <= server.atomic_snapshot())) {
            server.note_txn(server.worker_of_shard(shard.id()), TxnCounter::Waits);
            ready = false;
        }
    });
    return ready;
}

enum class TxnBlind : uint8_t { Clear, Completing, Crossing };
TxnBlind txn_blind_scan(Shard& shard, const std::vector<TxnClaim>& claims,
                        const void* own = nullptr) {
    if (!shard.store().atomic_may_have_blind_records()) {
        if (auto* server = shard.server())
            ++exec1s_counters[server->worker_of_shard(shard.id())].blind_clear;
        return TxnBlind::Clear;
    }
    TxnBlind result = TxnBlind::Clear;
    for (const auto& claim : claims)
        shard.store().atomic_visit_unit_records(claim.hash, txn_claim_slice(claim),
            claim.key.empty(), [&](AtomicEntry& entry) {
                if (!entry.group || entry.group == own || entry.group->multi_parent == own ||
                    entry.group->multi_child || entry.group->kind == Kind::Script) return;
                const auto* attempt = entry.group->group_attempt();
                if (attempt && attempt->age_ns) return; // TO-B unit: arbitrated by claims
                if (entry.group->epoch.load(std::memory_order_acquire) ||
                    entry.group->aborted.load(std::memory_order_acquire)) return;
                if (entry.group->pending.load(std::memory_order_acquire))
                    result = TxnBlind::Crossing;
                else if (result == TxnBlind::Clear) result = TxnBlind::Completing;
            });
    return result;
}

enum class MultiPrepareWrite : uint8_t { Ready, Retry, Error };

MultiPrepareWrite prepare_write_key(Server& server, MultiExecState& state, Shard& shard,
                                    Slice key, uint64_t hash, uint32_t owner_thread_id,
                                    const void* watch_token = nullptr,
                                    std::atomic<uint32_t>* watch_refs = nullptr,
                                    bool signal_watch = true) {
    if (!watch_token) watch_token = &state;
    if (!multi_touch_key(state, shard, hash, key, true)) return MultiPrepareWrite::Retry;
    if (!watch_refs) watch_refs = &state.watch_refs;
    // THE FALSIFIER, and it must read ZERO. It asks EXACTLY the question the dispatch-time park in
    // ExLoop::execute() asks -- does this owner still hold an undecided record belonging to a
    // DIFFERENT logical unit of this connection? -- but asks it one step later, at install time.
    // The park is supposed to foreclose it completely, because only this owner thread may publish
    // into this owner's pending list, so nothing can appear between the dispatch check and these
    // installs. A non-zero reading is therefore not a statistic: it is proof that the park's
    // safety argument is false on this build, and that a transaction could
    // again clone a withdrawable candidate into an acknowledged write.
    //
    // It counts into its OWN counter, deliberately. Sharing atomic_exec_order_holds with the park
    // would make this arm unreadable: the park is non-zero BY DESIGN in exactly the runs that open
    // the window, so a sum can never be checked against zero and the falsifier would be inert --
    // the safety argument would break with no test going red. Split, each counter answers one
    // question: holds > 0 proves the hold fired, late == 0 proves it fired EARLY ENOUGH.
    // Not a Shard::Stats field because Shard's layout is locked at 1440 bytes; a namespace-scope
    // atomic costs nothing here, since the increment is on a path that is never taken.
    //
    // Holding the transaction HERE deadlocked with one connection and no WATCH (0 rounds versus
    // 300 on base): the older group could wait on the transaction's partial installs while the
    // transaction waited on that group. The dispatch-time park is safe because the fragment has
    // installed nothing on this owner, so it cannot give the older group a reason to wait here.
    // The exclusion is BY EPOCH WORD and must cover the transaction's lowered children as well as
    // its own: a cross-shard child installs through the scatter path with its own ScatterState,
    // and counting that would report a violation every time a transaction merely met its own
    // RENAME/LMPOP child.
    if (__builtin_expect(shard.store().atomic_has_records(), false) &&
        shard.store().atomic_has_foreign_unit_undecided(
            state.origin_conn_id,
            [&state](const void* group_epoch) {
                return multi_state_owns_epoch(state, group_epoch);
            }))
        g_exec_order_late.fetch_add(1, std::memory_order_relaxed);
    if (!shard.watch_txn_write_ready(key, state)) return MultiPrepareWrite::Retry;
    // Placement reserves ordering; actual command effects signal the mutation.
    (void)signal_watch;
    const auto snapshot = shard.store().snapshot_prepare_write(hash, key);
    if (snapshot == FlatStore::SnapshotWriteResult::Pending) return MultiPrepareWrite::Retry;
    if (snapshot == FlatStore::SnapshotWriteResult::Error) return MultiPrepareWrite::Error;
    if (!shard.store().atomic_prepare_capacity(1)) return MultiPrepareWrite::Error;

    shard.store().atomic_set_read_context(UINT64_MAX, state.origin_conn_id);
    KvObj* visible = shard.store().find(hash, key);
    KvObj* clone = nullptr;
    if (!load_clone(shard, key, visible, clone)) {
        shard.store().atomic_clear_read_epoch();
        return MultiPrepareWrite::Error;
    }
    if (!shard.store().atomic_admit(key, clone)) {
        if (clone) kvobj_free(clone);
        shard.store().atomic_clear_read_epoch();
        return MultiPrepareWrite::Error;
    }
    const uint32_t slot = server.executor_slot(owner_thread_id);
    if (slot >= state.owner_record_refs.size()) std::abort();
    MultiOwnerRecordRefs& owner_progress = state.owner_record_refs[slot];
    uint32_t* owner_refs = &owner_progress.nodes;
    void* entry = nullptr;
    if (!shard.store().atomic_prepare_transaction(
            key, hash, state.origin_conn_id, &state.decision.epoch, &state.record_refs,
            &state.shard_aborted[shard.id()], owner_refs, entry)) {
        shard.store().atomic_unadmit(clone);
        if (clone) kvobj_free(clone);
        shard.store().atomic_clear_read_epoch();
        return MultiPrepareWrite::Error;
    }
    KvObj* installed = clone;
    shard.store().atomic_install_transaction(hash, key, entry, installed);
    // INVARIANT, not a hope: initialize_multi_owner_record_refs() gave every executor holding an
    // outer task of an installing transaction its sentinel before the first task became visible,
    // and this executor is running one of those tasks. A missing pin here would mean cleanup could
    // release the state's last reference between two of this owner's own installs.
    if (!owner_progress.completion_sentinel || !*owner_refs) std::abort();
    (*owner_refs)++;
    // Keep the transaction overlay selected for the handler and later keys in this command.
    shard.store().atomic_set_read_context(UINT64_MAX, state.origin_conn_id);
    return MultiPrepareWrite::Ready;
}

bool command_has_owner_work(const MultiCommand& command) {
    return command.kind != MultiCommandKind::Ping &&
           command.kind != MultiCommandKind::Echo &&
           command.kind != MultiCommandKind::UnwatchReply &&
           command.kind != MultiCommandKind::IoLocal &&
           command.kind != MultiCommandKind::Prebuilt &&
           command.kind != MultiCommandKind::Unsupported;
}

bool prepare_local_write_keys(Server& server, MultiExecState& state, MultiCommand& command,
                              Shard& shard, uint32_t owner_thread_id) {
    if (!(command.queued.spec->flags & (CmdFlags::Write | CmdFlags::SnapshotWrite))) return true;
    // The common one-key command needs no duplicate-index allocation. Keep the
    // full preflight-before-install order for the less common multi-key handler.
    const uint32_t single = command.key_args.empty() ? 0 : command.key_args.front();
    std::vector<uint32_t> storage;
    const uint32_t* unique = &single;
    size_t count = command.key_args.size();
    if (count == 1) {
        if (command.key_shards.front() != shard.id()) return true;
    } else {
        try { storage.reserve(count); }
        catch (const std::bad_alloc&) { state.decision.aborted.store(true, std::memory_order_release); return false; }
        for (size_t i = 0; i < command.key_args.size(); i++) {
            if (command.key_shards[i] != shard.id()) continue;
            const uint32_t arg = command.key_args[i];
            bool duplicate = false;
            for (uint32_t prior : storage)
                duplicate |= command.op->arg(prior).key_mem_eq(command.op->arg(arg));
            if (!duplicate) storage.push_back(arg);
        }
        unique = storage.data();
        count = storage.size();
    }
    // Multi-key handlers must preflight every key before the first install.
    // For one key, prepare_write_key already performs these checks before its
    // only install, including the ordering falsifiers and snapshot retry.
    for (size_t i = 0; count > 1 && i < count; ++i) {
        const uint32_t arg = unique[i];
        const Slice key = command.op->arg(arg);
        const uint64_t hash = FlatStore::hash_key(key);
        if (!multi_touch_key(state, shard, hash, key, true) ||
            !shard.watch_txn_write_ready(key, state)) return false;
        const auto snapshot = shard.store().snapshot_prepare_write(hash, key);
        if (snapshot == FlatStore::SnapshotWriteResult::Pending) return false;
        if (snapshot == FlatStore::SnapshotWriteResult::Error) {
            state.decision.aborted.store(true, std::memory_order_release);
            return false;
        }
    }
    for (size_t i = 0; i < count; ++i) {
        const uint32_t arg = unique[i];
        const Slice key = command.op->arg(arg);
        const MultiPrepareWrite result = prepare_write_key(
            server, state, shard, key, command.key_args.size() == 1
                ? command.op->hash : FlatStore::hash_key(key), owner_thread_id,
            nullptr, nullptr, !has_name(command.queued, "xreadgroup"));
        if (result == MultiPrepareWrite::Retry) return false;
        if (result == MultiPrepareWrite::Error) {
            state.decision.aborted.store(true, std::memory_order_release);
            return false;
        }
    }
    return true;
}

// Read-only units borrow MGET's registered cut. Write units read newest committed
// under their claims and enforce the publication watermark through rule P.
uint64_t multi_read_cut(const MultiExecState& state) {
    return state.read_only ? state.snapshot : UINT64_MAX;
}

uint64_t multi_tripwire_slot(const Shard& shard, size_t key_index) {
    return (static_cast<uint64_t>(static_cast<uint32_t>(shard.id())) << 32) |
           static_cast<uint32_t>(key_index);
}

void multi_tripwire_fragment_begin(MultiExecState& state, Shard& shard) {
    if (!atomic_tripwire_enabled()) return;
    const uint32_t shard_id = static_cast<uint32_t>(shard.id());
    const uint64_t cut = multi_read_cut(state);
    for (uint32_t command_index : state.shard_commands[shard_id]) {
        MultiCommand& command = *state.commands[command_index];
        if (command.kind != MultiCommandKind::Mget &&
            command.kind != MultiCommandKind::Exists)
            continue;
        for (size_t i = 0; i < command.key_args.size(); i++) {
            if (command.key_shards[i] != shard.id()) continue;
            const Slice key = command.op->arg(command.key_args[i]);
            const uint64_t hash = FlatStore::hash_key(key);
            atomic_tripwire_plain_begin(
                &state, &command, multi_tripwire_slot(shard, i), hash, cut,
                shard.store().atomic_tripwire_ticket(hash, key),
                shard.store().atomic_needs_version(hash, key));
        }
    }
}

void multi_tripwire_read_execution(MultiExecState& state, MultiCommand& command,
                                   Shard& shard, size_t key_index, Slice key) {
    if (!atomic_tripwire_enabled()) return;
    const uint64_t hash = FlatStore::hash_key(key);
    atomic_tripwire_plain_execution(
        &state, &command, multi_tripwire_slot(shard, key_index), hash, multi_read_cut(state),
        shard.store().atomic_tripwire_ticket(hash, key),
        shard.store().atomic_needs_version(hash, key),
        shard.store().atomic_tripwire_plain_path());
}

bool execute_local_command(Server& server, MultiExecState& state, MultiCommand& command,
                           Shard& shard, uint32_t owner_thread_id) {
    if (!(command.queued.spec->flags & (CmdFlags::Write | CmdFlags::SnapshotWrite))) {
        if (has_name(command.queued, "scan")) {
            if (!multi_touch_key(state, shard, 0, {}, false, true)) return false;
        } else for (size_t i = 0; i < command.key_args.size(); ++i) {
            if (command.key_shards[i] != shard.id()) continue;
            const Slice key = command.op->arg(command.key_args[i]);
            if (!multi_touch_key(state, shard, FlatStore::hash_key(key), key, false)) return false;
        }
    }
    if (function_is_fcall(*command.op)) {
        WatchMutationScope watch_scope(shard, &state, &state.decision.epoch,
            &state.decision.aborted, &state.watch_refs, state.client);
        struct Context {
            Server& server; MultiExecState& state; MultiCommand& command;
            Shard& shard; uint32_t owner;
        } context{server, state, command, shard, owner_thread_id};
        const bool completed = function_execute_exec(shard, *command.op, &context, [](void* raw) {
            auto& c = *static_cast<Context*>(raw);
            if (!prepare_local_write_keys(c.server, c.state, c.command, c.shard, c.owner))
                return false;
            if (c.command.op->spec->flags & CmdFlags::NotifySelected)
                notify_execute_source(c.shard, *c.command.op, c.command.notify_order_base);
            c.shard.store().atomic_set_read_context(multi_read_cut(c.state), c.state.origin_conn_id);
            return true;
        });
        if (completed) complete_child_zc(shard, *command.op);
        shard.store().atomic_clear_read_epoch();
        return completed;
    }
    if (!prepare_local_write_keys(server, state, command, shard, owner_thread_id)) return false;
    if (command.op->spec->flags & CmdFlags::NotifySelected)
        notify_execute_source(shard, *command.op, command.notify_order_base);
    shard.store().atomic_set_read_context(multi_read_cut(state), state.origin_conn_id);
    {
        WatchMutationScope watch_scope(shard, &state, &state.decision.epoch,
            &state.decision.aborted, &state.watch_refs, state.client);
        if (shard.has_watches()) watch_execute_handler(shard, *command.op);
        else command.op->spec->handler(shard, *command.op);
    }
    complete_child_zc(shard, *command.op);
    shard.store().atomic_clear_read_epoch();
    return true;
}

bool execute_cross_command(Server& server, MultiExecState& state, MultiCommand& command,
                           Shard& shard, uint32_t owner_thread_id, uint32_t stage) {
    // ConfigRoute's keyless handlers run once, on shard 0's owner, between two all-owner
    // joins. In particular CONFIG GET before CONFIG SET must not run at reply retirement.
    // DEBUG SLEEP requests the global pause after the first all-owner join.
    if (command.kind == MultiCommandKind::Admin || command.kind == MultiCommandKind::DebugSleep) {
        if (stage == 0) return true;
        if (command.kind == MultiCommandKind::DebugSleep)
            return debug_sleep_exec(server, shard, command.integer, owner_thread_id);
        if (shard.id() == 0) {
            Client* previous_client = command_local_client();
            ThreadCtx* previous_thread = command_local_thread();
            command_set_local_context(state.client, &server.thread(owner_thread_id));
            {
        WatchMutationScope watch_scope(shard, &state, &state.decision.epoch,
            &state.decision.aborted, &state.watch_refs, state.client);
        if (shard.has_watches()) watch_execute_handler(shard, *command.op);
        else command.op->spec->handler(shard, *command.op);
    }
            command_set_local_context(previous_client, previous_thread);
        }
        return true;
    }
    // All children already name the physical keys implied by preceding swaps.
    // Join all shards here; the map itself changes only at the commit decision.
    if (command.kind == MultiCommandKind::Swapdb) {
        uint8_t first = 0, second = 0;
        multidb_parse_index(command.op->arg(1), server.cfg().databases, first);
        multidb_parse_index(command.op->arg(2), server.cfg().databases, second);
        if (first == second) return true;
        // Capture the key's presence AT this command, including prior private
        // writes. Later commands may delete it or swap it away again. Publish
        // these invalidations only when the whole transaction commits.
        shard.store().atomic_set_read_context(multi_read_cut(state), state.origin_conn_id);
        const bool ok = shard.watch_database_swap(first, second,
            command.swap_physical[0], command.swap_physical[1], &state.database_watch[shard.id()]);
        shard.store().atomic_clear_read_epoch();
        if (!ok) state.decision.aborted.store(true, std::memory_order_release);
        return true;
    }
    Op& op = *command.op;
    const bool notify = (op.spec->flags & CmdFlags::NotifySelected) != 0 || shard.has_watches();
    WatchMutationScope watch_scope(shard, &state, &state.decision.epoch,
        &state.decision.aborted, &state.watch_refs, state.client);
    if (notify)
        notify_execute_source(shard, op, command.notify_order_base);
    const bool read_kind = command.kind == MultiCommandKind::Mget ||
                           command.kind == MultiCommandKind::Exists ||
                           (command.kind == MultiCommandKind::Msetnx && stage == 0);
    // All touches precede this command's first install on this shard.
    for (size_t i = 0; i < command.key_args.size(); ++i) {
        if (command.key_shards[i] != shard.id()) continue;
        const Slice key = op.arg(command.key_args[i]);
        if (!multi_touch_key(state, shard, FlatStore::hash_key(key), key, !read_kind) ||
            (!read_kind && !shard.watch_txn_write_ready(key, state))) return false;
    }
    shard.store().atomic_set_read_context(multi_read_cut(state), state.origin_conn_id);
    if (command.kind == MultiCommandKind::Mget) {
        for (size_t i = 0; i < command.key_args.size(); i++) {
            if (command.key_shards[i] != shard.id()) continue;
            const uint32_t arg = command.key_args[i];
            const Slice key = op.arg(arg);
            if (__builtin_expect(atomic_tripwire_enabled(), false))
                multi_tripwire_read_execution(state, command, shard, i, key);
            KvObj* object = notify
                ? shard.store_find_read<true>(FlatStore::hash_key(key), key)
                : shard.store_find_read<false>(FlatStore::hash_key(key), key);
            if (!object || static_cast<Type>(object->type) != Type::String) continue;
            MultiValue& value = command.values[i];
            if (object->is_int()) {
                char text[24];
                const uint32_t n = i64_to_dec(text, object->int_value());
                value.value.assign(text, n);
            } else {
                KvObjRawReadBuffer raw;
                const Slice bytes = kvobj_string_value(object, raw);
                value.value.assign(bytes.p, bytes.n);
            }
            value.present = true;
        }
    } else if (command.kind == MultiCommandKind::Mset ||
               (command.kind == MultiCommandKind::Msetnx && stage == 1)) {
        for (size_t i = 0; i < command.key_args.size(); i++) {
            if (command.key_shards[i] != shard.id()) continue;
            const uint32_t arg = command.key_args[i];
            const Slice key = op.arg(arg);
            const MultiPrepareWrite prepared = prepare_write_key(
                server, state, shard, key, FlatStore::hash_key(key), owner_thread_id);
            if (prepared == MultiPrepareWrite::Retry) {
                shard.store().atomic_clear_read_epoch();
                return false;
            }
            if (prepared == MultiPrepareWrite::Error) {
                state.decision.aborted.store(true, std::memory_order_release);
                break;
            }
            const WorkError stored = store_xstring_selected(
                notify, shard, key, FlatStore::hash_key(key), op.arg(arg + 1));
            if (stored != WorkError::None) {
                state.decision.aborted.store(true, std::memory_order_release);
                break;
            }
            if (notify) notify_record(shard, op, NOTIFY_STRING, NotifyEventId::Set, key);
        }
    } else if (command.kind == MultiCommandKind::Msetnx) {
        for (size_t i = 0; i < command.key_args.size(); i++) {
            if (command.key_shards[i] != shard.id()) continue;
            const uint32_t arg = command.key_args[i];
            const Slice key = op.arg(arg);
            if (notify ? shard.store_find<true>(FlatStore::hash_key(key), key)
                       : shard.store().find(FlatStore::hash_key(key), key))
                command.condition_failed.store(true, std::memory_order_release);
        }
    } else if (command.kind == MultiCommandKind::Del) {
        long long removed = 0;
        for (size_t i = 0; i < command.key_args.size(); i++) {
            if (command.key_shards[i] != shard.id()) continue;
            const uint32_t arg = command.key_args[i];
            const Slice key = op.arg(arg);
            const MultiPrepareWrite prepared = prepare_write_key(
                server, state, shard, key, FlatStore::hash_key(key), owner_thread_id);
            if (prepared == MultiPrepareWrite::Retry) {
                shard.store().atomic_clear_read_epoch();
                return false;
            }
            if (prepared == MultiPrepareWrite::Error) {
                state.decision.aborted.store(true, std::memory_order_release);
                break;
            }
            removed += notify ? shard.store_erase<true>(FlatStore::hash_key(key), key)
                              : shard.store().erase(FlatStore::hash_key(key), key);
        }
        command.integer.fetch_add(removed, std::memory_order_relaxed);
    } else if (command.kind == MultiCommandKind::Exists) {
        LookupNoTouch no_touch(shard.store(), op.cmd_name().eq_icase("exists"));
        long long found = 0;
        for (size_t i = 0; i < command.key_args.size(); i++) {
            if (command.key_shards[i] != shard.id()) continue;
            const uint32_t arg = command.key_args[i];
            const Slice key = op.arg(arg);
            if (__builtin_expect(atomic_tripwire_enabled(), false))
                multi_tripwire_read_execution(state, command, shard, i, key);
            found += (notify ? shard.store_find_read<true>(FlatStore::hash_key(key), key)
                             : shard.store_find_read<false>(FlatStore::hash_key(key), key)) != nullptr;
        }
        command.integer.fetch_add(found, std::memory_order_relaxed);
    }
    shard.store().atomic_clear_read_epoch();
    return true;
}

void assemble_cross_reply(MultiCommand& command) {
    Op& op = *command.op;
    if (command.kind == MultiCommandKind::Mget) {
        reply_array_header(op.sink(), command.values.size());
        for (const MultiValue& value : command.values) {
            if (!value.present) reply_null(op.sink(), op.resp3());
            else reply_bulk(op.sink(), Slice(value.value.data(),
                                              static_cast<uint32_t>(value.value.size())));
        }
    } else if (command.kind == MultiCommandKind::Mset) {
        reply_ok(op.sink());
    } else if (command.kind == MultiCommandKind::Msetnx) {
        reply_int(op.sink(), command.condition_failed.load(std::memory_order_acquire) ? 0 : 1);
    } else if (command.kind == MultiCommandKind::Del ||
               command.kind == MultiCommandKind::Exists) {
        reply_int(op.sink(), command.integer.load(std::memory_order_relaxed));
    } else if (command.kind == MultiCommandKind::Ping) {
        if (op.argc() == 1) reply_pong(op.sink());
        else reply_bulk(op.sink(), op.arg(1));
    } else if (command.kind == MultiCommandKind::Echo) {
        reply_bulk(op.sink(), op.arg(1));
    } else if (command.kind == MultiCommandKind::UnwatchReply ||
               command.kind == MultiCommandKind::DebugSleep) {
        reply_ok(op.sink());
    } else {
        reply_err(op.sink(), "ERR command is not supported by MULTI execution");
    }
}

bool execute_watch_phase(MultiExecState& state, Shard& shard,
                         const MultiRetryPromoter* promoter = nullptr) {
    if (state.watch_shard_done[static_cast<uint32_t>(shard.id())]) return true;
    if (state.kind == MultiStateKind::Execute && !state.read_only &&
        state.final_reply != MultiFinalReply::ExecAbort &&
        !state.decision.aborted.load(std::memory_order_acquire)) {
        uint8_t& noted = state.execution_noted[shard.id()];
        if (state.shards.size() != 1 && !(noted & 4u)) {
            // No shard holds anything until every participant has passed
            // program order and its blind-candidate arrival scan.
            if (txn_blind_scan(shard, state.claims[shard.id()], &state) != TxnBlind::Clear)
                return false;
            noted |= 4u;
            state.watch_arrived.fetch_add(1, std::memory_order_acq_rel);
        }
        if (state.shards.size() != 1 &&
            state.watch_arrived.load(std::memory_order_acquire) != state.shards.size()) return false;
        if (state.debug_place_deadline && shard.id() != state.shards.front() &&
            now_ns() < state.debug_place_deadline) return false;
        const auto blind = txn_blind_scan(shard, state.claims[shard.id()], &state);
        if (blind == TxnBlind::Completing) return false;
        if (blind == TxnBlind::Crossing) {
            TxnPhase placing = TxnPhase::Placing;
            if (state.decision.phase.compare_exchange_strong(placing, TxnPhase::Wounded,
                                                             std::memory_order_acq_rel)) {
                state.backoff.store(true, std::memory_order_relaxed);
                multi_cancel_decision(state.decision, shard.id(), TxnCounter::BlindRestarts);
            }
        } else {
            Shard::WatchReservation claim{&state, &state.decision.epoch, &state.decision.aborted,
                &state.watch_refs, state.client, state.watch_generation, false, true};
            claim.unit_kind = 1;
            if (!shard.watch_place_unit(state.claims[shard.id()], claim, promoter)) return false;
            noted |= 16u; // placed, including a subsequent WATCH validation wait
        }
    }
    if (state.kind == MultiStateKind::WatchAdd) {
        for (const MultiWatchedKey& watched : state.watched) {
            if (watched.shard != shard.id()) continue;
            const Slice key(watched.key.data(), static_cast<uint32_t>(watched.key.size()), watched.ns);
            if (!shard.watch_add(key, state.client, state.watch_generation, watched.db)) return false;
        }
    } else if (state.kind == MultiStateKind::Execute &&
               !state.decision.aborted.load(std::memory_order_acquire)) {
        for (const MultiWatchedKey& watched : state.watched) {
            if (watched.shard != shard.id()) continue;
            // Inactive namespace aliases detect a later SWAPDB, but do not reserve
            // another logical database or observe its deadline during EXEC.
            if (state.database_map[watched.db] != watched.ns) continue;
            const Slice key(watched.key.data(), static_cast<uint32_t>(watched.key.size()), watched.ns);
            if (!shard.watch_validate_and_reserve(
                    key, state.client, state.watch_generation, &state, &state.decision.epoch,
                    &state.decision.aborted, &state.watch_refs,
                    state_writes_key(state, watched), &state, !state.read_only)) return false;
        }
        if (state.client->watch_dirty()) {
            state.watch_failed.store(true, std::memory_order_release);
            state.decision.aborted.store(true, std::memory_order_release);
        }
    } else if (state.kind != MultiStateKind::Execute) {
        for (const MultiWatchedKey& watched : state.watched) {
            if (watched.shard != shard.id()) continue;
            // A prior atomic writer may have completed its owner pass while its global decision is
            // still unpublished.  Keep UNWATCH/DISCARD/close behind that decision so removing the
            // last watcher also releases the reservation's state-lifetime pin.
            if (!shard.watch_write_ready(
                    Slice(watched.key.data(), static_cast<uint32_t>(watched.key.size()), watched.ns)))
                return false;
            shard.watch_remove(Slice(watched.key.data(), static_cast<uint32_t>(watched.key.size()), watched.ns),
                               state.client, state.watch_generation);
        }
    }
    state.watch_shard_done[static_cast<uint32_t>(shard.id())] = 1;
    if (state.watch_pending.fetch_sub(1, std::memory_order_acq_rel) == 1) {
        if (state.kind == MultiStateKind::Execute &&
            state.final_reply != MultiFinalReply::ExecAbort &&
            !state.decision.aborted.load(std::memory_order_acquire)) {
            TxnPhase placing = TxnPhase::Placing;
            if (state.decision.phase.compare_exchange_strong(placing, TxnPhase::Executing,
                                                             std::memory_order_acq_rel))
                state.server->note_txn(state.server->worker_of_shard(shard.id()),
                                       state.read_only ? TxnCounter::Readonly : TxnCounter::Executed);
            else state.decision.aborted.store(true, std::memory_order_release);
        }
        state.watch_phase_done.store(true, std::memory_order_release);
    }
    return true;
}

void finalize_reservations(MultiExecState& state, Shard& shard,
                           const MultiRetryPromoter* promoter = nullptr) {
    if (state.final_shard_done[static_cast<uint32_t>(shard.id())]) return;
    if (state.place_blockers) state.place_blockers[shard.id()].clear();
    // A claim-skipped serve needs another owner sweep after either decision.
    // The periodic blocking beat alone does not revisit clean registries.
    if (shard.has_blocking_waiters()) shard.set_blocking_dirty();
    state.shard_aborted[shard.id()].store(
        state.decision.aborted.load(std::memory_order_acquire), std::memory_order_release);
    const uint32_t intents = shard.store().atomic_unit_unpin(&state);
    state.server->note_txn(state.server->worker_of_shard(shard.id()),
                           TxnCounter::IntentsLive, uint64_t{0} - intents);
    shard.watch_finish_unit(state.claims[shard.id()], &state, promoter);
    if (!state.database_watch.empty()) {
        auto& targets = state.database_watch[shard.id()];
        const bool committed = !state.decision.aborted.load(std::memory_order_acquire);
        for (auto [client, generation] : targets) {
            if (committed && client->watch_generation() == generation) client->set_watch_dirty();
            client->watch_unref();
        }
        targets.clear();
    }
    for (const MultiWatchedKey& watched : state.watched) {
        if (watched.shard != shard.id()) continue;
        const Slice key(watched.key.data(), static_cast<uint32_t>(watched.key.size()), watched.ns);
        if (!watched.claim_finalizes) shard.watch_write_ready(key, nullptr);
        // Cancellation discards only an attempt. Keep the original watch entry
        // and deadline so a write between attempts still gives EXEC's legal null.
        if (!state.doomed && state.kind == MultiStateKind::Execute)
            shard.watch_remove(key, state.client, state.watch_generation);
    }
    for (const MultiWriteKey& write : state.write_keys) {
        if (write.shard != shard.id() || write.claim_finalizes) continue;
        shard.watch_write_ready(
            Slice(write.key.data(), static_cast<uint32_t>(write.key.size()), write.ns), nullptr);
    }
    state.final_shard_done[static_cast<uint32_t>(shard.id())] = 1;
}

void finish_command(MultiCommand& command, uint32_t stage, uint32_t /*owner_thread_id*/) {
    if (command.pending.fetch_sub(1, std::memory_order_acq_rel) != 1) return;
    if (stage == 0 && (command.kind == MultiCommandKind::Admin ||
                       command.kind == MultiCommandKind::DebugSleep)) {
        command.pending.store(static_cast<uint32_t>(command.participants.size()),
                              std::memory_order_relaxed);
        command.stage.store(1, std::memory_order_release);
        return;
    }
    if (command.kind == MultiCommandKind::Msetnx && stage == 0 &&
        !command.condition_failed.load(std::memory_order_acquire)) {
        command.pending.store(static_cast<uint32_t>(command.participants.size()),
                              std::memory_order_relaxed);
        command.stage.store(1, std::memory_order_release);
        return;
    }
    if (command.kind != MultiCommandKind::Local &&
        command.kind != MultiCommandKind::Scan &&
        command.kind != MultiCommandKind::IoLocal &&
        command.kind != MultiCommandKind::Admin &&
        command.kind != MultiCommandKind::Swapdb &&
        command.kind != MultiCommandKind::Prebuilt) assemble_cross_reply(command);
    command.finished.store(true, std::memory_order_release);
}

void assemble_ownerless_replies(MultiExecState& state, uint32_t owner_thread_id) {
    for (const auto& command : state.commands) {
        if (command_has_owner_work(*command) ||
            command->kind == MultiCommandKind::IoLocal ||
            command->kind == MultiCommandKind::Prebuilt)
            continue;
        LatencyTrackingPart latency(owner_thread_id, command->op.get());
        assemble_cross_reply(*command);
    }
}

// INFO's bare physical census cannot see transaction-private inserts/deletes or TTL changes.
// Use the same physical/side-key split as DBSIZE, resolving pending images at EXEC's read cut.
// Stable expired physical keys remain counted, as Redis INFO does; this walk never reaps them.
__attribute__((noinline)) void multi_collect_database_stats(
        MultiExecState& state, MultiCommand& command, Shard& shard) {
    auto& group = *group_for(*command.scatter, shard.id());
    try {
        if (!group.aux) group.aux = new GroupAux;
        if (!group.aux->database_stats)
            group.aux->database_stats = std::make_unique<DatabaseStatsTable>();
    } catch (const std::bad_alloc&) {
        group.error = WorkError::Oom;
        return;
    }
    multi_database_stats(shard, *group.aux->database_stats,
                         command.scatter->snapshot, state.origin_conn_id);
}

// A transaction is one commit ticket but not one runtime-error bit. Each xshard child keeps its
// own abort word so a normal command failure can hide that child's partially installed candidates
// while the other queued commands still commit, as Redis EXEC semantics require. The Server helper
// calls the commit arm before its safe watermark publication, so no reader can observe only a
// subset of these epoch stores.
void publish_multi_child_epochs(MultiExecState& state, uint64_t ticket) {
    for (const auto& command : state.commands)
        if (command->scatter)
            command->scatter->epoch.store(ticket, std::memory_order_release);
}

void abort_multi_children(MultiExecState& state) {
    // EXECABORT also decides the parent's WATCH reservations. Without this
    // publication a queue-time error leaves epoch=0/aborted=false forever.
    state.decision.aborted.store(true, std::memory_order_release);
    for (const auto& command : state.commands)
        if (command->scatter)
            command->scatter->aborted.store(true, std::memory_order_release);
}

}  // namespace

bool multi_queueing(const Client& client) {
    return client.multi_session() && client.multi_session()->active;
}

void multi_mark_queue_error(Client& client) {
    MultiSession* session = client.multi_session();
    if (session && session->active) session->queue_error = true;
}

MultiIoAction multi_handle_io(Server& server, Client& client, Op& op, uint32_t owner_io,
                              MultiExecState*& dispatch) {
    dispatch = nullptr;
    MultiSession* session = client.multi_session();
    if (session && session->pending) {
        dispatch = session->pending;
        return MultiIoAction::Dispatch;
    }

    if (multi_name(op, "multi")) {
        session = ensure_multi_session(client);
        if (!session) {
            reply_err(op.sink(), "ERR out of memory");
        } else if (session->active) {
            reply_err(op.sink(), "ERR MULTI calls can not be nested");
        } else {
            session->active = true;
            session->queue_error = false;
            session->next_queue_op_id = client.rob().dispatch_id() + 1;
            session->clear_queue();
            reply_ok(op.sink());
        }
        return MultiIoAction::LocalDone;
    }

    if (multi_name(op, "watch")) {
        session = ensure_multi_session(client);
        if (!session) { reply_err(op.sink(), "ERR out of memory"); return MultiIoAction::LocalDone; }
        if (session->active) {
            reply_err(op.sink(), "ERR WATCH inside MULTI is not allowed");
            return MultiIoAction::LocalDone;
        }
        if (session->watched.empty()) {
            client.next_watch_generation();
            client.clear_watch_dirty();
        }
        MultiExecState* state = allocate_state(server, client, owner_io, MultiStateKind::WatchAdd);
        if (!state) { reply_err(op.sink(), "ERR out of memory"); return MultiIoAction::LocalDone; }
        state->final_reply = MultiFinalReply::Ok;
        const size_t watched_before = session->watched.size();
        try {
            for (uint32_t i = 1; i < op.argc(); i++) {
                const std::string key(op.arg(i).p, op.arg(i).n);
                bool duplicate = false;
                for (const MultiWatchedKey& prior : session->watched)
                    duplicate |= prior.db == op.db && prior.key == key;
                if (duplicate) continue;
                // WATCH is cold. Register one owner-local alias in each namespace so
                // SWAPDB can inspect only local keys, without foreign store reads or
                // invalidating an absent key merely because its DB was swapped.
                for (uint32_t ns = 0; ns < server.cfg().databases; ++ns) {
                    const uint64_t hash = FlatStore::hash_key(Slice(key.data(), key.size(), ns));
                    MultiWatchedKey watched{key, hash, server.router().shard_of(hash),
                        static_cast<uint8_t>(ns), op.db};
                    session->watched.push_back(watched);
                    state->watched.push_back(std::move(watched));
                }
            }
            for (const MultiWatchedKey& key : state->watched) add_shard(state->shards, key.shard);
        } catch (const std::bad_alloc&) {
            session->watched.resize(watched_before);
            destroy_multi_state(state);
            reply_err(op.sink(), "ERR out of memory");
            return MultiIoAction::LocalDone;
        }
        if (state->shards.empty()) {
            delete state;
            reply_ok(op.sink());
            return MultiIoAction::LocalDone;
        }
        state->watch_pending.store(static_cast<uint32_t>(state->shards.size()),
                                   std::memory_order_relaxed);
        state->lists_pending.store(static_cast<uint32_t>(state->shards.size()),
                                   std::memory_order_relaxed);
        state->tasks_pending.store(static_cast<uint32_t>(state->shards.size()),
                                   std::memory_order_relaxed);
        session->pending = state;
        dispatch = state;
        return MultiIoAction::Dispatch;
    }

    if (multi_name(op, "unwatch") && (!session || !session->active)) {
        if (!session || session->watched.empty()) {
            client.next_watch_generation();
            client.clear_watch_dirty();
            reply_ok(op.sink());
            return MultiIoAction::LocalDone;
        }
        MultiExecState* state = prepare_unwatch_state(
            server, client, owner_io, *session, MultiStateKind::Unwatch, MultiFinalReply::Ok);
        if (!state) { reply_err(op.sink(), "ERR out of memory"); return MultiIoAction::LocalDone; }
        session->pending = state;
        dispatch = state;
        return MultiIoAction::Dispatch;
    }

    if (multi_name(op, "discard")) {
        if (!session || !session->active) {
            reply_err(op.sink(), "ERR DISCARD without MULTI");
            return MultiIoAction::LocalDone;
        }
        session->active = false;
        session->queue_error = false;
        session->clear_queue();
        if (session->watched.empty()) {
            client.next_watch_generation();
            client.clear_watch_dirty();
            reply_ok(op.sink());
            return MultiIoAction::LocalDone;
        }
        MultiExecState* state = prepare_unwatch_state(
            server, client, owner_io, *session, MultiStateKind::Unwatch, MultiFinalReply::Ok);
        if (!state) { reply_err(op.sink(), "ERR out of memory"); return MultiIoAction::LocalDone; }
        session->pending = state;
        dispatch = state;
        return MultiIoAction::Dispatch;
    }

    if (multi_name(op, "exec")) {
        if (!session || !session->active) {
            reply_err(op.sink(), "ERR EXEC without MULTI");
            return MultiIoAction::LocalDone;
        }
        if (server.aof().failed()) {
            bool writes = false;
            for (const auto& queued : session->queue) {
                Op probe;
                probe.spec = queued.spec;
                // Metadata resolution needs only the command and child name.
                for (size_t i = 0; i < std::min<size_t>(2, queued.argv.size()); ++i)
                    probe.push_arg(Slice(queued.argv[i].data(), queued.argv[i].size()));
                writes |= command_metadata_write(probe);
            }
            if (writes) {
                MultiExecState* cleanup = nullptr;
                if (!session->watched.empty()) {
                    cleanup = prepare_unwatch_state(server, client, owner_io, *session,
                        MultiStateKind::Unwatch, MultiFinalReply::ExecDiskError);
                    if (!cleanup) { reply_err(op.sink(), "ERR out of memory"); return MultiIoAction::LocalDone; }
                }
                session->active = session->queue_error = false;
                session->clear_queue();
                if (cleanup) {
                    session->pending = dispatch = cleanup;
                    return MultiIoAction::Dispatch;
                }
                client.next_watch_generation();
                client.clear_watch_dirty();
                server.aof().reply_write_error(op, true);
                return MultiIoAction::LocalDone;
            }
        }
        bool swaps = false;
        if constexpr (!kSingleDatabase)
            for (const auto& queued : session->queue) swaps |= has_name(queued, "swapdb");
        if (swaps && !server.database_boundary_begin(client, owner_io, client.rob().dispatch_id()))
            return MultiIoAction::Backpressure;
        if (!server.atomic_can_admit(owner_io, true)) return MultiIoAction::Backpressure;
        uint64_t generation = 0;
        if (!server.atomic_try_admit(owner_io, generation, true))
            return MultiIoAction::Backpressure;
        MultiExecState* state = allocate_state(server, client, owner_io, MultiStateKind::Execute);
        if (!state) {
            server.atomic_retire_group(owner_io, generation);
            reply_err(op.sink(), "ERR out of memory");
            session->active = false;
            session->clear_queue();
            return MultiIoAction::LocalDone;
        }
        state->admitted = true;
        server.atomic_apply_open(owner_io, state->apply_open);
        state->admission_generation = generation;
        state->reset_watch = true;
        state->watched = std::move(session->watched);
        state->final_reply = session->queue_error ? MultiFinalReply::ExecAbort : MultiFinalReply::Exec;
        if (!session->queue_error &&
            !prepare_commands(server, *state, session->queue)) {
            destroy_multi_state(state);
            reply_err(op.sink(), "ERR out of memory");
            session->active = false;
            session->clear_queue();
            return MultiIoAction::LocalDone;
        }
        if ((!state->write_keys.empty() || state->database_publish) && server.aof().recording()) {
            std::vector<uint32_t> participants;
            try {
                participants.reserve(state->write_keys.size());
                for (const MultiWriteKey& write : state->write_keys)
                    participants.push_back(static_cast<uint32_t>(write.shard));
                if (state->database_publish) participants.push_back(0);
            } catch (const std::bad_alloc&) {
                destroy_multi_state(state);
                reply_err(op.sink(), "ERR out of memory");
                session->active = false;
                session->clear_queue();
                return MultiIoAction::LocalDone;
            }
            state->aof_group = aof_create_group(server.aof(), participants);
            if (!state->aof_group) {
                destroy_multi_state(state);
                reply_err(op.sink(), "ERR out of memory");
                session->active = false;
                session->clear_queue();
                return MultiIoAction::LocalDone;
            }
        }
        session->active = false;
        session->queue_error = false;
        session->clear_queue();
        for (const MultiWatchedKey& key : state->watched) add_shard(state->shards, key.shard);
        if (state->shards.empty()) {
            if (state->final_reply == MultiFinalReply::ExecAbort)
                reply_err(op.sink(), "EXECABORT Transaction discarded because of previous errors.");
            else reply_array_header(op.sink(), 0);
            release_admission(*state);
            client.next_watch_generation();
            client.clear_watch_dirty();
            delete state;
            return MultiIoAction::LocalDone;
        }
        state->watch_pending.store(static_cast<uint32_t>(state->shards.size()),
                                   std::memory_order_relaxed);
        state->lists_pending.store(static_cast<uint32_t>(state->shards.size()),
                                   std::memory_order_relaxed);
        state->tasks_pending.store(static_cast<uint32_t>(state->shards.size()),
                                   std::memory_order_relaxed);
        session->pending = state;
        dispatch = state;
        return MultiIoAction::Dispatch;
    }

    if (!session || !session->active) return MultiIoAction::NotHandled;
    if (command_metadata_no_multi(op) || multi_engine_policy_refusal(op)) {
        session->queue_error = true;
        reply_err(op.sink(), "ERR Command not allowed inside a transaction");
        return MultiIoAction::LocalDone;
    }
    MultiQueuedCommand queued;
    if (!queued_copy(op, queued)) {
        session->queue_error = true;
        reply_err(op.sink(), "ERR out of memory");
        return MultiIoAction::LocalDone;
    }
    try { session->queue.push_back(std::move(queued)); }
    catch (const std::bad_alloc&) {
        session->queue_error = true;
        reply_err(op.sink(), "ERR out of memory");
        return MultiIoAction::LocalDone;
    }
    for (const std::string& arg : session->queue.back().argv)
        session->query_bytes += arg.size() + sizeof(void*);
    reply_simple(op.sink(), "QUEUED");
    return MultiIoAction::LocalDone;
}

// Shared first-dispatch/retry tail. Only begin_dispatch publishes the initial
// ROB slot; a retry supplies an empty callback and preserves that slot/barrier.
template <bool IofusedPrivateQueue, typename Begin>
bool multi_dispatch_attempt(Server& server, ThreadCtx& self, ScatterArenaPool& pool,
                            Client& client, Op& op, MultiExecState* dispatch, uint64_t op_id,
                            bool* touched, uint32_t* touched_list, uint32_t& ntouched,
                            Begin&& begin_dispatch) {
    uint32_t needed[kMaxThreads] = {};
    const uint32_t count = multi_dispatch_count(dispatch);
    for (uint32_t i = 0; i < count; i++) {
        const int32_t sid = multi_dispatch_shard(dispatch, i);
        needed[server.worker_of_shard(sid)]++;
    }
    for (uint32_t tid = 0; tid < server.nthreads(); tid++) {
        if (!needed[tid]) continue;
        ThreadCtx& owner = server.thread(tid);
        const uint32_t free_slots = [&] {
            if constexpr (IofusedPrivateQueue)
                return owner.iofused_task_free_slots(self.id());
            else
                return owner.task_free_slots(self.id());
        }();
        if (free_slots < needed[tid]) {
            // Returning through the one parse-loop continuation reaches the existing top-of-loop
            // backpressure check, which has the same effect as the old in-line break.
            client.set_atomic_backpressure(true);
            return false;
        }
    }

    // PIN THE TRANSACTION'S READ CUT, BEFORE ANY FRAGMENT IS POSTED.
    // Drawn here rather than at execution for the same reason a bare cross-shard read draws it at
    // prepare: this is the connection's program order, and register_snapshot publishes the cleanup
    // floor synchronously, so no owner can resolve under a cut whose predecessors cleanup has
    // already been free to collapse. `op` reuses the parse pass's cut when IO stamped one, which
    // keeps a plain read and a transaction prepared back to back on one connection from disagreeing
    // about which of them is older. Untaken -- and therefore free -- for any transaction that
    // carries no multi-owner read.
    if (__builtin_expect(dispatch->exec_read_fanout ||
            (dispatch->kind == MultiStateKind::Execute && dispatch->read_only && dispatch->shards.size() > 1), false)) {
        if (!pool.can_register_snapshot()) {
            // The unresolved-cut window is full on this IO thread. Falling through without a cut
            // would silently restore the defect, so this is backpressure: the state stays in
            // session->pending and the same EXEC is re-dispatched on a later pass.
            client.set_atomic_backpressure(true);
            return false;
        }
        dispatch->snapshot = op.has_read_cut() ? op.read_cut(server.atomic_snapshot())
                                               : server.atomic_snapshot();
        if (!pool.register_snapshot(server, dispatch, self.id())) {
            dispatch->snapshot = UINT64_MAX;
            client.set_atomic_backpressure(true);
            return false;
        }
        // Vacuous-validation guard: one per transaction that really entered the machinery. A gate
        // row for this defect that never moves this counter never armed the window it claims to
        // close. register_snapshot may have adopted a confirmed newer cut, so the children are
        // stamped from dispatch->snapshot afterwards, never from the value asked for.
        server.note_atomic_exec_read_cut();
        for (const auto& command : dispatch->commands)
            if (command->scatter) command->scatter->snapshot = multi_read_cut(*dispatch);
        // TEST HOOK arming, after the participant set exists so a lead shard can be named. Only a
        // transaction carrying a multi-owner read arms it -- the writer transaction the battery
        // races must stay free to run and publish its ticket inside the window.
        const uint32_t fanout_defer = server.debug_atomic_fanout_defer();
        if (__builtin_expect(fanout_defer != 0, false) && dispatch->shards.size() > 1) {
            dispatch->debug_fanout_lead = dispatch->shards[0];
            dispatch->debug_fanout_deadline =
                now_ns() + static_cast<uint64_t>(fanout_defer) * 1000ull;
        }
    }

    // PIN THE TRANSACTION'S TIME CUT, BEFORE ANY FRAGMENT IS POSTED.
    // Same argument as the read cut above, for the other axis a fan-out can straddle. Unlike the
    // read cut this one is unconditional and free of any registry: a deadline is not a ticket
    // anybody has to wait on, so pinning one costs a single clock read per EXEC and nothing else.
    // The cross-shard children inherit it rather than stamping their own, so a transaction is one
    // instant end to end and not one instant per lowered command.
    if (dispatch->kind == MultiStateKind::Execute && dispatch->attempt == 0) {
        const auto delay = server.take_debug_txn_place_defer();
        if (delay) dispatch->debug_place_deadline = now_ns() + uint64_t(delay) * 1000;
    }
    dispatch->now_cut_ms = now_realtime_ms();
    for (const auto& command : dispatch->commands)
        if (command->scatter) command->scatter->now_cut_ms = dispatch->now_cut_ms;

    // A pending EXEC may survive queue or snapshot-window backpressure while shard ownership
    // migrates. Derive owner sentinels only on the final, no-failure path immediately before the
    // first task can become visible, so their slots match the routes used by this publication.
    if (!dispatch->apply_open.load(std::memory_order_relaxed))
        server.atomic_apply_open(self.id(), dispatch->apply_open);
    dispatch->exec_op_id = op_id;
    op.attach_multi_state(dispatch);
    begin_dispatch();
    multi_dispatch_started(client, dispatch);
    if (dispatch->kind == MultiStateKind::Execute)
        server.note_txn(self.id(), TxnCounter::Attempts);
    LoopSignals& sig = self.sig();
    for (uint32_t i = 0; i < count; i++) {
        const int32_t sid = multi_dispatch_shard(dispatch, i);
        const uint32_t tid = server.worker_of_shard(sid);
        ThreadCtx& owner = server.thread(tid);
        const Task task = multi_make_task(&client, op_id, sid, dispatch);
        const bool posted = [&] {
            if constexpr (IofusedPrivateQueue)
                return owner.post_iofused_task_quiet(self.id(), task, sig);
            else
                return owner.post_task_quiet(self.id(), task, sig);
        }();
        if (!posted) std::abort();
        if (!touched[tid]) {
            touched[tid] = true;
            touched_list[ntouched++] = tid;
        }
    }
    return true;
}

template <bool IofusedPrivateQueue>
bool multi_dispatch_entry_impl(IoLoop& loop, Client& client, Op& op, uint32_t consumed) {
    MultiSession* queue_session = client.multi_session();
    const bool was_queueing = queue_session && queue_session->active;
    const uint64_t op_id = client.rob().dispatch_id();
    if (was_queueing && op_id != queue_session->next_queue_op_id)
        queue_session->queue_error = true;
    MultiExecState* dispatch = nullptr;
    const uint64_t latency_started = latency_tracking_start();
    const MultiIoAction action =
        multi_handle_io(*loop.srv_, client, op, loop.self_->id(), dispatch);
    if (action == MultiIoAction::NotHandled) return false;
    if (action == MultiIoAction::Backpressure) {
        client.set_atomic_backpressure(true);
        return true;
    }
    if (was_queueing) queue_session->next_queue_op_id = op_id + 1;
    if (action == MultiIoAction::LocalDone) {
        if (op.spec->flags & CmdFlags::Transaction)
            latency_tracking_finish(loop.self_->id(), op, latency_started);
        client.advance_parse(consumed);
        loop.self_->note_command(op.spec->id);
        loop.flip_fingerprint_note(*op.spec, op);
        loop.finish_prebuilt(&client, op);
        return true;
    }

    if (!multi_dispatch_attempt<IofusedPrivateQueue>(
            *loop.srv_, *loop.self_, loop.scatter_pool_, client, op, dispatch, op_id,
            loop.touched_, loop.touched_list_, loop.ntouched_, [&] {
                client.atomic_group_started();
                client.rob().publish();
            })) return true;
    LoopSignals& sig = loop.self_->sig();
    loop.self_->note_command(op.spec->id);
    loop.flip_fingerprint_note(*op.spec, op);
    client.advance_parse(consumed);
    sig.ops++;
    // Released by the quiescence backstop in flush_ready: EXEC's parked lifetime IS its ROB slot,
    // so "nothing in flight" and "this transaction is done" are the same instant. Unlike a blocking
    // command, EXEC takes the barrier WITHOUT requiring an empty ROB -- older ops of this
    // connection may still be in flight when it does.
    loop.barrier_arm(&client, BarrierOwner::Exec);
    loop.mark_active(&client);
    return true;
}

bool multi_dispatch_entry(IoLoop& loop, Client& client, Op& op, uint32_t consumed) {
    return multi_dispatch_entry_impl<false>(loop, client, op, consumed);
}

void multi_retire_entry(IoLoop& loop, Client& client, Op& op) {
    command_set_local_context(&client, loop.self_);
    snapshot_bind_io(loop.self_, &loop.ring_);
    if (client.is_tls()) {
        auto* state = static_cast<MultiExecState*>(op.multi_state());
        if (state)
            for (const auto& command : state->commands) {
                ScatterState* scatter = command->scatter;
                if (!scatter || scatter->kind != Kind::Mget || !scatter->values) continue;
                for (uint32_t i = 0; i < scatter->key_count; i++) {
                    ValueSlot& slot = scatter->values[i];
                    if (slot.kind != ValueKind::Borrow) continue;
                    loop.queue_borrow_release(slot.shard, slot.ptr);
                    loop.wb_.note_zc_suppressed_tls();
                    slot.kind = ValueKind::Nil;
                }
            }
    }
    // RELEASE THE CUT ONLY AFTER THE LAST FRAGMENT HAS ANSWERED. Retirement is that moment: the
    // final reply is assembled once every participating owner has reported, and this is the one
    // retire path a published transaction takes (io_loop.h routes op.has_multi_state() here). The
    // state object is still alive -- multi_retire below is what releases or defers it.
    if (auto* cut = static_cast<MultiExecState*>(op.multi_state())) {
        if (__builtin_expect(cut->snapshot_registered, false))
            loop.scatter_pool_.unregister_snapshot(*loop.srv_, cut, loop.self_->id());
    }
    multi_retire(client, op, loop.multi_deferred_);
    snapshot_bind_io(nullptr, nullptr);
    command_set_local_context(nullptr, nullptr);
}

uint32_t multi_owner_reap_entry(IoLoop& loop) {
    return multi_reap_deferred(loop.multi_deferred_);
}

namespace {
MultiExecState* multi_rebuild_attempt(MultiExecState& previous) {
    Server& server = *previous.server;
    auto* next = allocate_state(server, *previous.client, previous.owner_io, MultiStateKind::Execute,
                                previous.decision.age_ns);
    if (!next) return nullptr;
    try {
        std::vector<MultiQueuedCommand> queue;
        queue.reserve(previous.commands.size());
        // Old child Ops retain slices into these strings until record retirement.
        for (const auto& command : previous.commands) queue.push_back(command->queued);
        next->watched = previous.watched;
        if (!prepare_commands(server, *next, queue)) throw std::bad_alloc();
        for (const auto& key : next->watched) add_shard(next->shards, key.shard);
        if ((!next->write_keys.empty() || next->database_publish) && server.aof().recording()) {
            std::vector<uint32_t> participants;
            for (const auto& write : next->write_keys) participants.push_back(write.shard);
            if (next->database_publish) participants.push_back(0);
            next->aof_group = aof_create_group(server.aof(), participants);
            if (!next->aof_group) throw std::bad_alloc();
        }
    } catch (const std::bad_alloc&) {
        destroy_multi_state(next);
        return nullptr;
    }
    next->decision.age_ns = previous.decision.age_ns;
    next->decision.age_io = previous.decision.age_io;
    next->decision.age_seq = previous.decision.age_seq;
    next->attempt = previous.attempt + 1;
    next->exec_op_id = previous.exec_op_id;
    next->watch_generation = previous.watch_generation;
    next->reset_watch = true;
    next->final_reply = MultiFinalReply::Exec;
    const auto count = static_cast<uint32_t>(next->shards.size());
    next->watch_pending.store(count, std::memory_order_relaxed);
    next->lists_pending.store(count, std::memory_order_relaxed);
    next->tasks_pending.store(count, std::memory_order_relaxed);
    return next;
}
}

void multi_bind_retry_lane(Server& server, uint32_t io) {
    auto& lane = server.multi_retry_lane(io);
    multi_retry_signal.pending.store(false, std::memory_order_relaxed);
    lane.signal.store(&multi_retry_signal.pending, std::memory_order_seq_cst);
    if (lane.head.load(std::memory_order_seq_cst))
        multi_retry_signal.pending.store(true, std::memory_order_release);
}

template <bool IofusedPrivateQueue>
__attribute__((noinline)) uint32_t multi_owner_pass_entry_impl(IoLoop& loop) {
    uint32_t work = 0;
    // Reset before the acquire/release exchange. A producer after the exchange
    // acquires this reset before setting the signal; an earlier node is drained.
    multi_retry_signal.pending.store(false, std::memory_order_release);
    auto& inbox = loop.srv_->multi_retry_lane(loop.self_->id()).head;
    if (__builtin_expect(inbox.load(std::memory_order_relaxed) != nullptr, false)) {
        MultiRetryNode* stack = inbox.exchange(nullptr, std::memory_order_acq_rel);
        MultiRetryNode* pending = nullptr;
        while (stack) {
            auto* next = stack->next;
            stack->next = pending;
            pending = stack;
            stack = next;
        }
        while (pending) {
            auto* node = pending;
            pending = node->next;
            if (node->kind == MultiRetryNode::Kind::Group) {
                auto& previous = *static_cast<ScatterState*>(node->unit);
                Client* client = previous.commit_client;
                txn_group_redispatch<IofusedPrivateQueue>(
                    *loop.srv_, *loop.self_, loop.ring_, loop.scatter_pool_, previous);
                loop.mark_active(client);
                ++work;
                continue;
            }
            auto* previous = static_cast<MultiExecState*>(node->unit);
            // The IO's existing park decision consumes this hook's work count.
            // A held/requeued attempt is still work: returning zero can park
            // with the only retry already in our own inbox and nobody left to wake us.
            ++work;
            Client& client = *previous->client;
            Op& op = client.rob().at(previous->exec_op_id);
            if (previous->finalized.load(std::memory_order_acquire) && !previous->doomed) {
                if (!previous->publication_started) {
                    std::shared_ptr<PubSubNotificationChain> chain;
                    try {
                        chain = std::make_shared<PubSubNotificationChain>();
                        for (const auto& command : previous->commands) {
                            if (command->kind != MultiCommandKind::IoLocal ||
                                !(has_name(command->queued, "publish") ||
                                  has_name(command->queued, "spublish"))) continue;
                            chain->items.push_back(PubSubNotificationItem{
                                command->queued.argv[1], command->queued.argv[2], command->op.get(),
                                has_name(command->queued, "spublish")});
                        }
                        chain->completed = [](void* context) {
                            multi_enqueue_retry(*static_cast<MultiExecState*>(context));
                        };
                        chain->completion = previous;
                    } catch (const std::bad_alloc&) {
                        // No publication was queued; retain this already committed
                        // attempt until the IO can allocate its one effect batch.
                        multi_enqueue_retry(*previous);
                        continue;
                    }
                    // Enqueue can start publishing immediately. Its allocation
                    // failures follow the existing pub/sub policy; they must
                    // never be mistaken for an unqueued batch and replayed.
                    previous->publication_started = true;
                    loop.pubsub_notification_enqueue(chain);
                } else {
                    op.state.store(OpState::Done, std::memory_order_release);
                    loop.mark_active(&client);
                }
                ++work;
                continue;
            }
            if (client.closing() || client.dead()) {
                previous->decision.aborted.store(true, std::memory_order_release);
                if (auto* session = ensure_multi_session(client))
                    session->watched = std::move(previous->watched);
                multi_close_entry(loop, client);
                op.state.store(OpState::Done, std::memory_order_release);
                loop.mark_active(&client);
                ++work;
                continue;
            }
            if (loop.srv_->txn_retry_held(&previous->retry) || now_ns() < previous->retry_after_ns) {
                multi_enqueue_retry(*previous);
                continue;
            }
            // No owner can still read P. Release its cleanup pin before asking
            // for N's slot, or eight cancelled cut holders deadlock the window.
            if (previous->snapshot_registered)
                loop.scatter_pool_.unregister_snapshot(*loop.srv_, previous, loop.self_->id());
            MultiExecState* next = multi_rebuild_attempt(*previous);
            if (!next) {
                previous->retry_after_ns = now_ns() + 1000000;
                multi_enqueue_retry(*previous);
                continue;
            }
            try { loop.multi_deferred_.reserve(loop.multi_deferred_.size() + 1); }
            catch (const std::bad_alloc&) {
                destroy_multi_state(next);
                multi_enqueue_retry(*previous);
                continue;
            }
            next->admitted = previous->admitted;
            next->admission_generation = previous->admission_generation;
            previous->admitted = false;
            if (!multi_dispatch_attempt<IofusedPrivateQueue>(
                    *loop.srv_, *loop.self_, loop.scatter_pool_, client, op, next,
                    previous->exec_op_id, loop.touched_, loop.touched_list_, loop.ntouched_, [] {})) {
                previous->admitted = next->admitted;
                next->admitted = false;
                destroy_multi_state(next);
                multi_enqueue_retry(*previous);
                continue;
            }
            for (size_t i = 0; i < previous->commands.size(); ++i)
                latency_tracking_retry(*previous->commands[i]->op, *next->commands[i]->op);
            previous->watched.clear();
            previous->retired = true;
            loop.multi_deferred_.push_back(previous);
            loop.srv_->note_txn(loop.self_->id(), TxnCounter::Retries);
            loop.flush_ifid_posts();
            loop.mark_active(&client);
            ++work;
        }
    }
    while (!loop.pending_multi_cleanups_.empty()) {
        MultiExecState* state = loop.pending_multi_cleanups_.front();
        uint32_t needed[kMaxThreads] = {};
        const uint32_t count = multi_dispatch_count(state);
        for (uint32_t i = 0; i < count; i++)
            needed[loop.srv_->worker_of_shard(multi_dispatch_shard(state, i))]++;
        bool room = true;
        for (uint32_t tid = 0; tid < loop.srv_->nthreads(); tid++) {
            if (!needed[tid]) continue;
            ThreadCtx& owner = loop.srv_->thread(tid);
            const uint32_t free_slots = [&] {
                if constexpr (IofusedPrivateQueue)
                    return owner.iofused_task_free_slots(loop.self_->id());
                else
                    return owner.task_free_slots(loop.self_->id());
            }();
            if (free_slots < needed[tid]) {
                room = false;
                break;
            }
        }
        if (!room) break;
        for (uint32_t i = 0; i < count; i++) {
            const int32_t sid = multi_dispatch_shard(state, i);
            ThreadCtx& owner = loop.srv_->thread(loop.srv_->worker_of_shard(sid));
            const Task task = multi_make_task(nullptr, UINT64_MAX, sid, state);
            const bool posted = [&] {
                if constexpr (IofusedPrivateQueue)
                    return owner.post_iofused_task(
                        loop.self_->id(), task, loop.ring_, loop.self_->sig());
                else
                    return owner.post_task(
                        loop.self_->id(), task, loop.ring_, loop.self_->sig());
            }();
            if (!posted)
                std::abort();
        }
        multi_internal_dispatch_started(state);
        loop.pending_multi_cleanups_.pop_front();
        work++;
    }
    return work;
}

uint32_t multi_owner_pass_entry(IoLoop& loop) {
    uint32_t work = multi_owner_reap_entry(loop);
    // Keep allocation, posting and their large stack frame off an empty pass.
    if (__builtin_expect(multi_retry_signal.pending.load(std::memory_order_relaxed), false) ||
        !loop.pending_multi_cleanups_.empty())
        work += multi_owner_pass_entry_impl<false>(loop);
    return work;
}

void multi_close_entry(IoLoop& loop, Client& client) {
    if (MultiExecState* cleanup = multi_prepare_close(*loop.srv_, client, loop.self_->id()))
        loop.pending_multi_cleanups_.push_back(cleanup);
}

static void multi_shutdown_attempt(MultiExecState* state, ScatterArenaPool& pool,
                                   std::vector<MultiExecState*>& deferred) {
    uint64_t undecided = 0;
    if (state->decision.epoch.compare_exchange_strong(
            undecided, kAtomicCancelledEpoch, std::memory_order_relaxed)) {
        state->decision.aborted.store(true, std::memory_order_relaxed);
        abort_multi_children(*state);
        aof_abort_group(state->aof_group);
    }
    for (const MultiWatchedKey& watched : state->watched)
        state->server->shard(watched.shard).watch_remove(
            Slice(watched.key.data(), static_cast<uint32_t>(watched.key.size()), watched.ns),
            state->client, state->watch_generation);
    for (int32_t sid : state->shards)
        state->server->shard(sid).watch_finish_unit(state->claims[sid], state);
    if (state->snapshot_registered)
        pool.unregister_snapshot(*state->server, state, state->owner_io);
    if (!state->published) clear_unpublished_multi_record_refs(*state);
    Op& op = state->client->rob().at(state->exec_op_id);
    if (op.multi_state() != state) std::abort();
    op.detach_scatter_state();
    op.state.store(OpState::Done, std::memory_order_relaxed);
    state->client->atomic_group_finished();
    release_admission(*state);
    state->retired = true;
    if (multi_records_done(*state)) destroy_multi_state(state);
    else deferred.push_back(state);
}

void multi_shutdown_entry(IoLoop& loop) {
    if (loop.srv_ && loop.self_) {
        // Every producer is joined and the store records have drained. Only
        // completed attempts remain in this IO-owned retry inbox.
        auto* pending = loop.srv_->multi_retry_lane(loop.self_->id()).head.exchange(
            nullptr, std::memory_order_relaxed);
        while (pending) {
            auto* node = pending;
            pending = node->next;
            if (node->kind == MultiRetryNode::Kind::Group) {
                txn_group_shutdown(*static_cast<ScatterState*>(node->unit), loop.scatter_pool_);
                continue;
            }
            multi_shutdown_attempt(static_cast<MultiExecState*>(node->unit),
                                   loop.scatter_pool_, loop.multi_deferred_);
        }
        multi_owner_reap_entry(loop);
    }
    for (MultiExecState* state : loop.pending_multi_cleanups_)
        multi_abandon_unpublished(state);
    loop.pending_multi_cleanups_.clear();
}

uint32_t multi_dispatch_count(const MultiExecState* state) {
    return state ? static_cast<uint32_t>(state->shards.size()) : 0;
}

int32_t multi_dispatch_shard(const MultiExecState* state, uint32_t index) {
    return state && index < state->shards.size() ? state->shards[index] : -1;
}

void multi_dispatch_started(Client& client, MultiExecState* state) {
    if (!state) return;
    if (state->published) std::abort();
    // Internal owner drivers may have prepared sentinels already. The public
    // dispatch boundary must also support callers that leave preparation to us,
    // without counting any owner twice. Initialization itself stays one-shot.
    if (!state->record_refs_precounted) initialize_multi_owner_record_refs(*state);
    state->published = true;
    MultiSession* session = client.multi_session();
    if (session && session->pending == state) session->pending = nullptr;
}

void multi_internal_dispatch_started(MultiExecState* state) {
    if (state) state->published = true;
}

void multi_abandon_unpublished(MultiExecState* state) {
    if (!state || state->published) return;
    clear_unpublished_multi_record_refs(*state);
    destroy_multi_state(state);
}

bool multi_task_tagged(const Task& task) {
    return (reinterpret_cast<uintptr_t>(task.scatter) & kMultiTaskTag) != 0;
}

bool multi_task_owns_epoch(const Task& task, const void* group_epoch) {
    const uintptr_t tagged = reinterpret_cast<uintptr_t>(task.scatter);
    const auto* state = reinterpret_cast<const MultiExecState*>(tagged & ~kMultiTaskTag);
    return state && multi_state_owns_epoch(*state, group_epoch);
}

// INFO atomic_exec_order_late. Defined HERE, outside this file's anonymous namespace, because
// t_server.cc calls it through multi.h: inside, it would be internal-linkage and the reference
// from the other translation unit would not resolve.
uint64_t multi_exec_order_late() { return g_exec_order_late.load(std::memory_order_relaxed); }

Task multi_make_task(Client* client, uint64_t op_id, int32_t shard, MultiExecState* state) {
    const uintptr_t tagged = reinterpret_cast<uintptr_t>(state) | kMultiTaskTag;
    return Task{client, op_id, shard, reinterpret_cast<ScatterState*>(tagged)};
}

bool multi_aof_emit_fragment(MultiExecState& state, Shard& shard) {
    if (!state.aof_group) return true;
    uint8_t& done = state.aof_shard_done[static_cast<uint32_t>(shard.id())];
    if (done) return true;
    uint32_t count = 0;
    for (const MultiWriteKey& write : state.write_keys) count += write.shard == shard.id();
    if (shard.id() == 0 && state.database_publish) ++count;
    if (!count) { done = 1; return true; }
    AofProducer& producer = shard.store().aof();
    if (!producer.begin_group(state.aof_group)) return false;
    // Runtime-error children keep any already-installed candidates private under their own abort
    // word. The physical table head may therefore be a rejected RENAMENX source tombstone. Resolve
    // the transaction's own overlay and record its LOGICAL final image, which skips that child but
    // still sees successful private candidates from the same connection.
    shard.store().atomic_set_read_context(UINT64_MAX, state.origin_conn_id);
    bool ok = true;
    if (shard.id() == 0 && state.database_publish)
        ok &= producer.record_group_database_map(state.database_publish->data());
    for (const MultiWriteKey& write : state.write_keys) {
        if (write.shard != shard.id()) continue;
        const Slice key(write.key.data(), static_cast<uint32_t>(write.key.size()), write.ns);
        ok &= producer.record_group_visible_post_image(shard.store(), write.hash, key);
    }
    shard.store().atomic_clear_read_epoch();
    ok &= producer.finish_group();
    done = 1;
    return ok;
}

MultiOwnerRetryNode& multi_owner_retry_node(const Task& task) {
    const auto tagged = reinterpret_cast<uintptr_t>(task.scatter);
    auto& state = *reinterpret_cast<MultiExecState*>(tagged & ~kMultiTaskTag);
    return state.owner_retries[task.shard];
}

MultiTaskResult multi_execute_task(Server& server, const Task& task, Shard& shard,
                                   uint32_t owner_thread_id, uint32_t owner_domain,
                                   AofOwnerContext* aof_context,
                                   const MultiRetryPromoter* promoter) {
    struct DeferBlockingPublication {
        DeferBlockingPublication() { blocking_defer_plain_publication(true); }
        ~DeferBlockingPublication() { blocking_defer_plain_publication(false); }
    } defer_blocking_publication;
    // A carrier-less fragment is not an error: multi_close_entry posts the watch-release fragment
    // of a vanished connection with client=nullptr and op_id=UINT64_MAX, and this function's own
    // tail already destroys the state on that path. Only the notify scope wanted an Op, and a
    // fragment with no client raises no notifications, so it takes the pointer form.
    Op* carrier = task.client && task.op_id != UINT64_MAX
        ? &task.client->rob().at(task.op_id) : nullptr;
    LatencyTrackingPart latency_parent(owner_thread_id, carrier);
    const bool notify = carrier && (carrier->spec->flags & CmdFlags::NotifySelected);
    NotifyExecutionScope notify_scope(shard, carrier, notify);
    const uintptr_t tagged = reinterpret_cast<uintptr_t>(task.scatter);
    auto& state = *reinterpret_cast<MultiExecState*>(tagged & ~kMultiTaskTag);
    // ONE EXPIRY CUT FOR THE WHOLE TRANSACTION, on every owner and for every fragment including the
    // WATCH phase below -- redis validates watches inside EXEC's own call, under EXEC's snapshot.
    // Without this, two identical reads in one EXEC could disagree about the same key.
    PinnedNowMs now_cut(shard, state.now_cut_ms);
    uint8_t& noted = state.execution_noted[static_cast<uint32_t>(shard.id())];
    if (!(noted & 1u)) {
        shard.note_execution(owner_domain);
        noted |= 1u;
    }
    if (state.kind == MultiStateKind::Execute && state.read_only &&
        state.shards.size() == 1 && !state.read_cut_sampled) {
        // A single-shard unit samples on its owner, before its first read.
        state.snapshot = server.atomic_snapshot();
        state.read_cut_sampled = true;
        for (const auto& command : state.commands)
            if (command->scatter) command->scatter->snapshot = state.snapshot;
    }
    if (__builtin_expect(atomic_tripwire_enabled(), false) && !(noted & 2u)) {
        multi_tripwire_fragment_begin(state, shard);
        noted |= 2u;
    }
    const auto retry = [&] {
        const auto sid = static_cast<uint32_t>(shard.id());
        const bool arriving = state.kind == MultiStateKind::Execute && !state.read_only &&
            state.shards.size() != 1 &&
            state.watch_arrived.load(std::memory_order_acquire) != state.shards.size();
        return state.watch_shard_done[sid] || arriving || (state.execution_noted[sid] & 16u)
            ? MultiTaskResult::RetrySoon : MultiTaskResult::Retry;
    };
    MultiWatchMapScope transaction_map(state.database_watch.empty() ? nullptr : &state.database_map);
    if (!state.watch_phase_done.load(std::memory_order_acquire)) {
        if (!execute_watch_phase(state, shard, promoter)) return retry();
        if (!state.watch_phase_done.load(std::memory_order_acquire)) return retry();
    }

    if (state.kind == MultiStateKind::Execute &&
        state.decision.phase.load(std::memory_order_acquire) == TxnPhase::Executing)
        noted |= 8u; // owner-local start: plain writers may no longer pass this shard

    // TEST HOOK (DEBUG ATOMIC-FANOUT-DEFER), the MULTI half. Park every fragment of this
    // transaction except the one on its lead shard until the deadline, so the foreign transaction
    // the battery races really does commit BETWEEN two fragments of one in-EXEC read. It sits
    // AFTER the watch phase and this owner's start bit deliberately: D1 permits plain writes
    // before owner start, so parking earlier does not hold the read claims being tested.
    // The watch phase is an all-participants barrier, so parking
    // ahead of it would hold the lead back too and no fragment would run early. A park, not a
    // stall -- Retry re-queues the task on multi_retries_ and the owner returns to its queue, so
    // the writer is free to execute and publish its ticket inside the window. Off, this is one
    // load of a word the task has already touched.
    if (__builtin_expect(state.debug_fanout_deadline != 0, false) &&
        shard.id() != state.debug_fanout_lead &&
        now_ns() < state.debug_fanout_deadline)
        return retry();

    const uint32_t shard_id = static_cast<uint32_t>(shard.id());
    std::vector<uint32_t>& command_list = state.shard_commands[shard_id];
    uint32_t& cursor = state.shard_cursors[shard_id];
    if (state.kind != MultiStateKind::Execute ||
        state.final_reply == MultiFinalReply::ExecAbort ||
        state.watch_failed.load(std::memory_order_acquire)) {
        cursor = static_cast<uint32_t>(command_list.size());
    }

    while (cursor < command_list.size()) {
        MultiCommand& command = *state.commands[command_list[cursor]];
        MultiWatchMapScope command_map(command.watch_map.get());
        if (command.finished.load(std::memory_order_acquire)) {
            cursor++;
            continue;
        }
        const uint32_t stage = command.stage.load(std::memory_order_acquire);
        uint8_t& done = command.shard_done[shard_id];
        if (command.kind == MultiCommandKind::Xshard) {
            if (!state.decision.aborted.load(std::memory_order_acquire) &&
                command.scatter->kind == Kind::Sort && command.scatter->sort_options.deref &&
                !multi_touch_key(state, shard, 0, {}, false, true))
                return retry();
            // Membership is published with `stage`, not discovered from ScatterState::groups.
            // The latter is a reusable table: source/gather/apply transitions rewrite it on the
            // last owner of the old stage.  Reading it from a barrier-only task before the release
            // store below races that rewrite and can execute a partially built SORT gather group.
            if (!multi_xshard_stage_has_group(command, stage, shard.id())) {
                if (command.finished.load(std::memory_order_acquire)) continue;
                return retry();
            }
            if (done == stage + 1) {
                if (command.finished.load(std::memory_order_acquire)) continue;
                return retry();
            }
            if (!state.decision.aborted.load(std::memory_order_acquire)) {
                ShardGroup& group = *group_for(*command.scatter, shard.id());
                const bool writes = command.queued.spec->flags &
                    (CmdFlags::Write | CmdFlags::SnapshotWrite);
                if (group.count == 0 || command.scatter->kind == Kind::DatabaseInfo) {
                    if (!multi_touch_key(state, shard, 0, {}, false, true))
                        return retry();
                } else if (!sort_deref_gathering(*command.scatter)) {
                    for (uint32_t i = 0; i < group.count; ++i) {
                        const KeyRef& key = command.scatter->keys[
                            command.scatter->key_order[group.begin + i]];
                        const Slice bytes = command.op->arg(key.arg);
                        // A source can become a phase-two write (pop/move/rename).
                        // Conservatively resolve all keyed write-child roles as Write.
                        if (!multi_touch_key(state, shard, key.hash, bytes, writes) ||
                            (writes && !shard.watch_txn_write_ready(bytes, state)))
                            return retry();
                        // Its phase-one image is a read dependency until install.
                        if (!multi_touch_key(state, shard, key.hash, bytes, false))
                            return retry();
                    }
                }
            } else command.scatter->aborted.store(true, std::memory_order_release);
            if (notify)
                notify_execute_source(shard, *command.op, command.notify_order_base);
            const Task child_task{state.client, task.op_id, shard.id(), command.scatter};
            bool execute_child = !state.decision.aborted.load(std::memory_order_acquire);
            if (execute_child && command.scatter->atomic_pop && command.scatter->phase == 2) {
                ShardGroup* group = group_for(*command.scatter, shard.id());
                if (!group || group->count != 1) std::abort();
                const uint32_t pos = command.scatter->key_order[group->begin];
                const KeyRef& selected = command.scatter->keys[pos];
                const MultiPrepareWrite prepared = prepare_write_key(
                    server, state, shard, command.op->arg(selected.arg), selected.hash,
                    owner_thread_id, command.scatter, &command.scatter->watch_refs);
                if (prepared == MultiPrepareWrite::Retry) return retry();
                if (prepared == MultiPrepareWrite::Error) {
                    state.decision.aborted.store(true, std::memory_order_release);
                    command.scatter->aborted.store(true, std::memory_order_release);
                    execute_child = false;
                }
            }
            ScatterTaskResult executed = ScatterTaskResult::Complete;
            if (execute_child) {
                LatencyTrackingPart latency_child(owner_thread_id, command.op.get());
                if (command.scatter->kind == Kind::DatabaseInfo)
                    multi_collect_database_stats(state, command, shard);
                else executed = shard.has_watches()
                    ? watch_execute_scatter(child_task, shard, *command.op, owner_thread_id)
                    : xshard_execute(child_task, shard, *command.op, owner_thread_id);
            }
            if (executed != ScatterTaskResult::Complete) return retry();
            done = static_cast<uint8_t>(stage + 1);
            const MultiChildFinish finished = xshard_multi_child_complete(
                *command.scatter, *command.op, owner_thread_id);
            if (finished == MultiChildFinish::PhaseAdvanced) {
                const uint32_t next_stage = stage + 1;
                if (next_stage >= MultiCommand::kXshardStages) std::abort();
                // xshard_multi_child_complete has finished rebuilding groups.  Snapshot their
                // membership first; the release store then publishes both the group contents and
                // this immutable routing decision to every retrying transaction fragment.
                xshard_multi_child_capture_groups(
                    *command.scatter, command.xshard_stage_groups[next_stage]);
                command.stage.store(next_stage, std::memory_order_release);
            } else if (finished == MultiChildFinish::Final) {
                if (notify)
                    notify_xshard_finished(shard, *command.op, *command.scatter);
                if (!kSingleDatabase && command.scatter->kind == Kind::DatabaseInfo && command.watch_map) {
                    // SWAPDB publishes the live map only at the transaction's final decision.
                    // INFO must label this command's physical counts using the map at its own
                    // position in EXEC, including earlier swaps but excluding later ones.
                    WorkError error;
                    if (first_error(*command.scatter, error)) {
                        reply_work_error(*command.op, error);
                    } else {
                        DatabaseStatsTable physical{}, visible{};
                        for (uint32_t i = 0; i < command.scatter->nsub; ++i) {
                            const auto* aux = command.scatter->groups[i].aux;
                            if (!aux || !aux->database_stats) continue;
                            for (unsigned db = 0; db < physical.size(); ++db) {
                                const auto& row = (*aux->database_stats)[db];
                                physical[db].keys += row.keys;
                                physical[db].expires += row.expires;
                                physical[db].ttl += row.ttl;
                                physical[db].subexpiry += row.subexpiry;
                            }
                        }
                        for (uint32_t db = 0; db < server.cfg().databases; ++db)
                            visible[state.database_map[db]] = physical[(*command.watch_map)[db]];
                        command_info_with_databases(server, *command.op, visible);
                    }
                } else {
                    assemble_final(*state.client, *command.op, *command.scatter,
                                   nullptr, nullptr, nullptr);
                }
                command.finished.store(true, std::memory_order_release);
            }
            continue;
        }
        if (done == stage + 1) {
            if (command.finished.load(std::memory_order_acquire)) continue;
            return retry();
        }
        LatencyTrackingPart latency_child(owner_thread_id,
            command.kind == MultiCommandKind::IoLocal ? nullptr : command.op.get());
        bool executed = true;
        if (state.decision.aborted.load(std::memory_order_acquire)) {
            // Still join the command barrier; another owner may already have installed a
            // private candidate which the shared abort flag will hide.
        } else if (command.kind == MultiCommandKind::Local ||
                   command.kind == MultiCommandKind::Scan) {
            executed = execute_local_command(server, state, command, shard, owner_thread_id);
        } else {
            executed = execute_cross_command(
                server, state, command, shard, owner_thread_id, stage);
        }
        if (!executed) return retry();
        done = static_cast<uint8_t>(stage + 1);
        latency_child.finish();
        finish_command(command, stage, owner_thread_id);
    }

    uint8_t& joined = state.execution_joined[shard_id];
    if (!joined) {
        joined = 1;
        // Each shard emits its AOF fragment exactly once, under the same join guard that
        // publishes its list's owner work; a failed emit aborts the whole group (GCMT).
        if (!multi_aof_emit_fragment(state, shard)) aof_abort_group(state.aof_group);
        // This first barrier publishes every list's owner work before the one commit decision.
        // tasks_pending remains the post-decision lifetime barrier for state and reservations.
        if (state.lists_pending.fetch_sub(1, std::memory_order_acq_rel) == 1) {
            bool expected = false;
            if (state.finalizer_claimed.compare_exchange_strong(
                    expected, true, std::memory_order_acq_rel)) {
                // A read-only unit has no validation claim. All fragment reads
                // happen-before this last join; catch a write after placement
                // before discarding WATCH entries or publishing a non-null reply.
                if (state.read_only && !state.watched.empty() && state.client->watch_dirty())
                    state.watch_failed.store(true, std::memory_order_release);
                if (state.watch_failed.load(std::memory_order_acquire))
                    state.decision.aborted.store(true, std::memory_order_release);
                if (!state.decision.aborted.load(std::memory_order_acquire) &&
                    state.final_reply == MultiFinalReply::Exec) {
                    assemble_ownerless_replies(state, owner_thread_id);
                    const uint64_t ticket = server.atomic_commit_group_cas(
                        state.decision.epoch,
                        [&](uint64_t shared) {
                            publish_multi_child_epochs(state, shared);
                            if (state.database_publish)
                                server.databases().publish_prepared(std::move(state.database_publish));
                        });
                    if (!ticket) {
                        state.decision.aborted.store(true, std::memory_order_release);
                        abort_multi_children(state);
                        aof_abort_group(state.aof_group);
                    } else {
                        if (aof_context)
                            (void)aof_commit_group(server.aof(), state.aof_group, ticket,
                                                   *aof_context);
                        // Private pushes must never claim a blocked client. Once
                        // the CAS wins, sweep participant registries on their owners.
                        bool owners[kMaxThreads] = {};
                        for (int32_t sid : state.shards) {
                            Shard& participant = server.shard(sid);
                            if (!participant.has_blocking_waiters()) continue;
                            participant.set_blocking_dirty();
                            owners[server.worker_of_shard(sid)] = true;
                        }
                        ThreadCtx& self = server.thread(owner_thread_id);
                        if (Ring* ring = self.ring())
                            for (uint32_t tid = 0; tid < server.nthreads(); ++tid)
                                if (owners[tid]) server.thread(tid).wake_if_parked(*ring, self.sig());
                    }
                } else {
                    // Child entries no longer point at the parent's abort word, because doing so
                    // made a normal child error abort every other command. A genuine transaction
                    // abort still has to decide all of them before reservations are finalized.
                    abort_multi_children(state);
                    aof_abort_group(state.aof_group);
                }
                state.doomed = state.decision.epoch.load(std::memory_order_acquire) ==
                               kAtomicCancelledEpoch;
                state.finalized.store(true, std::memory_order_release);
                // Every owner has joined and the one commit decision is made: nothing this
                // transaction writes can land on a shard after this point, so it can no longer
                // straddle a snapshot cut. Closed here, on an OWNER, not at reply retirement.
                server.atomic_apply_close(owner_thread_id, state.apply_open);
            }
        }
    }
    if (!state.finalized.load(std::memory_order_acquire)) return retry();
    finalize_reservations(state, shard, promoter);
    complete_multi_owner_record_refs(state, owner_thread_id);
    latency_parent.finish();
    if (state.tasks_pending.fetch_sub(1, std::memory_order_acq_rel) != 1)
        return MultiTaskResult::Complete;

    if (task.op_id == UINT64_MAX) {
        destroy_multi_state(&state);
        return MultiTaskResult::Complete;
    }
    if (state.doomed || (state.has_publication &&
                        !state.decision.aborted.load(std::memory_order_acquire) &&
                        state.final_reply == MultiFinalReply::Exec)) {
        state.exec_op_id = task.op_id;
        if (state.backoff.load(std::memory_order_relaxed))
            state.retry_after_ns = now_ns() + std::min(
                kTxnRetryBackoffMax, uint64_t{1000} << std::min(state.attempt, uint32_t{10}));
        multi_enqueue_retry(state);
        if (Ring* ring = server.thread(owner_thread_id).ring())
            server.thread(state.owner_io).wake_if_parked(*ring, server.thread(owner_thread_id).sig());
        return MultiTaskResult::Complete;
    }
    return MultiTaskResult::Final;
}

void multi_retire(Client& client, Op& op, std::vector<MultiExecState*>& deferred) {
    auto* state = static_cast<MultiExecState*>(op.multi_state());
    if (!state) return;
    if (state->kind == MultiStateKind::Execute)
        if (auto* session = ensure_multi_session(client)) session->last_attempts = state->attempt + 1;
    if (state->kind == MultiStateKind::Execute &&
        state->final_reply == MultiFinalReply::Exec &&
        !state->watch_failed.load(std::memory_order_acquire) &&
        !state->decision.aborted.load(std::memory_order_acquire)) {
        // Connection-local handlers deliberately return to their owning IO thread.  This preserves
        // their thread-local client/snapshot context and keeps every shard-owning handler on EX.
        for (const auto& command : state->commands)
            if (command->kind == MultiCommandKind::IoLocal &&
                !(state->publication_started &&
                  (has_name(command->queued, "publish") || has_name(command->queued, "spublish"))))
            {
                LatencyTrackingScope latency(state->owner_io, *command->op);
                command->op->spec->handler(state->server->shard(0), *command->op);
            }
    }
    // A completed child can belong to an internally wounded attempt. Publish
    // samples only at logical EXEC retirement; retries transfer their active
    // slices to replacement children instead of incrementing call counts.
    for (const auto& command : state->commands)
        latency_tracking_retire(state->owner_io, *command->op);
    set_state_reply(*state, op);
    op.detach_scatter_state();
    client.atomic_group_finished();
    if (state->reset_watch) {
        client.next_watch_generation();
        client.clear_watch_dirty();
    }
    release_admission(*state);
    state->retired = true;
    if (multi_records_done(*state)) {
        destroy_multi_state(state);
        return;
    }
    try { deferred.push_back(state); }
    catch (const std::bad_alloc&) {
        // The record refs keep the state valid.  An allocation failure leaks one transaction state
        // rather than freeing epoch/abort words still named by shard-local MVCC entries.
    }
}

uint32_t multi_reap_deferred(std::vector<MultiExecState*>& deferred) {
    uint32_t reaped = 0;
    for (size_t i = 0; i < deferred.size();) {
        MultiExecState* state = deferred[i];
        if (!multi_records_done(*state)) { i++; continue; }
        destroy_multi_state(state);
        deferred[i] = deferred.back();
        deferred.pop_back();
        reaped++;
    }
    return reaped;
}

MultiExecState* multi_prepare_close(Server& server, Client& client, uint32_t owner_io) {
    MultiSession* session = client.multi_session();
    if (!session) return nullptr;
    if (session->pending && !session->pending->published) {
        MultiExecState* pending = session->pending;
        session->pending = nullptr;
        multi_abandon_unpublished(pending);
    }
    session->active = false;
    session->queue_error = false;
    session->clear_queue();
    if (session->watched.empty()) return nullptr;
    MultiExecState* state = prepare_unwatch_state(
        server, client, owner_io, *session, MultiStateKind::Close, MultiFinalReply::Ok);
    return state;
}

void multi_session_destroy(MultiSession* session) {
    if (!session) return;
    if (session->pending && !session->pending->published)
        multi_abandon_unpublished(session->pending);
    delete session;
}

bool multi_session_active(const Client& client) {
    const MultiSession* session = client.multi_session();
    return session && session->active;
}

uint32_t multi_session_queue_size(const Client& client) {
    const MultiSession* session = client.multi_session();
    return session && session->active ? static_cast<uint32_t>(session->queue.size()) : 0;
}

uint32_t multi_session_watch_size(const Client& client) {
    const MultiSession* session = client.multi_session();
    if (!session) return 0;
    if constexpr (kSingleDatabase) return static_cast<uint32_t>(session->watched.size());
    // WATCH installs one alias per physical namespace for each (logical DB, key).
    // Exactly one alias has ns=0, even after SWAPDB; count that representative.
    return static_cast<uint32_t>(std::count_if(session->watched.begin(), session->watched.end(),
        [](const MultiWatchedKey& watched) { return watched.ns == 0; }));
}

uint64_t multi_session_memory(const Client& client) {
    const MultiSession* session = client.multi_session();
    if (!session) return 0;
    uint64_t bytes = 0;
    for (const MultiQueuedCommand& command : session->queue)
        for (const std::string& arg : command.argv) bytes += arg.size();
    return bytes;
}

uint32_t multi_last_attempts(const Client& client) {
    const auto* session = client.multi_session();
    return session ? session->last_attempts : 0;
}

uint64_t multi_session_query_bytes(const Client& client) {
    const MultiSession* session = client.multi_session();
    return session ? session->query_bytes : 0;
}

namespace {

std::string watch_key_string(Slice key) { return database_owned_key(key); }

template <typename Fn>
void for_each_spec_key(Op& op, Fn&& fn) {
    // EVAL/FCALL's legacy registry range extends through ARGV so generic command metadata can
    // express a variable key count.  The numkeys field is the authoritative touched range: treating
    // trailing arguments as keys spuriously dirties an unrelated WATCH when a script command runs
    // between WATCH and EXEC.
    if (op.spec && (op.spec->flags & CmdFlags::ScriptRoute)) {
        uint32_t first = 0, count = 0;
        if (!command_script_key_range(op, first, count)) return;
        for (uint32_t i = 0; i < count; i++) fn(op.arg(first + i));
        return;
    }
    if (!op.spec || op.spec->first_key <= 0 || op.spec->key_step <= 0) return;
    const uint32_t last = op.spec->last_key < 0
        ? op.argc() - 1
        : std::min<uint32_t>(static_cast<uint32_t>(op.spec->last_key), op.argc() - 1);
    for (uint32_t arg = static_cast<uint32_t>(op.spec->first_key); arg <= last;
         arg += static_cast<uint32_t>(op.spec->key_step))
        fn(op.arg(arg));
}

}  // namespace

namespace {
struct TxnUnitView {
    std::atomic<TxnPhase>* phase;
    uint64_t age_ns;
    uint32_t age_io, age_seq;
};
TxnUnitView txn_unit_view(const Shard::WatchReservation& unit) {
    if (unit.unit_kind == 1) {
        auto& state = *static_cast<MultiExecState*>(const_cast<void*>(unit.token));
        auto& d = state.decision;
        return {&d.phase, d.age_ns, d.age_io, d.age_seq};
    }
    auto& state = *static_cast<ScatterState*>(const_cast<void*>(unit.token));
    auto& d = *state.group_attempt();
    return {&d.phase, d.age_ns, d.age_io, d.age_seq};
}
bool txn_version_before(const TxnUnitView& a, const TxnUnitView& b) {
    if (a.age_ns != b.age_ns) return a.age_ns < b.age_ns;
    if (a.age_io != b.age_io) return a.age_io < b.age_io;
    return a.age_seq < b.age_seq;
}
bool txn_reservation_live(const Shard::WatchReservation& r) {
    return r.entry_kind == 2 || (r.epoch &&
        r.epoch->load(std::memory_order_acquire) == 0 &&
        !(r.aborted && r.aborted->load(std::memory_order_acquire)));
}
bool txn_wound(const Shard::WatchReservation& holder, Shard& shard, Server& server) {
    auto view = txn_unit_view(holder);
    TxnPhase placing = TxnPhase::Placing;
    if (!view.phase->compare_exchange_strong(placing, TxnPhase::Wounded,
                                             std::memory_order_acq_rel)) return false;
    uint64_t zero = 0;
    if (holder.epoch->compare_exchange_strong(zero, kAtomicCancelledEpoch,
                                             std::memory_order_acq_rel)) {
        server.note_txn(server.worker_of_shard(shard.id()), holder.unit_kind == 1
            ? TxnCounter::Wounds : TxnCounter::GroupWounds);
        holder.aborted->store(true, std::memory_order_release);
    }
    return true;
}
}

#include "txn_key_queue.inc"

uint64_t Shard::watch_writer_stamp(Slice key, const void* token, bool whole) const {
    const auto found = watch_reservations_.find(whole ? std::string{} : watch_key_string(key));
    if (found == watch_reservations_.end()) return 0;
    for (const auto& r : found->second.marks)
        if ((TOMO_TXN_REGISTRY_VISIT(), r.entry_kind == 2) && r.token == token) return r.writer_generation;
    return 0;
}

bool Shard::watch_writer_mark(Slice key, const void* token, bool whole, uint64_t stamp) {
    const auto owned = whole ? std::string{} : watch_key_string(key);
    if (auto found = watch_reservations_.find(owned); found != watch_reservations_.end())
        for (const auto& r : found->second.marks)
            if ((TOMO_TXN_REGISTRY_VISIT(), r.entry_kind == 2) && r.token == token) return r.writer_generation == stamp;
    WatchReservation mark;
    mark.token = token;
    mark.entry_kind = 2;
    mark.writer_generation = stamp;
    if (!watch_append_reservation(owned, mark)) return false;
#ifdef TOMO_TXNORDER_DEBUG
    txn_debug_writer_mark(token, 1);
#endif
    server_->note_txn(server_->worker_of_shard(id()), TxnCounter::WriterMarks);
    return true;
}

void Shard::watch_writer_unmark(Slice key, const void* token, bool whole) {
    const auto found = watch_reservations_.find(whole ? std::string{} : watch_key_string(key));
    if (found == watch_reservations_.end()) return;
    auto& list = found->second.marks;
    const auto removed = std::erase_if(list, [&](const auto& r) {
        TOMO_TXN_REGISTRY_VISIT();
        return r.entry_kind == 2 && r.token == token;
    });
#ifdef TOMO_TXNORDER_DEBUG
    if (removed) txn_debug_writer_mark(token, -static_cast<int>(removed));
#else
    (void)removed;
#endif
    if (found->second.empty()) { watch_reservations_.erase(found); refresh_has_watches(); }
}

// Allocation failure must not leave a partial episode. This fallback does not
// allocate, including for long keys whose owned spelling could not be built.
void Shard::watch_writer_forget(const void* token) {
    for (auto it = watch_reservations_.begin(); it != watch_reservations_.end();) {
        const auto removed = std::erase_if(it->second.marks, [&](const auto& r) {
            TOMO_TXN_REGISTRY_VISIT();
            return r.entry_kind == 2 && r.token == token;
        });
#ifdef TOMO_TXNORDER_DEBUG
        if (removed) txn_debug_writer_mark(token, -static_cast<int>(removed));
#else
        (void)removed;
#endif
        if (it->second.empty()) it = watch_reservations_.erase(it);
        else ++it;
    }
    refresh_has_watches();
}

// Invariant I, checked only on the blocked path. A placing validator or a
// started TO-B claim must predate every episode covering that key.
void Shard::watch_writer_check(Slice key, bool whole, uint64_t stamp) {
    const auto check = [&](const auto& entries) {
        for (const auto& r : entries) {
            TOMO_TXN_REGISTRY_VISIT();
            if (!r.unit_kind || !r.blocking || !txn_reservation_live(r)) continue;
            const auto unit = txn_unit_view(r);
            if (unit.age_ns <= stamp ||
                unit.phase->load(std::memory_order_acquire) != TxnPhase::Placing) continue;
            if (r.entry_kind == 0 || (r.unit_kind == 2 &&
                (static_cast<const ScatterState*>(r.token)->group_attempt()->arrived[id()] & 4u)))
                server_->note_txn(server_->worker_of_shard(id()), TxnCounter::OrderViolations);
        }
    };
    if (whole) {
        for (const auto& [name, entries] : watch_reservations_) check(entries.held);
    } else {
        if (auto it = watch_reservations_.find(""); it != watch_reservations_.end()) check(it->second.held);
        if (auto it = watch_reservations_.find(watch_key_string(key));
            it != watch_reservations_.end()) check(it->second.held);
    }
}

// Retires every reservation on `key` whose unit has DECIDED, applying its effect, and answers
// whether anything still blocks a foreign unit on this key.
//
// "Decided" is epoch != 0 (the unit published a commit ticket) or aborted. An undecided
// reservation is kept. Only an undecided BLOCKING reservation -- the EXEC validate claim --
// makes this return false; an undecided atomic-group write reservation is left in place and
// answers "ready", because nothing may wait on it (Shard::WatchReservation::blocking).
bool Shard::watch_finalize_queue(const std::string& key, TxnKeyQueue& queue) {
    auto& list = queue.held;
    bool blocked = false;
    std::array<uint64_t, 4> dirty{};
    size_t keep = 0;
    for (size_t i = 0; i < list.size(); i++) {
        auto& reservation = list[i];
        TOMO_TXN_REGISTRY_VISIT();
        const uint64_t epoch = reservation.epoch
            ? reservation.epoch->load(std::memory_order_acquire) : 1;
        const bool aborted = epoch == kAtomicCancelledEpoch || (reservation.aborted &&
            reservation.aborted->load(std::memory_order_acquire));
        if (!aborted && epoch == 0) {
            if (reservation.blocking) {
                stats_.watch_reservation_waits++;
                blocked = true;
            }
            if (keep != i) list[keep] = reservation;
            keep++;
            continue;
        }
        if (!aborted && reservation.mutates)
            for (unsigned db = 0; db < dirty.size(); ++db)
                dirty[db] |= reservation.dirty_databases[db];
        if (reservation.handle) reservation.handle->queue = nullptr;
        if (reservation.refs) reservation.refs->fetch_sub(1, std::memory_order_release);
    }
    list.erase(list.begin() + keep, list.end());
    if (dirty[0] || dirty[1] || dirty[2] || dirty[3]) {
        auto watchers = watchers_.find(key);
        if (watchers != watchers_.end()) {
            for (const WatchEntry& entry : watchers->second)
                if ((dirty[entry.db / 64] & (uint64_t{1} << (entry.db % 64))) &&
                    entry.client && entry.client->watch_generation() == entry.generation)
                    entry.client->set_watch_dirty();
        }
    }
    return !blocked;
}

bool Shard::watch_finalize_reservation(const std::string& key) {
    auto found = watch_reservations_.find(key);
    if (found == watch_reservations_.end()) return true;
    const bool ready = watch_finalize_queue(key, found->second);
    txn_live_head(found->second);
    txn_live_head(found->second, true);
    if (found->second.empty()) {
        watch_reservations_.erase(found);
        refresh_has_watches();
    }
    return ready;
}

void Shard::watch_prune_stale(const std::string& key) {
    auto found = watchers_.find(key);
    if (found == watchers_.end()) return;
    auto& entries = found->second;
    size_t keep = 0;
    for (const Shard::WatchEntry& entry : entries) {
        if (entry.client && entry.client->watch_generation() == entry.generation) {
            entries[keep++] = entry;
        } else if (entry.client) {
            entry.client->watch_unref();
        }
    }
    entries.resize(keep);
    if (entries.empty()) {
        watchers_.erase(found);
        refresh_has_watches();
    }
}

bool Shard::watch_add(Slice key, Client* client, uint64_t generation, uint16_t db) {
    const std::string owned = watch_key_string(key);
    if (!watch_write_ready(key)) return false;
    bool pending = false;
    store_.atomic_visit_unit_records(FlatStore::hash_key(key), key, false, [&](AtomicEntry& e) {
        if (e.group && e.group_epoch && !e.group_epoch->load(std::memory_order_acquire) &&
            !(e.group_aborted && e.group_aborted->load(std::memory_order_acquire))) pending = true;
    });
    if (pending) return false; // F8: WATCH cannot miss an installed group's eventual write
    watch_prune_stale(owned);
    const uint8_t logical = server_ ? server_->databases().logical(key.ns) : key.ns;
    if (db == 256) db = logical;
    auto& entries = watchers_[owned];
    for (const WatchEntry& entry : entries)
        if (entry.client == client && entry.generation == generation && entry.db == db) return true;
    const int64_t deadline = db == logical
        ? store_.watch_deadline(FlatStore::hash_key(key), key) : -1;
    try { entries.push_back(WatchEntry{client, generation, static_cast<uint8_t>(db), deadline}); }
    catch (const std::bad_alloc&) {
        if (entries.empty()) watchers_.erase(owned);
        return false;
    }
    client->watch_ref();
    arm_watches();
    return true;
}

void Shard::watch_remove(Slice key, Client* client, uint64_t generation) {
    const std::string owned = watch_key_string(key);
    auto found = watchers_.find(owned);
    if (found == watchers_.end()) return;
    auto& entries = found->second;
    size_t keep = 0;
    for (const WatchEntry& entry : entries) {
        if (entry.client == client && entry.generation == generation) client->watch_unref();
        else entries[keep++] = entry;
    }
    entries.resize(keep);
    if (entries.empty()) {
        watchers_.erase(found);
        refresh_has_watches();
    }
}

bool Shard::watch_validate_and_reserve(Slice key, Client* client, uint64_t generation,
                                       const void* token, std::atomic<uint64_t>* epoch,
                                       std::atomic<bool>* aborted,
                                       std::atomic<uint32_t>* refs, bool mutates,
                                       MultiExecState* unit, bool reserve) {
    const std::string owned = watch_key_string(key);
    watch_finalize_reservation(owned);
    // A key that was alive when this client armed the WATCH and whose deadline has since elapsed is
    // a change, even when nothing has reaped it yet: redis aborts EXEC in that case whether the
    // removal came from its active cycle or is still pending. No command wrote the key, so the
    // reservation path never hears about it -- the armed deadline is the whole record.
    if (const auto watched = watchers_.find(owned); watched != watchers_.end()) {
        const int64_t now = now_ms_;
        const uint8_t logical = server_ ? server_->databases().logical(key.ns) : key.ns;
        for (const WatchEntry& entry : watched->second)
            if (entry.client == client && entry.generation == generation && entry.db == logical &&
                entry.expire_at_ms >= 0 && entry.expire_at_ms < now) {
                client->set_watch_dirty();
                break;
            }
    }
    if (client->watch_generation() != generation || client->watch_dirty()) return true;
    if (!reserve) return true;
    if (auto existing = watch_reservations_.find(owned); existing != watch_reservations_.end())
        for (auto& r : existing->second.held) if ((TOMO_TXN_REGISTRY_VISIT(), r.token == token)) {
            r.entry_kind = 0; // WATCH blocks from validation, before the started bit
            r.blocking = true;
            if (r.mutates) watch_note_database(r, server_, key.ns);
            return true;
        }
    WatchReservation claim{token, epoch, aborted, refs, client, generation,
                            false, true};
    claim.unit_kind = unit ? 1 : 0;
    claim.unit_mode = static_cast<uint8_t>(mutates ? TxnClaimMode::Write : TxnClaimMode::Read);
    if (!watch_append_reservation(owned, claim)) aborted->store(true, std::memory_order_release);
    return true;
}

bool Shard::watch_key_ready(const std::string& owned, const void* token, bool all_units) {
    const auto found = watch_reservations_.find(owned);
    if (found == watch_reservations_.end()) return true;
    auto& queue = found->second;
    if (token && queue.size() == 1 && queue.front().token == token) return true;
    watch_finalize_queue(owned, queue);
    if (queue.empty()) {
        watch_reservations_.erase(found);
        refresh_has_watches();
        return true;
    }
    // Waiters and writer marks cannot falsify unit execution. Preserve the
    // exact validation/all-units/started predicate and OrderViolations caller.
    for (const auto& r : queue.held) {
        TOMO_TXN_REGISTRY_VISIT();
        if (r.token == token || !r.blocking || !txn_reservation_live(r)) continue;
        if (r.entry_kind != 1 || all_units) return false;
        if (r.unit_kind == 1) {
            const auto& holder = *static_cast<const MultiExecState*>(r.token);
            if (holder.execution_noted[id()] & 8u) return false;
        } else if (r.unit_kind == 2) {
            const auto& holder = *static_cast<const ScatterState*>(r.token);
            if (holder.group_attempt()->arrived[id()] & 4u) return false;
        }
    }
    return true;
}

bool Shard::watch_write_ready(Slice key, const void* token) {
    return !has_watches() || (watch_key_ready("", token, false) &&
                              watch_key_ready(watch_key_string(key), token, false));
}
bool Shard::watch_group_write_ready(Slice key, const void* token) {
    return !has_watches() || (watch_key_ready("", token, true) &&
                              watch_key_ready(watch_key_string(key), token, true));
}

bool Shard::watch_txn_write_ready(Slice key, MultiExecState& state) {
    if (watch_group_write_ready(key, &state)) return true;
    server_->note_txn(server_->worker_of_shard(id()), TxnCounter::OrderViolations);
    return false;
}

void Shard::watch_reserve_write(Slice key, Client* writer, uint64_t writer_generation,
                                const void* token, std::atomic<uint64_t>* epoch,
                                std::atomic<bool>* aborted,
                                std::atomic<uint32_t>* refs) {
    if (watchers_.empty()) return;
    // A later WATCH cannot enter while this key has an undecided record. Only
    // existing registrations need a dirty reservation for this decision.
    const std::string owned = watch_key_string(key);
    if (auto existing = watch_reservations_.find(owned); existing != watch_reservations_.end())
        for (WatchReservation& reservation : existing->second.held)
            if ((TOMO_TXN_REGISTRY_VISIT(), reservation.token == token)) {
                reservation.mutates = true;
                watch_note_database(reservation, server_, key.ns);
                return;
            }
    if (watchers_.find(owned) == watchers_.end()) return;
    // Never exclusive, never a wait: this group's reservation sits alongside whatever else is
    // undecided on the key, and each one dirties the key's watchers at its OWN decision.
    if (auto found = watch_reservations_.find(owned);
        found != watch_reservations_.end() && !found->second.empty())
        stats_.watch_reservation_coexist++;
    if (!watch_append_reservation(owned, WatchReservation{
            token, epoch, aborted, refs, writer, writer_generation, true, /*blocking=*/false}))
        aborted->store(true, std::memory_order_release);
}

// Appends one reservation, leaving the map unchanged on allocation failure. Returns false when the
// caller must abort its unit rather than proceed with an unrecorded reservation.
bool Shard::watch_append_reservation(const std::string& key, const WatchReservation& reservation,
                                      TxnWaiter* handle) {
    try {
        auto& queue = watch_reservations_[key];
        if (reservation.entry_kind == 3) {
            TOMO_ASSERT(handle && !reservation.mutates);
            txn_link_waiter(queue, *handle, reservation);
        } else if (reservation.entry_kind == 2) {
            const auto at = std::upper_bound(queue.marks.begin(), queue.marks.end(),
                reservation.writer_generation, [](uint64_t stamp, const auto& r) {
                    TOMO_TXN_REGISTRY_VISIT();
                    return stamp < r.writer_generation;
                });
            queue.marks.insert(at, reservation);
        } else {
            queue.held.emplace_back(reservation, handle);
            if (reservation.mutates) watch_note_database(queue.held.back(), server_, static_cast<uint8_t>(key[0]));
            if (handle) handle->queue = &queue;
            if (reservation.refs) reservation.refs->fetch_add(1, std::memory_order_release);
        }
        arm_watches();
    } catch (const std::bad_alloc&) {
        auto found = watch_reservations_.find(key);
        if (found != watch_reservations_.end() && found->second.empty())
            watch_reservations_.erase(found);
        return false;
    }
    return true;
}

void Shard::watch_write_committed(Slice key, Client*, uint64_t) {
    if (!has_watches()) return;
    const std::string owned = watch_key_string(key);
    if (!watch_write_ready(key)) return;
    watch_prune_stale(owned);
    auto found = watchers_.find(owned);
    if (found == watchers_.end()) return;
    const uint8_t logical = server_ ? server_->databases().logical(key.ns) : key.ns;
    for (const WatchEntry& entry : found->second)
        if (entry.db == logical && entry.client && entry.client->watch_generation() == entry.generation)
            entry.client->set_watch_dirty();
}

void Shard::watch_physical_delete(Slice key, bool expired) {
    if (!has_watches()) return;
    const std::string owned = watch_key_string(key);
    watch_prune_stale(owned);
    const auto found = watchers_.find(owned);
    if (found == watchers_.end()) return;
    const uint8_t logical = server_ ? server_->databases().logical(key.ns) : key.ns;
    for (const auto& entry : found->second)
        if (entry.db == logical && entry.client &&
            entry.client->watch_generation() == entry.generation &&
            (!expired || entry.expire_at_ms >= 0))
            entry.client->set_watch_dirty();
}

bool Shard::watch_all_write_ready(const void* token) {
    if (!has_watches()) return true;
    std::vector<std::string> keys;
    try {
        keys.reserve(watch_reservations_.size());
        for (const auto& item : watch_reservations_) keys.push_back(item.first);
    } catch (const std::bad_alloc&) {
        return false;
    }
    for (const std::string& key : keys)
        if (!watch_key_ready(key, token, false)) return false;
    return true;
}

bool Shard::watch_flush(int physical_db) {
    // Capture existence before tombstones/clear erase it. WATCH registrations
    // pin these clients for this owner turn. Failed preparation dirties nobody.
    std::vector<Client*> dirty;
    try {
        for (const auto& [owned, entries] : watchers_) {
            const uint8_t ns = static_cast<uint8_t>(owned[0]);
            if (physical_db >= 0 && ns != physical_db) continue;
            const uint8_t logical = server_ ? server_->databases().logical(ns) : ns;
            const Slice key(owned.data() + 1, owned.size() - 1, ns);
            const bool present = store_.find_no_touch(FlatStore::hash_key(key), key) != nullptr;
            for (const auto& entry : entries)
                if (entry.db == logical && entry.client &&
                    entry.client->watch_generation() == entry.generation &&
                    (present || (entry.expire_at_ms >= 0 && entry.expire_at_ms < now_ms_)))
                    dirty.push_back(entry.client);
        }
    } catch (const std::bad_alloc&) { return false; }
    if (!store_.atomic_tombstone_all(physical_db)) return false;
    for (Client* client : dirty) client->set_watch_dirty();
    return true;
}

void Shard::watch_database_swap(uint8_t first, uint8_t second) {
    if (!has_watches() || first == second) return;
    DatabaseMap::Read map(server_->databases());
    watch_database_swap(first, second, map[first], map[second]);
}

bool Shard::watch_database_swap(uint8_t first, uint8_t second, uint8_t physical_first,
                               uint8_t physical_second,
                               std::vector<std::pair<Client*, uint64_t>>* deferred) {
    if (!has_watches() || first == second) return true;
    for (auto& [owned, entries] : watchers_) {
        const uint8_t ns = static_cast<uint8_t>(owned[0]);
        if (ns != physical_first && ns != physical_second) continue;
        const Slice key(owned.data() + 1, owned.size() - 1, ns);
        // Both pre-swap physical namespaces have an alias on THEIR owner. A
        // present key in either side changes both logical keys; absent/absent
        // must preserve WATCH. Expired keys are absent at this owner's cut.
        const bool present = store_.find_no_touch(FlatStore::hash_key(key), key) != nullptr;
        for (const WatchEntry& entry : entries)
            if ((entry.db == first || entry.db == second) && entry.client &&
                entry.client->watch_generation() == entry.generation &&
                (present || (entry.expire_at_ms >= 0 && entry.expire_at_ms < now_ms_))) {
                if (deferred) {
                    try { deferred->emplace_back(entry.client, entry.generation); }
                    catch (const std::bad_alloc&) { return false; }
                    entry.client->watch_ref();
                } else entry.client->set_watch_dirty();
            }
    }
    return true;
}


namespace {
template <typename Fn>
void for_each_plain_write_key(Op& op, Fn&& fn) {
    if (op.local_xshard()) for_each_touched_key(op, fn);
    else if (op.spec->flags & CmdFlags::ScriptRoute)
        for_each_spec_key(op, [&](Slice key) { fn(0, key); });
    else fn(op.hash, op_routed_key(op));
}

// Each enumerator visits the complete mark set on this owner, including "" for
// FLUSH. The first mark carries the episode stamp; all marks share its lifetime.
template <typename Each>
void txn_writer_episode(Shard& shard, Op& op, Each&& each) {
    try {
        uint64_t stamp = 0;
        bool first = true;
        each([&](Slice key, bool whole) {
            if (first) { stamp = shard.watch_writer_stamp(key, &op, whole); first = false; }
        });
        if (!stamp) stamp = now_ns();
        bool complete = true;
        each([&](Slice key, bool whole) {
            complete &= shard.watch_writer_mark(key, &op, whole, stamp);
        });
        if (!complete) { shard.watch_writer_forget(&op); return; }
        each([&](Slice key, bool whole) { shard.watch_writer_check(key, whole, stamp); });
    } catch (const std::bad_alloc&) {
        shard.watch_writer_forget(&op);
    }
}
}

bool multi_plain_write_ready(Shard& shard, Op& op) {
    if (!shard.has_watches()) return true;
    bool ready = true;
    for_each_plain_write_key(op, [&](uint64_t, Slice key) {
        ready &= shard.watch_write_ready(key);
    });
    if (ready) {
        for_each_plain_write_key(op, [&](uint64_t, Slice key) { shard.watch_writer_unmark(key, &op); });
        return true;
    }
    txn_writer_episode(shard, op, [&](auto&& fn) {
        for_each_plain_write_key(op, [&](uint64_t, Slice key) { fn(key, false); });
    });
    op.mark_atomic_hazard();
    shard.server()->note_txn(shard.server()->worker_of_shard(shard.id()), TxnCounter::WriterWaits);
    return false;
}


namespace {
bool txn_scatter_write_ready(const Task& task, Shard& shard, Op& op) {
    auto& state = *task.scatter;
    auto& group = *group_for(state, shard.id());
    const void* token = state.multi_parent ? state.multi_parent
        : state.atomic_group ? static_cast<const void*>(&state) : nullptr;
    bool ready = true;
    if (state.group_attempt()) {
        // Placement arbitrates these groups, including MSETNX before its first
        // install. The early scatter visitor and gate must not bypass that order.
        if (!txn_group_ready(state, shard, op))
            return state.aborted.load(std::memory_order_acquire);
    }
    if (!group.count && !state.group_attempt()) {
        ready = shard.watch_all_write_ready(token);
    }
    for (uint32_t i = 0; i < group.count; ++i) {
        const Slice key = op.arg(state.keys[state.key_order[group.begin + i]].arg);
        const bool key_ready = state.atomic_group && !state.multi_child
            ? shard.watch_group_write_ready(key, token) : shard.watch_write_ready(key, token);
        if (!key_ready) ready = false;
    }
    if (!ready) {
        if (!state.atomic_group) txn_writer_episode(shard, op, [&](auto&& fn) {
            if (!group.count) fn(Slice{}, true);
            for (uint32_t i = 0; i < group.count; ++i)
                fn(op.arg(state.keys[state.key_order[group.begin + i]].arg), false);
        });
        if (state.kind != Kind::Script) {
            state.server->note_txn(state.server->worker_of_shard(shard.id()), TxnCounter::WriterWaits);
            return false;
        }
        // F2: APPLY owns a reserved ticket, so waiting here would freeze rule P
        // behind the unit that owns this claim. Cancel and finish the APPLY wave;
        // the existing script finalizer closes the bracket and restages (limit 8).
        uint64_t zero = 0;
        state.epoch.compare_exchange_strong(zero, kAtomicCancelledEpoch, std::memory_order_acq_rel);
        state.script_conflict.store(true, std::memory_order_release);
        state.aborted.store(true, std::memory_order_release);
        return true;
    }
    if (!state.atomic_group && !group.count) shard.watch_writer_unmark({}, &op, true);
    for (uint32_t i = 0; i < group.count; ++i) {
        const Slice key = op.arg(state.keys[state.key_order[group.begin + i]].arg);
        if (!state.atomic_group) shard.watch_writer_unmark(key, &op);

    }
    return true;
}
}

// ---- post-join shutdown (IoLoop::shutdown_clients_after_join only) ---------------------------
// Same borrow walk as multi_retire_entry's TLS branch, returning each borrow to its store
// directly: every owner has joined, so queue_borrow_release would post to a dead inbox.
static void multi_shutdown_return_tls_borrows(Server& server, WbEngine& wb, Client& client,
                                              MultiExecState& state) {
    if (!client.is_tls()) return;
    for (const auto& command : state.commands) {
        ScatterState* scatter = command->scatter;
        if (!scatter || scatter->kind != Kind::Mget || !scatter->values) continue;
        for (uint32_t i = 0; i < scatter->key_count; i++) {
            ValueSlot& slot = scatter->values[i];
            if (slot.kind != ValueKind::Borrow) continue;
            server.shard(slot.shard).store().unborrow(slot.ptr);
            wb.note_zc_suppressed_tls();
            slot.kind = ValueKind::Nil;
        }
    }
}

bool multi_shutdown_retirable(Server& server, WbEngine& wb, Client& client, Op& op) {
    auto* state = static_cast<MultiExecState*>(op.multi_state());
    if (!state) return true;
    // Exactly multi_retire's condition for running connection-local handlers.
    if (state->kind == MultiStateKind::Execute &&
        state->final_reply == MultiFinalReply::Exec &&
        !state->watch_failed.load(std::memory_order_acquire) &&
        !state->decision.aborted.load(std::memory_order_acquire))
        for (const auto& command : state->commands)
            if (command->kind == MultiCommandKind::IoLocal &&
                !(state->publication_started &&
                  (has_name(command->queued, "publish") || has_name(command->queued, "spublish"))))
                return false;
    multi_shutdown_return_tls_borrows(server, wb, client, *state);
    return true;
}

// multi_retire_entry without its handlers, reply and session bookkeeping: the Client is freed
// next. Owners released every record reference before IO destruction, so the state normally
// dies here; otherwise it waits exactly as an ordinary retirement would.
void multi_shutdown_discard(Server& server, WbEngine& wb, Client& client, Op& op,
                            ScatterArenaPool& pool, uint32_t owner_io,
                            std::vector<MultiExecState*>& deferred) {
    auto* state = static_cast<MultiExecState*>(op.multi_state());
    if (!state) return;
    multi_shutdown_return_tls_borrows(server, wb, client, *state);
    if (state->snapshot_registered) pool.unregister_snapshot(server, state, owner_io);
    op.detach_scatter_state();
    client.atomic_group_finished();
    release_admission(*state);
    state->retired = true;
    if (multi_records_done(*state)) {
        destroy_multi_state(state);
        return;
    }
    try { deferred.push_back(state); }
    catch (const std::bad_alloc&) {
        // As in multi_retire: leak one state rather than free words a record still names.
    }
}

}  // namespace tomo
