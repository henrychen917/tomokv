#!/usr/bin/env python3
"""flipfix5 DIAGNOSTIC v3 (on top of v1+v2): no syscall inside the stage-sample -> ack-check window.
rusage is taken before the stage load; vDSO timestamps at the sample and at the ack check."""
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

ex = 'src/core/ex_loop.h'
patch(ex, '''    struct Ff5Sample {
        uint64_t sample_ns = 0, epoch_before = 0, epoch_after = 0;
        long nivcsw = -1, nvcsw = -1;
        uint64_t exinstall_ack_ns = 0, exinstall_ack_epoch = 0;
    };''', '''    struct Ff5Sample {
        uint64_t sample_ns = 0, epoch_before = 0, epoch_after = 0;
        long nivcsw = -1, nvcsw = -1;
        uint64_t exinstall_ack_ns = 0, exinstall_ack_epoch = 0;
        uint64_t check_ns = 0, check_epoch = 0;
    };''')
patch(ex, '''        Ff5Sample& ff5 = ff5_samples_[self_->id()];
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
        }''', '''        Ff5Sample& ff5 = ff5_samples_[self_->id()];
        long ff5_nivcsw = -1, ff5_nvcsw = -1;
        if (srv_->flip_stage() == FlipStage::ExInstall) {
            rusage ru{};
            getrusage(RUSAGE_THREAD, &ru);   // outside the window: before the stage load
            ff5_nivcsw = ru.ru_nivcsw;
            ff5_nvcsw = ru.ru_nvcsw;
        }
        const uint64_t ff5_epoch_before = srv_->flip_epoch();
        const FlipStage stage = srv_->flip_stage();
        const uint64_t ff5_sample_ns = ff5_now_ns();   // vDSO, no kernel entry
        if (stage == FlipStage::ExInstall) {
            ff5.epoch_before = ff5_epoch_before;
            ff5.epoch_after = srv_->flip_epoch();
            ff5.sample_ns = ff5_sample_ns;
            ff5.nivcsw = ff5_nivcsw;
            ff5.nvcsw = ff5_nvcsw;
        }''')
patch(ex, EXINSTALL_OLD,
      '''        if (stage == FlipStage::ExInstall) {
            ff5.check_ns = ff5_now_ns();
            ff5.check_epoch = srv_->flip_epoch();
        }
''' + EXINSTALL_OLD[8:] )
patch(ex, '''            std::fprintf(out, "FF5 ack token=0x%llx''', '''            std::fprintf(out, "FF5 window sample_ns=%llu check_ns=%llu window_ns=%llu check_epoch=%llu\\n",
                         static_cast<unsigned long long>(ff5_samples_[self_->id()].sample_ns),
                         static_cast<unsigned long long>(ff5_samples_[self_->id()].check_ns),
                         static_cast<unsigned long long>(ff5_samples_[self_->id()].check_ns -
                                                         ff5_samples_[self_->id()].sample_ns),
                         static_cast<unsigned long long>(ff5_samples_[self_->id()].check_epoch));
            std::fprintf(out, "FF5 ack token=0x%llx''')
print('diag v3 applied')
