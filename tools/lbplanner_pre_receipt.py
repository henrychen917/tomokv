#!/usr/bin/env python3
"""Freeze launch source and emit a PRE serverless pass witness; never compile or run it."""
import io
from pathlib import Path
import subprocess
import tarfile

root = Path(__file__).resolve().parents[1]
pre = root / 'build/lbplanner-pre-source'
pre.mkdir(parents=True, exist_ok=True)
archive = subprocess.check_output(['git', 'archive', 'cd02ecbab', 'src', 'tests', 'third_party', 'Makefile'], cwd=root)
with tarfile.open(fileobj=io.BytesIO(archive)) as tar:
    tar.extractall(pre, filter='data')
# The historical measurement PRE predates later merged mainline fields. Freeze the
# fix's actual launch source separately so its layout check does not forgive drift.
launch = root / 'build/lbplanner-launch-source'
launch.mkdir(parents=True, exist_ok=True)
archive = subprocess.check_output(['git', 'archive', '6c9cb4b85', 'src', 'third_party'], cwd=root)
with tarfile.open(fileobj=io.BytesIO(archive)) as tar:
    tar.extractall(launch, filter='data')
(root / 'build/lbplanner-launch-layout.cc').write_text('#include "src/core/io_loop.h"\n')
p = pre / 'tests/core_concurrency_unit.cc'
s = p.read_text().replace('int main(int argc, char** argv) {', '#ifndef TOMO_CORE_CONCURRENCY_EMBED\nint main(int argc, char** argv) {', 1)
s += '\n#endif\n'
s = s.replace('    static void snapshot_forward()', '''    static bool lbplanner_parse_gate(const IoLoop& io, uint64_t id) {
        return io.lb_controller_armed_ && io.srv_->lb_should_pause(io.self_->id(), id);
    }
    static uint32_t lbplanner_control(IoLoop& io) { return io.lb_control_pass(); }
    static void snapshot_forward()''', 1)
p.write_text(s)
# Compile the same contention/arrival schedule against the frozen PRE actuator.
# Friend access is test-only; no production expression or fixture expectation changes.
for name in ('src/core/server.h', 'src/core/io_loop.h'):
    p = pre / name
    p.write_text(p.read_text().replace('    friend struct CoreConcurrencyTest;',
                                     '    friend struct CoreConcurrencyTest;\n    friend struct LbPlannerTest;', 1))
driver = (root / 'tests/lbplanner_unit.cc').read_text()
def region(start, end):
    return driver[driver.index(start):driver.index(end) + len(end)]
timing = root / 'build/lbplanner-pre-timing.cc'
timing.write_text('''#define TOMO_CORE_CONCURRENCY_EMBED
#define TOMO_LBPLANNER_PRE
#include "tests/core_concurrency_unit.cc"
#include <latch>
''' + region('// BEGIN timing wrappers', '// END timing wrappers') + '''
namespace tomo { struct LbPlannerTest {
    using Core = CoreConcurrencyTest;
    static void require(bool yes, const char* why) { Core::require(yes, why); }
''' + region('    // BEGIN client-drain timing witness', '    // END client-drain timing witness') + '''
}; }
int main() { tomo::LbPlannerTest::timing("PRE", true); }
''')
unit = root / 'build/lbplanner-pre-pass.cc'
unit.write_text('''#define TOMO_CORE_CONCURRENCY_EMBED
#include "tests/core_concurrency_unit.cc"
extern "C" __attribute__((noinline)) bool lbplanner_parse_gate(const tomo::IoLoop* io, uint64_t id) {
    return tomo::CoreConcurrencyTest::lbplanner_parse_gate(*io, id);
}
extern "C" __attribute__((noinline)) uint32_t lbplanner_io_pass(tomo::IoLoop* io, uint32_t count) {
    uint32_t result = 0;
    for(uint32_t id=1; id<=count; ++id) result += lbplanner_parse_gate(io,id);
    return result + tomo::CoreConcurrencyTest::lbplanner_control(*io);
}
int main(int argc, char** argv) {
    if(argc!=2) return 2;
    tomo::CoreConcurrencyTest::Fixture<false> f;
    return lbplanner_io_pass(&f.io,std::strtoul(argv[1],nullptr,10));
}
''')
(root/'build/lbplanner-extra.mk').write_text('''include Makefile
LBPLANNER_PRE_OBJ := $(filter-out build/lbplanner-pre/src/main.o,$(wildcard build/lbplanner-pre/src/*/*.o))
build/lbplanner-pre-pass: build/lbplanner-pre-pass.cc $(LBPLANNER_PRE_OBJ)
	$(CXX) $(CXXFLAGS) $(JEFLAGS) -DTOMO_CORE_CONCURRENCY_TEST -Ibuild/lbplanner-pre-source -I. $< $(LBPLANNER_PRE_OBJ) -o $@ $(JELIBS) $(LDLIBS) -lm
build/lbplanner-pre-timing: build/lbplanner-pre-timing.cc $(LBPLANNER_PRE_OBJ)
	$(CXX) $(CXXFLAGS) $(JEFLAGS) -DTOMO_CORE_CONCURRENCY_TEST -Ibuild/lbplanner-pre-source -I. $< $(LBPLANNER_PRE_OBJ) -o $@ $(JELIBS) $(LDLIBS) -lm -Wl,--wrap=pthread_mutex_trylock -Wl,--wrap=pthread_mutex_lock
build/lbplanner-launch-layout.o: build/lbplanner-launch-layout.cc
	$(CXX) $(CXXFLAGS) $(JEFLAGS) -fno-eliminate-unused-debug-types -Ibuild/lbplanner-launch-source -I. -c $< -o $@
build/lbplanner-launch-layout-db0.o: build/lbplanner-launch-layout.cc
	$(CXX) $(CXXFLAGS) $(JEFLAGS) -fno-eliminate-unused-debug-types -DTOMO_SINGLE_DATABASE=1 -Dtomo=tomo_db0 -Ibuild/lbplanner-launch-source -I. -c $< -o $@
''')
print('PRE source frozen at cd02ecbab; extra Makefile emitted')
