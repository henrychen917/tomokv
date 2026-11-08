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
import subprocess
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
        if not re.fullmatch(r'_ZN(?:4tomo|8tomo_db0)18ctlfix_correctnessEv', symbol['name']):
            continue
        body = original.body(symbol)
        prefix = 4 if body.startswith(bytes.fromhex('f3 0f 1e fa')) else 0
        assert body[prefix:] == bytes.fromhex('b8 01 00 00 00 c3'), symbol
        section = original.sections[symbol['sec']]
        offset = section[4] + symbol['value'] - section[3] + prefix + 1
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


def object_identity():
    hot = re.compile(r'::cmd_(?:get|set)(?:\(|<)|::cmd_xshard_only|'
                     r'::xshard_(?:prepare|execute|complete|store_string|queue_commit|flush_commits)')
    rows = []
    for prefix in ('src', 'db0/src'):
        for unit in ('t_string', 'xshard'):
            relative = Path(prefix) / 'cmd' / (unit + '.o')
            old = Elf(ROOT / 'build/ctlfix-pre/build' / relative)
            new = Elf(ROOT / 'build' / relative)
            before, after = old.functions(), new.functions()
            symbols = sorted(before)
            names = subprocess.check_output(['c++filt'], input='\n'.join(symbols) + '\n', text=True).splitlines()
            for symbol, name in zip(symbols, names):
                if hot.search(name):
                    rows.append(dict(object=str(relative), name=name, symbol=symbol,
                        equal=symbol in after and old.canonical(before[symbol]) == new.canonical(after[symbol]),
                        pre_size=before[symbol]['size'], post_size=after.get(symbol, {}).get('size')))
    assert rows and any('::xshard_execute(' in r['name'] for r in rows)
    save(OUT / 'command-object-identity.json', dict(
        normalizer='tools/lbstall_artifacts.py Elf.canonical (unmodified)',
        bodies=rows, changed=[r for r in rows if not r['equal']]))
    print('Command object bodies:', len(rows), 'changed:', sum(not r['equal'] for r in rows))


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


def archive_differ(log):
    text = log.read_text()
    summary = [line for line in text.splitlines() if line.startswith('DIFFER GATE:')]
    assert len(summary) == 1, 'differential matrix did not finish'
    directory = log.with_suffix('')
    destination = OUT / 'differ-receipts'
    destination.mkdir(exist_ok=True)
    target = destination / (log.stem + '.tar.gz')
    included, omitted = [], []
    with tarfile.open(target, 'w:gz') as tar:
        for path in sorted(directory.rglob('*')):
            if not path.is_file() or path.is_symlink():
                continue
            name = str(path.relative_to(directory))
            # Retain all textual receipts, including generated ACL/config files;
            # generated persistence images and other binary data are disposable.
            if path.stat().st_size > 20_000_000:
                omitted.append(name)
                continue
            try:
                path.read_bytes().decode('utf-8')
            except UnicodeDecodeError:
                omitted.append(name)
                continue
            tar.add(path, arcname=name, recursive=False)
            included.append(name)
    meta = dict(directory=str(directory), summary=summary[0], included=included,
                omitted=omitted, archive_sha256=sha(target))
    for name in ('seeds.json', 'command-coverage.json'):
        path = directory / name
        if path.exists():
            meta[name.removesuffix('.json')] = json.loads(path.read_text())
    save(destination / (log.stem + '.json'), meta)
    print(log.stem, len(included), 'text receipts archived;', len(omitted), 'binary/large files omitted')


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


def freshness():
    gate = (ROOT / 'tests/gate.sh').read_text()
    body = gate.split('job_production_units(){', 1)[1].split('\njob_multidb(){', 1)[0]
    build = body.split('make -k ', 1)[1].split('>"$TMPDIR/build.log"', 1)[0]
    targets = ['all'] + re.findall(r'\bbuild/[\w-]+', build) + ['mdbqsbr-live-arms']
    assert len(set(targets)) == len(targets) and len(targets) > 40
    rows = []
    for target in targets:
        result = subprocess.run(['make', '-q', target], cwd=ROOT, capture_output=True, text=True)
        rows.append(dict(target=target, returncode=result.returncode, stdout=result.stdout, stderr=result.stderr))
    save(OUT / 'make-freshness.json', dict(targets=rows, all_fresh=all(r['returncode'] == 0 for r in rows)))
    print('make -q:', sum(r['returncode'] == 0 for r in rows), '/', len(rows), 'fresh')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    commands = parser.add_subparsers(dest='command', required=True)
    control = commands.add_parser('pad')
    for name in ('source', 'destination', 'receipt'):
        control.add_argument(name, type=Path)
    commands.add_parser('identity')
    commands.add_parser('object-identity')
    commands.add_parser('labels')
    commands.add_parser('freshness')
    archived = commands.add_parser('archive')
    archived.add_argument('logs', nargs='+', type=Path)
    differ = commands.add_parser('archive-differ')
    differ.add_argument('logs', nargs='+', type=Path)
    args = parser.parse_args()
    if args.command == 'pad': pad(args.source, args.destination, args.receipt)
    elif args.command == 'identity': identity()
    elif args.command == 'object-identity': object_identity()
    elif args.command == 'labels': labels()
    elif args.command == 'freshness': freshness()
    elif args.command == 'archive-differ':
        for log in args.logs: archive_differ(log)
    else:
        for log in args.logs: archive(log)
