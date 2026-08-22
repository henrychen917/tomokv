// io_loop.h — the IO stage. Accepts, receives, parses, routes, publishes, retires, and (in Io mode)
// sends.
//
// WHAT MOVES BETWEEN MODES, AND WHAT DOES NOT. The ROB is ALWAYS drained by the IO thread that owns
// the connection, in every mode. Only the send syscall moves. That is a deliberate narrowing:
//
//   - The ROB's producer side (acquire/publish) is the parser, which is this thread. Letting another
//     thread also retire from it would make dispatch_id/flush_id a cross-thread pair and put the
//     window accounting into a race for no measured benefit.
//   - The question the Ex and Wb modes exist to answer is "does it help to have a different thread
//     issue the send?" — and staging bytes here while another thread issues the write tests exactly
//     that.
//
// It is therefore NOT a byte-for-byte reproduction of the fork's ex-wb, which had the executor build
// and send its own contiguous ready prefix without returning to IO. Saying so here so nobody later
// reads a result from this mode as a verdict on that design.
#pragma once
#include <netinet/in.h>
#include <netinet/tcp.h>
#include <sys/socket.h>
#include <unistd.h>
#include <cstdio>
#include <vector>
#include "server.h"
#include "../net/conn.h"
#include "../net/resp.h"
#include "../net/uring.h"
#include "../net/wb.h"
#include "../cmd/command.h"

namespace tomo {

inline constexpr uint32_t kRecvChunk = 16 * 1024;

class IoLoop {
public:
    bool init(Server* srv, ThreadCtx* self, WbMode mode, int listen_fd) {
        srv_ = srv; self_ = self; listen_fd_ = listen_fd;
        if (!ring_.init(4096)) return false;
        wb_.bind(&ring_, mode);
        return true;
    }

    Ring& ring() { return ring_; }

    // In Ex/Wb modes, where this thread stages bytes but another issues the send.
    void set_send_target(ReadyQueue* q, Ring* target_ring) {
        send_q_ = q; target_ring_ = target_ring;
    }

    void run() {
        arm_accept();
        while (!self_->stop_flag().load(std::memory_order_relaxed)) {
            ring_.submit_and_wait(1);
            ring_.for_each_cqe([&](io_uring_cqe* cqe) { on_cqe(cqe); });
            // A worker that finished an op wakes this ring, so by the time we get here some ROBs may
            // have completed entries. Retiring is O(clients with work), not O(all clients).
            flush_ready();
            self_->stats().loop_spins++;
        }
    }

private:
    // ---- submission -----------------------------------------------------------------------------
    void arm_accept() {
        io_uring_sqe* s = ring_.sqe();
        io_uring_prep_multishot_accept(s, listen_fd_, nullptr, nullptr, 0);
        s->user_data = ur_tag(UrKind::Accept, nullptr);
        ring_.note_pending();
    }

    void arm_recv(Client* c) {
        size_t avail = 0;
        char* dst = c->conn().read_space(kRecvChunk, avail);
        if (!dst) return;                      // soft cap hit: stop reading until the ROB drains
        io_uring_sqe* s = ring_.sqe();
        io_uring_prep_recv(s, c->conn().fd(), dst, avail, 0);
        s->user_data = ur_tag(UrKind::Recv, c);
        ring_.note_pending();
    }

    // ---- completions ----------------------------------------------------------------------------
    void on_cqe(io_uring_cqe* cqe) {
        switch (ur_kind(cqe->user_data)) {
            case UrKind::Accept: on_accept(cqe); break;
            case UrKind::Recv:   on_recv(ur_ptr<Client>(cqe->user_data), cqe->res); break;
            case UrKind::Send: {
                Client* c = ur_ptr<Client>(cqe->user_data);
                if (!wb_.on_send_complete(*c, c->wb(), cqe->res)) close_client(c);
                break;
            }
            case UrKind::Wake:  break;         // a worker poked us; flush_ready() does the work
            case UrKind::Close: break;
        }
    }

    void on_accept(io_uring_cqe* cqe) {
        if (cqe->res < 0) { arm_accept(); return; }
        int fd = cqe->res;
        int one = 1;
        setsockopt(fd, IPPROTO_TCP, TCP_NODELAY, &one, sizeof(one));

        auto* c = new Client(fd);
        c->set_id(srv_->next_client_id().fetch_add(1, std::memory_order_relaxed));
        c->set_io_thread(self_->id());
        self_->clients().push_back(c);
        arm_recv(c);

        // Multishot re-arms itself; if the kernel dropped it, arm again.
        if (!(cqe->flags & IORING_CQE_F_MORE)) arm_accept();
    }

    void on_recv(Client* c, int res) {
        if (res <= 0) { close_client(c); return; }
        c->conn().commit_read(static_cast<size_t>(res));
        parse_and_dispatch(c);
        if (!c->closing()) arm_recv(c);
    }

    // ---- parse -> route -> publish ----------------------------------------------------------------
    void parse_and_dispatch(Client* c) {
        Conn& conn = c->conn();
        Rob<kRobWindow>& rob = c->rob();

        for (;;) {
            Op* op = rob.acquire();
            if (!op) break;                    // window full: backpressure, let replies drain first

            uint32_t pos = conn.rpos();
            const char* err = nullptr;
            op->rbuf_off = pos;
            ParseResult pr = resp_parse(conn.rbuf(), conn.rlen(), pos, *op, &err);

            if (pr == ParseResult::Incomplete) break;
            if (pr == ParseResult::Error) {
                reply_err(op->reply, err ? err : "ERR protocol error");
                op->state.store(OpState::Done, std::memory_order_release);
                rob.publish();
                conn.advance_parse(conn.rlen() - conn.rpos());   // resync by discarding
                c->mark_closing();
                break;
            }
            conn.advance_parse(pos - conn.rpos());

            const CommandSpec* spec = command_lookup(op->cmd_name());
            if (!spec) {
                reply_err(op->reply, "ERR unknown command");
                op->state.store(OpState::Done, std::memory_order_release);
                rob.publish();
                continue;
            }
            if ((spec->arity >= 0 && static_cast<int32_t>(op->argc()) != spec->arity) ||
                (spec->arity <  0 && static_cast<int32_t>(op->argc()) < -spec->arity)) {
                reply_err(op->reply, "ERR wrong number of arguments");
                op->state.store(OpState::Done, std::memory_order_release);
                rob.publish();
                continue;
            }
            op->spec = spec;

            // Connection-local commands never reach a worker — that is the cheapest class and the
            // one most easily wasted by routing it anyway.
            if (spec->flags & CmdFlags::ConnLocal) {
                spec->handler(srv_->shard(0), *op);           // shard unused for this class
                op->state.store(OpState::Done, std::memory_order_release);
                rob.publish();
                continue;
            }

            op->hash  = FlatStore::hash_key(op->key());
            op->shard = srv_->router().shard_of(op->hash);
            const uint32_t worker = srv_->worker_of_shard(op->shard);

            Task t{c, rob.dispatch_id()};
            if (!srv_->thread(worker).inbox(self_->id()).push(t)) {
                // NEVER drop a full queue on the floor: the reply would be lost and the connection
                // would wedge waiting for it. That exact bug shipped in the fork.
                self_->stats().queue_full++;
                break;                                          // leave the op unpublished; retry later
            }
            rob.publish();
            self_->stats().ops_dispatched++;
            if (!active_.count(c)) { active_.insert(c); }
        }
    }

    // ---- retire -> stage bytes -> send or hand off ------------------------------------------------
    void flush_ready() {
        for (auto it = active_.begin(); it != active_.end();) {
            Client* c = *it;
            Conn& conn = c->conn();
            const uint32_t n = c->rob().drain([&](Op& op) {
                conn.wbuf().append(op.reply.data(), op.reply.size());
            });
            if (n) self_->stats().replies_sent += n;

            if (c->rob().quiesced()) conn.reset_rbuf_at_quiescence();

            if (conn.wbuf().size() > conn.wsent()) {
                if (wb_.mode() == WbMode::Io) {
                    wb_.pump(*c, c->wb());                       // this thread sends
                } else {
                    handoff(c);                                  // another thread sends
                }
            }
            if (c->rob().quiesced() && conn.write_drained()) it = active_.erase(it);
            else ++it;
        }
    }

    void handoff(Client* c) {
        bool expected = false;
        if (!c->wb().queued.compare_exchange_strong(expected, true, std::memory_order_acq_rel))
            return;                                              // already queued; do not double-enqueue
        if (!send_q_ || !send_q_->push(c)) {
            c->wb().queued.store(false, std::memory_order_release);
            return;
        }
        wb_.stats().handoffs++;
        if (target_ring_) ring_.msg_to(*target_ring_, ur_tag(UrKind::Wake, nullptr));
    }

    void close_client(Client* c) {
        c->mark_closing();
        // A connection may only be released at the quiescence fence: a worker may still hold a Task
        // that resolves through this ROB. Anything else is a use-after-free under pipelining.
        if (!c->safe_to_release()) return;
        active_.erase(c);
        auto& v = self_->clients();
        for (size_t i = 0; i < v.size(); i++)
            if (v[i] == c) { v[i] = v.back(); v.pop_back(); break; }
        ::close(c->conn().fd());
        delete c;
    }

    Server*     srv_ = nullptr;
    ThreadCtx*  self_ = nullptr;
    int         listen_fd_ = -1;
    Ring        ring_;
    WbEngine    wb_;
    ReadyQueue* send_q_ = nullptr;       // Ex/Wb modes
    Ring*       target_ring_ = nullptr;

    // Clients with work outstanding. Deliberately not a scan of every client per iteration: at
    // 10k+ connections that scan is the loop's dominant cost.
    struct PtrSet {
        std::vector<Client*> v;
        bool count(Client* c) const { for (auto* p : v) if (p == c) return true; return false; }
        void insert(Client* c) { v.push_back(c); }
        using It = std::vector<Client*>::iterator;
        It   begin() { return v.begin(); }
        It   end()   { return v.end(); }
        It   erase(It it) { return v.erase(it); }
        void erase(Client* c) { for (size_t i = 0; i < v.size(); i++) if (v[i] == c) { v.erase(v.begin() + i); return; } }
    } active_;
};

}  // namespace tomo
