#define TOMO_CORE_CONCURRENCY_TEST
#define TOMO_CORE_CONCURRENCY_EMBED
#include "core_concurrency_unit.cc"

namespace tomo {
struct NetcmdRegression {
    static void run(bool post_only) {
        using T = CoreConcurrencyTest;
        for (unsigned db : {1u, 16u}) {
            if (kSingleDatabase && db != 1) continue;
            for (auto kind : {IoLoop::DeferredTimerKind::ReceiveFin, IoLoop::DeferredTimerKind::ReceiveEof}) {
                T::Fixture<> f(false, 8, 16, db);
                std::string error;
                T::require(f.server.flip_begin(7, 1, f.io_id, error), "EOF surviving IO plan");
                Client client(-1); f.client(client);
                f.server.thread(f.io_id).add_client(&client); f.server.client_accepted();
                size_t available;
                auto* bytes = client.read_space(32, available, true);
                constexpr char input[] = "INCR accepted\r\n";
                std::memcpy(bytes, input, sizeof(input)-1); client.commit_read(sizeof(input)-1);
                f.io.deferred_timers_.push_back(IoLoop::DeferredTimer{&client, 0, 1000, 0, {}, kind});
                if (!post_only) {
                    f.server.flip_stage_.store(FlipStage::IoDrain);
                    T::require(!f.io.flip_timers_drained(), "precommit EOF still owns an obligation");
                    T::require(f.io.flip_immovable_refused(), "precommit EOF refuses the circular wait");
                    T::require(f.server.flip_failed(error) &&
                        error == "ERR FLIP refused: a connection is draining its end of stream", "exact EOF refusal");
                }
                f.server.flip_stage_.store(FlipStage::ClientInstall);
                T::require(f.io.flip_timers_drained(), "committed EOF may resume buffered input at Idle");
                client.barrier_acquire(BarrierOwner::Exec);
                T::require(!f.io.flip_timers_drained(), "EOF does not waive an executor barrier");
                client.barrier_release(BarrierOwner::Exec);
                const char borrowed[] = "borrowed";
                client.append_borrow_segment(borrowed, 8, f.sid());
                T::require(!f.io.flip_timers_drained(), "EOF does not waive a borrow pin");
                unsigned released = 0;
                client.release_all_segments([&](int32_t sid, const char* p) {
                    T::require(sid == f.sid() && p == borrowed, "exact EOF borrow"); ++released;
                });
                T::require(released == 1 && f.io.flip_timers_drained(), "borrow release restores readiness");
                f.io.deferred_timers_.push_back(IoLoop::DeferredTimer{nullptr, 0, 0, 0, {},
                    IoLoop::DeferredTimerKind::AcceptRetry});
                T::require(!f.io.flip_timers_drained(), "accept retry cannot be mistaken for EOF client");
                f.io.deferred_timers_.pop_back();
                T::require(client.rpos() == 0 && client.rlen() == sizeof(input)-1 &&
                    !std::memcmp(client.rbuf(), input, sizeof(input)-1), "complete accepted input retained exactly");
                if (!post_only) {
                    // Consumed input and idle work: this EOF closes through its own timer
                    // pass during the drain, so ordinary closes keep their approved outcome.
                    f.server.flip_stage_.store(FlipStage::IoDrain);
                    client.advance_parse(sizeof(input)-1);
                    T::require(!f.io.flip_immovable_refused(), "consumed idle EOF drains instead of refusing");
                }
                f.io.deferred_timers_.clear();
                f.server.flip_stage_.store(FlipStage::Idle);
                f.server.thread(f.io_id).remove_client(&client);
                f.server.thread(f.io_id).release_wb_slot(client.wb_slot()); f.server.client_released();
                std::printf("PASS wave15 EOF control db%u kind%u post-only%u\n", db, unsigned(kind), post_only);
            }
        }
    }
};
}
int main(int argc, char**) { tomo::NetcmdRegression::run(argc > 1); }
