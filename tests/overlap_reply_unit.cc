// Serverless O7 witness: the real O1 rotation and ROB, with a deterministic transport double.
// The next owner batch must finish WHILE the sink serializes the previous reply. No listener,
// kernel ring, load generator, probabilistic arming, or timing tolerance makes this pass.
#include <chrono>
#include <condition_variable>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <mutex>
#include <string>
#include <thread>
#include <type_traits>
#include <vector>
#include "src/core/iopipe_pipeline.h"
#include "src/core/overlap_reply.h"
#include "src/net/rob.h"

using namespace tomo;

static void require(bool ok, const char* message) {
    if (!ok) {
        std::fprintf(stderr, "FAIL overlap reply: %s\n", message);
        std::_Exit(1); // negative control may still have a parked witness thread
    }
}

// MSG_RING is queued by notification and delivered only at submit; eventfd is synchronous.
// Ordinary RECV SQEs can already be present and must not cause a busy-owner early syscall.
struct Transport {
    std::mutex mutex;
    std::condition_variable changed;
    bool ready = false, delivered = false, serializing = false, finished = false;
    bool wake_pending = false;
    unsigned sqes = 3, submits = 0, queries = 0;
    unsigned sq_ready() { queries++; return sqes; }
    void submit_and_reap() {
        std::lock_guard lock(mutex);
        submits++;
        if (wake_pending) delivered = true;
        wake_pending = false;
        sqes = 0;
        changed.notify_all();
    }
    void notify(bool parked, bool epoll, uint64_t& wakes) {
        std::lock_guard lock(mutex);
        ready = true;
        if (parked) {
            wakes++;
            if (!epoll) { wake_pending = true; sqes++; }
        }
        if (!parked || epoll) delivered = true;
        changed.notify_all();
    }
};

template <bool Epoll>
static void witness(bool natural, bool parked, bool expect_pre) {
    Transport ring;
    ModeScheduleStats stats;
    Rob<64> rob;
    Op* older = rob.acquire();
    require(older != nullptr, "older ROB slot");
    older->reply.append("N", 1);
    older->state.store(OpState::Done, std::memory_order_release);
    rob.publish();
    Op* younger = nullptr;
    uint64_t wakes = 0;
    uint32_t pending = 0, posts = 0;
    bool submitted = false, pubsub_boundary = false;
    std::vector<std::string> replies;

    std::thread owner([&] {
        std::unique_lock lock(ring.mutex);
        ring.changed.wait(lock, [&] {
            return ring.ready && ring.delivered && ring.serializing;
        });
        require(younger != nullptr, "owner work was published before notification");
        younger->reply.append("N+1", 3);
        younger->state.store(OpState::Done, std::memory_order_release);
        ring.finished = true;
        ring.changed.notify_all();
    });
    auto notify = [&] {
        const uint32_t count = pending;
        if (count) { ring.notify(parked, Epoll, wakes); pending = 0; posts++; }
        return count;
    };
    auto parse = [&] {
        younger = rob.acquire();
        require(younger != nullptr, "younger ROB slot");
        younger->state.store(OpState::Issued, std::memory_order_release);
        rob.publish();
        pending = 1;
    };
    auto serialize = [&] {
        if (expect_pre) {
            require(posts == (natural ? 1u : 0u), "PAD moved the notification boundary");
            require(ring.submits == 0, "PAD submitted before WB");
            // Release the intentionally parked worker only AFTER observing PRE's boundary.
            notify();
            if constexpr (!Epoll) if (parked) ring.submit_and_reap();
        }
        require(rob.drain([&](Op& op) {
            replies.emplace_back(op.reply.data(), op.reply.size());
            if (&op != older) return;
            std::unique_lock lock(ring.mutex);
            ring.serializing = true;
            ring.changed.notify_all();
            require(ring.changed.wait_for(lock, std::chrono::seconds(2), [&] { return ring.finished; }),
                    "next owner batch did not execute during reply serialization");
        }) == 2, "both replies retire exactly once in order");
    };

    if (natural) {
        parse();
        const uint64_t wakes_before = wakes;
        notify(); // O1's existing IFID.POST
        pubsub_boundary = true;
        if (wakes != wakes_before)
            overlap_reply_before_wb<Epoll>(1, 1, wakes_before, wakes, ring, submitted,
                                           stats, [] { return 0u; });
        serialize();
    } else {
        io_pipe_schedule([&]<IoPipeStage Stage>() {
            if constexpr (Stage == IoPipeStage::IfidParseHash) parse();
            else if constexpr (Stage == IoPipeStage::WbRetirePrepare) {
                overlap_reply_before_wb<Epoll>(pending, 1, wakes, wakes, ring, submitted,
                                               stats, notify);
                serialize();
                require(!pubsub_boundary, "shallow pub/sub boundary moved before preparation");
            } else if constexpr (Stage == IoPipeStage::IfidPost) {
                notify();
                pubsub_boundary = true;
            }
        });
    }
    owner.join();
    require(replies == std::vector<std::string>{"N", "N+1"}, "ROB reply order");
    require(rob.quiesced() && posts == 1 && pending == 0, "one owner notification, no retained work");
    require(pubsub_boundary, "normal pub/sub stage ran");
    require(stats.overlap_reply_early_posts == (!expect_pre && !natural ? 1u : 0u),
            "early-post witness must count only real notifications");
    require(stats.overlap_reply_early_submits == (!expect_pre && parked && !Epoll ? 1u : 0u),
            "early-submit witness must count only actual uring submissions");
    require(submitted == (!expect_pre && parked && !Epoll), "outer-loop submitted flag");
    require(ring.submits == (parked && !Epoll ? 1u : 0u), "no extra busy/epoll submissions");
    if constexpr (Epoll) require(ring.queries == 0, "epoll never queries a uring SQ");
}

static void empty_streams() {
    for (auto pair : {std::pair{0u, 3u}, std::pair{3u, 0u}, std::pair{0u, 0u}}) {
        Transport ring;
        ModeScheduleStats stats;
        uint64_t wakes = 1;
        bool submitted = false;
        const auto work = overlap_reply_before_wb<false>(pair.first, pair.second, 0, wakes,
            ring, submitted, stats, [] { require(false, "empty stream notified"); return 1u; });
        require(!work && !submitted && ring.queries == 0 && ring.submits == 0,
                "an empty stream performed work");
        require(stats.overlap_reply_early_posts == 0 && stats.overlap_reply_early_submits == 0,
                "empty stream must not claim engagement");
    }
    static_assert(std::is_empty_v<IoPipeLoopState<false>>);
}

static void full_ring_already_submitted(bool expect_pre) {
    Transport ring;
    ring.sqes = 0;
    uint64_t wakes = 1;
    bool submitted = false;
    ModeScheduleStats stats;
    overlap_reply_before_wb<false>(1, 1, 0, wakes, ring, submitted, stats, [] { return 0u; });
    require(!submitted && ring.submits == 0 && stats.overlap_reply_early_submits == 0,
            "already-submitted wake caused an empty submit");
    require(ring.queries == (expect_pre ? 0u : 1u), "control policy must bypass the SQ query");
}

int main(int argc, char** argv) {
    require(argc == 1 || (argc == 2 && !std::strcmp(argv[1], "--expect-pre")), "arguments");
    const bool expect_pre = argc == 2;
    empty_streams();
    for (bool natural : {false, true}) for (bool parked : {false, true}) {
        witness<false>(natural, parked, expect_pre);
        witness<true>(natural, parked, expect_pre);
    }
    full_ring_already_submitted(expect_pre);
    std::printf("PASS overlap reply: 8 %s schedules, empty streams, full-ring boundary, ROB order\n",
                expect_pre ? "PRE-control" : "engagement");
}
