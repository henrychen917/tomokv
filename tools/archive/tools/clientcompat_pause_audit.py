#!/usr/bin/env python3
"""Compare every Redis metadata command/subcommand against the production classifier."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import wave12_counts as census

ROOT = Path(__file__).resolve().parents[1]
assert os.sched_getaffinity(0) <= set(range(64, 80))
os.environ['LC_ALL'] = 'C'
census.BUILD = ROOT/'build/clientcompat/counts'
census.DOC = ROOT/'docs/clientcompat/pause-audit'
binary = census.build('registry', ROOT, ROOT/'build', 'normal',
                      'tests/clientcompat_pause_scope.cc')
metadata = {}
for path in Path('/home/user/Projects/redis/src/commands').glob('*.json'):
    for name, command in json.loads(path.read_text()).items():
        if 'function' not in command:
            continue  # containers themselves are not executable Redis commands
        key = (command.get('container', '')+' '+name).strip()
        metadata[key] = dict(flags=command.get('command_flags', []),
                            reference=str(path), sha256=hashlib.sha256(path.read_bytes()).hexdigest())
output = subprocess.check_output([str(binary)], input='\n'.join(metadata)+'\n', text=True)
rows=[]
for line in output.splitlines():
    if line.count('\t') != 2:
        continue
    name, script, held = line.split('\t')
    ref=metadata[name]
    expected=bool(set(ref['flags']) & {'WRITE', 'MAY_REPLICATE'})
    rows.append(dict(command=name, script=bool(int(script)), held=int(held),
                     expected=expected, **ref))
mismatches=[row for row in rows if not row['script'] and bool(row['held']) != row['expected']]
result=dict(probe_sha256=census.sha(binary), server_sha256=census.sha(ROOT/'build/tomokv'),
            rows=rows, mismatches=mismatches,
            dynamic_scripts=[row['command'] for row in rows if row['script']])
census.save(census.DOC/'registry.json', result)
print(json.dumps(dict(audited=len(rows), mismatches=mismatches,
                     dynamic_scripts=result['dynamic_scripts']), indent=2))
raise SystemExit(bool(mismatches))
