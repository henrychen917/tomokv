#!/usr/bin/env python3
"""flipfix5 DIAGNOSTIC v2 (on top of v1): stage-sample epoch, ack token, flip begin/finish times,
and involuntary context switches across the sampled ExInstall pass."""
import sys
from pathlib import Path
root = Path(sys.argv[1])

def patch(rel, old, new, count=1):
    p = root / rel
    t = p.read_text()
    n = t.count(old)
    if n != count:
        raise SystemExit(f'{rel}: expected {count} occurrence(s), found {n}: {old[:80]!r}')
    p.write_text(t.replace(old, new))

mq = 'src/exec/masked_queue.h'
patch(mq, 'inline uint64_t (*g_ff5_push_state)(uint32_t consumer, uint32_t producer) = nullptr;',
      '''inline uint64_t (*g_ff5_push_state)(uint32_t consumer, uint32_t producer) = nullptr;
inline std::atomic<uint64_t> g_ff5_begin_ns{0}, g_ff5_begin_epoch{0};
inline std::atomic<uint64_t> g_ff5_finish_ns{0}, g_ff5_finish_epoch{0};''')

sv = 'src/core/server.h'
patch(sv, '''        flip_epoch_.fetch_add(1, std::memory_order_acq_rel);
        flip_deadline_ns_.store(now_ns() + 5ull * 1000 * 1000 * 1000,
                                std::memory_order_release);
        flip_stage_.store(FlipStage::IoDrain, std::memory_order_release);''', '''        flip_epoch_.fetch_add(1, std::memory_order_acq_rel);
        g_ff5_begin_epoch.store(flip_epoch(), std::memory_order_relaxed);
        g_ff5_begin_ns.store(ff5_now_ns(), std::memory_order_relaxed);
        flip_deadline_ns_.store(now_ns() + 5ull * 1000 * 1000 * 1000,
                                std::memory_order_release);
        flip_stage_.store(FlipStage::IoDrain, std::memory_order_release);''')
patch(sv, '''        flip_completed_.fetch_add(1, std::memory_order_relaxed);
        flip_stage_.store(FlipStage::Idle, std::memory_order_release);
        flip_deadline_ns_.store(0, std::memory_order_release);
    }''', '''        flip_completed_.fetch_add(1, std::memory_order_relaxed);
        g_ff5_finish_epoch.store(flip_epoch(), std::memory_order_relaxed);
        g_ff5_finish_ns.store(ff5_now_ns(), std::memory_order_relaxed);
        flip_stage_.store(FlipStage::Idle, std::memory_order_release);
        flip_deadline_ns_.store(0, std::memory_order_release);
    }
    uint64_t ff5_ack_token(uint32_t tid) const { return flip_ack_[tid].load(std::memory_order_acquire); }''')

ex = 'src/core/ex_loop.h'
patch(ex, '''    uint32_t flip_control_pass() {
        const FlipStage stage = srv_->flip_stage();''', '''    struct Ff5Sample {
        uint64_t sample_ns = 0, epoch_before = 0, epoch_after = 0;
        long nivcsw = -1, nvcsw = -1;
        uint64_t exinstall_ack_ns = 0, exinstall_ack_epoch = 0;
    };
    inline static Ff5Sample ff5_samples_[kMaxThreads];
    uint32_t flip_control_pass() {
        Ff5Sample& ff5 = ff5_samples_[self_->id()];
        const uint64_t ff5_epoch_before = srv_->flip_epoch();
        const FlipStage stage = srv_->flip_stage();
        if (stage == FlipStage::ExInstall) {
            ff5.epoch_before = ff5_epoch_before;
            ff5.epoch_after = srv_->flip_epoch();
            ff5.sample_ns = ff5_now_ns();
            rusage ru{};
            getrusage(RUSAGE_THREAD, &ru);
            ff5.nivcsw = ru.ru_nivcsw;
            ff5.nvcsw = ru.ru_nvcsw;
        }''')
patch(ex, '''            for (Shard* shard : self_->shards())
                shard->bind_notify_pending(&notify_keyless_pending_);
            srv_->flip_ack(self_->id(), stage);
            return 1;
        }
        if (stage == FlipStage::Rollback && !srv_->flip_acked(self_->id(), stage)) {''', '''            for (Shard* shard : self_->shards())
                shard->bind_notify_pending(&notify_keyless_pending_);
            ff5.exinstall_ack_ns = ff5_now_ns();
            ff5.exinstall_ack_epoch = srv_->flip_epoch();
            srv_->flip_ack(self_->id(), stage);
            return 1;
        }
        if (stage == FlipStage::Rollback && !srv_->flip_acked(self_->id(), stage)) {''')
patch(ex, '''        std::fprintf(out, "FF5 io=");''', '''        {
            rusage ru{};
            getrusage(RUSAGE_THREAD, &ru);
            const uint64_t token = srv_->ff5_ack_token(self_->id());
            std::fprintf(out, "FF5 sample stage=ExInstall epoch_before_stage_load=%llu epoch_after_stage_load=%llu "
                         "sample_ns=%llu now_ns=%llu held_ns=%llu nivcsw_sample=%ld nivcsw_now=%ld nvcsw_sample=%ld nvcsw_now=%ld\\n",
                         static_cast<unsigned long long>(ff5_samples_[self_->id()].epoch_before),
                         static_cast<unsigned long long>(ff5_samples_[self_->id()].epoch_after),
                         static_cast<unsigned long long>(ff5_samples_[self_->id()].sample_ns),
                         static_cast<unsigned long long>(ff5_now_ns()),
                         static_cast<unsigned long long>(ff5_now_ns() - ff5_samples_[self_->id()].sample_ns),
                         ff5_samples_[self_->id()].nivcsw, ru.ru_nivcsw, ff5_samples_[self_->id()].nvcsw, ru.ru_nvcsw);
            std::fprintf(out, "FF5 ack token=0x%llx token_epoch=%llu token_stage=%u live_epoch=%llu own_exinstall_ack_epoch=%llu own_exinstall_ack_ns=%llu "
                         "last_finish_epoch=%llu last_finish_ns=%llu last_begin_epoch=%llu last_begin_ns=%llu\\n",
                         static_cast<unsigned long long>(token), static_cast<unsigned long long>(token >> 8),
                         unsigned(token & 0xff), static_cast<unsigned long long>(srv_->flip_epoch()),
                         static_cast<unsigned long long>(ff5_samples_[self_->id()].exinstall_ack_epoch),
                         static_cast<unsigned long long>(ff5_samples_[self_->id()].exinstall_ack_ns),
                         static_cast<unsigned long long>(g_ff5_finish_epoch.load()),
                         static_cast<unsigned long long>(g_ff5_finish_ns.load()),
                         static_cast<unsigned long long>(g_ff5_begin_epoch.load()),
                         static_cast<unsigned long long>(g_ff5_begin_ns.load()));
        }
        std::fprintf(out, "FF5 io=");''')
t = (root / ex).read_text()
if '#include <sys/resource.h>' not in t:
    t = '#include <sys/resource.h>\n' + t
(root / ex).write_text(t)
print('diag v2 applied')
