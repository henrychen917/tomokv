#!/usr/bin/env python3
"""wave3 compile-only budget trials (adapted from docs/wave2/tools/trial.py; never runs a server).

  trial.py size <obj>...                       IPA starting unit ("Starting with size") for PRE
                                               (f821104a9), BASE (991d48f65), the integrated
                                               source and every lane tip
  trial.py try <obj> '<params>' ['<params>'...] compile the integrated source of <obj> with its
                                               --param set replaced; classify every body
                                               (attribute.py) and print one JSON line per value
Environment: JOBS (parallel compiles, default 8), SHOW (non-hot C/D lines to print),
POSTLOG (the integrated build log holding the compile lines, default build/wave3/prov-build.log).
All compiles run under taskset -c 80-95.
"""
import concurrent.futures as cf, hashlib, json, os, re, shlex, subprocess, sys, tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import attribute as A

WT = A.WT
SCRATCH = WT / 'build/wave3/trials'
LOGS = {'pre': (A.REFS / 'pre-src', A.REFS / 'pre-build.log'),
        'base991': (A.REFS / 'base991-src', A.REFS / 'base991-build.log'),
        'post': (WT, Path(os.environ.get('POSTLOG', WT / 'build/wave3/prov-build.log')))}
for lane in A.LANES:
    LOGS[lane] = (A.REFS / f'{lane}-src', A.REFS / f'{lane}-build.log')


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
            skip = False; continue
        if word == '--param':
            skip = True; continue
        out.append(word)
    return out


def src_key(root):
    h = hashlib.sha1()
    for f in sorted((root / 'src').rglob('*')):
        if f.is_file() and f.suffix in ('.h', '.inc', '.cc'):
            h.update(f.read_bytes())
    return h.hexdigest()[:10]


_KEYS = {}


def compile_obj(tag, obj, params=None, dump=False):
    cwd, argv = command(tag, obj)
    if params is not None:
        argv = strip_params(argv)
        i = argv.index('-I.')
        argv = argv[:i] + shlex.split(params) + argv[i:]
    if cwd not in _KEYS:
        _KEYS[cwd] = src_key(cwd)
    key = hashlib.sha1((tag + obj + ' '.join(argv) + _KEYS[cwd] + str(dump)).encode()).hexdigest()[:12]
    out = SCRATCH / tag / (obj.replace('/', '_') + '.' + key + '.o')
    out.parent.mkdir(parents=True, exist_ok=True)
    argv[argv.index('-o') + 1] = str(out)
    sizefile = out.with_suffix('.size')
    if dump:
        argv += ['-fdump-ipa-inline', '-dumpbase', str(out.with_suffix(''))]
    if not out.exists() or (dump and not sizefile.exists()):
        subprocess.run(['taskset', '-c', '80-95', *argv], cwd=cwd, check=True)
        if dump:
            size = None
            dumpfile = next(out.parent.glob(out.with_suffix('').name + '*.inline'))
            with dumpfile.open(errors='replace') as stream:
                for line in stream:
                    m = re.search(r'Starting with size (\d+)', line)
                    if m:
                        size = int(m[1]); break
            dumpfile.unlink()
            sizefile.write_text(str(size))
    size = int(sizefile.read_text()) if dump else None
    return out, size


def summarize(rows):
    s = dict(changed=len(rows), hot_changed=0, A=0, B=0, C=0, D=0, hot_lines=[], other_lines=[])
    for x in rows:
        c = x['cls']
        s[c] += 1
        if x['hot']:
            s['hot_changed'] += 1
        struct = ('T=PRE' if x['targets_equal_pre'] else
                  'T=' + ','.join(x['targets_equal_lane']) if x['targets_equal_lane'] else 'T=new')
        line = (f"{c} {struct} {x['kind']} {x['pre_size']}->{x['post_size']} "
                f"lanes={','.join(x['lanes_changed']) or '-'} eq={','.join(x['merged_equals_lane']) or '-'} "
                f"{x['name'][:110]}")
        (s['hot_lines'] if x['hot'] else s['other_lines']).append(line)
    s['hotA'] = sum(1 for x in rows if x['hot'] and x['cls'] == 'A')
    s['hotB'] = sum(1 for x in rows if x['hot'] and x['cls'] == 'B')
    s['hotCD'] = sum(1 for x in rows if x['hot'] and x['cls'] in 'CD')
    return s


def classify(obj, path):
    tmp = Path(tempfile.mkdtemp(dir=SCRATCH))
    (tmp / obj).parent.mkdir(parents=True, exist_ok=True)
    os.symlink(path, tmp / obj)
    r = A.run(obj, tmp)
    os.unlink(tmp / obj)
    return summarize(r['rows'])


def main():
    mode = sys.argv[1]
    jobs = int(os.environ.get('JOBS', '8'))
    if mode == 'size':
        objs = sys.argv[2:]
        tags = ['pre', 'base991', 'post'] + [l for l in A.LANES if LOGS[l][1].exists()]
        res = {}
        with cf.ThreadPoolExecutor(jobs) as pool:
            futs = {}
            for o in objs:
                for t in tags:
                    try:
                        command(t, o)
                    except SystemExit:
                        continue
                    futs[pool.submit(compile_obj, t, o, None, True)] = (t, o)
            for f in cf.as_completed(futs):
                t, o = futs[f]
                res.setdefault(o, {})[t] = f.result()[1]
        for o in objs:
            res[o]['delta_vs_pre'] = res[o]['post'] - res[o]['pre']
            res[o]['delta_vs_base'] = res[o]['post'] - res[o]['base991']
            print(json.dumps({o: res[o]}), flush=True)
    elif mode == 'try':
        # A repeated value would compile the same output twice concurrently (one thread deletes the
        # IPA dump the other is reading): keep each distinct parameter set once, in order.
        obj, params = sys.argv[2], list(dict.fromkeys(sys.argv[3:]))
        with cf.ThreadPoolExecutor(jobs) as pool:
            done = pool.map(lambda p: compile_obj('post', obj, p, True), params)
            for p, (path, size) in zip(params, done):
                s = classify(obj, path)
                print(json.dumps(dict(object=obj, params=p, unit=size, changed=s['changed'],
                                      hot_changed=s['hot_changed'], A=s['A'], B=s['B'], C=s['C'],
                                      D=s['D'], hotA=s['hotA'], hotB=s['hotB'], hotCD=s['hotCD'],
                                      path=str(path))), flush=True)
                for line in s['hot_lines']:
                    print('    HOT ' + line, flush=True)
                for line in [l for l in s['other_lines'] if l[0] in 'CD'][:int(os.environ.get('SHOW', '8'))]:
                    print('    ' + line, flush=True)


if __name__ == '__main__':
    main()
