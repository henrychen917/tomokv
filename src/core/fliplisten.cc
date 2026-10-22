// Listener ownership is independent of an IO tenure. Everything in this file is
// reached through an existing cold accept branch or a live FLIP control tail.
#include "io_loop.h"
#include <sys/resource.h>

namespace tomo {
namespace {
constexpr UrKind kListenerAccept = static_cast<UrKind>(18);
constexpr UrKind kListenerCancel = static_cast<UrKind>(19);
constexpr uint32_t kListeners = 3 * kMaxThreads;
constexpr UrKind kinds[] = {UrKind::Accept, UrKind::TlsAccept, UrKind::UnixAccept};

}

struct FlipListenerState {
    struct Pending { int next; UrKind kind; };
    struct Listener {
        int fd = -1;
        uint32_t home = 0, owner = 0, target = 0;
        UrKind kind = UrKind::Accept;
        const TlsContext* tls = nullptr;
        bool armed = false, cancel_pending = false, cancel_submitted = false;
    };
    struct Local {
        int head = -1, tail = -1;
        bool registered[kListeners] = {};
        bool files_registered = false;
        uint64_t quiesce_epoch = 0;
        std::atomic<uint64_t> resumed{0};
    };
    std::array<Listener, kListeners> listeners;
    std::array<Local, kMaxThreads> local;
    std::unique_ptr<Pending[]> pending;
    size_t descriptor_limit = 0;
    std::atomic<uint64_t> admission{0};

    static IoLoop* io(Server& srv, uint32_t tid) {
        return static_cast<IoLoop*>(srv.thread(tid).io_role_context_);
    }
    static int& native(IoLoop& io, UrKind kind) {
        return kind == UrKind::UnixAccept ? io.unix_listen_fd_ :
               kind == UrKind::TlsAccept ? io.tls_listen_fd_ : io.listen_fd_;
    }
    bool register_on(IoLoop& io, unsigned index) {
        auto& own = local[io.self_->id()];
        if (own.registered[index]) return true;
        auto& listener = listeners[index];
        if (io.epoll_) {
            const auto tag = listener.home == io.self_->id()
                ? ur_tag(listener.kind, nullptr) : ur_tag(kListenerAccept, &listener);
            if (!set_nonblocking(listener.fd) ||
                !io.ep_.add(listener.fd, EPOLLIN, tag)) return false;
        } else {
            // Reserve the real kernel file reference, on the destination issuer,
            // before its prepare ACK. No accept is submitted until admission.
            if (!own.files_registered) {
                int empty[kListeners];
                std::fill_n(empty, kListeners, -1);
                if (io_uring_register_files(io.ring_.raw(), empty, kListeners) < 0)
                    return false;
                own.files_registered = true;
            }
            if (io_uring_register_files_update(io.ring_.raw(), index, &listener.fd, 1) != 1)
                return false;
        }
        own.registered[index] = true;
        return true;
    }
    void unregister_epoll(IoLoop& io) {
        if (!io.epoll_) return;
        auto& own = local[io.self_->id()];
        for (unsigned i = 0; i < kListeners; ++i) {
            const auto& listener = listeners[i];
            if (own.registered[i] && listener.owner != io.self_->id()) {
                if (!io.ep_.del(listener.fd)) std::abort();
                own.registered[i] = false;
            }
        }
    }
    bool arm(IoLoop& io, Listener& listener) {
        if (listener.armed) return true;
        auto* sqe = io.ring_.sqe();
        if (!sqe) return false;
        io_uring_prep_multishot_accept(sqe, listener.fd, nullptr, nullptr, 0);
        sqe->user_data = ur_tag(kListenerAccept, &listener);
        listener.armed = true;
        return true;
    }
    void admit(IoLoop& io, int fd, UrKind kind) {
        if (io.epoll_) {
            if (io.srv_->read_local_enabled()) io.admit_retained_fd<true, true>(fd, kind);
            else io.admit_retained_fd<true, false>(fd, kind);
        } else {
            if (io.srv_->read_local_enabled()) io.admit_retained_fd<false, true>(fd, kind);
            else io.admit_retained_fd<false, false>(fd, kind);
        }
    }
};

bool fliplisten_reserve(Server& srv, std::string& error) {
    if (srv.flip_listeners_) return true;
    try {
        rlimit limit{};
        if (getrlimit(RLIMIT_NOFILE, &limit) || limit.rlim_cur > INT_MAX) {
            error = "ERR FLIP cannot bound retained descriptors";
            return false;
        }
        auto state = std::make_shared<FlipListenerState>();
        state->descriptor_limit = limit.rlim_cur;
        // One slot per possible process fd, shared by all owners. No allocation
        // or capacity failure can occur after an accept has returned a descriptor.
        // Entries are initialized only when used, before publishing their list link.
        state->pending.reset(new FlipListenerState::Pending[limit.rlim_cur]);
        for (uint32_t tid = 0; tid < srv.nthreads(); ++tid) {
            auto* io = FlipListenerState::io(srv, tid);
            for (unsigned k = 0; k < 3; ++k) {
                auto& listener = state->listeners[3 * tid + k];
                listener.home = listener.owner = listener.target = tid;
                listener.kind = kinds[k];
                if (!io) continue; // serverless role/quota fixtures have no network loop
                listener.fd = FlipListenerState::native(*io, kinds[k]);
                listener.tls = io->tls_context_;
                if (listener.fd >= 0 && io->epoll_)
                    state->local[tid].registered[3 * tid + k] = true;
            }
        }
        srv.flip_listeners_ = std::move(state);
        return true;
    } catch (const std::bad_alloc&) {
        error = "ERR FLIP could not reserve listener and descriptor state";
        return false;
    }
}

void IoLoop::fliplisten_retain(int fd, UrKind kind) {
    auto& state = *srv_->flip_listeners_;
    // Planning has not frozen any Client set. Invalid/no-op requests may leave
    // Planning directly, so they must not strand an accepted fd in a drain list.
    if (srv_->flip_stage() <= FlipStage::Planning ||
        state.admission.load(std::memory_order_acquire) == srv_->flip_epoch()) {
        state.admit(*this, fd, kind);
        return;
    }
    if (fd < 0 || static_cast<size_t>(fd) >= state.descriptor_limit) std::abort();
    auto& own = state.local[self_->id()];
    state.pending[fd] = {-1, kind};
    if (own.tail < 0) own.head = fd;
    else state.pending[own.tail].next = fd;
    own.tail = fd;
    fliplisten_quiesce();
}

void IoLoop::fliplisten_stale(io_uring_cqe* cqe, UrKind kind) {
    // Includes successful old-generation completions produced before cancel
    // wins. The terminal CQE and the cancel CQE are independent fences.
    if (cqe->res >= 0) fliplisten_retain(cqe->res, kind);
    if (!(cqe->flags & IORING_CQE_F_MORE)) accept_armed_ref(kind) = false;
}

void IoLoop::fliplisten_quiesce() {
    if (!srv_->flip_listeners_) return;
    auto& state = *srv_->flip_listeners_;
    auto& own = state.local[self_->id()];
    // Borrowed-listener SQ starvation also sets accept_quiescing_. It is not
    // evidence that this epoch cancelled anything: initialize the cancellation
    // generation and per-listener fences once per FLIP, independently of it.
    if (own.quiesce_epoch != srv_->flip_epoch()) {
        own.quiesce_epoch = srv_->flip_epoch();
        accept_quiescing_ = true;
        accept_cancel_generation_ = accept_generation_++;
        accept_pending_ = tls_accept_pending_ = unix_accept_pending_ = false;
        for (auto& listener : state.listeners)
            if (listener.owner == self_->id()) listener.cancel_submitted = false;
    }
    if (epoll_) return;
    for (auto& listener : state.listeners) {
        if (listener.fd < 0 || listener.owner != self_->id()) continue;
        const bool native = listener.home == self_->id();
        const bool armed = native ? accept_armed_ref(listener.kind) : listener.armed;
        if (!armed || listener.cancel_submitted) continue;
        auto* sqe = ring_.sqe();
        if (!sqe) { self_->sig().sqe_starved++; continue; }
        const uint64_t tag = native
            ? ur_tag(listener.kind, reinterpret_cast<void*>(accept_cancel_generation_))
            : ur_tag(kListenerAccept, &listener);
        io_uring_prep_cancel64(sqe, tag, 0);
        sqe->user_data = ur_tag(kListenerCancel, &listener);
        listener.cancel_pending = listener.cancel_submitted = true;
    }
}

bool IoLoop::fliplisten_quiet() const {
    if (epoll_) return true;
    if (accept_armed_ || tls_accept_armed_ || unix_accept_armed_) return false;
    if (!srv_->flip_listeners_) return true;
    for (const auto& listener : srv_->flip_listeners_->listeners)
        if (listener.fd >= 0 && listener.owner == self_->id() &&
            (listener.armed || listener.cancel_pending)) return false;
    return true;
}

void IoLoop::fliplisten_cqe(io_uring_cqe* cqe) {
    const auto kind = ur_kind(cqe->user_data);
    if (kind != kListenerAccept && kind != kListenerCancel) return;
    auto& listener = *ur_ptr<FlipListenerState::Listener>(cqe->user_data);
    if (listener.owner != self_->id()) std::abort();
    if (kind == kListenerCancel) { listener.cancel_pending = false; return; }
    if (cqe->res >= 0) {
        if (accepts_paused()) fliplisten_retain(cqe->res, listener.kind);
        else srv_->flip_listeners_->admit(*this, cqe->res, listener.kind);
    } else if (cqe->res != -ECANCELED) self_->sig().accept_err++;
    if (!(cqe->flags & IORING_CQE_F_MORE)) {
        listener.armed = false;
        if (!accept_quiescing_ && !srv_->flip_listeners_->arm(*this, listener)) {
            // Reuse the existing SQ-starvation retry branch. No new loop probe.
            accept_quiescing_ = accept_pending_ = true;
        }
    }
}

uint32_t IoLoop::fliplisten_epoll(uint64_t tag) {
    if (ur_kind(tag) != kListenerAccept || accepts_paused()) return 0;
    auto& listener = *ur_ptr<FlipListenerState::Listener>(tag);
    if (listener.owner != self_->id()) return 0; // reversible destination registration
    uint32_t count = 0;
    for (;;) {
        int fd = accept4(listener.fd, nullptr, nullptr, SOCK_NONBLOCK | SOCK_CLOEXEC);
        if (fd < 0) {
            if (errno == EINTR) continue;
            if (errno != EAGAIN && errno != EWOULDBLOCK) self_->sig().accept_err++;
            return count;
        }
        ++count;
        // The pause can open while epoll drains a listener.
        if (accepts_paused()) { fliplisten_retain(fd, listener.kind); return count; }
        srv_->flip_listeners_->admit(*this, fd, listener.kind);
    }
}

bool IoLoop::fliplisten_plan() {
    if (!srv_->flip_listeners_) return true; // serverless role models
    auto& state = *srv_->flip_listeners_;
    // All old IOs acknowledged cancel + drain. Create at most one TCP/TLS
    // listener per physical thread, reusing its existing listener on later FLIPs.
    for (uint32_t tid = 0; tid < srv_->nthreads(); ++tid) {
        if (srv_->flip_final_role(tid) != Role::Ifid) continue;
        for (unsigned k = 0; k < 2; ++k) {
            const unsigned index = 3 * tid + k;
            auto& listener = state.listeners[index];
            if (listener.fd >= 0 || (!k && !configured_port_) || (k && !tls_context_)) continue;
            const int fd = socket(AF_INET, SOCK_STREAM | SOCK_CLOEXEC, 0);
            if (fd < 0) return false;
            listener.fd = fd;
            listener.owner = self_->id(); // rollback destination, before listen(2)
            listener.tls = tls_context_;
            // Install rollback's kernel reference BEFORE making the socket a
            // listener. Any failure up to listen is safe to close (no SYN queue).
            bool okay = state.register_on(*this, index);
            int one = 1;
            if (okay) okay = setsockopt(fd, SOL_SOCKET, SO_REUSEADDR, &one, sizeof(one)) == 0 &&
                            setsockopt(fd, SOL_SOCKET, SO_REUSEPORT, &one, sizeof(one)) == 0;
            if (okay && k) okay = setsockopt(fd, IPPROTO_TCP, TCP_DEFER_ACCEPT, &one, sizeof(one)) == 0;
            sockaddr_in address{};
            address.sin_family = AF_INET;
            address.sin_port = htons(k ? srv_->cfg().tls_port : configured_port_);
            if (okay) okay = inet_pton(AF_INET, srv_->cfg().bind_addr, &address.sin_addr) == 1 &&
                            bind(fd, reinterpret_cast<sockaddr*>(&address), sizeof(address)) == 0 &&
                            listen(fd, static_cast<int>(srv_->cfg().tcp_backlog)) == 0;
            if (!okay) {
                if (state.local[self_->id()].registered[index]) {
                    if (epoll_) ep_.del(fd);
                    else { int empty = -1; io_uring_register_files_update(ring_.raw(), index, &empty, 1); }
                    state.local[self_->id()].registered[index] = false;
                }
                close(fd); listener.fd = -1;
                return false;
            }
        }
    }
    for (auto& listener : state.listeners) {
        if (listener.fd < 0) continue;
        listener.target = listener.owner;
        if (listener.kind == UrKind::UnixAccept) continue;
        if (srv_->flip_final_role(listener.home) == Role::Ifid) listener.target = listener.home;
        else if (srv_->flip_final_role(listener.owner) != Role::Ifid)
            listener.target = srv_->flip_surviving_io_[listener.home % srv_->flip_surviving_io_count_];
    }
    return true;
}

bool IoLoop::fliplisten_prepare() {
    if (!srv_->flip_listeners_) return true; // serverless role models
    auto& state = *srv_->flip_listeners_;
    for (unsigned i = 0; i < kListeners; ++i) {
        const auto& listener = state.listeners[i];
        if (listener.fd >= 0 && listener.target == self_->id() &&
            !state.register_on(*this, i)) return false;
    }
    return true;
}

bool IoLoop::fliplisten_prepare_activation() {
    if (srv_->aof().configured() && !aof_bound_) {
        std::string error;
        if (!srv_->aof().bind_writer(*self_, ring_, error)) return false;
        aof_bound_ = true;
    }
    if (!fliplisten_prepare()) return false;
    prepared_role_ = true;
    return true;
}

void IoLoop::fliplisten_cancel_activation() {
    if (srv_->flip_listeners_) srv_->flip_listeners_->unregister_epoll(*this);
}

void IoLoop::fliplisten_commit() {
    if (!srv_->flip_listeners_) return; // no listeners in serverless role models
    auto& state = *srv_->flip_listeners_;
    // Every source is cancelled, and every target registered, before this
    // publication. No ring can still produce a completion naming the old owner.
    for (auto& listener : state.listeners)
        if (listener.fd >= 0) listener.owner = listener.target;
    for (uint32_t tid = 0; tid < srv_->nthreads(); ++tid) {
        auto& source = state.local[tid];
        if (source.head < 0 || srv_->flip_final_role(tid) == Role::Ifid) continue;
        const auto target = srv_->flip_surviving_io_[tid % srv_->flip_surviving_io_count_];
        auto& dest = state.local[target];
        if (dest.tail < 0) dest.head = source.head;
        else state.pending[dest.tail].next = source.head;
        dest.tail = source.tail;
        source.head = source.tail = -1;
    }
}

void IoLoop::fliplisten_install() {
    if (!srv_->flip_listeners_) return; // no listeners in serverless role models
    auto& state = *srv_->flip_listeners_;
    state.unregister_epoll(*this);
    for (unsigned k = 0; k < 3; ++k) {
        const auto& listener = state.listeners[3 * self_->id() + k];
        FlipListenerState::native(*this, kinds[k]) =
            listener.owner == self_->id() ? listener.fd : -1;
    }
}

bool IoLoop::fliplisten_finish(bool rollback) {
    if (!srv_->flip_listeners_) {
        if (!rollback) srv_->flip_validate_active();
        return true;
    }
    auto& state = *srv_->flip_listeners_;
    const uint64_t epoch = srv_->flip_epoch();
    if (state.admission.load(std::memory_order_acquire) != epoch) {
        if (!rollback) srv_->flip_validate_active(); // original exact frozen quotas
        state.admission.store(epoch, std::memory_order_release);
        return false;
    }
    for (uint32_t tid = 0; tid < srv_->nthreads(); ++tid)
        if (srv_->thread(tid).role() == Role::Ifid &&
            state.local[tid].resumed.load(std::memory_order_acquire) != epoch) return false;
    return true;
}

void IoLoop::fliplisten_resume() {
    if (!srv_->flip_listeners_) return; // no listeners in serverless role models
    auto& state = *srv_->flip_listeners_;
    const uint64_t epoch = srv_->flip_epoch();
    auto& own = state.local[self_->id()];
    if (state.admission.load(std::memory_order_acquire) != epoch ||
        own.resumed.load(std::memory_order_relaxed) == epoch) return;
    fliplisten_install();
    // This physical owner alone consumes the retained list. Client allocation,
    // maxclients, protected mode, TLS and UNIX handoff retain ordinary semantics.
    while (own.head >= 0) {
        const int fd = own.head;
        const auto pending = state.pending[fd];
        own.head = pending.next;
        if (own.head < 0) own.tail = -1;
        state.admit(*this, fd, pending.kind);
    }
    accept_quiescing_ = false;
    if (!epoll_) {
        for (auto& listener : state.listeners) {
            if (listener.fd < 0 || listener.owner != self_->id()) continue;
            if (listener.tls != tls_context_) std::abort();
            if (listener.home == self_->id()) {
                if (!accept_armed_ref(listener.kind)) arm_accept(listener.kind);
                if (!accept_armed_ref(listener.kind)) return;
            } else if (!state.arm(*this, listener)) return;
        }
        if (ring_.submit() < 0) return;
    }
    if (!pending_handoffs_.empty() || !self_->client_transfers_quiesced()) return;
    own.resumed.store(epoch, std::memory_order_release);
}

void IoLoop::fliplisten_retry_accept(UrKind kind) {
    // The pre-existing per-pass accept_pending_ branch is the only caller.
    // Keep arm_accept itself unchanged: even a cold call in its quiescing branch
    // made GCC save another register on every ordinary native accept rearm.
    if (!accept_quiescing_) { arm_accept(kind); return; }
    if (!srv_->flip_listeners_ || self_->role() != Role::Ifid || accepts_paused()) return;
    accept_quiescing_ = false;
    accept_pending_ = false; // the retry may own only borrowed/TLS listeners
    bool pending = false;
    for (auto& listener : srv_->flip_listeners_->listeners) {
        if (listener.fd < 0 || listener.owner != self_->id()) continue;
        if (listener.home == self_->id()) {
            if (!accept_armed_ref(listener.kind)) arm_accept(listener.kind);
        } else if (!srv_->flip_listeners_->arm(*this, listener)) pending = true;
    }
    // Publish only after the walk; setting quiescing before a later native
    // rearm used to suppress that rearm (or recurse through an arm hook).
    if (pending) accept_quiescing_ = accept_pending_ = true;
}

void IoLoop::fliplisten_shutdown() {
    if (!srv_ || !self_ || !srv_->flip_listeners_) return;
    auto& state = *srv_->flip_listeners_;
    auto& own = state.local[self_->id()];
    while (own.head >= 0) {
        int fd = own.head;
        own.head = state.pending[fd].next;
        close(fd);
    }
    own.tail = -1;
    for (auto& listener : state.listeners) {
        if (listener.fd < 0 || listener.owner != self_->id()) continue;
        if (listener.home != self_->id()) close(listener.fd);
        listener.fd = -1; // native descriptors are closed by the existing destructor
    }
}
} // namespace tomo
