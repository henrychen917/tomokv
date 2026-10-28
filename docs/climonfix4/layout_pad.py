#!/usr/bin/env python3
"""PAD-A: headline behaviour, inert candidate cold struct layout, candidate text extent.
No server, load generator, or performance measurement. The control does not
reproduce individual POST function addresses or candidate data-section layout.
"""
import hashlib,io,json,os,shlex,subprocess,sys,tarfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'tools'))
from lbstall_artifacts import Elf
OUT=ROOT/'build/climonfix4/pad-a';SRC=OUT/'source';OBJ=OUT/'objects'
DOC=ROOT/'docs/climonfix4/pad-a.json'
PRE=ROOT/'build/climonfix4/tomokv-PRE';POST=ROOT/'build/tomokv'
os.sched_setaffinity(0,set(range(16,32)))
def sha(p): return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def text(p):
 e=Elf(p);s=e.sections[e.names.index('.text')];return dict(address=s[3],size=s[5])
def main():
 if '--relink' in sys.argv:
  prior=json.loads(DOC.read_text());relink(prior['changes'],prior['command']);return
 OUT.mkdir(parents=True,exist_ok=True);SRC.mkdir(exist_ok=True)
 changes=[]
 archive=subprocess.check_output(['git','archive','393d6ceb1','src','third_party','Makefile','tools/assert_map.py'],cwd=ROOT)
 with tarfile.open(fileobj=io.BytesIO(archive)) as t:t.extractall(SRC,filter='data')
 def replace(file,old,new):
  p=SRC/file;s=p.read_text();assert s.count(old)==1,(file,old)
  p.write_text(s.replace(old,new));changes.append(dict(file=file,before=old,after=new))
 replace('src/cmd/t_server.cc', '    bool no_touch = false;',
         '    bool no_touch = false;\n    bool pause_blocked = false;\n'
         '    const CommandMetadata* last_command = nullptr;\n    uint64_t last_command_id = UINT64_MAX;')
 replace('src/cmd/notify.inc', '    std::shared_ptr<NotifyExpiryCompletion> expiry_completion;',
         '    std::shared_ptr<NotifyExpiryCompletion> expiry_completion;\n    std::vector<std::string> monitor_lines;')
 replace('src/cmd/climon.inc', '    struct ClimonConn {',
         '    struct ClimonConn {\n'
         '        struct MonitorPending { uint64_t id, excluded; bool script; std::string line; };')
 replace('src/cmd/climon.inc', '        uint64_t tracking_generation = 0;',
         '        uint64_t tracking_generation = 0;\n'
         '        uint64_t monitor_script_id = UINT64_MAX;\n'
         '        std::vector<MonitorPending> monitor_pending;')
 cmd=['make','-j16','BUILD_ROOT='+str(OBJ),'all']
 with (OUT/'build.log').open('w') as f:subprocess.run(cmd,cwd=SRC,stdout=f,stderr=subprocess.STDOUT,check=True)
 relink(changes,cmd)

def relink(changes,cmd):
 recipe=subprocess.check_output(['make','BUILD_ROOT='+str(OBJ),'-n','-W',str(OBJ/'src/main.o'),'all'],cwd=SRC,text=True)
 link=shlex.split(next(s for s in recipe.splitlines() if s.startswith('g++ ') and ' -Wl,--wrap=main ' in s))
 output=OUT/'tomokv';link[link.index('-o')+1]=str(output)
 assembly=OUT/'padding.S';obj=OUT/'padding.o';link.insert(link.index('-o'),str(obj))
 desired,before=text(POST),text(OBJ/'tomokv')
 link+=['-Wl,--section-start=.text='+hex(desired['address'])]
 padding=desired['size']-before['size'];assert padding>=5
 for _ in range(5):
  assembly.write_text('.text\n.balign 1\n.globl climonfix4_pad_a\n.type climonfix4_pad_a,@function\nclimonfix4_pad_a:\nendbr64\nret\n'+
    f'.fill {padding-5},1,0x90\n.size climonfix4_pad_a,.-climonfix4_pad_a\n'+
    '.section .note.GNU-stack,"",@progbits\n.section .note.gnu.property,"a",@note\n.balign 8\n'+
    '.long 4,16,5\n.asciz "GNU"\n.long 0xc0000002,4,3,0\n')
  subprocess.run(['g++','-c',str(assembly),'-o',str(obj)],check=True)
  with (OUT/'link.log').open('w') as f:subprocess.run(link,cwd=SRC,stdout=f,stderr=subprocess.STDOUT,check=True)
  actual=text(output)
  if actual==desired:break
  assert actual['address']==desired['address'];padding+=desired['size']-actual['size']
 else:raise AssertionError((actual,desired))
 result=dict(kind='A: behaviour twin',behavior='393d6ceb1 with inert candidate layout fields',
   matched='ClientMeta, NotifyBatch and ClimonConn candidate member layout; POST .text origin and total size',
   limitation='Individual function offsets and data sections retain PRE placement; text extent is matched, not every function address.',
   changes=changes,command=cmd,link=link,padding_bytes=padding,pre_layout_text=before,post_text=desired,pad_text=actual,
   inputs=[dict(path=x,sha256=sha(x)) for x in link if x.endswith('.o')],
   arms={a:dict(path=str(p),sha256=sha(p)) for a,p in [('PRE',PRE),('POST',POST),('PAD-A',output)]})
 DOC.write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result['arms'],indent=2),flush=True)
if __name__=='__main__':main()
