#!/usr/bin/env python3
"""wave3 R7 round (mainline decision 1): compile-only budget trials for the reorder.o units after the
R7 envelope regeneration (7fa5cb0e0). Never runs a server.

Reference = the cx-wave3 build before the regeneration (build/wave3/r7base, = build/tomokv
07cda1d9...). Every body of the trial object is compared with the reference object in
tools/ccfix_audit.py's canonical form. The regeneration edits exactly one generated function,
IoLoop::r7_ReadLocalDemotionPlan::prepare (both namespaces); a body is "edited" when it is that
function or carries its new code inline (a call/relocation to the RL4.4 helpers
Rob<64>::refine_current_write_hash / Op::mark_read_local_precise_write that the reference body
lacks). Everything else must stay byte- and target-identical to the reference; hot = the same
selector as attribute.py.

  trial_r7.py try <obj> '<params>' ['<params>'...]   one JSON line per parameter set
Environment: JOBS (parallel compiles, default 8), POSTLOG (compile lines, default
build/wave3/final-build.log). All compiles run under taskset -c 80-95.
"""
import concurrent.futures as cf, json, os, re, subprocess, sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
os.environ.setdefault('POSTLOG', str(Path('/home/user/Projects/cx-wave3/build/wave3/final-build.log')))
import trial as T
import attribute as A

REF = A.WT / 'build/wave3/r7base'
EDITED = re.compile(r'IoLoop::r7_ReadLocalDemotionPlan::prepare')
RL44 = re.compile(r'refine_current_write_hash|mark_read_local_precise_write')


def bodies(path):
    elf = A.audit.Elf(Path(path))
    funcs = elf.functions()
    return elf, funcs


def compare(obj, path):
    re_elf, re_funcs = bodies(REF / obj)
    tr_elf, tr_funcs = bodies(path)
    names = sorted(set(re_funcs) | set(tr_funcs))
    labels = subprocess.check_output(['c++filt'], input='\n'.join(names) + '\n', text=True).splitlines()
    rows = []
    for sym, name in zip(names, labels):
        a = re_elf.canonical(re_funcs[sym]) if sym in re_funcs else None
        b = tr_elf.canonical(tr_funcs[sym]) if sym in tr_funcs else None
        if a == b:
            continue
        targets_new = {repr(t[2]) for t in b[1]} if b else set()
        targets_old = {repr(t[2]) for t in a[1]} if a else set()
        carries = any(RL44.search(t) for t in targets_new - targets_old)
        edited = bool(EDITED.search(name)) or carries
        rows.append(dict(name=name, hot=A.is_hot(name), edited=edited,
                         kind='added' if a is None else 'removed' if b is None else
                         'reloc-only' if a[0] == b[0] else 'code',
                         ref_size=re_funcs[sym]['size'] if sym in re_funcs else 0,
                         size=tr_funcs[sym]['size'] if sym in tr_funcs else 0))
    return rows


def main():
    mode, obj, params = sys.argv[1], sys.argv[2], list(dict.fromkeys(sys.argv[3:]))
    assert mode == 'try'
    jobs = int(os.environ.get('JOBS', '8'))
    T.SCRATCH = A.WT / 'build/wave3/trials-r7'
    with cf.ThreadPoolExecutor(jobs) as pool:
        done = pool.map(lambda p: T.compile_obj('post', obj, p, True), params)
        for p, (path, size) in zip(params, done):
            rows = compare(obj, path)
            other = [r for r in rows if not r['edited']]
            print(json.dumps(dict(object=obj, params=p, unit=size, changed=len(rows),
                                  edited=sum(r['edited'] for r in rows),
                                  hot_unedited=sum(r['hot'] for r in other),
                                  unedited=len(other), path=str(path))), flush=True)
            for r in rows:
                tag = 'EDITED' if r['edited'] else ('HOT   ' if r['hot'] else 'other ')
                print(f"    {tag} {r['kind']} {r['ref_size']}->{r['size']} {r['name'][:120]}", flush=True)


if __name__ == '__main__':
    main()
