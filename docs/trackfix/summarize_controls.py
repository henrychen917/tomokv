"""Count actual duplicate frames in every retained fresh climon seed-19 run."""
import ast
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent
prefix = b'>2\r\n$10\r\ninvalidate\r\n'
rows = []
for directory in sorted((ROOT / 'tracking-controls').iterdir()):
    source = directory / 'results.json'
    if not source.exists():
        continue
    for row in json.loads(source.read_text()):
        path = directory / f"{row['arm']}-{row['roll']}.log"
        lines = path.read_text().splitlines()
        observations = []
        label = ''
        for index, line in enumerate(lines):
            if line.startswith('  DIFF '):
                label = line.strip()
            if not line.startswith('    target:'):
                continue
            target = ast.literal_eval(line.split(': ', 1)[1])
            oracle = ast.literal_eval(lines[index + 1].split(': ', 1)[1])
            assert lines[index + 1].startswith('    oracle:')
            duplicate = (isinstance(target, bytes) and isinstance(oracle, bytes)
                         and oracle.startswith(prefix) and target == oracle * 2)
            observations.append(dict(label=label, duplicate_frame=bool(duplicate),
                target_frame_count=target.count(prefix) if isinstance(target, bytes) else None,
                oracle_frame_count=oracle.count(prefix) if isinstance(oracle, bytes) else None,
                target_repr=repr(target), oracle_repr=repr(oracle)))
        row.update(duplicate_frames=sum(x['duplicate_frame'] for x in observations),
                   other_differences=sum(not x['duplicate_frame'] for x in observations),
                   observations=observations, log=str(path.relative_to(ROOT)))
        assert row['duplicate_frames'] == row['duplicate_comparisons'], row
        rows.append(row)
(ROOT / 'control-counts.json').write_text(json.dumps(rows, indent=2) + '\n')
pre = [r for r in rows if r['arm'] == 'PRE' and r['roll'] >= 11]
pre += [r for r in rows if r['arm'] == 'PRE-extra']
post = [r for r in rows if r['arm'] == 'POST-final']
assert len(pre) == 20
table = ['# Fresh seed-19 duplicate frames per run', '',
         'PRE runs 11–30 are the 20 retained port-confined controls. Earlier PRE runs and the',
         'first accounting revision remain in control-counts.json, with all raw logs.', '',
         '| Pair | PRE run | PRE duplicate frames | Final POST duplicate frames |',
         '|---:|---:|---:|---:|']
for index, before in enumerate(pre):
    after = post[index] if index < len(post) else None
    table.append(f"| {index + 1} | {before['roll']} | {before['duplicate_frames']} | "
                 + (str(after['duplicate_frames']) if after else 'RUNNING') + ' |')
table += ['', f'Final POST runs completed: {len(post)}/20.', '']
(ROOT / 'control-counts.md').write_text('\n'.join(table))
print('PRE controlled runs', len(pre), 'POST final', len(post), 'all retained', len(rows))
