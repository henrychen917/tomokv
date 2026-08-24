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
#include <deque>
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

// THE FIVE LOOPS. Each mode composes threads from five specialised loop shapes, distinguished by
// what the thread OWNS while serving -- fixed PER CONNECTION at accept by sender_thread(), so the
// hot paths carry no mode branches, only per-conn ownership checks:
//
//   io    IoLoop, self-served conns       recv+parse+retire+send; owns the whole client
//   ifid  IoLoop, delegated conns         recv+parse only; sender_is_io false, so the
//                                         serve path never runs and ConnOut is never touched
//   ex    ExLoop                          execute+notify; never sends
//   wb    WbLoop                          retire+send, channel-fed, ConnOut owned STATICALLY --
//                                         which is why its serve takes no lock (see WbGuard)

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
    bool init(Server* srv, ThreadCtx* self, const char* addr, uint16_t port) {
        srv_ = srv; self_ = self;
        listen_fd_ = make_reuseport_listener(addr, port);
        if (listen_fd_ < 0) return false;
        if (!ring_.init(4096)) return false;
        self_->set_ring(&ring_);
        wb_.bind(&ring_);
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
            reap_dead();               // free clients dead for a full iteration -- see close_client

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
        if (c->in().recv_armed() || c->closing()) return;
        size_t avail = 0;
        // may_grow ONLY at quiescence: realloc moves the buffer that every in-flight argv Slice
        // points into. See Conn::read_space.
        char* dst = c->in().read_space(kRecvChunk, avail, c->rob().quiesced());
        if (!dst) return;                      // no usable space yet: let the ROB drain first
        io_uring_sqe* s = ring_.sqe();
        if (!s) { self_->sig().sqe_starved++; return; }   // retried from flush_ready next pass
        io_uring_prep_recv(s, c->in().fd(), dst, avail, 0);
        s->user_data = ur_tag(UrKind::Recv, c);
        ring_.note_pending();
        c->in().set_recv_armed(true);
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
        c->set_ifid_thread(self_->id());
        c->set_sender_thread(sender_ ? sender_->id() : self_->id());
        // Item 5: the connection's wb protocol, for life (until a flip changes it at the fence).
        // Owned = we send for it ourselves; Fixed = one designated remote sender. Nobody is Shared
        // today, so no serve anywhere takes a lock.
        c->set_proto(c->sender_is_io() ? WbProto::Owned : WbProto::Fixed);
        // Owned connections get their ready-mask slot immediately -- WE are the sender. Remote
        // senders assign at adoption (their first channel contact).
        if (c->sender_is_io()) c->set_wb_slot(self_->assign_wb_slot(c));
        self_->clients().push_back(c);
        arm_recv(c);
        if (!(cqe->flags & IORING_CQE_F_MORE)) {               // multishot dropped: re-arm
            self_->sig().accept_rearm++;
            arm_accept();
        }
    }

    void on_recv(Client* c, int res) {
        c->in().set_recv_armed(false);       // the kernel has released its pointer
        if (res <= 0) { close_client(c); return; }
        c->in().commit_read(static_cast<size_t>(res));
        parse_and_dispatch(c);
        // Deliberately NOT re-armed here. flush_ready() re-arms AFTER it may have reset the read
        // buffer; arming first would leave the kernel holding a pointer that the reset then moves.
        mark_active(c);
    }

    // ---- parse -> route -> publish -----------------------------------------------------------------
    void parse_and_dispatch(Client* c) {
        ConnIn& conn = c->in();
        Rob<kRobWindow>& rob = c->rob();
        LoopSignals& sig = self_->sig();
        bool head_candidate = true;   // only the pass's FIRST dispatch can be the direct head
        uint32_t dispatched_this_pass = 0;

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
                // Item 6: session-mutating commands run HERE, on the connection's single parse
                // thread -- which is the whole reason Session state never needs a lock and handlers
                // never need a Client. SELECT is the only one so far.
                if (op->argc() == 2) {
                    Slice n = op->cmd_name();
                    if (n.n == 6 && (n.p[0] == 's' || n.p[0] == 'S')) {
                        char buf[16] = {};
                        std::memcpy(buf, n.p, 6);
                        for (auto& ch : buf) ch = static_cast<char>(std::tolower(ch));
                        if (!std::strncmp(buf, "select", 6)) {
                            uint64_t v = 0; uint32_t pp = 0;
                            Slice a = op->arg(1);
                            (void)parse_len_crlf; // (index parsed simply below)
                            for (uint32_t k = 0; k < a.n && a.p[k] >= '0' && a.p[k] <= '9'; k++)
                                v = v * 10 + static_cast<uint64_t>(a.p[k] - '0');
                            (void)pp;
                            c->session().db_index = static_cast<uint32_t>(v);
                        }
                    }
                }
                spec->handler(srv_->shard(0), *op);
                op->state.store(OpState::Done, std::memory_order_release);
                rob.publish();
                enqueue_serve(c);
                mark_active(c);
                notify_sender_if_remote(c);
                continue;
            }

            op->db    = static_cast<uint8_t>(c->session().db_index);
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
            // DIRECT-REPLY eligibility (owner's c->buf trick): this op is the ROB head and the
            // fill buffer is empty, so its bytes can be formatted in place by the worker. True for
            // every op at depth 1 and for the head of each fresh batch at depth. Evaluated ONLY for
            // the first dispatch of the pass: later ops cannot be head, and the in_flight() read
            // touches flush_, a line the sender writes -- checked per op it became a per-op
            // cross-thread load and cost -2..-4% at p32 for a candidate that can never qualify.
            if (head_candidate) {
                head_candidate = false;
                if ((c->sender_is_io() || conn.last_batch() <= 1) &&
                    rob.in_flight() == 0 && c->out().nothing_to_write()) {
                    SmallBuf<kWbufInline>& fb = c->out().fill_buf();
                    op->direct     = fb.data();
                    op->direct_cap = static_cast<uint32_t>(fb.cap());
                }
            }
            Task t{c, rob.dispatch_id()};
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
            dispatched_this_pass++;
            {
                const uint32_t wkr = static_cast<uint32_t>(srv_->worker_of_shard(op->shard));
                if (!touched_[wkr]) { touched_[wkr] = true; touched_list_[ntouched_++] = wkr; }
            }
            mark_active(c);
        }
        conn.set_last_batch(dispatched_this_pass);
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
        op.state.store(OpState::Done, std::memory_order_release);
        c->rob().publish();
        enqueue_serve(c);
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
        if (c->dead()) return;               // a corpse from the deferred-free list: entry consumed, nothing to do
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
        return n;
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
            ConnIn& conn = c->in();
            if (backstop_pass_ && c->sender_is_io() && !c->serve_pending()) enqueue_serve(c);

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
            const bool done = c->rob().quiesced() && !more_input && !stuck && !c->serve_pending() &&
                              (!c->sender_is_io() || c->out().nothing_to_write());
            if (done && !c->closing()) { c->set_in_active(false); it = active_.erase(it); }
            else if (c->closing() && c->safe_to_release()) {
                c->set_in_active(false); it = active_.erase(it); close_client(c);
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
            if (wb_.try_serve(*c, [] {})) work++;
        }
        work += served;
        return work;
    }

    void enqueue_serve(Client* c) {
        if (!c->sender_is_io()) return;                 // remote-sender conns are not ours to serve
        if (c->serve_pending()) return;                 // already queued
        c->set_serve_pending(true);
        pending_serve_.push_back(c);
    }

    void close_client(Client* c) {
        c->mark_closing();
        // Release only at the quiescence fence: a worker may still hold a Task that resolves through
        // this ROB. Anything else is a use-after-free under pipelining. (The retryable wait paths,
        // with their mark_active leak guard, are below.)
        c->set_in_active(false);
        active_.erase(c);
        auto& v = self_->clients();
        for (size_t i = 0; i < v.size(); i++)
            if (v[i] == c) { v[i] = v.back(); v.pop_back(); break; }
        // Remote sender still holds our slot (its table maps a bit to this pointer): ask it to let
        // go and try again. THE RETRY IS THE LOAD-BEARING PART: this client left the active set
        // when it went quiet, so nothing revisits it unless we put it back -- and the first version
        // of this path returned without doing so, leaking the ENTIRE client (ROB chunks + grown
        // buffers, ~137KB) on every remote-mode disconnect. Measured: +130MB RSS per bench round,
        // linear, until the box died. mark_active() re-enters the client into flush_ready's closing
        // branch, which calls back here every pass until the sender lets go.
        // ORDER MATTERS: quiesce first, release-request second. Asking the sender to let go while
        // ops are still in flight makes it drop the slot, after which completions fall back to the
        // channel where the closing branch refuses to serve -- the replies never retire, the conn
        // never quiesces, and the "wait" is forever. Only a quiesced, claim-free conn may ask.
        if (!c->safe_to_release()) { mark_active(c); return; }
        if (!c->sender_is_io() && c->wb_slot() != Client::kNoWbSlot) {
            bool expected = false;
            if (c->retire_queued().compare_exchange_strong(expected, true, std::memory_order_acq_rel)) {
                ThreadCtx& snd = srv_->thread(c->sender_thread());
                if (!snd.post_client(self_->id(), c, ring_, self_->sig()))
                    c->retire_queued().store(false, std::memory_order_release);
            }
            mark_active(c);                                // keep retrying until the release lands
            return;                                        // freed only after the sender releases
        }
        if (c->sender_is_io()) {
            self_->release_wb_slot(c->wb_slot());
            c->set_wb_slot(Client::kNoWbSlot);
        }
        ::close(c->in().fd());
        // NOT delete. A poke-path post (serve's needs_io_wake notify) carries no claim flag, so one
        // may still sit un-consumed in our inbound channels naming this client. Every such entry was
        // pushed BEFORE this point, and channels are FIFO with their mask bits set -- so ONE full
        // collect_retire_work pass consumes all of them. Park the corpse for one loop iteration and
        // free it at the top of the one after; the drain lambda skips dead clients.
        c->mark_dead();
        dead_next_.push_back(c);
    }

    // Free everything that has been dead for a full iteration. Called once per loop pass, BEFORE
    // this pass's drains, so a corpse parked in pass N is freed in pass N+2's prologue -- after the
    // whole of pass N+1 (including its channel drains) ran with the corpse still readable.
    void reap_dead() {
        for (Client* c : dead_ready_) delete c;
        dead_ready_.clear();
        dead_ready_.swap(dead_next_);
    }

    Server*    srv_  = nullptr;
    ThreadCtx* self_ = nullptr;
    ThreadCtx* sender_ = nullptr;      // Ex/Wb modes
    static constexpr uint32_t kFlushBackstopEvery = 64;
    // Serves per pass. Sized so a pass's serve work stays comparable to its recv work: ~16 serves
    // x a ~32-op prefix each is one CQ batch worth of replies. The queue, not the pass, absorbs
    // overload.
    static constexpr uint32_t kServeBudget = 16;
    std::deque<Client*> pending_serve_;
    uint32_t flush_tick_ = 0;
    bool     backstop_pass_ = false;
    bool touched_[kMaxThreads] = {};      // dedupe flags for the current parse pass
    uint32_t touched_list_[kMaxThreads] = {}; // the workers actually fed, dense
    uint32_t ntouched_ = 0;
    std::vector<Client*> dead_next_;   // corpses parked this iteration
    std::vector<Client*> dead_ready_;  // corpses freed at the next prologue
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
