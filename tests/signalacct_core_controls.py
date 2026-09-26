#!/usr/bin/env python3
"""Serverless negative controls of the actual model/fold/picker; never starts IO."""
import json
import os
from pathlib import Path
import shutil
import subprocess

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'build/signalacct-proof/core-controls'


def once(s, old, new):
    assert s.count(old) == 1, old
    return s.replace(old, new, 1)


def main():
    assert set(os.sched_getaffinity(0)) <= set(range(112, 128)), 'pin to CPUs 112-127'
    expected = {
        'legacy-occupancy': ('signalacct-post', 'corrected occupancy uses complete IO wall'),
        'model-uses-busy': ('signalacct', 'fixed model trace holds stable 6:2'),
        'no-coordinator-exclusion': ('signalacct-post', 'coordinator excluded despite lowest occupancy'),
        'no-aof-exclusion': ('signalacct-post', 'AOF writer excluded despite lowest occupancy'),
        'no-unix-exclusion': ('signalacct-post', 'unix owner excluded despite lowest occupancy'),
    }
    OUT.mkdir(parents=True, exist_ok=True)
    make = ['include Makefile', '.PHONY: signalacct-core-controls',
            'signalacct-core-controls: ' + ' '.join(str((OUT / n / 'unit').relative_to(ROOT)) for n in expected)]
    for name in expected:
        dest = OUT / name
        for path in (ROOT / 'src').rglob('*'):
            if path.is_file() and path.suffix in ('.h', '.inc', '.cc'):
                target = dest / path.relative_to(ROOT)
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(path, target)
        if name == 'legacy-occupancy':
            p = dest / 'src/core/signalacct.h'
            p.write_text(once(p.read_text(), 'sig_.busy_ns += busy;',
                             'sig_.busy_ns += busy == 900 ? 100 : busy; // lost submit/sweep'))
        elif name == 'model-uses-busy':
            p = dest / 'src/core/flipctl.cc'
            p.write_text(once(p.read_text(), 'role_work[index] += flip_role_work(wall, idle);',
                             'role_work[index] += signal.busy_ns - start.busy_ns;'))
        else:
            p = dest / 'src/core/server.h'
            needle = 'if (tid == coordinator || tid == aof_writer || tid == unix_owner_tid_) continue;'
            alternatives = {
                'no-coordinator-exclusion': 'if (tid == aof_writer || tid == unix_owner_tid_) continue;',
                'no-aof-exclusion': 'if (tid == coordinator || tid == unix_owner_tid_) continue;',
                'no-unix-exclusion': 'if (tid == coordinator || tid == aof_writer) continue;',
            }
            p.write_text(once(p.read_text(), needle, alternatives[name]))
        path = str(dest.relative_to(ROOT))
        model = name == 'model-uses-busy'
        objs = '$(filter-out build/src/core/flipctl.o,$(CORE_TEST_OBJ))' if model else '$(CORE_TEST_OBJ)'
        extra = f'{path}/src/core/flipctl.cc ' if model else ''
        make += [f'{path}/unit: tests/core_concurrency_unit.cc tests/signalacct_core_checks.inc {objs}',
                 '\t$(CXX) $(CXXFLAGS) $(JEFLAGS) -O1 -DTOMO_CORE_CONCURRENCY_TEST '
                 f'-I{path} -I. tests/core_concurrency_unit.cc {extra}{objs} '
                 '-o $@ $(JELIBS) $(LDLIBS) -lm']
    mk = OUT / 'controls.mk'
    mk.write_text('\n'.join(make) + '\n')
    with (OUT / 'build.log').open('w') as log:
        subprocess.run(['make', '-j16', '-f', str(mk), 'signalacct-core-controls'], cwd=ROOT,
                       stdout=log, stderr=subprocess.STDOUT, check=True)
    results = []
    for name, (row, message) in expected.items():
        r = subprocess.run([str(OUT / name / 'unit'), row], cwd=ROOT, text=True,
                           stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=60)
        (OUT / name / 'run.log').write_text(r.stdout)
        assert r.returncode == 1 and message in r.stdout, (name, r.returncode, r.stdout)
        results.append(dict(control=name, state=row, rejected=True, returncode=r.returncode,
                            assertion=message))
        print('PASS rejected', name, message, flush=True)
    (OUT / 'results.json').write_text(json.dumps(results, indent=2) + '\n')


if __name__ == '__main__':
    main()
