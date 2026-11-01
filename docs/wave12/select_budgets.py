#!/usr/bin/env python3
"""Choose compiler budgets, preserving CONFIG's approved lane body first."""
import gzip
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'tools'))
import wave12_budgets as trial

doc = ROOT / 'docs/wave12/budgets'
selected = json.loads((doc / 'selected.json').read_text())
extra = json.loads((doc / 'config-extra-score.json').read_text())
refs = {arm: trial.identity.inventory(path) for arm, path in trial.identity.REFS.items()}
decisions = []
for row in selected:
    if row['object'].endswith('/cmd/t_server.o'):
        scores = [json.loads(Path(r['output'] + '.frozen-score.json').read_text())
                  for r in row['trials'] if Path(r['output'] + '.frozen-score.json').exists()]
        if row['object'] == 'src/cmd/t_server.o':
            scores += extra
        namespace = 'tomo_db0::' if row['object'].startswith('db0/') else 'tomo::'
        for score in scores:
            with gzip.open(trial.identity.OUT / score['linked_sha256'] / 'inventory.json.gz', 'rt') as stream:
                inventory = json.load(stream)
            bodies = [r for r in trial.identity.compare(inventory, refs)
                      if r['name'].startswith(namespace) and '::cmd_config(' in r['name']]
            assert bodies
            score['config_identity'] = all('maxmemrace' in r['matches'] for r in bodies)
        best = min(scores, key=lambda r: (not r['config_identity'], r['score'],
                                          r['budget'] != row['old'], abs(r['budget'] - row['old'])))
        assert best['config_identity'], 'No approved CONFIG body found'
        row['budget'] = best['budget']
        row['score'] = best['score']
        row['decision'] = 'Exact maxmemrace CONFIG body, then command/hot/all-body score'
        row['config_trials'] = [{k: r[k] for k in ('budget', 'score', 'config_identity', 'linked_sha256')}
                                for r in scores]
    else:
        row['decision'] = 'Command bodies, single-lane hot bodies, all hot bodies, then all bodies'
    decisions.append(row)
(doc / 'final-selected.json').write_text(json.dumps(decisions, indent=2) + '\n')
makefile = ROOT / 'Makefile'
text = makefile.read_text()
for row in decisions:
    if row['old'] == row['budget']:
        continue
    prefix = '$(BUILD_ROOT)/' + row['object'] + ':'
    lines = [line for line in text.splitlines() if line.startswith(prefix) and 'large-unit-insns=' in line]
    assert len(lines) == 1
    old = lines[0]
    new = old.replace('large-unit-insns=' + str(row['old']), 'large-unit-insns=' + str(row['budget']))
    assert new != old
    text = text.replace(old, new)
    print(row['object'], row['old'], '->', row['budget'], row['decision'])
makefile.write_text(text)
