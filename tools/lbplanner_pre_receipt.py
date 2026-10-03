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
p = pre / 'tests/core_concurrency_unit.cc'
s = p.read_text().replace('int main(int argc, char** argv) {', '#ifndef TOMO_CORE_CONCURRENCY_EMBED\nint main(int argc, char** argv) {', 1)
s += '\n#endif\n'
s = s.replace('    static void snapshot_forward()', '''    static bool lbplanner_parse_gate(const IoLoop& io, uint64_t id) {
        return io.lb_controller_armed_ && io.srv_->lb_should_pause(io.self_->id(), id);
    }
    static uint32_t lbplanner_control(IoLoop& io) { return io.lb_control_pass(); }
    static void snapshot_forward()''', 1)
p.write_text(s)
unit = root / 'build/lbplanner-pre-pass.cc'
unit.write_text('''#define TOMO_CORE_CONCURRENCY_EMBED
#include "tests/core_concurrency_unit.cc"
extern "C" __attribute__((noinline)) bool lbplanner_parse_gate(const tomo::IoLoop* io, uint64_t id) {
    return tomo::CoreConcurrencyTest::lbplanner_parse_gate(*io, id);
}
extern "C" __attribute__((noinline)) uint32_t lbplanner_io_pass(tomo::IoLoop* io, uint32_t count) {
    uint32_t result = tomo::CoreConcurrencyTest::lbplanner_control(*io);
    for(uint32_t id=1; id<=count; ++id) result += lbplanner_parse_gate(io,id);
    return result;
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
''')
print('PRE source frozen at cd02ecbab; extra Makefile emitted')
