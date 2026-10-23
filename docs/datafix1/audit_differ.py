"""Check the gate's frozen inventory, journals and strict folds without rerunning legs."""
from pathlib import Path
import json
import re
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'tests'))
from differ_fanout import load_plan, expected_legs, read_journal, fold

for arm in sys.argv[1:]:
    name = arm + '-differ-serial'
    log = (ROOT / 'docs/datafix1' / (name + '-gate.log')).read_text()
    assert 'GATE(PARTIAL):' in log, (name, 'coordinator still running')
    run = Path(re.search(r'artifacts: (.*)', log)[1])
    plan = load_plan(run / 'differ-plan.json')
    result = dict(arm=arm, run=str(run), seeds=plan['manifest']['seeds'],
                  suite_count=len(plan['suites']), parts={}, folds={})
    for part in ('split-0', 'split-1', 'armed-0', 'armed-1'):
        directory = run / 'jobs' / ('differ-' + part) / 'differ'
        rows = read_journal(directory)
        expected = expected_legs(plan, part)
        actual = [row[:4] for row in rows]
        result['parts'][part] = dict(expected=len(expected), executed=len(rows),
            exact_inventory=actual == expected,
            failures=[dict(suite=r[0], atomic=r[1], seed=r[2], repeat=r[3],
                           rc=r[4], log=str(directory / r[5])) for r in rows if r[4]])
    equivalence = run / 'jobs/differ-equivalence/differ'
    directories = [p for p in equivalence.glob('mode-equivalence-*') if p.is_dir()]
    assert len(directories) == 1, directories
    directory = directories[0]
    stream = json.loads((directory / 'stream.json').read_text())
    cells = json.loads((directory / 'results.json').read_text())
    completion = json.loads((equivalence / 'complete.json').read_text())
    result['mode_equivalence'] = dict(
        declared_cells=len(stream['cells']), executed_cells=len(cells),
        exact_inventory=[cell['cell'] for cell in cells] == stream['cells'],
        all_pass=all(cell['verdict'] == 'ok' and cell['reached'] for cell in cells),
        owned_boots=len(list(directory.glob('*/replay/exit.json'))) +
                    len(list(directory.glob('*/witness/exit.json'))),
        observed_engines=sorted({cell['witnesses']['before']['multiplexing_api']
                                 for cell in cells}),
        observed_executables=sorted({cell['witnesses']['before']['executable']
                                     for cell in cells}),
        complete=completion)
    for group in ('split', 'armed'):
        try:
            result['folds'][group] = fold(plan, group, run)
        except Exception as error:
            result['folds'][group] = dict(complete=False, error=str(error))
    path = ROOT / 'docs/datafix1' / (arm + '-differ-inventory.json')
    path.write_text(json.dumps(result, indent=2) + '\n')
    print(arm, 'legs', sum(p['executed'] for p in result['parts'].values()),
          'exact inventory', all(p['exact_inventory'] for p in result['parts'].values()),
          'failed legs', sum(len(p['failures']) for p in result['parts'].values()),
          'folds', {k: v['complete'] for k, v in result['folds'].items()}, flush=True)
