#!/usr/bin/env python3
"""Apply the flipfix5 DIAGNOSTIC instrumentation to a source tree (never production)."""
import sys
from pathlib import Path

root = Path(sys.argv[1])
import os
POST = os.environ.get('FF5_POST') == '1'
EXDRAIN_OLD = ("        if (stage == FlipStage::ExDrain && flip_owed(stage) && flip_quiesced()) {\n            srv_->flip_ack(self_->id(), stage);"
               if POST else "        if (stage == FlipStage::ExDrain && !srv_->flip_acked(self_->id(), stage) &&\n            flip_quiesced()) {\n            srv_->flip_ack(self_->id(), stage);")
EXDRAIN_NEW_PREFIX = ("        if (stage == FlipStage::ExDrain && flip_owed(stage) && flip_quiesced()) {"
                      if POST else "        if (stage == FlipStage::ExDrain && !srv_->flip_acked(self_->id(), stage) &&\n            flip_quiesced()) {")
EXINSTALL_OLD = ("        if (stage == FlipStage::ExInstall && flip_owed(stage)) {"
                 if POST else "        if (stage == FlipStage::ExInstall && !srv_->flip_acked(self_->id(), stage)) {")


def patch(rel, old, new, count=1):
    p = root / rel
    t = p.read_text()
    n = t.count(old)
    if n != count:
        raise SystemExit(f'{rel}: expected {count} occurrence(s), found {n}: {old[:80]!r}')
    p.write_text(t.replace(old, new))

# ---------------------------------------------------------------- masked_queue.h
mq = 'src/exec/masked_queue.h'
patch(mq, '#include "exqueue.h"\n', '''#include "exqueue.h"
#include <cstdio>
#include <ctime>
#include <execinfo.h>
extern "C" char __executable_start;
''')
patch(mq, 'template <typename T, uint32_t MaxProducers>\nclass MaskedSpscArray {', '''// flipfix5 DIAGNOSTIC: push provenance while a FLIP is between ExDrain and Rollback.
struct Ff5PushRecord {
    uint64_t state = 0;
    uint64_t ns = 0;
    uint32_t tail_after = 0;
    uint32_t count = 0;
    int nframes = 0;
    void* frames[14] = {};
};
inline uint64_t (*g_ff5_push_state)(uint32_t consumer, uint32_t producer) = nullptr;
inline uint64_t ff5_now_ns() {
    timespec ts;
    clock_gettime(CLOCK_MONOTONIC, &ts);
    return static_cast<uint64_t>(ts.tv_sec) * 1000000000ull + static_cast<uint64_t>(ts.tv_nsec);
}

template <typename T, uint32_t MaxProducers>
class MaskedSpscArray {''')
# push sites: record after every tail publication
patch(mq, '''        slots_[p.base + (tail & p.mask)] = value;
        p.tail.store(next, std::memory_order_release);
        return true;
    }

    template <typename Prepare>
    bool push_prepared(''', '''        slots_[p.base + (tail & p.mask)] = value;
        p.tail.store(next, std::memory_order_release);
        ff5_note(producer, next, 1);
        return true;
    }

    template <typename Prepare>
    bool push_prepared(''')
patch(mq, '''        prepare(value);
        slots_[p.base + (tail & p.mask)] = value;
        p.tail.store(next, std::memory_order_release);
        return true;
    }

    bool push_batch(''', '''        prepare(value);
        slots_[p.base + (tail & p.mask)] = value;
        p.tail.store(next, std::memory_order_release);
        ff5_note(producer, next, 1);
        return true;
    }

    bool push_batch(''')
patch(mq, '''        for (uint32_t i = 0; i < count; i++)
            slots_[p.base + ((tail + i) & p.mask)] = values[i];
        p.tail.store(next, std::memory_order_release);
        return true;
    }''', '''        for (uint32_t i = 0; i < count; i++)
            slots_[p.base + ((tail + i) & p.mask)] = values[i];
        p.tail.store(next, std::memory_order_release);
        ff5_note(producer, next, count);
        return true;
    }''')
patch(mq, '''            slots_[p.base + ((tail + i) & p.mask)] = value;
        }
        p.tail.store(next, std::memory_order_release);
        return true;
    }''', '''            slots_[p.base + ((tail + i) & p.mask)] = value;
        }
        p.tail.store(next, std::memory_order_release);
        ff5_note(producer, next, count);
        return true;
    }''')
patch(mq, '''        slots_[p.base + (tail & p.mask)] = value;
        p.tail.store(tail + 1, std::memory_order_release);
        p.available_capacity++;
    }''', '''        slots_[p.base + (tail & p.mask)] = value;
        p.tail.store(tail + 1, std::memory_order_release);
        p.available_capacity++;
        ff5_note(producer, tail + 1, 1);
    }''', count=2)
# diagnostics API inserted before the private section
patch(mq, '''private:
    void note_lane_full(ProducerLine& p) {''', '''    // ---- flipfix5 DIAGNOSTIC ----
    static constexpr uint32_t kFf5Ring = 8;
    void ff5_set_consumer(uint32_t id) {
        ff5_consumer_ = id;
        void* prime[2];
        (void)backtrace(prime, 2);  // load the unwinder before any hot-path capture
    }
    uint32_t ff5_consumer() const { return ff5_consumer_; }
    __attribute__((noinline)) void ff5_note(uint32_t producer, uint32_t tail_after, uint32_t count) {
        auto hook = g_ff5_push_state;
        if (!hook) return;
        const uint64_t state = hook(ff5_consumer_, producer);
        if (!state) return;
        Ff5PushRecord& r = ff5_ring_[producer][ff5_next_[producer]++ % kFf5Ring];
        r.state = state;
        r.ns = ff5_now_ns();
        r.tail_after = tail_after;
        r.count = count;
        // Light: the push site only (ff5_note is out of line), no unwinding.
        r.frames[0] = __builtin_extract_return_addr(__builtin_return_address(0));
        r.nframes = 1;
        ff5_recorded_[producer]++;
    }
    const char* ff5_remask_reason(const std::vector<uint32_t>& io,
                                  const std::vector<uint32_t>& ex) const {
        if (!slots_) return "no-slots";
        if (io.empty()) return "io-empty";
        if (ex.empty()) return "ex-empty";
        if (io.size() + ex.size() != producers_) return "io+ex!=producers";
        if (!all_quiesced()) return "all_quiesced()==false";
        bool assigned[MaxProducers] = {};
        for (uint32_t p : io) { if (p >= producers_ || assigned[p]) return "io-dup-or-range"; assigned[p] = true; }
        for (uint32_t p : ex) { if (p >= producers_ || assigned[p]) return "ex-dup-or-range"; assigned[p] = true; }
        for (uint32_t p = 0; p < producers_; p++) if (!assigned[p]) return "unassigned-producer";
        const uint64_t internal = static_cast<uint64_t>(ex.size()) * kInternalProducerSlots;
        if (internal >= total_slots_) return "internal>=total";
        const uint32_t io_share = static_cast<uint32_t>((total_slots_ - internal) / io.size());
        const uint32_t io_capacity = std::bit_floor(io_share);
        if (!io_capacity || io_capacity * sizeof(T) < kMaskedQueueCacheLine) return "io-capacity";
        if ((io_capacity < kInternalProducerSlots ? io_capacity : kInternalProducerSlots) < kInternalProducerSlots)
            return "min-bank";
        return "predicates-pass";
    }
    template <typename Describe>
    void ff5_dump(FILE* out, Describe&& describe) const {
        std::fprintf(out, "FF5 inbox consumer=%u producers=%u total_slots=%u\\n",
                     ff5_consumer_, producers_, total_slots_);
        for (uint32_t p = 0; p < producers_; p++) {
            const ConsumerLine& c = lanes_[p].consumer;
            const ProducerLine& q = lanes_[p].producer;
            const uint32_t head = c.head.load(std::memory_order_acquire);
            const uint32_t retired = c.retired.load(std::memory_order_acquire);
            const uint32_t tail = q.tail.load(std::memory_order_acquire);
            const bool open = head != tail || retired != tail;
            if (!open && !ff5_recorded_[p]) continue;
            std::fprintf(out, "FF5 lane p=%u %s head=%u retired=%u tail=%u cbase=%u cmask=%u ccap=%u "
                         "pbase=%u pmask=%u pcap=%u avail=%u recorded=%llu\\n",
                         p, open ? "OPEN" : "quiet", head, retired, tail, c.base, c.mask, c.capacity,
                         q.base, q.mask, q.capacity, q.available_capacity,
                         static_cast<unsigned long long>(ff5_recorded_[p]));
            uint32_t shown = 0;
            for (uint32_t i = retired; i != tail && shown < 16; i++, shown++)
                describe(out, p, i, slots_[c.base + (i & c.mask)]);
            const uint32_t have = ff5_recorded_[p] < kFf5Ring ? static_cast<uint32_t>(ff5_recorded_[p]) : kFf5Ring;
            for (uint32_t k = 0; k < have; k++) {
                const Ff5PushRecord& r = ff5_ring_[p][(ff5_next_[p] - have + k) % kFf5Ring];
                std::fprintf(out, "FF5   push lane=%u ns=%llu tail_after=%u count=%u epoch=%llu stage=%u "
                             "consumer_acked_exdrain=%u producer_acked_exdrain=%u producer_role=%u consumer_role=%u frames=",
                             p, static_cast<unsigned long long>(r.ns), r.tail_after, r.count,
                             static_cast<unsigned long long>((r.state >> 24) & 0xffffffffull),
                             static_cast<unsigned>((r.state >> 16) & 0xff),
                             static_cast<unsigned>((r.state >> 15) & 1), static_cast<unsigned>((r.state >> 14) & 1),
                             static_cast<unsigned>((r.state >> 4) & 0xf), static_cast<unsigned>(r.state & 0xf));
                for (int f = 0; f < r.nframes; f++)
                    std::fprintf(out, "%s0x%lx", f ? "," : "",
                                 static_cast<unsigned long>(static_cast<char*>(r.frames[f]) - &__executable_start));
                std::fprintf(out, "\\n");
            }
        }
        std::fflush(out);
    }

private:
    uint32_t ff5_consumer_ = UINT32_MAX;
    uint32_t ff5_next_[MaxProducers] = {};
    uint64_t ff5_recorded_[MaxProducers] = {};
    Ff5PushRecord ff5_ring_[MaxProducers][kFf5Ring];

    void note_lane_full(ProducerLine& p) {''')

# ---------------------------------------------------------------- signal.h passthroughs
sg = 'src/core/signal.h'
patch(sg, '''    uint32_t total_slots() const { return q_.total_slots(); }
    MaskedQueueDiagnostics diagnostics() const { return q_.diagnostics(); }

private:
    MaskedSpscArray<T, MaxProducers> q_;''', '''    uint32_t total_slots() const { return q_.total_slots(); }
    MaskedQueueDiagnostics diagnostics() const { return q_.diagnostics(); }
    void ff5_set_consumer(uint32_t id) { q_.ff5_set_consumer(id); }
    const char* ff5_remask_reason(const std::vector<uint32_t>& io,
                                  const std::vector<uint32_t>& ex) const {
        return q_.ff5_remask_reason(io, ex);
    }
    template <typename Describe>
    void ff5_dump(FILE* out, Describe&& describe) const { q_.ff5_dump(out, describe); }

private:
    MaskedSpscArray<T, MaxProducers> q_;''')

# ---------------------------------------------------------------- thread.h
th = 'src/core/thread.h'
patch(th, '''        if (!inbox || !inbox->init_local(nchan_, kInboxSlots, io, ex)) return false;
        task_in_ = std::move(inbox);
        return true;
    }''', '''        if (!inbox || !inbox->init_local(nchan_, kInboxSlots, io, ex)) return false;
        inbox->ff5_set_consumer(id_);
        task_in_ = std::move(inbox);
        return true;
    }
    const char* ff5_remask_reason(const std::vector<uint32_t>& io,
                                  const std::vector<uint32_t>& ex) const {
        return task_in_ ? task_in_->ff5_remask_reason(io, ex) : "no-task-inbox";
    }
    template <typename Describe>
    void ff5_dump_task_inbox(FILE* out, Describe&& describe) const {
        if (task_in_) task_in_->ff5_dump(out, describe);
    }
    bool ff5_release_quiesced() const {
        for (uint32_t i = 0; i < nchan_; i++) if (!release_in_[i].quiesced()) return false;
        return true;
    }''')

# ---------------------------------------------------------------- xshard.cc scatter description
xs = 'src/cmd/xshard.cc'
t = (root / xs).read_text()
t = t.rstrip('\n') + '''

namespace tomo {
// flipfix5 DIAGNOSTIC: describe a scatter state named by a stranded task.
void ff5_describe_scatter(FILE* out, const ScatterState* s) {
    std::fprintf(out, "FF5   scatter kind=%u phase=%u pending=%u nsub=%u key_count=%u owner_io=%u "
                 "multi_child=%d atomic_group=%d atomic_write=%d atomic_apply=%d atomic_direct=%d "
                 "script_phase=%u final_reply=%u retired=%d two_hop=%d barrier=%d admitted=%d "
                 "apply_open=%d record_refs=%u runtime_loading=%d\\n",
                 unsigned(s->kind), unsigned(s->phase), s->pending.load(), s->nsub, s->key_count,
                 s->owner_io, int(s->multi_child), int(s->atomic_group), int(s->atomic_write),
                 int(s->atomic_apply), int(s->atomic_direct), unsigned(s->script_phase),
                 unsigned(s->final_reply), int(s->retired), int(s->two_hop), int(s->barrier),
                 int(s->admitted), int(s->apply_open.load()), s->record_refs.load(),
                 int(s->runtime_loading));
    std::fflush(out);
}
}  // namespace tomo
'''
(root / xs).write_text(t)

# ---------------------------------------------------------------- ex_loop.h
ex = 'src/core/ex_loop.h'
patch(ex, '''template <bool Fused>
class ExLoopT {
public:''', '''// ---- flipfix5 DIAGNOSTIC ----
void ff5_describe_scatter(FILE* out, const ScatterState* s);
inline Server* g_ff5_server = nullptr;
inline std::atomic<uint64_t> g_ff5_exdrain_ack_epoch[kMaxThreads];
inline std::atomic<uint64_t> g_ff5_exdrain_ack_ns[kMaxThreads];
inline uint64_t ff5_push_state_fn(uint32_t consumer, uint32_t producer) {
    Server* srv = g_ff5_server;
    if (!srv || consumer >= srv->nthreads()) return 0;
    const FlipStage stage = srv->flip_stage();
    if (stage == FlipStage::Idle) return 0;
    const uint64_t epoch = srv->flip_epoch() & 0xffffffffull;
    const uint64_t consumer_acked = srv->flip_acked(consumer, FlipStage::ExDrain) ? 1 : 0;
    const bool live_producer = producer < srv->nthreads();
    const uint64_t producer_acked =
        live_producer && srv->flip_acked(producer, FlipStage::ExDrain) ? 1 : 0;
    const uint64_t producer_role =
        live_producer ? static_cast<uint8_t>(srv->thread(producer).role()) : 0xf;
    const uint64_t consumer_role = static_cast<uint8_t>(srv->thread(consumer).role());
    return (1ull << 63) | (epoch << 24) | (static_cast<uint64_t>(static_cast<uint8_t>(stage)) << 16) |
           (consumer_acked << 15) | (producer_acked << 14) | ((producer_role & 0xf) << 4) |
           (consumer_role & 0xf);
}

template <bool Fused>
class ExLoopT {
public:''')
patch(ex, '''    bool init(Server* srv, ThreadCtx* self, bool dormant = false) {
        srv_ = srv; self_ = self;''', '''    bool init(Server* srv, ThreadCtx* self, bool dormant = false) {
        srv_ = srv; self_ = self;
        g_ff5_server = srv;
        g_ff5_push_state = &ff5_push_state_fn;''')
patch(ex, EXDRAIN_OLD, EXDRAIN_NEW_PREFIX + '''
            g_ff5_exdrain_ack_epoch[self_->id()].store(srv_->flip_epoch(), std::memory_order_relaxed);
            g_ff5_exdrain_ack_ns[self_->id()].store(ff5_now_ns(), std::memory_order_relaxed);
            srv_->flip_ack(self_->id(), stage);''')
patch(ex, '''            if (!self_->remask_task_inbox_quiesced(srv_->placement().ifid_threads(),
                                                    srv_->placement().ex_threads()))
                std::abort();''', '''            if (!self_->remask_task_inbox_quiesced(srv_->placement().ifid_threads(),
                                                    srv_->placement().ex_threads())) {
                ff5_dump_failure(srv_->placement().ifid_threads(), srv_->placement().ex_threads());
                std::abort();
            }''')
patch(ex, '''    uint32_t lb_control_pass() {
        if (!lb_controller_armed_) return 0;''', '''    __attribute__((noinline, cold)) void ff5_dump_failure(const std::vector<uint32_t>& io,
                                                         const std::vector<uint32_t>& ex) {
        FILE* out = stderr;
        std::fprintf(out, "FF5 ABORT ExInstall remask thread=%u role=%u epoch=%llu stage=%u now_ns=%llu reason=%s\\n",
                     self_->id(), unsigned(static_cast<uint8_t>(self_->role())),
                     static_cast<unsigned long long>(srv_->flip_epoch()),
                     unsigned(static_cast<uint8_t>(srv_->flip_stage())),
                     static_cast<unsigned long long>(ff5_now_ns()),
                     self_->ff5_remask_reason(io, ex));
        std::fprintf(out, "FF5 io=");
        for (uint32_t t : io) std::fprintf(out, "%u,", t);
        std::fprintf(out, " ex=");
        for (uint32_t t : ex) std::fprintf(out, "%u,", t);
        std::fprintf(out, " nthreads=%u\\n", srv_->nthreads());
        for (uint32_t t = 0; t < srv_->nthreads(); t++)
            std::fprintf(out, "FF5 thread %u role=%u ready_role=%u exdrain_ack_epoch=%llu exdrain_ack_ns=%llu "
                         "acked_exdrain=%d acked_exinstall=%d\\n", t,
                         unsigned(static_cast<uint8_t>(srv_->thread(t).role())),
                         unsigned(static_cast<uint8_t>(srv_->thread(t).ready_role())),
                         static_cast<unsigned long long>(g_ff5_exdrain_ack_epoch[t].load()),
                         static_cast<unsigned long long>(g_ff5_exdrain_ack_ns[t].load()),
                         int(srv_->flip_acked(t, FlipStage::ExDrain)),
                         int(srv_->flip_acked(t, FlipStage::ExInstall)));
        std::fprintf(out, "FF5 self quiesce: inbound=%d release=%d stale_tasks=%zu stale_releases=%zu "
                     "atomic_deferred=%zu multi_retries=%zu xshard_retries=%zu ordered_deferred=%zu "
                     "xshard_commit_pending=%d notify_keyless=%d atomic_inflight=%llu apply_inflight=%llu snapshot_state=%u\\n",
                     int(self_->ex_inbound_quiesced()), int(self_->ff5_release_quiesced()),
                     stale_tasks_.size(), stale_releases_.size(), atomic_deferred_.size(),
                     size_t(multi_retries_.count), xshard_retries_.size(), ordered_deferred_.size(),
                     int(xshard_commit_pending_), int(notify_keyless_pending_),
                     static_cast<unsigned long long>(srv_->atomic_inflight()),
                     static_cast<unsigned long long>(srv_->atomic_apply_inflight()),
                     unsigned(snapshot_owner_state_));
        std::fflush(out);
        self_->ff5_dump_task_inbox(out, [&](FILE* o, uint32_t lane, uint32_t index, const Task& t) {
            std::fprintf(o, "FF5 task lane=%u idx=%u client=%p op_id=%llu shard=%d scatter=%p stamp=%u\\n",
                         lane, index, static_cast<void*>(t.client),
                         static_cast<unsigned long long>(t.op_id), t.shard,
                         static_cast<void*>(t.scatter), t.enqueue_us_low);
            std::fflush(o);
            bool blocking = false;
            if (t.client) {
                Op& op = t.client->rob().at(t.op_id);
                blocking = op.has_blocking_state();
                const Slice name = op.cmd_name();
                std::fprintf(o, "FF5   op cmd=%.*s argc=%u state=%u shard=%d blocking=%d closing=%d "
                             "rob.flush=%llu rob.dispatch=%llu ifid=%u\\n",
                             int(name.n), name.p, op.argc(),
                             unsigned(static_cast<uint8_t>(op.state.load())), op.shard, int(blocking),
                             int(t.client->closing()),
                             static_cast<unsigned long long>(t.client->rob().flush_id()),
                             static_cast<unsigned long long>(t.client->rob().dispatch_id()),
                             t.client->ifid_thread());
                std::fflush(o);
            }
            if (t.scatter && !blocking) ff5_describe_scatter(o, t.scatter);
        });
    }

    uint32_t lb_control_pass() {
        if (!lb_controller_armed_) return 0;''')

# ---------------------------------------------------------------- abort wrapper in the server link
mk = 'Makefile'
patch(mk, '''	$(CXX) $(CXXFLAGS) $(DB0_OBJ) $(DB0_SERVER_ONLY_OBJ) $(OBJ) $(SERVER_ONLY_OBJ) -o $@ -Wl,--wrap=main $(JELIBS) $(LDLIBS) -lm''',
      '''	$(CXX) $(CXXFLAGS) -c tools/ff5_abort.cc -o $(BUILD_ROOT)/ff5_abort.o
	$(CXX) $(CXXFLAGS) $(DB0_OBJ) $(DB0_SERVER_ONLY_OBJ) $(OBJ) $(SERVER_ONLY_OBJ) $(BUILD_ROOT)/ff5_abort.o -o $@ -Wl,--wrap=main -Wl,--wrap=abort $(JELIBS) $(LDLIBS) -lm''')
(root / 'tools/ff5_abort.cc').write_text('''#include <execinfo.h>
#include <unistd.h>
#include <cstdio>
extern "C" char __executable_start;
// flipfix5 DIAGNOSTIC: print the abort-time stack as executable offsets, then exit 134.
extern "C" [[noreturn]] void __wrap_abort() {
    void* frames[64];
    const int n = backtrace(frames, 64);
    std::fprintf(stderr, "FF5 abort-stack:");
    for (int i = 0; i < n; i++)
        std::fprintf(stderr, "%s0x%lx", i ? "," : "",
                     static_cast<unsigned long>(static_cast<char*>(frames[i]) - &__executable_start));
    std::fprintf(stderr, "\\n");
    std::fflush(stderr);
    backtrace_symbols_fd(frames, n, 2);
    _exit(134);
}
''')
print('diag patch applied')
