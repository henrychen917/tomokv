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
edit('src/core/server.h', '        flip_error_ = error;', '''        std::fprintf(stderr, "FLIPFIX6 failure epoch=%llu stage=%u deadline=%d error=%s\\n",
            (unsigned long long)flip_epoch(), (unsigned)flip_stage(), flip_timed_out(), error.c_str());
        flip_error_ = error;''')
print(DEST)
