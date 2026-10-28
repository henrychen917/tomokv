#!/usr/bin/env python3
"""exec1s-d frozen builds and bounded instruction scopes; no performance work."""
import argparse, concurrent.futures, hashlib, json, os, shlex, shutil, subprocess, tarfile
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'build/exec1s-d'
DOCS = ROOT / 'docs/exec1s-d'
CPUS = '64-95'

def sha(p):
    with Path(p).open('rb') as f: return hashlib.file_digest(f, 'sha256').hexdigest()

def save(p, v):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(v, indent=2) + '\n')

def run(cmd, log, cwd=ROOT, env=None):
    log.parent.mkdir(parents=True, exist_ok=True)
    with log.open('w') as f:
        subprocess.run(cmd, cwd=cwd, env=env, stdout=f, stderr=subprocess.STDOUT, check=True)

def record(arm, source, commit):
    binary = OUT / arm
    shutil.copy2(source / 'build/tomokv', binary)
    path = DOCS / 'arms.json'
    rows = json.loads(path.read_text()) if path.exists() else []
    rows = [r for r in rows if r['arm'] != arm]
    rows.append(dict(arm=arm, source_commit=commit, binary=str(binary),
                     sha256=sha(binary), bytes=binary.stat().st_size))
    save(path, rows)
    (DOCS / 'SHA256SUMS').write_text(''.join(f"{r['sha256']}  {r['binary']}\n" for r in rows))
    print('BUILT', arm, sha(binary), flush=True)

def snapshot(ref, arm):
    source = OUT / (arm + '-source')
    commit = subprocess.check_output(['git', 'rev-parse', ref], cwd=ROOT, text=True).strip()
    if not source.exists():
        source.mkdir(parents=True)
        with subprocess.Popen(['git', 'archive', commit, 'src', 'third_party', 'Makefile',
                               'tools', 'tests'], cwd=ROOT, stdout=subprocess.PIPE) as p:
            with tarfile.open(fileobj=p.stdout, mode='r|') as t: t.extractall(source, filter='data')
            assert p.wait() == 0
        (source / 'SOURCE-COMMIT').write_text(commit + '\n')
    else:
        assert (source / 'SOURCE-COMMIT').read_text().strip() == commit
    return source, commit

def scope_module():
    os.environ['EXEC1S_CPUS'] = CPUS
    import exec1s_scope as s
    s.OUT = OUT / 'counts'
    s.BUILD = OUT / 'scopes'
    s.OUT.mkdir(exist_ok=True)
    s.BUILD.mkdir(exist_ok=True)
    return s

def probes(arm, source, kinds):
    s = scope_module()
    for kind in kinds.split(','):
        fixture = {'ORD': 'txnorder_command_scope.cc', 'EXEC': 'exec1sd_scope.cc',
                   'IDLE': 'exec1s_idle_scope.cc', 'RL': 'wave9_scope.cc'}[kind]
        label = kind + '-' + arm
        s.ARMS[label] = (source, source / 'build')
        s.FIXTURE = ROOT / 'tests' / fixture
        for ns in ('normal', 'db0'): s.build(label, ns)

def allocations(arm, source):
    from exec1s_pad import recipe
    objects = source / 'build'
    link = recipe(source, objects)
    for ns in ('normal', 'db0'):
        flags = ['g++', '-std=c++20', '-O2', '-g', '-march=native', '-pthread',
                 '-DTOMO_JEMALLOC', '-I' + str(source)]
        if ns == 'db0': flags += ['-DTOMO_SINGLE_DATABASE=1', '-Dtomo=tomo_db0']
        selected = []
        for x in link:
            if not x.endswith('.o') or x.endswith(('/src/main.o', '/src/core/version.o')): continue
            db0 = '/db0/' in x
            if ns == 'normal' and db0: continue
            if x.endswith('/src/cmd/xshard.o') and db0 == (ns == 'db0'): continue
            selected.append(x)
        binary = OUT / (arm + '-allocation-' + ns)
        cmd = flags + [str(ROOT/'tests/exec1s_alloc_scope.cc'), *selected, '-o', str(binary),
                       '-ljemalloc', '-luring', '-pthread', '-lssl', '-lcrypto', '-lm']
        run(cmd, OUT/'evidence'/(arm+'-allocation-'+ns+'-build.log'))
        rows = []
        for mode, shards in [('2s', '16'), ('1s', '64')]:
            output = subprocess.check_output(['taskset', '-c', '64-71', str(binary), mode, shards], text=True)
            rows.append(json.loads(next(l for l in output.splitlines() if l.startswith('{'))))
        save(DOCS/(arm+'-allocation-'+ns+'.json'), dict(arm=arm, namespace=ns, command=cmd,
             sha256=sha(binary), production_sha256=sha(objects/'tomokv'), results=rows))
        binary.unlink()
        print('ALLOC', arm, ns, rows, flush=True)

def traces(arm, kinds):
    s = scope_module()
    import crlffix_fast_scope as fast
    fast.scope = s
    fast.OUT = s.OUT
    # Reuse the established finite ptrace counter and its exact-data exit check.
    step = ROOT/'build/crlffix/step'
    step.parent.mkdir(exist_ok=True, parents=True)
    run(['gcc', '-O2', '-g', 'tools/crlffix_step.c', '-o', str(step)], OUT/'evidence/step-build.log')
    for kind in kinds.split(','):
        label = kind+'-'+arm
        cases = []
        if kind == 'ORD':
            cases = [(label, ns, cmd, mode, n, atomic, -1)
                     for ns in ('normal','db0') for cmd in ('GET','SET','INCR','MGET','MSET')
                     for mode in ('1s','2s') for n in (1,32)
                     for atomic in ((0,1) if cmd=='MSET' else (1,))]
        elif kind == 'RL':
            cases = [(label, ns, 'READLOCAL-GET', '1s', n, 1, -1)
                     for ns in ('normal','db0') for n in (1,32)]
        elif kind == 'EXEC':
            cases = [(label, ns, cmd, mode, n, atomic, -1)
                     for ns in ('normal','db0') for cmd in ('EXEC-same','EXEC-cross')
                     for mode in ('1s','2s') for n in (1,2,4) for atomic in (0,1)]
            cases += [(label, ns, 'EXEC-depth-'+str(depth), mode, 2, atomic, -1)
                      for ns in ('normal','db0') for depth in (0,16,64)
                      for mode in ('1s','2s') for atomic in (0,1)]
        elif kind == 'IDLE':
            cases = [(label, ns, 'IDLE', '1s', 1, 1, -1) for ns in ('normal','db0')]
        if kind == 'IDLE':
            with concurrent.futures.ThreadPoolExecutor(2) as pool: rows = list(pool.map(s.trace,cases))
        else:
            prepared = {(label,ns):fast.prepare(label,ns) for ns in ('normal','db0')}
            with concurrent.futures.ThreadPoolExecutor(8) as pool:
                rows = list(pool.map(lambda case:fast.run(case,prepared),cases))
        save(DOCS/(kind+'-'+arm+'-counts.json'),rows)

def main():
    assert os.sched_getaffinity(0) <= set(range(64, 96)), 'taskset -c 64-95 required'
    OUT.mkdir(parents=True, exist_ok=True)
    DOCS.mkdir(parents=True, exist_ok=True)
    p = argparse.ArgumentParser()
    p.add_argument('action', choices=['build', 'probes', 'allocations', 'trace'])
    p.add_argument('arm')
    p.add_argument('--ref')
    p.add_argument('--kinds', default='ORD,EXEC,RL')
    a = p.parse_args()
    source, commit = snapshot(a.ref, a.arm) if a.ref else (ROOT,
        subprocess.check_output(['git', 'rev-parse', 'HEAD'], text=True).strip())
    if a.action == 'build':
        run(['make', '-j32', 'all'], OUT / 'evidence' / (a.arm + '-build.log'), cwd=source)
        record(a.arm, source, commit)
    elif a.action == 'probes':
        probes(a.arm, source, a.kinds)
    elif a.action == 'allocations':
        allocations(a.arm, source)
    else:
        traces(a.arm, a.kinds)

if __name__ == '__main__': main()
