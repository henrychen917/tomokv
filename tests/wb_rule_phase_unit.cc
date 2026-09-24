// Deterministic production-path witnesses. No listener, worker loop, real io_uring, or load.
// The only intercepted boundary is the kernel SQ submission; real liburing SQ accounting and
// real parser, inbox, execution, and writeback bodies run on fresh in-memory fixtures.
#include <array>
#include <atomic>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <memory>
#include <string>
#include <vector>
#include <sched.h>
#include "src/core/io_loop.h"

static const char* selected;
static unsigned submissions = 0, submitted_sends = 0;
extern "C" int __wrap_io_uring_submit(io_uring* ring) {
    const unsigned count = ring->sq.sqe_tail - ring->sq.sqe_head;
    if (count > ring->sq.ring_entries) std::abort();
    for (unsigned i = ring->sq.sqe_head; i != ring->sq.sqe_tail; ++i) {
        const auto& sqe = ring->sq.sqes[i & ring->sq.ring_mask];
        if (sqe.opcode != IORING_OP_SEND && sqe.opcode != IORING_OP_SENDMSG &&
            sqe.opcode != IORING_OP_SEND_ZC && sqe.opcode != IORING_OP_SENDMSG_ZC)
            std::abort();
        ++submitted_sends;
    }
    ++submissions;
    ring->sq.sqe_head = ring->sq.sqe_tail;
    *ring->sq.khead = ring->sq.sqe_tail;
    return static_cast<int>(count);
}
extern "C" int __wrap_io_uring_submit_and_get_events(io_uring* ring) {
    return __wrap_io_uring_submit(ring);
}

namespace tomo {
// C++ explicit instantiation permits naming a private member here. This test-only
// accessor installs the historical synthetic SQ without editing Ring or its layout.
struct RingSqAccess {
    using Type = io_uring Ring::*;
    friend Type ring_sq(RingSqAccess);
};
template <RingSqAccess::Type Member> struct RingSqMember {
    friend RingSqAccess::Type ring_sq(RingSqAccess) { return Member; }
};
template struct RingSqMember<&Ring::r_>;
struct CoreConcurrencyTest {
    static void require(bool ok, const char* message) {
        if (!ok) { std::fprintf(stderr, "FAIL wb-rule %s: %s\n", selected, message); std::_Exit(1); }
    }
    static Slice slice(const std::string& s) { return {s.data(), static_cast<uint32_t>(s.size())}; }
    template <bool Fused, bool SplitLocal = false> struct Fixture {
        Server server;
        ExLoopT<Fused || SplitLocal> ex;
        IoLoop io;
        const uint32_t owner = Fused || SplitLocal ? 0 : 6;
        uint32_t now = 1000;
        std::atomic<bool> limits{false};
        unsigned sq_head = 0;
        unsigned cq_head = 0, cq_tail = 0;
        std::array<io_uring_sqe, 8> sqes{};
        Fixture() {
            cpu_set_t cpus;
            CPU_ZERO(&cpus);
            require(sched_getaffinity(0, sizeof cpus, &cpus) == 0, "read affinity");
            std::string domain;
            unsigned count = 0;
            for (int cpu = 0; cpu < CPU_SETSIZE && count < 8; ++cpu) {
                if (!CPU_ISSET(cpu, &cpus)) continue;
                if (count++) domain += '+';
                domain += std::to_string(cpu);
            }
            require(count == 8, "eight allowed CPUs, no skip");
            require(server.topo_.declare(domain.c_str()), "topology");
            require(Fused ? server.placement_.build_fused(server.topo_, nullptr)
                          : server.placement_.build_even(server.topo_, 6, 2), "placement");
            require(server.placement_.reserve_runtime_roles(8), "roles");
            Config config;
            config.thread_mode = Fused ? ThreadMode::Fused : ThreadMode::Split;
            config.shards = 16;
            config.read_local = SplitLocal;
            config.overlap = config.atomic = 1;
            config.save.clear();
            require(server.init(config), "in-memory server state");
            for (unsigned tid = 0; tid < 8; ++tid) {
                ThreadCtx& thread = server.thread(tid);
                require(Fused ? thread.init_task_inbox_local_fused()
                              : thread.init_task_inbox_local(server.placement_.ifid_threads(),
                                                             server.placement_.ex_threads()), "inbox");
            }
            ex.srv_ = &server;
            ex.self_ = &server.thread(owner);
            ex.fused_handoff_ring_ = &ex.ring_;
            ex.cached_now_ms_ = 1000;
            server.bind_owner_notify_pending(owner, &ex.notify_keyless_pending_);
            if constexpr (SplitLocal) {
                ex.read_local_.impl = std::make_unique<ReadLocalExImpl>();
                require(ex.read_local_impl().deferred.init(&server, ex.self_), "split reader QSBR queue");
            }
            ex.refresh_live_config();
            ex.slowlog_armed_ = false;
            g_ring_epoll_mode = true;
            require(ex.ring_.init(8), "eventfd-only owner doorbell");
            g_ring_epoll_mode = false;
            io.srv_ = &server;
            io.self_ = &server.thread(0);
            if constexpr (Fused || SplitLocal) {
                io.fused_executor_ = &ex;
                ex.bind_fused_completion(nullptr, [](void*, Client*) {});
            }
            // A tiny real SQ data structure makes every ninth SEND use Ring::sqe's full path.
            auto& raw = io.ring_.*ring_sq(RingSqAccess{});
            raw.sq.khead = &sq_head;
            raw.sq.ring_entries = sqes.size();
            raw.sq.ring_mask = sqes.size() - 1;
            raw.sq.sqes = sqes.data();
            raw.cq.khead = &cq_head;
            raw.cq.ktail = &cq_tail;
            io.wb_.bind(&io.ring_, nullptr, [](void*, int32_t, const char*) {},
                        nullptr, [](void*, Client&, Op&) {}, &limits, nullptr,
                        [](void*, Client&) { return false; }, &now, &io.self_->sig());
        }
        std::string key(unsigned first = 0) {
            const int32_t sid = server.thread(owner).shards().front()->id();
            for (unsigned i = first; i < first + 100000; ++i) {
                std::string key = "wb-rule:" + std::to_string(i);
                if (server.router().shard_of(FlatStore::hash_key(slice(key))) == sid) return key;
            }
            require(false, "owner key search");
            return {};
        }
        void client(Client& c, unsigned id) {
            c.set_id(id);
            c.set_ifid_thread(0);
            c.set_wb_slot(server.thread(0).assign_wb_slot(&c));
            c.set_recv_armed(true);
        }
        Task get(Client& c, const std::string& key, bool set = false) {
            Op* op = c.rob().template acquire<false>();
            require(op != nullptr, "ROB acquire");
            require(op->push_arg({set ? "SET" : "GET", 3}) && op->push_arg(slice(key)), "command argv");
            if (set) require(op->push_arg({"value", 5}), "SET value");
            op->spec = command_lookup(op->arg(0));
            require(op->spec != nullptr, "GET registered");
            op->hash = FlatStore::hash_key(slice(key));
            op->shard = server.router().shard_of(op->hash);
            op->state.store(OpState::Issued, std::memory_order_release);
            Task task{&c, c.rob().dispatch_id(), -1, nullptr};
            c.rob().publish();
            return task;
        }
    };

    static void fill(Client& c, unsigned n, unsigned prefix) {
        for (unsigned i = 0; i < n; ++i) {
            Op* op = c.rob().acquire<false>(); require(op, "ROB capacity");
            op->reply.append("+OK\r\n", 5); c.rob().publish();
            op->state.store(i < prefix ? OpState::Done : OpState::Issued,
                            std::memory_order_release);
        }
    }
    template <bool Fused> static unsigned phase(Fixture<Fused>& f, bool r7 = false) {
        if constexpr (Fused) if (r7) return f.io.template r7_flush_ready<false, false, true>();
        return f.io.template flush_ready<false, false, Fused>();
    }
    template <bool Fused> static void budget(bool r7) {
        Fixture<Fused> f;
        std::vector<std::unique_ptr<Client>> clients;
        constexpr unsigned count = 96;
        constexpr unsigned expected = Fused ? count : 16;
        for (unsigned i = 0; i < count; ++i) {
            auto c = std::make_unique<Client>(-1); f.client(*c, i+1);
            fill(*c, 1, 1); f.io.enqueue_serve(c.get()); clients.push_back(std::move(c));
        }
        submissions = submitted_sends = 0;
        phase(f, r7);
        require(f.io.wb_.stats().serves == expected, "exact mode-specific budget");
        require(f.io.pending_serve_.size() == count-expected, "exact FIFO suffix");
        for (unsigned i = 0; i < count; ++i) {
            require(clients[i]->serve_pending() == (i >= expected), "served pin cleared; suffix pinned");
            require(clients[i]->rob().in_flight() == unsigned(i >= expected), "budget retires exact prefix");
        }
        if constexpr (Fused) require(submissions > 1 && submitted_sends >= count-8, "SQ full continues");
    }
    static void fastpath(bool r7) {
        Fixture<true> f;
        Client staged(-1), issued(-1); f.client(staged, 1); f.client(issued, 2);
        staged.fill_buf().append("+PUSH\r\n", 7); fill(issued, 1, 0);
        f.io.enqueue_serve(&staged); f.io.enqueue_serve(&issued); phase(f, r7);
        require(f.io.wb_.stats().serves == 2, "staged-only and p1 enter ordinary serve");
        require(staged.send_inflight() && !staged.serve_pending(), "zero-inflight output sent");
        require(issued.rob().in_flight() == 1 && !issued.send_inflight(), "p1 never retires Issued");
    }
    static void fifo(bool r7) {
        Fixture<true> f;
        Client a(-1), b(-1), c(-1);
        f.client(a, 1); f.client(b, 2); f.client(c, 3);
        fill(a, 32, 1); fill(b, 32, 0); fill(c, 1, 1);
        f.io.enqueue_serve(&a); f.io.enqueue_serve(&b); f.io.enqueue_serve(&c);
        phase(f, r7);
        require(c.rob().quiesced(), "younger eligible passes deferred head");
        require(f.io.pending_serve_.size() == 2 && f.io.pending_serve_[0] == &a &&
                f.io.pending_serve_[1] == &b, "deferred rotation preserves order");
        require(a.serve_pending() && b.serve_pending(), "deferred lifetime pins kept");
        f.io.enqueue_serve(&a);
        require(f.io.pending_serve_.size() == 2, "pin deduplicates future notification");
        require(a.rob().in_flight() == 32 && b.rob().in_flight() == 32, "deferred prefix not retired");
    }
    static void capture(bool r7) {
        Fixture<true> f;
        Client a(-1), b(-1), added(-1);
        f.client(a, 1); f.client(b, 2); f.client(added, 3);
        fill(a, 32, 0); fill(b, 1, 1); fill(added, 1, 1);
        struct Context { Fixture<true>* f; Client* added; unsigned calls = 0; } ctx{&f, &added};
        b.rob().at(0).zc_ptr = reinterpret_cast<const char*>(&ctx);
        added.rob().at(0).zc_ptr = reinterpret_cast<const char*>(&ctx);
        f.io.wb_.bind(&f.io.ring_, nullptr, [](void*, int32_t, const char*) {},
            &ctx, [](void* raw, Client&, Op& op) {
                auto& c = *static_cast<Context*>(raw); ++c.calls; op.zc_ptr = nullptr;
                c.f->io.enqueue_serve(c.added);
            }, &f.limits, nullptr, [](void*, Client&) { return false; }, &f.now, &f.io.self_->sig());
        f.io.enqueue_serve(&a); f.io.enqueue_serve(&b); phase(f, r7);
        require(ctx.calls == 1, "callback cannot extend captured visit count");
        require(added.rob().in_flight() == 1 && added.serve_pending() &&
                f.io.pending_serve_.size() == 2 && f.io.pending_serve_[0] == &a &&
                f.io.pending_serve_[1] == &added,
                "new arrival stays queued and pinned");
    }
    template <bool Fused> static void dead(bool r7) {
        Fixture<Fused> f;
        Client corpse(-1), live(-1); f.client(corpse, 1); f.client(live, 2);
        fill(corpse, 32, 0); corpse.mark_dead(); fill(live, 1, 1);
        f.io.enqueue_serve(&corpse); f.io.enqueue_serve(&live); phase(f, r7);
        require(!corpse.serve_pending() && f.io.pending_serve_.empty(), "dead entry removed and unpinned");
        require(f.io.wb_.stats().serves == 1 && live.rob().quiesced(), "dead entry consumes no service");
    }
    static void progress(bool r7) {
        Fixture<true> f;
        require(phase(f, r7) == 0, "empty fixture has no unrelated work");
        Client c(-1); f.client(c, 1); fill(c, 32, 1); f.io.enqueue_serve(&c);
        require(phase(f, r7) == 1 && f.io.wb_.stats().serves == 0, "deferral alone is positive work");
        for (unsigned i = 1; i < 32; ++i) c.rob().at(i).state.store(OpState::Done, std::memory_order_release);
        phase(f, r7); // Deliberately no new request or completion enqueue.
        require(c.rob().quiesced() && !c.serve_pending(), "completion releases without fresh arrival");
    }
    static void split_policy() {
        Fixture<false> f; Client c(-1); f.client(c, 1); fill(c, 32, 1);
        f.io.enqueue_serve(&c);
        // Eligible tails let a wrongly widened selector terminate at the split
        // budget, so the control fails an assertion rather than just timing out.
        std::vector<std::unique_ptr<Client>> tails;
        for (unsigned i = 0; i < 16; ++i) {
            auto tail = std::make_unique<Client>(-1); f.client(*tail, i+2);
            fill(*tail, 1, 1); f.io.enqueue_serve(tail.get()); tails.push_back(std::move(tail));
        }
        phase(f);
        require(f.io.wb_.stats().serves == 16 && c.rob().in_flight() == 31 && !c.serve_pending(),
                "2s never applies fused eligibility");
    }
    static void split_local_policy(bool sweeping) {
        Fixture<false, true> f; Client c(-1); f.client(c, 1); fill(c, 32, 1);
        require(f.ex.read_local_enabled() && f.server.thread_mode() == ThreadMode::Split,
                "physical split reader is armed");
        f.io.enqueue_serve(&c);
        std::vector<std::unique_ptr<Client>> tails;
        for (unsigned i = 0; i < 16; ++i) {
            auto tail = std::make_unique<Client>(-1); f.client(*tail, i+2);
            fill(*tail, 1, 1); f.io.enqueue_serve(tail.get()); tails.push_back(std::move(tail));
        }
        if (sweeping) f.io.sweep<false, false, false, true, true>();
        else f.io.flush_ready<false, false, true, false, false, true>();
        require(f.io.wb_.stats().serves == 16 && c.rob().in_flight() == 31 && !c.serve_pending(),
                "2s reader capability never enables fused writeback");
    }
    template <bool Fused> static void parse() {
        Fixture<Fused> f; Client c(-1); f.client(c, 1);
        const std::string key = f.key();
        const std::string request = "*2\r\n$3\r\nGET\r\n$" + std::to_string(key.size()) + "\r\n" + key + "\r\n";
        for (unsigned i = 0; i < 128; ++i) {
            std::memcpy(c.rbuf()+c.rlen(), request.data(), request.size()); c.commit_read(request.size());
        }
        f.io.template parse_and_dispatch<false, Fused ? kGenthreadIfidBatchOps : 0>(&c);
        const unsigned n = c.rob().in_flight();
        require(n == (Fused ? 32u : 64u) && c.rpos() < c.rlen(), "unchanged parser quantum");
        const unsigned posted = f.ex.self_->drain_tasks_unmasked([&](const Task& task) {
            require(task.client == &c && task.op_id < n, "real parsed GET publication");
        });
        require(posted == n, "every parsed GET reached owner inbox");
    }
    inline static ExLoop* observed_ex;
    inline static decltype(CommandSpec::handler) get_handler;
    inline static unsigned observed_ops;
    static void observed_get(Shard& shard, Op& op) {
        // Observe the real notification-batch frontier at the handler boundary. This
        // distinguishes 32 from 64/128 even though drain_tasks consumes the whole queue.
        require(observed_ex->notify_batch_n_ == observed_ops % 32, "default split EX chunk remains 32");
        ++observed_ops; get_handler(shard, op);
    }
    static void split_ex(bool timed, bool unmasked) {
        Fixture<false> f; const std::string key = f.key();
        CommandSpec spec = *command_lookup(Slice{"GET", 3});
        get_handler = spec.handler; spec.handler = observed_get;
        observed_ex = &f.ex; observed_ops = 0;
        std::vector<std::unique_ptr<Client>> clients;
        for (unsigned i = 0; i < 257; ++i) {
            auto c = std::make_unique<Client>(-1); f.client(*c, i+1);
            Task task = f.get(*c, key); c->rob().at(0).spec = &spec;
            require(f.ex.self_->post_task_quiet(i%2, task, f.io.self_->sig()), "enqueue split GET");
            clients.push_back(std::move(c));
        }
        for (unsigned p = 0; p < 2; ++p) f.ex.self_->flush_task_notify(p, f.io.ring_, f.io.self_->sig());
        f.ex.slowlog_armed_ = timed;
        if (timed) f.ex.slowlog_state_.escalate_batches = 1;
        // Omit the template argument: pins the default entry, not an explicit test-only width.
        require(f.ex.drain_tasks<>(unmasked) == 257 && observed_ops == 257, "default split EX full drain");
        for (auto& c : clients) require(c->rob().at(0).state.load() == OpState::Done, "all GETs Done");
        require(f.ex.self_->ex_inbound_quiesced(), "EX sources retired");
    }
    static int run(int argc, char** argv) {
        require(argc == 2 || argc == 3, "usage: wb-rule-phase-unit CASE [r7]");
        selected = argv[1]; const std::string name = selected;
        const bool r7 = argc == 3 && std::string(argv[2]) == "r7";
        require(command_registry_init(false), "command registry");
        if (name == "fused-budget") budget<true>(r7);
        else if (name == "split-budget") budget<false>(false);
        else if (name == "fastpath") fastpath(r7);
        else if (name == "fifo") fifo(r7);
        else if (name == "capture") capture(r7);
        else if (name == "dead") dead<true>(r7);
        else if (name == "split-dead") dead<false>(false);
        else if (name == "progress") progress(r7);
        else if (name == "split-policy") split_policy();
        else if (name == "split-local") split_local_policy(false);
        else if (name == "split-local-sweep") split_local_policy(true);
        else if (name == "fused-parse") parse<true>();
        else if (name == "split-parse") parse<false>();
        else if (name == "split-ex") split_ex(false, false);
        else if (name == "split-ex-unmasked") split_ex(false, true);
        else if (name == "split-ex-timed") split_ex(true, false);
        else require(false, "known proof");
        std::printf("PASS wb-rule %s\n", selected); return 0;
    }
};
} // namespace tomo
int main(int argc, char** argv) { return tomo::CoreConcurrencyTest::run(argc, argv); }
