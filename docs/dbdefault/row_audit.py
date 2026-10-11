"""Review every declared row and collection line; never execute the gate."""
from pathlib import Path
import inspect
import json
import re
import subprocess
import sys

root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(root / "tests"))
import gate_ledger_fixture as fixture

source = (root / "tests/gate.sh").read_text()
# Preserve the fixture parser's finite-loop expansion and annotate each collected
# row with its owner job. Only the coordinator's tailgen row has no collected job.
code = inspect.getsource(fixture.source_labels).replace('def source_labels(gate):', 'def rows(gate):')
code = code.replace('return [public_label(name)]', 'return [(name, public_label(name))]')
code = code.replace('return evaluate(declarations(body), dict(global_values, **{"1": argument}), collect)',
                    'return [(name, label) for label in evaluate(declarations(body), dict(global_values, **{"1": argument}), collect)]')
space = dict(fixture.__dict__)
exec(code, space)
rows = space['rows'](source)
serverless = set("release asan config_unit flip_unit filter_unit ring_unit flipfix_units core_units "
    "lbplanner_units persistfix_units exbatch_units wb_rule_units wbland_units reorder_sync "
    "reorder_engagement reorder_identity splitlocal_units storage_units atomic_units netcmd_units "
    "acl_metadata cmd_metadata abba_selftest wait_units".split())
records = []
for index, row in enumerate(rows, 1):
    job, label = row if isinstance(row, tuple) else ('coordinator', row)
    if job in serverless or label == 'shutdown policy + signal handoff serverless':
        decision = 'serverless / linked image audit; no server boot'
    elif job == 'dbdefault':
        decision = 'default 16, no --databases; 1s and 2s'
    elif job.startswith('multidb-'):
        decision = 'explicit 16 (launch override + mdbqsbr_live.py)'
    elif job.startswith('differ-'):
        decision = 'explicit 16 differential; equivalence subtest inherits explicit 1'
    elif job == 'exbatch_live':
        decision = 'explicit 4 (launch override)'
    elif job == 'boot_grammar':
        decision = 'reject_boot supplies 1; parser must reject before listener'
    else:
        decision = 'explicit 1 via launch or audited direct helper'
    records.append((index, job, label, decision))
out = root / 'docs/dbdefault'
(out / 'gate-rows.tsv').write_text('row\tjob\tlabel\timage decision\n' +
    ''.join('\t'.join(map(str, row)) + '\n' for row in records))

def quick_part(text):
    first = text.index('\nstart_workers\n')
    cut = text.index('\nif [ "$TIER" = quick ]; then', first)
    end = text.index('\n# Every worker has reaped', cut)
    return text[:cut] + text[end:], cut

base = subprocess.check_output(['git', 'rev-parse', 'origin/cpp'], cwd=root, text=True).strip()
pre = subprocess.check_output(['git', 'show', base + ':tests/gate.sh'], cwd=root, text=True)
qsource, qline = quick_part(source)
quick, full = len(fixture.source_labels(qsource)), len(fixture.source_labels(source))
counts = dict(audited_origin=base, base_quick=int(re.search(r'^EXPECT_QUICK=(\d+)', pre, re.M)[1]),
    base_full=int(re.search(r'^EXPECT_FULL=(\d+)', pre, re.M)[1]), quick=quick, full=full,
    DQ=quick-len(fixture.source_labels(quick_part(pre)[0])), DF=full-len(fixture.source_labels(pre)),
    quick_exit_line=source[:qline].count('\n')+1,
    default_row_collection_line=source[:source.index('collect_job dbdefault')].count('\n')+1)
labels = json.loads((root / fixture.FIXTURE).read_text())['labels']
assert fixture.Counter(fixture.source_labels(source)) == fixture.Counter(labels)
counts['fixture_labels_match'] = True
# Demonstrate the maintained fixture with the proposed count IN MEMORY ONLY.
# Neither EXPECT constant nor the checker is edited; ordinary checker remains red.
proposed = re.sub(r'^EXPECT_FULL=\d+', 'EXPECT_FULL=' + str(full), source, flags=re.M)
assert fixture.check(proposed, labels) == labels
counts['proposed_count_check_passes_in_memory'] = True
(out / 'gate-counts.json').write_text(json.dumps(counts, indent=2) + '\n')
print(json.dumps(counts))
