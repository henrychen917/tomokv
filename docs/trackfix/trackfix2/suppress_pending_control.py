"""Disposable negative control: suppress pending-reader frames, keep all other code."""
import hashlib, importlib.util, json, os, re, subprocess, sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[3]
sys.path[:0]=[str(ROOT/'tools'),str(ROOT/'docs/trackfix')]
from lbstall_artifacts import Elf
from run_proof import environment, ORACLE
spec=importlib.util.spec_from_file_location('support',ROOT/'docs/wave4/run_supplemental.py')
support=importlib.util.module_from_spec(spec);spec.loader.exec_module(support)
support.ROOT=ROOT;support.OUT=ROOT/'build/trackfix/suppress-pending-boots'
source=ROOT/'build/trackfix/gate-scheduled-POST-final/tomokv'
out=ROOT/'build/trackfix/suppress-pending'
out.mkdir(parents=True,exist_ok=True)
dest=ROOT/'docs/trackfix/trackfix2/suppress-pending'
dest.mkdir(parents=True,exist_ok=True)
elf=Elf(source);data=bytearray(source.read_bytes());patches=[]
for sym in elf.symbols:
    name=subprocess.check_output(['c++filt',sym['name']],text=True).strip() if 'tracking_retire_read' in sym['name'] else ''
    if not name or 'clone' in name:continue
    start=sym['value'];end=start+sym['size']
    dis=subprocess.check_output(['objdump','-d','-C','--start-address='+hex(start),'--stop-address='+hex(end),str(source)],text=True)
    lines=[l for l in dis.splitlines() if 'call' in l and '::tracking_deliver_frame(' in l]
    assert len(lines)==1,(name,lines)
    address=int(lines[0].split(':')[0],16)
    section,=[s for s in elf.sections if s[1]!=8 and s[2]&2 and s[3]<=address< s[3]+s[5]]
    offset=section[4]+address-section[3]
    original=bytes(data[offset:offset+5]);assert original[0]==0xe8
    data[offset:offset+5]=b'\x90'*5
    patches.append(dict(name=name,address=hex(address),offset=offset,original=original.hex(),replacement='90'*5))
assert len(patches)==2
binary=out/'tomokv';binary.write_bytes(data);binary.chmod(0o755)
schedule=out/'schedule';schedule.mkdir(exist_ok=True)
assert not any(schedule.iterdir())
shape=['--shards','16','--thread-mode','1s','--read-local','0','--net-io','epoll','--atomic','0','--client-lb','0','--key-lb','0','--flip-auto','0','--enable-debug-command','yes','--save','']
os.environ['TOMO_TRACKFIX_SCHEDULE_DIR']=str(schedule)
argv=['taskset','-c','105-111','python3','tests/trackfix.py','127.0.0.1','22810','--oracle','127.0.0.1','22811','--mode','1s','--engine','epoll','--atomic','0','--read-local','0','--case','ordered','--schedule-dir',str(schedule)]
with support.owned('oracle',ORACLE,'104',22811,[]):
    with support.owned('target',binary,'96-103',22810,shape):
        with (dest/'test.log').open('w') as log:rc=subprocess.run(argv,cwd=ROOT,env=environment(),stdout=log,stderr=subprocess.STDOUT).returncode
result=dict(source=str(source),source_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),control_sha256=hashlib.sha256(data).hexdigest(),patches=patches,argv=argv,returncode=rc)
(dest/'result.json').write_text(json.dumps(result,indent=2)+'\n')
print(result,flush=True)
assert rc!=0,'suppressing required pending-reader frames must fail'
