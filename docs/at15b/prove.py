#!/usr/bin/env python3
"""Run AT15b's serverless row bodies on the authorized CPUs; never boot a server."""
from pathlib import Path
import subprocess

out = Path('docs/at15b')
cases = ('admission closure script_keys rename_overlay write_latest script_apply '
         'post_apply_probe lua_conversion watch_parent watch_cycle mset_arity '
         'watch_oom lua_lines library_limit stage_flag instruction_limit plain_0 plain_1').split()


def run(label, *command, expected=0, witness=None):
    command = ['taskset', '-c', '112-127', *command]
    result = subprocess.run(command, text=True, stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, timeout=180)
    (out / (label + '.log')).write_text('$ ' + ' '.join(command) + '\n' +
                                     result.stdout + f'\nexit={result.returncode}\n')
    assert result.returncode == expected, (label, result.returncode, result.stdout[-4000:])
    if witness:
        assert witness in result.stdout, (label, 'missing witness', witness)
    print(f'PASS {label}: exit={result.returncode}', flush=True)


for case in cases:
    run('survivor-' + case, './build/atomic-survivors-unit', case, witness='PASS ' + case)
run('multidb', './build/multidb-unit')
run('mdbqsbr', 'python3', 'tests/mdbqsbr_checks.py', 'build/mdbqsbr-unit')
for variant in ('at15-unit', 'at15-db0-unit'):
    for mode in ('1s', '2s'):
        run(variant + '-' + mode, './build/' + variant, mode, witness='PASS at15')
for variant in ('execabort-watch-unit', 'execabort-watch-db0-unit'):
    for mode in ('1s', '2s'):
        for control in ('', 'no-watch', 'no-error'):
            run(variant + '-' + mode + ('-' + control if control else ''),
                './build/' + variant, mode, *([control] if control else []))
    run(variant + '-no-arm', './build/' + variant, '2s', 'no-arm',
        expected=1, witness='WATCH window never armed')
run('wire-self-test', 'python3', 'tests/at15.py', '--self-test')
run('shell-row', 'python3', 'tests/at15_gate_test.py')
