from pathlib import Path
import os
import subprocess
import sys

ROOT = Path.cwd()
OUT = ROOT / 'build/reorderscan2-evidence/witnesses'
OUT.mkdir(parents=True, exist_ok=True)
assert set(os.sched_getaffinity(0)) <= set(range(112, 128))
sys.path.insert(0, str(ROOT / 'tools'))
import iopass_receipts
flags = ['g++', '-std=c++20', '-O2', '-g', '-Wall', '-Wextra', '-march=native', '-pthread',
         '-DTOMO_JEMALLOC', '-I.']
objects = sorted((ROOT / 'build/src').rglob('*.o'))
objects = [str(p) for p in objects if p.name not in ('main.o', 'reorder.o')]
libs = ['-ljemalloc', '-luring', '-lssl', '-lcrypto', '-lm']
def run(name, command):
    print('RUN', name, flush=True)
    with (OUT / (name + '.log')).open('w') as log:
        result = subprocess.run(command, stdout=log, stderr=subprocess.STDOUT)
    if result.returncode:
        print((OUT / (name + '.log')).read_text(), flush=True)
        raise SystemExit(result.returncode)
    print('PASS', name, flush=True)

if '--iopass-only' not in sys.argv:
    witness_flags = flags + ['-DTOMO_R7_WITNESS', '-include', 'tests/reorderscan_witness.h', '-include', 'tests/r7shadow_witness.h']
    reorder = str(OUT / 'reorder.o')
    run('instrumented-reorder-build', witness_flags + ['-c', 'src/core/reorder.cc', '-o', reorder])
    run('paths-build', witness_flags + ['tests/reorderscan_paths.cc', reorder] + objects + ['-o', str(OUT / 'paths')] + libs)
    run('paths', [str(OUT / 'paths'), 'post'])

    source = OUT / 'default.cc'
    source.write_text(r'''
    #define main inherited_engagement_main
    #include "tests/reorder_engagement_unit.cc"
    #undef main
    int main(int argc, char** argv) {
        using T = tomo::CoreConcurrencyTest;
        using namespace tomo;
        T::require(argc == 2, "default or positive arm required");
        T::require(command_registry_init(false), "registry");
        r7_witness::paths = r7_witness::allocations = 0;
        for (auto mode : {ThreadMode::Fused, ThreadMode::Split})
            for (uint32_t overlap : {0u, 1u}) {
                T::run<true>(mode, overlap, 0, true);
                T::shadow_pipes<true>(mode, overlap, 0);
                T::io_dispatch_membership<true>(mode, overlap, 0);
                T::io_dispatch_membership<false>(mode, overlap, 0);
                T::shadow_pipes<false>(mode, overlap, 0);
            }
        T::database_dispatch(0);
        T::require(r7_witness::paths == 0 && r7_witness::allocations == 0,
                   "reorder 0 entered R7 or allocated R7 state");
        std::puts("PASS reorder 0: both modes/overlap/read-local/database paths; zero R7 entries and allocations");
        if (std::string(argv[1]) == "positive") {
            T::shadow_foreign_passes();
            T::require(r7_witness::paths > 0 && r7_witness::allocations > 0,
                       "armed path/allocation positive control never fired");
            std::puts("PASS R7 path/allocation positive control");
        } else if (std::string(argv[1]) == "leak") {
            T::shadow_foreign_passes();
            T::require(r7_witness::paths == 0, "deliberate R7 entry rejected");
        }
    }
    ''')
    run('default-build', witness_flags + [str(source), reorder] + objects + ['-o', str(OUT / 'default')] + libs)
    run('default', [str(OUT / 'default'), 'positive'])
    negative = subprocess.run([str(OUT / 'default'), 'leak'], text=True, capture_output=True)
    (OUT / 'default-negative.log').write_text(negative.stdout + negative.stderr)
    assert negative.returncode == 1 and 'deliberate R7 entry rejected' in negative.stderr
    print('PASS default negative control', flush=True)

for armed in (False, True):
    name = 'iopass-armed' if armed else 'iopass'
    unit = OUT / (name + '.cc')
    iopass_receipts.emit(ROOT, unit)
    if armed:
        text = unit.read_text()
        needle = '#include "tests/iopass_checks.inc"'
        assert text.count(needle) == 1
        checks = (ROOT / 'tests/iopass_checks.inc').read_text()
        flip = checks[checks.index('template<class F> static void flip_fences('):checks.index('template<class F> static void writer_fences(')]
        flip = flip.replace('flip_fences(', 'flip_fences_r7(').replace('parse_and_dispatch<false, 0>', 'r7_parse_and_dispatch<false, kGenthreadIfidBatchOps>')
        atomic = checks[checks.index('template<bool Fused> static void atomic_scatter_cases('):]
        atomic = atomic.replace('atomic_scatter_cases(', 'atomic_scatter_cases_r7(').replace('template parse_and_dispatch<', 'template r7_parse_and_dispatch<')
        atomic = atomic.replace('input(client, request("MSET", true));', '''input(client, request("MSET", true));
    require(command_length_class(*command_lookup(Slice("MSET"))) == CommandLengthClass::Long,
            "atomic scatter Long index witness must arm");''')
        atomic = atomic.replace('        clean();\n        require(owner.drain_tasks_unmasked', '''        clean();
        require(r7::ShadowLongIndex::pending_before(client, UINT64_MAX) == UINT64_MAX,
                "refused atomic scatter left a ghost Long");
        require(owner.drain_tasks_unmasked''')
        atomic = atomic.replace('        require(client.has_atomic_group_io() == atomic,', '''        require(r7::ShadowLongIndex::pending_before(client, client.rob().dispatch_id()) ==
                    (atomic ? client.rob().dispatch_id() - 1 : UINT64_MAX),
                "atomic scatter publication omitted Long index or retained retired entry");
        require(client.has_atomic_group_io() == atomic,''')
        extra = '''
    static void run_r7_iopass() {
        Fixture<true> fresh(false);
        fresh.io.bind_fused_executor(&fresh.loops[fresh.io_id]);
        fresh.loops[fresh.io_id].bind_fused_completion(&fresh.io, [](void* p, Client* c) {
            static_cast<IoLoop*>(p)->fused_executor_completion(c);
        });
        flip_fences_r7(fresh);
        atomic_scatter_cases_r7<true>();
        atomic_scatter_cases_r7<true>(256);
    }
'''
        text = text.replace(needle, needle + '\n' + flip + atomic + extra)
        text = text.replace('command_registry_init(false)', 'command_registry_init(false, false, true)')
        text = text.replace('T::run_iopass(argv[1]);', 'T::run_iopass(argv[1]);\n    T::run_r7_iopass();')
        text = '#include "src/core/reorder.h"\n' + text
        unit.write_text(text)
    testflags = flags + ['-DTOMO_CORE_CONCURRENCY_TEST', '-DTOMO_IOPASS_CHECKS', '-ffunction-sections', '-fdata-sections']
    run(name + '-build', testflags + [str(unit), str(ROOT / 'build/src/core/reorder.o')] + objects + ['-Wl,--gc-sections', '-o', str(OUT / name)] + libs)
    run(name, [str(OUT / name), 'checks'])

# Remove only the new delegated-publication rollback in a disposable generated
# copy. The augmented IO7 witness must reject a ghost Long on actual refusal.
broken = (ROOT / 'src/core/reorder.cc').read_text()
needle = '''if (!dispatch_atomic_scatter(c, *op, scatter_dispatch)) {
                r7::ShadowLongIndex::unpublish(*c);
                break;
            }'''
assert broken.count(needle) == 1
broken = broken.replace(needle, 'if (!dispatch_atomic_scatter(c, *op, scatter_dispatch)) break;')
negative_source = OUT / 'missing-atomic-rollback.cc'
negative_source.write_text(broken)
negative_object = OUT / 'missing-atomic-rollback.o'
run('atomic-rollback-negative-build', flags + ['-iquote', 'src/core', '-c', str(negative_source), '-o', str(negative_object)])
negative_binary = OUT / 'missing-atomic-rollback'
run('atomic-rollback-negative-link', testflags + [str(unit), str(negative_object)] + objects +
    ['-Wl,--gc-sections', '-o', str(negative_binary)] + libs)
negative = subprocess.run([str(negative_binary), 'checks'], text=True, capture_output=True)
(OUT / 'atomic-rollback-negative.log').write_text(negative.stdout + negative.stderr)
assert negative.returncode == 1 and 'refused atomic scatter left a ghost Long' in negative.stderr
print('PASS atomic rollback negative control', flush=True)
