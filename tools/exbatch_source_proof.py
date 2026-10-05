#!/usr/bin/env python3
"""Frozen PRE-source closure and static instruction receipts; executes no ELF."""
import argparse
import gzip
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess

from lbstall_artifacts import Elf
from rlfence_artifacts import instructions, tables

ROOT = Path(__file__).resolve().parents[1]
PRE = 'cd02ecbab1502775f1c170e806971d1f7bbc3ee9'
OUT = ROOT/'docs/exbatch'
TOKEN = re.compile(r'//[^\n]*|/\*.*?\*/|"(?:\\.|[^"\\])*"|\w+|[^\s]', re.S)


def tokens(text):
    return [m.group() for m in TOKEN.finditer(text) if not m.group().startswith(('//', '/*'))]


def body(source, signature):
    start = source.index('{', source.index(signature)) + 1
    level = 1
    for token in TOKEN.finditer(source, start):
        if token.group() == '{': level += 1
        if token.group() == '}': level -= 1
        if not level: return source[start:token.start()]
    raise AssertionError('unclosed function')


def save(name, value):
    OUT.mkdir(exist_ok=True)
    (OUT/name).write_text(json.dumps(value, indent=2, sort_keys=True) + '\n')


def same_body(expected, actual, signature):
    assert tokens(expected) == tokens(actual), ('PRE control body differs', signature)


def source():
    rows = []
    controls = []
    for file, signature in (
        ('src/core/shard.h', 'void publish_size()'),
        ('src/core/shard.h', 'bool has_watches() const'),
        ('src/cmd/cmdmeta.cc', 'uint32_t child_count('),
        ('src/cmd/cmdmeta.cc', 'const CommandMetadata* command_metadata_lookup('),
        ('src/cmd/cmdmeta.cc', 'const CommandMetadata* command_metadata_resolve('),
    ):
        before = subprocess.check_output(['git', 'show', f'{PRE}:{file}'], cwd=ROOT, text=True)
        after = (ROOT/file).read_text()
        old = body(before, signature)
        new = body(after, signature).split('legacy:', 1)[1]
        same_body(old, new, signature)
        rows.append(dict(file=file, function=signature, tokens=len(tokens(old)), exact_PRE_tokens=True))
        if signature == 'void publish_size()':
            statement = 'published_size_.store(store_.size(), std::memory_order_relaxed);'
            assert new.count(statement) == 1
            try: same_body(old, new.replace(statement, ''), signature)
            except AssertionError as error:
                controls.append(dict(mutation='remove real PRE size publication store',
                                     rejected=True, reason=str(error)))
            else: raise AssertionError('source verifier accepted missing store')
    old = subprocess.check_output(['git', 'show', f'{PRE}:src/core/ex_loop.h'], cwd=ROOT)
    new = (ROOT/'src/core/ex_loop.h').read_bytes()
    assert old == new, 'EX2 or batch coverage changed'
    header = (ROOT/'src/core/shard.h').read_text()
    assert header.count('has_watches_ = true;') == 1
    assert header.count('has_watches_ = !watchers_.empty() || !watch_reservations_.empty();') == 1
    for name in ('void refresh_has_watches()', 'void arm_watches()'):
        code = body(header, name)
        assert 'TOMO_EXBATCH_TWIN(legacy, 30);' in code and code.rstrip().endswith('legacy:;')
    multi = (ROOT/'src/cmd/multi.inc').read_text()
    assert multi.count('arm_watches();') == 2 and multi.count('refresh_has_watches();') == 3
    metadata = (ROOT/'src/cmd/cmdmeta_generated.inc').read_bytes()
    assert metadata == subprocess.check_output(['git', 'show', f'{PRE}:src/cmd/cmdmeta_generated.inc'], cwd=ROOT)
    save('source-proof.json', dict(reference=PRE, legacy_bodies=rows,
         executor_byte_identical=True, EX2='unchanged', generated_metadata_byte_identical=True,
         cache_mutators={'arm': 2, 'erase_refresh': 3},
         note='The cached bit stays on its physical Shard across migration; no per-owner sidecar.'))
    save('source-negative.json', controls)
    print('PASS exbatch source: five exact PRE bodies, five cache mutation sites, EX2 unchanged')


def static(pre, post):
    result = []
    for label, path in [('PRE', pre), ('POST', post)]:
        elf = Elf(path)
        table = tables(elf, OUT/'static', label)
        selected = [s for s in elf.symbols if s['info'] & 15 == 2 and s['size'] and
                    (re.search(r'7(?:publish|watches)ERK?N4tomo5ShardE$', s['name']) or
                     s['name'] in ('_ZN4tomo5Shard12publish_sizeEv',
                                   '_ZN4tomo24command_metadata_resolveERNS_2OpEj',
                                   '_ZN4tomo23command_metadata_lookupENS_5SliceE'))]
        for symbol in selected:
            dis = subprocess.check_output(['objdump', '-dw', '--disassemble='+symbol['name'], str(path)], text=True)
            code = instructions(dis)
            name = f'{label}-{symbol["name"]}.asm.gz'
            with gzip.GzipFile(str(OUT/'static'/name), 'wb', mtime=0) as out: out.write(dis.encode())
            result.append(dict(arm=label, symbol=symbol['name'], address=symbol['value'], bytes=symbol['size'],
                               static_instructions=len(code), disassembly=name,
                               note='Static function inventory, including retained control blocks; not retired instr/op.'))
        for path in (OUT/'static').glob('*.tsv'):
            with gzip.GzipFile(str(path)+'.gz', 'wb', mtime=0) as out: out.write(path.read_bytes())
            path.unlink()
        save(f'{label.lower()}-unit-elf.json', table)
    assert any('publish' in row['symbol'] for row in result)
    assert any('watches' in row['symbol'] for row in result)
    save('static-functions.json', result)
    print('PASS exbatch static receipts:', len(result), 'functions (no perf, no server execution)')


if __name__ == '__main__':
    assert os.sched_getaffinity(0) <= set(range(112, 128)), 'pin to 112-127'
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--pre-unit', type=Path)
    parser.add_argument('--post-unit', type=Path)
    args = parser.parse_args()
    source()
    if args.pre_unit and args.post_unit: static(args.pre_unit, args.post_unit)
