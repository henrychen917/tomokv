#!/usr/bin/env python3
"""Run only the lane's 24 correctness rows, retaining PRE failures verbatim."""
import argparse
import json
from pathlib import Path
import shutil
import subprocess
import time

p = argparse.ArgumentParser(description=__doc__)
p.add_argument('arm', choices=('pre', 'post'))
p.add_argument('--binary', required=True)
p.add_argument('--port', required=True, type=int)
p.add_argument('--tag', default='')
a = p.parse_args()
root = Path('docs/savefix') / (a.arm + a.tag)
root.mkdir(parents=True, exist_ok=False)
results = []
for engine in ('uring', 'epoll'):
    for case in ('acks', 'bgsave', 'rewrite'):
        for mode in ('1s', '2s'):
            for variant in (('sigterm', 'command') if case == 'acks' else (0, 1)):
                label = f'{case}-{mode}-{variant}-{engine}'
                data = Path('build/savefix') / (a.arm + a.tag + '-rows') / label
                argv = ['taskset', '-c', '112-127', 'python3', 'tests/savefix.py',
                        '--binary', a.binary, '--port', str(a.port), '--cores', '112-119',
                        '--output', str(data), '--case', case, '--mode', mode, '--net-io', engine,
                        '--action' if case == 'acks' else '--atomic', str(variant)]
                started = time.monotonic()
                with (root / (label + '.log')).open('w') as log:
                    status = subprocess.run(argv, stdout=log, stderr=log).returncode
                evidence = list(data.glob('attempt-*/result.json'))
                result = json.loads(evidence[-1].read_text()) if evidence else None
                expected = (status == 0) if a.arm == 'post' else (
                    status != 0 and result is not None and bool(result['witness']) and
                    (bool(result.get('lost')) if case == 'acks' else result['status'] == -6))
                row = dict(label=label, argv=argv, exit_code=status, expected=expected,
                           seconds=round(time.monotonic() - started, 3), result=result)
                results.append(row)
                (root / 'results.json').write_text(json.dumps(results, indent=2) + '\n')
                for directory in sorted(data.glob('attempt-*')):
                    for source in directory.glob('*.log'):
                        shutil.copyfile(source, root / (label + '-' + directory.name + '-' + source.name))
                print(label, 'EXPECTED' if expected else 'UNEXPECTED', status, row['seconds'], flush=True)
raise SystemExit(not all(row['expected'] for row in results))
