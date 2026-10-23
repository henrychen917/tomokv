"""Strict linked-body comparison with PRE; retain every changed body."""
import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
spec = importlib.util.spec_from_file_location('inventory', ROOT / 'docs/wave4/identity.py')
audit = importlib.util.module_from_spec(spec)
spec.loader.exec_module(audit)
audit.OUT = ROOT / 'build/trackfix/trackfix2-identity'


def main():
    before = audit.inventory(ROOT / 'build/tomokv-PRE')
    after = audit.inventory(ROOT / 'build/tomokv')
    rows = audit.compare(after, {'headline': before})
    changed = [row for row in rows if not row['equal']]
    from identity_reasons import reason
    for row in changed:
        row["reason"] = reason(row)
    result = dict(pre={k: v for k, v in before.items() if k != 'groups'},
                  post={k: v for k, v in after.items() if k != 'groups'},
                  total=len(rows), identical=sum(row['equal'] for row in rows),
                  changed=changed,
                  command_hot_total=sum(row['command_hot'] for row in rows),
                  command_hot_changed=[row for row in changed if row['command_hot']],
                  all_commands=[row for row in rows if '::cmd_' in row['name']])
    dest = ROOT / 'docs/trackfix/trackfix2/identity'
    dest.mkdir(parents=True, exist_ok=True)
    (dest / 'summary.json').write_text(json.dumps(result, indent=2) + '\n')
    (dest / 'changed-bodies.md').write_text('# PRE versus POST changed bodies\n\n' + ''.join(
        '- `' + row['name'] + '`: ' + row['reason'] + '\n' for row in changed))
    print(json.dumps({k: v for k, v in result.items() if k not in ('changed', 'all_commands')}), flush=True)


if __name__ == '__main__':
    main()
