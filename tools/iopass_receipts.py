#!/usr/bin/env python3
"""Serverless IO-pass instruction receipts, using the existing ptrace tracer.

The measured boundary is the production cron predicates, writer probes, completion
drain, full parser(s), and FLIP tail. It excludes network/clock/executor work.
No perf events, load generator, listener, or server loop is started.
"""
import argparse
import gzip
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
from lbstall_artifacts import Elf


def run(command, **kw):
    return subprocess.run(command, cwd=ROOT, check=True, text=True, **kw)


def emit(source, destination):
    core = (ROOT / 'tests/core_concurrency_unit.cc').read_text()
    # Reuse the existing fixture verbatim; do not change its setup or assertions.
    fixture = core[:core.index('    static void watch_disconnect()')]
    io = (source / 'src/core/io_loop.h').read_text()
    cron = re.search(r'const bool client_cron_armed = ([\s\S]*?);', io)[1]
    save = re.search(r'const bool save_cron_armed = ([\s\S]*?);', io)[1]
    begin = 'io.flip_pass_begin();' if 'void flip_pass_begin()' in io else ''
    aof = re.search(r'if \(([^\n]*writer_is\(self_->id\(\)\)[^\n]*)\)\n\s*did \+= srv_->aof\(\).writer_pass', io)
    if aof:
        writers = f'if ({aof[1]}) did += srv_->aof().writer_pass(*self_, ring_);\n'
    else:
        assert 'did += aof_writer_pass();' in io
        writers = 'did += aof_writer_pass();\n'
    snap = re.search(r'if \(([^\n]*writer_is\(self_->id\(\)\)[^\n]*)\)\n\s*did \+= srv_->snapshot\(\).writer_pass', io)
    if snap:
        writers += f'if ({snap[1]}) did += srv_->snapshot().writer_pass(*self_, ring_);\n'
    else:
        assert 'did += snapshot_writer_pass();' in io
        writers += 'did += snapshot_writer_pass();\n'
    # Qualify the exact production expressions inside the friend test wrapper.
    def qualify(text):
        return re.sub(r'(?<!->)\b(srv_|self_|ring_|save_cron_writer_|flip_dispatch_paused|aof_writer_pass|snapshot_writer_pass|aof_bound_)\b', r'io.\1', text)
    fixture += '''
    template<bool Fused>
    static uint32_t receipt_pass(Fixture<Fused>& f, Client** clients, uint32_t count) {
        auto& io = f.io;
        uint32_t did = 0;
        ''' + begin + '''
        const bool client_cron_armed = ''' + qualify(cron) + ''';
        const bool save_cron_armed = ''' + qualify(save) + ''';
        ''' + qualify(writers) + '''
        did += io.template collect_retire_work<false, false>();
        for (uint32_t i = 0; i < count; ++i)
            io.template parse_and_dispatch<false, Fused ? kGenthreadIfidBatchOps : 0>(clients[i]);
        did += io.template flip_control_pass<false>();
        return did + client_cron_armed + save_cron_armed;
    }
#include "tests/iopass_checks.inc"
};
} // namespace tomo
extern "C" __attribute__((noinline)) uint32_t iopass_boundary(
    tomo::CoreConcurrencyTest::Fixture<false>& f, tomo::Client** clients, uint32_t count) {
    return tomo::CoreConcurrencyTest::receipt_pass(f, clients, count);
}
namespace tomo {
uint32_t call_iopass_boundary(CoreConcurrencyTest::Fixture<false>& f, Client** clients, uint32_t count) {
    return iopass_boundary(f, clients, count);
}
}
int main(int argc, char** argv) {
    using T = tomo::CoreConcurrencyTest;
    T::require(argc == 2, "select iopass case");
    T::require(tomo::command_registry_init(false), "command registry");
    T::run_iopass(argv[1]);
}
'''
    destination.write_text(fixture)


def build(label, source):
    out = ROOT / 'build/iopass-receipts' / label
    out.mkdir(parents=True, exist_ok=True)
    emit(source, out / 'unit.cc')
    objects = sorted((ROOT / 'build/iopass-pre/src').rglob('*.o'))
    # As in lbplanner-unit, link the witness first so its inline definitions win
    # COMDAT selection. Frozen command/executor objects isolate the IO change.
    objects = [p for p in objects if p.name != 'main.o']
    flags = ['g++', '-std=c++20', '-O2', '-g', '-Wall', '-Wextra', '-march=native', '-pthread',
             '-DTOMO_JEMALLOC', '-DTOMO_CORE_CONCURRENCY_TEST', '-ffunction-sections',
             '-fdata-sections', '-I' + str(source), '-I' + str(ROOT)]
    with (out / 'build.log').open('w') as log:
        # Snapshot start may acquire an IO-private bound byte in IO4. Compile that
        # implementation from the same source as the witness for every arm.
        run(flags + ['-c', str(source / 'src/snapshot/snapshot.cc'), '-o', str(out / 'snapshot.o')], stdout=log, stderr=log)
        objects = [p for p in objects if p.name != 'snapshot.o']
        run(flags + [str(out / 'unit.cc'), str(out / 'snapshot.o')] + list(map(str, objects)) +
            ['-Wl,--gc-sections', '-o', str(out / 'unit'), '-ljemalloc', '-luring', '-lssl', '-lcrypto', '-lm'],
            stdout=log, stderr=log)
    return out / 'unit'


def trace(label, binary):
    tracer = ROOT / 'build/lbplanner-trace'
    if not tracer.exists():
        run(['g++', '-std=c++20', '-O2', str(ROOT / 'tools/lbplanner_trace.cc'), '-o', str(tracer)])
    elf = Elf(binary)
    sec = elf.sections[elf.names.index('.text')]
    address = elf.functions()['iopass_boundary']['value']
    rows = []
    for case in ('quiet', 'get32', 'set', 'atomic'):
        result = run(['taskset', '-c', '112-127', str(tracer), str(binary), case,
                      f'{address:x}', f'{sec[3]:x}', f'{sec[5]:x}', str(int(elf.kind == 3))],
                     capture_output=True, timeout=120)
        lines = result.stdout.splitlines()
        data = json.loads(next(x[6:] for x in lines if x.startswith('TRACE=')))
        sites = json.loads(next(x[6:] for x in lines if x.startswith('SITES=')))
        rows.append(dict(case=case, **data, sites=sites))
        print(label, case, data, flush=True)
    out = ROOT / 'docs/iopass'
    out.mkdir(parents=True, exist_ok=True)
    sites = {row['case']: row.pop('sites') for row in rows}
    with gzip.GzipFile(filename=str(out / (label + '.sites.json.gz')), mode='wb', mtime=0) as file:
        file.write(json.dumps(sites, sort_keys=True).encode())
    (out / (label + '.json')).write_text(json.dumps(dict(
        scope=__doc__, sha256=hashlib.sha256(binary.read_bytes()).hexdigest(),
        sites=label + '.sites.json.gz', rows=rows), indent=2) + '\n')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('label')
    parser.add_argument('--source', type=Path)
    parser.add_argument('--trace-only', action='store_true')
    args = parser.parse_args()
    source = args.source or ROOT / 'build/iopass-receipts' / args.label / 'source'
    if not source.exists():
        shutil.copytree(ROOT / 'src', source / 'src')
    binary = ROOT / 'build/iopass-receipts' / args.label / 'unit'
    if not args.trace_only:
        binary = build(args.label, source)
    trace(args.label, binary)
