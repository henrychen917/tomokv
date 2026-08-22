// io_loop.h — the IO stage. Accepts, receives, parses, routes, publishes, retires, and (in Io mode)
// sends.
//
// EVERY CROSS-THREAD SIGNAL HERE IS A Channel, and every measurement is a LoopSignals field, so this
// loop is comparable with the EX and WB loops through one interface. See signal.h.
//
//   out  task_in of the shard's owner        a parsed op to execute
//   in   client_in from workers              "you have completed ops to retire"
//   out  client_in of the sender             "you have bytes to write"   (Ex and Wb modes)
//
// WHAT MOVES BETWEEN MODES, AND WHAT DOES NOT. The ROB is ALWAYS drained by the IO thread that owns
// the connection, in every mode. Only the send syscall moves. Letting a second thread retire from
// the ROB would make dispatch_id/flush_id a cross-thread pair for no measured benefit. So this is
// NOT a byte-for-byte reproduction of the fork's ex-wb, which had the executor build and send its
// own contiguous ready prefix without returning to IO — said here so no result from that mode is
// misread as a verdict on that design.
#pragma once
#include <arpa/inet.h>
#include <netinet/in.h>
#include <netinet/tcp.h>
#include <sys/socket.h>
#include <unistd.h>
#include <cstdio>
#include <cstdlib>
#include <vector>
#include "server.h"
#include "signal.h"
#include "../net/conn.h"
#include "../net/resp.h"
#include "../net/uring.h"
#include "../net/wb.h"
#include "../cmd/command.h"

namespace tomo {

inline constexpr uint32_t kRecvChunk = 16 * 1024;

class IoLoop {
public:
    WbEngine& engine() { return wb_; }
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
    bool init(Server* srv, ThreadCtx* self, WbMode mode, const char* addr, uint16_t port) {
        srv_ = srv; self_ = self;
        listen_fd_ = make_reuseport_listener(addr, port);
        if (listen_fd_ < 0) return false;
        if (!ring_.init(4096)) return false;
        self_->set_ring(&ring_);
        wb_.bind(&ring_, mode);
        return true;
    }

    ~IoLoop() { if (listen_fd_ >= 0) ::close(listen_fd_); }

    static int make_reuseport_listener(const char* addr, uint16_t port) {
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
        // Backlog must hold a benchmark's whole opening burst; capped by net.core.somaxconn anyway.
        if (::listen(fd, 16384) != 0) { ::close(fd); return -1; }
        return fd;
    }

    Ring& ring() { return ring_; }

    // Ex/Wb modes: this thread stages ordered bytes, `sender` issues the write.
    void set_send_target(ThreadCtx* sender) { sender_ = sender; }

    void run() {
        arm_accept();
        LoopSignals& sig = self_->sig();
        while (!self_->stop_flag().load(std::memory_order_relaxed)) {
            sig.iterations++;
            self_->sample_depth();

            uint32_t did = 0;
            {
                Span busy(sig.busy_ns);
                // A dropped accept re-arm means the server stops taking connections entirely, so it
                // is retried every pass until it lands.
                if (accept_pending_) arm_accept();
                did += ring_.for_each_cqe([&](io_uring_cqe* cqe) { on_cqe(cqe); });
                did += collect_retire_work();
                did += flush_ready();
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
            if (sweep()) { ring_.submit_and_reap(); continue; }

            Span idle(sig.idle_ns);
            self_->arm_blocked();
            if (!self_->any_inbound()) ring_.submit_and_wait(1);
            else                       ring_.submit_and_reap();
            self_->clear_blocked();
        }
    }

private:
    // ---- submission -----------------------------------------------------------------------------
    void arm_accept() {
        io_uring_sqe* s = ring_.sqe();
        // sqe() can still return null when the submission queue is saturated. Writing through it
        // corrupts memory, and losing the accept re-arm silently stops the server taking
        // connections at all — so this is checked, counted, and retried on the next pass.
        if (!s) { self_->sig().sqe_starved++; accept_pending_ = true; return; }
        io_uring_prep_multishot_accept(s, listen_fd_, nullptr, nullptr, 0);
        s->user_data = ur_tag(UrKind::Accept, nullptr);
        ring_.note_pending();
        accept_pending_ = false;
    }

    // ONE recv in flight per connection. While it is armed the kernel holds a raw pointer into the
    // read buffer, so nothing may move or realloc that buffer until the completion arrives.
    void arm_recv(Client* c) {
        if (c->conn().recv_armed() || c->closing()) return;
        size_t avail = 0;
        // may_grow ONLY at quiescence: realloc moves the buffer that every in-flight argv Slice
        // points into. See Conn::read_space.
        char* dst = c->conn().read_space(kRecvChunk, avail, c->rob().quiesced());
        if (!dst) return;                      // no usable space yet: let the ROB drain first
        io_uring_sqe* s = ring_.sqe();
        if (!s) { self_->sig().sqe_starved++; return; }   // retried from flush_ready next pass
        io_uring_prep_recv(s, c->conn().fd(), dst, avail, 0);
        s->user_data = ur_tag(UrKind::Recv, c);
        ring_.note_pending();
        c->conn().set_recv_armed(true);
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
            case UrKind::Wake:  self_->sig().wakes_recv++; break;
            case UrKind::Close: break;
        }
    }

    void on_accept(io_uring_cqe* cqe) {
        if (cqe->res < 0) {
            // Do not swallow this silently: a failing accept with no trace is indistinguishable from
            // a hung server, which is exactly how the 1024-connection failure presented.
            self_->sig().accept_err++;
            arm_accept();
            return;
        }
        self_->sig().accepts++;
        int fd = cqe->res, one = 1;
        setsockopt(fd, IPPROTO_TCP, TCP_NODELAY, &one, sizeof(one));

        auto* c = new Client(fd);
        c->set_id(srv_->next_client_id().fetch_add(1, std::memory_order_relaxed));
        c->set_io_thread(self_->id());
        c->set_sender_thread(sender_ ? sender_->id() : self_->id());
        self_->clients().push_back(c);
        arm_recv(c);
        if (!(cqe->flags & IORING_CQE_F_MORE)) {               // multishot dropped: re-arm
            self_->sig().accept_rearm++;
            arm_accept();
        }
    }

    void on_recv(Client* c, int res) {
        c->conn().set_recv_armed(false);       // the kernel has released its pointer
        if (res <= 0) { close_client(c); return; }
        c->conn().commit_read(static_cast<size_t>(res));
        parse_and_dispatch(c);
        // Deliberately NOT re-armed here. flush_ready() re-arms AFTER it may have reset the read
        // buffer; arming first would leave the kernel holding a pointer that the reset then moves.
        mark_active(c);
    }

    // ---- parse -> route -> publish -----------------------------------------------------------------
    void parse_and_dispatch(Client* c) {
        Conn& conn = c->conn();
        Rob<kRobWindow>& rob = c->rob();
        LoopSignals& sig = self_->sig();

        for (;;) {
            Op* op = rob.acquire();
            if (!op) break;                    // window full: backpressure; let replies drain first

            uint32_t pos = conn.rpos();
            const char* err = nullptr;
            op->rbuf_off = pos;
            ParseResult pr = resp_parse(conn.rbuf(), conn.rlen(), pos, *op, &err);

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
            const int32_t argc = static_cast<int32_t>(op->argc());
            if ((spec->arity >= 0 && argc != spec->arity) || (spec->arity < 0 && argc < -spec->arity)) {
                conn.advance_parse(consumed);
                finish_locally(c, *op, "ERR wrong number of arguments"); continue;
            }
            op->spec = spec;

            // Connection-local commands never reach a worker — the cheapest class, and the one most
            // easily wasted by routing it anyway.
            if (spec->flags & CmdFlags::ConnLocal) {
                conn.advance_parse(consumed);
                spec->handler(srv_->shard(0), *op);
                op->state.store(OpState::Done, std::memory_order_release);
                rob.publish();
                mark_active(c);
                notify_sender_if_remote(c);
                continue;
            }

            op->hash  = FlatStore::hash_key(op->key());
            op->shard = srv_->router().shard_of(op->hash);
            ThreadCtx& worker = srv_->thread(srv_->worker_of_shard(op->shard));

            // PUBLISH BEFORE DISPATCH. The old order posted the task first and published after, which
            // left a window of two instructions in which a worker could receive the task, execute it,
            // mark it Done and notify the sender -- all while dispatch_ still excluded the op. The
            // sender then woke, drained a ROB that did not yet contain the op, retired nothing, and
            // went back to sleep having spent its one notification. Nothing ever notified again, so
            // the reply sat Done in the ROB forever.
            //
            // It cost 3 lost replies in 87 million and wedged the connection permanently. Invisible in
            // 2-stage, where io is the sender and re-drains its own active set unprompted; fatal in
            // ex-wb and 3-stage, where the sender only ever looks when it is told to.
            Task t{c, rob.dispatch_id()};
            rob.publish();
            if (!worker.post_task(self_->id(), t, ring_, sig)) {
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
            mark_active(c);
        }
    }

    void finish_locally(Client* c, Op& op, const char* err) {
        reply_err(op.reply, err);
        op.state.store(OpState::Done, std::memory_order_release);
        c->rob().publish();
        mark_active(c);
        notify_sender_if_remote(c);
    }

    // THE OP NOBODY WOULD OTHERWISE REPORT. Most ops are completed by a worker, and the worker tells
    // the sender. But PING, DBSIZE, INFO, an unknown command and a bad arity are all finished right
    // here on the io thread -- no worker ever sees them, so no worker ever notifies. In 2-stage that
    // is invisible because io is itself the sender and retires on the same pass. In ex-wb and 3-stage
    // the reply is published into the ROB and then simply waits, forever, for a message that is never
    // sent.
    //
    // It is deterministic, not a race, and it hides in plain sight: any pipeline containing a single
    // keyed command drains the whole ROB and looks fine. Only a LONE keyless command hangs -- which is
    // exactly what a health check, a handshake, or `redis-cli ping` sends.
    void notify_sender_if_remote(Client* c) {
        if (c->sender_is_io()) return;                  // 2-stage: we retire it ourselves
        bool expected = false;
        if (!c->retire_queued().compare_exchange_strong(expected, true, std::memory_order_acq_rel))
            return;                                     // already queued; one message covers the batch
        ThreadCtx& snd = srv_->thread(c->sender_thread());
        if (!snd.post_client(self_->id(), c, ring_, self_->sig())) {
            self_->sig().notify_drop++;
            c->retire_queued().store(false, std::memory_order_release);   // retry on a later pass
        }
    }

    void mark_active(Client* c) {
        if (c->in_active()) return;          // one load, not a scan of the whole set
        c->set_in_active(true);
        active_.insert(c);
    }

    // ---- inbound: workers telling us a client has completed ops -----------------------------------
    // Inbound from workers (2-stage: "ops are Done") or from the sender ("I retired something, you
    // may be unstuck"). Either way the answer is the same: put the client back in the active set.
    uint32_t sweep() { return collect_retire_work(true) + flush_ready(); }

    uint32_t collect_retire_work(bool unmasked = false) {
        auto take = [&](Client* c) {
            c->retire_queued().store(false, std::memory_order_release);
            mark_active(c);
        };
        return unmasked ? self_->drain_clients_unmasked(take) : self_->drain_clients(take);
    }

    // ---- retire -> stage bytes -> send or hand off -------------------------------------------------
    // The io thread's own work per active client. In 2-stage it also owns the reply side and calls
    // serve() here; in ex-wb and 3-stage the sender does that on its own thread and io only keeps
    // the READ side moving — reclaim the buffer once nothing points into it, and re-arm.
    uint32_t flush_ready() {
        uint32_t work = 0;
        for (auto it = active_.begin(); it != active_.end();) {
            Client* c = *it;
            Conn& conn = c->conn();

            if (c->sender_is_io()) {
                if (wb_.serve(*c, [] {})) work++;      // 2-stage: same thread, no notification
            }

            // Reset only when the ROB is quiescent AND no recv is outstanding — see conn.h. Then
            // re-arm, in that order.
            if (c->rob().quiesced() && !conn.recv_armed()) conn.reset_rbuf_at_quiescence();

            // Re-parse the buffered remainder. parse_and_dispatch stops when the ROB window fills
            // and is otherwise only driven by recv completions, so a client that sent a whole
            // pipeline in ONE write would get `window` replies and then hang. Retiring frees slots,
            // which is what makes the rest parseable.
            if (!c->closing() && conn.rpos() < conn.rlen()) { parse_and_dispatch(c); work++; }

            arm_recv(c);

            // If we still cannot progress, say so: the sender will poke us once retiring has freed
            // a slot or unpinned the buffer. Without this the io thread can sit with a full window
            // and no recv armed, waiting for an event that never arrives.
            const bool stuck = (conn.rpos() < conn.rlen() && c->rob().full()) ||
                               (!conn.recv_armed() && !c->closing());
            c->needs_io_wake().store(stuck, std::memory_order_release);

            const bool more_input = conn.rpos() < conn.rlen();
            const bool done = c->rob().quiesced() && !more_input && !stuck &&
                              (!c->sender_is_io() || conn.nothing_to_write());
            if (done && !c->closing()) { c->set_in_active(false); it = active_.erase(it); }
            else if (c->closing() && c->safe_to_release()) {
                c->set_in_active(false); it = active_.erase(it); close_client(c);
            } else ++it;
        }
        return work;
    }

    void close_client(Client* c) {
        c->mark_closing();
        // Release only at the quiescence fence: a worker may still hold a Task that resolves through
        // this ROB. Anything else is a use-after-free under pipelining.
        if (!c->safe_to_release()) return;
        c->set_in_active(false);
        active_.erase(c);
        auto& v = self_->clients();
        for (size_t i = 0; i < v.size(); i++)
            if (v[i] == c) { v[i] = v.back(); v.pop_back(); break; }
        ::close(c->conn().fd());
        delete c;
    }

    Server*    srv_  = nullptr;
    ThreadCtx* self_ = nullptr;
    ThreadCtx* sender_ = nullptr;      // Ex/Wb modes
    int        listen_fd_ = -1;
    Ring       ring_;
    WbEngine   wb_;
    bool       accept_pending_ = false;

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
};

}  // namespace tomo
