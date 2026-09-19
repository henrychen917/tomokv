#!/usr/bin/env python3
"""Reorder boot contract and source-mutant controls.

build/check are serverless. boot explicitly starts servers and is for mainline.
The same acceptance, diagnostic and effective-value assertions cover both paths.
"""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'build/reordertrim-controls'
ERROR = '--reorder wants 0 or 1\n'
PROBE = r'''
#include "src/core/config.h"
int main(int argc, char** argv) {
    tomo::Config cfg;
    tomo::ConfigParseState state;
    if (argc == 3 && !std::strcmp(argv[1], "--direct")) {
        cfg.reorder = static_cast<uint32_t>(std::strtoull(argv[2], nullptr, 10));
    } else {
        const std::vector<const char*> args(argv + 1, argv + argc);
        if (tomo::parse_config_args(args, cfg, state, 2, "probe") != tomo::kConfigParsed) return 1;
    }
    if (tomo::validate_config(cfg) != tomo::kConfigParsed) return 1;
    std::printf("%d\n", tomo::reorder_for_mode(cfg.reorder, cfg.thread_mode));
}
'''


def replace(source, before, after, count=1):
    assert source.count(before) == count, (before, source.count(before))
    return source.replace(before, after)


def mutants(source):
    parse = 'if (!cfg_parse_u32(value, cfg.reorder) || cfg.reorder > 1) {'
    selector = 'return mode == ThreadMode::Fused ? requested : 0;'
    return {
        'accept-auto': (replace(source, parse,
            'if (value && !std::strcmp(value, "-1")) cfg.reorder = 1;\n            else ' + parse),
            'reject -1 1s'),
        'accept-two': (replace(source, 'cfg.reorder > 1', 'cfg.reorder > 2', 2), 'reject 2 1s'),
        'reject-zero': (replace(source, parse, parse.replace('> 1)', '> 1 || cfg.reorder == 0)')),
                        'accept 0 1s'),
        'reject-one': (replace(source, parse, parse.replace('> 1)', '> 1 || cfg.reorder == 1)')),
                       'accept 1 1s'),
        'split-priority': (replace(source, selector, 'return requested;'), 'accept 1 2s'),
        'fused-fifo': (replace(source, selector, 'return 0;'), 'accept 1 1s'),
        'no-diagnostic': (replace(source, '--reorder wants 0 or 1', 'invalid reorder', 2),
                          'reject -1 1s'),
        'no-validation': (replace(source, 'if (cfg.reorder > 1) {', 'if (false) {'), 'direct 2'),
    }


def cases():
    result = [('default', [], 0)]
    for mode in ('1s', '2s', 'fused', 'split'):
        for value in ('-1', '2', '-2', 'on', 'off', 'auto', '1x', ''):
            result.append((f'reject {value} {mode}', ['--thread-mode', mode, '--reorder', value], None))
        result.append((f'missing {mode}', ['--thread-mode', mode, '--reorder'], None))
        for value in (0, 1):
            result.append((f'accept {value} {mode}', ['--thread-mode', mode, '--reorder', str(value)],
                           value if mode in ('1s', 'fused') else 0))
    for value in (2, 4294967295):
        result.append((f'direct {value}', ['--direct', str(value)], None))
    return result


def check_result(label, result, effective):
    if effective is None:
        assert result.returncode == 1 and result.stderr == ERROR, (label, result)
    else:
        assert result.returncode == 0 and result.stdout == f'{effective}\n', (label, result)


def invoke(binary, args):
    return subprocess.run([str(binary), *args], cwd=ROOT, text=True, capture_output=True, timeout=10)


def build():
    assert set(os.sched_getaffinity(0)) <= set(range(112, 128)), 'pin builds to 112-127'
    source = (ROOT / 'src/core/config.h').read_text()
    manifest = []
    for name, (header, failure) in {'post': (source, None), **mutants(source)}.items():
        directory = OUT / name
        include = directory / 'src/core/config.h'
        include.parent.mkdir(parents=True, exist_ok=True)
        include.write_text(header)
        (directory / 'probe.cc').write_text(PROBE)
        for variant in ('multi', 'db0'):
            binary = directory / variant
            command = ['g++', '-std=c++20', '-O2', '-march=native', '-pthread',
                       '-I' + str(directory), '-I.', '-iquote', 'src/core']
            if variant == 'db0': command += ['-DTOMO_SINGLE_DATABASE=1', '-Dtomo=tomo_db0']
            command += [str(directory / 'probe.cc'), '-o', str(binary)]
            with (directory / f'{variant}.build.log').open('w') as log:
                subprocess.run(command, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT, check=True)
            manifest.append(dict(name=name, variant=variant, binary=str(binary), failure=failure))
    (OUT / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
    print(f'Built {len(manifest)} serverless probes; no servers started')


def check():
    rows = []
    all_cases = {label: (args, expected) for label, args, expected in cases()}
    for entry in json.loads((OUT / 'manifest.json').read_text()):
        labels = [entry['failure']] if entry['failure'] else all_cases
        for label in labels:
            args, effective = all_cases[label]
            result = invoke(entry['binary'], args)
            try:
                check_result(label, result, effective)
            except AssertionError:
                if not entry['failure']: raise
                # A crash, timeout or unrelated error cannot qualify a negative control.
                assert result.returncode in (0, 1), result
                if entry['name'] == 'no-diagnostic':
                    assert result.stderr == 'invalid reorder\n', result
                elif entry['name'].startswith('reject-'):
                    assert result.returncode == 1 and result.stderr == ERROR, result
                else:
                    assert result.returncode == 0 and result.stdout in ('0\n', '1\n', '2\n'), result
            else:
                assert not entry['failure'], f'mutant escaped its detector: {entry}'
            rows.append(dict(name=entry['name'], variant=entry['variant'], case=label,
                             stdout=result.stdout, stderr=result.stderr, returncode=result.returncode))
        print('PASS', entry['variant'], entry['name'], entry['failure'] or f'{len(all_cases)} cases')
    (OUT / 'results.json').write_text(json.dumps(rows, indent=2) + '\n')


def artifacts(args):
    """Build-free preparation: exact FIFO twin A and inverse text-size control B."""
    sys.path.insert(0, str(ROOT / 'tools'))
    from lbstall_artifacts import Elf
    from r7shadow_pad import twin
    pre, post = Elf(args.pre), Elf(args.binary)
    pre_size = len(pre.section_data(pre.names.index('.text')))
    post_size = len(post.section_data(post.names.index('.text')))
    assert pre_size > post_size, 'this inverse control requires the cleanup to shrink text'
    directory = ROOT / 'build'
    receipt = twin(args.binary, directory / 'tomokv-reordertrim-pad-a', 'fifo')
    (directory / 'tomokv-reordertrim-pad-a.json').write_text(json.dumps(receipt, indent=2) + '\n')
    # Preserve compiler CET notes; dropping them would shift the entire PLT/text base.
    obj = Elf(directory / 'src/main.o')
    note = obj.section_data(obj.names.index('.note.gnu.property'))
    (directory / 'reordertrim-pad-b.S').write_text(
        '.text\n.globl reordertrim_text_size_control\nreordertrim_text_size_control:\n' +
        f'.fill {pre_size - post_size},1,0x90\n.section .note.GNU-stack,"",@progbits\n' +
        '.section .note.gnu.property,"a",@note\n.p2align 3\n.byte ' +
        ','.join(str(byte) for byte in note) + '\n')
    (directory / 'reordertrim-pad-b.mk').write_text(
        'build/reordertrim-pad-b.o: build/reordertrim-pad-b.S\n'
        '\t$(CXX) -c $< -o $@\n'
        'build/tomokv-reordertrim-pad-b: $(DB0_OBJ) $(OBJ) build/reordertrim-pad-b.o\n'
        '\t$(CXX) $(CXXFLAGS) $(DB0_OBJ) $(OBJ) build/reordertrim-pad-b.o '
        '-o $@ $(JELIBS) $(LDLIBS) -lm\n')
    (directory / 'tomokv-reordertrim-pad-b.json').write_text(json.dumps(dict(
        kind='B: candidate behaviour plus padding restoring PRE text size',
        pre=str(args.pre), post=str(args.binary), pre_text_bytes=pre_size,
        post_text_bytes=post_size, padding=pre_size - post_size,
        limitation='Restores text extent, not the deleted internal function placement.'), indent=2) + '\n')
    print('Prepared A and B controls; build B with make -f Makefile -f build/reordertrim-pad-b.mk')


def boot(args):
    from _gate_process import cpus, info, server
    assert len(cpus(args.cores)) == 8, 'boot witness requires eight CPUs (gate geometry)'
    binary = args.binary.resolve()
    # Check refusals with a live-process deadline; a mutant that boots must fail.
    # The private temp directory and port=0 avoid loading a user snapshot/listener.
    for databases in (1, 16):
        for mode in ('1s', '2s'):
            for value in ('-1', '2'):
                directory = args.output / f'refuse-db{databases}-{mode}-{value}'
                directory.mkdir(parents=True, exist_ok=False)
                command = ['taskset', '-c', args.cores, str(binary), '--port', '0', '--dir', str(directory),
                           '--save', '', '--appendonly', 'no', '--databases', str(databases),
                           '--shards', '16', '--thread-mode', mode, '--reorder', value]
                if mode == '2s': command += ['--ratio', '6:2']
                result = subprocess.run(command, text=True, capture_output=True, timeout=10)
                check_result(f'reject {value} {mode}', result, None)
                (directory / 'result.json').write_text(json.dumps(vars(result), indent=2) + '\n')
    for databases in (1, 16):
        for mode in ('1s', '2s'):
            for value in (0, 1):
                for local in (0, 1):
                    for overlap in (0, 1):
                        label = f'db{databases}-{mode}-r{value}-rl{local}-o{overlap}'
                        flags = ['--databases', databases, '--shards', 16, '--thread-mode', mode,
                                 '--reorder', value, '--read-local', local, '--overlap', overlap,
                                 '--atomic', 1, '--key-lb', 0, '--client-lb', 0]
                        if mode == '2s': flags += ['--ratio', '6:2']
                        with server(binary, args.cores, args.port, args.output / label, flags) as (conn, _):
                            row = info(conn, 'SERVER')
                            effective = value if mode == '1s' else 0
                            check_result(label, subprocess.CompletedProcess([], 0, row['reorder'] + '\n', ''),
                                         effective)
                            assert row['reorder_retired'] == ('0' if mode == '1s' else '1'), row
                            assert row['schedule_stats_threads'] == ('8' if overlap or effective else '0'), row
                            assert not any(key.startswith('reorder_auto') for key in row), row
                            assert conn.must('SET', 'reordertrim', 'value') == b'OK'
                            assert conn.must('GET', 'reordertrim') == b'value'
                            (args.output / label / 'info.json').write_text(json.dumps(row, indent=2) + '\n')
                        print('PASS boot', label)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('build', 'check', 'artifacts', 'boot'))
    parser.add_argument('--binary', type=Path, default=ROOT / 'build/tomokv')
    parser.add_argument('--pre', type=Path, default=ROOT / 'build/pre/tomokv')
    parser.add_argument('--cores', default='112-119')
    parser.add_argument('--port', type=int, default=8894)
    parser.add_argument('--output', type=Path, default=ROOT / 'build/reordertrim-boots')
    args = parser.parse_args()
    if args.action == 'build': build()
    elif args.action == 'check': check()
    elif args.action == 'artifacts': artifacts(args)
    else: boot(args)
