// Per-worker io_uring submission/completion engine and epoll-mode eventfd mailbox. IoLoop,
// ExLoopT and persistence code use Ring; each native ring has one submission issuer. Under epoll
// Ring creates no io_uring instance and supplies tagged cross-thread notifications instead.
//
// msg_to/for_each_cqe preserve the wake interface used by Channel::wake, ThreadCtx::wake_if_parked
// and the snapshot epoch barrier. The epoll implementation queues the tag under mail_mu_ before
// ringing eventfd, then presents it as a CQE to the receiving loop's on_cqe switch.
//
// THE TAG MUST SURVIVE, not just the wake. The snapshot epoch barrier posts UrKind::SnapshotStart
// carrying a SnapshotManager*, and the executor that receives it calls begin_snapshot() on that
// pointer. A doorbell that only said "wake up" would silently break BGSAVE under epoll -- the
// executors would never enter the barrier and the snapshot would hang. Hence a mailbox of tags, not
// a bare eventfd counter.
//
// Cost when NOT selected: one predicted-not-taken test on wake_fd_ per outer-loop step (submit,
// wait, drain) and per park-wake. Nothing per operation, nothing per event.
//
// Per-thread rings avoid a shared submission lock and completion bottleneck. SINGLE_ISSUER
// declares one submitting task; DEFER_TASKRUN defers task work until an event-requesting enter.
// Controllers must distinguish loop activity from measured thread CPU time (CPUTIME); deferred
// completion work prevents loop iteration counts from describing the cost of a completed request.
//
// USER DATA encodes what a completion was for. x86-64 user pointers are canonical 48-bit, so the
// tag stores the kind in bits 56..63 and the pointer in bits 0..47; bits 48..55 are unused.
#pragma once
#include <liburing.h>
#include <poll.h>
#include <sys/eventfd.h>
#include <unistd.h>
#include <cerrno>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <mutex>
#include <vector>

#include "../core/signal_doorbell.h"
#include "../core/exec1s.h"
#include "../base/park_net.h"

namespace tomo {

// BOOT-LATCHED, WRITTEN ONCE, before any thread that reads it exists (main.cc, before the pool is
// spawned). Not a knob that can be flipped: every Ring in the process must agree, because a uring
// ring cannot receive an eventfd doorbell and an eventfd doorbell cannot receive a msg_ring.
inline bool g_ring_epoll_mode = false;

enum class UrKind : uint8_t {
    Accept = 1,
    Recv = 2,
    Send = 3,
    Close = 4,
    Wake = 5,  // cross-ring notification via msg_ring
    UnixAccept = 6,
    SnapshotStart = 7,  // epoch barrier request; pointer is SnapshotManager
    Shutdown = 8,       // process signal doorbell; no pointer payload
    TlsAccept = 9,
    TlsRecv = 10,
    TlsSend = 11,
    AofIo = 12,       // persistence-engine request; pointer is writer-private request state
    SnapshotIo = 13,  // persistence-engine request; pointer is writer-private request state
    TlsReadPoll = 14,
    TlsWritePoll = 15,
    MigrateCancel = 16,  // source-ring cancellation request; original Recv CQE is the fence
    // 18/19 are fliplisten's accept/cancel tags.
    WakeSent = 20,      // issuer-side completion, distinct from a peer notification
    DatabaseWake = 17,  // physical-worker database grace/boundary eventfd
};

inline uint64_t ur_tag(UrKind k, void* p) {
    return (static_cast<uint64_t>(k) << 56) | (reinterpret_cast<uint64_t>(p) & ((1ULL << 48) - 1));
}
inline UrKind ur_kind(uint64_t tag) { return static_cast<UrKind>(tag >> 56); }
template <typename T>
inline T* ur_ptr(uint64_t tag) {
    return reinterpret_cast<T*>(tag & ((1ULL << 48) - 1));
}

// Owns the native ring or eventfd/mailbox and deferred CQEs; the process shutdown fd is borrowed.
// The issuer performs SQ/CQ work; peers post mailbox tags under mail_mu_, whose unlock/lock pairs
// publish payloads before consumption. Native ordering follows liburing's SQ/CQ protocol. Teardown
// requires issuer/peer quiescence before freeing objects named by tags. init reports failure;
// sqe retries one submission when full and can still return null, while callers retain retry work.
class Ring {
public:
    static constexpr unsigned /* TOMO_TOOL_BIND kWaitTimeoutMs */ kWaitTimeoutMs = 50;
    static_assert(kParkNetStretched || kParkNetMs == kWaitTimeoutMs, "park_net.h production net");
    Ring() = default;
    ~Ring() { shutdown(); }
    Ring(const Ring&) = delete;
    Ring& operator=(const Ring&) = delete;

    bool init(unsigned entries) {
        shutdown_fd_ = signal_doorbell_fd();
        if (g_ring_epoll_mode) {
            // EFD_NONBLOCK so a spurious drain of an already-empty counter cannot park the loop.
            wake_fd_ = ::eventfd(0, EFD_NONBLOCK | EFD_CLOEXEC);
            if (wake_fd_ < 0) {
                std::perror("eventfd");
                return false;
            }
            return true;
        }
        io_uring_params p{};
        // SINGLE_ISSUER: promises only one thread submits, letting the kernel drop internal locking.
        // DEFER_TASKRUN: completions are processed when we wait, not via IPI on the submitting cpu.
        // SUBMIT_ALL: keep submitting after an SQE fails validation instead of stopping at it. We
        // batch many SQEs per enter by design, so the default behaviour would silently strand every
        // later SQE in the batch -- including recv re-arms belonging to unrelated connections -- and
        // present as one connection's fault stalling several others.
        p.flags = IORING_SETUP_SINGLE_ISSUER | IORING_SETUP_DEFER_TASKRUN | IORING_SETUP_SUBMIT_ALL;
        // Fused EX rings skip idle enters. Peer MSG_RING and permanent polls
        // can enqueue deferred task work without an owned SQE: the kernel flag
        // is the service request for that incoming work.
        if (track_owned_) p.flags |= IORING_SETUP_TASKRUN_FLAG;
        int rc = io_uring_queue_init_params(entries, &r_, &p);
        if (rc < 0) {
            // Retry without setup flags for kernels that reject them. If this also fails, init
            // returns false; a successful retry records that deferred completion mode is absent.
            std::memset(&p, 0, sizeof(p));
            rc = io_uring_queue_init_params(entries, &r_, &p);
            if (rc < 0) {
                std::fprintf(stderr, "io_uring init failed: %d\n", rc);
                return false;
            }
            deferred_ = false;
        }
        inited_ = true;
        if (shutdown_fd_ >= 0) {
            io_uring_sqe* shutdown = io_uring_get_sqe(&r_);
            if (!shutdown) return false;
            io_uring_prep_poll_add(shutdown, shutdown_fd_, POLLIN);
            shutdown->user_data = ur_tag(UrKind::Shutdown, nullptr);
            if (io_uring_submit(&r_) < 1) return false;
        }
        return true;
    }

    // POST-JOIN FENCE. io_uring CQEs carry raw Client*/buffer pointers and the epoll fallback's
    // mailbox carries the same tagged pointers. Queue teardown must therefore precede destruction
    // of any connection those entries can name. Normal shutdown calls this after every ring
    // issuer has joined on normal shutdown; idempotence also supports destructor cleanup and
    // partially initialized boot failures.
    void shutdown() {
        if (inited_) {
            io_uring_queue_exit(&r_);
            inited_ = false;
        }
        if (wake_fd_ >= 0) {
            ::close(wake_fd_);
            wake_fd_ = -1;
        }
        shutdown_fd_ = -1;  // borrowed process doorbell; Ring never closes it
        deferred_cqes_.clear();
        {
            std::lock_guard<std::mutex> lock(mail_mu_);
            mail_.clear();
        }
        raw_callback_active_ = false;
        raw_callback_taken_ = false;
        raw_callback_index_ = 0;
        send_pending_ = false;
    }

    // Registration is task-local. The guard ends on the issuer, before the
    // post-join teardown can call liburing from the coordinator thread. This guard borrows Ring;
    // it must outlive the guard. Registration failure leaves the guard empty; unregister failure
    // aborts. It adds no cross-thread synchronization.
    class RegisteredFd {
        Ring* ring_ = nullptr;

    public:
        explicit RegisteredFd(Ring* ring) {
            if (ring && ring->inited_ && io_uring_register_ring_fd(&ring->r_) == 1) ring_ = ring;
        }
        ~RegisteredFd() {
            if (ring_ && io_uring_unregister_ring_fd(&ring_->r_) != 1) std::abort();
        }
        RegisteredFd(const RegisteredFd&) = delete;
        RegisteredFd& operator=(const RegisteredFd&) = delete;
    };

    // Only fused executor rings opt in. Permanent shutdown/database polls do
    // not represent outstanding data work; IO continues entering every rotation.
    void track_owned_completions() { track_owned_ = true; }
    void note_owned_completion() {
        if (track_owned_) ++owned_completions_;
    }
    unsigned owned_completions() const { return owned_completions_; }
    bool completion_service_needed() const {
        return inited_ &&
               (sq_ready() || owned_completions_ ||
                (IO_URING_READ_ONCE(*r_.sq.kflags) & (IORING_SQ_TASKRUN | IORING_SQ_CQ_OVERFLOW)));
    }

    bool shutdown_complete() const { return !inited_ && wake_fd_ < 0; }

    // enter counts are submit/get-events entries; waits are separate because liburing
    // may satisfy a wait from an already populated CQ without entering the kernel.
    void bind_entry_counters(uint32_t tid, bool executor) {
        counter_slot_ = 2 * tid + executor;
        exec1s_ring_counters[counter_slot_] = {};
    }
    io_uring* raw() { return &r_; }
    bool deferred() const { return deferred_; }

    // >= 0 exactly in epoll mode. The io loop registers it in its epoll set; that is what turns a
    // peer's msg_to() into a return from epoll_wait.
    int wake_fd() const { return wake_fd_; }
    int shutdown_fd() const { return shutdown_fd_; }

    // A request may fail its save and leave the server live. Re-arm from the owning
    // loop's request completion; a terminal completion needs no new subscription.
    // A one-shot poll is already complete at terminal wake, so queue teardown does
    // not leave a multishot subscription retaining ring/socket references at exit.
    __attribute__((noinline)) void rearm_shutdown_poll() {
        if (!inited_ || shutdown_fd_ < 0) return;
        if (io_uring_sqe* poll = sqe()) {
            io_uring_prep_poll_add(poll, shutdown_fd_, POLLIN);
            poll->user_data = ur_tag(UrKind::Shutdown, nullptr);
        }
    }

    // Drain the doorbell counter. Level-triggered registration plus this read is deliberate: an
    // edge-triggered eventfd that we forgot to read would go quiet forever, and the price of
    // getting it wrong is a permanently parked io thread.
    void drain_wake_fd() {
        uint64_t counter = 0;
        while (::read(wake_fd_, &counter, sizeof(counter)) ==
               static_cast<ssize_t>(sizeof(counter)));
    }

    // Get an SQE on the issuer, submitting once to make space if the ring is full. The second
    // get can still fail, so callers must handle nullptr. Epoll mode has no SQ and returns null;
    // IoLoop selects network submission by engine, and persistence selects its syscall backend.
    io_uring_sqe* sqe() {
        if (__builtin_expect(wake_fd_ >= 0, false)) return nullptr;
        io_uring_sqe* s = io_uring_get_sqe(&r_);
        if (!s) {
            submit();
            // A forced-full flush is a real boundary for the pipeline-1 SEND classifier. Keep
            // this reset on the rare slow arm instead of charging every explicit submit.
            send_pending_ = false;
            s = io_uring_get_sqe(&r_);
        }
        return s;
    }

    // A linked pair must not be split by sqe()'s full-ring flush between its two entries.
    void ensure_sq_space(unsigned needed) {
        if (__builtin_expect(wake_fd_ >= 0, false)) return;
        if (io_uring_sq_space_left(&r_) < needed) {
            submit();
            send_pending_ = false;
        }
    }

    int submit() {
        if (__builtin_expect(wake_fd_ >= 0, false)) return 0;
        if (counter_slot_ < 256 && io_uring_sq_ready(&r_))
            ++exec1s_ring_counters[counter_slot_].enters;
        return io_uring_submit(&r_);
    }

    // Submit and request pending completion work. DEFER_TASKRUN needs an event-requesting enter:
    // a plain submit followed by CQ inspection can leave completed work deferred until the loop
    // next parks. submit_and_get_events lets a busy loop reap it without waiting for idleness.
    template <bool ClearSendClassification = false>
    int submit_and_reap() {
        if constexpr (ClearSendClassification) send_pending_ = false;
        if (__builtin_expect(wake_fd_ >= 0, false)) return 0;
        if (counter_slot_ < 256) ++exec1s_ring_counters[counter_slot_].enters;
        return io_uring_submit_and_get_events(&r_);
    }

    // Submit whatever is queued and block until a completion arrives OR the timeout expires.
    // The timeout is not decoration: without it a thread parked here never re-reads its stop flag,
    // so shutdown hangs and the process has to be SIGKILLed. It also bounds the damage from any
    // missed wake — the loop recovers on the next tick instead of sleeping forever.
    // The default is the missed-wake safety net (park_net.h); the diagnostic build stretches it.
    template <bool ClearSendClassification = false>
    int submit_and_wait(unsigned want = 1, unsigned timeout_ms = kParkNetMs, int database_fd = -1) {
        if constexpr (ClearSendClassification) send_pending_ = false;
        if (__builtin_expect(wake_fd_ >= 0, false)) {
            // The ex loop's park. Same contract as the uring path: block until a peer rings the
            // doorbell OR the timeout expires, so the stop flag is re-read on every tick.
            pollfd waits[3] = {
                {wake_fd_, POLLIN, 0}, {shutdown_fd_, POLLIN, 0}, {database_fd, POLLIN, 0}};
            const nfds_t count = database_fd >= 0 ? 3 : (shutdown_fd_ >= 0 ? 2 : 1);
            const int n = ::poll(waits, count, static_cast<int>(timeout_ms));
            if (n > 0 && (waits[0].revents & POLLIN)) drain_wake_fd();
            return n < 0 ? 0 : n;
        }
        if (counter_slot_ < 256) ++exec1s_ring_counters[counter_slot_].waits;
        __kernel_timespec ts{};
        ts.tv_sec = timeout_ms / 1000;
        ts.tv_nsec = static_cast<long long>(timeout_ms % 1000) * 1000000LL;
        // cqe_ptr is written through UNCONDITIONALLY by liburing — passing nullptr segfaults inside
        // the library rather than returning an error. The value is then ignored here on purpose:
        // completions are drained by for_each_cqe, which advances the ring once for the whole batch.
        io_uring_cqe* cqe = nullptr;
        return io_uring_submit_and_wait_timeout(&r_, &cqe, want, &ts, nullptr);
    }

    // Batch-drain completions. `fn(cqe)` per completion; the ring advances once at the end, which
    // is a single store rather than one per completion.
    template <typename Fn>
    unsigned for_each_cqe(Fn&& fn) {
        unsigned n = 0;
        if (__builtin_expect(wake_fd_ >= 0, false)) return for_each_mail(fn);
        if (!deferred_cqes_.empty()) {
            std::vector<io_uring_cqe> deferred;
            deferred.swap(deferred_cqes_);
            for (io_uring_cqe& cqe : deferred) {
                fn(&cqe);
                n++;
            }
        }
        io_uring_cqe* cqe;
        unsigned head, raw = 0;
        raw_callback_active_ = true;
        raw_callback_taken_ = false;
        io_uring_for_each_cqe(&r_, head, cqe) {
            raw++;
            raw_callback_index_ = raw;
            account_owned_completion(cqe);
            fn(cqe);
            if (raw_callback_taken_) break;
        }
        raw_callback_active_ = false;
        if (raw && !raw_callback_taken_) io_uring_cq_advance(&r_, raw);
        raw_callback_taken_ = false;
        raw_callback_index_ = 0;
        n += raw;
        return n;
    }

    // A persistence command can deliberately occupy its IO owner (SAVE and the AOF rewrite mark).
    // It still has to reap its own CQEs under DEFER_TASKRUN, but must not consume unrelated recv/send
    // completions whose callbacks live in IoLoop. The filter handles matching CQEs and retains the
    // rest for the loop's next ordinary for_each_cqe pass.
    template <typename Fn>
    unsigned for_each_cqe_filtered(Fn&& fn) {
        // Nothing to filter in epoll mode: persistence is forced onto the syscall engine there, so
        // no AofIo/SnapshotIo completion can exist. Returning zero is not a stub -- the callers
        // (SAVE, the AOF rewrite mark) all loop on their own pending counters, which stay zero.
        if (__builtin_expect(wake_fd_ >= 0, false)) return 0;
        // A blocking SAVE can enter here from inside the recv CQE callback that invoked it. Retire
        // that already-processed prefix before looking at the CQ and tell the outer batch to stop;
        // otherwise the current recv CQE is copied into deferred_cqes_ and delivered a second time.
        if (raw_callback_active_ && !raw_callback_taken_) {
            io_uring_cq_advance(&r_, raw_callback_index_);
            raw_callback_taken_ = true;
        }
        unsigned consumed = 0;
        std::vector<io_uring_cqe> keep;
        keep.reserve(deferred_cqes_.size());
        for (io_uring_cqe& cqe : deferred_cqes_) {
            if (fn(&cqe))
                consumed++;
            else
                keep.push_back(cqe);
        }
        deferred_cqes_.swap(keep);

        io_uring_cqe* cqe;
        unsigned head, raw = 0;
        io_uring_for_each_cqe(&r_, head, cqe) {
            account_owned_completion(cqe);
            if (fn(cqe))
                consumed++;
            else
                deferred_cqes_.push_back(*cqe);
            raw++;
        }
        if (raw) io_uring_cq_advance(&r_, raw);
        return consumed;
    }

    // SEND-bearing batches are latency carrying: a request/response client cannot create the next
    // arrival until this SQE reaches the kernel. Track that scheduling classification separately
    // from liburing's own count of queued SQEs.
    template <bool Classify>
    void note_send_pending() {
        if constexpr (Classify) send_pending_ = true;
    }
    bool send_pending() const { return send_pending_; }

    // Schedule boundaries occasionally need to know whether a later stage prepared real SQEs.
    // Query liburing's tail/head state at those boundaries, without a per-SQE shadow counter.
    unsigned sq_ready() const {
        return __builtin_expect(wake_fd_ >= 0, false) ? 0 : io_uring_sq_ready(&r_);
    }

    // Post a completion into ANOTHER thread's ring. This is how an executor wakes a parked io
    // thread that has replies to retire (ThreadCtx::wake_if_parked), and how any producer pokes a
    // parked consumer (Channel::wake), without a shared queue or an eventfd round trip.
    bool msg_to(Ring& target, uint64_t tag) {
        if (__builtin_expect(target.wake_fd_ >= 0, false)) return target.post_mail(tag);
        io_uring_sqe* s = sqe();
        if (!s) return false;
        io_uring_prep_msg_ring(s, target.r_.ring_fd, 0, tag, 0);
        s->user_data = ur_tag(track_owned_ ? UrKind::WakeSent : UrKind::Wake, nullptr);
        note_owned_completion();
        return true;
    }

private:
    void account_owned_completion(io_uring_cqe* cqe) {
        const auto kind = ur_kind(cqe->user_data);
        if (track_owned_ &&
            (kind == UrKind::WakeSent || kind == UrKind::AofIo || kind == UrKind::SnapshotIo)) {
            if (!owned_completions_) std::abort();
            --owned_completions_;
            if (kind == UrKind::WakeSent) cqe->user_data = ur_tag(UrKind::Wake, nullptr);
        }
    }
    // The epoll-mode doorbell. PAYLOAD FIRST, THEN THE BELL -- the same push-then-flag order the
    // channel mesh uses, and for the same reason: a consumer woken by the bell must be able to see
    // the tag that triggered the wake. mail_mu_ unlock/lock publishes the queued payload to
    // for_each_mail; producers may contend with each other or with the receiving drain. A failed
    // eventfd write returns false after enqueueing, leaving the tag for a later drain.
    bool post_mail(uint64_t tag) {
        {
            std::lock_guard<std::mutex> lock(mail_mu_);
            mail_.push_back(tag);
        }
        const uint64_t one = 1;
        return ::write(wake_fd_, &one, sizeof(one)) == static_cast<ssize_t>(sizeof(one));
    }

    // Hand the mailbox back shaped as CQEs so both loops' on_cqe switches are engine-blind. res and
    // flags are zero, which is what a msg_ring completion carries anyway.
    template <typename Fn>
    unsigned for_each_mail(Fn&& fn) {
        std::vector<uint64_t> taken;
        {
            std::lock_guard<std::mutex> lock(mail_mu_);
            if (mail_.empty()) return 0;
            taken.swap(mail_);
        }
        for (uint64_t tag : taken) {
            io_uring_cqe cqe{};
            cqe.user_data = tag;
            fn(&cqe);
        }
        return static_cast<unsigned>(taken.size());
    }

    io_uring r_{};
    bool inited_ = false;
    bool deferred_ = true;
    bool send_pending_ = false;
    bool track_owned_ = false;  // packed with the ring-state flags
    uint32_t owned_completions_ = 0;
    std::vector<io_uring_cqe> deferred_cqes_;
    bool raw_callback_active_ = false;
    bool raw_callback_taken_ = false;
    uint16_t counter_slot_ = 256;  // two-byte alignment hole
    unsigned raw_callback_index_ = 0;
    // Epoll-mode doorbell state. -1 in uring mode, which is the single test every method above
    // branches on; the mailbox remains empty there, though its vector and mutex are constructed.
    int wake_fd_ = -1;
    int shutdown_fd_ = -1;  // borrowed from main; never drained or closed by a Ring
    std::mutex mail_mu_;
    std::vector<uint64_t> mail_;
};

}  // namespace tomo
