// io_loop.h — the IO stage. Accepts, receives, parses, routes, publishes, retires, and (in Io mode)
// sends.
//
// EVERY CROSS-THREAD SIGNAL HERE IS A Channel, and every measurement is a LoopSignals field, so this
// loop is comparable with the EX and WB loops through one interface. See signal.h.
//
//   out  task_in of the shard's owner        a parsed op to execute
//   in   client_in from workers              "you have completed ops to retire"
//
// WHAT MOVES BETWEEN MODES, AND WHAT DOES NOT. The ROB is ALWAYS drained by the IO thread that owns
// the connection, in every mode. Only the send syscall moves. Letting a second thread retire from
// the ROB would make dispatch_id/flush_id a cross-thread pair for no measured benefit. So this is
// NOT a byte-for-byte reproduction of the fork's ex-wb, which had the executor build and send its
// own contiguous ready prefix without returning to IO — said here so no result from that mode is
// misread as a verdict on that design.
#pragma once
#include <deque>
#include <arpa/inet.h>
#include <netinet/in.h>
#include <netinet/tcp.h>
#include <sys/socket.h>
#include <sys/un.h>
#include <unistd.h>
#include <cstdio>
#include <cstdlib>
#include <new>
#include <string>
#include <unordered_map>
#include <unordered_set>
#include <vector>
#include "server.h"
#include "signal.h"
#include "../net/conn.h"
#include "../net/resp.h"
#include "../net/uring.h"
#include "../net/wb.h"
#include "../cmd/command.h"
#include "../cmd/blocking.h"
#include "../cmd/auth.h"
#include "../cmd/acl.h"
#include "../cmd/multi.h"
#include "../cmd/xshard.h"
#include "../snapshot/snapshot.h"

namespace tomo {

inline constexpr uint32_t kRecvChunk = 16 * 1024;

// THE FIVE LOOPS. Each mode composes threads from five specialised loop shapes, distinguished by
// what the thread OWNS while serving (pure 2s, owner ruling 2026-08-24):
//
//   io    IoLoop    recv+parse+retire+send; owns the whole client
//   ex    ExLoop    execute+notify; never sends

class IoLoop {
public:
    WbEngine& engine() { return wb_; }
    uint32_t reap_atomic_deferred() {
        return scatter_pool_.reap_deferred() + multi_owner_reap_entry(*this);
    }
    // ONE LISTENING SOCKET PER IO THREAD, via SO_REUSEPORT.
    //
    // Sharing a single listen fd across io threads does NOT distribute connections: every thread
    // arms a multishot accept on it and the kernel satisfies them all from one ring. Measured
    // consequence with 6 io threads and 577 connections — t5 took every single one and t0..t4 sat
    // idle for the entire run, so the server was really running on one io thread. It looked like a
    // latency problem (uniform ~3.5 ms at p1) and was actually a distribution problem.
    //
    // With SO_REUSEPORT the kernel hashes each incoming connection to one of the listening sockets,
    // which spreads them across threads without any userspace handoff. Note this is safe WITHIN one
    // process; two SERVER PROCESSES sharing a port is the failure mode that once faked data loss,
    // so a boot must still verify nothing else holds the port.
    bool init(Server* srv, ThreadCtx* self, const char* addr, uint16_t port,
              int unix_listen_fd = -1) {
        srv_ = srv; self_ = self;
        listen_fd_ = make_reuseport_listener(addr, port, srv_->cfg().tcp_backlog);
        if (listen_fd_ < 0) return false;
        unix_listen_fd_ = unix_listen_fd;
        if (!ring_.init(4096)) return false;
        self_->set_ring(&ring_);
        wb_.bind(&ring_, this, [](void* ctx, int32_t shard, const char* ptr) {
            static_cast<IoLoop*>(ctx)->queue_borrow_release(shard, ptr);
        }, this, [](void* ctx, Client& client, Op& op) {
            auto* loop = static_cast<IoLoop*>(ctx);
            if (op.has_scatter_state())
                xshard_retire(*loop->srv_, *loop->self_, loop->ring_, client, op,
                    loop->scatter_pool_, loop->self_->id(), loop,
                    [](void* release_ctx, int32_t shard, const char* ptr) {
                        static_cast<IoLoop*>(release_ctx)->queue_borrow_release(shard, ptr);
                    });
            else if (op.has_blocking_state())
                blocking_retire(*loop->srv_, client, op, *loop->self_);
            else if (op.has_multi_state()) multi_retire_entry(*loop, client, op);
        }, srv_->client_obuf_armed_ptr(), this, [](void* ctx, Client& client) {
            return static_cast<IoLoop*>(ctx)->client_obuf_check(&client, true);
        }, &cached_now_s_);
        return true;
    }

    ~IoLoop() {
        if (self_) pubsub_shutdown_events();
        if (listen_fd_ >= 0) ::close(listen_fd_);
        if (unix_listen_fd_ >= 0) ::close(unix_listen_fd_);
        for (Client* c : pending_handoffs_) {
            ::close(c->fd());
            srv_->client_released();
            delete c;
        }
        multi_shutdown_entry(*this);
    }

    static int make_reuseport_listener(const char* addr, uint16_t port, uint32_t backlog = 511) {
        int fd = ::socket(AF_INET, SOCK_STREAM, 0);
        if (fd < 0) return -1;
        int one = 1;
        setsockopt(fd, SOL_SOCKET, SO_REUSEADDR, &one, sizeof(one));
        setsockopt(fd, SOL_SOCKET, SO_REUSEPORT, &one, sizeof(one));
        sockaddr_in sa{};
        sa.sin_family = AF_INET;
        sa.sin_port   = htons(port);
        if (::inet_pton(AF_INET, addr, &sa.sin_addr) != 1) { ::close(fd); return -1; }
        if (::bind(fd, reinterpret_cast<sockaddr*>(&sa), sizeof(sa)) != 0) { ::close(fd); return -1; }
        if (::listen(fd, static_cast<int>(backlog)) != 0) { ::close(fd); return -1; }
        return fd;
    }

    // Linux does not provide TCP-style SO_REUSEPORT distribution for filesystem AF_UNIX paths:
    // the pathname is a unique bind key. One listener is therefore armed by one IO thread, which
    // round-robins accepted Client handles through the existing per-producer client channels.
    static int make_unix_listener(const char* path, uint32_t backlog = 511) {
        sockaddr_un sa{};
        if (!path || !*path || std::strlen(path) >= sizeof(sa.sun_path)) return -1;
        int fd = ::socket(AF_UNIX, SOCK_STREAM, 0);
        if (fd < 0) return -1;
        sa.sun_family = AF_UNIX;
        std::memcpy(sa.sun_path, path, std::strlen(path) + 1);
        if (::bind(fd, reinterpret_cast<sockaddr*>(&sa), sizeof(sa)) != 0 ||
            ::listen(fd, static_cast<int>(backlog)) != 0) {
            ::close(fd); return -1;
        }
        return fd;
    }

    Ring& ring() { return ring_; }

    void run() {
        if (unix_listen_fd_ >= 0 || (srv_->cfg().unixsocket && *srv_->cfg().unixsocket))
            run_loop<true>();
        else
            run_loop<false>();
    }

private:
    friend bool multi_dispatch_entry(IoLoop&, Client&, Op&, uint32_t);
    friend bool auth_dispatch_entry(IoLoop&, Client&, Op&, uint32_t);
    friend bool acl_dispatch_entry(IoLoop&, Client&, Op&, uint32_t, bool, bool);
    friend void acl_command_entry(IoLoop&, Client&, Op&);
    friend void acl_broadcast_user_change(IoLoop&, uint32_t, const AclPerm*, bool);
    friend void multi_retire_entry(IoLoop&, Client&, Op&);
    friend uint32_t multi_owner_pass_entry(IoLoop&);
    friend uint32_t multi_owner_reap_entry(IoLoop&);
    friend void multi_close_entry(IoLoop&, Client&);
    friend void multi_shutdown_entry(IoLoop&);
#include "pubsub.inc"

    template <bool HasUnix>
    void run_loop() {
        arm_accept(false);
        if constexpr (HasUnix) if (unix_listen_fd_ >= 0) arm_accept(true);
        LoopSignals& sig = self_->sig();
        while (!self_->stop_flag().load(std::memory_order_relaxed)) {
            const bool cron_armed = srv_->client_cron_armed();
            if (__builtin_expect(cron_armed, false)) {
                cached_now_ms_ = now_ns() / 1000000ull;
                cached_now_s_ = static_cast<uint32_t>(cached_now_ms_ / 1000);
                if (!client_cron_was_armed_) {
                    for (Client* c : self_->clients()) c->set_last_interaction_s(cached_now_s_);
                    client_cron_beat_ms_ = cached_now_ms_;
                }
            } else if (__builtin_expect(client_cron_was_armed_, false)) {
                // Turning the last client cron consumer off also retires output accounting once.
                // The disabled write-back specialization then has no per-serve cleanup branch.
                for (Client* c : self_->clients()) c->stop_obuf_tracking();
            }
            client_cron_was_armed_ = cron_armed;
            sig.iterations++;
            self_->sample_depth();
            reap_dead();               // free clients dead for a full iteration -- see close_client
            scatter_pool_.reap_deferred();

            uint32_t did = 0;
            {
                Span busy(sig.busy_ns);
                // A dropped accept re-arm means the server stops taking connections entirely, so it
                // is retried every pass until it lands.
                if (accept_pending_) arm_accept(false);
                if constexpr (HasUnix) if (unix_accept_pending_) arm_accept(true);
                did += ring_.for_each_cqe([&](io_uring_cqe* cqe) { on_cqe(cqe); });
                did += scatter_pool_.refresh_snapshot_floor(*srv_, self_->id());
                if constexpr (HasUnix) did += flush_handoffs();
                did += multi_owner_pass_entry(*this);
                if (srv_->snapshot().writer_is(self_->id()))
                    did += srv_->snapshot().writer_pass(*self_, ring_);
                did += flush_borrow_releases();
                did += collect_retire_work<HasUnix>();
                did += flush_ready();
                if (__builtin_expect(cron_armed && cached_now_ms_ >= client_cron_beat_ms_, false)) {
                    did += client_cron_pass();
                    client_cron_beat_ms_ = cached_now_ms_ + 100;
                }
            }
            sig.cpu_ns = thread_cpu_ns();

            // Flush prepared SQEs before looping. Recv re-arms and cross-ring wakes are
            // PREPARED during the work section but only reach the kernel on submit; taking
            // the busy path without submitting strands them in the SQ forever, and the peer
            // that is waiting on that wake never runs.
            if (did) { ring_.submit_and_reap(); continue; }

            // Nothing to do: declare intent to block, re-check (a producer may have pushed between
            // the last drain and the flag being set), then wait.
            // Mask-independent sweep before parking. The mask is a hint for the hot path; it must
            // not be the only thing that can find queued work, or one lost bit wedges a connection
            // forever. Runs only when this thread has already concluded it has nothing to do.
            if (sweep<HasUnix>()) { ring_.submit_and_reap(); continue; }

            Span idle(sig.idle_ns);
            self_->arm_blocked();
            if (!self_->any_io_inbound()) ring_.submit_and_wait(1);
            else                       ring_.submit_and_reap();
            self_->clear_blocked();
        }
    }

    // ---- submission -----------------------------------------------------------------------------
    void arm_accept(bool unix_socket) {
        io_uring_sqe* s = ring_.sqe();
        // sqe() can still return null when the submission queue is saturated. Writing through it
        // corrupts memory, and losing the accept re-arm silently stops the server taking
        // connections at all — so this is checked, counted, and retried on the next pass.
        if (!s) {
            self_->sig().sqe_starved++;
            (unix_socket ? unix_accept_pending_ : accept_pending_) = true;
            return;
        }
        io_uring_prep_multishot_accept(s, unix_socket ? unix_listen_fd_ : listen_fd_, nullptr, nullptr, 0);
        s->user_data = ur_tag(unix_socket ? UrKind::UnixAccept : UrKind::Accept, nullptr);
        ring_.note_pending();
        (unix_socket ? unix_accept_pending_ : accept_pending_) = false;
    }

    // ONE recv in flight per connection. While it is armed the kernel holds a raw pointer into the
    // read buffer, so nothing may move or realloc that buffer until the completion arrives.
    void arm_recv(Client* c) {
        if (c->recv_armed() || c->closing()) return;
        size_t avail = 0;
        // may_grow ONLY at quiescence: realloc moves the buffer that every in-flight argv Slice
        // points into. See Conn::read_space.
        char* dst = c->read_space(kRecvChunk, avail, c->rob().quiesced());
        if (!dst) return;                      // no usable space yet: let the ROB drain first
        io_uring_sqe* s = ring_.sqe();
        if (!s) { self_->sig().sqe_starved++; return; }   // retried from flush_ready next pass
        io_uring_prep_recv(s, c->fd(), dst, avail, 0);
        s->user_data = ur_tag(UrKind::Recv, c);
        ring_.note_pending();
        c->set_recv_armed(true);
    }

    // ---- completions ----------------------------------------------------------------------------
    void on_cqe(io_uring_cqe* cqe) {
        switch (ur_kind(cqe->user_data)) {
            case UrKind::Accept: on_accept(cqe, false); break;
            case UrKind::UnixAccept: on_accept(cqe, true); break;
            case UrKind::Recv:   on_recv(ur_ptr<Client>(cqe->user_data), cqe->res); break;
            case UrKind::Send: {
                Client* c = ur_ptr<Client>(cqe->user_data);
                if (c->dead()) {
                    // sendmsg's msghdr/iovecs and borrowed payload remain live through this CQE.
                    wb_.on_dead_send_complete(*c, cqe->res);
                    break;
                }
                if (!wb_.on_send_complete(*c, cqe->res)) close_client(c);
                break;
            }
            case UrKind::Wake:  self_->sig().wakes_recv++; break;
            case UrKind::SnapshotStart: break;  // epoch broadcasts target executor rings only
            case UrKind::Close: break;
        }
    }

    void on_accept(io_uring_cqe* cqe, bool unix_socket) {
        if (cqe->res < 0) {
            // Do not swallow this silently: a failing accept with no trace is indistinguishable from
            // a hung server, which is exactly how the 1024-connection failure presented.
            self_->sig().accept_err++;
            arm_accept(unix_socket);
            return;
        }
        self_->sig().accepts++;
        int fd = cqe->res;
        if (srv_->live_clients() >= srv_->maxclients()) {
            static constexpr char kErr[] = "-ERR max number of clients reached\r\n";
            (void)::send(fd, kErr, sizeof(kErr) - 1, MSG_NOSIGNAL | MSG_DONTWAIT);
            ::close(fd);
            srv_->note_rejected_conn();
            self_->sig().accept_rejected++;
            if (!(cqe->flags & IORING_CQE_F_MORE)) {
                self_->sig().accept_rearm++;
                arm_accept(unix_socket);
            }
            return;
        }
        if (__builtin_expect(srv_->protected_mode() && !srv_->requirepass_enabled() &&
                             !peer_is_local(fd, unix_socket), false)) {
            static constexpr char kDenied[] =
                "-DENIED Redis is running in protected mode because protected mode is enabled and no password is set for the default user. In this mode connections are only accepted from the loopback interface. If you want to connect from external computers to Redis you may adopt one of the following solutions: 1) Just disable protected mode sending the command 'CONFIG SET protected-mode no' from the loopback interface by connecting to Redis from the same host the server is running, however MAKE SURE Redis is not publicly accessible from internet if you do so. Use CONFIG REWRITE to make this change permanent. 2) Alternatively you can just disable the protected mode by editing the Redis configuration file, and setting the protected mode option to 'no', and then restarting the server. 3) If you started the server manually just for testing, restart it with the '--protected-mode no' option. 4) Set up an authentication password for the default user. NOTE: You only need to do one of the above things in order for the server to start accepting connections from the outside.\r\n";
            (void)::send(fd, kDenied, sizeof(kDenied) - 1, MSG_NOSIGNAL | MSG_DONTWAIT);
            ::close(fd);
            srv_->note_rejected_connection();
            self_->sig().accept_rejected++;
            if (!(cqe->flags & IORING_CQE_F_MORE)) {
                self_->sig().accept_rearm++;
                arm_accept(unix_socket);
            }
            return;
        }
        auto* c = new (std::nothrow) Client(fd);
        if (!c) {
            ::close(fd);
            self_->sig().accept_err++;
            if (!(cqe->flags & IORING_CQE_F_MORE)) {
                self_->sig().accept_rearm++;
                arm_accept(unix_socket);
            }
            return;
        }
        srv_->client_accepted();
        c->set_authenticated(!srv_->requirepass_enabled());
        c->set_acl_user_idx(kAclDefaultUser);
        c->set_id(srv_->next_client_id().fetch_add(1, std::memory_order_relaxed));
        if (unix_socket) {
            const auto& ios = srv_->placement().ifid_threads();
            const uint32_t target = ios[unix_rr_++ % ios.size()];
            c->set_ifid_thread(target);
            if (target == self_->id()) adopt_client(c, true);
            else if (!srv_->thread(target).post_client(self_->id(), c, ring_, self_->sig()))
                pending_handoffs_.push_back(c);
        } else {
            c->set_ifid_thread(self_->id());
            adopt_client(c, false);
        }
        if (!(cqe->flags & IORING_CQE_F_MORE)) {               // multishot dropped: re-arm
            self_->sig().accept_rearm++;
            arm_accept(unix_socket);
        }
    }

    std::string peer_address(int fd, bool unix_socket) const {
        if (unix_socket) return std::string(srv_->cfg().unixsocket ? srv_->cfg().unixsocket : "unix") + ":0";
        sockaddr_in peer{};
        socklen_t len = sizeof(peer);
        char ip[INET_ADDRSTRLEN] = "unknown";
        if (::getpeername(fd, reinterpret_cast<sockaddr*>(&peer), &len) == 0)
            ::inet_ntop(AF_INET, &peer.sin_addr, ip, sizeof(ip));
        char out[INET_ADDRSTRLEN + 16];
        std::snprintf(out, sizeof(out), "%s:%u", ip, ntohs(peer.sin_port));
        return out;
    }

    bool peer_is_local(int fd, bool unix_socket) const {
        if (unix_socket) return true;
        sockaddr_in peer{};
        socklen_t len = sizeof(peer);
        if (::getpeername(fd, reinterpret_cast<sockaddr*>(&peer), &len) != 0) return false;
        return (ntohl(peer.sin_addr.s_addr) & 0xff000000u) == 0x7f000000u;
    }

    void adopt_client(Client* c, bool unix_socket) {
        if (!unix_socket) {
            int one = 1;
            setsockopt(c->fd(), IPPROTO_TCP, TCP_NODELAY, &one, sizeof(one));
            const uint32_t interval = srv_->tcp_keepalive();
            if (interval) {
                setsockopt(c->fd(), SOL_SOCKET, SO_KEEPALIVE, &one, sizeof(one));
                const int idle = static_cast<int>(interval);
                const int intvl = std::max(1, idle / 3);
                const int count = 3;
                setsockopt(c->fd(), IPPROTO_TCP, TCP_KEEPIDLE, &idle, sizeof(idle));
                setsockopt(c->fd(), IPPROTO_TCP, TCP_KEEPINTVL, &intvl, sizeof(intvl));
                setsockopt(c->fd(), IPPROTO_TCP, TCP_KEEPCNT, &count, sizeof(count));
            }
        }
        c->set_last_interaction_s(cached_now_s_ ? cached_now_s_
                                                : static_cast<uint32_t>(now_ns() / 1000000000ull));
        c->set_ifid_thread(self_->id());
        // The ready-mask slot is assigned immediately: WE are the sender, for life.
        c->set_wb_slot(self_->assign_wb_slot(c));
        self_->clients().push_back(c);
        const std::string addr = peer_address(c->fd(), unix_socket);
        command_client_connected(c, addr.c_str());
        arm_recv(c);
        // Reachability, not optimism: if that arm starved for an SQE, nothing else names this
        // conn -- it would sit accepted and silent forever (audit finding). The active set's
        // phase-1 re-arms it until the recv lands; one wasted visit if the arm succeeded.
        mark_active(c);
    }

    uint32_t flush_handoffs() {
        uint32_t sent = 0;
        while (!pending_handoffs_.empty()) {
            Client* c = pending_handoffs_.front();
            ThreadCtx& target = srv_->thread(c->ifid_thread());
            if (!target.post_client(self_->id(), c, ring_, self_->sig())) break;
            pending_handoffs_.pop_front();
            sent++;
        }
        return sent;
    }

    void on_recv(Client* c, int res) {
        c->set_recv_armed(false);       // the kernel has released its pointer
        // A send error can close the fd while this recv is still owned by io_uring. The Client stays
        // alive until this CQE arrives, but it is a corpse: positive bytes must not resurrect it by
        // parsing and dispatching new Tasks after the teardown quiescence fence.
        if (c->dead()) return;
        if (res <= 0) { close_client(c); return; }
        c->commit_read(static_cast<size_t>(res));
        c->set_last_interaction_s(cached_now_s_);
        parse_and_dispatch(c);
        // Deliberately NOT re-armed here. flush_ready() re-arms AFTER it may have reset the read
        // buffer; arming first would leave the kernel holding a pointer that the reset then moves.
        mark_active(c);
    }

    // ---- parse -> route -> publish -----------------------------------------------------------------
    void parse_and_dispatch(Client* c) {
        Client& conn = *c;
        Rob<kRobWindow>& rob = c->rob();
        LoopSignals& sig = self_->sig();
        bool head_candidate = true;   // only the pass's FIRST dispatch can be the direct head
        const uint8_t security_flags = srv_->security_flags();
        const bool auth_required = (security_flags & Server::kSecurityAuth) != 0;
        const bool acl_active = (security_flags & Server::kSecurityAcl) != 0;

        for (;;) {
            if (c->scatter_barrier() || c->atomic_backpressure()) break;
            Op* op = rob.acquire();
            if (!op) break;                    // window full: backpressure; let replies drain first

            uint32_t pos = conn.rpos();
            const char* err = nullptr;
            op->rbuf_off = pos;
            const bool unauthenticated = auth_required && !conn.authenticated();
            ParseResult pr = resp_parse(conn.rbuf(), conn.rlen(), pos, *op, &err,
                                        unauthenticated ? 10 : 1024 * 1024,
                                        unauthenticated ? 16384 : 512ull * 1024 * 1024);

            if (pr == ParseResult::Incomplete) break;
            if (pr == ParseResult::Error) {
                finish_locally(c, *op, err ? err : "ERR protocol error");
                conn.advance_parse(conn.rlen() - conn.rpos());
                c->mark_closing();
                break;
            }
            // The parse cursor is deliberately NOT advanced here. It advances only once this op is
            // certain to be answered — see the dispatch-refusal path below for why.
            const uint32_t consumed = pos - conn.rpos();

            const CommandSpec* spec = command_lookup(op->cmd_name());
            if (!spec) {
                conn.advance_parse(consumed);
                finish_locally(c, *op, "ERR unknown command"); continue;
            }
            if (!command_arity_ok(*spec, op->argc())) {
                conn.advance_parse(consumed);
                char message[128];
                char command[64];
                const size_t name_len = std::min(std::strlen(spec->name), sizeof(command) - 1);
                for (size_t i = 0; i < name_len; i++) {
                    const char ch = spec->name[i];
                    command[i] = (ch >= 'A' && ch <= 'Z') ? static_cast<char>(ch + ('a' - 'A')) : ch;
                }
                command[name_len] = '\0';
                std::snprintf(message, sizeof(message),
                              "ERR wrong number of arguments for '%s' command", command);
                finish_locally(c, *op, message); continue;
            }
            op->spec = spec;
            if (__builtin_expect(unauthenticated || acl_active, false) &&
                acl_dispatch_entry(*this, conn, *op, consumed,
                                   unauthenticated, acl_active)) continue;
            if (__builtin_expect((spec->flags & CmdFlags::Transaction) != 0, false) ||
                __builtin_expect(conn.multi_session() != nullptr, false)) {
                if (multi_dispatch_entry(*this, conn, *op, consumed)) continue;
            }
            const bool config_scatter = (spec->flags & CmdFlags::ConfigRoute) &&
                                        command_config_routes_all_shards(*op);

            // RESP2 enters subscribed mode after its first subscription acknowledgement. Only the
            // Redis subscriber command set is legal until the last subscription is removed.
            const bool subscriber_mode = __builtin_expect(c->subscriber_mode(), false);
            if (subscriber_mode) {
                const bool subscription_control =
                    op->cmd_name().eq_icase("subscribe") ||
                    op->cmd_name().eq_icase("unsubscribe") ||
                    op->cmd_name().eq_icase("psubscribe") ||
                    op->cmd_name().eq_icase("punsubscribe") ||
                    op->cmd_name().eq_icase("ssubscribe") ||
                    op->cmd_name().eq_icase("sunsubscribe");
                if (op->cmd_name().eq_icase("ping")) {
                    conn.advance_parse(consumed);
                    self_->note_command(spec->id);
                    pubsub_reply_ping(*op);
                    finish_prebuilt(c, *op);
                    continue;
                }
                if (op->cmd_name().eq_icase("reset")) {
                    conn.advance_parse(consumed);
                    self_->note_command(spec->id);
                    pubsub_start_reset(c, *op);
                    sig.ops++;
                    mark_active(c);
                    break;
                }
                if (!subscription_control && !op->cmd_name().eq_icase("quit")) {
                    conn.advance_parse(consumed);
                    self_->note_command(spec->id);
                    pubsub_reply_restricted(*op);
                    finish_prebuilt(c, *op);
                    continue;
                }
            }
            if (spec->flags & CmdFlags::PubSub) {
                conn.advance_parse(consumed);
                self_->note_command(spec->id);
                const PubSubStartResult result = pubsub_start_command(c, *op);
                if (result == PubSubStartResult::Async) {
                    sig.ops++;
                    mark_active(c);
                    break;
                }
                finish_prebuilt(c, *op);
                continue;
            }

            // Connection-local commands never reach a worker — the cheapest class, and the one most
            // easily wasted by routing it anyway.
            if ((spec->flags & CmdFlags::ConnLocal) ||
                ((spec->flags & CmdFlags::ConfigRoute) && !config_scatter)) {
                conn.advance_parse(consumed);
                self_->note_command(spec->id);
                command_set_local_context(c, self_);
                snapshot_bind_io(self_, &ring_);
                const bool acl_command = __builtin_expect(op->cmd_name().eq_icase("acl"), false);
                if (acl_command)
                    acl_command_entry(*this, conn, *op);
                else
                    spec->handler(srv_->shard(0), *op);
                snapshot_bind_io(nullptr, nullptr);
                command_set_local_context(nullptr, nullptr);
                op->state.store(OpState::Done, std::memory_order_release);
                rob.publish();
                enqueue_serve(c);
                mark_active(c);
                if (c->closing() || acl_command) break;
                continue;
            }

            op->db    = static_cast<uint8_t>(c->session().db_index);
            // This command only needs an owner-local same-connection pending lookup when an older
            // cross-shard atomic group was already in flight. Set the immutable bit before the
            // current group increments the count, so a group never treats itself as a predecessor.
            if (c->has_atomic_group_io()) op->mark_atomic_hazard();

            if (spec->flags & CmdFlags::Blocking) {
                // A blocking command is a connection barrier, including against older frames.
                // Waiting to issue it until the ROB head preserves same-connection program order
                // without teaching the owner registry about younger operations.
                if (rob.in_flight() != 0) break;
                BlockingDispatch dispatch;
                const BlockingPrepare prepared = blocking_prepare(
                    *srv_, *c, *op, rob.dispatch_id(), dispatch);
                if (prepared == BlockingPrepare::Error) {
                    conn.advance_parse(consumed);
                    finish_prebuilt(c, *op);
                    continue;
                }
                uint32_t needed[kMaxThreads] = {};
                for (uint32_t i = 0; i < dispatch.nshards; i++) {
                    const int32_t sid = blocking_dispatch_shard(dispatch, i);
                    needed[srv_->worker_of_shard(sid)]++;
                }
                bool room = true;
                for (uint32_t tid = 0; tid < srv_->nthreads(); tid++) {
                    if (needed[tid] &&
                        srv_->thread(tid).task_free_slots(self_->id()) < needed[tid]) {
                        room = false;
                        break;
                    }
                }
                if (!room) {
                    blocking_destroy_unpublished(dispatch.state);
                    break;
                }
                const uint64_t op_id = rob.dispatch_id();
                op->attach_blocking_state(dispatch.state);
                blocking_start(dispatch.state, dispatch.nshards);
                rob.publish();
                for (uint32_t i = 0; i < dispatch.nshards; i++) {
                    const int32_t sid = blocking_dispatch_shard(dispatch, i);
                    const uint32_t tid = srv_->worker_of_shard(sid);
                    ThreadCtx& owner = srv_->thread(tid);
                    const Task task{c, op_id, sid,
                                    reinterpret_cast<ScatterState*>(dispatch.state)};
                    if (!owner.post_task_quiet(self_->id(), task, sig)) std::abort();
                    if (!touched_[tid]) {
                        touched_[tid] = true;
                        touched_list_[ntouched_++] = tid;
                    }
                }
                self_->note_command(spec->id);
                conn.advance_parse(consumed);
                sig.ops++;
                c->set_blocked(true);
                c->set_scatter_barrier(true);
                mark_active(c);
                break;
            }

            ScatterDispatch scatter_dispatch;
            const ScatterPrepare scatter_prepared =
                xshard_prepare(*srv_, *op, scatter_pool_, self_->id(), c->id(), scatter_dispatch,
                               false, c);
            if (scatter_prepared == ScatterPrepare::Error) {
                conn.advance_parse(consumed);
                finish_prebuilt(c, *op);
                continue;
            }
            if (scatter_prepared == ScatterPrepare::Backpressure) {
                // Leave this frame unconsumed and retry it when a window slot retires. TCP framing
                // naturally keeps younger frames behind it; no ROB-quiescence barrier is needed.
                c->set_atomic_backpressure(true);
                break;
            }
            if (scatter_prepared == ScatterPrepare::Ready) {
                // Read-only/plain scatters keep the compact V3 dispatch arm. Constructing route and
                // bundle arrays for MGET added work without helping its already-cheap individual
                // queue stores. Atomic writes take the bundled arm below, where fan-out dominates.
                if (!scatter_dispatch.atomic_write) {
                    uint32_t needed[kMaxThreads] = {};
                    for (uint32_t i = 0; i < scatter_dispatch.nshards; i++) {
                        const int32_t sid = xshard_dispatch_shard(scatter_dispatch, i);
                        needed[srv_->worker_of_shard(sid)]++;
                    }
                    bool room = true;
                    for (uint32_t tid = 0; tid < srv_->nthreads(); tid++) {
                        if (needed[tid] &&
                            srv_->thread(tid).task_free_slots(self_->id()) < needed[tid]) {
                            room = false;
                            break;
                        }
                    }
                    if (!room) {
                        xshard_destroy(scatter_dispatch.state, scatter_pool_, self_->id());
                        break;
                    }
                    const uint64_t op_id = rob.dispatch_id();
                    op->attach_scatter_state(scatter_dispatch.state);
                    rob.publish();
                    for (uint32_t i = 0; i < scatter_dispatch.nshards; i++) {
                        const int32_t sid = xshard_dispatch_shard(scatter_dispatch, i);
                        const uint32_t tid = srv_->worker_of_shard(sid);
                        ThreadCtx& owner = srv_->thread(tid);
                        const Task task{c, op_id, sid, scatter_dispatch.state};
                        if (!owner.post_task_quiet(self_->id(), task, sig)) std::abort();
                        if (!touched_[tid]) {
                            touched_[tid] = true;
                            touched_list_[ntouched_++] = tid;
                        }
                    }
                    self_->note_command(spec->id);
                    conn.advance_parse(consumed);
                    sig.ops++;
                    head_candidate = false;
                    if (scatter_dispatch.barrier) c->set_scatter_barrier(true);
                    mark_active(c);
                    continue;
                }

                uint32_t needed[kMaxThreads] = {};
                uint32_t participants[kMaxThreads];
                uint16_t routed_owner[256];
                int32_t routed_shard[256];
                uint32_t nparticipants = 0;
                for (uint32_t i = 0; i < scatter_dispatch.nshards; i++) {
                    const int32_t sid = xshard_dispatch_shard(scatter_dispatch, i);
                    const uint32_t tid = srv_->worker_of_shard(sid);
                    routed_shard[i] = sid;
                    routed_owner[i] = static_cast<uint16_t>(tid);
                    if (needed[tid]++ == 0) participants[nparticipants++] = tid;
                }
                bool room = true;
                for (uint32_t p = 0; p < nparticipants; p++) {
                    const uint32_t tid = participants[p];
                    if (srv_->thread(tid).task_free_slots(self_->id()) < needed[tid]) {
                        room = false; break;
                    }
                }
                if (!room) {
                    xshard_destroy(scatter_dispatch.state, scatter_pool_, self_->id());
                    break;
                }
                const uint64_t op_id = rob.dispatch_id();
                op->attach_scatter_state(scatter_dispatch.state);
                c->atomic_group_started();
                rob.publish();
                Task posts[256];
                uint16_t participant_begin[kMaxThreads];
                uint32_t cursor = 0;
                for (uint32_t p = 0; p < nparticipants; p++) {
                    const uint32_t tid = participants[p];
                    participant_begin[p] = static_cast<uint16_t>(cursor);
                    cursor += needed[tid];
                    needed[tid] = participant_begin[p]; // reuse as the fill cursor
                }
                for (uint32_t i = 0; i < scatter_dispatch.nshards; i++) {
                    const uint32_t tid = routed_owner[i];
                    posts[needed[tid]++] = Task{
                        c, op_id, routed_shard[i], scatter_dispatch.state};
                }
                if (cursor != scatter_dispatch.nshards) std::abort();
                for (uint32_t p = 0; p < nparticipants; p++) {
                    const uint32_t tid = participants[p];
                    const uint32_t begin = participant_begin[p];
                    const uint32_t end = p + 1 < nparticipants
                        ? participant_begin[p + 1] : scatter_dispatch.nshards;
                    ThreadCtx& owner = srv_->thread(tid);
                    // Capacity was checked before any push. Publish all of this group's tasks for
                    // one executor with one queue-tail store; the parse-pass notify remains folded.
                    if (!owner.post_tasks_quiet(
                            self_->id(), posts + begin, end - begin, sig)) std::abort();
                    if (!touched_[tid]) { touched_[tid] = true; touched_list_[ntouched_++] = tid; }
                }
                self_->note_command(spec->id); // one public command, not one count per shard task
                conn.advance_parse(consumed);
                sig.ops++;
                head_candidate = false;
                if (scatter_dispatch.barrier) c->set_scatter_barrier(true);
                mark_active(c);
                continue;
            }

            // The key position is registry metadata. OBJECT ENCODING is the first command whose
            // route key is not argv[1], and future multi-key lowering consumes the same range.
            if (spec->flags & CmdFlags::CursorShard) {
                if (!command_prepare_scan_route(*srv_, *op)) {
                    conn.advance_parse(consumed);
                    finish_prebuilt(c, *op);
                    continue;
                }
            } else if (spec->flags & CmdFlags::RandomShard) {
                uint64_t random = next_random();
                uint32_t start = static_cast<uint32_t>(random % srv_->nshards());
                uint32_t chosen = start;
                for (uint32_t n = 0; n < srv_->nshards(); n++) {
                    const uint32_t candidate = (start + n) % srv_->nshards();
                    if (srv_->shard(static_cast<int32_t>(candidate)).published_size()) {
                        chosen = candidate; break;
                    }
                }
                op->hash = random;
                op->shard = static_cast<int32_t>(chosen);
            } else {
                op->hash  = FlatStore::hash_key(op->arg(static_cast<uint32_t>(spec->first_key)));
                op->shard = srv_->router().shard_of(op->hash);
            }
            ThreadCtx& worker = srv_->thread(srv_->worker_of_shard(op->shard));

            // PUBLISH BEFORE DISPATCH. The old order posted the task first and published after, which
            // left a window of two instructions in which a worker could receive the task, execute it,
            // mark it Done and notify the sender -- all while dispatch_ still excluded the op. The
            // sender then woke, drained a ROB that did not yet contain the op, retired nothing, and
            // went back to sleep having spent its one notification. Nothing ever notified again, so
            // the reply sat Done in the ROB forever.
            //
            // It cost 3 lost replies in 87 million and wedged the connection permanently. Invisible in
            // 2-stage, where io is the sender and re-drains its own active set unprompted; it was
            // FATAL in the deleted remote-sender modes, and the ordering is kept because it is
            // simply correct: publish, then tell.
            // DIRECT-REPLY eligibility (owner's c->buf trick): this op is the ROB head and the
            // fill buffer is empty, so its bytes can be formatted in place by the worker. True for
            // every op at depth 1 and for the head of each fresh batch at depth. Evaluated ONLY for
            // the first dispatch of the pass: later ops cannot be head, and the in_flight() read
            // touches flush_, a line the sender writes -- checked per op it became a per-op
            // cross-thread load and cost -2..-4% at p32 for a candidate that can never qualify.
            if (head_candidate) {
                head_candidate = false;
                if (rob.in_flight() == 0 && c->nothing_to_write()) {
                    SmallBuf<kWbufInline>& fb = c->fill_buf();
                    op->direct     = fb.data();
                    op->direct_cap = static_cast<uint32_t>(fb.cap());
                }
            }
            Task t{c, rob.dispatch_id(), -1, nullptr};
            rob.publish();
            if (!worker.post_task_quiet(self_->id(), t, sig)) {
                rob.unpublish();          // a refused push must leave NO trace -- including in the ROB
                // A REFUSED PUSH MUST LEAVE NO TRACE. Advancing the parse cursor before this point
                // consumed the command's bytes while publishing no op, so the client waited forever
                // for a reply that would never be produced and the connection wedged. This is not an
                // edge case: with enough io threads feeding few workers the inbox fills routinely,
                // and it hung a benchmark within seconds at io6/ex2. Leaving the cursor untouched
                // means the command is simply re-parsed on a later pass, once retiring has freed
                // inbox space.
                break;
            }
            conn.advance_parse(consumed);
            sig.ops++;
            {
                const uint32_t wkr = static_cast<uint32_t>(srv_->worker_of_shard(op->shard));
                if (!touched_[wkr]) { touched_[wkr] = true; touched_list_[ntouched_++] = wkr; }
            }
            mark_active(c);
        }
        // Item 2: one notify per worker per parse pass, not per op. The pushes above are already
        // visible in the queues; this publishes the "look here" bit and pays the wake decision once.
        // The touched set is a LIST, not a scan: the first version swept all 128 thread slots per
        // pass, which at p1 is 128 loads per op and measured -2.5% -- the batching win eaten by its
        // own bookkeeping.
        for (uint32_t i = 0; i < ntouched_; i++) {
            const uint32_t wkr = touched_list_[i];
            touched_[wkr] = false;
            srv_->thread(wkr).flush_task_notify(self_->id(), ring_, sig);
        }
        ntouched_ = 0;
    }

    void finish_locally(Client* c, Op& op, const char* err) {
        reply_err(op.reply, err);
        finish_prebuilt(c, op);
    }

    void finish_prebuilt(Client* c, Op& op) {
        op.state.store(OpState::Done, std::memory_order_release);
        c->rob().publish();
        enqueue_serve(c);
        mark_active(c);
    }

    uint64_t next_random() {
        random_state_ ^= random_state_ << 13;
        random_state_ ^= random_state_ >> 7;
        random_state_ ^= random_state_ << 17;
        return random_state_;
    }

    void mark_active(Client* c) {
        if (c->dead()) return;               // a corpse from the deferred-free list: entry consumed, nothing to do
        if (c->in_active()) return;          // one load, not a scan of the whole set
        c->set_in_active(true);
        active_.insert(c);
    }

    // ---- inbound: workers telling us a client has completed ops -----------------------------------
    // Inbound from workers: "ops are Done" -- the claimed-post fallback for a conn with no
    // ready-mask slot. Either way the answer is the same: put the client back in the active set.
    template <bool HasUnix>
    uint32_t sweep() {
        uint32_t work = 0;
        if constexpr (HasUnix) work += flush_handoffs();
        work += flush_borrow_releases() + collect_retire_work<HasUnix>(true) + flush_ready();
        if (srv_->snapshot().writer_is(self_->id()))
            work += srv_->snapshot().writer_pass(*self_, ring_, true);
        return work;
    }

    void queue_borrow_release(int32_t shard, const char* ptr) {
        pending_releases_.push_back(BorrowRelease{shard, ptr});
        flush_borrow_releases();
    }

    uint32_t flush_borrow_releases() {
        uint32_t n = 0;
        while (!pending_releases_.empty()) {
            const BorrowRelease r = pending_releases_.front();
            ThreadCtx& owner = srv_->thread(srv_->worker_of_shard(r.shard));
            if (!owner.post_release(self_->id(), r, ring_, self_->sig())) break;
            pending_releases_.pop_front();
            n++;
        }
        return n;
    }

    template <bool HasUnix>
    uint32_t collect_retire_work(bool unmasked = false) {
        uint32_t pubsub_work = 0;
        auto take = [&](Client* c) {
            if (!c) {
                pubsub_work += pubsub_drain_events();
                return;
            }
            // AF_UNIX accept handoffs use this existing channel without claiming retirement.
            // Executor completions always CAS retire_queued false->true before posting, so the bit
            // distinguishes the two meanings without adding a Client field or a catalog lock here.
            if constexpr (HasUnix)
                if (!c->retire_queued().load(std::memory_order_acquire)) {
                    adopt_client(c, true);
                    return;
                }
            c->retire_queued().store(false, std::memory_order_release);
            enqueue_serve(c);                    // a posted client is a serve request
            mark_active(c);
        };
        uint32_t n = unmasked ? self_->drain_clients_unmasked(take) : self_->drain_clients(take);
        // The ready-mask path: workers set one bit per completed-work burst; we map slot -> client,
        // flag it FOR SERVING, and put it back in the active set. The flag is the point: serving
        // every active conn every pass measured 93% EMPTY serves at 8 nodes -- 526M drain-checks
        // that each pulled a remote worker's cache line to learn there was nothing to do. Targeted
        // serving turns the poll into a response.
        for (uint32_t w = 0; w < ReadyMask::kWords; w++) {
            uint64_t bits = self_->ready().take(w);
            while (bits) {
                const uint32_t b = static_cast<uint32_t>(__builtin_ctzll(bits));
                bits &= bits - 1;
                Client* c = self_->wb_slot_client(w * 64 + b);
                if (c && !c->dead()) { enqueue_serve(c); mark_active(c); n++; }
            }
        }
        return n + pubsub_work;
    }

    // ---- retire -> stage bytes -> send or hand off -------------------------------------------------
    // The io thread's own work per active client. In 2-stage it also owns the reply side and calls
    // serve() here; in ex-wb and 3-stage the sender does that on its own thread and io only keeps
    // the READ side moving — reclaim the buffer once nothing points into it, and re-arm.
    uint32_t flush_ready() {
        uint32_t work = 0;
        backstop_pass_ = (++flush_tick_ >= kFlushBackstopEvery);
        if (backstop_pass_) flush_tick_ = 0;

        // PHASE 1 -- the read side, every active conn, BEFORE any serving. At 2048 conns the old
        // interleaved pass collapsed loop iterations 7.5x: each pass walked ~100 conns doing serve
        // and send work while drained recvs sat un-armed, sockets backed up, and arrivals went
        // bursty (113k park/wake round-trips where 22k belonged). Arming first keeps the arrival
        // stream flowing no matter how deep the reply backlog is -- which is exactly the property
        // that made 3s hold flat (-3.7%) at the conn count where 2s lost 21%.
        for (auto it = active_.begin(); it != active_.end();) {
            Client* c = *it;
            Client& conn = *c;
            if (backstop_pass_ && !c->serve_pending()) enqueue_serve(c);

            // Reset only when the ROB is quiescent AND no recv is outstanding — see conn.h. Then
            // re-arm, in that order.
            if (c->scatter_barrier()) {
                if (c->blocked() &&
                    blocking_resume_move(*srv_, *self_, ring_, *c, scatter_pool_)) {
                    enqueue_serve(c);
                    work++;
                }
                if (c->rob().quiesced()) c->set_scatter_barrier(false);
            }
            if (c->atomic_backpressure() && srv_->atomic_can_admit(self_->id()) &&
                scatter_pool_.can_register_snapshot())
                c->set_atomic_backpressure(false);
            if (c->rob().quiesced() && !conn.recv_armed()) conn.reset_rbuf_at_quiescence();

            // Re-parse the buffered remainder. parse_and_dispatch stops when the ROB window fills
            // and is otherwise only driven by recv completions, so a client that sent a whole
            // pipeline in ONE write would get `window` replies and then hang. Retiring frees slots,
            // which is what makes the rest parseable.
            if (!c->closing() && conn.rpos() < conn.rlen() && !c->scatter_barrier() &&
                !c->atomic_backpressure()) {
                parse_and_dispatch(c);
                work++;
            }

            arm_recv(c);

            // Progress marker: a full window with unparsed bytes (or an unarmed recv) means this
            // conn must stay active so later passes retry once retiring frees slots. We are our own
            // sender, so no poke protocol is needed -- the flush_ready pass IS the retry.
            const bool stuck = (conn.rpos() < conn.rlen() && c->rob().full()) ||
                               (!conn.recv_armed() && !c->closing());

            const bool more_input = conn.rpos() < conn.rlen();
            const bool done = c->rob().quiesced() && !more_input && !stuck && !c->serve_pending() &&
                              c->nothing_to_write();
            if (done && !c->closing()) { c->set_in_active(false); it = active_.erase(it); }
            else if (c->closing() && c->safe_to_release()) {
                // Pub/sub teardown is asynchronous. Keep the client in place while home IOs
                // acknowledge removal; erase+reinsert would invalidate this vector iterator and
                // can turn one closing subscriber into a same-pass spin.
                if (!pubsub_disconnect_ready(c)) { ++it; }
                else { c->set_in_active(false); it = active_.erase(it); close_client(c); }
            } else ++it;
        }

        // PHASE 2 -- serve AT MOST kServeBudget conns from the FIFO. Bounding the pass is the
        // fourth application of the same law (per-pass work scales with what the pass does, not
        // with connection count): the leftovers stay queued, did > 0 keeps the loop from parking,
        // and FIFO order is arrival-order fairness across connections. Under overload the queue is
        // the latency -- which is the correct place for overload to live; throughput stays at peak.
        uint32_t served = 0;
        while (served < kServeBudget && !pending_serve_.empty()) {
            Client* c = pending_serve_.front();
            pending_serve_.pop_front();
            c->set_serve_pending(false);
            // Closing conns MUST still be served -- their ROB has to drain before quiesce can let
            // close_client finish. Only corpses (freed-pending) are skippable.
            if (c->dead()) continue;
            served++;
            if (wb_.serve(*c)) work++;
        }
        work += served;
        return work;
    }

    void enqueue_serve(Client* c) {
        if (c->serve_pending()) return;                 // already queued
        c->set_serve_pending(true);
        pending_serve_.push_back(c);
    }

    bool client_obuf_check(Client* c, bool async) {
        if (c->closing() || c->dead()) return false;
        if (!srv_->client_obuf_armed()) {
            c->stop_obuf_tracking();
            return false;
        }
        c->start_obuf_tracking();
        const ClientLimitsConfigSnapshot limits = srv_->client_limits_snapshot();
        const ClientBufferLimit& limit = c->subscriber_mode() ? limits.pubsub : limits.normal;
        const uint64_t used = c->obuf_bytes();
        bool over = limit.hard_bytes && used >= limit.hard_bytes;
        if (!over && limit.soft_bytes && used >= limit.soft_bytes) {
            if (!c->obuf_soft_since_s()) c->set_obuf_soft_since_s(cached_now_s_);
            else if (cached_now_s_ - c->obuf_soft_since_s() > limit.soft_seconds) over = true;
        } else if (!over) {
            c->set_obuf_soft_since_s(0);
        }
        if (!over) return false;

        srv_->note_client_output_buffer_limit_disconnect();
        if (async)
            std::fprintf(stderr,
                "Client id=%llu scheduled to be closed ASAP for overcoming of output buffer limits.\n",
                static_cast<unsigned long long>(c->id()));
        else
            std::fprintf(stderr,
                "Client id=%llu closed for overcoming of output buffer limits.\n",
                static_cast<unsigned long long>(c->id()));
        close_client(c);
        return true;
    }

    uint32_t client_cron_pass() {
        auto& clients = self_->clients();
        const size_t initial = clients.size();
        if (!initial) { client_cron_cursor_ = 0; return 0; }
        size_t visits = initial / kClientCronBeatsPerSecond;
        if (visits < kClientCronMinVisits)
            visits = std::min(initial, static_cast<size_t>(kClientCronMinVisits));

        const uint32_t timeout = srv_->timeout();
        uint32_t work = 0;
        for (size_t visited = 0; visited < visits && !clients.empty(); visited++) {
            if (client_cron_cursor_ >= clients.size()) client_cron_cursor_ = 0;
            Client* c = clients[client_cron_cursor_];
            const size_t before = clients.size();
            bool closed = false;
            if (timeout && !c->blocked() && !c->subscriber_mode() && !c->closing() &&
                cached_now_s_ - c->last_interaction_s() > timeout) {
                close_client(c);
                closed = true;
            } else if (client_obuf_check(c, false)) {
                closed = true;
            }
            work++;
            // close_client removes by swap-with-back. Revisit this index so the swapped-in client
            // is not skipped; if teardown is still pending, advance past the unchanged entry.
            if (!closed || clients.size() == before) client_cron_cursor_++;
        }
        return work;
    }

    void close_client(Client* c) {
        // IDEMPOTENT, and that is load-bearing: an abrupt disconnect can close a conn twice --
        // once when the recv fails and again when the in-flight reply's send CQE comes back
        // failed. The second call found the client already parked on the deferred-free list and
        // parked it AGAIN: a double delete, one reap later. Caught by the torture battery's RST
        // churn under ASAN; latent since the first teardown path was written.
        if (c->dead()) return;
        if (!c->closing()) {
            c->mark_closing();
            if (c->blocked() && blocking_cancel_client(*srv_, *self_, ring_, *c))
                enqueue_serve(c);
            // Break any in-flight recv/send NOW: safe_to_release refuses to free while the kernel
            // holds a buffer pointer (recv_armed / send_inflight), and those only clear when their
            // CQEs come back -- which a half-open peer might never trigger on its own.
            ::shutdown(c->fd(), SHUT_RDWR);
        }
        multi_close_entry(*this, *c);
        // Release only at the quiescence fence: a worker may still hold a Task that resolves through
        // this ROB. Anything else is a use-after-free under pipelining. (The retryable wait paths,
        // with their mark_active leak guard, are below.)
        if (!pubsub_disconnect_ready(c)) { mark_active(c); return; }
        c->set_in_active(false);
        active_.erase(c);
        auto& v = self_->clients();
        for (size_t i = 0; i < v.size(); i++)
            if (v[i] == c) { v[i] = v.back(); v.pop_back(); break; }
        // THE RETRY IS THE LOAD-BEARING PART of this wait: the client left the active set when it
        // went quiet, so nothing revisits it unless mark_active puts it back -- returning without
        // doing so leaked the entire client (~137KB) per disconnect once. Only a quiesced,
        // claim-free conn may release its slot and die.
        if (!c->safe_to_release()) { mark_active(c); return; }
        command_client_disconnected(c);
        self_->release_wb_slot(c->wb_slot());
        c->set_wb_slot(Client::kNoWbSlot);
        wb_.teardown(*c);
        ::close(c->fd());
        srv_->client_released();
        // NOT delete. An ex-side claimed post may still sit un-consumed in our inbound channels
        // naming this client. Every such entry was pushed BEFORE this point, and channels are FIFO
        // with their mask bits set -- so ONE full
        // collect_retire_work pass consumes all of them. Park the corpse for one loop iteration and
        // free it at the top of the one after; the drain lambda skips dead clients.
        c->mark_dead();
        dead_next_.push_back(c);
    }

    // Free everything that has been dead for a full iteration. Called once per loop pass, BEFORE
    // this pass's drains, so a corpse parked in pass N is freed in pass N+2's prologue -- after the
    // whole of pass N+1 (including its channel drains) ran with the corpse still readable.
    void reap_dead() {
        // Hold a corpse while ANY outside reference can still surface: a pending_serve_ FIFO
        // entry (the budget serves 16/pass, so an entry can outlive two prologues -- audit
        // finding), or a kernel CQE not yet reaped (a send pins msghdr/iovecs/BORROWs; a recv
        // pins the buffer and the Client* in its user_data). Two prologues are the minimum grace;
        // these fences extend it exactly as long as a reference exists. teardown() before delete
        // returns any BORROW the close path could not (idempotent: release_all empties the queue).
        size_t keep = 0;
        for (Client* c : dead_ready_) {
            if (c->serve_pending() || c->send_inflight() || c->recv_armed()) {
                dead_ready_[keep++] = c;
                continue;
            }
            wb_.teardown(*c);
            delete c;
        }
        dead_ready_.resize(keep);
        dead_ready_.insert(dead_ready_.end(), dead_next_.begin(), dead_next_.end());
        dead_next_.clear();
    }

    Server*    srv_  = nullptr;
    ThreadCtx* self_ = nullptr;
    static constexpr uint32_t kFlushBackstopEvery = 64;
    // Serves per pass. Sized so a pass's serve work stays comparable to its recv work: ~16 serves
    // x a ~32-op prefix each is one CQ batch worth of replies. The queue, not the pass, absorbs
    // overload.
    static constexpr uint32_t kServeBudget = 16;
    std::deque<Client*> pending_serve_;
    std::deque<BorrowRelease> pending_releases_;
    std::deque<Client*> pending_handoffs_;
    ScatterArenaPool scatter_pool_;          // touched only by this connection-owning IO thread
    uint32_t flush_tick_ = 0;
    bool     backstop_pass_ = false;
    static constexpr uint32_t kClientCronBeatsPerSecond = 10;
    static constexpr uint32_t kClientCronMinVisits = 5;
    uint64_t client_cron_beat_ms_ = 0;
    size_t   client_cron_cursor_ = 0;
    uint64_t cached_now_ms_ = 0;
    uint32_t cached_now_s_ = 0;
    bool     client_cron_was_armed_ = false;
    bool touched_[kMaxThreads] = {};      // dedupe flags for the current parse pass
    uint32_t touched_list_[kMaxThreads] = {}; // the workers actually fed, dense
    uint32_t ntouched_ = 0;
    std::vector<Client*> dead_next_;   // corpses parked this iteration
    std::vector<Client*> dead_ready_;  // corpses freed at the next prologue
    int        listen_fd_ = -1;
    int        unix_listen_fd_ = -1;
    Ring       ring_;
    WbEngine   wb_;
    bool       accept_pending_ = false;
    bool       unix_accept_pending_ = false;
    uint64_t   unix_rr_ = 0;
    uint64_t   random_state_ = 0x9e3779b97f4a7c15ULL;

    // Clients with work outstanding. Populated by dispatch and by the retire channel, never by
    // scanning every client: at 10k+ connections that scan dominates the loop.
    struct PtrSet {
        using It = std::vector<Client*>::iterator;
        std::vector<Client*> v;
        void insert(Client* c) { v.push_back(c); }
        It   begin() { return v.begin(); }
        It   end()   { return v.end(); }
        // Swap-with-back rather than vector::erase: order in the active set carries no meaning, and
        // erase() shifts every element after the removed one.
        It   erase(It it) { *it = v.back(); v.pop_back(); return it; }
        void erase(Client* c) {
            for (size_t i = 0; i < v.size(); i++)
                if (v[i] == c) { v[i] = v.back(); v.pop_back(); return; }
        }
    } active_;
    std::vector<MultiExecState*> multi_deferred_;
    std::deque<MultiExecState*> pending_multi_cleanups_;
};

}  // namespace tomo
