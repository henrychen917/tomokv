#!/usr/bin/env python3
"""Classify the complete, unmodified ccfix byte inventory for perfex2."""
import json
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / 'docs/perfex2/identity'

reasons = {
    'tomo_db0::(anonymous namespace)::cmd_flush(tomo_db0::Shard&, tomo_db0::Op&)':
        'Cold FLUSH handler: inlined snapshot-clear sample reset.',
    'tomo_db0::FlatStore::clear()':
        'Cold FLUSH/reload/replay clear: reset the discarded population sample.',
    'tomo_db0::command_client_migration_extract(tomo_db0::Client*)':
        'Unedited cold client-role-migration metadata extraction; compiler allocation change.',
    'tomo_db0::AofManager::~AofManager()':
        'Unedited cold AOF teardown; compiler inlining change (two aliases).',
    'tomo_db0::(anonymous namespace)::manifest_name(std::__cxx11::basic_string<char, std::char_traits<char>, std::allocator<char> > const&)':
        'Unedited cold persistence manifest path construction; compiler allocation change.',
}
rows = json.loads((OUT / 'changed-bodies.json').read_text())
summary = json.loads((OUT / 'summary.json').read_text())
assert summary['hot'] == summary['hot_equal'], 'selected hot body changed'
assert summary['handlers'] - summary['handlers_equal'] == 1
for row in rows:
    assert row['name'] in reasons, f'unexpected body: {row}'
    row['reason'] = reasons[row['name']]
assert set(row['name'] for row in rows) == set(reasons), 'review the changed-body inventory'
source = subprocess.check_output(
    ['git', 'diff', '--name-only', 'f437ab255', '--', 'src'], cwd=ROOT, text=True).splitlines()
assert source == ['src/cmd/storesize.cc', 'src/store/flatstore.h'], source
(OUT / 'cold-bodies.json').write_text(json.dumps(rows, indent=2) + '\n')
result = dict(total=summary['total'], identical=summary['equal'], cold_changed=len(rows),
              selected_hot=summary['hot'], selected_hot_identical=summary['hot_equal'],
              handlers=summary['handlers'], handlers_identical=summary['handlers_equal'],
              changed_handler='cmd_flush', production_source_files=source,
              raw_checker='unchanged; exits 1 because its admitted cold-handler list omits FLUSH',
              comparison='merged previous perfex POST (04a9a0cce production sources) versus perfex2')
(OUT / 'cold-only-summary.json').write_text(json.dumps(result, indent=2) + '\n')
print(json.dumps(result, indent=2))
