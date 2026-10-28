#!/usr/bin/env python3
"""exec1s-d frozen builds and bounded instruction scopes; no performance work."""
import argparse, hashlib, json, os, shutil, subprocess, tarfile
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

def main():
    assert os.sched_getaffinity(0) <= set(range(64, 96)), 'taskset -c 64-95 required'
    OUT.mkdir(parents=True, exist_ok=True)
    DOCS.mkdir(parents=True, exist_ok=True)
    p = argparse.ArgumentParser()
    p.add_argument('action', choices=['build', 'probes'])
    p.add_argument('arm')
    p.add_argument('--ref')
    p.add_argument('--kinds', default='ORD,EXEC,RL')
    a = p.parse_args()
    source, commit = snapshot(a.ref, a.arm) if a.ref else (ROOT,
        subprocess.check_output(['git', 'rev-parse', 'HEAD'], text=True).strip())
    if a.action == 'build':
        run(['make', '-j32', 'all'], OUT / 'evidence' / (a.arm + '-build.log'), cwd=source)
        record(a.arm, source, commit)
    else:
        probes(a.arm, source, a.kinds)

if __name__ == '__main__': main()
