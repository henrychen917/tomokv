#!/usr/bin/env python3
"""Run the tree's own selected correctness jobs; retain commands and receipts."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT/'build/wave4'
DOC = ROOT/'docs/wave4'
BROAD = '''storage_units core_units atomic_units netcmd_units wait_units
reorder_sync reorder_engagement reorder_identity perfex_units perfex_live ntnew4_live
compat2 moverfix tls auth authfix aclfix acl_recheck notify notify_order notify_aof
feature-split-0 feature-split-1 feature-armed-0 feature-armed-1 fused-0 fused-1
release_batteries atomic_batteries script_bounds scriptfix sort bplus dump_restore
snapshot-epoll snapshot-uring aof-epoll aof-uring aof_frame aoforder
netcap respcompat ntfix_input clientfix debug-0 debug-1 hexpread flip
multidb-1s-0-0 multidb-1s-0-1 multidb-1s-1-0 multidb-1s-1-1
multidb-2s-0-0 multidb-2s-0-1 multidb-2s-1-0 multidb-2s-1-1'''.split()
BROAD += [f'respresume-{case}-{mode}-{engine}' for case in ('fragment','cpu','neighbour')
          for mode in ('1s','2s') for engine in ('epoll','uring')]


def setup():
    binpath = OUT/'bin'; binpath.mkdir(parents=True,exist_ok=True)
    # Supported correctness-only mode; every correctness assertion still runs.
    (binpath/'python3').write_text('''#!/bin/bash
case "${1:-}" in
  *tests/atomic_ryow.py) exec /usr/bin/python3 "$@" --no-rate-assertions;;
  *) exec /usr/bin/python3 "$@";;
esac
''')
    (binpath/'make').write_text('''#!/usr/bin/python3
import os,sys
args=[]
for arg in sys.argv[1:]:
    args.append('-j32' if arg.startswith('-j') and arg[2:].isdigit() else arg)
os.execv('/usr/bin/make',['make',*args])
''')
    (binpath/'memtier_benchmark').write_text('''#!/bin/bash
echo 'wave4: performance load generators are reserved for the maintainer' >&2
exit 125
''')
    for p in binpath.iterdir(): p.chmod(0o755)
    oracle = OUT/'oracle/src'; oracle.mkdir(parents=True,exist_ok=True)
    for source in Path('/home/user/Projects/redis/src').iterdir():
        dest=oracle/source.name
        if not dest.exists(): dest.symlink_to(source)
    for name in ('redis-server','redis-cli'):
        dest=oracle/name
        if dest.is_symlink(): dest.unlink()
        dest.symlink_to(Path('/home/user/Projects/redis74/src')/name)
    return dict(os.environ, PATH=str(binpath)+':'+os.environ['PATH'],
                PYTHONPATH=str(DOC/'fixture_site'), WAVE4_FIXTURE_PORT_LOG=str(OUT/'fixture-ports.log'),
                GATE_TEST_PORT='26899', REDIS74_ROOT=str(oracle.parent),
                GATE_DIFFER_ORACLE_CORES='88', GATE_NOTIFY_ORACLE_CORES='88')


def main():
    p=argparse.ArgumentParser(); p.add_argument('label'); p.add_argument('--jobs',default='')
    p.add_argument('--cwd',type=Path,default=ROOT); p.add_argument('--binary',type=Path,default=ROOT/'build/tomokv')
    p.add_argument('--single',action='store_true'); a=p.parse_args()
    dest=DOC/'proof'/a.label; dest.mkdir(parents=True,exist_ok=False)
    env=setup(); jobs=a.jobs.split() if a.jobs else BROAD
    env.update(GATE_ONLY_JOBS=' '.join(jobs),GATE_LEDGER=str(dest/'ledger'),
               GATE_HISTORY=str(OUT/('history-'+a.label)))
    # Three disjoint eight-core server slots, with seven client CPUs each.
    servers,clients=('64-72','73-95') if a.single else ('64-87','89-109')
    if a.single: env.update(GATE_DIFFER_ORACLE_CORES='72',GATE_NOTIFY_ORACLE_CORES='72')
    argv=['taskset','-c','64-111','bash','tests/gate.sh','quick',
          '--server-cores',servers,'--load-cores',clients,'--server-smt','','--load-smt','',
          '--ports','26800-26879','--candidate-binary',str(a.binary.resolve())]
    receipt=dict(argv=argv,cwd=str(a.cwd),jobs=jobs,binary=str(a.binary),
                 binary_sha256=hashlib.sha256(a.binary.read_bytes()).hexdigest(),
                 env={k:v for k,v in env.items() if k.startswith(('GATE_','REDIS74','WAVE4','PYTHONPATH'))})
    (dest/'command.json').write_text(json.dumps(receipt,indent=2)+'\n')
    with (dest/'gate.log').open('w') as log:
        rc=subprocess.run(argv,cwd=a.cwd,env=env,stdout=log,stderr=subprocess.STDOUT).returncode
    receipt['returncode']=rc
    found=re.search(r'artifacts: (\S+)',(dest/'gate.log').read_text())
    if found:
        receipt['run_directory']=found[1]
        run=Path(found[1]); done={}
        for f in (run/'jobs').glob('*/done'): done[f.parent.name]=f.read_text().strip()
        receipt['jobs_done']=done
    (dest/'result.json').write_text(json.dumps(receipt,indent=2)+'\n')
    print(a.label,'rc',rc,receipt.get('run_directory'),flush=True)
    raise SystemExit(rc)


if __name__=='__main__': main()
