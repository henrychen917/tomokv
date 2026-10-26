"""Before/after ABBA self-test timings: row time from the gate ledger, per-suite and per-test from the observer."""
import glob
import json
import os
import statistics
import sys
from pathlib import Path

S = Path('/tmp/claude-1000/-home-user-Projects/ee6eb242-5302-49cf-b767-1a2d8d8f0f61/scratchpad/timing')
CODEX_BEFORE_I = Path('/home/user/Projects/cx-harness5/docs/harness5/before')  # same 8+8 geometry, this base


def row_seconds(folder):
    for line in (folder / 'ledger.partial').read_text().splitlines():
        if line.endswith('ABBA comparison + saturation negative controls'):
            verdict, seconds, _ = line.split('\t')
            return verdict, float(seconds)
    raise SystemExit(f'no row in {folder}')


def suites(folder):
    out = {}
    for path in glob.glob(str(folder / 'timings' / '*.json')):
        data = json.loads(Path(path).read_text())
        name = Path(path).stem.rsplit('-', 1)[0]
        out[name] = out.get(name, 0) + data['seconds']
    return out


runs = {}
for folder in sorted(S.glob('[LI]-*-*')):
    geo, arm, idx = folder.name.split('-')
    head = (folder / 'tree-head').read_text().strip()[:9]
    status = (folder / 'tree-status').read_text().strip()
    runs.setdefault((geo, arm), []).append(dict(folder=folder, idx=idx, row=row_seconds(folder), suites=suites(folder),
                                                head=head, clean=not status))
if CODEX_BEFORE_I.exists():
    runs.setdefault(('I', 'before'), []).append(dict(folder=CODEX_BEFORE_I, idx='codex', row=row_seconds(CODEX_BEFORE_I),
        suites=suites(CODEX_BEFORE_I), head='3700b51d7', clean=True))
report = {}
for (geo, arm), items in sorted(runs.items()):
    secs = [i['row'][1] for i in items]
    print(f"{geo} {arm}: rows {[f'{v}:{s:.2f}' for v, s in (i['row'] for i in items)]} heads {[i['head'] for i in items]} "
          f"clean {[i['clean'] for i in items]} median {statistics.median(secs):.2f}")
    report[f'{geo}-{arm}'] = dict(rows=[i['row'] for i in items], median=statistics.median(secs),
                                  heads=[i['head'] for i in items],
                                  suites={k: statistics.median([i['suites'].get(k, 0) for i in items])
                                          for k in sorted({k for i in items for k in i['suites']})})
for geo in ('L', 'I'):
    b, a = report.get(f'{geo}-before'), report.get(f'{geo}-after')
    if not (b and a):
        continue
    print(f'\n== {geo}: suite medians (seconds), before -> after')
    for k in sorted(set(b['suites']) | set(a['suites']), key=lambda k: -max(b['suites'].get(k, 0), a['suites'].get(k, 0))):
        print(f"   {k:28} {b['suites'].get(k, 0):8.2f} -> {a['suites'].get(k, 0):8.2f}")
(S / 'analysis.json').write_text(json.dumps(report, indent=1, default=str) + '\n')
