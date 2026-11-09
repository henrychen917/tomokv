#include "src/core/io_loop.h"
#include <cassert>
#include <cstdio>
#include <new>
#include <cstdlib>
#include <sys/resource.h>
#include <sys/wait.h>
#include <unistd.h>

static bool fail_next_allocation = false;
static void (*allocation_hook)(void*) = nullptr;
static void* allocation_context = nullptr;
void* operator new(std::size_t size) {
    if (auto hook = allocation_hook) {
        allocation_hook = nullptr;
        hook(allocation_context);
    }
    if (fail_next_allocation) {
        fail_next_allocation = false;
        throw std::bad_alloc();
    }
    if (void* p = std::malloc(size ? size : 1)) return p;
    throw std::bad_alloc();
}
void operator delete(void* p) noexcept { std::free(p); }
void operator delete(void* p, std::size_t) noexcept { std::free(p); }
using namespace tomo;

static void ring_cases() {
    fail_next_allocation = true;
    PlainReadHolds ring;
    bool created = false;
    assert(ring.floor() == UINT64_MAX);
    auto a = ring.acquire(9, created); assert(created);
    assert(ring.acquire(9, created) == a && !created);
    auto b = ring.acquire(12, created); assert(created);
    auto c = ring.acquire(15, created); assert(created);
    ring.release(b);  // a dead interior generation cannot advance the floor
    ring.release(a); assert(ring.floor() == 10);
    ring.release(a); assert(ring.floor() == 16);
    ring.raise_newest(17); assert(ring.floor() == 18);
    ring.release(c); assert(ring.floor() == UINT64_MAX);
    uint16_t slots[PlainReadHolds::kSlots];
    for (uint32_t i = 0; i < PlainReadHolds::kSlots; ++i) {
        slots[i] = ring.acquire((uint64_t{1} << 32) + i, created);
        assert(created);
    }
    // Full-ring fallback retains the newest older cut, without allocating.
    const auto joined = ring.acquire((uint64_t{1} << 33), created);
    assert(!created && joined == slots[PlainReadHolds::kSlots - 1]);
    for (auto slot : slots) ring.release(slot);
    assert(ring.floor() == (uint64_t{1} << 32) + PlainReadHolds::kSlots);
    ring.release(joined); assert(ring.floor() == UINT64_MAX);
    assert(fail_next_allocation); fail_next_allocation = false;
    // Exercise ring reuse and cuts spanning more than a low-word wrap.
    for (uint32_t i = 0; i < PlainReadHolds::kSlots * 3; ++i) {
        auto slot = ring.acquire((uint64_t{1} << 34) + i, created);
        assert(created); ring.release(slot);
    }
    const pid_t pid = fork(); assert(pid >= 0);
    if (!pid) {
        rlimit limit{0, 0}; setrlimit(RLIMIT_CORE, &limit);
        ring.acquire(100, created); ring.acquire(99, created);
        _exit(0);
    }
    int status = 0; assert(waitpid(pid, &status, 0) == pid);
    assert(WIFSIGNALED(status) && WTERMSIG(status) == SIGABRT);
}

static void advance(Server& server) {
    std::atomic<uint64_t> epoch{0}; server.atomic_commit_group(epoch);
}

static void bucket_cases(Server& server) {
    ScatterArenaPool pool;
    PlainReadHold h;
    uint8_t bucket = 0;
    const uint64_t cut = server.atomic_snapshot();
    fail_next_allocation = true;
    assert(pool.plain_hold_begin(server, h, cut, 1, bucket, 0) == cut && bucket == 1);
    assert(fail_next_allocation); fail_next_allocation = false;
    pool.plain_hold_cover(h, bucket, 8);
    assert(server.atomic_read_floor() == cut + 1 && h.a_end == 8);
    advance(server);
    const uint64_t newer = server.atomic_snapshot();
    assert(pool.plain_hold_begin(server, h, newer, 8, bucket, 0) == newer && bucket == 2);
    pool.plain_hold_cover(h, bucket, 16);
    const auto b = h.b_slot;
    advance(server);
    assert(pool.plain_hold_begin(server, h, server.atomic_snapshot(), 16, bucket, 0) ==
           server.atomic_snapshot());
    assert(bucket == 2 && h.b_slot == b);
    pool.plain_hold_cover(h, bucket, 24);
    pool.plain_hold_cover(h, bucket, 20); assert(h.b_end == 24);
    pool.plain_hold_cover(h, 0, 30); assert(h.b_end == 24);
    pool.plain_hold_retire(server, h, 7, false, 0);
    assert(h.live() && server.atomic_read_floor() == cut + 1);
    pool.plain_hold_retire(server, h, 8, false, 0);
    assert(h.a_slot == b && h.a_end == 24 && h.b_slot == PlainReadHold::kNone);
    assert(server.atomic_read_floor() == newer + 1);
    pool.plain_hold_retire(server, h, 24, false, 0);
    assert(!h.live() && server.atomic_read_floor() == UINT64_MAX);

    // Both buckets may die in one drain; quiescence discards conservative ends too.
    for (bool quiesced : {false, true}) {
        pool.plain_hold_begin(server, h, server.atomic_snapshot(), 31, bucket, 0);
        pool.plain_hold_cover(h, bucket, 32);
        pool.plain_hold_begin(server, h, server.atomic_snapshot(), 32, bucket, 0);
        pool.plain_hold_cover(h, bucket, 40);
        pool.plain_hold_retire(server, h, quiesced ? 31 : 40, quiesced, 0);
        assert(!h.live() && server.atomic_read_floor() == UINT64_MAX);
    }
    for (uint64_t id : {uint64_t{65535}, UINT64_MAX}) {
        pool.plain_hold_begin(server, h, server.atomic_snapshot(), uint16_t(id), bucket, 0);
        pool.plain_hold_cover(h, bucket, uint16_t(id + 1));
        pool.plain_hold_retire(server, h, id, false, 0);
        assert(h.live());
        pool.plain_hold_retire(server, h, id + 1, false, 0); assert(!h.live());
    }

    // Fresh pool: no cached scatter cut can hide publish-then-confirm advancement.
    ScatterArenaPool fresh;
    assert(fresh.plain_hold_begin(server, h, cut, 0, bucket, 0) == server.atomic_snapshot());
    assert(server.atomic_read_floor() == server.atomic_snapshot() + 1);
    fresh.plain_hold_discard(server, h, 0);
    assert(!h.live() && server.atomic_read_floor() == UINT64_MAX);

    pool.plain_hold_begin(server, h, server.atomic_snapshot(), 1, bucket, 0);
    const auto held_floor = server.atomic_read_floor();
    advance(server);
    SnapshotCut scatter; scatter.snapshot = cut;
    assert(pool.register_snapshot(server, &scatter, 0));
    assert(scatter.snapshot == server.atomic_snapshot());
    assert(pool.confirmed_snapshot_cut() == scatter.snapshot);
    assert(server.atomic_read_floor() == held_floor);
    scatter.snapshot_complete.store(true); server.note_atomic_snapshot_complete(0);
    assert(pool.refresh_snapshot_floor(server, 0) == 1);
    assert(server.atomic_read_floor() == held_floor);  // completion cannot release the hold
    pool.unregister_snapshot(server, &scatter, 0);
    assert(server.atomic_read_floor() == held_floor);
    assert(pool.plain_hold_begin(server, h, cut, 2, bucket, 0) == scatter.snapshot);
    pool.plain_hold_discard(server, h, 0);  // joined shutdown, including both buckets
    assert(!h.live() && server.atomic_read_floor() == UINT64_MAX);

    puts("PASS ring/buckets: allocation-free, wrap, full join, rotation, progress, combined floors, confirmation, discard");
}

static void continuous_progress(Server& server) {
    ScatterArenaPool pool;
    PlainReadHold h;
    uint8_t bucket = 0;
    // Continuous sliding window: the ROB is never quiescent, and B may extend over
    // several passes. A must rotate out so the floor advances throughout the run.
    uint64_t issued = 0, flush = 0, previous_floor = 0;
    unsigned advances = 0;
    for (unsigned pass = 0; pass < 3000; ++pass) {
        advance(server);
        pool.plain_hold_begin(server, h, server.atomic_snapshot(), uint16_t(issued), bucket, 0);
        issued += 8;
        pool.plain_hold_cover(h, bucket, uint16_t(issued));
        if (issued > 56) flush = issued - 56;
        if (h.live()) pool.plain_hold_retire(server, h, flush, false, 0);
        assert(issued - flush >= 8 && issued - flush <= 56);
        const auto floor = server.atomic_read_floor();
        assert(floor != UINT64_MAX && floor >= previous_floor);
        if (floor > previous_floor) ++advances;
        previous_floor = floor;
    }
    assert(advances > 100);  // always extending A fails this assertion
    pool.plain_hold_discard(server, h, 0);
    puts("PASS continuously nonempty ROB advances cleanup floor");
}

struct DrainContext { Server& server; ScatterArenaPool& pool; unsigned calls = 0; };
static void bind_drain(WbEngine& wb, Ring& ring, DrainContext& context, uint32_t& now,
                       LoopSignals& signals, const std::atomic<bool>& limits) {
    wb.bind(&ring, nullptr, [](void*, int32_t, const char*) { std::abort(); }, &context,
            [](void*, Client&, Op&) { std::abort(); }, &limits, nullptr,
            [](void*, Client&) { return false; }, &now, &signals);
    wb.bind_plain_hold([](void* opaque, Client& client) {
        auto& c = *static_cast<DrainContext*>(opaque); ++c.calls;
        auto& rob = client.rob();
        c.pool.plain_hold_retire(c.server, rob.plain_hold(), rob.flush_id(), rob.quiesced(), 0);
    });
}
static void drain_cases(Server& server) {
    for (bool suppress : {false, true}) for (bool closing : {false, true})
        for (bool parked : {false, true}) {
        ScatterArenaPool pool;
        Client client(-1);
        if (closing) client.mark_closing();
        auto& rob = client.rob();
        Op* first = rob.acquire<true>(); assert(first);
        reply_ok(first->sink()); rob.publish();
        Op* second = rob.acquire<true>(); assert(second);
        uint8_t bucket = 0;
        pool.plain_hold_begin(server, rob.plain_hold(), server.atomic_snapshot(),
                              uint16_t(rob.dispatch_id()), bucket, 0);
        reply_ok(second->sink()); rob.publish();
        pool.plain_hold_cover(rob.plain_hold(), bucket, uint16_t(rob.dispatch_id()));
        Op* coordinator = nullptr;
        if (parked) {
            coordinator = rob.acquire<true>(); assert(coordinator);
            reply_ok(coordinator->sink()); rob.publish();
            if (suppress) coordinator->mark_reply_skip();
            // An uncovered coordinator must not extend the covered read's end.
        }
        if (suppress) { first->mark_reply_skip(); second->mark_reply_skip(); }
        Ring ring; WbEngine wb; uint32_t now = 0; LoopSignals signals;
        std::atomic<bool> limits{false}; DrainContext context{server, pool};
        bind_drain(wb, ring, context, now, signals, limits);
        bool submit = false;
        auto drain = [&] {
            if (suppress) wb.prepare_suppressing(client, submit, false);
            else wb.prepare<true, true>(client, submit);
        };
        drain(); assert(context.calls == 0 && rob.plain_hold().live());
        first->state.store(OpState::Done, std::memory_order_release);
        drain(); assert(context.calls == 1 && rob.plain_hold().live() && !rob.quiesced());
        second->state.store(OpState::Done, std::memory_order_release);
        drain(); assert(context.calls == 2 && !rob.plain_hold().live());
        assert(rob.quiesced() == !parked);
        if (parked) {
            coordinator->state.store(OpState::Done, std::memory_order_release);
            drain(); assert(context.calls == 2 && rob.quiesced());
        }
        assert(server.atomic_read_floor() == UINT64_MAX);
        if (suppress) assert(client.nothing_to_write());
    }
    puts("PASS real WB drains: normal, suppressed, closing, unfinished younger read");
}

namespace tomo {
struct CoreConcurrencyTest {
    static void scatter_carry(Server& server) {
        IoLoop io;
        io.srv_ = &server; io.self_ = &server.thread(0);
        for (uint32_t tid : server.placement().ex_threads())
            assert(server.thread(tid).init_task_inbox_local(server.placement().ifid_threads(),
                                                           server.placement().ex_threads()));
        std::string keys[2];
        for (int shard = 0; shard < 2; ++shard) {
            for (unsigned i = 0; i < 10000; ++i) {
                std::string key = "carry:" + std::to_string(i);
                if (server.router().shard_of(FlatStore::hash_key(Slice(key.data(), key.size()))) == shard) {
                    keys[shard] = key; break;
                }
            }
            assert(!keys[shard].empty());
        }
        Client client(-1); client.set_id(1); client.set_ifid_thread(0);
        client.set_wb_slot(server.thread(0).assign_wb_slot(&client));
        auto& rob = client.rob();
        Op* older = rob.acquire<true>(); assert(older); reply_ok(older->sink()); rob.publish();
        const uint64_t cut = server.atomic_snapshot();
        uint8_t bucket = 0;
        io.scatter_pool_.plain_hold_begin(server, rob.plain_hold(), cut, 1, bucket, 0);
        io.scatter_pool_.plain_hold_begin(server, rob.plain_hold(), cut, 1, bucket, 0);
        auto bulk = [](const std::string& value) {
            return "$" + std::to_string(value.size()) + "\r\n" + value + "\r\n";
        };
        const std::string request = "*2\r\n$3\r\nGET\r\n" + bulk(keys[0]) +
            "*3\r\n$4\r\nMGET\r\n" + bulk(keys[0]) + bulk(keys[1]) +
            "*2\r\n$3\r\nGET\r\n" + bulk(keys[1]);
        std::memcpy(client.rbuf(), request.data(), request.size());
        client.commit_read(request.size());
        struct Window { Server& server; Rob<64>& rob; uint64_t at = UINT64_MAX; } window{server, rob};
        allocation_context = &window;
        allocation_hook = [](void* opaque) {
            auto& w = *static_cast<Window*>(opaque);
            w.at = w.rob.dispatch_id();
            advance(w.server);
        };
        io.parse_and_dispatch<false>(&client);
        assert(!allocation_hook && window.at == 2); // after first GET, before MGET publishes
        allocation_context = nullptr;
        const uint64_t confirmed = server.atomic_snapshot();
        assert(confirmed > cut && rob.dispatch_id() == 4);
        assert(rob.at(1).read_cut(confirmed) == cut);
        assert(rob.at(2).has_scatter_state());
        assert(io.scatter_pool_.confirmed_snapshot_cut() == confirmed);
        assert(rob.at(3).read_cut(confirmed) == confirmed); // requires the scatter-path carry
        unsigned posted = 0;
        for (uint32_t tid : server.placement().ex_threads())
            server.thread(tid).drain_tasks([&](const Task&) { ++posted; });
        assert(posted == 4);
        auto* state = rob.at(2).scatter_state();
        rob.at(2).detach_scatter_state();
        xshard_destroy(state, io.scatter_pool_, 0);
        for (uint64_t id = 0; id < 4; ++id) rob.at(id).state.store(OpState::Done);
        Ring ring; WbEngine wb; uint32_t now = 0; LoopSignals signals;
        std::atomic<bool> limits{false}; DrainContext context{server, io.scatter_pool_};
        bind_drain(wb, ring, context, now, signals, limits);
        bool submit = false; wb.prepare<true, true>(client, submit);
        assert(rob.quiesced() && !rob.plain_hold().live());
        assert(server.atomic_read_floor() == UINT64_MAX);
        io.active_.erase(&client); client.set_in_active(false);
        server.thread(0).release_wb_slot(client.wb_slot());
        puts("PASS production parser: confirmed scatter cut reaches the same pass's younger GET");
    }

    static void parser_wrap(Server& server) {
        static_assert(offsetof(Rob<64>, plain_hold_) == 120);
        IoLoop io;
        io.srv_ = &server; io.self_ = &server.thread(0);
        for (uint32_t tid : server.placement().ex_threads())
            assert(server.thread(tid).init_task_inbox_local(server.placement().ifid_threads(),
                                                           server.placement().ex_threads()));
        for (uint64_t start : {uint64_t{65534}, UINT64_MAX - 1})
            for (const char* tail : {"", "*3\r\n$4\r\nWAIT\r\n$1\r\n1\r\n$1\r\n0\r\n",
                                    "*3\r\n$4\r\nFLIP\r\n$1\r\n1\r\n$1\r\n7\r\n"}) {
            Client client(-1); client.set_id(1); client.set_ifid_thread(0);
            client.set_wb_slot(server.thread(0).assign_wb_slot(&client));
            auto& rob = client.rob();
            rob.dispatch_.store(start); rob.flush_.store(start);
            constexpr char request[] = "*2\r\n$3\r\nGET\r\n$1\r\nx\r\n*2\r\n$3\r\nGET\r\n$1\r\ny\r\n";
            std::memcpy(client.rbuf(), request, sizeof(request) - 1);
            std::memcpy(client.rbuf() + sizeof(request) - 1, tail, std::strlen(tail));
            client.commit_read(sizeof(request) - 1 + std::strlen(tail));
            io.parse_and_dispatch<false>(&client);
            assert(client.rpos() == sizeof(request) - 1); // OrderedLocal waits for both reads.
            assert(rob.dispatch_id() == start + 2 && rob.plain_hold().live());
            assert(rob.plain_hold().a_end == uint16_t(start + 2));
            unsigned posted = 0;
            for (uint32_t tid : server.placement().ex_threads())
                server.thread(tid).drain_tasks([&](const Task& task) {
                    assert(task.client == &client); ++posted;
                });
            assert(posted == 2);
            Ring ring; WbEngine wb; uint32_t now = 0; LoopSignals signals;
            std::atomic<bool> limits{false}; DrainContext context{server, io.scatter_pool_};
            bind_drain(wb, ring, context, now, signals, limits);
            bool submit = false;
            rob.at(start).state.store(OpState::Done, std::memory_order_release);
            wb.prepare<true, true>(client, submit);
            assert(rob.flush_id() == start + 1 && rob.plain_hold().live());
            rob.at(start + 1).state.store(OpState::Done, std::memory_order_release);
            wb.prepare<true, true>(client, submit);
            assert(rob.quiesced() && !rob.plain_hold().live());
            io.active_.erase(&client); client.set_in_active(false);
            server.thread(0).release_wb_slot(client.wb_slot());
        }
        puts("PASS production parser/WB: end wraps at 2^16 and 2^64, hold survives partial drain");
    }
};
}

int main(int argc, char** argv) {
    static_assert(sizeof(Op) == 336 && sizeof(Client) == 1984 && sizeof(ThreadCtx) == 1408);
    static_assert(sizeof(Shard) == 1440 && sizeof(FlatStore) == 944 && sizeof(Rob<64>) == 192);
    static_assert(sizeof(AtomicEntry) == 144 && sizeof(Config) == 624);
    if (argc == 1) ring_cases();
    assert(command_registry_init(false));
    Config cfg; cfg.databases = 1; cfg.shards = 16; cfg.even_ifid = 6; cfg.even_ex = 2;
    cfg.key_lb = cfg.client_lb = cfg.flip_auto = 0; cfg.save.clear();
    Server server; assert(server.prepare_boot(cfg) && server.init(cfg));
    if (argc == 2) {
        assert(std::string(argv[1]) == "--progress");
        continuous_progress(server);
        return 0;
    }
    bucket_cases(server); continuous_progress(server);
    drain_cases(server); CoreConcurrencyTest::parser_wrap(server);
    CoreConcurrencyTest::scatter_carry(server);
    puts("PASS tornhold layouts and hold lifetime");
}
