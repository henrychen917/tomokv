#!/usr/bin/env python3
"""wave1b compile-only budget trials (adapted from cx-wave1 docs/wave1/tools/trial.py; never runs a server).

  trial.py size <obj>...                      initial IPA unit size ("Starting with size"), PRE and merged
  trial.py try <obj> '<params>' ['<params>'...] compile the merged source of <obj> with replaced --param set,
                                              classify every body (attribute.py logic) and print a summary
Environment: JOBS (parallel compiles, default 8).
"""
import concurrent.futures as cf, hashlib, json, os, re, shlex, subprocess, sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import attribute as A

WT = A.WT
PRE_SRC = WT / 'build/wave1b/refs/pre-src'
SCRATCH = WT / 'build/wave1b/trials'
LOGS = {'pre': (PRE_SRC, WT / 'build/wave1b/refs/pre-build.log'),
        'post': (WT, WT / 'build/wave1b/prov-build.log')}


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
    tag_hash = hashlib.sha1((tag + obj + ' '.join(argv) + _KEYS[cwd] + str(dump)).encode()).hexdigest()[:12]
    out = SCRATCH / tag / (obj.replace('/', '_') + '.' + tag_hash + '.o')
    out.parent.mkdir(parents=True, exist_ok=True)
    argv[argv.index('-o') + 1] = str(out)
    size = None
    sizefile = out.with_suffix('.size')
    if dump:
        argv += ['-fdump-ipa-inline', '-dumpbase', str(out.with_suffix(''))]
    if not out.exists() or (dump and not sizefile.exists()):
        subprocess.run(['taskset', '-c', '112-127', *argv], cwd=cwd, check=True)
        if dump:
            d = next(out.parent.glob(out.with_suffix('').name + '*.inline'))
            with d.open(errors='replace') as stream:
                for line in stream:
                    m = re.search(r'Starting with size (\d+)', line)
                    if m:
                        size = int(m[1]); break
            d.unlink()
            sizefile.write_text(str(size))
    if dump:
        size = int(sizefile.read_text())
    return out, size


def classify(obj, path):
    """attribute.run() on one object, with the merged object replaced by the trial object."""
    import tempfile
    tmp = Path(tempfile.mkdtemp(dir=SCRATCH))
    (tmp / obj).parent.mkdir(parents=True, exist_ok=True)
    os.symlink(path, tmp / obj)
    r = A.run(obj, tmp)
    os.unlink(tmp / obj)
    summary = dict(hot_changed=0, A=0, B=0, C=0, D=0, AOF=0, R7=0, CF=0, neB4=0, Chot=[], Dhot=[], Call=[], Dall=[])
    for x in r['rows']:
        lc, eq = x['lanes_changed'], x['merged_equals_lane']
        summary['neB4'] += not x['merged_equals_b4']
        if x.get('climonfix'): c = 'CF'
        elif x.get('r7_mirror_of'): c = 'R7'
        elif not lc and not x['aoffix2_changed']: c = 'C'
        elif eq and set(eq) & set(lc): c = 'A'
        elif len(lc) > 1: c = 'B'
        elif lc: c = 'D'
        else: c = 'AOF'
        summary[c] += 1
        struct = 'T=PRE' if x['targets_equal_pre'] else ('T=' + ','.join(x['targets_equal_lane'])) if x['targets_equal_lane'] else 'T=new'
        line = f"{c} {struct} {x['kind']} {x['pre_size']}->{x['post_size']} lanes={','.join(lc) or '-'} {x['name'][:100]}"
        if x['hot']:
            summary['hot_changed'] += 1
            if c in ('C', 'D'): summary[c + 'hot'].append(line)
        if c in ('C', 'D'): summary[c + 'all'].append(line)
    return summary, r


def main():
    mode = sys.argv[1]
    jobs = int(os.environ.get('JOBS', '8'))
    if mode == 'size':
        objs = sys.argv[2:]
        res = {}
        with cf.ThreadPoolExecutor(jobs) as pool:
            futs = {pool.submit(compile_obj, t, o, None, True): (t, o) for o in objs for t in ('pre', 'post')}
            for f in cf.as_completed(futs):
                t, o = futs[f]
                res.setdefault(o, {})[t] = f.result()[1]
        for o in objs:
            res[o]['delta'] = res[o]['post'] - res[o]['pre']
            print(json.dumps({o: res[o]}), flush=True)
    elif mode == 'path':
        obj = sys.argv[2]
        for p in sys.argv[3:]:
            print(compile_obj('post', obj, p, True)[0])
    elif mode == 'try':
        obj, params = sys.argv[2], sys.argv[3:]
        with cf.ThreadPoolExecutor(jobs) as pool:
            for p, (path, size) in zip(params, pool.map(lambda p: compile_obj('post', obj, p, True), params)):
                s, _ = classify(obj, path)
                print(json.dumps(dict(object=obj, params=p, unit=size, hot_changed=s['hot_changed'],
                                      A=s['A'], B=s['B'], C=s['C'], D=s['D'], AOF=s['AOF'], R7=s['R7'],
                                      CF=s['CF'], neB4=s['neB4'],
                                      Chot=len(s['Chot']), Dhot=len(s['Dhot']))), flush=True)
                for line in s['Chot'] + s['Dhot']:
                    print('    HOT ' + line, flush=True)
                for line in (s['Call'] + s['Dall'])[:int(os.environ.get('SHOW', '6'))]:
                    print('    ' + line, flush=True)


if __name__ == '__main__':
    main()
