// uring.h — one io_uring per thread. This is the only network backend for now; epoll comes later.
//
// RING PER THREAD, NEVER SHARED. A shared ring needs locking around the submission queue and
// serialises every thread through one completion path. Per-thread rings with SINGLE_ISSUER let the
// kernel skip its own internal locking, and it is the configuration where io_uring actually wins:
// naively swapped in, io_uring is roughly net-neutral, and the large gains come from exploiting it
// deliberately (ring per thread + DEFER_TASKRUN).
//
// DEFER_TASKRUN is on, with one consequence recorded here because it already caused a wrong reading
// once: it defers completion processing to the point where the thread waits on the ring, which means
// the thread's CPU time no longer reflects how busy it is. Any controller that reads thread busyness
// to make decisions will be BLIND under this flag and must sample CPUTIME explicitly instead of
// inferring it from loop behaviour.
//
// USER DATA encodes what a completion was for. x86-64 user pointers are canonical 48-bit, so the
// top 16 bits carry the kind — same trick as the FlatStore slot.
#pragma once
#include <liburing.h>
#include <cstdint>
#include <cstdio>
#include <cstring>

namespace tomo {

enum class UrKind : uint8_t {
    Accept = 1,
    Recv   = 2,
    Send   = 3,
    Close  = 4,
    Wake   = 5,   // cross-ring notification via msg_ring
};

inline uint64_t ur_tag(UrKind k, void* p) {
    return (static_cast<uint64_t>(k) << 56) | (reinterpret_cast<uint64_t>(p) & ((1ULL << 48) - 1));
}
inline UrKind ur_kind(uint64_t tag) { return static_cast<UrKind>(tag >> 56); }
template <typename T>
inline T* ur_ptr(uint64_t tag) { return reinterpret_cast<T*>(tag & ((1ULL << 48) - 1)); }

class Ring {
public:
    Ring() = default;
    ~Ring() { if (inited_) io_uring_queue_exit(&r_); }
    Ring(const Ring&) = delete;
    Ring& operator=(const Ring&) = delete;

    bool init(unsigned entries) {
        io_uring_params p{};
        // SINGLE_ISSUER: promises only one thread submits, letting the kernel drop internal locking.
        // DEFER_TASKRUN: completions are processed when we wait, not via IPI on the submitting cpu.
        p.flags = IORING_SETUP_SINGLE_ISSUER | IORING_SETUP_DEFER_TASKRUN;
        int rc = io_uring_queue_init_params(entries, &r_, &p);
        if (rc < 0) {
            // Fall back rather than refuse to boot: an older kernel should still run, just slower.
            // The fork had the opposite failure — a build without uring support hung on the first
            // connection instead of degrading, which is far worse than being slow.
            std::memset(&p, 0, sizeof(p));
            rc = io_uring_queue_init_params(entries, &r_, &p);
            if (rc < 0) { std::fprintf(stderr, "io_uring init failed: %d\n", rc); return false; }
            deferred_ = false;
        }
        inited_ = true;
        return true;
    }

    io_uring* raw() { return &r_; }
    bool deferred() const { return deferred_; }

    // Never returns nullptr: a full SQ ring is flushed rather than reported, because every caller
    // would otherwise have to invent the same retry and one of them would get it wrong.
    io_uring_sqe* sqe() {
        io_uring_sqe* s = io_uring_get_sqe(&r_);
        if (!s) { submit(); s = io_uring_get_sqe(&r_); }
        return s;
    }

    int submit() { pending_ = 0; return io_uring_submit(&r_); }

    // Submit whatever is queued and block until at least one completion is available.
    int submit_and_wait(unsigned want = 1) {
        pending_ = 0;
        return io_uring_submit_and_wait(&r_, want);
    }

    // Batch-drain completions. `fn(cqe)` per completion; the ring advances once at the end, which
    // is a single store rather than one per completion.
    template <typename Fn>
    unsigned for_each_cqe(Fn&& fn) {
        io_uring_cqe* cqe;
        unsigned head, n = 0;
        io_uring_for_each_cqe(&r_, head, cqe) { fn(cqe); n++; }
        if (n) io_uring_cq_advance(&r_, n);
        return n;
    }

    void note_pending() { pending_++; }
    unsigned pending() const { return pending_; }

    // Post a completion into ANOTHER thread's ring. This is how an IO thread tells a WB thread that
    // a client has replies to send, without a shared queue or an eventfd round trip.
    bool msg_to(Ring& target, uint64_t tag) {
        io_uring_sqe* s = sqe();
        if (!s) return false;
        io_uring_prep_msg_ring(s, target.r_.ring_fd, 0, tag, 0);
        s->user_data = ur_tag(UrKind::Wake, nullptr);
        note_pending();
        return true;
    }

private:
    io_uring r_{};
    bool     inited_   = false;
    bool     deferred_ = true;
    unsigned pending_  = 0;
};

}  // namespace tomo
