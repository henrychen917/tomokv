#!/usr/bin/env python3
"""Known instruction counts, REP collapse, and mandatory fixture-exit control."""
import json,subprocess,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'tools'))
from rlfix4_native import trace
work=ROOT/'build/rlfix4/trace-control';work.mkdir(exist_ok=True)
(work/'test.cc').write_text(r'''
#include <cstdlib>
extern "C" char trace_bytes[8];
char trace_bytes[8];
namespace tomo {void counted();}
asm(".text\n.globl _ZN4tomo7countedEv\n.type _ZN4tomo7countedEv,@function\n"
"_ZN4tomo7countedEv:\n mov $3,%ecx\n lea trace_bytes(%rip),%rdi\n xor %eax,%eax\n rep stosb\n ret\n"
".size _ZN4tomo7countedEv,.-_ZN4tomo7countedEv\n");
__attribute__((noinline)) void scope_begin(){asm volatile("":::"memory");}
__attribute__((noinline)) void scope_end(){asm volatile("":::"memory");}
int main(int argc,char**argv){scope_begin();tomo::counted();scope_end();return argc>1&&argv[1][0]=='f';}
''')
subprocess.run(['g++','-O2','-g',str(work/'test.cc'),'-o',str(work/'probe')],check=True)
line=next(l.split() for l in subprocess.check_output(['nm','-S',str(work/'probe')],text=True).splitlines() if l.endswith(' _ZN4tomo7countedEv'))
lo,size=map(lambda x:int(x,16),line[:2]);ranges=[[lo,lo+size,line[3],'tomo::counted()']]
r=trace(work/'probe',ranges,('control','normal','pass','1s',1,1,-1,'local'),work/'pass.json')
assert r['total']==5 and r['raw_total']==7,r
try:trace(work/'probe',ranges,('control','normal','fail','1s',1,1,-1,'local'),work/'fail.json')
except RuntimeError as e:assert 'exact fixture result' in str(e)
else:raise AssertionError('failed fixture falsely accepted')
assert not (work/'fail.json').exists()
(ROOT/'docs/rlfix4/tracer-selftest.json').write_text(json.dumps(dict(pass_total=r['total'],pass_raw=r['raw_total'],failed_fixture_rejected=True),indent=2)+'\n')
print('PASS exact five-instruction REP scope; negative fixture refused')
