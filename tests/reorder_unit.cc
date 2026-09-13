// Serverless R8 mechanism tests: real ROBs, FlatStore borrows and resumable popcount. The
// executor/atomic admission integration is in core_concurrency_unit.cc's scheduler row.
// Negative controls: make ex_split_possible always false; ignore same-client predecessors;
// remove borrow/unborrow together; or treat MultiShard/scatter as ordinary. Each must fail.
#include <cstdio>
#include <cstdlib>
#include <memory>
#include <string>
#include <vector>
#include "src/core/reorder.h"

// This fixture has only strings and no persistence, snapshots, notifications or transactions.
// Fail on any use of an excluded subsystem, including unexpected fixture type destruction.
namespace tomo {
void multi_session_destroy(MultiSession* s) { if (s) std::abort(); }
Shard::~Shard() = default;
StreamVal::~StreamVal() { std::abort(); }
ZsetVal::~ZsetVal() { std::abort(); }
HashVal::~HashVal() { std::abort(); }
uint64_t stream_groups_allocation_bytes(const void*) { std::abort(); }
uint64_t xshard_atomic_key_hash(const ScatterState*, uint32_t) { std::abort(); }
Slice xshard_atomic_key_slice(const ScatterState*, uint32_t) { std::abort(); }
bool AofProducer::record_delete(Slice, uint64_t) { std::abort(); }
bool AofProducer::record_post_image_buffered(FlatStore&, uint64_t, Slice, uint64_t) { std::abort(); }
void notify_flat_store_emit(const FlatStore*, uint32_t, NotifyEventId, Slice) { std::abort(); }
const SnapshotTypeHooks& snapshot_type_hooks(Type) { std::abort(); }
}

namespace {
using namespace tomo;
void require(bool ok, const char* why) {
    if (!ok) { std::fprintf(stderr, "FAIL reorder: %s\n", why); std::exit(1); }
}
void unused(Shard&, Op&) { std::abort(); }
constexpr CommandSpec spec(const char* name, uint32_t flags, CommandLengthClass length) {
    CommandSpec row(name, 2, -1, flags, unused, 1, 1, 1, unused);
    row.length_class = static_cast<uint8_t>(length);
    return row;
}
constexpr auto get = spec("GET", CmdFlags::Readonly, CommandLengthClass::Point);
constexpr auto set = spec("SET", CmdFlags::Write, CommandLengthClass::SmallMulti);
constexpr auto bits = spec("BITCOUNT", CmdFlags::Readonly | CmdFlags::SliceBitcount,
                           CommandLengthClass::Long);
constexpr auto multi = spec("MSET", CmdFlags::Write | CmdFlags::MultiShard,
                            CommandLengthClass::SmallMulti);
Slice view(const std::string& s) { return {s.data(), static_cast<uint32_t>(s.size())}; }

struct Fixture {
    KvBlockCache cache;
    Shard shard;
    std::vector<std::unique_ptr<Client>> clients;
    std::vector<Task> tasks;
    std::vector<uint32_t> begins, finishes, retries;
    std::vector<uint64_t> answers;
    uint32_t yield_calls = 0, mutations_while_pinned = 0;
    int fail_at = -1;
    std::string key = "bitmap", value = std::string(65536, '\xff');
    uint64_t hash = FlatStore::hash_key(view(key));
    explicit Fixture(bool armed) {
        if (armed) {
            require(shard.store().prepare_read_local(), "read-local storage");
            shard.store().configure_read_local(true, {nullptr,
                [](void*, void* owner, void* p, size_t n, ReadLocalRetireSink::ReclaimFn reclaim) {
                    reclaim(owner, p, n); // no foreign reader; force retention through the borrow
                }, &cache});
        }
        put(value);
    }
    ~Fixture() {
        require(shard.store().outstanding_borrows() == 0, "borrow escaped batch");
        cache.release_all();
    }
    void put(const std::string& bytes) {
        KvObj* obj = kvobj_new_string(view(key), view(bytes));
        require(obj, "string allocation");
        require(shard.store().insert(hash, obj) == FlatStore::InsertResult::Inserted,
                "string replacement");
    }
    void add(uint32_t client_id, const CommandSpec& command) {
        while (clients.size() <= client_id) clients.push_back(std::make_unique<Client>(-1));
        Client& client = *clients[client_id];
        const uint64_t id = client.rob().dispatch_id();
        Op* op = client.rob().acquire<false>();
        require(op, "ROB capacity");
        op->spec = &command;
        op->shard = 0;
        op->state.store(OpState::Issued, std::memory_order_release);
        client.rob().publish();
        tasks.emplace_back(&client, id, 0, nullptr);
        answers.push_back(0);
    }
    uint32_t index(const Task& task) { return static_cast<uint32_t>(&task - tasks.data()); }
    void complete(const Task& task) {
        const uint32_t i = index(task);
        Op& op = task.client->rob().at(task.op_id);
        if (op.spec == &bits) {
            const std::string want = ":" + std::to_string(answers[i]) + "\r\n";
            require(std::string(op.reply.data(), op.reply.size()) == want, "immutable count/reply");
        }
        require(op.state.load() == OpState::Issued, "one completion only");
        op.state.store(OpState::Done, std::memory_order_release);
        finishes.push_back(i);
    }
    ReorderResult run() {
        return ex_split_batch(tasks.data(), static_cast<uint32_t>(tasks.size()),
            [&](const Task& task, BitcountSlice* slice) {
                const uint32_t i = index(task);
                begins.push_back(i);
                // Check actual admission order independently of scheduler scratch state.
                for (uint32_t j = 0; j < i; j++) if (tasks[j].client == task.client)
                    require(tasks[j].client->rob().at(tasks[j].op_id).state.load() == OpState::Done,
                            "younger same-connection task entered before sliced predecessor");
                if (static_cast<int>(i) == fail_at) return false;
                Op& op = task.client->rob().at(task.op_id);
                if (op.spec == &bits) {
                    const Slice bytes = shard.store().find(hash, view(key))->str_value();
                    // Deliberately independent bit-at-a-time oracle, captured before mutation.
                    for (uint32_t j = 0; j < bytes.n; j++)
                        for (unsigned bit = 0; bit < 8; bit++)
                            answers[i] += (static_cast<unsigned char>(bytes.p[j]) >> bit) & 1;
                    if (slice) (*slice)(shard, op, bytes, 0, bytes.n);
                    else BitcountReply{}(shard, op, bytes, 0, bytes.n);
                    if (slice && slice->pending()) return true;
                } else if (op.spec == &set) {
                    mutations_while_pinned += shard.store().outstanding_borrows() != 0;
                    put(std::string(value.size(), '\0'));
                } else if (op.spec == &multi) {
                    require(shard.store().outstanding_borrows() == 0, "group crossed live slice");
                }
                complete(task);
                return true;
            },
            [&](const Task& task) { complete(task); },
            [&](const Task& task) { retries.push_back(index(task)); },
            [&] {
                require(shard.store().outstanding_borrows() != 0, "yield without live slice");
                yield_calls++;
            });
    }
};

void geometry(bool armed, uint32_t capacity) {
    for (uint32_t n = 2; n <= capacity; n++) {
        Fixture f(armed);
        f.add(0, bits);
        for (uint32_t i = 1; i < n; i++) f.add(i, i == 1 ? set : get);
        require(ex_split_possible(f.tasks.data(), n), "real mixed-client scope must arm");
        const auto result = f.run();
        require(result.sliced_commands == 1 && result.slice_yields == f.yield_calls && f.yield_calls,
                "slice/yield witnesses must fire");
        require(f.mutations_while_pinned == 1, "replacement must overlap unfinished count");
        require(f.begins.front() == 0 && f.finishes.front() == 1 && f.finishes.back() == 0,
                "must start blocker, execute peer, then finish blocker (no FIFO/sort substitute)");
        require(f.begins.size() == n && f.finishes.size() == n && f.retries.empty(),
                "batch conservation");
    }
}

void ordering(bool armed) {
    Fixture f(armed);
    f.add(0, bits); f.add(0, set); f.add(1, bits); f.add(2, set); f.add(0, bits);
    const auto result = f.run();
    require(result.sliced_commands >= 2 && f.mutations_while_pinned, "two live immutable counts");
    require(f.answers[0] == 65536 * 8 && f.answers[2] == 65536 * 8 && f.answers[4] == 0,
            "read before replacement / read your own later replacement");
    require(f.finishes.size() == 5, "same-client suffix drained");

    Fixture retry(armed);
    retry.add(0, bits); retry.add(0, get); retry.add(1, set); retry.add(2, get);
    retry.fail_at = 2;
    retry.run();
    require(retry.finishes == std::vector<uint32_t>{0}, "retry finishes only already-pinned reads");
    require(retry.retries == std::vector<uint32_t>({1, 2, 3}), "retry suffix is intact FIFO");

    Fixture barriers(armed);
    barriers.add(0, bits); barriers.add(1, multi); barriers.add(2, set);
    require(!ex_split_possible(barriers.tasks.data(), 3), "atomic barrier must close scope");
    require(barriers.run().sliced_commands == 0, "no slice across an atomic group");
    require(barriers.finishes == std::vector<uint32_t>({0, 1, 2}), "barrier FIFO");

    Fixture one(armed);
    for (uint32_t i = 0; i < kRobWindow; i++) one.add(0, i == 0 ? bits : get);
    require(!ex_split_possible(one.tasks.data(), kRobWindow), "one-client scope is a no-op");
    require(one.run().sliced_commands == 0 && !one.yield_calls, "one-client path cannot suspend");
}

void classification() {
    Fixture f(false);
    f.add(0, bits);
    for (uint32_t flag : {CmdFlags::Admin, CmdFlags::ConnLocal, CmdFlags::AllShards,
            CmdFlags::RandomShard, CmdFlags::CursorShard, CmdFlags::ConfigRoute,
            CmdFlags::ScriptRoute, CmdFlags::PubSub, CmdFlags::Blocking, CmdFlags::Transaction,
            CmdFlags::MultiShard, CmdFlags::StreamRoute, CmdFlags::SubcmdRoute,
            CmdFlags::FlipAsync, CmdFlags::NotifySelected, CmdFlags::SnapshotWrite}) {
        auto row = bits;
        row.flags |= flag;
        f.clients[0]->rob().at(0).spec = &row;
        require(ex_split_kind(f.tasks[0]) == SplitKind::Barrier, "special flag is a barrier");
    }
    f.clients[0]->rob().at(0).spec = &bits;
    f.tasks[0].scatter = reinterpret_cast<ScatterState*>(uintptr_t{1});
    require(ex_split_kind(f.tasks[0]) == SplitKind::Barrier, "tagged MULTI/scatter barrier");
    f.tasks[0].scatter = nullptr;
    f.tasks[0].client = nullptr;
    require(ex_split_kind(f.tasks[0]) == SplitKind::Barrier, "ownerless cleanup barrier");
}

void range_lifetime(bool armed) {
    Fixture f(armed);
    std::string bytes(4097, '\0');
    for (uint32_t i = 0; i < bytes.size(); i++) bytes[i] = static_cast<char>((i * 37 + 11) & 255);
    f.put(bytes);
    const Slice stored = f.shard.store().find(f.hash, view(f.key))->str_value();
    Op a, b;
    BitcountSlice first(4), second(4);
    constexpr size_t offset = 129, length = 3001;
    uint64_t expected = 3; // already-masked endpoint contribution from the shared parser
    for (size_t i = offset; i < offset + length; i++)
        for (unsigned bit = 0; bit < 8; bit++)
            expected += (static_cast<unsigned char>(bytes[i]) >> bit) & 1;
    first(f.shard, a, stored, offset, length, 3);
    second(f.shard, b, stored, offset, length, 3);
    require(first.pending() && second.pending() && f.shard.store().outstanding_borrows() == 2,
            "two ranges must pin the whole-value pointer");
    require(f.shard.store().erase(f.hash, view(f.key)), "delete while two counts are pinned");
    require(first.step(true) && f.shard.store().outstanding_borrows() == 1,
            "first release retains the other range");
    for (uint32_t turn = 0; turn < 4 && second.pending(); turn++) second.step();
    require(!second.pending() && f.shard.store().outstanding_borrows() == 0,
            "range slices finish in a bounded number of turns");
    const std::string reply = ":" + std::to_string(expected) + "\r\n";
    require(std::string(a.reply.data(), a.reply.size()) == reply &&
            std::string(b.reply.data(), b.reply.size()) == reply, "range sum survives deletion");

    Op small;
    BitcountSlice inline_value(128);
    char temporary[] = "123";
    inline_value(f.shard, small, Slice(temporary, 3), 0, 3);
    require(!inline_value.pending() && f.shard.store().outstanding_borrows() == 0,
            "handler-stack integer/inline buffers cannot suspend");
}
}

int main() {
    for (bool armed : {false, true}) {
        geometry(armed, tomo::kGenthreadExBatchOps);
        geometry(armed, tomo::kGenthreadPipelineExBatchOps);
        ordering(armed);
        range_lifetime(armed);
    }
    classification();
    std::puts("reorder battery: PASS (32/128, immutable slices, RYOW, barriers, retries)");
}
