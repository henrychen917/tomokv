#!/usr/bin/env python3
"""wave2 compile-only budget trials (adapted from docs/wave1b/tools/trial.py; never runs a server).

  trial.py size <obj>...                       IPA starting unit ("Starting with size") for PRE, the
                                               integrated source and every lane tip
  trial.py try <obj> '<params>' ['<params>'...] compile the integrated source of <obj> with its
                                               --param set replaced; classify every body
                                               (attribute.py) and print one JSON line per value
Environment: JOBS (parallel compiles, default 8), SHOW (non-hot C/D lines to print).
All compiles run under taskset -c 80-95.
"""
import concurrent.futures as cf, hashlib, json, os, re, shlex, subprocess, sys, tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import attribute as A

WT = A.WT
SCRATCH = WT / 'build/wave2/trials'
INTENDED = re.compile(r'ExLoopT<.*>::(?:drain_tasks|run\()')
LOGS = {'pre': (WT / 'build/wave2/pre-src', WT / 'build/wave2/pre-build.log'),
        'post': (WT, WT / 'build/wave2/prov-build.log')}
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


def classify(obj, path):
    tmp = Path(tempfile.mkdtemp(dir=SCRATCH))
    (tmp / obj).parent.mkdir(parents=True, exist_ok=True)
    os.symlink(path, tmp / obj)
    r = A.run(obj, tmp)
    os.unlink(tmp / obj)
    s = dict(changed=len(r['rows']), hot_changed=0, A=0, B=0, C=0, D=0,
             hot_lines=[], other_lines=[])
    for x in r['rows']:
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
    s['Chot'] = sum(1 for x in r['rows'] if x['hot'] and x['cls'] == 'C')
    s['Dhot'] = sum(1 for x in r['rows'] if x['hot'] and x['cls'] == 'D')
    # perfex's intended hot changes are its executor bodies (drain storage, beat-sampled clocks).
    # Every other selected hot body must stay byte/target-identical to 991d48f65.
    s['bad_hot'] = sum(1 for x in r['rows'] if x['hot'] and not INTENDED.search(x['name']))
    s['intended_off'] = sum(1 for x in r['rows'] if x['hot'] and INTENDED.search(x['name']) and
                            'perfex' not in x['merged_equals_lane'])
    return s


def main():
    mode = sys.argv[1]
    jobs = int(os.environ.get('JOBS', '8'))
    if mode == 'size':
        objs = sys.argv[2:]
        tags = ['pre', 'post'] + [l for l in A.LANES if LOGS[l][1].exists()]
        res = {}
        with cf.ThreadPoolExecutor(jobs) as pool:
            futs = {pool.submit(compile_obj, t, o, None, True): (t, o) for o in objs for t in tags}
            for f in cf.as_completed(futs):
                t, o = futs[f]
                res.setdefault(o, {})[t] = f.result()[1]
        for o in objs:
            res[o]['delta'] = res[o]['post'] - res[o]['pre']
            print(json.dumps({o: res[o]}), flush=True)
    elif mode == 'try':
        obj, params = sys.argv[2], sys.argv[3:]
        with cf.ThreadPoolExecutor(jobs) as pool:
            done = pool.map(lambda p: compile_obj('post', obj, p, True), params)
            for p, (path, size) in zip(params, done):
                s = classify(obj, path)
                print(json.dumps(dict(object=obj, params=p, unit=size, changed=s['changed'],
                                      hot_changed=s['hot_changed'], A=s['A'], B=s['B'], C=s['C'],
                                      D=s['D'], Chot=s['Chot'], Dhot=s['Dhot'],
                                      bad_hot=s['bad_hot'], intended_off=s['intended_off'],
                                      path=str(path))), flush=True)
                for line in s['hot_lines']:
                    print('    HOT ' + line, flush=True)
                for line in [l for l in s['other_lines'] if l[0] in 'CD'][:int(os.environ.get('SHOW', '8'))]:
                    print('    ' + line, flush=True)


if __name__ == '__main__':
    main()
