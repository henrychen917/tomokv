#!/usr/bin/env python3
"""Build-only S1 schedule: same latch placement in PRE and POST, no production hook.

The owner pauses after finish_completions' failed() guard, before the receipt gate.
The faulting writer waits for that pause, then wakes it after changing failure state.
The live row holds the writer's diagnostic on a full pipe until the reply is checked.
Markers distinguish an armed S1 window from owner work held by the injected
latches. A fresh attempt is required when the gate and writer cannot rendezvous.
"""
from pathlib import Path
import sys
import source_tokens as cpp

source, destination = map(Path, sys.argv[1:])
text = cpp.read(source)
declaration = '''
namespace {
std::atomic<unsigned> persistfmt_schedule{0};
bool persistfmt_armed() {
    const char* path = std::getenv("TOMO_PERSISTFMT_SCHEDULE");
    return path && ::access(path, F_OK) == 0;
}
bool persistfmt_marker(const char* suffix, uint32_t producer = UINT32_MAX) {
    const char* base = std::getenv("TOMO_PERSISTFMT_SCHEDULE");
    if (!base) std::abort();
    const std::string path = std::string(base) + suffix;
    const int fd = ::open(path.c_str(), O_WRONLY | O_CREAT | O_EXCL | O_CLOEXEC, 0600);
    if (fd < 0) { if (errno == EEXIST) return false; std::abort(); }
    char bytes[96];
    const int size = std::snprintf(bytes, sizeof(bytes), "%ld %u %u\\n",
        static_cast<long>(::gettid()), producer, persistfmt_schedule.load());
    if (size <= 0 || ::write(fd, bytes, static_cast<size_t>(size)) != size) std::abort();
    if (::close(fd) != 0) std::abort();
    return true;
}
}
'''
text = text.replace('namespace tomo {', 'namespace tomo {\n' + declaration, 1)
writer_guard = '    if (!configured_ || writer.id() != writer_tid_ || fd_ < 0 || failed()) return 0;'
assert text.count(writer_guard) == 1
text = text.replace(writer_guard, writer_guard + '''
    // Leave the fused writer free to finish its FLUSH owner work before the
    // faulting write. Spinning inside fail() before that work deadlocks the
    // artificial rendezvous. This delay changes only the scheduling twin.
    if (persistfmt_armed() && persistfmt_schedule.load() == 0) {
        persistfmt_marker(".deferred", writer.id());
        return 0;
    }
''')
before_gate = '        if (!reply_gate_ready(front.target)) {'
assert text.count(before_gate) == 1
text = text.replace(before_gate, '''
        if (persistfmt_armed() && persistfmt_schedule.load() < 2) {
            persistfmt_marker(".gate", producer);
            persistfmt_schedule.store(1);
            while (persistfmt_schedule.load() != 2) std::this_thread::yield();
        }
''' + before_gate)
before_fail = 'void AofManager::fail(const char* message, int error) {'
assert text.count(before_fail) == 1
text = text.replace(before_fail, before_fail + '''
    bool persistfmt_fault_writer = false;
    if (persistfmt_armed()) {
        persistfmt_fault_writer = persistfmt_marker(".fail");
        while (persistfmt_schedule.load() == 0) std::this_thread::yield();
    }
''')
diagnostic = '    std::fprintf(stderr, "AOF error: %s\\n", message ? message : "AOF failure");'
assert text.count(diagnostic) == 1
text = text.replace(diagnostic, '''
    if (persistfmt_armed()) {
        persistfmt_schedule.store(2);
        if (persistfmt_fault_writer) persistfmt_marker(".diagnostic");
        // Any concurrent failure reporter may own stderr's FILE lock. Record
        // every logger so the driver can identify the actual pipe waiter.
        const std::string suffix = ".logging-" + std::to_string(static_cast<long>(::gettid()));
        persistfmt_marker(suffix.c_str());
    }
''' + diagnostic)
destination.parent.mkdir(parents=True, exist_ok=True)
destination.write_text(text)
