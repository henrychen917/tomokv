#!/usr/bin/env python3
"""Build-only S1 schedule: same latch placement in PRE and POST, no production hook.

The owner pauses after finish_completions' failed() guard, before the receipt gate.
The faulting writer waits for that pause, then wakes it after changing failure state.
The live row holds the writer's diagnostic on a full pipe until the reply is checked.
"""
from pathlib import Path
import sys

source, destination = map(Path, sys.argv[1:])
text = source.read_text()
declaration = '''
namespace {
std::atomic<unsigned> persistfmt_schedule{0};
bool persistfmt_armed() {
    const char* path = std::getenv("TOMO_PERSISTFMT_SCHEDULE");
    return path && ::access(path, F_OK) == 0;
}
}
'''
text = text.replace('namespace tomo {', 'namespace tomo {\n' + declaration, 1)
before_gate = '        if (!reply_gate_ready(front.target)) {'
assert text.count(before_gate) == 1
text = text.replace(before_gate, '''
        if (persistfmt_armed() && persistfmt_schedule.load() < 2) {
            persistfmt_schedule.store(1);
            while (persistfmt_schedule.load() != 2) std::this_thread::yield();
        }
''' + before_gate)
before_fail = 'void AofManager::fail(const char* message, int error) {'
assert text.count(before_fail) == 1
text = text.replace(before_fail, before_fail + '''
    if (persistfmt_armed())
        while (persistfmt_schedule.load() == 0) std::this_thread::yield();
''')
diagnostic = '    std::fprintf(stderr, "AOF error: %s\\n", message ? message : "AOF failure");'
assert text.count(diagnostic) == 1
text = text.replace(diagnostic, '    if (persistfmt_armed()) persistfmt_schedule.store(2);\n' + diagnostic)
destination.parent.mkdir(parents=True, exist_ok=True)
destination.write_text(text)
