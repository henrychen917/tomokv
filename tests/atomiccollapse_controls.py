#!/usr/bin/env python3
"""Generate/build/run serverless collapse controls; never launches tomokv.

Use under taskset -c 112-127. All generated source/binaries/logs stay in build/.
The linked driver contains the real xshard implementation and is the first link
input, so its instrumented FlatStore COMDATs are selected ahead of release TUs.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'build/atomiccollapse/controls'
ATOMIC = 'src/store/flatstore_atomic.inc'
TEST = 'tests/atomiccollapse_checks.inc'
# name, file, old spelling, new spelling, selection, exact expected assertion
CONTROLS = [
    ('floor', ATOMIC, 'epoch >= floor', 'epoch > floor', 'boundaries',
     'floor equality: epoch equal to floor retained'),
    ('cutoff', ATOMIC, 'epoch > cleanup_cutoff', 'epoch >= cleanup_cutoff', 'boundaries',
     'cleanup cutoff equality: eligible prefix reclaimed'),
    ('undecided', ATOMIC, '!epoch || epoch >= floor', 'epoch >= floor', 'boundaries',
     'undecided boundary: no cleanup past epoch zero'),
    ('winner', ATOMIC, 'epoch >= key.winner_epoch', 'epoch < key.winner_epoch', 'winners',
     'collapse winner: exact logical value/tombstone'),
    ('program-order', ATOMIC, 'epoch = key.prev_epoch;', '(void)epoch;', 'winners',
     'collapse winner: exact logical value/tombstone'),
    ('aborted-winner', ATOMIC, 'if (aborted) return;', '(void)aborted;', 'winners',
     'collapse winner: exact logical value/tombstone'),
    ('deduplicate', ATOMIC,
     '        atomic_collapse_retire_.erase(\n'
     '            std::unique(atomic_collapse_retire_.begin(), atomic_collapse_retire_.end()),\n'
     '            atomic_collapse_retire_.end());',
     '        // negative control: duplicate retire remains in the worklist', 'winners',
     'duplicate loser: direct pool contains each reclaimed value once'),
    ('allocation', ATOMIC, 'catch (const std::bad_alloc&) {\n            return false;',
     'catch (const std::bad_alloc&) {\n            return true;', 'allocation',
     'allocation refusal: all entries, ownership, accounting and retire state preserved'),
    ('snapshot', ATOMIC, ' || snapshot_active_', '', 'snapshot_teardown',
     'snapshot refusal: eligible entry retained without reclamation'),
    ('unlink', ATOMIC, 'if (first_unselected) first_unselected->prev = nullptr;',
     'if (first_unselected) {}', 'boundaries',
     'undecided boundary: linked suffix and its owner reference retained'),
    ('accounting', ATOMIC, '*atomic_promotions_ += occurrences;',
     '*atomic_promotions_ += occurrences + 1;', 'boundaries',
     'undecided boundary: linked suffix and its owner reference retained'),
    ('armed-direct', ATOMIC, '= ReadLocal ?', '= false ?', 'pinned',
     'armed pinned: loser must reach QSBR sink before any storage reuse'),
    ('unarmed-sink', ATOMIC, '= ReadLocal ?', '= true ?', 'pinned',
     'unarmed collapse: read-local sink must not be called'),
    ('fast-path', ATOMIC, '        if (direct) {', '        if (false) {', 'pinned',
     'pinned collapse: committed fast path entered'),
    ('teardown', 'src/store/flatstore.h',
     'read_local_enabled_ = false;  // shutdown promotion/free is direct; no callback may outlive us',
     '// negative control: armed at destruction', 'snapshot_teardown',
     'teardown: undecided record aborted and directly reclaimed after disarm, no sink callback'),
    ('early-grace', 'src/core/read_local.h',
     'const uint64_t grace_floor = server_->read_local_grace_floor(oldest, grace_hint_);',
     'const uint64_t grace_floor = UINT64_MAX;', 'pinned',
     'armed pinned: actual reclaim callback blocked and immutable reader bytes intact'),
    ('unentered-pin', TEST, 'server.thread(0).publish_read_local_tick(server.read_local_epoch());',
     'server.thread(0).publish_read_local_parked(server.read_local_epoch());', 'pinned',
     'armed pinned: actual reclaim callback blocked and immutable reader bytes intact'),
    ('unentered-snapshot', TEST, 'f.s().snapshot_mark(0, 100) && f.s().snapshot_active()',
     'true && f.s().snapshot_active()', 'snapshot_teardown',
     'snapshot refusal: capture really active'),
    ('unentered-allocation', TEST, 'fail_new_after = budget;', 'fail_new_after = -1;', 'allocation',
     'allocation window: all four scratch allocations refused, then success'),
    # These two helpers are equivalent on this launch revision. Runtime PASS is
    # expected; the independent source-selector proof must still reject them.
    ('free-alias', ATOMIC, 'free_entry = ReadLocal ?', 'free_entry = false ?', 'all', None),
    ('exchange-dispatch', ATOMIC, 'exchange = ReadLocal ?', 'exchange = false ?', 'all', None),
]


def generate():
    OUT.mkdir(parents=True, exist_ok=True)
    plan = (ROOT / 'build/atomiccollapse/PRE/freeze/build-plan.txt').read_text()
    objects = re.findall(r' -c \S+ -o build/(src/\S+\.o)', plan)
    objects = [str(ROOT / 'build/atomiccollapse/POST' / name) for name in objects
               if name not in ('src/main.o', 'src/cmd/xshard.o')]
    assert len(objects) == 40
    command = ['g++', '-std=c++20', '-O2', '-g', '-Wall', '-Wextra', '-march=native', '-pthread',
               '-DTOMO_JEMALLOC', '-I.', 'tests/atomic_survivors_unit.cc', *objects,
               '-o', 'unit', '-ljemalloc', '-luring', '-pthread', '-lssl', '-lcrypto', '-lm']
    rows = []
    for name, file, old, new, selection, assertion in CONTROLS:
        tree = OUT / name
        shutil.copytree(ROOT / 'src', tree / 'src', dirs_exist_ok=True)
        (tree / 'tests').mkdir(exist_ok=True)
        for test in ('atomic_survivors_unit.cc', 'atomiccollapse_checks.inc'):
            shutil.copyfile(ROOT / 'tests' / test, tree / 'tests' / test)
        if not (tree / 'third_party').exists():
            (tree / 'third_party').symlink_to(ROOT / 'third_party', target_is_directory=True)
        path = tree / file
        source = path.read_text()
        start = source.index('    template <bool ReadLocal>') if file == ATOMIC else 0
        end = source.index('    void atomic_promote_all_for_shutdown()', start) if file == ATOMIC else len(source)
        body = source[start:end]
        count = body.count(old)
        assert count > 0, name
        source = source[:start] + body.replace(old, new) + source[end:]
        path.write_text(source)
        rows.append(dict(name=name, path=file, substitutions=count, selection=selection,
                         assertion=assertion, sha256=hashlib.sha256(source.encode()).hexdigest(),
                         source=old, replacement=new, command=command))
    make = '.PHONY: all\nall: ' + ' '.join(r['name'] + '/unit' for r in rows) + '\n\n'
    for row in rows:
        make += row['name'] + '/unit:\n\tcd ' + shlex.quote(str(OUT / row['name'])) + ' && ' + \
                shlex.join(command) + ' > build.log 2>&1\n\n'
    (OUT / 'Makefile').write_text(make)
    (OUT / 'manifest.json').write_text(json.dumps(rows, indent=2) + '\n')
    print(f'Generated {len(rows)} controls; build with taskset -c 112-127 make -C {OUT} -j16')


def run():
    results = []
    for row in json.loads((OUT / 'manifest.json').read_text()):
        tree = OUT / row['name']
        command = ['taskset', '-c', '112-119', str(tree / 'unit'), 'collapse_' + row['selection']]
        result = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=60)
        output = result.stdout.decode(errors='replace')
        (tree / 'run.log').write_text(output)
        if row['assertion']:
            passed = result.returncode == 1 and ('FAIL: ' + row['assertion']) in output
        else:
            # Explicitly demonstrate the limitation of the runtime witness.
            passed = result.returncode == 0 and 'PASS atomic collapse:' in output
            source = subprocess.run(['python3', str(ROOT / 'tools/atomiccollapse_artifacts.py'), 'factor',
                '37eeb5e90', str(tree / ATOMIC), str(tree / 'source-check')], cwd=ROOT,
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
            (tree / 'source-check.log').write_bytes(source.stdout)
            passed &= source.returncode != 0 and b'wrong compile-time selector' in source.stdout
        results.append(dict(name=row['name'], expected_assertion=row['assertion'],
                            exit=result.returncode, passed=passed, command=command,
                            binary_sha256=hashlib.sha256((tree / 'unit').read_bytes()).hexdigest()))
        print(row['name'], 'PASS' if passed else 'FAIL', output.strip().splitlines()[-1:])
    (OUT / 'results.json').write_text(json.dumps(results, indent=2) + '\n')
    assert all(r['passed'] for r in results), 'one or more controls did not produce the exact required failure'


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('generate', 'run'))
    args = parser.parse_args()
    assert os.sched_getaffinity(0) <= set(range(112, 128)), 'run under taskset -c 112-127'
    (generate if args.action == 'generate' else run)()
