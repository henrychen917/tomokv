#!/usr/bin/env python3
"""Serverless accounting/parser negative controls. Run pinned to CPUs 112-127.

Mutants exist only under build/. No server or load generator is executed.
"""
import copy
import json
import os
from pathlib import Path
import resource
import shutil
import subprocess
import sys

from shutdown_report import require_io_conservation
ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'build/signalacct-proof/controls'


def replace_once(text, old, new):
    assert text.count(old) == 1, old
    return text.replace(old, new, 1)


def parser_controls():
    record = dict(entry_ns=100, begin_ns=101, end_ns=233, exit_ns=234,
                  busy_ns=112, idle_ns=20, did_submit=2, sweep_submit=1, park=1,
                  role_exit=True, stopped=False)
    reentry = dict(record, entry_ns=500, begin_ns=501, end_ns=633, exit_ns=634,
                   role_exit=False, stopped=True)
    report = dict(schema=1, thread_mode='2s', threads=[
        dict(tid=0, role='io', busy_ns=624, idle_ns=140, io_tenures=[record, reentry]),
        dict(tid=1, role='ex', busy_ns=300, idle_ns=500, io_tenures=[])])
    assert require_io_conservation(report, edges=True)['mixed']
    mutations = {
        'legacy-dropped-window': lambda r: r['threads'][0]['io_tenures'][0].update(busy_ns=72),
        'unflushed-tail': lambda r: r['threads'][0]['io_tenures'][1].update(busy_ns=99),
        'idle-subtracted-twice': lambda r: r['threads'][0]['io_tenures'][0].update(busy_ns=92),
        'carry-ex-time': lambda r: r['threads'][0]['io_tenures'][1].update(busy_ns=380),
        'missing-row': lambda r: r['threads'][0].pop('io_tenures'),
        'unentered-io': lambda r: r['threads'][0].update(io_tenures=[]),
        'overlapping-endpoints': lambda r: r['threads'][0]['io_tenures'][1].update(entry_ns=230),
        'no-exit-reason': lambda r: r['threads'][0]['io_tenures'][0].update(role_exit=False),
        'no-did-submit': lambda r: [t.update(did_submit=0) for t in r['threads'][0]['io_tenures']],
        'no-sweep-submit': lambda r: [t.update(sweep_submit=0) for t in r['threads'][0]['io_tenures']],
        'no-park': lambda r: [t.update(park=0) for t in r['threads'][0]['io_tenures']],
        'no-role-edge': lambda r: [t.update(role_exit=False, stopped=True) for t in r['threads'][0]['io_tenures']],
        'mixed-lifetime-used-as-io': lambda r: r['threads'][0]['io_tenures'][0].update(busy_ns=624),
        'lifetime-counter-reset': lambda r: r['threads'][0].update(busy_ns=0),
    }
    rows = []
    for name, mutate in mutations.items():
        bad = copy.deepcopy(report)
        mutate(bad)
        try:
            require_io_conservation(bad, edges=True)
        except SystemExit as error:
            rows.append(dict(control=name, rejected=True, reason=str(error)))
        else:
            raise AssertionError('parser accepted ' + name)
    return rows


def main():
    assert set(os.sched_getaffinity(0)) <= set(range(112, 128)), 'pin to CPUs 112-127'
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    OUT.mkdir(parents=True, exist_ok=True)
    source = (ROOT / 'src/core/signalacct.h').read_text()
    mutants = {
        'omit-entry': ('passes', 'entry/prologue cut', replace_once(source,
            '        account(next);', '        if (next == 110) { cut_ = next; }\n        account(next);')),
        'omit-no-work': ('passes', 'no-work non-idle', replace_once(source,
            '        account(next);', '        if (next == 220) { cut_ = next; }\n        account(next);')),
        'omit-zero-flush': ('zero', 'zero-pass tenure final flush', replace_once(source,
            '        account(end);', '        /* omit final flush */')),
        'omit-stop-park-flush': ('roles', 'IO->EX->IO excludes EX', replace_once(source,
            '        account(end);', '        if (end != 1550) account(end);')),
        'omit-submit': ('passes', 'did-submit elapsed', replace_once(source,
            '        account(next);', '        if (next == 150) { cut_ = next; }\n        account(next);')),
        'omit-sweep': ('passes', 'sweep-submit elapsed', replace_once(source,
            '        account(next);', '        if (next == 180) { cut_ = next; }\n        account(next);')),
        'omit-final-flush': ('passes', 'final partial interval', replace_once(source,
            '        account(end);', '        /* negative control: omit final partial interval */')),
        'double-idle': ('passes', 'idle subtracted exactly once', replace_once(source,
            'elapsed - asleep;', 'elapsed - 2 * asleep;')),
        'carry-ex': ('roles', 'IO->EX->IO excludes EX', replace_once(replace_once(replace_once(source,
            '    uint64_t cut_, idle_cut_, busy_begin_, idle_begin_;',
            '    inline static uint64_t carry_ = 0;\n    uint64_t cut_, idle_cut_, busy_begin_, idle_begin_;'),
            '        busy_begin_ = sig_.busy_ns;', '        if (carry_) cut_ = carry_;\n        busy_begin_ = sig_.busy_ns;'),
            '        cut_ = next;', '        cut_ = carry_ = next;')),
        'extra-clock': ('passes', 'five passes use five clocks', replace_once(source,
            '        account(next);', '        account(next);\n        (void)Clock::now();')),
    }
    results = parser_controls()
    for name, (case, expected, header) in mutants.items():
        dest = OUT / name
        (dest / 'src/core').mkdir(parents=True, exist_ok=True)
        (dest / 'src/core/signalacct.h').write_text(header)
        binary = dest / 'unit'
        command = ['g++', '-std=c++20', '-O2', '-Wall', '-Wextra', '-I' + str(dest),
                   '-I.', '-iquote', 'src/core', 'tests/signalacct_unit.cc', '-o', str(binary)]
        with (dest / 'build.log').open('w') as log:
            subprocess.run(command, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT, check=True)
        result = subprocess.run([str(binary), case], cwd=ROOT, text=True, stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT, timeout=20)
        (dest / 'run.log').write_text(result.stdout)
        assert result.returncode == 1 and expected in result.stdout, (name, result.returncode, result.stdout)
        results.append(dict(control=name, rejected=True, returncode=result.returncode, reason=result.stdout.strip()))
    positive = OUT / 'unit'
    subprocess.run(['g++', '-std=c++20', '-O2', '-I.', 'tests/signalacct_unit.cc', '-o', str(positive)], cwd=ROOT, check=True)
    subprocess.run([str(positive)], cwd=ROOT, check=True)
    for state in ('clock', 'idle-reset', 'idle-excess', 'busy-overflow', 'double-finish'):
        result = subprocess.run([str(positive), 'invalid-' + state], text=True, stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT, timeout=20)
        assert result.returncode == -6 and 'invalid IO accounting' in result.stdout, (state, result)
        results.append(dict(control='invalid-' + state, rejected=True, returncode=result.returncode))
    (OUT / 'results.json').write_text(json.dumps(results, indent=2) + '\n')
    for row in results:
        print('PASS rejected', row['control'], row.get('reason', 'invalid cuts abort'))


if __name__ == '__main__':
    main()
