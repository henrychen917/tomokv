#!/usr/bin/env python3
"""Serverless FLIP close/drain regression and an exact removal negative control."""
import json
import os
from pathlib import Path
import shutil
import subprocess

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'build/signalacct-proof/flip-close'


def main():
    assert set(os.sched_getaffinity(0)) <= set(range(112, 128)), 'pin to CPUs 112-127'
    overlay = OUT / 'no-close-drain'
    shutil.copytree(ROOT / 'src', overlay / 'src', dirs_exist_ok=True)
    path = overlay / 'src/core/io_loop.h'
    source = path.read_text()
    guard = ('        for (Client* client : active_.v)\n'
             '            if (client->closing() && !client->dead()) return false;\n')
    assert source.count(guard) == 1
    path.write_text(source.replace(guard, '', 1))
    target = str((OUT / 'negative').relative_to(ROOT))
    makefile = OUT / 'control.mk'
    makefile.write_text('include Makefile\n' + target + ': tests/core_concurrency_unit.cc '
        'tests/flip_close_checks.inc $(CORE_TEST_OBJ) ' + str(path) + '\n'
        '\t$(CXX) $(CXXFLAGS) $(JEFLAGS) -DTOMO_CORE_CONCURRENCY_TEST -I' + str(overlay) +
        ' -I. $< $(CORE_TEST_OBJ) -o $@ $(JELIBS) $(LDLIBS) -lm\n')
    with (OUT / 'build.log').open('w') as log:
        subprocess.run(['make', '-j16', '-f', str(makefile), 'build/signalacct-core-unit', target],
                       cwd=ROOT, stdout=log, stderr=subprocess.STDOUT, check=True)
    rows = []
    for arm, binary in [('positive', ROOT / 'build/signalacct-core-unit'), ('negative', ROOT / target)]:
        run = subprocess.run([str(binary), 'flip-close'], cwd=ROOT, text=True,
                             stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=30)
        (OUT / (arm + '.log')).write_text(run.stdout)
        expected = 0 if arm == 'positive' else 1
        assert run.returncode == expected, (arm, run.returncode, run.stdout)
        assert 'ERR FLIP connection ownership count is not conserved' in run.stdout, run.stdout
        if arm == 'negative':
            assert 'FAIL core concurrency: FLIP drain must wait for detached closing client' in run.stdout
        else:
            assert 'ARMED flip-close db1:' in run.stdout and 'ARMED flip-close db16:' in run.stdout
        rows.append(dict(arm=arm, returncode=run.returncode, output=run.stdout))
        print(run.stdout, end='')
    (OUT / 'results.json').write_text(json.dumps(rows, indent=2) + '\n')


if __name__ == '__main__':
    main()
