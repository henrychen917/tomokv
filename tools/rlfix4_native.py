"""Native counterpart to the GDB named-production census; exact return checks mandatory."""
import bisect,gzip,hashlib,json,re,subprocess
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
def trace(binary,ranges,case,output):
    label='-'.join(map(str,case));work=ROOT/'build/rlfix4/commands'
    rs=sorted(ranges);rf=work/(label+'.ranges');rf.write_text(''.join(f'{r[0]:x} {r[1]:x}\n' for r in rs))
    syms={r.split()[-1]:int(r.split()[0],16) for r in subprocess.check_output(['nm','--defined-only',str(binary)],text=True).splitlines() if len(r.split())>=3}
    dump=subprocess.check_output(['objdump','-d','-j','.plt','-j','.plt.sec','-j','.plt.got',str(binary)],text=True)
    m=re.search(r'([0-9a-f]+) <clock_gettime@plt>:',dump);clock=int(m[1],16) if m else 0
    cmd=[str(ROOT/'build/rlfix4/trace'),str(binary),str(rf),f'{syms["_Z11scope_beginv"]:x}',f'{syms["_Z9scope_endv"]:x}',f'{clock:x}',*map(str,case[2:])]
    run=subprocess.run(cmd,text=True,capture_output=True,timeout=600)
    if run.returncode:raise RuntimeError(label+' '+run.stderr+run.stdout[-1000:])
    record=json.loads(next(l[6:] for l in run.stdout.splitlines() if l.startswith('TRACE=')))
    starts=[r[0] for r in rs];functions={};bodies={};raw_total=0
    for pc,n in record['sites'].items():
        at=int(pc,16);i=bisect.bisect_right(starts,at)-1;assert i>=0 and at<rs[i][1]
        r=rs[i];functions[r[3]]=functions.get(r[3],0)+n
        body=hex(r[0])+' '+r[3];bodies[body]=bodies.get(body,0)+n
    row=dict(binary_sha256=hashlib.file_digest(binary.open('rb'),'sha256').hexdigest(),backend='ptrace-rep-once',total=sum(functions.values()),functions=functions,bodies=bodies,raw_total=sum(record['raw_sites'].values()),clock_calls=record['clock_calls'],excluded_calls=record['excluded_calls'])
    output.write_text(json.dumps(row,indent=2)+'\n')
    with gzip.GzipFile(filename=str(output)+'.sites.gz',mode='wb',mtime=0) as f:f.write(json.dumps(record).encode())
    output.with_suffix('.log').write_text(' '.join(cmd)+'\n'+run.stderr+'\n'.join(l for l in run.stdout.splitlines() if not l.startswith('TRACE='))+'\nCOUNT '+str(row['total'])+'\n')
    print(label,row['total'],'native',flush=True)
    return dict(zip(('arm','namespace','command','mode','batch','atomic','threshold','route'),case),**row)
