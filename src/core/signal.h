// Cross-thread handoffs, ready/notify masks and loop measurements used by ThreadCtx and both
// roles. IO -> EX dispatch uses MaskedChannelArray; EX -> IO completion uses ready bits or
// Channel<Client*>. Queue publication and the wake protocol are separate: publish work, publish
// its mask, then decide whether to wake. Consumers take masks before draining and fence their
// blocked-state publication before rechecking work. A popped item still needs retirement before
// quiescence.
//
// LoopSignals records operations, nanoseconds and queue entries. Time-weighted busy accounting
// distinguishes cheap from expensive work; depth_sum/depth_samples describe sampled pressure
// rather than a single noisy spot depth. Owner-written scheduling counters are plain fields,
// while socket totals have relaxed atomic load/store updates for concurrent INFO/cron readers.

#pragma once
#include <algorithm>
#include <atomic>
#include <cstdint>
#include <ctime>
#include <vector>
#include "../exec/exqueue.h"
#include "../exec/masked_queue.h"
#include "../net/uring.h"
#include "exec1s.h"

namespace tomo {

// A scheduling-pressure signal older than one minute has already saturated every useful control
// decision. More importantly, the low-32-bit enqueue clock's "producer is a few microseconds ahead
// of the consumer's cached beat" sentinel must never become a multi-billion-us observation. Clamp
// at the source and again at export so neither future arithmetic drift nor a racy capture can put
// an absurd age on the operator/controller surface.
inline constexpr uint64_t kLbAgeSaneMaxUs = 60ull * 1000 * 1000;

inline uint64_t now_ns() {
    timespec ts;
    clock_gettime(CLOCK_MONOTONIC, &ts);
    return static_cast<uint64_t>(ts.tv_sec) * 1000000000ull + static_cast<uint64_t>(ts.tv_nsec);
}

// Wall clock in milliseconds. Key deadlines are absolute CLOCK_REALTIME milliseconds, so ANYTHING
// that will be compared against a deadline must come from here and never from now_ns() above --
// that one is CLOCK_MONOTONIC, so its "milliseconds" are milliseconds since boot and sit roughly
// five orders of magnitude below any real deadline. A monotonic value used as an expiry cut does
// not skew the answer, it disables expiry outright.
[[gnu::always_inline]] inline int64_t now_realtime_ms() {
    timespec ts;
    clock_gettime(CLOCK_REALTIME, &ts);
    return static_cast<int64_t>(ts.tv_sec) * 1000 + ts.tv_nsec / 1000000;
}

// Thread CPU time includes completion work that DEFER_TASKRUN performs while waiting on the
// ring. Timing just the surrounding work section would omit that CPU demand.
inline uint64_t thread_cpu_ns() {
    timespec ts;
    clock_gettime(CLOCK_THREAD_CPUTIME_ID, &ts);
    return static_cast<uint64_t>(ts.tv_sec) * 1000000000ull + static_cast<uint64_t>(ts.tv_nsec);
}

// Contract: a physical loop updates its own scheduling/TLS counters; roles interpret ops
// according to their work units. Socket totals use relaxed atomic load/store updates by that IO
// owner. Plain counters have concurrent diagnostic/controller readers but no race-free C++
// publication is established for them. Age stamping requires a nonzero configured rate; callers
// bypass it at zero. Methods allocate nothing and do not provide queue back-pressure
// themselves.
struct LoopSignals {
    // ---- work -------------------------------------------------------------------------------
    uint64_t ops = 0;  // units this loop completed: parsed+dispatched / executed / sent
    uint64_t iterations = 0;

    // ---- time (ns), time-weighted ------------------------------------------------------------
    uint64_t busy_ns = 0;  // IO tenure wall minus booked idle; EX productive-pass time
    uint64_t idle_ns = 0;  // IO park span (includes callbacks/publication); EX empty passes/waits
    uint64_t cpu_ns = 0;   // thread CPU time; the DEFER_TASKRUN-proof busyness reading

    // ---- pressure ----------------------------------------------------------------------------
    uint64_t depth_sum = 0;      // sum of sampled inbound depths, in ENTRIES
    uint64_t depth_samples = 0;  // divide to get a time-average rather than a spot reading
    uint64_t full_events = 0;    // outbound push refused: real backpressure, not a guess

    // Sampled queue/age signals. Timestamps come from the loop's already-paid pass clock;
    // queue-delay observation therefore adds no clock read or atomic to a per-operation path.
    // EWMAs use x256 fixed point so writers stay plain owner-local uint64 stores.
    uint64_t queue_delay_samples = 0;
    uint64_t queue_delay_ewma_x256 = 0;
    uint64_t oldest_age_us = 0;  // current role-specific gauge at the 100us signal beat
    uint64_t oldest_age_samples = 0;
    uint64_t oldest_age_ewma_x256 = 0;
    uint64_t oldest_age_min_us = 0;
    uint64_t oldest_age_max_us = 0;

    // ---- signalling --------------------------------------------------------------------------
    uint64_t wakes_sent = 0;
    uint64_t wakes_recv = 0;
    uint64_t spins = 0;

    // ---- accept / submission health ------------------------------------------------------------
    uint64_t accepts = 0;       // connections taken
    uint64_t accept_err = 0;    // accept completions with a negative result
    uint64_t accept_rearm = 0;  // multishot dropped and had to be re-armed
    uint64_t sqe_starved = 0;   // get_sqe returned null even after submit: ring saturation
    uint64_t notify_drop = 0;   // sender post refused; keep the claim and repost
    uint64_t acl_access_denied_cmd = 0;
    uint64_t acl_access_denied_key = 0;
    uint64_t acl_access_denied_channel = 0;
    uint64_t acl_access_denied_auth = 0;

    // Socket bytes have one IO-owner writer and concurrent INFO/cron readers. Updates use
    // relaxed load/store, preserving the single writer without a shared atomic RMW.
    std::atomic<uint64_t> /* TOMO_TOOL_BIND net_input_bytes */ net_input_bytes{0};
    std::atomic<uint64_t> /* TOMO_TOOL_BIND net_output_bytes */ net_output_bytes{0};

    // TLS counters are written only by the owning IO thread. With tls-port=0 the clean loop
    // specialization contains no increments or per-operation TLS tests.
    uint64_t plain_accepts = 0;
    uint64_t tls_accepts = 0;
    uint64_t tls_handshakes_started = 0;
    uint64_t tls_handshakes_completed = 0;
    uint64_t tls_handshakes_failed = 0;
    uint64_t tls_connections_freed = 0;
    uint64_t tls_want_read = 0;
    uint64_t tls_want_write = 0;
    uint64_t tls_ciphertext_input_bytes = 0;
    uint64_t tls_plaintext_input_bytes = 0;
    uint64_t tls_ciphertext_output_bytes = 0;
    uint64_t tls_plaintext_output_bytes = 0;
    uint64_t tls_zc_suppressed = 0;
    uint64_t tls_ktls_active = 0;    // current bidirectionally-offloaded connections
    uint64_t tls_ktls_fallback = 0;  // successful userspace-mode handshakes

    // --net-io epoll only. Both stay zero under io_uring, which is what makes them a usable
    // FIRED-MECHANISM proof: a run claiming to be on the epoll engine and reporting
    // epoll_events=0 was not on the epoll engine.
    uint64_t epoll_events = 0;  // readiness events returned by epoll_wait
    uint64_t epoll_recvs = 0;   // recv syscalls that returned bytes

    // Owner-cached producer sampling state. A zero rate takes the direct Channel push path: no
    // stamp writes, countdown work, arrays, or EWMA updates. cached_now_us is refreshed from
    // the pass cut, not by another clock read.
    uint64_t cached_now_us = 0;
    uint32_t age_sample_rate = 0;
    uint32_t age_sample_countdown = 0;

    void configure_age_sampling(uint32_t rate) {
        age_sample_rate = rate;
        age_sample_countdown = rate;
    }
    uint32_t next_age_stamp() {
        if (--age_sample_countdown != 0) return 0;
        age_sample_countdown = age_sample_rate;
        const uint32_t low = static_cast<uint32_t>(cached_now_us);
        return low;  // zero loses one sample per 2^32us; it is the sentinel
    }
    bool sampled_age(uint32_t enqueue_us_low, uint64_t& age_us) const {
        const uint32_t modular = static_cast<uint32_t>(cached_now_us) - enqueue_us_low;
        // The producer stamped after this consumer cached its current beat. This is the transient
        // empty-queue/future-stamp sentinel, not a task that waited for roughly UINT32_MAX us.
        if (static_cast<int32_t>(modular) < 0) return false;
        age_us = std::min<uint64_t>(modular, kLbAgeSaneMaxUs);
        return true;
    }
    bool observe_queue_delay(uint32_t enqueue_us_low, uint64_t& delay) {
        if (!sampled_age(enqueue_us_low, delay)) return false;
        observe_ewma(delay, queue_delay_samples, queue_delay_ewma_x256);
        return true;
    }
    void observe_oldest_age(uint64_t age_us) {
        age_us = std::min(age_us, kLbAgeSaneMaxUs);
        oldest_age_us = age_us;
        if (!oldest_age_samples) {
            oldest_age_min_us = oldest_age_max_us = age_us;
        } else {
            oldest_age_min_us = std::min(oldest_age_min_us, age_us);
            oldest_age_max_us = std::max(oldest_age_max_us, age_us);
        }
        observe_ewma(age_us, oldest_age_samples, oldest_age_ewma_x256);
    }
    void clear_oldest_age() { oldest_age_us = 0; }

    // Derived, computed on read so the hot path never divides.
    double avg_depth() const {
        return depth_samples ? static_cast<double>(depth_sum) / static_cast<double>(depth_samples)
                             : 0.0;
    }

private:
    static void observe_ewma(uint64_t sample, uint64_t& samples, uint64_t& ewma_x256) {
        const uint64_t scaled = sample << 8;
        if (!samples) {
            ewma_x256 = scaled;
        } else if (scaled >= ewma_x256) {
            ewma_x256 += (scaled - ewma_x256 + 7) / 8;
        } else {
            ewma_x256 -= (ewma_x256 - scaled + 7) / 8;
        }
        samples++;
    }
};

// Scoped timer for independent spans, including IO idle. Disjoint spans alone do not
// conserve a loop wall interval; IO busy accounting uses consecutive cuts in signalacct.h.
// Contract: The caller supplies a sink that outlives this scope and serializes updates to it.
// Construction/destruction sample CLOCK_MONOTONIC and add elapsed nanoseconds without
// publication, allocation or retries. This measures one span; IoTenure separately conserves
// whole-loop time.
class Span {
public:
    explicit Span(uint64_t& sink) : sink_(sink), t0_(now_ns()) {}
    ~Span() { sink_ += now_ns() - t0_; }
    uint64_t start_ns() const { return t0_; }
    Span(const Span&) = delete;
    Span& operator=(const Span&) = delete;

private:
    uint64_t& sink_;
    uint64_t t0_;
};

// ---------------------------------------------------------------------------------------------
// NotifyMask — the "where should I look" bitmap. One bit per producer.
//
// WITHOUT IT every consumer polls every producer's channel each iteration: at 128 threads that is
// 128 loads to discover that one of them has work. The mask turns that into one load plus a
// find-first-set per non-empty producer, so the cost tracks the number of ACTIVE producers rather
// than the number of possible ones.
//
// THE RMW TRAP, which is the whole reason this is not just a fetch_or: a blind atomic OR per push is
// a read-modify-write on a line shared with every other producer of that consumer. SPSC exists
// precisely to avoid per-push RMWs, so adding one here would give back what the queue design bought.
// Hence the read-first guard below: once a producer's bit is set it stays set until the consumer
// takes it, so a busy producer pays a shared-line READ and no write at all. Reads scale; writes
// serialise.
//
// THE ORDERING THAT MAKES IT CORRECT. The consumer must TAKE (exchange to zero) before draining,
// never after:
//
//      take bits -> drain those channels          correct
//      drain channels -> clear bits               LOSES a push that landed mid-drain
//
// In the wrong order a producer that pushes between the drain and the clear has its bit wiped, and
// its item sits in the queue until something unrelated happens to notify again. Same shape as the
// queued-flag ordering in the WB path.
// ---------------------------------------------------------------------------------------------
// ReadyMask — per-SENDER "which of my clients has completed work" bits, one bit per wb slot.
//
// Contract: executors set completion bits for IO-owned writeback slots. The IO takes bits
// before serving and maps slots through its own client table. Clear a slot after ROB quiescence
// and before reuse so an old completion cannot name a new client. There are no pointer payloads
// or queue-full failures in the mask. Duplicate sets coalesce and a completion after take sets
// the bit again; clearing after serving would lose a concurrent completion. set uses a
// read-first guard and seq_cst fetch_or for a new bit; a true result assigns the caller the
// park wake. take uses acquire exchange. The mask does not replace the ROB's completion
// publication or the caller's lifetime fences.
// Callers order Done publication before set with a seq_cst fence (see ex_loop.h's notify path).
// The read-first path performs no fence: without the caller's fence, a stale set bit can hide
// a completion that the IO has already missed while consuming the earlier notification.
class ReadyMask {
public:
    static constexpr uint32_t kSlots = 1024;
    static constexpr uint32_t kWords = kSlots / 64;

    bool set(uint32_t slot) {
        const uint64_t bit = 1ull << (slot & 63);
        auto& w = words_[(slot >> 6) % kWords];
        if (w.load(std::memory_order_relaxed) & bit) return false;
        return (w.fetch_or(bit, std::memory_order_seq_cst) & bit) == 0;
    }
    // Load-first: an exchange is a locked RMW that takes the line exclusive even when the word is
    // zero -- and these words are fetch_or'd by workers on OTHER CCDs, so an unconditional 16-word
    // exchange sweep per loop pass bounces contended lines for nothing. The relaxed load costs a
    // shared-line read; a zero word stays shared. A bit set between the
    // load and a skipped exchange is not lost: it is still set, and the next pass takes it.
    uint64_t take(uint32_t word) {
        if (!words_[word].load(std::memory_order_relaxed)) return 0;
        return words_[word].exchange(0, std::memory_order_acquire);
    }
    // Owner-only teardown/migration fence. Once the ROB is quiescent no executor can set this
    // slot again; clearing it before recycling the slot prevents a stale ready bit from naming the
    // next connection assigned the same index.
    void clear(uint32_t slot) {
        const uint64_t bit = 1ull << (slot & 63);
        words_[(slot >> 6) % kWords].fetch_and(~bit, std::memory_order_acq_rel);
    }
    bool any() const {
        for (uint32_t i = 0; i < kWords; i++)
            if (words_[i].load(std::memory_order_relaxed)) return true;
        return false;
    }

private:
    alignas(64) std::atomic<uint64_t> words_[kWords] = {};
};

// Contract: Producers flag their channel; the consumer takes each word before draining it and
// restores bits for unfinished drains. Producer ids must be below kBits and word indices below
// kWords. publish uses seq_cst fetch_or even for an already-set bit; take uses acquire
// exchange. set's read-first path does not itself publish a new queue item when the bit is
// already set. ThreadCtx's blocked-state seq_cst fence and work recheck complete the park
// protocol. Bits coalesce without allocation or capacity refusal.
class NotifyMask {
public:
    static constexpr uint32_t kBits = 128;
    static constexpr uint32_t kWords = kBits / 64;

    // Producer/repair side: read first, then seq_cst fetch_or if the bit is absent. Return true
    // for the caller that sets the bit; that RMW orders its bit store before the blocked_ load
    // in Channel::wake. If already set, this method performs no fence and owes no new edge
    // wake. Queue publication must still establish StoreLoad ordering, as publish does
    // unconditionally; a set bit by itself does not publish work added after an earlier
    // notification.
    bool set(uint32_t producer) {
        const uint64_t bit = 1ull << (producer & 63);
        auto& w = words_[(producer >> 6) & (kWords - 1)];
        if (w.load(std::memory_order_relaxed) & bit) return false;  // already flagged: no write
        return (w.fetch_or(bit, std::memory_order_seq_cst) & bit) == 0;
    }

    // Queue producers need StoreLoad ordering even when the bit was already
    // set. One unconditional RMW publishes the item and owns an edge wake;
    // a relaxed read-first shortcut needs a separate fence to be safe.
    bool publish(uint32_t producer) {
        const uint64_t bit = 1ull << (producer & 63);
        auto& w = words_[(producer >> 6) & (kWords - 1)];
        return (w.fetch_or(bit, std::memory_order_seq_cst) & bit) == 0;
    }

    // Consumer side. Takes and clears one word's worth of flags. Acquire pairs with the producer's
    // release so the queue contents behind the bit are visible.
    //
    // As in ReadyMask::take, load first to avoid taking a zero mask word exclusive. Every
    // consumer pass visits the mask words, so unconditional exchanges would acquire shared
    // producer-written lines even without work. A set between the load and skipped exchange
    // remains for the next pass. ThreadCtx::arm_blocked supplies a seq_cst fence before the
    // park path rechecks masks and queue depths, closing the missed-wake window.
    uint64_t take(uint32_t word) {
        if (!words_[word].load(std::memory_order_relaxed)) return 0;
        return words_[word].exchange(0, std::memory_order_acquire);
    }

    // Read-only optimization hint. Correctness consumers still use take(); a stale or missing bit
    // here may suppress optional filler work but can never strand the underlying queue.
    uint64_t peek(uint32_t word) const { return words_[word].load(std::memory_order_relaxed); }

    // Consumer side, for a bounded drain that stops before a channel is empty: put back the flags
    // it took for those channels so its own next pass visits them again. No wake is owed: the
    // consumer is the running thread, and the park path re-checks masks and depths anyway.
    void restore(uint32_t word, uint64_t bits) {
        words_[word].fetch_or(bits, std::memory_order_seq_cst);
    }

    bool any() const {
        for (uint32_t i = 0; i < kWords; i++)
            if (words_[i].load(std::memory_order_relaxed)) return true;
        return false;
    }

private:
    std::atomic<uint64_t> words_[kWords] = {};
};

// Contract: one producer pushes and one consumer pops/retires this directed channel. ExQueue
// owns inline slots and release/acquire frontiers; payload lifetimes remain the caller's duty.
// Publish the notify mask between enqueue and wake, with the required StoreLoad ordering. Full
// pushes return false and increment full_events; retain the item for retry/back-pressure.
// Retire after processing, and stop producers before relying on quiesced. Normal wake checks
// blocked_; wake_edge instead retries notification for persistence writers outside ThreadCtx's
// park.
template <typename T, uint32_t Cap>
class Channel {
public:
    // ---- producer side --------------------------------------------------------------------------
    // A refused push must not be dropped: losing an item can lose a reply and strand its
    // client. The consumer ring is supplied to wake rather than bound during channel
    // construction, when the peer ring might not exist. A null peer cannot receive a wake. Push
    // and wake are separate so the caller publishes the notify mask between them. If wake reads
    // blocked_ before that publication, a consumer can read an empty mask and park while the
    // producer reads unblocked; a lone request then has no later notification to rescue it.
    bool push(T v, LoopSignals& sig) {
        if (!q_.push(v)) {
            sig.full_events++;
            return false;
        }
        return true;
    }
    template <typename Prepare>
    bool push_prepared(T v, LoopSignals& sig, Prepare&& prepare) {
        if (!q_.push_prepared(v, static_cast<Prepare&&>(prepare))) {
            sig.full_events++;
            return false;
        }
        return true;
    }
    bool push_batch(const T* values, uint32_t count, LoopSignals& sig) {
        if (!q_.push_batch(values, count)) {
            sig.full_events++;
            return false;
        }
        return true;
    }
    template <typename Prepare>
    bool push_batch_prepared(const T* values, uint32_t count, LoopSignals& sig, Prepare&& prepare) {
        if (!q_.push_batch_prepared(values, count, static_cast<Prepare&&>(prepare))) {
            sig.full_events++;
            return false;
        }
        return true;
    }

    template <typename Extract>
    uint32_t newest_nonzero(Extract&& extract) const {
        return q_.newest_nonzero(static_cast<Extract&&>(extract));
    }

    // Call ONLY when the caller performed the mask's empty->flagged transition. That RMW is a full
    // fence, which is what makes this load safe: without it, store(blocked_)/load(mask) on the
    // consumer and store(mask)/load(blocked_) here are a Dekker pair, and x86 permits exactly the one
    // reordering (StoreLoad) that lets both sides miss each other.
    //
    // Only pay a syscall if the consumer is actually blocked. Under load it is spinning and will see
    // the item on its next pass, so the common case costs one relaxed atomic read.
    void wake(Ring& my_ring, LoopSignals& sig, Ring* peer_ring) {
        if (peer_ring && blocked_.load(std::memory_order_acquire)) {
            my_ring.msg_to(*peer_ring, ur_tag(UrKind::Wake, nullptr));
            sig.wakes_sent++;
        }
    }

    // Persistence writers do not arm these channels in ThreadCtx's park. Their
    // empty->flagged mask edge owns one unconditional wake, amortized per batch.
    // A failed SQE reservation must not consume that edge without a notification.
    void wake_edge(Ring& my_ring, LoopSignals& sig, Ring* peer_ring) {
        if (!peer_ring || peer_ring == &my_ring) return;
        while (!my_ring.msg_to(*peer_ring, ur_tag(UrKind::Wake, nullptr)))
            my_ring.submit_and_reap();
        sig.wakes_sent++;
    }

    // ---- consumer side --------------------------------------------------------------------------
    bool recv(T& out) { return q_.pop(out); }

    // Call AFTER the item has actually been processed — see exqueue.h. quiesced() is the predicate
    // every teardown, reshard and role conversion must test; depth() == 0 is not the same thing.
    void retire() { q_.retire(); }
    bool quiesced() const { return q_.quiesced(); }
    uint32_t depth() const { return q_.depth(); }
    uint32_t producer_free_slots() const { return q_.producer_free_slots(); }

    // Declare intent to block, so producers know a wake is worth its syscall. Set it, then re-check
    // the queue before actually blocking: without that re-check a producer that pushed just before
    // the flag was set would not have woken us, and we would sleep on a non-empty queue.
    void arm_blocked() { blocked_.store(true, std::memory_order_release); }
    void clear_blocked() { blocked_.store(false, std::memory_order_release); }

private:
    ExQueue<T, Cap> q_;
    std::atomic<bool> blocked_{false};
};

// Contract: one consumer owns the masked slot array; each producer owns its indexed frontier.
// MaskedSpscArray supplies slot publication and retirement. The caller serializes each
// endpoint, uses valid producer ids and changes capacity/masks while quiesced. A shared
// release-stored blocked flag covers all producer lanes; wake acquire-loads it after mask
// publication. Full pushes return false and increment full_events; reserved pushes require
// matching credits. This wrapper owns queue storage, not the pointed-to tasks' lifetimes.
template <typename T, uint32_t MaxProducers>
class MaskedChannelArray {
public:
    bool init_local(uint32_t producers, uint32_t slots_per_thread, const std::vector<uint32_t>& io,
                    const std::vector<uint32_t>& ex) {
        return q_.init_local(producers, slots_per_thread, io, ex);
    }
    template <uint32_t SlotsPerProducer>
    bool init_local_fused(uint32_t producers) {
        return q_.template init_local_fused<SlotsPerProducer>(producers);
    }
    bool remask_quiesced(const std::vector<uint32_t>& io, const std::vector<uint32_t>& ex) {
        return q_.remask_quiesced(io, ex);
    }
    bool grow_quiesced(uint32_t slots, const std::vector<uint32_t>& io,
                       const std::vector<uint32_t>& ex) {
        return q_.grow_quiesced(slots, io, ex);
    }

    bool push(uint32_t producer, T value, LoopSignals& sig) {
        if (!q_.push(producer, value)) {
            sig.full_events++;
            return false;
        }
        return true;
    }
    template <typename Prepare>
    bool push_prepared(uint32_t producer, T value, LoopSignals& sig, Prepare&& prepare) {
        if (!q_.push_prepared(producer, value, static_cast<Prepare&&>(prepare))) {
            sig.full_events++;
            return false;
        }
        return true;
    }
    bool push_batch(uint32_t producer, const T* values, uint32_t count, LoopSignals& sig) {
        if (!q_.push_batch(producer, values, count)) {
            sig.full_events++;
            return false;
        }
        return true;
    }
    bool reserve(uint32_t producer, uint32_t count) { return q_.reserve(producer, count); }
    void cancel_reservation(uint32_t producer, uint32_t count) {
        q_.cancel_reservation(producer, count);
    }
    void push_reserved(uint32_t producer, T value) { q_.push_reserved(producer, value); }
    template <typename Prepare>
    void push_reserved_prepared(uint32_t producer, T value, Prepare&& prepare) {
        q_.push_reserved_prepared(producer, value, static_cast<Prepare&&>(prepare));
    }
    template <typename Prepare>
    bool push_batch_prepared(uint32_t producer, const T* values, uint32_t count, LoopSignals& sig,
                             Prepare&& prepare) {
        if (!q_.push_batch_prepared(producer, values, count, static_cast<Prepare&&>(prepare))) {
            sig.full_events++;
            return false;
        }
        return true;
    }
    template <uint32_t SlotsPerProducer>
    bool push_fused_private(uint32_t producer, T value, LoopSignals& sig) {
        if (!q_.template push_fused_private<SlotsPerProducer>(producer, value)) {
            sig.full_events++;
            return false;
        }
        return true;
    }
    template <uint32_t SlotsPerProducer, typename Prepare>
    bool push_fused_private_prepared(uint32_t producer, T value, LoopSignals& sig,
                                     Prepare&& prepare) {
        if (!q_.template push_fused_private_prepared<SlotsPerProducer>(
                producer, value, static_cast<Prepare&&>(prepare))) {
            sig.full_events++;
            return false;
        }
        return true;
    }
    template <uint32_t SlotsPerProducer>
    bool push_fused_private_batch(uint32_t producer, const T* values, uint32_t count,
                                  LoopSignals& sig) {
        if (!q_.template push_fused_private_batch<SlotsPerProducer>(producer, values, count)) {
            sig.full_events++;
            return false;
        }
        return true;
    }
    template <uint32_t SlotsPerProducer, typename Prepare>
    bool push_fused_private_batch_prepared(uint32_t producer, const T* values, uint32_t count,
                                           LoopSignals& sig, Prepare&& prepare) {
        if (!q_.template push_fused_private_batch_prepared<SlotsPerProducer>(
                producer, values, count, static_cast<Prepare&&>(prepare))) {
            sig.full_events++;
            return false;
        }
        return true;
    }
    template <uint32_t SlotsPerProducer>
    uint32_t fused_private_free_slots(uint32_t producer) const {
        return q_.template fused_private_free_slots<SlotsPerProducer>(producer);
    }
    template <typename Extract>
    uint32_t newest_nonzero(uint32_t producer, Extract&& extract) const {
        return q_.newest_nonzero(producer, static_cast<Extract&&>(extract));
    }
    void wake(Ring& my_ring, LoopSignals& sig, Ring* peer_ring) {
        if (peer_ring && blocked_.load(std::memory_order_acquire)) {
            my_ring.msg_to(*peer_ring, ur_tag(UrKind::Wake, nullptr));
            sig.wakes_sent++;
        }
    }
    bool recv(uint32_t producer, T& out) { return q_.pop(producer, out); }
    template <uint32_t SlotsPerProducer>
    bool recv_fused_private(uint32_t producer, T& out) {
        return q_.template pop_fused_private_unretired<SlotsPerProducer>(producer, out);
    }
    bool pop_unretired(uint32_t producer, T& out) { return q_.pop_unretired(producer, out); }
    void retire(uint32_t producer) { q_.retire(producer); }
    void retire_n(uint32_t producer, uint32_t count) { q_.retire_n(producer, count); }
    bool quiesced(uint32_t producer) const { return q_.quiesced(producer); }
    bool all_quiesced() const { return q_.all_quiesced(); }
    uint32_t depth(uint32_t producer) const { return q_.depth(producer); }
    uint32_t sample_depth(uint32_t producer) { return q_.sample_depth(producer); }
    uint32_t producer_free_slots(uint32_t producer) const {
        return q_.producer_free_slots(producer);
    }
    void arm_blocked() { blocked_.store(true, std::memory_order_release); }
    void clear_blocked() { blocked_.store(false, std::memory_order_release); }
    uint32_t total_slots() const { return q_.total_slots(); }
    MaskedQueueDiagnostics diagnostics() const { return q_.diagnostics(); }

private:
    MaskedSpscArray<T, MaxProducers> q_;
    std::atomic<bool> blocked_{false};
};

}  // namespace tomo
