// Serverless topology demotion witnesses. No listener, io_uring instance or worker loop.
// All linked implementation TUs use TOMO_CORE_CONCURRENCY_TEST; release has no hooks.
#include <atomic>
#include <cstdio>
#include <cstdlib>
#include <memory>
#include <new>
#include <optional>
#include <string>
#include <sys/wait.h>
#include <unistd.h>
#include <sched.h>
#include "src/core/io_loop.h"

static bool refuse_sidecar = false;
static unsigned refused_sidecars = 0;
// ReadLocalRobState is over-aligned. Replace only the standard nothrow aligned
// allocation entry; successful allocations retain the normal ASAN-aware allocator.
void* operator new(size_t size, std::align_val_t alignment, const std::nothrow_t&) noexcept {
    if (refuse_sidecar && size == sizeof(tomo::ReadLocalRobState) &&
            static_cast<size_t>(alignment) == alignof(tomo::ReadLocalRobState)) {
        ++refused_sidecars;
        return nullptr;
    }
    try { return ::operator new(size, alignment); }
    catch (...) { return nullptr; }
}

namespace tomo {
struct CoreConcurrencyTest {
    enum class Fault {
        None, NoFlip, Retry, NoCount, DirtyReply, DropOwner, CorruptReply, NoRetire,
        KeepChanging, NoOom, WrongArmReason, NoArmFence, NoArmRecovery
    };
    enum class Window { Capture, Copy, Open };
    inline static Fault fault = Fault::None;
    inline static FlatStore* changing = nullptr;
    inline static std::optional<FlatStore::ReadLocalTableGuard> guard;
    inline static unsigned captures = 0, flips = 0;
    inline static bool leave_open = false;

    static void require(bool ok, const char* message) {
        if (!ok) {
            std::fprintf(stderr, "FAIL rltopo: %s\n", message);
            std::_Exit(1);
        }
    }
    static Slice slice(const std::string& s) {
        return {s.data(), static_cast<uint32_t>(s.size())};
    }
    static void flip() {
        if (flips || fault == Fault::NoFlip) return;
        const uint64_t before = changing->read_local_state_acquire();
        guard.emplace(changing->read_local_table_guard());
        require(FlatStore::read_local_table_mutating(changing->read_local_state_acquire()),
                "writer bracket opened");
        if (!leave_open) {
            guard.reset();
            require(!FlatStore::read_local_generation_equal(
                        before, changing->read_local_state_acquire()), "generation advanced");
        }
        ++flips;
    }
    static void captured(const FlatStore&) { ++captures; flip(); }

    struct Fixture {
        Server server;
        ExLoopT<true> reader, owner;
        IoLoop io;
        uint32_t owner_id, reader_id;
        int32_t sid;
        std::string key;
        Fixture(ThreadMode mode, uint32_t databases = 1) : owner_id(mode == ThreadMode::Fused ? 0 : 6),
                                   reader_id(mode == ThreadMode::Fused ? 7 : 0) {
            cpu_set_t allowed;
            CPU_ZERO(&allowed);
            require(sched_getaffinity(0, sizeof(allowed), &allowed) == 0, "fixture affinity");
            std::string domain;
            unsigned count = 0;
            for (int cpu = 0; cpu < CPU_SETSIZE && count < 8; ++cpu) {
                if (!CPU_ISSET(cpu, &allowed)) continue;
                if (count++) domain += '+';
                domain += std::to_string(cpu);
            }
            require(count == 8, "eight allowed CPUs required, no skip");
            require(server.topo_.declare(domain.c_str()), "fixture topology");
            require(mode == ThreadMode::Fused
                        ? server.placement_.build_fused(server.topo_, nullptr)
                        : server.placement_.build_even(server.topo_, 6, 2), "fixture placement");
            require(server.placement_.reserve_runtime_roles(8), "fixture roles");
            Config cfg;
            cfg.thread_mode = mode;
            cfg.databases = databases;
            cfg.shards = 16;
            cfg.read_local = cfg.atomic = cfg.key_lb = cfg.client_lb = 1;
            cfg.flip_auto = 0;
            cfg.save.clear();
            require(server.init(cfg), "fixture initialization");
            for (uint32_t tid = 0; tid < server.nthreads(); ++tid) {
                auto& thread = server.thread(tid);
                require(mode == ThreadMode::Fused ? thread.init_task_inbox_local_fused()
                            : thread.init_task_inbox_local(server.placement().ifid_threads(),
                                                          server.placement().ex_threads()),
                        "fixture task lanes");
            }
            for (auto* loop : {&reader, &owner}) {
                loop->srv_ = &server;
                loop->self_ = &server.thread(loop == &reader ? reader_id : owner_id);
                loop->cached_now_ms_ = 1000;
                loop->read_local_.impl = std::make_unique<ReadLocalExImpl>();
                auto& lane = loop->read_local_impl();
                lane.lane = std::make_unique<ReadLocalExImpl::LaneEntry[]>(kInboxSlots);
                lane.lane_fallbacks = std::make_unique<ReadLocalFallbackReason[]>(kInboxSlots);
                require(lane.deferred.init(&server, loop->self_), "fixture QSBR queue");
                loop->refresh_live_config();
                loop->bind_fused_completion(nullptr, [](void*, Client*) {});
            }
            for (Shard* sh : server.thread(owner_id).shards())
                sh->store().configure_read_local(true, *owner.read_local_impl().deferred.sink());
            io.srv_ = &server;
            io.self_ = &server.thread(reader_id);
            io.fused_executor_ = &reader;
            reader.bind_read_local_demotion(&io,
                [](void* context, Client* client, const uint64_t* ids,
                   const ReadLocalFallbackReason* reasons, uint32_t count, uint32_t& demoted) {
                    auto& loop = *static_cast<IoLoop*>(context);
                    if (fault == Fault::DirtyReply) client->rob().at(ids[0]).reply.append("bad", 3);
                    require(client->rob().at(ids[0]).reply.size() == 0,
                            "private reply cleared before demotion");
                    const bool result = loop.fused_demote_local_read_batch(
                        client, ids, reasons, count, demoted);
                    if (fault == Fault::NoCount) loop.self_->read_local_stats().fallback_seq_churn--;
                    return result;
                });
            sid = server.thread(owner_id).shards().front()->id();
            for (unsigned i = 0; i < 100000; ++i) {
                key = "rltopo-" + std::to_string(i);
                if (server.router().shard_of(FlatStore::hash_key(slice(key))) == sid) break;
            }
            require(server.router().shard_of(FlatStore::hash_key(slice(key))) == sid,
                    "bounded fixture key search");
            KvObj* object = kvobj_new_string(slice(key), Slice("value"));
            require(object && server.shard(sid).store().insert(FlatStore::hash_key(slice(key)), object)
                        == FlatStore::InsertResult::Inserted, "fixture value");
        }
        ~Fixture() {
            guard.reset();
            FlatStore::test_read_local_captured = nullptr;
            ExLoopT<true>::test_local_read_copied_ = nullptr;
            owner.read_local_impl().deferred.drain_shutdown();
            for (Shard* sh : server.thread(owner_id).shards()) sh->store().configure_read_local(false, {});
        }
        Op& enqueue(Client& client, unsigned keys) {
            client.set_id(1);
            client.set_ifid_thread(reader_id);
            client.set_wb_slot(server.thread(reader_id).assign_wb_slot(&client));
            Op* op = client.rob().acquire_read_local();
            require(op != nullptr, "fixture ROB slot");
            require(op->push_arg(Slice(keys ? "MGET" : "GET")), "fixture command name");
            for (unsigned i = 0; i < (keys ? keys : 1); ++i)
                require(op->push_arg(slice(key)), "fixture key argument");
            op->spec = command_lookup(op->arg(0));
            require(op->spec != nullptr, "fixture command registered");
            op->hash = FlatStore::hash_key(slice(key));
            op->shard = sid;
            op->mark_read_local();
            op->state.store(OpState::Issued, std::memory_order_release);
            const uint64_t id = client.rob().dispatch_id();
            client.rob().mark_current_read_local_hash(id, op->hash);
            if (keys) client.rob().arm_current_local_mget_fence();
            client.rob().publish();
            reader.enqueue_local_read(&client, id, keys ? std::min(keys, server.nshards()) : 1);
            return *op;
        }
    };

    // Exact private-reply and demotion contracts for the single-attempt cleanup. Mutants in
    // tools/readreply_proof.py change the real header, never these expected results.
    inline static uint64_t readreply_hash = 0;
    inline static bool readreply_publish_conflict = false;
    inline static bool readreply_use_epochs = false;
    static void readreply_copied() {
        if (fault == Fault::NoFlip) return;
        if (readreply_publish_conflict) {
            if (!flips++) changing->foreign_read_scope_open(readreply_hash);
        } else if (readreply_use_epochs) {
            if (!flips++) {
                changing->foreign_read_scope_open(readreply_hash);
                changing->foreign_read_scope_close(readreply_hash);
            }
        } else {
            flip();
        }
    }

    static void readreply_case(ThreadMode mode, uint32_t databases, bool mget,
                               const std::string& state) {
        Fixture f(mode, databases);
        FlatStore& store = f.server.shard(f.sid).store();
        const uint64_t hash = FlatStore::hash_key(slice(f.key));
        const std::string label = std::string(mget ? "MGET/" : "GET/") + state;
        auto check = [&](bool okay, const char* contract) {
            require(okay, ("readreply " + label + ": " + contract).c_str());
        };
        std::string value("raw\0\r\npayload", 13);
        if (state == "external") value = std::string(513, 'x') + "\r\n";
        if (state == "empty") value.clear();
        if (state == "integer") value = "-9223372036854775808";
        const int64_t deadline = state == "expired" ? 1000 : state == "ttl-live" ? 1001 : -1;
        KvObj* object = state == "integer"
            ? kvobj_new_int(slice(f.key), INT64_MIN)
            : kvobj_new_string(slice(f.key), slice(value), deadline, state == "persisted");
        require(object && store.insert(hash, object) == FlatStore::InsertResult::Inserted,
                "readreply fixture replacement");
        object->set_eviction_meta(3);
        const Enc encoding = object->encoding();
        check(encoding == (state == "integer" ? Enc::Int : state == "external" ? Enc::Extern : Enc::Raw),
              "requested encoding entered");
        // No concurrent user of this fixture. Restore deliberately invalid header tags below
        // before destruction; the capture and reply implementation still see the real tags.
        if (state == "typed") object->type = static_cast<uint8_t>(Type::Hash);
        if (state == "encoding") object->enc = static_cast<uint8_t>(Enc::Compact);
        if (state == "missing") require(store.erase(hash, slice(f.key)), "readreply fixture erase");
        Op op;
        require(op.push_arg(Slice(mget ? "MGET" : "GET")) && op.push_arg(slice(f.key)) &&
                    (!mget || op.push_arg(slice(f.key))), "readreply fixture argv");
        op.spec = command_lookup(op.arg(0));
        op.hash = hash;
        op.shard = f.sid;
        op.reply.append("stale", 5);
        op.reply_code_ = static_cast<uint8_t>(ReplyCode::Int);
        op.reply_ival_ = 42;
        op.zc_ptr = "stale";
        op.zc_len = 5;
        op.zc_shard = f.sid;
        f.reader.maxmemory_enabled_ = true;
        f.reader.foreign_touch_policy_ = ExLoopT<true>::kForeignTouchLru;
        f.reader.cached_lru_clock_ = 9;
        ExLoopT<true>::test_local_get_reply_attempts_ = 0;
        changing = &store;
        readreply_hash = hash;
        readreply_publish_conflict = state == "tail-pending";
        readreply_use_epochs = mget;
        flips = captures = 0;
        leave_open = false;
        if (state == "pending") store.foreign_read_scope_open(hash);
        if (state == "churn" || state == "churn-pending") {
            guard.emplace(store.read_local_table_guard());
            check(FlatStore::read_local_table_mutating(store.read_local_state_acquire()),
                  "topology window entered");
        }
        auto capture = store.read_local_prefetch_capture(hash, slice(f.key));
        if (state == "churn-pending") store.foreign_read_scope_open(hash);
        if (state == "invalid" || state == "tail-pending")
            ExLoopT<true>::test_local_read_copied_ = readreply_copied;
        const auto result = f.reader.prepare_local_read(op, mget ? nullptr : &store, mget,
                                                        mget ? nullptr : &capture);
        // This counts entries into the real GET emission path, including integer replies.
        // The restored-continue mutant must fail here even when its final bytes are correct.
        check(ExLoopT<true>::test_local_get_reply_attempts_ <= 1,
              "at most one GET reply attempt");
        if (state == "invalid" || state == "tail-pending")
            check(flips == 1, "copy window entered exactly once");
        ReadLocalFallbackReason reason = ReadLocalFallbackReason::None;
        if (state == "typed" || state == "encoding") reason = ReadLocalFallbackReason::Typed;
        if (state == "expired") reason = ReadLocalFallbackReason::Expired;
        if (state == "missing" && !mget) reason = ReadLocalFallbackReason::Missing;
        if (state == "pending" || state == "tail-pending" || state == "churn-pending")
            reason = ReadLocalFallbackReason::AtomicPending;
        if (state == "churn") reason = ReadLocalFallbackReason::SeqChurn;
        if (state == "invalid") reason = mget ? ReadLocalFallbackReason::Generation
                                              : ReadLocalFallbackReason::SeqChurn;
        check(result.fallback == reason, "exact final fallback reason");
        std::string expected;
        if (reason == ReadLocalFallbackReason::None) {
            if (mget) expected = "*2\r\n";
            for (unsigned i = 0; i < (mget ? 2u : 1u); ++i)
                expected += state == "missing" ? "$-1\r\n"
                    : "$" + std::to_string(value.size()) + "\r\n" + value + "\r\n";
        }
        check(std::string(op.reply.data(), op.reply.size()) == expected, "exact private reply bytes");
        check(op.reply_code_ == 0 && op.zc_ptr == nullptr && op.zc_len == 0 && op.zc_shard == -1,
              "reply code and borrowed state cleared");
        const bool success = reason == ReadLocalFallbackReason::None;
        check(result.keyspace_hits == (success && state != "missing" ? (mget ? 2u : 1u) : 0u) &&
                  result.keyspace_misses == (success && state == "missing" ? 2u : 0u),
              "exact accepted hit and miss counts");
        if (state != "missing" && state != "encoding") {
            // MGET records each accepted value before its outer window closes. GET records
            // access only after final validation; retain this intentional ordering difference.
            const bool touched = success || (mget && (state == "invalid" || state == "tail-pending"));
            check(object->eviction_meta() == (touched ? 9 : 3), "access metadata ordering");
        }
        ExLoopT<true>::test_local_read_copied_ = nullptr;
        if (state == "pending" || state == "tail-pending" || state == "churn-pending")
            store.foreign_read_scope_close(hash);
        guard.reset();
        if (state == "typed") object->type = static_cast<uint8_t>(Type::String);
        if (state == "encoding") object->enc = static_cast<uint8_t>(encoding);
        std::printf("PASS readreply %s db=%u\n", label.c_str(), databases);
    }

    static void readreply_all(ThreadMode mode) {
        for (uint32_t databases : {1u, 4u})
            for (bool mget : {false, true})
                for (const char* state : {"raw", "integer", "external", "empty", "typed", "encoding",
                        "ttl-live", "expired", "persisted", "missing", "pending", "churn", "invalid",
                        "tail-pending", "churn-pending"})
                    readreply_case(mode, databases, mget, state);
    }

    static void topology(ThreadMode mode, unsigned keys, Window window, bool open) {
        Fixture f(mode);
        Client client(-1);
        Op& op = f.enqueue(client, keys);
        changing = &f.server.shard(f.sid).store();
        captures = flips = 0;
        leave_open = open;
        if (window == Window::Capture) FlatStore::test_read_local_captured = captured;
        else if (window == Window::Copy) ExLoopT<true>::test_local_read_copied_ = flip;
        else flip();
        // Restore a reader retry in the fixture, outside production code. The capture
        // hook counts actual probes, so this must fail even though INFO has no retry row.
        if (fault == Fault::Retry) (void)f.reader.prepare_captured_local_mget(op);
        require(f.reader.drain_local_reads() == 1, "one lane operation consumed");
        require(flips == 1, "forced topology window fired exactly once");
        const auto& stats = f.server.thread(f.reader_id).read_local_stats();
        std::printf("rltopo keys=%u window=%u open=%u captures=%u demotions=%llu\n",
                    keys, static_cast<unsigned>(window), open, captures,
                    static_cast<unsigned long long>(stats.fallback_seq_churn + stats.fallback_generation));
        std::fflush(stdout);
        require(window != Window::Capture || captures == (keys ? keys : 1),
                "zero Churn/SeqChurn retries");
        require(stats.fallback_seq_churn + stats.fallback_generation == 1 && stats.fallbacks() == 1 &&
                    stats.hits == 0 && (!keys || stats.mget_fallbacks() == 1),
                "exactly one topology demotion");
        require(!client.rob().has_pending_read_local() && op.state.load() == OpState::Issued,
                "demoted read pending on owner");
        guard.reset();
        FlatStore::test_read_local_captured = nullptr;
        ExLoopT<true>::test_local_read_copied_ = nullptr;
        unsigned tasks = f.server.thread(f.owner_id).drain_tasks([&](const Task& task) {
            require(task.client == &client && task.op_id == client.rob().flush_id(),
                    "owner receives same ROB operation");
            if (fault == Fault::DropOwner) return;
            require(f.owner.execute(task), "owner completes demoted read");
        });
        require(tasks == 1 && op.state.load() == OpState::Done, "exactly one owner hop and completion");
        std::string expected;
        if (keys) expected = "*" + std::to_string(keys) + "\r\n";
        for (unsigned i = 0; i < (keys ? keys : 1); ++i) expected += "$5\r\nvalue\r\n";
        if (fault == Fault::CorruptReply) op.reply.append("bad", 3);
        require(std::string(op.reply.data(), op.reply.size()) == expected, "owner reply intact");
        const unsigned retired = fault == Fault::NoRetire ? 0 : client.rob().drain([](Op&) {});
        require(retired == 1, "single ROB retirement");
        Client clean(-1);
        Op& clean_op = f.enqueue(clean, keys);
        if (fault == Fault::KeepChanging) guard.emplace(changing->read_local_table_guard());
        require(f.reader.drain_local_reads() == 1 && clean_op.state.load() == OpState::Done &&
                    stats.hits == 1 && stats.fallbacks() == 1,
                "next stable read stays local without another demotion");
        clean.rob().drain([](Op&) {});
    }

    static void arm(bool oom) {
        Client client(-1);
        auto& rob = client.rob();
        ReadLocalStats stats;
        rob.set_read_local_arm_stats(&stats.arm);
        if (oom) require(!rob.read_local_write_conflicts(2, read_local_command_touches_hash),
                         "fresh read arms without a fence");
        Op* write = rob.acquire_read_local();
        require(write != nullptr, "write ROB slot");
        write->hash = 1;
        write->state.store(OpState::Issued);
        refused_sidecars = 0;
        refuse_sidecar = oom && fault != Fault::NoOom;
        rob.mark_current_write();
        refuse_sidecar = false;
        rob.publish();
        if (oom) require(refused_sidecars == 1 && stats.arm.sidecars == 0,
                         "sidecar allocation refusal fired");
        if (fault == Fault::NoArmFence) {
            write->state.store(OpState::Done);
            rob.drain([](Op&) {});
        }
        require(rob.read_local_write_conflicts(2, read_local_command_touches_hash),
                "disjoint read is fenced during accepted transient");
        auto reason = IoLoop::read_local_write_fallback_reason(rob);
        if (fault == Fault::WrongArmReason) reason = ReadLocalFallbackReason::InflightWrite;
        stats.note_fallback(reason);
        require(stats.fallback_arm_transient == 1 && stats.fallback_inflight_write == 0,
                "accepted transient attributed to arm counter");
        write->state.store(OpState::Done);
        require(rob.drain([](Op&) {}) == 1, "retire pre-arming write");
        if (fault == Fault::NoArmRecovery) {
            Op* next = rob.acquire_read_local();
            require(next != nullptr, "control ROB slot");
            next->hash = 2;
            next->state.store(OpState::Issued);
            rob.mark_current_write();
            rob.publish();
        }
        require(!rob.read_local_write_conflicts(2, read_local_command_touches_hash),
                "arm transient ends at ROB retirement");
    }

    template <typename Fn>
    static void negative(Fault broken, const char* message, Fn&& fn) {
        int output[2];
        require(pipe(output) == 0, "control pipe");
        std::fflush(nullptr);
        const pid_t child = fork();
        require(child >= 0, "control fork");
        if (!child) {
            close(output[0]);
            require(dup2(output[1], STDERR_FILENO) >= 0, "control stderr");
            close(output[1]);
            fault = broken;
            fn();
            std::_Exit(0);
        }
        close(output[1]);
        std::string error;
        char buffer[1024];
        ssize_t n;
        while ((n = read(output[0], buffer, sizeof buffer)) > 0) error.append(buffer, n);
        close(output[0]);
        int status = 0;
        require(waitpid(child, &status, 0) == child, "control wait");
        require(WIFEXITED(status) && WEXITSTATUS(status) == 1 &&
                    error.find(std::string("FAIL rltopo: ") + message + "\n") != std::string::npos,
                "negative control must fail at its designated assertion");
        std::printf("CONTROL caught: %s\n", message);
    }

    static void run(ThreadMode mode) {
        readreply_all(mode);
        for (bool open : {false, true}) {
            topology(mode, 0, Window::Capture, open);
            topology(mode, 0, Window::Copy, open);
            topology(mode, 1, Window::Capture, open);
            topology(mode, ExLoopT<true>::LocalMgetWindow::kMaxEpochKeys + 1, Window::Copy, open);
        }
        topology(mode, 0, Window::Open, true);
        topology(mode, 1, Window::Open, true);
        for (Fault broken : {Fault::NoFlip, Fault::Retry, Fault::NoCount, Fault::DirtyReply}) {
            const char* message = broken == Fault::NoFlip ? "forced topology window fired exactly once"
                : broken == Fault::Retry ? "zero Churn/SeqChurn retries"
                : broken == Fault::NoCount ? "exactly one topology demotion"
                : "private reply cleared before demotion";
            negative(broken, message, [&] { topology(mode, 1, Window::Capture, false); });
        }
        for (auto [broken, message] : {
                std::pair{Fault::DropOwner, "exactly one owner hop and completion"},
                std::pair{Fault::CorruptReply, "owner reply intact"},
                std::pair{Fault::NoRetire, "single ROB retirement"},
                std::pair{Fault::KeepChanging, "next stable read stays local without another demotion"}})
            negative(broken, message, [&] { topology(mode, 1, Window::Capture, false); });
        arm(false);
        arm(true);
        negative(Fault::NoOom, "sidecar allocation refusal fired", [] { arm(true); });
        for (bool oom : {false, true}) {
            negative(Fault::WrongArmReason, "accepted transient attributed to arm counter",
                     [&] { arm(oom); });
            negative(Fault::NoArmFence, "disjoint read is fenced during accepted transient",
                     [&] { arm(oom); });
            negative(Fault::NoArmRecovery, "arm transient ends at ROB retirement",
                     [&] { arm(oom); });
        }
    }
};
} // namespace tomo

int main(int argc, char** argv) {
    using T = tomo::CoreConcurrencyTest;
    T::require((argc == 2 || (argc == 5 && std::string(argv[2]) == "readreply")) &&
                   (std::string(argv[1]) == "1s" || std::string(argv[1]) == "2s"),
               "usage: rltopo-unit 1s|2s [readreply GET|MGET STATE]");
    T::require(tomo::command_registry_init(false), "command registry");
    const auto mode = std::string(argv[1]) == "1s" ? tomo::ThreadMode::Fused : tomo::ThreadMode::Split;
    if (argc == 5) T::readreply_case(mode, 1, std::string(argv[3]) == "MGET", argv[4]);
    else T::run(mode);
    std::printf("PASS rltopo %s (demotions, zero retries, negative controls, arm transients)\n", argv[1]);
}
