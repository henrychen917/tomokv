#!/usr/bin/env python3
"""Offline ctlfix PAD-A, linked-body audit and gate evidence archiving."""
import argparse
from collections import Counter
import gzip
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import shutil
import sys
import tarfile

from lbstall_artifacts import Elf

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'docs/ctlfix'


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def save(path, value):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(value, indent=2) + '\n')


def pad(source, destination, receipt):
    original = Elf(source)
    data = bytearray(original.data)
    patches = []
    for symbol in original.symbols:
        if 'ctlfix_correctnessEv' not in symbol['name']:
            continue
        assert original.body(symbol) == bytes.fromhex('b8 01 00 00 00 c3'), symbol
        section = original.sections[symbol['sec']]
        offset = section[4] + symbol['value'] - section[3] + 1
        assert data[offset] == 1
        data[offset] = 0
        patches.append(dict(symbol=symbol['name'], offset=offset, before=1, after=0))
    assert len(patches) in (1, 2), patches
    shutil.copyfile(source, destination)
    Path(destination).write_bytes(data)
    Path(destination).chmod(Path(source).stat().st_mode)
    twin = Elf(destination)
    assert original.sections == twin.sections and original.symbols == twin.symbols
    assert [i for i, (a, b) in enumerate(zip(original.data, twin.data)) if a != b] == sorted(
        p['offset'] for p in patches)
    save(receipt, dict(kind='A: PRE behaviour with POST text size/layout',
         source=str(source), twin=str(destination), post_sha256=sha(source), pad_sha256=sha(destination),
         every_function_address_and_size_identical=True, all_other_bytes_identical=True,
         patches=patches))
    print('PAD-A', destination, sha(destination))


def identity():
    spec = importlib.util.spec_from_file_location('ctlfix_identity', ROOT / 'docs/wave4/identity.py')
    audit = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(audit)
    audit.OUT = ROOT / 'build/ctlfix-identity'
    pre = audit.inventory(ROOT / 'build/tomokv-PRE')
    post = audit.inventory(ROOT / 'build/tomokv')
    rows = audit.compare(post, {'headline': pre})
    hot = re.compile(r'::cmd_(?:get|set)(?:\(|<)|::cmd_xshard_only|'
                     r'::xshard_(?:prepare|execute|complete|store_string|queue_commit|flush_commits)')
    commands = [row for row in rows if hot.search(row['name'])]
    assert commands and any('::xshard_execute(' in r['name'] for r in commands)
    changed = [row for row in rows if not row['equal']]
    with gzip.open(OUT / 'all-bodies.json.gz', 'wt') as stream:
        json.dump(rows, stream)
    save(OUT / 'changed-bodies.json', changed)
    save(OUT / 'identity.json', dict(pre=pre['sha256'], post=post['sha256'],
         normalizer='tests/reorder_noop.py via docs/wave4/identity.py (unmodified)',
         compared=len(rows), changed=len(changed), command_bodies=commands,
         changed_commands=[row for row in commands if not row['equal']],
         changed_hot=[row for row in changed if row['hot']]))
    print('Linked bodies:', len(rows), 'changed:', len(changed),
          'GET/SET/MGET/MSET changed:', sum(not r['equal'] for r in commands))


def archive(log):
    text = log.read_text()
    assert 'GATE(PARTIAL):' in text, 'gate did not finish'
    run = Path(re.search(r'artifacts: (.+)', text)[1])
    dest = OUT / 'gate-receipts'
    dest.mkdir(exist_ok=True)
    included, omitted = [], []
    target = dest / (log.stem + '.tar.gz')
    with tarfile.open(target, 'w:gz') as tar:
        for path in sorted(run.rglob('*')):
            if not path.is_file() or path.is_symlink():
                continue
            name = str(path.relative_to(run))
            if path.suffix not in ('.txt', '.log', '.json', '.tsv', '.sh', '.py', '') or path.stat().st_size > 20_000_000:
                omitted.append(name)
                continue
            with path.open('rb') as stream:
                prefix = stream.read(512)
            if b'\0' in prefix or prefix.startswith(b'\x7fELF'):
                omitted.append(name)
                continue
            tar.add(path, arcname=name, recursive=False)
            included.append(name)
    jobs = []
    for job in sorted((run / 'jobs').iterdir()):
        done = job / 'done'
        assert done.exists(), job
        jobs.append(dict(job=job.name, done=done.read_text().strip()))
    save(dest / (log.stem + '.json'), dict(run=str(run), jobs=jobs, included=included,
         omitted=omitted, archive_sha256=sha(target),
         summary=[s for s in text.splitlines() if s.startswith('GATE(PARTIAL):')]))
    print(log.stem, len(jobs), 'jobs archived')


def labels():
    sys.path.insert(0, str(ROOT / 'tests'))
    import gate_ledger_fixture as fixture
    gate = (ROOT / 'tests/gate.sh').read_text()
    declared = fixture.source_labels(gate)
    frozen = json.loads((ROOT / fixture.FIXTURE).read_text())['labels']
    expected = dict(re.findall(r'^EXPECT_(QUICK|FULL)=(\d+)', gate, re.M))
    save(OUT / 'label-fixture.json', dict(source=len(declared), fixture=len(frozen), expected=expected,
         missing=list((Counter(declared) - Counter(frozen)).elements()),
         extra=list((Counter(frozen) - Counter(declared)).elements()),
         counts_match=Counter(declared) == Counter(frozen)))
    print('Label inventory:', len(declared), 'source;', len(frozen), 'fixture;', expected)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    commands = parser.add_subparsers(dest='command', required=True)
    control = commands.add_parser('pad')
    for name in ('source', 'destination', 'receipt'):
        control.add_argument(name, type=Path)
    commands.add_parser('identity')
    commands.add_parser('labels')
    archived = commands.add_parser('archive')
    archived.add_argument('logs', nargs='+', type=Path)
    args = parser.parse_args()
    if args.command == 'pad': pad(args.source, args.destination, args.receipt)
    elif args.command == 'identity': identity()
    elif args.command == 'labels': labels()
    else:
        for log in args.logs: archive(log)
