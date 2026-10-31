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
