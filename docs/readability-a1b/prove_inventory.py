#!/usr/bin/env python3
"""Validate all twenty supplied references and the complete archive frontier."""
import gzip
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / 'docs/readability-a1b/evidence'
manifest = json.loads((ROOT / 'docs/readability-a1b/known_references.json').read_text())
assert len(manifest) == 20
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--graph', type=Path, default=ROOT / 'build/readability-a1b/callers.json')
source = parser.parse_args().graph
graph = json.loads(source.read_text())
by_stem = {Path(p).stem: p for p in manifest}
pattern = re.compile(r'(?<![\w-])(' + '|'.join(map(re.escape, by_stem)) + r')(?![\w-])')
hits = {p: [] for p in manifest}
for name in subprocess.check_output(['git', 'ls-files', 'Makefile', 'tests', 'tools'], cwd=ROOT, text=True).splitlines():
    if name.startswith('tools/archive/') or not (name == 'Makefile' or Path(name).suffix in ('.py', '.sh', '.mk')):
        continue
    if not (ROOT / name).exists():
        continue
    for line, text in enumerate((ROOT / name).read_text().splitlines(), 1):
        for match in pattern.finditer(text):
            hits[by_stem[match[0]]].append(dict(caller=name, line=line, text=text.strip()))
for path, refs in hits.items():
    assert refs, ('known reference disappeared from the audit', path)
    is_call = bool(graph['restored_or_required'].get(path))
    assert is_call == manifest[path].startswith('CALL:'), (path, manifest[path], is_call)
expected_callers = {'tests/cd13b_window_test.py': 'tests/gate.sh',
                    'tests/slowlog_identity.py': 'tests/gate.sh',
                    'tools/ccfix_audit.py': 'docs/wave9/budgets.py'}
for target, caller in expected_callers.items():
    assert any(edge['caller'] == caller for edge in graph['restored_or_required'][target]), (caller, target)
assert any(edge['target'] == 'docs/wave9/budgets.py' for edge in graph['edges']['tools/wave10.py'])
restored = json.loads((ROOT / 'docs/readability-a1b/restored.json').read_text())
remaining = json.loads((ROOT / 'docs/readability-a1/retired.json').read_text())
assert set(graph['restored_or_required']) == {r['original'] for r in restored}
for record in remaining:
    assert record['original'] not in graph['live'], record
    assert hashlib.sha256((ROOT / record['archive']).read_bytes()).hexdigest() == record['sha256'], record
for record in restored:
    assert not (ROOT / record['archive']).exists(), record
    assert hashlib.sha256((ROOT / record['original']).read_bytes()).hexdigest() == record['sha256'], record
# Every unresolved executable script pathname must have a concrete reviewed
# explanation. New unresolved callers fail rather than silently certify retirement.
script_reviews = [r for r in graph['review_required'] if r['pattern'].endswith(('.py', '.sh', '.mk'))]
assert len(script_reviews) == 1, script_reviews
review = script_reviews[0]
assert review['caller'] == 'tests/scriptatomic_strict.py' and review['kind'] == 'process-argv', review
assert review['expression'].startswith('subprocess.run([sys.executable, str(fixture),'), review
reviewed = json.loads((ROOT / 'docs/readability-a1b/reviewed_dynamic.json').read_text())[review['caller']]
review['source_sha256'] = hashlib.sha256((ROOT / review['caller']).read_bytes()).hexdigest()
assert review['source_sha256'] == reviewed['sha256'], 'generated-script producer changed; re-review required'
review['resolution'] = reviewed['resolution']
result = dict(known_references=[dict(path=p, disposition=manifest[p], references=hits[p],
                                  calls=graph['restored_or_required'].get(p, [])) for p in manifest],
              restored=graph['restored_or_required'], remaining_archive_count=len(remaining),
              archive_digests='all unchanged', roots=len(graph['roots']), reachable=len(graph['live']),
              script_reviews=script_reviews)
OUT.mkdir(parents=True, exist_ok=True)
(OUT / 'caller-audit.json').write_text(json.dumps(result, indent=2, sort_keys=True) + '\n')
# The full graph is reproducible and compressed only to stay below the 1 MB
# commit limit; its raw JSON stays in build/ for easy local inspection.
with (OUT / 'caller-graph.json.gz').open('wb') as output:
    with gzip.GzipFile(filename='', mode='wb', fileobj=output, mtime=0) as stream:
        stream.write(source.read_bytes())
print(f'20/20 references classified; {len(restored)} restored; {len(remaining)} archived digests verified; one generated-script sink reviewed')
