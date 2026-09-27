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
    enum class Fault { None, NoFlip, Retry, NoCount, DirtyReply, NoOom, WrongArmReason };
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
        Fixture(ThreadMode mode) : owner_id(mode == ThreadMode::Fused ? 0 : 6),
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
                loop->fused_handoff_ring_ = &loop->ring_;
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
            ExLoopT<true>::test_retry_local_mget_ = false;
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

    static void topology(ThreadMode mode, unsigned keys, Window window, bool open) {
        Fixture f(mode);
        Client client(-1);
        Op& op = f.enqueue(client, keys);
        changing = &f.server.shard(f.sid).store();
        captures = flips = 0;
        leave_open = open;
        ExLoopT<true>::test_retry_local_mget_ = fault == Fault::Retry;
        if (window == Window::Capture) FlatStore::test_read_local_captured = captured;
        else if (window == Window::Copy) ExLoopT<true>::test_local_read_copied_ = flip;
        else flip();
        require(f.reader.drain_local_reads() == 1, "one lane operation consumed");
        require(flips == 1, "forced topology window fired exactly once");
        const auto& stats = f.server.thread(f.reader_id).read_local_stats();
        std::printf("rltopo keys=%u window=%u open=%u captures=%u retries=%llu demotions=%llu\n",
                    keys, static_cast<unsigned>(window), open, captures,
                    static_cast<unsigned long long>(stats.mget_generation_retries),
                    static_cast<unsigned long long>(stats.fallback_seq_churn + stats.fallback_generation));
        std::fflush(stdout);
        require(stats.mget_generation_retries == 0 &&
                    (window != Window::Capture || captures == (keys ? keys : 1)),
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
            require(f.owner.execute(task), "owner completes demoted read");
        });
        require(tasks == 1 && op.state.load() == OpState::Done, "exactly one owner hop and completion");
        std::string expected;
        if (keys) expected = "*" + std::to_string(keys) + "\r\n";
        for (unsigned i = 0; i < (keys ? keys : 1); ++i) expected += "$5\r\nvalue\r\n";
        require(std::string(op.reply.data(), op.reply.size()) == expected, "owner reply intact");
        require(client.rob().drain([](Op&) {}) == 1, "single ROB retirement");
        Client clean(-1);
        Op& clean_op = f.enqueue(clean, keys);
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
        require(rob.read_local_write_conflicts(2, read_local_command_touches_hash),
                "disjoint read is fenced during accepted transient");
        auto reason = IoLoop::read_local_write_fallback_reason(rob);
        if (fault == Fault::WrongArmReason) reason = ReadLocalFallbackReason::InflightWrite;
        stats.note_fallback(reason);
        require(stats.fallback_arm_transient == 1 && stats.fallback_inflight_write == 0,
                "accepted transient attributed to arm counter");
        write->state.store(OpState::Done);
        require(rob.drain([](Op&) {}) == 1, "retire pre-arming write");
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
        arm(false);
        arm(true);
        negative(Fault::NoOom, "sidecar allocation refusal fired", [] { arm(true); });
        for (bool oom : {false, true})
            negative(Fault::WrongArmReason, "accepted transient attributed to arm counter",
                     [&] { arm(oom); });
    }
};
} // namespace tomo

int main(int argc, char** argv) {
    using T = tomo::CoreConcurrencyTest;
    T::require(argc == 2 && (std::string(argv[1]) == "1s" || std::string(argv[1]) == "2s"),
               "usage: rltopo-unit 1s|2s");
    T::require(tomo::command_registry_init(false), "command registry");
    T::run(std::string(argv[1]) == "1s" ? tomo::ThreadMode::Fused : tomo::ThreadMode::Split);
    std::printf("PASS rltopo %s (demotions, zero retries, negative controls, arm transients)\n", argv[1]);
}
