#!/usr/bin/env python3
"""Audit the production writeback rule against frozen serverless witnesses.

No server, clocks, PMU, load, selector, source overlay or arm build. Frozen
inputs are checked against the preservation manifest before use. Run after
make build/wbland-units, under the lane's assigned compile/test affinity.
"""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
from lbstall_artifacts import Elf

ROOT = Path(__file__).resolve().parents[1]
FLAGS = ['g++', '-std=c++20', '-O2', '-g', '-Wall', '-Wextra', '-march=native',
         '-pthread', '-DTOMO_JEMALLOC', '-I.']


def sha(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def write(path, value):
    path.write_text(json.dumps(value, indent=2) + '\n')


def sections(path):
    elf = Elf(path)
    rows = {}
    for i, (name, section) in enumerate(zip(elf.names, elf.sections)):
        rows[name] = dict(type=section[1], flags=section[2], address=section[3],
                          offset=section[4], size=section[5], alignment=section[8],
                          sha256=None if section[1] == 8 else
                          hashlib.sha256(elf.section_data(i)).hexdigest())
    return dict(path=str(path), sha256=sha(path), sections=rows)


def identity(inputs, output):
    production = sections(ROOT/'build/tomokv')
    study = sections(inputs/'tomokv-study-d3')
    differences = []
    for name in sorted(production['sections'].keys() | study['sections'].keys()):
        a, b = study['sections'].get(name), production['sections'].get(name)
        if a != b:
            differences.append(dict(section=name, study=a, production=b,
                                    changed_fields=[key for key in a.keys() | b.keys() if a.get(key) != b.get(key)]
                                    if a and b else ['section_presence']))
    same_text = production['sections']['.text']['sha256'] == study['sections']['.text']['sha256']
    write(output/'identity.json', dict(production=production, study=study,
                                       text_identical=same_text, differences=differences))
    print('Whole .text identical:', same_text, '; differing sections:',
          ', '.join(row['section'] for row in differences), flush=True)

    # GDB reads DWARF only; there is deliberately no run/start command.
    script = output/'layout.gdb'
    script.write_text('''set pagination off
python
import gdb,json
expected = dict(Op=336,Client=1984,ThreadCtx=1408,Shard=1440,FlatStore=944,AtomicEntry=144,Config=624)
expected['Rob<64>'] = 192
rows = []
for ns in ('tomo','tomo_db0'):
    sizes = {name:int(gdb.lookup_type(ns+'::'+name).sizeof) for name in expected}
    assert sizes == expected, (ns,sizes)
    client = gdb.lookup_type(ns+'::Client')
    fields = {f.name:[int(f.bitpos)//8,int(f.type.sizeof)] for f in client.fields() if hasattr(f,'bitpos')}
    assert fields['wb_deferrals_'] == [72,1] and fields['rob_'] == [128,192]
    rows.append(dict(namespace=ns,sizes=sizes,client_fields=fields))
print('LAYOUT='+json.dumps(rows))
end
''')
    rows = {}
    for name, binary in [('production', ROOT/'build/tomokv'), ('study', inputs/'tomokv-study-d3')]:
        result = subprocess.run(['gdb', '-nx', '-q', '-batch', str(binary), '-x', str(script)],
                                capture_output=True, text=True)
        (output/f'{name}-layout.log').write_text(result.stdout + result.stderr)
        assert result.returncode == 0, result.stdout + result.stderr
        rows[name] = json.loads(next(line[7:] for line in result.stdout.splitlines() if line.startswith('LAYOUT=')))
    assert rows['production'] == rows['study'], 'Client member layout changed'
    write(output/'layout.json', rows)
    print('PASS both namespaces: all eight size locks and every Client member match the study', flush=True)


def costs(inputs, output):
    tracer = output/'instruction-trace'
    subprocess.run(FLAGS + ['tools/wb_rule_2s_trace.cc', '-o', str(tracer)], cwd=ROOT, check=True)
    # The original 22 fixtures, plus the subsequent study's half-boundary cases.
    standard = [(1, 0, 0, 1, 0), (64, 1, 0, 0, 0), (64, 0, 512, 1, 0)]
    standard += [(n, done, 0, 1, 0) for n in (8, 16, 17, 32, 33, 64) for done in (0, 1, n)]
    standard += [(64, 1, 0, 1, 1)]
    extra = [(n, done, 0, 1, 0) for n in (4, 8, 16, 17, 32, 64) for done in (0, 1, n//2, n)]
    extra += [(8, 1, 0, 1, 1)]
    fixtures = list(dict.fromkeys(standard + extra))
    assert len(standard) == 22
    rows, binaries, commands = [], [], []
    for db0 in (False, True):
        suffix = '-db0' if db0 else ''
        codes = output/f'production{suffix}-codes'
        command = FLAGS + (['-DTOMO_SINGLE_DATABASE=1', '-Dtomo=tomo_db0'] if db0 else [])
        command += ['tests/wb_rule_codes.cc', '-o', str(codes), '-ljemalloc']
        subprocess.run(command, cwd=ROOT, check=True)
        commands.append(command)
        for arm in ('ref', 'hyb16-d2', 'hyb16-d3', 'production'):
            for kind in ('unit', 'codes'):
                binary = ((ROOT/f'build/wb-rule{suffix}-completion-unit' if kind == 'unit' else codes)
                          if arm == 'production' else inputs/f'{arm}{suffix}-{kind}')
                elf = Elf(binary)
                symbol = 'wb_completion_defer' if arm == 'production' else 'wbhybrid2_defer'
                entry = elf.functions()[symbol]
                section = elf.sections[elf.names.index('.text')]
                binaries.append(dict(arm=arm, db0=db0, kind=kind, path=str(binary), sha256=sha(binary),
                                     symbol=symbol, address=entry['value']))
                cases = ([('trace-' + '-'.join(map(str, (*fixture, count))), fixture in standard)
                          for fixture in fixtures for count in range(4)] if kind == 'unit' else
                         [(f'codes-{done}-{count}-{shape}', False)
                          for done in range(3) for count in range(4) for shape in (1, 2, 3)])
                for case, is_standard in cases:
                    result = subprocess.run([str(tracer), str(binary), case, f'{entry["value"]:x}',
                                             f'{section[3]:x}', f'{section[5]:x}', str(int(elf.kind == 3))],
                                            capture_output=True, text=True, timeout=60)
                    prefix = 'wb-completion' if arm == 'production' else 'wbhybrid2'
                    assert result.returncode == 0 and f'PASS {prefix} {case}' in result.stdout, result.stdout + result.stderr
                    counts = json.loads(next(line[6:] for line in result.stdout.splitlines() if line.startswith('TRACE=')))
                    assert counts['library_instructions'] == 0
                    rows.append(dict(arm=arm, db0=db0, case=case, standard=is_standard, **counts))
            print('PASS instruction receipts:', arm, 'db0' if db0 else 'multi', flush=True)
    counts = {(r['arm'], r['db0'], r['case']):r['instructions'] for r in rows}
    compared = [r for r in rows if r['arm'] == 'production']
    assert all(r['instructions'] == counts['hyb16-d3', r['db0'], r['case']] for r in compared), 'study instruction mismatch'
    for db0 in (False, True):
        assert counts['production', db0, 'trace-64-1-0-1-0-0'] == 101
        assert counts['ref', db0, 'trace-64-1-0-1-0-0'] == 92
    write(output/'costs.json', dict(scope='One wrapper/defer call, setup excluded; ptrace, no clocks/PMU/server/load',
                                  tracer_sha256=sha(tracer), commands=commands, binaries=binaries, rows=rows,
                                  standard_fixtures=standard, production_equals_chosen=True,
                                  compared=len(compared), compared_standard=sum(r['standard'] for r in compared)))
    print('PASS production equals chosen:', len(compared), 'receipts;',
          sum(r['standard'] for r in compared), 'on the 22 standard fixtures', flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode', choices=('identity', 'costs'))
    parser.add_argument('--inputs', type=Path, default=ROOT/'build/wbhybrid3/inputs')
    parser.add_argument('--output', type=Path, default=ROOT/'build/wbhybrid3')
    args = parser.parse_args()
    args.inputs, args.output = args.inputs.resolve(), args.output.resolve()
    args.output.mkdir(parents=True, exist_ok=True)
    for row in json.loads((args.inputs/'manifest.json').read_text()):
        path = args.inputs/Path(row['copy']).name
        assert sha(path) == row['sha256'], f'frozen input changed: {path}'
    (identity if args.mode == 'identity' else costs)(args.inputs, args.output)
