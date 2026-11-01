#!/usr/bin/env python3
"""Make an isolated PRE diagnostic source copy. Never edits production sources."""
import io
from pathlib import Path
import subprocess
import tarfile

ROOT = Path(__file__).resolve().parents[1]
DEST = ROOT / 'build/flipfix6/diag-source'
DEST.mkdir(parents=True, exist_ok=True)
archive = subprocess.check_output(['git', 'archive', 'e32b04a44', 'Makefile', 'src',
                                   'third_party', 'tools/assert_map.py'], cwd=ROOT)
with tarfile.open(fileobj=io.BytesIO(archive)) as files:
    files.extractall(DEST, filter='data')

def edit(name, old, new):
    path = DEST / name
    text = path.read_text()
    assert text.count(old) == 1, (name, old)
    path.write_text(text.replace(old, new))

edit('src/net/conn.h', '    bool migration_protocol_idle() const {', '''    uint32_t flipfix6_diag_watch_refs() const { return watched_refs_.load(std::memory_order_acquire); }
    uint64_t flipfix6_diag_drain_mask() const {
        return uint64_t(!rob_.quiesced()) | (uint64_t(send_inflight_) << 1) |
            (uint64_t(serve_pending_) << 2) |
            (uint64_t(retire_queued_.load(std::memory_order_acquire)) << 3) |
            (uint64_t(barrier_owners_ != 0) << 4) |
            (uint64_t(atomic_groups_io_ != 0) << 5) |
            (uint64_t(blocked()) << 6) | (uint64_t(!nothing_to_write()) << 7);
    }
    bool migration_protocol_idle() const {''')
edit('src/cmd/multi.h', 'struct MultiSession;',
     'struct MultiSession;\nvoid flipfix6_diag_session(const Client&, uint64_t, uint32_t);')
edit('src/cmd/multi.inc', 'struct MultiOwnerRecordRefs {', '''
void flipfix6_diag_session(const Client& c, uint64_t epoch, uint32_t ordinal) {
    const auto* s = c.multi_session();
    std::fprintf(stderr, "FLIPFIX6 planned epoch=%llu io=%u ordinal=%u id=%llu session=%d pending=%d drain=%d migration=%d watched_refs=%u watched_keys=%zu\\n",
        (unsigned long long)epoch, c.ifid_thread(), ordinal, (unsigned long long)c.id(),
        s != nullptr, s && s->pending != nullptr, c.flip_drain_idle(), c.migration_protocol_idle(),
        c.flipfix6_diag_watch_refs(), s ? s->watched.size() : 0);
}
struct MultiOwnerRecordRefs {''')
# One snapshot of EVERY planned connection per source per epoch, before an early refusal.
edit('src/core/io_loop.h', '''        const uint32_t planned = srv_->flip_source_clients(self_->id());
        for (uint32_t ordinal = 0; ordinal < planned; ordinal++) {''', '''        const uint32_t planned = srv_->flip_source_clients(self_->id());
        static thread_local uint64_t diagnosed = UINT64_MAX;
        if (diagnosed != srv_->flip_epoch()) {
            diagnosed = srv_->flip_epoch();
            for (uint32_t n = 0; n < planned; n++)
                if (auto* c = srv_->flip_client_at(self_->id(), n))
                    flipfix6_diag_session(*c, diagnosed, n);
        }
        for (uint32_t ordinal = 0; ordinal < planned; ordinal++) {''')
edit('src/core/server.h', 'class Server {', '''inline std::atomic<uint64_t> flipfix6_diag_drain_masks[kMaxThreads]{};
class Server {''')
edit('src/core/io_loop.h', '    bool flip_io_drained() const {', '''
    void flipfix6_diag_drain_snapshot() const {
        const bool conditions[] = {
            !pending_serve_.empty(), !pending_releases_.empty(),
            !pending_handoffs_.empty(), !deferred_timers_.empty(),
            !client_migrations_.empty(), !epoll_closes_.empty(),
            !dead_next_.empty(), !dead_ready_.empty(),
            !multi_deferred_.empty(), !pending_multi_cleanups_.empty(),
            !pubsub_notification_chains_.empty(), !self_->io_inbound_quiesced(),
            srv_->pubsub_inflight() != 0, srv_->pubsub_pending() != 0,
            !accepts_quiesced(), !flip_io_drain_ordered()
        };
        uint64_t mask = 0;
        for (unsigned n = 0; n < sizeof(conditions)/sizeof(*conditions); n++)
            mask |= uint64_t(conditions[n]) << n;
        if (!flip_close_pin_)
            for (Client* c : active_.v)
                if (c->closing() && !c->dead()) mask |= uint64_t(1) << 16;
        for (Client* c : self_->clients()) {
            if (flip_close_pin_ && c->closing()) continue;
            const bool coordinator = self_->id() == srv_->flip_coordinator() &&
                c == flip_client_ && flip_epoch_local_ == srv_->flip_epoch();
            if (coordinator) {
                if (c->rob().in_flight() != 1 || c->send_inflight() ||
                    c->serve_pending() || !c->nothing_to_write() || !wb_.migration_ready(*c))
                    mask |= uint64_t(1) << 29;
            } else {
                mask |= c->flipfix6_diag_drain_mask() << 20;
                if (!wb_.migration_ready(*c)) mask |= uint64_t(1) << 28;
            }
        }
        flipfix6_diag_drain_masks[self_->id()].store(mask, std::memory_order_release);
    }
    bool flip_io_drained() const {''')
edit('src/core/io_loop.h', '''            fliplisten_quiesce();
            if (accepts_quiesced() && flip_io_drained() && flip_io_drain_ordered()) {''', '''            fliplisten_quiesce();
            flipfix6_diag_drain_snapshot();
            if (accepts_quiesced() && flip_io_drained() && flip_io_drain_ordered()) {''')
edit('src/core/server.h', '        flip_error_ = error;', '''        std::fprintf(stderr, "FLIPFIX6 failure epoch=%llu stage=%u deadline=%d error=%s\\n",
            (unsigned long long)flip_epoch(), (unsigned)flip_stage(), flip_timed_out(), error.c_str());
        if (flip_stage() == FlipStage::IoDrain)
            for (uint32_t tid = 0; tid < nthreads(); tid++)
                if (thread(tid).role() == Role::Ifid && !flip_acked(tid, FlipStage::IoDrain))
                    std::fprintf(stderr, "FLIPFIX6 drain epoch=%llu io=%u mask=%llu\\n",
                        (unsigned long long)flip_epoch(), tid,
                        (unsigned long long)flipfix6_diag_drain_masks[tid].load(std::memory_order_acquire));
        flip_error_ = error;''')
print(DEST)

# v3: distinguish retired MVCC reclamation from a prepared-unpublished session. The
# source IO snapshots only its own vectors and atomic state fields. The coordinator
# prints every IO (including one which acknowledged at the deadline), so a late ack
# cannot erase the last failing clause as it did in two v2 episodes.
edit('src/cmd/multi.h', 'struct MultiSession;', '''struct MultiSession;
void flipfix6_diag_deferred(const std::vector<MultiExecState*>&, uint64_t*);
bool flipfix6_diag_pending(const Client&);''')
edit('src/cmd/multi.inc', 'uint32_t multi_reap_deferred(std::vector<MultiExecState*>& deferred) {', '''
bool flipfix6_diag_pending(const Client& c) {
    return c.multi_session() && c.multi_session()->pending;
}
void flipfix6_diag_deferred(const std::vector<MultiExecState*>& states, uint64_t* out) {
    out[0] = states.size();
    for (const auto* s : states) {
        out[1] += s->record_refs.load(std::memory_order_acquire);
        out[2] += s->watch_refs.load(std::memory_order_acquire);
        for (const auto& cmd : s->commands)
            out[3] += cmd->scatter && !xshard_multi_child_records_done(*cmd->scatter);
        out[4] += s->retired;
        out[5] += s->published;
        out[6] += s->kind == MultiStateKind::Execute;
        out[7] += s->tasks_pending.load(std::memory_order_acquire);
        out[8] += s->snapshot_registered;
        out[9] += s->finalized.load(std::memory_order_acquire);
        out[10] = std::max(out[10], s->decision.epoch.load(std::memory_order_acquire));
    }
}
uint32_t multi_reap_deferred(std::vector<MultiExecState*>& deferred) {''')
edit('src/core/server.h', 'class Server {', '''inline std::atomic<uint64_t> flipfix6_diag_debt[kMaxThreads][14]{};
class Server {''')
edit('src/core/io_loop.h',
     '        flipfix6_diag_drain_masks[self_->id()].store(mask, std::memory_order_release);', '''
        uint64_t debt[14]{};
        flipfix6_diag_deferred(multi_deferred_, debt);
        for (Client* c : self_->clients()) debt[11] += flipfix6_diag_pending(*c);
        debt[12] = srv_->atomic_read_floor();
        debt[13] = srv_->atomic_snapshot();
        for (unsigned n = 0; n < 14; ++n)
            flipfix6_diag_debt[self_->id()][n].store(debt[n], std::memory_order_relaxed);
        flipfix6_diag_drain_masks[self_->id()].store(mask, std::memory_order_release);''')
edit('src/core/server.h', '''                if (thread(tid).role() == Role::Ifid && !flip_acked(tid, FlipStage::IoDrain))
                    std::fprintf(stderr, "FLIPFIX6 drain epoch=%llu io=%u mask=%llu\\n",
                        (unsigned long long)flip_epoch(), tid,
                        (unsigned long long)flipfix6_diag_drain_masks[tid].load(std::memory_order_acquire));''', '''
                if (thread(tid).role() == Role::Ifid) {
                    std::fprintf(stderr, "FLIPFIX6 drain epoch=%llu io=%u mask=%llu acked=%d debt=",
                        (unsigned long long)flip_epoch(), tid,
                        (unsigned long long)flipfix6_diag_drain_masks[tid].load(std::memory_order_acquire),
                        flip_acked(tid, FlipStage::IoDrain));
                    for (unsigned n = 0; n < 14; ++n)
                        std::fprintf(stderr, "%s%llu", n ? "," : "",
                            (unsigned long long)flipfix6_diag_debt[tid][n].load(std::memory_order_relaxed));
                    std::fprintf(stderr, "\\n");
                }''')

# v4: owner-local cleanup receipts. Only atomic snapshots cross threads.
edit('src/core/server.h', 'class Server {', '''inline std::atomic<uint64_t> flipfix6_diag_owner[kMaxThreads][8]{};
class Server {''')
edit('src/core/ex_loop.h', '''        const FlipStage stage = srv_->flip_stage();
#ifdef TOMO_CORE_CONCURRENCY_TEST''', '''        const FlipStage stage = srv_->flip_stage();
        flipfix6_diag_owner[self_->id()][0].fetch_add(1, std::memory_order_relaxed);
        flipfix6_diag_owner[self_->id()][1].store((unsigned)stage, std::memory_order_relaxed);
#ifdef TOMO_CORE_CONCURRENCY_TEST''')
edit('src/core/ex_loop.h', '''        const uint64_t floor = srv_->atomic_read_floor();
        uint32_t work = 0;''', '''        const uint64_t floor = srv_->atomic_read_floor();
        auto& diag = flipfix6_diag_owner[self_->id()];
        diag[2].fetch_add(1, std::memory_order_relaxed);
        diag[3].store(cleanup_cutoff, std::memory_order_relaxed);
        diag[4].store(floor, std::memory_order_relaxed);
        uint64_t records = 0;
        for (Shard* shard : shards) records += shard->store().atomic_pending_entries();
        diag[5].store(records, std::memory_order_relaxed);
        uint32_t work = 0;''')
edit('src/core/ex_loop.h', '''            work += xshard_cleanup_shard_at(*shard, floor, cleanup_cutoff, budget - work);
            if (work >= budget) break;''', '''            work += xshard_cleanup_shard_at(*shard, floor, cleanup_cutoff, budget - work);
            if (work >= budget) break;''')
edit('src/core/ex_loop.h', '''        return work;
    }

    uint32_t drain_releases(bool unmasked = false)''', '''        diag[6].fetch_add(work, std::memory_order_relaxed);
        diag[7].store((unsigned)srv_->flip_stage(), std::memory_order_relaxed);
        return work;
    }

    uint32_t drain_releases(bool unmasked = false)''')
edit('src/core/server.h', '        flip_error_ = error;', '''
        for (uint32_t tid = 0; tid < nthreads(); ++tid)
            if (thread(tid).role() == Role::Ex) {
                std::fprintf(stderr, "FLIPFIX6 owner epoch=%llu ex=%u cleanup=",
                    (unsigned long long)flip_epoch(), tid);
                for (unsigned n = 0; n < 8; ++n)
                    std::fprintf(stderr, "%s%llu", n ? "," : "",
                        (unsigned long long)flipfix6_diag_owner[tid][n].load(std::memory_order_relaxed));
                std::fprintf(stderr, "\\n");
            }
        flip_error_ = error;''')
