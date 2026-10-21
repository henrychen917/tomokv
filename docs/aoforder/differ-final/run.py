from pathlib import Path
import hashlib,json,os,subprocess,time
root=Path('build/aoforder/differ-final').resolve();root.mkdir(exist_ok=False)
binary=Path('build/tomokv').resolve()
for name in ('seeds.txt','suites.txt'):(root/name).write_bytes((Path('build/aoforder/differ')/name).read_bytes())
(root/'tmp').mkdir()
env=dict(os.environ,REDIS74_ROOT='/home/user/Projects/redis74',GATE_LOAD_CORES='105-107',GATE_DIFFER_ORACLE_CORES='104',GATE_DIFFER_PROOF_SUITES=str(root/'suites.txt'),GATE_DIFFER_PROOF_SEEDS=str(root/'seeds.txt'),GATE_DIFFER_HISTORY=str(root/'history'),TMPDIR=str(root/'tmp'))
(root/'binary.json').write_text(json.dumps(dict(binary=str(binary),sha256=hashlib.sha256(binary.read_bytes()).hexdigest()),indent=2)+'\n')
rows=[]
for geometry in ('split','armed-fused'):
    command=['taskset','-c','96-111','tests/differ_gate.sh',str(binary),'25720','25721','96-103','6:2']
    settings=env|dict(GATE_DIFFER_GEOMETRY=geometry,GATE_DIFFER_OUT=str(root/geometry))
    start=time.monotonic()
    with (root/(geometry+'.log')).open('w') as log:
        result=subprocess.run(command,env=settings,stdout=log,stderr=subprocess.STDOUT)
    rows.append(dict(geometry=geometry,command=command,environment={k:v for k,v in settings.items() if k.startswith('GATE_') or k in ('REDIS74_ROOT','TMPDIR')},rc=result.returncode,seconds=time.monotonic()-start))
    (root/'summary.json').write_text(json.dumps(rows,indent=2)+'\n')
    print(rows[-1],flush=True)
raise SystemExit(any(r['rc'] for r in rows))
