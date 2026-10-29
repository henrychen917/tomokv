#!/usr/bin/env python3
"""Archive completed gate-job and differential receipts without changing verdicts."""
from collections import Counter
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


def gate(log):
    text = log.read_text()
    root = Path(re.search(r'artifacts: (.+)', text)[1])
    expected = re.search(r'PARTIAL jobs \(including prerequisites\): (.+)', text)[1].split()
    rows = []
    jobs = []
    for name in expected:
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
                scored_rows=len(rows), verdicts=dict(Counter(r['verdict'] for r in rows)))


def differ(phase):
    log = RUN/(phase+'.log')
    text = log.read_text()
    match = re.search(r'DIFFER GATE: pass=(\d+) fail=(\d+) runtime=(\S+)', text)
    assert match, (phase, 'unfinished')
    folder = RUN/phase
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
                compared_commands=dict(sorted(commands.items())), coverage=coverage)


def main():
    primary = json.loads((RUN/'runs.json').read_text())
    armed = json.loads((RUN/'armed-runs.json').read_text())
    assert {r['phase'] for r in primary} == {'directed', 'broad', 'differ-uring', 'differ-epoll'}
    assert {r['phase'] for r in armed} == {'differ-armed-uring', 'differ-armed-epoll'}
    gates = {name:gate(RUN/(name+'.log')) for name in ('directed', 'broad', 'notifycompat', 'topology')}
    result = dict(binary=ref(ROOT/'build/flushfix2/post-final/tomokv'),
                  gate_source=ref(ROOT/'tests/gate.sh'), differ_source=ref(ROOT/'tests/differ_gate.sh'),
                  runs=primary+armed, topology_run=json.loads((RUN/'topology-run.json').read_text()),
                  gates=gates, differential=[differ(r['phase']) for r in primary+armed
                                             if r['phase'].startswith('differ-')])
    OUT.write_text(json.dumps(result, indent=2)+'\n')
    print({name:r['verdicts'] for name,r in gates.items()})
    print([(r['phase'],r['passed'],r['failed']) for r in result['differential']])


if __name__ == '__main__':
    main()
