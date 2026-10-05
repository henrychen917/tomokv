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
    fixture = fixture.replace('namespace tomo {\n', '''namespace tomo {
struct PersistFixTest {
    static void iopass_writer(AofManager& manager, uint32_t tid, bool configured) {
        manager.configured_ = configured;
        manager.writer_tid_ = tid;
    }
};
''', 1)
    io = (source / 'src/core/io_loop.h').read_text()
    cron = re.search(r'const bool client_cron_armed = ([\s\S]*?);', io)[1]
    save = re.search(r'const bool save_cron_armed = ([\s\S]*?);', io)[1]
    begin = 'io.flip_pass_begin();' if 'void flip_pass_begin()' in io else ''
    aof = re.search(r'if \(([^\n]*writer_is\(self_->id\(\)\)[^\n]*)\)\n\s*did \+= srv_->aof\(\).writer_pass', io)
    if aof:
        writers = f'if ({aof[1]}) did += srv_->aof().writer_pass(*self_, ring_);\n'
    else:
        assert 'if (aof_writer_bound())' in io
        writers = 'if (aof_writer_bound()) did += srv_->aof().writer_pass(*self_, ring_);\n'
    snap = re.search(r'if \(([^\n]*writer_is\(self_->id\(\)\)[^\n]*)\)\n\s*did \+= srv_->snapshot\(\).writer_pass', io)
    if snap:
        writers += f'if ({snap[1]}) did += srv_->snapshot().writer_pass(*self_, ring_);\n'
    else:
        assert 'if (snapshot_writer_bound())' in io
        writers += 'if (snapshot_writer_bound()) did += srv_->snapshot().writer_pass(*self_, ring_);\n'
    # Qualify the exact production expressions inside the friend test wrapper.
    def qualify(text):
        return re.sub(r'(?<!->)\b(srv_|self_|ring_|save_cron_writer_|flip_dispatch_paused|aof_writer_bound|snapshot_writer_bound|aof_bound_)\b', r'io.\1', text)
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


def build(label, source, checks=False):
    out = ROOT / 'build/iopass-receipts' / (label + ('-checks' if checks else ''))
    out.mkdir(parents=True, exist_ok=True)
    emit(source, out / 'unit.cc')
    objects = sorted((ROOT / 'build/iopass-pre/src').rglob('*.o'))
    # As in lbplanner-unit, link the witness first so its inline definitions win
    # COMDAT selection. Frozen command/executor objects isolate the IO change.
    objects = [p for p in objects if p.name != 'main.o']
    flags = ['g++', '-std=c++20', '-O2', '-g', '-Wall', '-Wextra', '-march=native', '-pthread',
             '-DTOMO_JEMALLOC', '-DTOMO_CORE_CONCURRENCY_TEST', '-ffunction-sections',
             '-fdata-sections', '-I' + str(source), '-I' + str(ROOT)]
    if checks:
        flags.append('-DTOMO_IOPASS_CHECKS')
    with (out / 'build.log').open('w') as log:
        # Snapshot start may acquire an IO-private bound byte in IO4. Compile that
        # implementation from the same source as the witness for every arm.
        run(flags + ['-c', str(source / 'src/snapshot/snapshot.cc'), '-o', str(out / 'snapshot.o')], stdout=log, stderr=log)
        objects = [p for p in objects if p.name != 'snapshot.o']
        run(flags + [str(out / 'unit.cc'), str(out / 'snapshot.o')] + list(map(str, objects)) +
            ['-Wl,--gc-sections', '-o', str(out / 'unit'), '-ljemalloc', '-luring', '-lssl', '-lcrypto', '-lm'],
            stdout=log, stderr=log)
    return out / 'unit'


def instruction_tracer():
    # x86 single-step traps after EACH REP iteration. Count the instruction once,
    # retain raw steps separately, and never collapse a self-branch or a SIMD F3 prefix.
    original = (ROOT / 'tools/lbplanner_trace.cc').read_text()
    source = original.replace(
        'unsigned long count=0,local=0; std::map<unsigned long,unsigned long> sites;',
        'unsigned long count=0,local=0,steps=0,rep_steps=0,last_rip=~0ul; '
        'bool last_rep=false; std::map<unsigned long,unsigned long> sites;')
    before = '''check(count<5000000,"instruction bound");++count; ++sites[regs.rip-base];
            if(regs.rip>=base+text_start && regs.rip<base+text_start+text_size)++local;'''
    after = '''check(++steps<5000000,"instruction bound");
            if(regs.rip==last_rip && last_rep) ++rep_steps;
            else { ++count; ++sites[regs.rip-base];
                if(regs.rip>=base+text_start && regs.rip<base+text_start+text_size)++local; }
            last_rip=regs.rip;
            unsigned long encoding=static_cast<unsigned long>(peek(child,regs.rip));
            bool rep=false; unsigned byte=0;
            for(unsigned i=0;i<sizeof(encoding);++i) {
                byte=(encoding>>(8*i))&255;
                if(byte==0xf2 || byte==0xf3) {rep=true;continue;}
                if((byte>=0x40 && byte<=0x4f) || byte==0x66 || byte==0x67 ||
                   byte==0x26 || byte==0x2e || byte==0x36 || byte==0x3e || byte==0x64 || byte==0x65) continue;
                break;
            }
            last_rep=rep && ((byte>=0xa4 && byte<=0xa7) || (byte>=0xaa && byte<=0xaf));'''
    assert source.count(before) == 1
    source = source.replace(before, after)
    source = source.replace('std::printf("SITES={");',
        'std::printf("STEPS={\\"ptrace_steps\\":%lu,\\"rep_iteration_steps\\":%lu}\\n",steps,rep_steps); '
        'std::printf("SITES={");')
    path, tracer = ROOT / 'build/iopass-trace.cc', ROOT / 'build/iopass-trace'
    if not path.exists() or path.read_text() != source or not tracer.exists():
        path.write_text(source)
        run(['g++', '-std=c++20', '-O2', str(path), '-o', str(tracer)])
    return tracer


def trace(label, binary):
    tracer = instruction_tracer()
    elf = Elf(binary)
    sec = elf.sections[elf.names.index('.text')]
    address = elf.functions()['iopass_boundary']['value']
    offsets = run(['gdb', '-nx', '-q', '-batch', str(binary), '-ex',
        'python import gdb,json; print("OFFSETS="+json.dumps({n:int(next(f for f in '
        'gdb.lookup_type("tomo::Server").fields() if f.name==n).bitpos)//8 '
        'for n in ("flip_stage_","live_save_armed_","placement_")}))'], capture_output=True)
    offsets = json.loads(next(s[8:] for s in offsets.stdout.splitlines() if s.startswith('OFFSETS=')))
    asm = run(['objdump', '-dw', str(binary)], capture_output=True).stdout
    decoded = {}
    for line in asm.splitlines():
        match = re.match(r'\s*([0-9a-f]+):\s+(?:[0-9a-f]{2} )+\s*(.*)', line)
        if match:
            decoded[match[1]] = match[2]
    rows = []
    for case in ('quiet', 'get32', 'set', 'atomic'):
        result = run(['taskset', '-c', '112-127', str(tracer), str(binary), case,
                      f'{address:x}', f'{sec[3]:x}', f'{sec[5]:x}', str(int(elf.kind == 3))],
                     capture_output=True, timeout=120)
        lines = result.stdout.splitlines()
        data = json.loads(next(x[6:] for x in lines if x.startswith('TRACE=')))
        data.update(json.loads(next(x[6:] for x in lines if x.startswith('STEPS='))))
        sites = json.loads(next(x[6:] for x in lines if x.startswith('SITES=')))
        loads = {}
        for field in ('flip_stage_', 'live_save_armed_'):
            selected = []
            for pc, visits in sites.items():
                instruction = decoded.get(pc, '')
                if f'0x{offsets[field]:x}(' not in instruction:
                    continue
                # MOV memory destinations are stores, not shared reads.
                if instruction.startswith('mov') and f'0x{offsets[field]:x}(' in instruction.split(',')[-1]:
                    continue
                selected.append(dict(pc=pc, visits=visits, instruction=instruction))
            loads[field] = dict(visits=sum(s['visits'] for s in selected), sites=selected)
        rows.append(dict(case=case, **data, shared_reads=loads, sites=sites))
        print(label, case, data, flush=True)
    out = ROOT / 'docs/iopass'
    out.mkdir(parents=True, exist_ok=True)
    sites = {row['case']: row.pop('sites') for row in rows}
    with gzip.GzipFile(filename=str(out / (label + '.sites.json.gz')), mode='wb', mtime=0) as file:
        file.write(json.dumps(sites, sort_keys=True).encode())
    (out / (label + '.json')).write_text(json.dumps(dict(
        scope=__doc__, sha256=hashlib.sha256(binary.read_bytes()).hexdigest(),
        offsets=offsets, sites=label + '.sites.json.gz', rows=rows), indent=2) + '\n')


def tracer_test():
    source = ROOT / 'build/iopass-trace-fixture.cc'
    source.write_text(r'''
#include <cstdlib>
extern "C" void iopass_boundary(char*, unsigned long);
asm(".text\n.globl iopass_boundary\n.type iopass_boundary,@function\n"
    "iopass_boundary:\nmov %rsi,%rcx\nmov $7,%eax\nrep stosb\nret\n"
    ".size iopass_boundary,.-iopass_boundary\n");
int main(int argc,char** argv) {
    if(argc!=2) return 1;
    unsigned n=std::atoi(argv[1]);
    if(n>128) return 1;
    char data[128];
    iopass_boundary(data,n);
    for(unsigned i=0;i<n;++i) if(data[i]!=7) return 1;
}
''')
    binary = source.with_suffix('')
    run(['g++', '-O2', str(source), '-o', str(binary)])
    elf = Elf(binary)
    sec = elf.sections[elf.names.index('.text')]
    symbol = elf.functions()['iopass_boundary']['value']
    for count in (0, 1, 64, 128):
        result = run(['taskset', '-c', '112-127', str(instruction_tracer()), str(binary), str(count),
                      f'{symbol:x}', f'{sec[3]:x}', f'{sec[5]:x}', str(int(elf.kind == 3))], capture_output=True)
        trace_row = json.loads(next(s[6:] for s in result.stdout.splitlines() if s.startswith('TRACE=')))
        steps = json.loads(next(s[6:] for s in result.stdout.splitlines() if s.startswith('STEPS=')))
        assert trace_row['instructions'] == trace_row['executable_instructions'] == 4, (count, trace_row)
        assert steps['rep_iteration_steps'] == max(0, count - 1), (count, steps)
        assert steps['ptrace_steps'] == 4 + max(0, count - 1), (count, steps)
        print('PASS tracer REP length', count, 'four instructions;', steps)


def layout():
    script = ROOT / 'build/iopass-layout.gdb'
    script.write_text('''set pagination off
python
import gdb,json
expected=dict(Op=336,Client=1984,ThreadCtx=1408,Shard=1440,FlatStore=944,AtomicEntry=144,Config=624)
expected['Rob<64>']=192
rows={}
for ns in ('tomo','tomo_db0'):
    sizes={name:int(gdb.lookup_type(ns+'::'+name).sizeof) for name in expected}
    assert sizes==expected,(ns,sizes)
    fields={}
    for name in ('IoLoop','ThreadCtx','Server'):
        t=gdb.lookup_type(ns+'::'+name)
        fields[name]=dict(size=int(t.sizeof),offsets={f.name:int(f.bitpos)//8 for f in t.fields() if hasattr(f,'bitpos')})
    rows[ns]=dict(locked=sizes,fields=fields)
print('LAYOUT='+json.dumps(rows))
end
''')
    rows = {}
    for arm, binary in [('PRE', ROOT / 'build/iopass-pre/tomokv'), ('POST', ROOT / 'build/tomokv')]:
        output = run(['gdb', '-nx', '-q', '-batch', str(binary), '-x', str(script)], capture_output=True).stdout
        fields = json.loads(next(s[7:] for s in output.splitlines() if s.startswith('LAYOUT=')))
        elf = Elf(binary)
        text = elf.sections[elf.names.index('.text')]
        parsers = []
        for name, symbol in elf.functions().items():
            if not re.match(r'^_ZN(?:4tomo|8tomo_db0)6IoLoop18parse_and_dispatchILb0ELj(?:0|32)ELb0ELb0EE', name) or name.endswith('.cold'):
                continue
            asm = run(['objdump', '-dw', '--disassemble=' + name, str(binary)], capture_output=True).stdout
            body = asm.split('<' + name + '>:\n', 1)[1]
            # Stack-clash protection splits PRE's fixed frame across several page-sized
            # SUBs. The first SUB alone is not its frame size. These parser entries have
            # straight-line prologues; stop before the first call/branch into their body.
            prologue = []
            for line in body.splitlines():
                if re.search(r'\s(?:call\S*|j\S+|ret\S*)\s', line):
                    break
                prologue.append(line)
            fixed = re.findall(r'sub\s+\$0x([0-9a-f]+),%rsp', '\n'.join(prologue))
            assert fixed, (arm, name, 'fixed stack subtraction missing')
            parsers.append(dict(symbol=name, bytes=symbol['size'],
                                fixed_stack_bytes=sum(int(part, 16) for part in fixed)))
        rows[arm] = dict(sha256=hashlib.sha256(binary.read_bytes()).hexdigest(), text_bytes=text[5],
                         layout=fields, parsers=parsers)
    for ns in rows['PRE']['layout']:
        for name, before in rows['PRE']['layout'][ns]['fields'].items():
            after = rows['POST']['layout'][ns]['fields'][name]
            assert before['size'] == after['size'], (ns, name, 'size moved')
            for field, offset in before['offsets'].items():
                assert after['offsets'][field] == offset, (ns, name, field, 'old field moved')
    old = (ROOT / 'build/iopass-receipts/IO6/source/src/core/io_loop.h').read_text()
    new = (ROOT / 'src/core/io_loop.h').read_text()
    def plain(source):
        start = source.index('                if (!scatter_dispatch.atomic_write) {')
        stop = source.index('\n                }\n\n', start) + len('\n                }')
        return source[start:stop]
    assert plain(old) == plain(new), 'plain scatter arm changed'
    rows['plain_scatter_body_sha256'] = hashlib.sha256(plain(new).encode()).hexdigest()
    rows['all_existing_offsets_and_sizes_equal'] = True
    (ROOT / 'docs/iopass/layout.json').write_text(json.dumps(rows, indent=2) + '\n')
    print('PASS all eight locks, both namespaces; every existing IoLoop/ThreadCtx/Server offset and size unchanged; plain scatter source identical')
    for arm in ('PRE', 'POST'):
        print(arm, 'sha256', rows[arm]['sha256'], 'text', rows[arm]['text_bytes'], 'parsers', rows[arm]['parsers'])


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('label', nargs='?')
    parser.add_argument('--source', type=Path)
    parser.add_argument('--trace-only', action='store_true')
    parser.add_argument('--checks', action='store_true')
    parser.add_argument('--tracer-test', action='store_true')
    parser.add_argument('--layout', action='store_true')
    args = parser.parse_args()
    if args.tracer_test:
        tracer_test()
        sys.exit(0)
    if args.layout:
        layout()
        sys.exit(0)
    assert args.label, 'select a receipt label'
    source = args.source or ROOT / 'build/iopass-receipts' / args.label / 'source'
    if not source.exists():
        shutil.copytree(ROOT / 'src', source / 'src')
    binary = ROOT / 'build/iopass-receipts' / args.label / 'unit'
    if not args.trace_only:
        binary = build(args.label, source, args.checks)
    if args.checks:
        run(['taskset', '-c', '112-127', str(binary), 'checks'])
    else:
        trace(args.label, binary)
