#!/usr/bin/env python3
"""Bind the six complete datafix1 reruns to every owned server's C environment."""
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DOC = ROOT / 'docs/wave13'
JOBS = {'datafix1_randscan': 6, 'datafix1_hexpire': 6, 'datafix1_bitfield': 6,
        'datafix1_lists': 12, 'datafix1_spop': 6, 'datafix1_geo': 12}


def main():
    receipt_path = DOC / 'jobs/landing-datafix1-C.json'
    receipt = json.loads(receipt_path.read_text())
    assert receipt['exit'] == 0 and receipt['binary_unchanged']
    assert receipt['source_tree_unchanged'] and receipt['tests_tools_unchanged']
    assert receipt['env']['LC_ALL'] == 'C'
    post = hashlib.sha256((ROOT / 'build/wave13/tomokv-POST').read_bytes()).hexdigest()
    assert receipt['binary_sha256'] == post
    rows = []
    for name, legs in JOBS.items():
        directory = Path(receipt['artifacts']) / 'jobs' / name
        assert list(map(int, (directory / 'done').read_text().split())) == [0, 1, 0]
        events = [json.loads(line) for line in (directory / 'proof.log').read_text().splitlines()
                  if line.startswith('{')]
        starts = {event['pid']: event for event in events if 'start' in event}
        locales = {event['pid']: event['boot_locale'] for event in events if 'boot_locale' in event}
        assert len(starts) == 2 * legs and starts.keys() == locales.keys(), name
        assert all(value == {'LANG': 'C', 'LC_ALL': 'C'} for value in locales.values()), name
        oracles = [row['start'] for row in starts.values()
                   if Path(row['start'][3]).name == 'redis-server']
        assert len(oracles) == legs
        assert all('--set-proc-title' in argv and argv[argv.index('--set-proc-title') + 1] == 'no'
                   for argv in oracles), name
        summary = json.loads((directory / 'proof/summary.json').read_text())
        assert summary['legs'] == legs and summary['failures'] == [], name
        rows.append(dict(job=name, legs=legs, boots=len(starts),
                         oracle_title_updates_disabled=True,
                         actual_environments=locales, passed=True,
                         proof_sha256=hashlib.sha256((directory / 'proof.log').read_bytes()).hexdigest()))
    result = dict(receipt=str(receipt_path.relative_to(ROOT)), binary_sha256=post,
                  helper_sha256=hashlib.sha256((ROOT / 'tests/datafix1_common.py').read_bytes()).hexdigest(),
                  jobs=rows, boots=sum(row['boots'] for row in rows), passed=True,
                  not_run=dict(job='datafix1_locale',
                      reason='Its inherited non-C default witness conflicts with the required C boot environment; assertion retained.'))
    (DOC / 'locale-C-reruns.json').write_text(json.dumps(result, indent=2) + '\n')
    print(result['boots'], 'C-pinned target/oracle boots; all six whole jobs passed')


if __name__ == '__main__':
    main()
