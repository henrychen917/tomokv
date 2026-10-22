"""Path audit over the unchanged gate normalizer's disassembly; not a rate claim."""
import hashlib,json,re
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2];DOC=ROOT/'docs/fliplisten/identity/io'
rows=json.loads((DOC/'summary.json').read_text())
loop_rows=[];accept_rows=[]
def lines(r,arm):
 return (DOC/(r['artifact']+'.'+arm)).read_text().splitlines()[1:]
for r in rows:
 if not r['name'].startswith('void ') or not any(x in r['name'] for x in ('::run_loop<','::r7_run_loop<')):continue
 if r['equal']:loop_rows.append(dict(name=r['name'],identical=True));continue
 pre,post=lines(r,'pre'),lines(r,'post')
 assert len(pre)==len(post),r
 changes=[(i,a,b) for i,(a,b) in enumerate(zip(pre,post)) if a!=b]
 assert len(changes)==1,changes
 i,a,b=changes[0]
 assert 'call ' in a and '::arm_accept(' in a and a.replace('::arm_accept(','::fliplisten_retry_accept(')==b
 # The existing conditional skip jumps beyond this call. It is reached only
 # when accept_pending_ was already set; no test, load, NOP or opcode was added.
 guards=[]
 for j,line in enumerate(pre[:-1]):
  if 'cmpb $0x0,0x1938(' not in line:continue
  branch=re.search(r'(je|jne) <\+0x([0-9a-f]+)>',pre[j+1]);assert branch
  target=int(branch[2],16)
  if (branch[1]=='je' and j==i-4 and target==int(pre[i+1].split()[0],16) or
      branch[1]=='jne' and target==int(pre[i-2].split()[0],16)):
   guards.append(pre[j:j+2])
 assert len(guards)==1,(r,guards)
 loop_rows.append(dict(name=r['name'],identical=False,sole_difference=a+' -> '+b,
                       existing_pending_branch=guards[0]))
assert len(loop_rows)==64
def path(text,kind,more):
 instructions={}
 for line in text:
  m=re.fullmatch(r'([0-9a-f]+) \[ *\d+\] (.*)',line);assert m,line
  instructions[int(m[1],16)]=m[2]
 offsets=sorted(instructions);next_at=dict(zip(offsets,offsets[1:]))
 at=offsets[0];trace=[];zf=sf=cf=False
 for _ in range(200):
  asm=instructions[at];trace.append(asm);op=asm.split()[0]
  if asm.startswith('cmp ') and '0xab0(' in asm:zf=True;sf=False;cf=False
  elif asm.startswith('cmp $0x1,%al'):zf=True;sf=False;cf=False
  elif asm.startswith('cmp $0x3,%al'):zf=False;sf=True;cf=True # idle is zero
  elif asm.startswith(('cmp $0x6,','cmp $0x9,')):
   value=6 if '$0x6,' in asm else 9;zf=kind==value;sf=kind<value;cf=kind<value
  elif asm.startswith('testb $0x2,'):zf=not more;sf=False;cf=False
  elif asm.startswith('test %eax,%eax'):zf=False;sf=False;cf=False # successful fd
  elif asm.startswith('test %al,%al'):zf=True;sf=False;cf=False # idle phase
  if op=='ret':return trace
  if op.startswith('j'):
   match=re.fullmatch(r'j[a-z]* <\+0x([0-9a-f]+)>',asm)
   if op=='jmp' and not match:
    assert '::arm_accept(' in asm,asm
    return trace
   assert match,asm
   take={'jmp':True,'je':zf,'jne':not zf,'js':sf,'jns':not sf,'ja':not cf and not zf}.get(op)
   assert take is not None,asm
   if take:at=int(match[1],16);continue
  assert 'fliplisten' not in asm,asm
  at=next_at[at]
 raise AssertionError('normal accept path did not terminate')
for r in rows:
 if '::on_accept<' not in r['name'] and '::r7_on_accept<' not in r['name']:continue
 assert not r['equal']
 for kind in (1,6,9):
  for more in (False,True):
   a,b=path(lines(r,'pre'),kind,more),path(lines(r,'post'),kind,more)
   assert len(b)<=len(a),(r['name'],kind,more,len(a),len(b))
   accept_rows.append(dict(name=r['name'],kind=kind,multishot_continues=more,
                           pre_instructions=len(a),post_instructions=len(b)))
result=dict(sha256={name:hashlib.sha256((ROOT/'build'/name).read_bytes()).hexdigest() for name in ('tomokv-PRE','tomokv')},scope='Idle phase; current generation; active IO; successful native accept. Callee admission is audited separately. Includes emitted NOPs. Resource-starvation retry remains on the existing cold branch.',
            loops=loop_rows,normal_accept_paths=accept_rows,
            native_arm_identical=[r['name'] for r in rows if '::arm_accept(' in r['name'] and r['equal']])
assert len(result['native_arm_identical'])==2
(ROOT/'docs/fliplisten/identity/normal-paths.json').write_text(json.dumps(result,indent=2)+'\n')
print(len(loop_rows),'loop variants:',sum(x['identical'] for x in loop_rows),'strict identical, other 32 only existing cold retry call target;',
      len(accept_rows),'successful accept paths have no instruction-count increase')
