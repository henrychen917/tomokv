#!/usr/bin/env python3
"""Private planted regressions; never alter production sources or install knobs.

Build each control from POST objects, replacing only its affected translation
unit in both namespaces. Check unchanged upstream Tcl assertions on fresh
servers, with a bounded deadline and mandatory POST positive controls.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path
import shlex
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'build/blockfix2/controls'
sys.path.insert(0, str(ROOT / 'tests'))
import redis_tcl

TCL = {
    'rename': ('unit/type/list', 'BLPOP when new key is moved into place'),
    'removed': ('unit/type/stream-cgroups', 'Blocking XREADGROUP: key deleted'),
    'wrongtype': ('unit/type/list', 'BRPOPLPUSH with multiple blocked clients'),
    'multi': ('unit/multi', 'Blocking commands ignores the timeout'),
    'counts': ('unit/type/stream-cgroups',
               'Blocking XREADGROUP for stream key that has clients blocked on list'),
    'slowlog': ('unit/slowlog', 'SLOWLOG - blocking command is reported only after unblocked'),
}


def replace(path, before, after):
    text = path.read_text()
    assert text.count(before) == 1, (str(path), before, text.count(before))
    path.write_text(text.replace(before, after, 1))


def mutation(case, source):
    blocking = source / 'src/cmd/blocking.inc'
    if case == 'rename':
        # Restore PRE's three publication surfaces, leaving the other fixes on.
        source.joinpath('src/cmd/xshard_commands.inc').write_bytes(subprocess.check_output(
            ['git', 'show', '83e0b809d:src/cmd/xshard_commands.inc'], cwd=ROOT))
        replace(blocking, ' ||\n             !std::strcmp(name, "RENAME") || !std::strcmp(name, "RENAMENX")', '')
        text = blocking.read_text()
        begin = text.index('    } else if (!std::strcmp(name, "SORT")) {')
        end = text.index('    } else if (!std::strcmp(name, "XGROUP")) {', begin)
        blocking.write_text(text[:begin] + text[end:])
        replace(blocking, ' ||\n          state.kind == Kind::Rename || state.kind == Kind::Renamenx ||\n          state.kind == Kind::Sort', '')
    elif case == 'removed':
        replace(blocking, 'const bool group_error = state.kind == BlockingKind::Xreadgroup &&',
                'const bool group_error = false && state.kind == BlockingKind::Xreadgroup &&')
    elif case == 'wrongtype':
        replace(blocking, '    if (blocking_is_move(block->kind)) {',
                '    if (false && blocking_is_move(block->kind)) {')
    elif case == 'slowlog':
        replace(blocking, 'SlowlogTiming timing(state.counted.load(std::memory_order_acquire) && arm.armed()',
                'SlowlogTiming timing(false && state.counted.load(std::memory_order_acquire) && arm.armed()')
    elif case == 'multi':
        replace(source / 'src/cmd/t_stream_groups.cc',
                '(void)stream_xreadgroup_execute(shard, op, false);',
                '(void)stream_xreadgroup_execute(shard, op, true);')
        return 't_stream_groups'
    elif case == 'counts':
        replace(source / 'src/cmd/t_server.cc',
                'if (g_server) blocking_key_counts(*g_server, blocking_keys, blocking_on_nokey);',
                'if (false && g_server) blocking_key_counts(*g_server, blocking_keys, blocking_on_nokey);')
        return 't_server'
    elif case == 'refusal':
        replace(blocking, '            if (!blocking_run_direct(state, shard, self, ring)) {',
                '            remove_at_from_shard(shard, queue, i);\n'
                '            if (!blocking_run_direct(state, shard, self, ring)) {')
        replace(blocking, '            remove_at_from_shard(shard, queue, i);\n'
                '            // Consume sequentially', '            // Consume sequentially')
    else:
        raise ValueError(case)
    return 'xshard'


def recipe(target, supplement=None):
    command = ['make', '-n', '-B']
    if supplement:
        command += ['-f', 'Makefile', '-f', supplement]
    lines = subprocess.check_output(command + [target], cwd=ROOT, text=True).splitlines()
    return shlex.split(next(line for line in lines if (' -o ' + target + ' ') in line or
                            line.endswith(' -o ' + target)))


def build_all(cases):
    OUT.mkdir(parents=True, exist_ok=True)
    jobs = []
    records = {}
    for case in cases:
        dest = OUT / case
        source = dest / 'source'
        if source.exists(): shutil.rmtree(source)
        shutil.copytree(ROOT / 'src', source / 'src')
        unit = mutation(case, source)
        records[case] = dict(unit=unit, objects=[], source=str(source),
                             post_sha256=redis_tcl.sha(ROOT / 'build/tomokv'))
        for ns in ('normal', 'db0'):
            obj = 'build/' + ('db0/' if ns == 'db0' else '') + f'src/cmd/{unit}.o'
            command = recipe(obj)
            command = [str(source / f'src/cmd/{unit}.cc') if arg == f'src/cmd/{unit}.cc'
                       else arg for arg in command]
            output = dest / (ns + '.o')
            command[command.index('-o') + 1] = str(output)
            records[case]['objects'].append(dict(original=obj, output=str(output), argv=command))
            jobs.append((command, dest / (ns + '-build.log')))
        if case == 'refusal':
            (source / 'tests').mkdir()
            for name in ('blockfix2_unit.cc', 'atomic_survivors_unit.cc'):
                shutil.copy2(ROOT / 'tests' / name, source / 'tests' / name)
            for name in ('blockfix2-unit', 'blockfix2-db0-unit'):
                command = recipe('build/' + name, 'tools/blockfix2.mk')
                command = [str(source / arg) if arg == 'tests/blockfix2_unit.cc' else arg
                           for arg in command]
                # The included fixture resolves its production include from this tree.
                command.insert(command.index('-I.'), '-I' + str(source))
                command[command.index('-o') + 1] = str(dest / name)
                jobs.append((command, dest / (name + '-build.log')))
    def compile_one(job):
        command, log = job
        with log.open('w') as output:
            subprocess.run(command, cwd=ROOT, stdout=output, stderr=subprocess.STDOUT, check=True)
    with ThreadPoolExecutor(16) as pool:
        list(pool.map(compile_one, jobs))
    link = recipe('build/tomokv')
    for case, record in records.items():
        dest = OUT / case
        replacements = {obj['original']: obj['output'] for obj in record['objects']}
        command = [replacements.get(arg, arg) for arg in link]
        command[command.index('-o') + 1] = str(dest / 'tomokv')
        with (dest / 'link.log').open('w') as output:
            subprocess.run(command, cwd=ROOT, stdout=output, stderr=subprocess.STDOUT, check=True)
        record.update(link=command, binary_sha256=redis_tcl.sha(dest / 'tomokv'))
        (dest / 'receipt.json').write_text(json.dumps(record, indent=2) + '\n')
        print(case, record['binary_sha256'], flush=True)


def check_tcl(args):
    unit, name = TCL[args.case]
    manifest = json.loads((ROOT / 'tests/redis_tcl_passing.json').read_text())
    expected = [label for label in manifest['files'][unit]['passed_tests']
                if label.split(' in tests/')[0] == name]
    assert expected, 'control must exercise a required upstream test'
    dest = args.output.resolve()
    tree = dest / 'checkout'
    redis_tcl.prepare(args.redis_root, tree, controller_port=args.port + 1)
    record = json.loads((OUT / args.case / 'receipt.json').read_text())
    assert record['post_sha256'] == redis_tcl.sha(args.binary), 'POST control binding changed'
    rows = []
    for mode in ('1s', '2s'):
        for arm, binary in [('POST', args.binary), ('BROKEN', OUT / args.case / 'tomokv')]:
            run = argparse.Namespace(output=dest / mode / arm, binary=binary.resolve(),
                cores=args.cores, port=args.port, baseport=args.port + 2, mode=mode,
                ratio='6:2', idle_timeout=15, file_timeout=45)
            row = redis_tcl.run_file(run, tree, unit, only=[name])
            passed = True
            try: redis_tcl.validate_passing(row, expected)
            except ValueError: passed = False
            row.update(arm=arm, required_test=name, validated=passed,
                       binary_sha256=redis_tcl.sha(binary))
            rows.append(row)
            (dest / 'summary.json').write_text(json.dumps(rows, indent=2) + '\n')
            # A broken boot or wrong selection is not a planted-regression witness.
            started = any(e['status'] in ('testing', 'ok', 'err') and
                          name in (e['test'] + e['data']) for e in row['events'])
            assert passed if arm == 'POST' else (not passed and started), (arm, mode, name, row['error'])
            print(args.case, mode, arm, 'PASS' if passed else 'REJECTED', flush=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('action', choices=('build', 'check-tcl'))
    parser.add_argument('--cases', default=','.join([*TCL, 'refusal']))
    parser.add_argument('--case', choices=TCL)
    parser.add_argument('--binary', type=Path, default=ROOT / 'build/tomokv')
    parser.add_argument('--cores', default='16-23')
    parser.add_argument('--port', type=int, default=20480)
    parser.add_argument('--redis-root', type=Path, default=Path('/home/user/Projects/redis'))
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    if args.action == 'build': build_all(args.cases.split(','))
    else: check_tcl(args)


if __name__ == '__main__': main()
