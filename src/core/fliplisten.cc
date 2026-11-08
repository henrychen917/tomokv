// Listener descriptors and accepted-fd retention across IO role changes and CONFIG rebinds.
// Physical IO issuers operate their own rings/epoll instances. FLIP stage acknowledgements
// fence
// listener cancellation, registration and ownership changes; admission/resumed release-acquire
// epochs fence retained-fd admission. CONFIG uses a worker rendezvous with barriers before
// replacing
// descriptors. A listener's home identifies its slot independently of its current IO owner.

#include "io_loop.h"
#include <sys/resource.h>
#include <barrier>
#include <linux/inet_diag.h>
#include <linux/netlink.h>
#include <linux/sock_diag.h>
#include <linux/rtnetlink.h>
#include <sys/stat.h>

namespace tomo {
namespace {
constexpr UrKind kListenerAccept = static_cast<UrKind>(18);
constexpr UrKind kListenerCancel = static_cast<UrKind>(19);
static_assert(UrKind::WakeSent != kListenerAccept && UrKind::WakeSent != kListenerCancel);
constexpr uint32_t kListeners = 3 * kMaxThreads;
constexpr UrKind kinds[] = {UrKind::Accept, UrKind::TlsAccept, UrKind::UnixAccept};

}

// Contract: Server holds this shared metadata beyond an individual IO tenure. Listener records
// name descriptors whose registration/close work belongs to the relevant IO issuers. Each IO
// owns
// its Local list and indexed Pending entries while admitting/retaining accepts; a quiescent
// FLIP
// coordinator splices lists and changes owners before stage publication. admission and resumed
// use release/acquire epochs before draining retained fds. reserve bounds pending storage by
// RLIMIT_NOFILE; allocation/registration failures refuse preparation, and fd bounds violations
// abort.
struct FlipListenerState {
    struct Pending {
        int next;
        UrKind kind;
    };
    // Contract: home identifies the stable array slot; owner selects the current issuer and
    // target
    // is the prepared destination. Issuers mutate accept/cancel flags; FLIP or CONFIG changes
    // descriptor
    // ownership after cancellation/rendezvous fences. This record does not close fd on
    // destruction.
    struct Listener {
        int fd = -1;
        uint32_t home = 0, owner = 0, target = 0;
        UrKind kind = UrKind::Accept;
        const TlsContext* tls = nullptr;
        bool armed = false, cancel_pending = false, cancel_submitted = false;
    };
    // Contract: The indexed physical IO owns registration flags and retained-list head/tail
    // during
    // normal processing. Quiescent coordinator splicing precedes release-published admission.
    // resumed
    // release-publishes completion after retained admission, accept rearming and transfer
    // quiescence.
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
        return kind == UrKind::UnixAccept  ? io.unix_listen_fd_
               : kind == UrKind::TlsAccept ? io.tls_listen_fd_
                                           : io.listen_fd_;
    }
    bool register_on(IoLoop& io, unsigned index) {
        auto& own = local[io.self_->id()];
        if (own.registered[index]) return true;
        auto& listener = listeners[index];
        if (io.epoll_) {
            const auto tag = listener.home == io.self_->id() ? ur_tag(listener.kind, nullptr)
                                                             : ur_tag(kListenerAccept, &listener);
            if (!set_nonblocking(listener.fd) || !io.ep_.add(listener.fd, EPOLLIN, tag))
                return false;
        } else {
            // Reserve the real kernel file reference, on the destination issuer,
            // before its prepare ACK. No accept is submitted until admission.
            if (!own.files_registered) {
                int empty[kListeners];
                std::fill_n(empty, kListeners, -1);
                if (io_uring_register_files(io.ring_.raw(), empty, kListeners) < 0) return false;
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
            if (io.srv_->read_local_enabled())
                io.admit_retained_fd<true, true>(fd, kind);
            else
                io.admit_retained_fd<true, false>(fd, kind);
        } else {
            if (io.srv_->read_local_enabled())
                io.admit_retained_fd<false, true>(fd, kind);
            else
                io.admit_retained_fd<false, false>(fd, kind);
        }
    }

    // CONFIG prepares every replacement before touching any old socket. The
    // same listener records (including homes transferred by FLIP) keep their
    // identity. Only the physical issuer touches its ring or epoll instance.
    // Contract: cfgfix_rebind owns this plan through an exclusive worker rendezvous. next owns
    // replacement descriptors until commit exchanges them into listener records; destruction
    // closes
    // unconsumed replacements. All workers meet join barriers, and all_okay uses two barriers
    // so no
    // worker overwrites a phase result before peers read it. Failed preparation leaves commit
    // false.
    struct Rebind {
        Server& server;
        FlipListenerState& state;
        std::array<int, kListeners> next;
        std::barrier<> join;
        std::atomic<bool> okay{true};
        std::atomic<bool> pending{false};
        uint16_t port;
        std::string bind;
        std::string error;
        bool listeners, old_aof, want_aof;
        uint32_t writer = UINT32_MAX;
        Rebind(Server& s, FlipListenerState& state, uint16_t p, std::string address, int aof)
            : server(s),
              state(state),
              join(s.nthreads()),
              port(p),
              bind(std::move(address)),
              listeners(p != s.cfg().port || bind != s.cfg().bind_addr),
              old_aof(s.aof().configured()),
              want_aof(aof < 0 ? old_aof : aof != 0) {
            next.fill(-1);
            for (uint32_t tid = 0; tid < s.nthreads(); ++tid)
                if (s.serves_clients(tid) && (!old_aof || s.aof().writer_is(tid))) writer = tid;
        }
        ~Rebind() {
            for (int fd : next)
                if (fd >= 0) ::close(fd);
        }
        bool all_okay() {
            join.arrive_and_wait();
            const bool result = okay.load();
            // Nobody may publish the next phase's result before all peers
            // have sampled this phase, including a failing writer.
            join.arrive_and_wait();
            return result;
        }
    };
    static void fence_rebound_accept(io_uring_cqe& cqe) {
        const auto kind = ur_kind(cqe.user_data);
        bool replaced = kind == UrKind::Accept || kind == UrKind::TlsAccept;
        if (kind == kListenerAccept) {
            const auto& listener = *ur_ptr<Listener>(cqe.user_data);
            replaced = listener.kind == UrKind::Accept || listener.kind == UrKind::TlsAccept;
        }
        // A transferred UNIX listener uses kListenerAccept too. Its terminal
        // CQE still owes the normal loop a rearm; CONFIG did not cancel it.
        if (!replaced) return;
        if (cqe.res < 0)
            cqe.user_data = ur_tag(static_cast<UrKind>(255), nullptr);
        else
            cqe.flags |= IORING_CQE_F_MORE;
    }
    // Contract: Each rendezvous worker calls with its physical tid and any IO context. Barriers
    // coordinate the elected AOF writer with per-owner queue flush/binding work. Existing
    // atomic work,
    // drain timeout or persistence failure sets okay false; all_okay propagates refusal before
    // rebinding.
    // Bindings are removed on all owners before the writer frees AOF state.
    static void aof_worker(Rebind& plan, IoLoop* loop, unsigned tid) {
        if (plan.old_aof == plan.want_aof) return;
        if (!plan.all_okay()) return;
        auto& server = plan.server;
        auto& manager = server.aof();
        if (tid == 0 && (plan.writer == UINT32_MAX || server.atomic_inflight() ||
                         server.atomic_apply_inflight())) {
            plan.error = "AOF configuration requires completed atomic commands";
            plan.okay.store(false);
        }
        if (!plan.all_okay()) return;
        if (plan.want_aof) {
            if (tid == plan.writer &&
                !manager.runtime_enable(server.thread(tid), loop->ring_, plan.error))
                plan.okay.store(false);
        } else {
            // Every owner flushes its own producer and completion queue. Only
            // the elected IO touches persistence CQEs; ordinary client work
            // remains parked. Keep the original bindings on any drain error.
            const uint64_t deadline = now_ns() + 5000000000ull;
            for (;;) {
                if (tid == 0) plan.pending.store(false);
                plan.join.arrive_and_wait();
                if (tid == plan.writer) manager.runtime_pump(server.thread(tid), loop->ring_);
                if (!cfgfix_executor_control(server, tid, 2)) plan.pending.store(true);
                if (tid == plan.writer && manager.pending_chunks()) plan.pending.store(true);
                plan.join.arrive_and_wait();
                if (tid == 0 && (manager.failed() || now_ns() >= deadline)) {
                    plan.error = "AOF producers could not drain";
                    plan.okay.store(false);
                }
                plan.join.arrive_and_wait();
                const bool again = plan.okay.load() && plan.pending.load();
                plan.join.arrive_and_wait();
                if (!again) break;
            }
            if (plan.okay.load() && tid == plan.writer &&
                !manager.runtime_disable(server.thread(tid), loop->ring_, plan.error))
                plan.okay.store(false);
        }
        if (!plan.all_okay()) return;
        for (Shard* shard : server.thread(tid).shards())
            shard->store().bind_aof(plan.want_aof ? &manager : nullptr, shard->id(), 0);
        if (!cfgfix_executor_control(server, tid, plan.want_aof ? 1 : 0)) std::abort();
        if (loop) loop->aof_bound_ = plan.want_aof;
        if (tid == 0) const_cast<Config&>(server.cfg()).appendonly = plan.want_aof;
        plan.join.arrive_and_wait();
        // No owner can retain a channel or producer binding when it is freed.
        if (!plan.want_aof && tid == plan.writer) manager.runtime_reset();
        plan.join.arrive_and_wait();
    }
    // Contract: The exclusive CONFIG rendezvous calls once per physical worker with a shared
    // Rebind plan. Each issuer reserves/cancels/registers its own kernel state; join barriers
    // separate
    // reservation, cancellation/AOF, descriptor commit and rearming. The caller holds
    // listener-control
    // admission. okay=false rolls back replacement registrations; failures of required
    // committed
    // kernel updates abort. Successful accepts keep their ordinary-loop lifetime obligations.
    static void rebind_worker(void* context, unsigned tid) {
        auto& plan = *static_cast<Rebind*>(context);
        auto& state = plan.state;
        auto* loop = io(plan.server, tid);
        if (!plan.listeners) {
            aof_worker(plan, loop, tid);
            return;
        }
        if (loop) {
            auto& own = state.local[tid];
            // Reserve epoll registrations without changing the old set.
            for (unsigned i = 0; i < kListeners; ++i) {
                const auto& listener = state.listeners[i];
                if (listener.kind == UrKind::UnixAccept || listener.owner != tid ||
                    plan.next[i] < 0)
                    continue;
                if (loop->epoll_) {
                    const auto tag = listener.home == tid
                                         ? ur_tag(listener.kind, nullptr)
                                         : ur_tag(kListenerAccept, &state.listeners[i]);
                    if (!set_nonblocking(plan.next[i]) ||
                        !loop->ep_.add(plan.next[i], EPOLLIN, tag))
                        plan.okay.store(false);
                }
            }
            (void)own;
        }
        plan.join.arrive_and_wait();
        if (plan.okay.load() && loop) {
            // Cancel by descriptor, never ANY: live client and persistence CQEs
            // retain their original lifetimes. The sync fence runs on issuer.
            loop->accept_quiescing_ = true;
            if (!loop->epoll_) {
                loop->ring_.submit_and_reap();
                for (auto& listener : state.listeners) {
                    if (listener.fd < 0 || listener.kind == UrKind::UnixAccept ||
                        listener.owner != tid)
                        continue;
                    io_uring_sync_cancel_reg cancel{};
                    cancel.fd = listener.fd;
                    cancel.flags = IORING_ASYNC_CANCEL_FD | IORING_ASYNC_CANCEL_ALL;
                    cancel.timeout.tv_sec = 5;
                    int rc;
                    do {
                        rc = io_uring_register_sync_cancel(loop->ring_.raw(), &cancel);
                    } while (rc == -EINTR);
                    if (rc < 0 && rc != -ENOENT)
                        plan.okay.store(false);
                    else {
                        // A later AOF apply failure keeps these descriptors,
                        // but rollback still owes them a fresh accept arm.
                        if (listener.home == tid)
                            loop->accept_armed_ref(listener.kind) = false;
                        else
                            listener.armed = false;
                    }
                }
                // Fence old accepts without executing unrelated client CQEs
                // inside the rendezvous. Preserve successful accepts for the
                // normal loop, but remove their obsolete rearm obligation.
                loop->ring_.submit_and_reap();
                unsigned head;
                io_uring_cqe* cqe;
                io_uring_for_each_cqe(loop->ring_.raw(), head, cqe) fence_rebound_accept(*cqe);
            }
        }
        plan.join.arrive_and_wait();
        aof_worker(plan, loop, tid);
        plan.join.arrive_and_wait();
        const bool commit = plan.okay.load();
        if (loop) {
            auto& own = state.local[tid];
            for (unsigned i = 0; i < kListeners; ++i) {
                auto& listener = state.listeners[i];
                if (listener.kind == UrKind::UnixAccept) continue;
                const int old = listener.fd, next = plan.next[i];
                if (loop->epoll_) {
                    if (!commit && listener.owner == tid && next >= 0) loop->ep_.del(next);
                    if (commit && own.registered[i] && old >= 0 && !loop->ep_.del(old))
                        std::abort();
                } else if (commit && own.files_registered && own.registered[i]) {
                    if (io_uring_register_files_update(loop->ring_.raw(), i, &next, 1) != 1)
                        std::abort();
                }
                if (commit)
                    own.registered[i] = loop->epoll_ ? listener.owner == tid && next >= 0
                                                     : own.registered[i] && next >= 0;
            }
        }
        plan.join.arrive_and_wait();
        if (tid == 0 && commit) {
            for (unsigned i = 0; i < kListeners; ++i) {
                auto& listener = state.listeners[i];
                if (listener.kind == UrKind::UnixAccept) continue;
                if (listener.fd >= 0) ::close(listener.fd);
                listener.fd = std::exchange(plan.next[i], -1);
                listener.armed = listener.cancel_pending = listener.cancel_submitted = false;
            }
            // Retain the address independently of CONFIG table vector storage.
            static std::string configured_bind;
            configured_bind = plan.bind;
            auto& cfg = const_cast<Config&>(plan.server.cfg());
            cfg.port = plan.port;
            cfg.bind_addr = configured_bind.c_str();
        }
        plan.join.arrive_and_wait();
        if (loop) {
            if (commit) {
                loop->configured_port_ = plan.port;
                loop->fliplisten_install();
                loop->accept_armed_ = loop->tls_accept_armed_ = false;
                loop->accept_pending_ = loop->tls_accept_pending_ = false;
            }
            loop->accept_quiescing_ = false;
            if (!loop->epoll_ && loop->self_->role() == Role::Ifid) {
                for (auto& listener : state.listeners) {
                    if (listener.fd < 0 || listener.owner != tid) continue;
                    if (listener.home == tid) {
                        if (!loop->accept_armed_ref(listener.kind)) loop->arm_accept(listener.kind);
                    } else if (!state.arm(*loop, listener))
                        loop->accept_quiescing_ = loop->accept_pending_ = true;
                }
                loop->ring_.submit();
            }
        }
    }
};

namespace {
// CONFIG may replace an overlapping address on our own port, so an ordinary
// exclusive bind would reject our old listeners as well. Inspect the kernel's
// listening sockets, excluding only the descriptors owned by this server. Like
// the boot probe this is a preflight, not a process-lifetime port reservation.
// Contract: The CONFIG rebind caller supplies stable listener records under control admission.
// Use a local netlink socket to inspect IPv4/IPv6 listening sockets, excluding this server's
// descriptor inodes. Return false with an error on conflicts, incomplete inspection or
// syscalls;
// the RAII socket closes on exit. This preflight does not reserve the port against later binds.
bool rebind_exclusive(const FlipListenerState& state, const char* address, uint16_t port,
                      std::string& error) {
    if (!port) return true;
    in_addr wanted{};
    if (::inet_pton(AF_INET, address, &wanted) != 1) {
        error = "invalid address";
        return false;
    }
    std::array<ino_t, kListeners> owned{};
    unsigned count = 0;
    for (const auto& listener : state.listeners)
        if (listener.fd >= 0) {
            struct stat info {};
            if (::fstat(listener.fd, &info) != 0) {
                error = std::strerror(errno);
                return false;
            }
            owned[count++] = info.st_ino;
        }
    const int fd = ::socket(AF_NETLINK, SOCK_DGRAM | SOCK_CLOEXEC, NETLINK_SOCK_DIAG);
    if (fd < 0) {
        error = std::strerror(errno);
        return false;
    }
    struct Close {
        int fd;
        ~Close() { ::close(fd); }
    } close{fd};
    timeval timeout{2, 0};
    if (::setsockopt(fd, SOL_SOCKET, SO_RCVTIMEO, &timeout, sizeof(timeout)) != 0) {
        error = std::strerror(errno);
        return false;
    }
    struct Request {
        nlmsghdr header;
        inet_diag_req_v2 body;
    } request{};
    request.header.nlmsg_len = sizeof(request);
    request.header.nlmsg_type = SOCK_DIAG_BY_FAMILY;
    request.header.nlmsg_flags = NLM_F_REQUEST | NLM_F_DUMP;
    request.header.nlmsg_seq = 1;
    request.body.sdiag_protocol = IPPROTO_TCP;
    request.body.idiag_states = 1u << 10;  // TCP_LISTEN
    sockaddr_nl kernel{};
    kernel.nl_family = AF_NETLINK;
    for (const uint8_t family : {AF_INET, AF_INET6}) {
        request.body.sdiag_family = family;
        request.header.nlmsg_seq = family;
        if (::sendto(fd, &request, sizeof(request), 0, reinterpret_cast<sockaddr*>(&kernel),
                     sizeof(kernel)) != sizeof(request)) {
            error = std::strerror(errno);
            return false;
        }
        for (;;) {
            alignas(nlmsghdr) char buffer[16384];
            const auto received = ::recv(fd, buffer, sizeof(buffer), MSG_TRUNC);
            if (received < 0 && errno == EINTR) continue;
            if (received <= 0 || received > static_cast<ssize_t>(sizeof(buffer))) {
                error = "could not inspect listener ownership";
                return false;
            }
            int remaining = static_cast<int>(received);
            for (auto* header = reinterpret_cast<nlmsghdr*>(buffer); NLMSG_OK(header, remaining);
                 header = NLMSG_NEXT(header, remaining)) {
                if (header->nlmsg_flags & NLM_F_DUMP_INTR) {
                    error = "listener ownership changed during inspection";
                    return false;
                }
                if (header->nlmsg_type == NLMSG_DONE) goto family_done;
                if (header->nlmsg_type != SOCK_DIAG_BY_FAMILY ||
                    header->nlmsg_len < NLMSG_LENGTH(sizeof(inet_diag_msg))) {
                    error = "could not inspect listener ownership";
                    return false;
                }
                const auto* socket = static_cast<const inet_diag_msg*>(NLMSG_DATA(header));
                if (ntohs(socket->id.idiag_sport) != port) continue;
                uint32_t bound = socket->id.idiag_src[0];
                if (family == AF_INET6) {
                    // IPv6-only sockets do not reserve any IPv4 endpoint. A dual
                    // stack wildcard or mapped address does, including REUSEPORT.
                    int length = header->nlmsg_len - NLMSG_LENGTH(sizeof(*socket));
                    auto* attr = reinterpret_cast<const rtattr*>(socket + 1);
                    bool known = false, only = false;
                    for (; RTA_OK(attr, length); attr = RTA_NEXT(attr, length)) {
                        if (attr->rta_type == INET_DIAG_SKV6ONLY && RTA_PAYLOAD(attr) >= 1) {
                            known = true;
                            only = *static_cast<const uint8_t*>(RTA_DATA(attr));
                        }
                    }
                    if (!known) {
                        error = "could not inspect IPv6 listener ownership";
                        return false;
                    }
                    if (only) continue;
                    const auto* source = socket->id.idiag_src;
                    if (source[0] || source[1] || (source[2] && source[2] != htonl(0xffff)))
                        continue;
                    if (!source[2] && source[3]) continue;
                    bound = source[3];
                }
                if (wanted.s_addr && bound && wanted.s_addr != bound) continue;
                if (std::find(owned.begin(), owned.begin() + count, socket->idiag_inode) !=
                    owned.begin() + count)
                    continue;
                error = std::strerror(EADDRINUSE);
                return false;
            }
        }
    family_done:;
    }
    return true;
}
}

// Contract: The CONFIG command's executing worker supplies caller for the global exclusive
// rendezvous. Acquire cfgfix control admission, prepare descriptors, then have each physical
// issuer
// apply its part behind worker barriers. Errors return false with diagnostics; scope guards
// release
// admission and close uncommitted sockets. Successful commit transfers descriptor ownership and
// may request AOF rewrite; no partially prepared replacement is installed before the commit
// decision.
bool cfgfix_rebind(Server& server, uint32_t caller, uint16_t port, const std::string& bind,
                   std::string& error, int appendonly) {
    if (port == server.cfg().port && bind == server.cfg().bind_addr &&
        (appendonly < 0 || (appendonly != 0) == server.aof().configured()))
        return true;
    // SO_REUSEPORT is needed for per-IO sockets, but must not merge the
    // plaintext listener with our live TLS group. Redis's bind rejects this.
    if (port && port == server.cfg().tls_port) {
        error = std::strerror(EADDRINUSE);
        return false;
    }
    if (!cfgfix_control_begin(server)) {
        error = "listener control path is busy";
        return false;
    }
    struct Finish {
        Server& server;
        bool held = true;
        ~Finish() {
            if (held) cfgfix_control_end(server);
        }
    } finish{server};
    if (!fliplisten_reserve(server, error)) return false;
    auto& state = *server.flip_listeners_;
    if ((port != server.cfg().port || bind != server.cfg().bind_addr) &&
        (!rebind_exclusive(state, bind.c_str(), port, error) ||
         !rebind_exclusive(state, bind.c_str(), server.cfg().tls_port, error)))
        return false;
    FlipListenerState::Rebind plan(server, state, port, bind, appendonly);
    for (unsigned i = 0; plan.listeners && i < 3 * server.nthreads(); ++i) {
        auto& listener = state.listeners[i];
        if (listener.kind == UrKind::UnixAccept || listener.home >= server.nthreads()) continue;
        const bool tcp = listener.kind == UrKind::Accept;
        const uint16_t next_port = tcp ? port : server.cfg().tls_port;
        if (!next_port) continue;
        if (listener.fd < 0 && server.thread(listener.home).role() != Role::Ifid) continue;
        // A zero-port -> live-port transition starts one listener per active IO.
        if (listener.fd < 0) listener.owner = listener.home;
        plan.next[i] = IoLoop::make_reuseport_listener(bind.c_str(), next_port,
                                                       server.cfg().tcp_backlog, !tcp);
        if (plan.next[i] < 0) {
            error = std::strerror(errno);
            return false;
        }
    }
    // Parked members would reach the rendezvous only at their park timeout, holding the whole
    // server meanwhile: ring them right after the request is published (before the caller waits).
    if (!server.debug_sleep_coordinator().exclusive(
            caller, server.nthreads(), &plan, FlipListenerState::rebind_worker,
            [](void* s, unsigned origin) {
                static_cast<Server*>(s)->wake_peers_from(origin, true);
            },
            &server)) {
        error = "listener control rendezvous timed out";
        return false;
    }
    if (!plan.okay.load()) {
        error = plan.error.empty() ? "listener registration or cancellation failed"
                                   : "appendonly: " + plan.error;
        return false;
    }
    cfgfix_control_end(server);
    finish.held = false;
    if (!plan.old_aof && plan.want_aof) server.aof().request_rewrite();
    return true;
}

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
                if (!io) continue;  // serverless role/quota fixtures have no network loop
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
    if (own.tail < 0)
        own.head = fd;
    else
        state.pending[own.tail].next = fd;
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
        if (!sqe) {
            self_->sig().sqe_starved++;
            continue;
        }
        const uint64_t tag =
            native ? ur_tag(listener.kind, reinterpret_cast<void*>(accept_cancel_generation_))
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
            (listener.armed || listener.cancel_pending))
            return false;
    return true;
}

void IoLoop::fliplisten_cqe(io_uring_cqe* cqe) {
    const auto kind = ur_kind(cqe->user_data);
    if (kind != kListenerAccept && kind != kListenerCancel) return;
    auto& listener = *ur_ptr<FlipListenerState::Listener>(cqe->user_data);
    if (listener.owner != self_->id()) std::abort();
    if (kind == kListenerCancel) {
        listener.cancel_pending = false;
        return;
    }
    if (cqe->res >= 0) {
        if (accepts_paused())
            fliplisten_retain(cqe->res, listener.kind);
        else
            srv_->flip_listeners_->admit(*this, cqe->res, listener.kind);
    } else if (cqe->res != -ECANCELED)
        self_->sig().accept_err++;
    if (!(cqe->flags & IORING_CQE_F_MORE)) {
        listener.armed = false;
        if (!accept_quiescing_ && !srv_->flip_listeners_->arm(*this, listener)) {
            // Route SQ starvation through the accept_pending_ retry branch.
            accept_quiescing_ = accept_pending_ = true;
        }
    }
}

uint32_t IoLoop::fliplisten_epoll(uint64_t tag) {
    if (ur_kind(tag) != kListenerAccept || accepts_paused()) return 0;
    auto& listener = *ur_ptr<FlipListenerState::Listener>(tag);
    if (listener.owner != self_->id()) return 0;  // reversible destination registration
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
        if (accepts_paused()) {
            fliplisten_retain(fd, listener.kind);
            return count;
        }
        srv_->flip_listeners_->admit(*this, fd, listener.kind);
    }
}

// Contract: The FLIP coordinator calls after old IOs acknowledge listener cancellation/drain.
// Create missing destination TCP/TLS listeners and reserve a rollback kernel reference before
// listen; choose targets without yet changing existing owners. Socket/registration failure
// returns
// false and closes a failed new socket. Later stage publication exposes this prepared metadata;
// the commit waits for destination registration and source preparation acknowledgements.
bool IoLoop::fliplisten_plan() {
    if (!srv_->flip_listeners_) return true;  // serverless role models
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
            listener.owner = self_->id();  // rollback destination, before listen(2)
            listener.tls = tls_context_;
            // Install rollback's kernel reference BEFORE making the socket a
            // listener. Any failure up to listen is safe to close (no SYN queue).
            bool okay = state.register_on(*this, index);
            int one = 1;
            if (okay)
                okay = setsockopt(fd, SOL_SOCKET, SO_REUSEADDR, &one, sizeof(one)) == 0 &&
                       setsockopt(fd, SOL_SOCKET, SO_REUSEPORT, &one, sizeof(one)) == 0;
            if (okay && k)
                okay = setsockopt(fd, IPPROTO_TCP, TCP_DEFER_ACCEPT, &one, sizeof(one)) == 0;
            sockaddr_in address{};
            address.sin_family = AF_INET;
            address.sin_port = htons(k ? srv_->cfg().tls_port : configured_port_);
            if (okay)
                okay = inet_pton(AF_INET, srv_->cfg().bind_addr, &address.sin_addr) == 1 &&
                       bind(fd, reinterpret_cast<sockaddr*>(&address), sizeof(address)) == 0 &&
                       listen(fd, static_cast<int>(srv_->cfg().tcp_backlog)) == 0;
            if (!okay) {
                if (state.local[self_->id()].registered[index]) {
                    if (epoll_)
                        ep_.del(fd);
                    else {
                        int empty = -1;
                        io_uring_register_files_update(ring_.raw(), index, &empty, 1);
                    }
                    state.local[self_->id()].registered[index] = false;
                }
                close(fd);
                listener.fd = -1;
                return false;
            }
        }
    }
    for (auto& listener : state.listeners) {
        if (listener.fd < 0) continue;
        listener.target = listener.owner;
        if (listener.kind == UrKind::UnixAccept) continue;
        if (srv_->flip_final_role(listener.home) == Role::Ifid)
            listener.target = listener.home;
        else if (srv_->flip_final_role(listener.owner) != Role::Ifid)
            listener.target =
                srv_->flip_surviving_io_[listener.home % srv_->flip_surviving_io_count_];
    }
    return true;
}

bool IoLoop::fliplisten_prepare() {
    if (!srv_->flip_listeners_) return true;  // serverless role models
    auto& state = *srv_->flip_listeners_;
    for (unsigned i = 0; i < kListeners; ++i) {
        const auto& listener = state.listeners[i];
        if (listener.fd >= 0 && listener.target == self_->id() && !state.register_on(*this, i))
            return false;
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
    if (!srv_->flip_listeners_) return;  // no listeners in serverless role models
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
        if (dest.tail < 0)
            dest.head = source.head;
        else
            state.pending[dest.tail].next = source.head;
        dest.tail = source.tail;
        source.head = source.tail = -1;
    }
}

void IoLoop::fliplisten_install() {
    if (!srv_->flip_listeners_) return;  // no listeners in serverless role models
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
        if (!rollback) srv_->flip_validate_active();  // exact frozen quotas
        state.admission.store(epoch, std::memory_order_release);
        return false;
    }
    for (uint32_t tid = 0; tid < srv_->nthreads(); ++tid)
        if (srv_->thread(tid).role() == Role::Ifid &&
            state.local[tid].resumed.load(std::memory_order_acquire) != epoch)
            return false;
    return true;
}

void IoLoop::fliplisten_resume() {
    if (!srv_->flip_listeners_) return;  // no listeners in serverless role models
    auto& state = *srv_->flip_listeners_;
    const uint64_t epoch = srv_->flip_epoch();
    auto& own = state.local[self_->id()];
    if (state.admission.load(std::memory_order_acquire) != epoch ||
        own.resumed.load(std::memory_order_relaxed) == epoch)
        return;
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
            } else if (!state.arm(*this, listener))
                return;
        }
        if (ring_.submit() < 0) return;
    }
    if (!pending_handoffs_.empty() || !self_->client_transfers_quiesced()) return;
    own.resumed.store(epoch, std::memory_order_release);
}

void IoLoop::fliplisten_retry_accept(UrKind kind) {
    // The per-pass accept_pending_ branch calls this retry helper. Keep the listener scan
    // outside
    // arm_accept so ordinary native accept rearming does not carry its extra register
    // requirements.
    if (!accept_quiescing_) {
        arm_accept(kind);
        return;
    }
    if (!srv_->flip_listeners_ || self_->role() != Role::Ifid || accepts_paused()) return;
    accept_quiescing_ = false;
    accept_pending_ = false;  // the retry may own only borrowed/TLS listeners
    bool pending = false;
    for (auto& listener : srv_->flip_listeners_->listeners) {
        if (listener.fd < 0 || listener.owner != self_->id()) continue;
        if (listener.home == self_->id()) {
            if (!accept_armed_ref(listener.kind)) arm_accept(listener.kind);
        } else if (!srv_->flip_listeners_->arm(*this, listener))
            pending = true;
    }
    // Publish quiescing after the walk. Publishing it before a later native arm_accept would
    // suppress that rearm; keeping the retry outside arm_accept also avoids recursive rearming.
    if (pending) accept_quiescing_ = accept_pending_ = true;
}

// Issuer only, after shutdown cancellation. register_on() reserves listener file references
// in this ring's fixed-file table. close(2) does not drop them, and the kernel frees a ring's
// table only in its asynchronous exit work, which can finish after the process was reaped:
// a restart then finds the port still bound. Drop them now; no request can use them.
void IoLoop::fliplisten_release_files() {
    if (epoll_ || !srv_ || !self_ || !srv_->flip_listeners_) return;
    auto& own = srv_->flip_listeners_->local[self_->id()];
    if (!own.files_registered) return;
    const int rc = io_uring_unregister_files(ring_.raw());
    if (rc < 0)
        std::fprintf(stderr, "shutdown: listener file release failed: %s\n", std::strerror(-rc));
    own.files_registered = false;
    std::fill(std::begin(own.registered), std::end(own.registered), false);
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
        listener.fd = -1;  // IoLoop destruction closes native descriptors
    }
}
}  // namespace tomo
