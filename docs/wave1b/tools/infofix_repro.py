#!/usr/bin/env python3
"""wave1b: direct infofix stress, the same procedure as cx-wave1's docs/wave1/fix2 infofix_repro.py
(which measured 3/10 failures on both perfex-carrying cx-wave1 binaries). One boot per atomic mode
(split 6:2, 16 shards, as feature_split_job); each boot runs `expwide` then `infofix` ROUNDS times.
Server 112-119, driver 121-127, port 25240. Never a performance measurement."""
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path('/home/user/Projects/cx-wave1b')
sys.path.insert(0, str(ROOT / 'tests'))
from _gate_process import server  # noqa: E402

OUT = ROOT / 'build/wave1b/infofix-repro'
OUT.mkdir(parents=True, exist_ok=True)
ROUNDS = int(sys.argv[1]) if len(sys.argv) > 1 else 5
binary = ROOT / 'build/tomokv'
summary = {}
for atomic in (0, 1):
    tag = f'wave1b-a{atomic}'
    fails, avg = 0, []
    directory = OUT / tag
    with server(binary, '112-119', 25240, directory / 'server',
                ['--ratio', '6:2', '--shards', '16', '--atomic', str(atomic)]):
        for i in range(ROUNDS):
            for script in ('expwide', 'infofix'):
                log = directory / f'{script}-{i}.log'
                with log.open('w') as output:
                    rc = subprocess.run(['taskset', '-c', '121-127', sys.executable,
                                         str(ROOT / 'tests' / (script + '.py')), '127.0.0.1', '25240'],
                                        cwd=ROOT, stdout=output, stderr=subprocess.STDOUT, timeout=300).returncode
                if script == 'infofix':
                    text = log.read_text()
                    if rc != 0:
                        fails += 1
                    avg += [line.strip() for line in text.splitlines() if 'avg_ttl' in line and 'FAIL' in line]
    summary[tag] = dict(rounds=ROUNDS, infofix_failures=fails, avg_ttl_failures=avg)
    print(tag, summary[tag], flush=True)
(OUT / 'summary.json').write_text(json.dumps(summary, indent=2) + '\n')
