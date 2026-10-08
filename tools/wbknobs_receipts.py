#!/usr/bin/env python3
"""Offline writeback knob instruction/layout receipts. Never starts a server or load."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
from lbstall_artifacts import Elf

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'docs/wbknobs'
BUILD = ROOT / 'build/wbknobs'
FLAGS = ['g++', '-std=c++20', '-O2', '-g', '-Wall', '-Wextra', '-march=native',
         '-pthread', '-DTOMO_JEMALLOC']


def run(argv):
    result = subprocess.run(list(map(str, argv)), cwd=ROOT, capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr
    return result.stdout


def sha(path):
    with path.open('rb') as file:
        return hashlib.file_digest(file, 'sha256').hexdigest()


def costs():
    tracer = BUILD / 'instruction-trace'
    run(FLAGS + ['tools/wb_rule_2s_trace.cc', '-o', tracer])
    standard = [(1, 0, 0, 1, 0), (64, 1, 0, 0, 0), (64, 0, 512, 1, 0)]
    standard += [(n, done, 0, 1, 0) for n in (8, 16, 17, 32, 33, 64) for done in (0, 1, n)]
    standard += [(64, 1, 0, 1, 1)]
    extra = [(n, done, 0, 1, 0) for n in (4, 8, 16, 17, 32, 64) for done in (0, 1, n//2, n)]
    extra += [(8, 1, 0, 1, 1)]
    fixtures = list(dict.fromkeys(standard + extra))
    cases = ['trace-' + '-'.join(map(str, (*f, count))) for f in fixtures for count in range(4)]
    cases += [f'codes-{done}-{count}-{shape}' for done in range(3) for count in range(4) for shape in (1, 2, 3)]
    rows, binaries, commands = [], [], []
    for arm in ('PRE', 'POST'):
        for db0 in (False, True):
            binary = BUILD / (arm + ('-db0' if db0 else '') + '-cost')
            command = FLAGS + (['-DWBKNOBS_PRE', '-I' + str(BUILD / 'PRE-src')] if arm == 'PRE' else [])
            command += (['-DTOMO_SINGLE_DATABASE=1', '-Dtomo=tomo_db0'] if db0 else [])
            command += ['-I.', 'tests/wbknobs_cost.cc', '-o', str(binary), '-ljemalloc']
            run(command); commands.append(command)
            elf = Elf(binary); symbol = elf.functions()['wbknobs_defer']
            section = elf.sections[elf.names.index('.text')]
            binaries.append(dict(arm=arm, db0=db0, path=str(binary.relative_to(ROOT)), sha256=sha(binary)))
            for case in cases:
                output = run([tracer, binary, case, f'{symbol["value"]:x}', f'{section[3]:x}',
                              f'{section[5]:x}', str(int(elf.kind == 3))])
                assert f'PASS wb-completion {case}' in output, output
                counts = json.loads(next(line[6:] for line in output.splitlines() if line.startswith('TRACE=')))
                assert counts['library_instructions'] == 0
                rows.append(dict(arm=arm, db0=db0, case=case, **counts))
            print('PASS instruction receipts', arm, 'db0' if db0 else 'multi', len(cases), flush=True)
    counts = {(r['arm'], r['db0'], r['case']): r['instructions'] for r in rows}
    comparisons = [dict(db0=db0, case=case, pre=counts['PRE', db0, case], post=counts['POST', db0, case],
                        delta=counts['POST', db0, case] - counts['PRE', db0, case])
                   for db0 in (False, True) for case in cases]
    # Per-reply instruction growth must stay at PRE: extra knob work belongs at
    # the visit boundary, including the integer encoder's register-sensitive path.
    growth = []
    for db0 in (False, True):
        for count in range(4):
            for shape in (1, 2, 3):
                pre = counts['PRE', db0, f'codes-2-{count}-{shape}'] - counts['PRE', db0, f'codes-1-{count}-{shape}']
                post = counts['POST', db0, f'codes-2-{count}-{shape}'] - counts['POST', db0, f'codes-1-{count}-{shape}']
                growth.append(dict(db0=db0, count=count, shape=shape, pre=pre, post=post))
    data = dict(scope='One wrapper/defer invocation including cached policy/S/D loads; setup excluded. Existing ptrace tracer, no clocks, PMU, server or load.',
                tracer_sha256=sha(tracer), commands=commands, binaries=binaries, rows=rows,
                comparisons=comparisons, per_reply_growth=growth)
    (OUT / 'code-costs.json').write_text(json.dumps(data, indent=2) + '\n')
    print('Visit deltas:', min(r['delta'] for r in comparisons), max(r['delta'] for r in comparisons), flush=True)
    assert all(r['post'] <= r['pre'] for r in growth), 'per-reply growth regression'


def layout():
    script = BUILD / 'layout.gdb'
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
    for name in ('Client','IoLoop','Config'):
        t=gdb.lookup_type(ns+'::'+name)
        fields[name]={'size':int(t.sizeof),'fields':{f.name:[int(f.bitpos)//8,int(f.type.sizeof)] for f in t.fields() if hasattr(f,'bitpos')}}
    rows[ns]={'sizes':sizes,'layouts':fields}
print('LAYOUT='+json.dumps(rows))
end
''')
    rows = {}
    for arm, binary in (('PRE', BUILD / 'PRE/tomokv'), ('POST', ROOT / 'build/tomokv')):
        output = run(['gdb', '-nx', '-q', '-batch', binary, '-x', script])
        rows[arm] = json.loads(next(line[7:] for line in output.splitlines() if line.startswith('LAYOUT=')))
    for ns in rows['PRE']:
        for name in ('Client', 'IoLoop', 'Config'):
            a, b = (rows[arm][ns]['layouts'][name] for arm in ('PRE', 'POST'))
            assert a['size'] == b['size'], (ns, name, 'size changed')
            for field, offset in a['fields'].items():
                if field != 'layout_reserved':
                    assert b['fields'][field] == offset, (ns, name, field, offset, b['fields'][field])
        client = rows['POST'][ns]['layouts']['Client']['fields']
        assert client['wb_deferrals_'] == [72, 1] and client['rob_'] == [128, 192]
    (OUT / 'layout.json').write_text(json.dumps(rows, indent=2) + '\n')
    print('PASS eight size locks, every existing Client/IoLoop/Config member offset, both namespaces')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('costs', 'layout'))
    args = parser.parse_args(); OUT.mkdir(parents=True, exist_ok=True); BUILD.mkdir(parents=True, exist_ok=True)
    (costs if args.action == 'costs' else layout)()
