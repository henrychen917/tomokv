#!/usr/bin/env python3
"""Serverless EX witnesses and broken-code controls; never executes tomokv."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
from exbatch_artifacts import GROUPS, plan, verify


def control(source, group):
    out = ROOT / 'build/exbatch/units' / source.name / group
    out.mkdir(parents=True, exist_ok=True)
    candidate = out / 'unit'
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    receipt = out / 'source.sha256'
    if not candidate.exists() or not receipt.exists() or receipt.read_text() != digest:
        intended = plan(source, group)
        raw = bytearray(source.read_bytes())
        for patch in intended['patches']:
            at = patch['offset']; raw[at:at+5] = bytes.fromhex(patch['after'])
        candidate.write_bytes(raw); candidate.chmod(0o755)
        verify(source, candidate, group, out)
        (out / 'planned-retargets.json').write_text(json.dumps(intended, indent=2) + '\n')
        receipt.write_text(digest)
    return candidate


def invoke(binary, selection, failure=None):
    result = subprocess.run([str(binary), selection], capture_output=True, timeout=30)
    stderr = result.stderr.decode()
    if failure:
        assert result.returncode != 0 and failure in stderr, (binary, selection, result)
    else:
        assert result.returncode == 0, (binary, selection, result.stdout, result.stderr)
    return dict(binary=str(binary.relative_to(ROOT)), selection=selection, rc=result.returncode,
                expected_failure=failure, stdout=(result.stdout.decode() if selection != 'wire' else None),
                stdout_sha256=hashlib.sha256(result.stdout).hexdigest(),
                stdout_bytes=len(result.stdout), stderr=stderr, _raw=result.stdout)


def run(group):
    rows = []
    for name in ('exbatch-unit', 'exbatch-db0-unit'):
        source = ROOT / 'build' / name
        if group == 'publication':
            rows.append(invoke(source, 'publication'))
            rows.append(invoke(control(source, 'ex1'), 'publication', 'unchanged publication must issue zero stores'))
        elif group == 'watch':
            rows.append(invoke(source, 'watch'))
            rows.append(invoke(source, 'watch-loads'))
            rows.append(invoke(control(source, 'watch-no-update'), 'watch', 'WATCH add arms gate'))
            rows.append(invoke(control(source, 'watch-old-loads'), 'watch-loads',
                               'unarmed WATCH gate must not read either cold map'))
            rows.append(invoke(control(source, 'ex3'), 'watch'))
        elif group == 'metadata':
            rows.append(invoke(source, 'metadata'))
            rows.append(invoke(control(source, 'ex6'), 'metadata', 'dispatch metadata resolution must allocate nothing'))
            post = invoke(source, 'wire')
            pad = invoke(control(source, 'all'), 'wire')
            assert post['_raw'] == pad['_raw'], 'PRE/PAD and POST metadata wire bytes changed'
            rows.extend((post, pad))
        else:
            raise AssertionError('unknown group')
    for row in rows: row.pop('_raw')
    out = ROOT / 'build/exbatch/checks' / (group + '-unit.json')
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(rows, indent=2) + '\n')
    print(f'PASS exbatch {group}: both database builds, {len(rows)} positive/negative checks')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('group', choices=['publication', 'watch', 'metadata'])
    run(parser.parse_args().group)
