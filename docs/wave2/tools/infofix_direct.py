#!/usr/bin/env python3
"""wave2: direct expwide -> infofix stress (docs/wave1b/tools/infofix_repro.py procedure, which
caught the stale avg_ttl of the last wave). One boot per atomic mode (split 6:2, 16 shards, the
feature_split_job shape; _gate_process.server supplies the gate's --databases 1); each boot runs
`expwide` then `infofix` ROUNDS times. Server 80-87, driver 89-95, port 22810.
Never a performance measurement. usage: infofix_direct.py <out-dir> [rounds]"""
import json
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path('/home/user/Projects/cx-wave2')
sys.path.insert(0, str(ROOT / 'tests'))
from _gate_process import server  # noqa: E402

OUT = Path(sys.argv[1]).resolve()
ROUNDS = int(sys.argv[2]) if len(sys.argv) > 2 else 20
OUT.mkdir(parents=True, exist_ok=False)
binary = ROOT / 'build/tomokv'
summary = dict(binary=str(binary), sha256=subprocess.check_output(['sha256sum', str(binary)], text=True).split()[0],
               rounds=ROUNDS, cells={})
for atomic in (0, 1):
    tag = f'a{atomic}'
    records, fails, avg = [], 0, []
    directory = OUT / tag
    with server(binary, '80-87', 22810, directory / 'server',
                ['--ratio', '6:2', '--shards', '16', '--atomic', str(atomic)]) as (admin, child):
        for i in range(1, ROUNDS + 1):
            for script in ('expwide', 'infofix'):
                log = directory / f'{script}-{i}.log'
                argv = ['taskset', '-c', '89-95', sys.executable, str(ROOT / 'tests' / (script + '.py')),
                        '127.0.0.1', '22810']
                start = time.monotonic()
                with log.open('w') as output:
                    rc = subprocess.run(argv, cwd=ROOT, stdout=output, stderr=subprocess.STDOUT,
                                        timeout=600).returncode
                records.append(dict(round=i, battery=script, exit_code=rc, argv=argv,
                                    seconds=round(time.monotonic() - start, 3),
                                    log=str(log.relative_to(ROOT))))
                if rc != 0:
                    fails += 1
                text = log.read_text(errors='replace')
                avg += [f'{script}-{i}: ' + line.strip() for line in text.splitlines()
                        if 'avg_ttl' in line and 'FAIL' in line]
        alive = child.poll() is None
    summary['cells'][tag] = dict(atomic=atomic, pairs=ROUNDS, failures=fails, avg_ttl_failures=avg,
                                 server_alive_at_end=alive, commands=records)
    print(tag, dict(pairs=ROUNDS, failures=fails, avg_ttl_failures=len(avg), server_alive_at_end=alive),
          flush=True)
(OUT / 'summary.json').write_text(json.dumps(summary, indent=2) + '\n')
