#!/usr/bin/env python3
"""Compile-only, whole-linked-inventory trials; never execute a candidate.

Input is a list of {object, budget?, growth?}. Compilation uses make -j32.
The existing strict gate normalizer is used unchanged for every linked score.
"""
from concurrent.futures import ProcessPoolExecutor
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'docs/wave4'))
import identity

OUT = ROOT / 'build/wave4c/budgets'
DOC = ROOT / 'docs/wave4c/budgets'
START_SHA = '3dfe9e510917cc12e320e6e31ca9f22f8ac498c2e5353ce162ff273b2f01f8e5'
COMMAND_NAMES = {r['name'] for r in json.loads(
    (ROOT / 'docs/wave4/identity/command-paths.json').read_text())['bodies']}
COMMAND_PATH = re.compile(r'::cmd_(?:get|set|mget|mset)(?:\(|<|_)|prepare_captured_local_mget|'
    r'::(?:store_xstring_selected|store_string(?:_notify)?|'
    r'xshard_(?:execute|prepare|retire|store_string(?:_notify)?))\(|::cmd_xshard_only(?:\(|_impl)')


def initial_inventory():
    import gzip
    with gzip.open(identity.OUT / START_SHA / 'inventory.json.gz', 'rt') as stream:
        return json.load(stream)


def command_for(job):
    lines = (ROOT / 'build/wave4/build-rebuilt.log').read_text().splitlines()
    command = next(shlex.split(line) for line in lines
                   if line.startswith('g++ ') and line.endswith(' -o build/' + job['object']))
    # The old log predates the final wave4b budget choice.
    make = (ROOT / 'Makefile').read_text()
    current = re.search(r'\$\(BUILD_ROOT\)/' + re.escape(job['object']) +
                        r':[^\n]*large-unit-insns=(\d+)', make)
    values = {'large-unit-insns': int(current[1])} if current else {}
    for field, option in [('budget', 'large-unit-insns'), ('growth', 'inline-unit-growth'),
                          ('auto', 'max-inline-insns-auto'), ('size', 'max-inline-insns-size'),
                          ('early', 'early-inlining-insns')]:
        if field in job:
            values[option] = job[field]
    for option, value in values.items():
        old = next((i for i, arg in enumerate(command) if arg.startswith(option + '=')), None)
        if old is None:
            command += ['--param', f'{option}={value}']
        else:
            command[old] = f'{option}={value}'
    return command


def compile_trials(jobs, label):
    OUT.mkdir(parents=True, exist_ok=True)
    DOC.mkdir(parents=True, exist_ok=True)
    source = hashlib.sha256()
    for path in sorted((ROOT / 'src').rglob('*')):
        if path.is_file():
            source.update(str(path.relative_to(ROOT)).encode() + path.read_bytes())
    source_sha = source.hexdigest()
    records, rules = [], []
    for job in jobs:
        command = command_for(job)
        key = hashlib.sha256((source_sha + shlex.join(command)).encode()).hexdigest()[:16]
        base = OUT / (job['object'].replace('/', '_') + '.' + key)
        command[command.index('-o') + 1] = str(base) + '.o'
        command += ['-fdump-ipa-inline', '-dumpbase', str(base)]
        records.append(dict(job, command=command, output=str(base) + '.o',
                            source_sha256=source_sha, base=str(base)))
        rules.append(f'{base}.o:\n\t{shlex.join(command)} >{base}.log 2>&1\n')
    makefile = OUT / (label + '.mk')
    makefile.write_text('.PHONY: all\nall: ' + ' '.join(r['output'] for r in records) + '\n' + '\n'.join(rules))
    subprocess.run(['make', '-j32', '-f', str(makefile)], cwd=ROOT, check=True)
    for record in records:
        base = Path(record['base'])
        receipt = Path(str(base) + '.compile.json')
        if receipt.exists():
            record.update(json.loads(receipt.read_text()))
            continue
        dump, = OUT.glob(base.name + '*.inline')
        with dump.open() as stream:
            record['unit'] = next(int(m[1]) for line in stream
                                  if (m := re.search(r'Starting with size (\d+)', line)))
        # Preserve useful inliner decisions without committing enormous dumps.
        import gzip
        with dump.open('rb') as src, gzip.open(str(base) + '.inline.gz', 'wb') as dest:
            import shutil
            shutil.copyfileobj(src, dest)
        dump.unlink()
        stripped = Path(str(base) + '.stripped.o')
        subprocess.run(['objcopy', '--strip-debug', record['output'], str(stripped)], check=True)
        record['object_code_sha256'] = hashlib.sha256(stripped.read_bytes()).hexdigest()
        stripped.unlink()
        receipt.write_text(json.dumps(record, indent=2) + '\n')
    (DOC / (label + '.compiled.json')).write_text(json.dumps(records, indent=2) + '\n')
    return records


def score(record):
    base = Path(record['base'])
    receipt = Path(str(base) + '.score.json')
    if receipt.exists():
        import gzip
        cached = json.loads(receipt.read_text())
        command = cached['link_command']
        with gzip.open(identity.OUT / cached['linked_sha256'] / 'inventory.json.gz', 'rt') as stream:
            post = json.load(stream)
    else:
        command = shlex.split(next(line for line in reversed(
            (ROOT / 'build/wave4/build-rebuilt.log').read_text().splitlines())
            if line.startswith('g++ ') and ' -Wl,--wrap=main ' in line))
        command[command.index('build/' + record['object'])] = record['output']
        binary = Path(str(base) + '.tomokv')
        command[command.index('-o') + 1] = str(binary)
        command += ['-Wl,--strip-debug']
        subprocess.run(command, cwd=ROOT, check=True, stdout=subprocess.DEVNULL)
        post = identity.inventory(binary)
        binary.unlink()
    refs = {arm: identity.inventory(path) for arm, path in identity.REFS.items()}
    before = initial_inventory()
    old_rows = {r['name']: r for r in identity.compare(before, refs)}
    rows = identity.compare(post, refs)
    changed = [r for r in rows if identity.signature(post['groups'].get(r['name'], [])) !=
               identity.signature(before['groups'].get(r['name'], []))]
    # A removed lane-added helper is absent from both headline and trial, hence
    # absent from compare()'s union. It still belongs to the protected PRE set.
    present = {r['name'] for r in rows}
    for name in before['groups'].keys() - present:
        changed.append(dict(old_rows[name], post_sizes=[], equal=True,
                            matches=[arm for arm, ref in refs.items() if name not in ref['groups']]))
    protected = [r['name'] for r in changed if old_rows.get(r['name'], {}).get('matches')]
    hot = lambda r: r['hot'] or bool(COMMAND_PATH.search(r['name']))
    result = dict(record, link_command=command, linked_sha256=post['sha256'],
        score=dict(hot_union_residual=sum(hot(r) and not r['matches'] for r in rows),
                   historical_hot_residual=sum(r['hot'] and not r['matches'] for r in rows),
                   command_residual=sum(bool(COMMAND_PATH.search(r['name'])) and not r['matches'] for r in rows),
                   residual=sum(not r['matches'] for r in rows),
                   changed_previously_matching=len(protected),
                   changed_previously_matching_hot=sum(hot(r) and r['name'] in protected for r in changed)),
        changed=changed, changed_previously_matching=protected,
        command_residuals=[r['name'] for r in rows if COMMAND_PATH.search(r['name']) and not r['matches']])
    receipt.write_text(json.dumps(result, indent=2) + '\n')
    print(record['object'], record.get('budget', 'default'), record.get('growth', 'default'), result['score'], flush=True)
    return result


def main():
    assert set(os.sched_getaffinity(0)) <= set(range(64, 112))
    jobs = json.loads(Path(sys.argv[1]).read_text())
    label = sys.argv[2]
    records = compile_trials(jobs, label)
    if '--compile-only' in sys.argv:
        return
    unique = {}
    for r in records:
        unique.setdefault((r['object'], r['object_code_sha256']), r)
    with ProcessPoolExecutor(max_workers=6) as pool:
        scores = list(pool.map(score, unique.values()))
    by = {(r['object'], r['object_code_sha256']): r for r in scores}
    rows = [dict(by[(r['object'], r['object_code_sha256'])], **r) for r in records]
    (DOC / (label + '.json')).write_text(json.dumps(rows, indent=2) + '\n')


if __name__ == '__main__':
    main()
