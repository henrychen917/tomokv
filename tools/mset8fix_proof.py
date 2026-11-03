#!/usr/bin/env python3
"""mset8fix: fold the gate-job proof runs into docs/mset8fix/proof/summary.json. No server.

Inputs are the per-run copies that tools/mset8fix_loop.sh keeps of each tests/gate.sh
GATE_ONLY_JOBS run (ledger.partial and each job's result/leg files): atomwake rows on PRE and
POST, txnorder FIFO live fairness on PRE and POST, and the touched-job ledgers. The *-hogs6 series
used the earlier six-hogs row definition (commit 25b24430e8), the others four hogs (9f87b7886c).
"""

# CPUs of each series (server / load; one CCD each, 16 MB L3 per 8-core CCX). CCD 7 (112-127) is
# also the CPU mask of the coordinator's pinned lifeboat, screen, lane-monitor and pending-mover
# processes; the probe driver runs on the first load CPU.
PLACEMENT = {
    'pre-2s': '32-39 / 40-47', 'pre-1s': '48-55 / 56-63', 'post-atomwake-ccd4': '64-71 / 72-79',
    'post-atomwake': '112-119 / 120-127 (shared CCD 7)', 'fifo-pre': '96-103 / 104-111',
    'fifo-post': '0-7 / 8-15', 'post-atomwake-hogs6': '112-119 / 120-127 (shared CCD 7)',
    'pre-2s-hogs6': 'not recorded', 'pre-1s-hogs6': 'not recorded',
}
import glob
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROOF = ROOT / 'build/mset8fix/proof'
OUT = ROOT / 'docs/mset8fix/proof'


def ledger(path):
    rows = [line.rstrip('\n').split('\t') for line in Path(path).read_text().splitlines()]
    return [dict(verdict=r[0], seconds=float(r[1]), label=r[2]) for r in rows if r and r[0] in ('ok', 'FAIL')]


def atomwake(label):
    runs = []
    for path in sorted(glob.glob(str(PROOF / label / 'run*.ledger')), key=lambda p: int(Path(p).stem[3:])):
        run = Path(path).stem
        rows = ledger(path)
        legs = {}
        for result in sorted(glob.glob(str(PROOF / label / f'{run}-atomwake-live-*' / 'result.json')) +
                             glob.glob(str(PROOF / label / f'{run}-atomwake-live-*.json'))):
            d = json.loads(Path(result).read_text())
            key = f"{d['mode']} {d['engine']}"
            legs[key] = dict(passed=d['passed'], legs=len(d['legs']), legs_passed=sum(l['passed'] for l in d['legs']),
                             probe_batches=[min(l.get('probe_batches') or 0 for l in d['legs']),
                                            max(l.get('probe_batches') or 0 for l in d['legs'])],
                             hog_median_batches=[min(l.get('hog_median_batches') or 0 for l in d['legs']),
                                                 max(l.get('hog_median_batches') or 0 for l in d['legs'])],
                             probe_share=[round(min(l.get('probe_share') or 0 for l in d['legs']), 4),
                                          round(max(l.get('probe_share') or 0 for l in d['legs']), 3)],
                             probe_max_ms=[round(min(l.get('probe_max_ms') or 0 for l in d['legs']), 2),
                                           round(max(l.get('probe_max_ms') or 0 for l in d['legs']), 2)],
                             hog_max_ms=round(max(l.get('hog_max_ms') or 0 for l in d['legs']), 2),
                             min_window_stalls=min(l.get('window_stalls') or 0 for l in d['legs']),
                             failed_legs=[(l['label'], l['reasons']) for l in d['legs'] if not l['passed']])
        runs.append(dict(run=run, rows=rows, legs=legs))
    return runs


def fifo(label):
    runs = []
    for path in sorted(glob.glob(str(PROOF / label / 'run*.ledger')), key=lambda p: int(Path(p).stem[3:])):
        run = Path(path).stem
        legs = []
        for leg in sorted(glob.glob(str(PROOF / label / f'{run}-txnorder_fifo_live' / 'fifo-*.json'))):
            d = json.loads(Path(leg).read_text())
            f = d.get('fifo', {})
            legs.append(dict(leg=Path(leg).stem[5:], passed=bool(d.get('pass')),
                             share=round(f.get('share', 0), 4), expected_share=f.get('expected_share'),
                             plain_p99_ms=round(f.get('plain_p99', 0) * 1e3, 3),
                             plain_p100_ms=round(f.get('plain_p100', 0) * 1e3, 3),
                             bound99_ms=round(f.get('bound99', 0) * 1e3, 3)))
        runs.append(dict(run=run, rows=ledger(path), legs=legs,
                         max_plain_p100_ms=max((l['plain_p100_ms'] for l in legs), default=None)))
    return runs


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    doc = dict(atomwake={k: atomwake(k) for k in ('pre-2s', 'pre-1s', 'post-atomwake-ccd4', 'post-atomwake',
                                                    'pre-2s-hogs6', 'pre-1s-hogs6', 'post-atomwake-hogs6')},
               placement=PLACEMENT,
               fifo={k: fifo(k) for k in ('fifo-pre', 'fifo-post')},
               touched={k: ledger(PROOF / p) for k, p in (('bigrun-post', 'bigrun/post.ledger'),
                                                          ('txnorder2-post', 'post-txnorder2/run1.ledger'),
                                                          ('timed-post', 'post-timed/run1.ledger'))
                        if (PROOF / p).exists()})
    (OUT / 'summary.json').write_text(json.dumps(doc, indent=1) + '\n')
    for k, runs in doc['atomwake'].items():
        print(k, [(r['run'], sum(x['verdict'] == 'ok' for x in r['rows']), sum(x['verdict'] == 'FAIL' for x in r['rows']))
                  for r in runs])
    for k, runs in doc['fifo'].items():
        print(k, [(r['run'], r['max_plain_p100_ms'], sum(not l['passed'] for l in r['legs'])) for r in runs])
    for k, rows in doc['touched'].items():
        print(k, sum(r['verdict'] == 'ok' for r in rows), 'ok', sum(r['verdict'] == 'FAIL' for r in rows), 'FAIL')


if __name__ == '__main__':
    main()
