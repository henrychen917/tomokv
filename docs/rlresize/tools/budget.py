#!/usr/bin/env python3
"""rlresize compile-only inlining-budget trials (adapted from docs/wave1b/tools/trial.py).

Never runs a server. PRE = 991d48f65 from `git archive` (build/rlresize/pre-src); POST = this
worktree. Compile lines come from each tree's full `make all` log.

  budget.py size <obj>...                IPA starting unit ("Starting with size"), PRE and POST
  budget.py try <obj> <params>...        compile POST <obj> with the given --param set (replacing
                                         the Makefile's), compare every body with PRE's object
                                         (tools/ccfix_audit.py canonical form) and print a summary
Classes: lane = the bodies this lane changes on purpose; hot = tools/lbstall_artifacts.py HOT
(or ExLoopT run); other = any further changed body. JOBS sets parallel compiles (default 8).
"""
import concurrent.futures as cf
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import subprocess
import sys

WT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(WT / 'tools'))
import ccfix_audit  # noqa: E402  (patches lbstall_artifacts.Elf canonical forms on import)
audit = ccfix_audit.audit

PRE_SRC = WT / 'build/rlresize/pre-src'
SCRATCH = WT / 'build/rlresize/trials'
# POST_ROOT compiles an alternative candidate tree with the same compile lines (default: this tree).
POST_ROOT = Path(os.environ.get('POST_ROOT', WT))
LOGS = {'pre': (PRE_SRC, WT / 'build/rlresize/pre-src-build.log'),
        'post': (POST_ROOT, WT / 'build/rlresize/post1-build.log')}
CPUS = os.environ.get('TRIAL_CPUS', '80-95')
LANE = re.compile(r'FlatStore::(?:atomic_prepare_capacity_read_local|clear|clear_read_local|'
                  r'clear_capacity|prepare_resize_retirement)\(')


def command(tag, obj):
    cwd, log = LOGS[tag]
    for line in log.read_text().splitlines():
        if line.startswith('g++ ') and line.endswith(' -o build/' + obj):
            return cwd, shlex.split(line)
    raise SystemExit(f'no compile line for {obj} in {log}')


def strip_params(argv):
    out, skip = [], False
    for word in argv:
        if skip:
            skip = False
            continue
        if word == '--param':
            skip = True
            continue
        out.append(word)
    return out


_KEYS = {}


def src_key(root):
    # Every compiled input below src/: a cached trial never outlives a source edit.
    if root not in _KEYS:
        digest = hashlib.sha1()
        for path in sorted((root / 'src').rglob('*')):
            if path.is_file() and path.suffix in ('.h', '.inc', '.cc'):
                digest.update(str(path.relative_to(root)).encode() + path.read_bytes())
        _KEYS[root] = digest.hexdigest()[:10]
    return _KEYS[root]


def compile_obj(tag, obj, params=None, dump=False):
    cwd, argv = command(tag, obj)
    if params is not None:
        argv = strip_params(argv)
        i = argv.index('-I.')
        argv = argv[:i] + shlex.split(params) + argv[i:]
    key = hashlib.sha1((tag + obj + ' '.join(argv) + str(dump) + src_key(cwd)).encode()).hexdigest()[:12]
    out = SCRATCH / (tag if cwd == WT or tag == 'pre' else tag + '-' + cwd.name) / \
        (obj.replace('/', '_') + '.' + key + '.o')
    out.parent.mkdir(parents=True, exist_ok=True)
    partial = out.with_suffix('.partial.o')   # renamed only after a complete compile
    argv[argv.index('-o') + 1] = str(partial)
    sizefile = out.with_suffix('.size')
    if dump:
        argv += ['-fdump-ipa-inline', '-dumpbase', str(out.with_suffix(''))]
    if not out.exists() or (dump and not sizefile.exists()):
        subprocess.run(['taskset', '-c', CPUS, *argv], cwd=cwd, check=True)
        partial.rename(out)
        if dump:
            dumpfile = next(out.parent.glob(out.with_suffix('').name + '*.inline'))
            size = None
            with dumpfile.open(errors='replace') as stream:
                for line in stream:
                    match = re.search(r'Starting with size (\d+)', line)
                    if match:
                        size = int(match[1])
                        break
            dumpfile.unlink()
            sizefile.write_text(str(size))
    return out, (int(sizefile.read_text()) if dump else None)


def bodies(path):
    elf = audit.Elf(path)
    functions = elf.functions()
    names = sorted(functions)
    readable = subprocess.check_output(['c++filt'], input='\n'.join(names) + '\n',
                                       text=True).splitlines()
    return elf, functions, dict(zip(names, readable))


def compare(pre_path, post_path):
    a, old, names_a = bodies(pre_path)
    b, new, names_b = bodies(post_path)
    rows = []
    for symbol in sorted(old.keys() | new.keys()):
        x, y = old.get(symbol), new.get(symbol)
        if x and y and a.canonical(x) == b.canonical(y):
            continue
        name = names_a.get(symbol) or names_b.get(symbol)
        kind = ('lane' if LANE.search(name) else
                'hot' if audit.HOT.search(name) or re.search(r'ExLoopT<.*>::run\(', name) else 'other')
        rows.append(dict(kind=kind, pre=x['size'] if x else 0, post=y['size'] if y else 0, name=name))
    return rows


def main():
    mode, obj, *rest = sys.argv[1:]
    jobs = int(os.environ.get('JOBS', '8'))
    if mode == 'size':
        with cf.ThreadPoolExecutor(jobs) as pool:
            futures = {(o, tag): pool.submit(compile_obj, tag, o, None, True)
                       for o in [obj, *rest] for tag in ('pre', 'post')}
            for o in [obj, *rest]:
                pre, post = futures[(o, 'pre')].result()[1], futures[(o, 'post')].result()[1]
                print(json.dumps({o: dict(pre=pre, post=post, delta=post - pre)}), flush=True)
        return
    if mode == 'show':   # show <obj> <params> <demangled-name regex>: PRE vs trial disassembly
        params, pattern = rest
        post_obj = compile_obj('post', obj, params)[0]
        for tag, path in (('PRE', PRE_SRC / 'build' / obj), ('POST', post_obj)):
            _, functions, names = bodies(path)
            for symbol, name in names.items():
                if re.search(pattern, name):
                    text = subprocess.check_output(
                        ['objdump', '-d', '--no-show-raw-insn', '-r',
                         '--disassemble=' + symbol, str(path)], text=True)
                    lines = [re.sub(r'^\s*[0-9a-f]+:\s*', '', l) for l in text.splitlines()
                             if re.match(r'^\s*[0-9a-f]+:', l)]
                    out = SCRATCH / f'show-{tag}.txt'
                    out.write_text('\n'.join(re.sub(r'\b[0-9a-f]{3,}\b', 'ADDR', l) for l in lines) + '\n')
                    print(tag, name[:120], len(lines), 'lines ->', out)
        return
    assert mode == 'try'
    pre_obj = PRE_SRC / 'build' / obj
    with cf.ThreadPoolExecutor(jobs) as pool:
        futures = [(params, pool.submit(compile_obj, 'post', obj, params)) for params in rest]
        for params, future in futures:
            rows = compare(pre_obj, future.result()[0])
            counts = {k: sum(r['kind'] == k for r in rows) for k in ('lane', 'hot', 'other')}
            print(json.dumps(dict(object=obj, params=params, **counts)), flush=True)
            for row in rows:
                if row['kind'] != 'lane':
                    print('   ', row['kind'].upper(), row['pre'], '->', row['post'], row['name'][:160])


if __name__ == '__main__':
    main()
