#!/usr/bin/env python3
"""PAD-A: headline behaviour, inert candidate struct layout, candidate text extent.
No server, load generator, or performance measurement. The control does not
reproduce individual POST function addresses or candidate data-section layout.
"""
import hashlib,io,json,os,shlex,subprocess,sys,tarfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'tools'))
from lbstall_artifacts import Elf
OUT=ROOT/'build/wave9/pad-a';SRC=OUT/'source';OBJ=OUT/'objects'
DOC=ROOT/'docs/wave9/pad-a.json'
PRE=ROOT/'build/wave9/pre-source/build/tomokv';POST=ROOT/'build/tomokv'
os.sched_setaffinity(0,set(range(64,96)))
def sha(p): return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def text(p):
 e=Elf(p);s=e.sections[e.names.index('.text')];return dict(address=s[3],size=s[5])
def main():
 OUT.mkdir(parents=True,exist_ok=True);SRC.mkdir(exist_ok=True)
 changes=[]
 archive=subprocess.check_output(['git','archive','a214652ec','src','third_party','Makefile','tools/assert_map.py'],cwd=ROOT)
 with tarfile.open(fileobj=io.BytesIO(archive)) as t:t.extractall(SRC,filter='data')
 def replace(file,old,new):
  p=SRC/file;s=p.read_text();assert s.count(old)==1,(file,old)
  p.write_text(s.replace(old,new));changes.append(dict(file=file,before=old,after=new))
 replace('src/store/typeval.h','    uint32_t physical_entries = 0;\n};\n\nstruct StreamNodeIndex',
         '    uint32_t physical_entries = 0;\n    uint32_t pad_deleted_entries;\n    uint64_t pad_wire_bytes;\n};\n\nstruct StreamNodeIndex')
 replace('src/cmd/blocking.inc','    std::atomic<bool> counted{false};',
         '    std::atomic<bool> counted{false};\n    BlockingState* pad_count_previous;\n    BlockingState* pad_count_next;\n    bool pad_count_linked;')
 replace('src/cmd/multi.inc','    std::atomic<bool> finished{false};',
         '    std::atomic<bool> finished{false};\n    uint64_t pad_slow_ns;\n    uint64_t pad_slow_sleep_started;\n    int64_t pad_slow_threshold;\n    bool pad_io_effect_done;')
 replace('src/cmd/multi.inc','    int64_t now_cut_ms = 0;',
         '    int64_t now_cut_ms = 0;\n    uint64_t pad_now_cut_mono_ms;')
 replace('src/core/server.h','    DebugSleepCoordinator<kMaxThreads, Ring::kWaitTimeoutMs> debug_sleep_;',
         '    DebugSleepCoordinator<kMaxThreads, Ring::kWaitTimeoutMs> debug_sleep_;\n'
         '    uint64_t pad_script_waits, pad_escalations, pad_commits, pad_waiter_peak;\n'
         '    uint32_t pad_apply_defer;\n    bool pad_force;\n'
         '    uint64_t pad_stage_watch, pad_stage_watch_tasks;')
 cmd=['make','-j32','BUILD_ROOT='+str(OBJ),'all']
 with (OUT/'build.log').open('w') as f:subprocess.run(cmd,cwd=SRC,stdout=f,stderr=subprocess.STDOUT,check=True)
 recipe=subprocess.check_output(['make','BUILD_ROOT='+str(OBJ),'-n','-W',str(OBJ/'src/main.o'),'all'],cwd=SRC,text=True)
 link=shlex.split(next(s for s in recipe.splitlines() if s.startswith('g++ ') and ' -Wl,--wrap=main ' in s))
 output=OUT/'tomokv';link[link.index('-o')+1]=str(output)
 assembly=OUT/'padding.S';obj=OUT/'padding.o';link.insert(link.index('-o'),str(obj))
 desired,before=text(POST),text(OBJ/'tomokv')
 link+=['-Wl,--section-start=.text='+hex(desired['address'])]
 padding=desired['size']-before['size'];assert padding>=5
 for _ in range(5):
  assembly.write_text('.text\n.balign 1\n.globl wave9_pad_a\n.type wave9_pad_a,@function\nwave9_pad_a:\nendbr64\nret\n'+
    f'.fill {padding-5},1,0x90\n.size wave9_pad_a,.-wave9_pad_a\n'+
    '.section .note.GNU-stack,"",@progbits\n.section .note.gnu.property,"a",@note\n.balign 8\n'+
    '.long 4,16,5\n.asciz "GNU"\n.long 0xc0000002,4,3,0\n')
  subprocess.run(['g++','-c',str(assembly),'-o',str(obj)],check=True)
  with (OUT/'link.log').open('w') as f:subprocess.run(link,cwd=SRC,stdout=f,stderr=subprocess.STDOUT,check=True)
  actual=text(output)
  if actual==desired:break
  assert actual['address']==desired['address'];padding+=desired['size']-actual['size']
 else:raise AssertionError((actual,desired))
 result=dict(kind='A: behaviour twin',behavior='a214652ec with inert candidate layout fields',
   matched='StreamNode, BlockingState, MultiCommand, MultiExecState and Server sizes/old-member offsets; POST .text origin and total size',
   limitation='Individual function offsets and data sections retain headline placement. New FIFO members occupy already-existing MultiRetryLane tail padding; new ScatterState flags occupy existing bit padding.',
   changes=changes,command=cmd,link=link,padding_bytes=padding,pre_layout_text=before,post_text=desired,pad_text=actual,
   inputs=[dict(path=x,sha256=sha(x)) for x in link if x.endswith('.o')],
   arms={a:dict(path=str(p),sha256=sha(p)) for a,p in [('PRE',PRE),('POST',POST),('PAD-A',output)]})
 DOC.write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result['arms'],indent=2),flush=True)
if __name__=='__main__':main()
