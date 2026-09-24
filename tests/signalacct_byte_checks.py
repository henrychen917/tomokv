#!/usr/bin/env python3
"""Serverless positive/negative controls for the existing strict ELF body checker."""
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
from lbstall_artifacts import Elf


def main():
    assert set(os.sched_getaffinity(0)) <= set(range(112, 128)), 'pin to CPUs 112-127'
    binary = ROOT / 'build/tomokv-signalacct-post'
    out = ROOT / 'build/signalacct-proof/byte-controls'
    out.mkdir(parents=True, exist_ok=True)
    elf = Elf(binary)
    names = [name for name in elf.functions()
             if name.startswith('_ZN4tomo12_GLOBAL__N_17cmd_getILb0ELb1E')]
    assert len(names) == 1, names
    symbol = elf.functions()[names[0]]
    section = elf.sections[symbol['sec']]
    offset = section[4] + symbol['value'] - section[3]
    corrupt = out / 'post.corrupt-never-run'
    data = bytearray(elf.data)
    data[offset] ^= 1
    corrupt.write_bytes(data)
    corrupt.chmod(0o600)
    rows = []
    for name, other, expected in [('identity', binary, 0), ('executable-byte', corrupt, 1)]:
        directory = out / name
        with (out / (name + '.log')).open('w') as log:
            result = subprocess.run([sys.executable, 'tests/r7shadow_noop.py', str(binary),
                                     str(other), str(directory)], cwd=ROOT,
                                    stdout=log, stderr=subprocess.STDOUT)
        assert result.returncode == expected, (name, result.returncode)
        report = json.loads((directory / 'audit.json').read_text())
        assert len(report['rows']) == 336
        changed = [r['name'] for r in report['rows'] if not r['equal']]
        if name == 'executable-byte':
            assert len(changed) == 1 and '::cmd_get<' in changed[0], changed
        else:
            assert not changed and report['strict_noop']
        rows.append(dict(control=name, result='PASS' if expected == 0 else 'REJECTED',
                         changed=changed, returncode=result.returncode))
    (out / 'results.json').write_text(json.dumps(rows, indent=2) + '\n')
    print(json.dumps(rows, indent=2))


if __name__ == '__main__':
    main()
