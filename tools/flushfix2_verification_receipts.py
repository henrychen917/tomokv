#!/usr/bin/env python3
"""Archive completed gate-job and differential receipts without changing verdicts."""
from collections import Counter
import argparse
import hashlib
import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
RUN = ROOT/'build/flushfix2/verification/final'
OUT = ROOT/'docs/flushfix2/verification-final.json'


def ref(path):
    return dict(path=str(path.relative_to(ROOT)),
                sha256=hashlib.sha256(path.read_bytes()).hexdigest())


def gate(log, completed=None):
    text = log.read_text()
    root = Path(re.search(r'artifacts: (.+)', text)[1])
    expected = re.search(r'PARTIAL jobs \(including prerequisites\): (.+)', text)[1].split()
    omitted = [name for name in expected if completed is not None and name not in completed]
    rows = []
    jobs = []
    for name in expected:
        if name in omitted:
            continue
        folder = root/'jobs'/name
        assert (folder/'done').exists(), (root, name, 'unfinished')
        done = (folder/'done').read_text().strip().split('\t')
        ledger = folder/'ledger'
        scored = []
        for line in ledger.read_text().splitlines() if ledger.exists() else []:
            verdict, seconds, label = line.split('\t', 2)
            assert verdict in ('ok', 'FAIL'), (ledger, line)
            row = dict(job=name, label=label, verdict=verdict, seconds=float(seconds))
            scored.append(row)
            rows.append(row)
        jobs.append(dict(name=name, done=done, ledger=ref(ledger) if ledger.exists() else None,
                         rows=scored))
    return dict(log=ref(log), root=str(root.relative_to(ROOT)), jobs=jobs,
                omitted_unfinished_jobs=omitted,
                scored_rows=len(rows), verdicts=dict(Counter(r['verdict'] for r in rows)))


def differ(phase, run=None):
    run = run or RUN
    log = run/(phase+'.log')
    text = log.read_text()
    match = re.search(r'DIFFER GATE: pass=(\d+) fail=(\d+) runtime=(\S+)', text)
    assert match, (phase, 'unfinished')
    folder = run/phase
    coverage = []
    commands = Counter()
    for path in sorted(folder.glob('*.coverage.json')):
        value = json.loads(path.read_text())
        commands.update(value['commands'])
        coverage.append(ref(path))
    return dict(phase=phase, log=ref(log), passed=int(match[1]), failed=int(match[2]),
                runtime=match[3], seeds=json.loads((folder/'seeds.json').read_text()),
                skipped=[line.strip() for line in text.splitlines() if 'SKIP' in line],
                failures=[line.strip() for line in text.splitlines() if 'FAIL' in line],
                mechanisms=[line.strip() for line in text.splitlines() if 'read-local lane fired' in line],
                compared_commands=dict(sorted(commands.items())), coverage=coverage)


def main():
    global RUN
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--label', default='final-v2')
    parser.add_argument('--binary', type=Path, default=ROOT/'build/flushfix2/post-v2/tomokv')
    args = parser.parse_args()
    RUN = ROOT/'build/flushfix2/verification'/args.label
    primary = json.loads((RUN/'runs.json').read_text())
    armed = json.loads((RUN/'armed-runs.json').read_text())
    split_root = RUN.with_name(args.label+'-split')
    split = json.loads((split_root/'runs.json').read_text())
    resumed = json.loads((RUN/'broad-resume-run.json').read_text())
    interruption = json.loads((RUN/'broad-interruption.json').read_text())
    assert {r['phase'] for r in primary} == {'directed'}
    assert {r['phase'] for r in armed} == {'differ-armed-uring', 'differ-armed-epoll'}
    assert {r['phase'] for r in split} == {'differ-uring', 'differ-epoll'}
    assert 'status' in resumed
    gates = {name:gate(RUN/(name+'.log')) for name in ('directed', 'broad-resume', 'notifycompat', 'topology')}
    gates['broad-original'] = gate(RUN/'broad.log', interruption['completed'])
    broad = {j['name']:j for name in ('broad-original', 'broad-resume') for j in gates[name]['jobs']}
    assert set(interruption['expected']) <= broad.keys(), set(interruption['expected'])-broad.keys()
    broad_rows = [row for job in broad.values() for row in job['rows']]
    result = dict(binary=ref(args.binary.resolve()),
                  gate_source=ref(ROOT/'tests/gate.sh'), differ_source=ref(ROOT/'tests/differ_gate.sh'),
                  runs=primary+[resumed]+armed+split,
                  broad_interruption=interruption,
                  broad_coverage=dict(jobs=sorted(broad), scored_rows=len(broad_rows),
                      verdicts=dict(Counter(r['verdict'] for r in broad_rows)),
                      failures=[r for r in broad_rows if r['verdict']=='FAIL']),
                  topology_run=json.loads((RUN/'topology-run.json').read_text()),
                  notifycompat_run=json.loads((RUN/'notifycompat-run.json').read_text()),
                  t9_rechecks=json.loads((ROOT/'docs/flushfix2/t9-rechecks.json').read_text()),
                  flip_failure=ref(ROOT/'docs/flushfix2/flip-failure.json'),
                  gates=gates, differential=[differ(r['phase']) for r in armed] +
                                             [differ(r['phase'], split_root) for r in split])
    OUT.write_text(json.dumps(result, indent=2)+'\n')
    print({name:r['verdicts'] for name,r in gates.items()})
    print([(r['phase'],r['passed'],r['failed']) for r in result['differential']])


if __name__ == '__main__':
    main()
