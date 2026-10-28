"""Resolve three literal/assembly labels missed by the gate's strict normalizer.

Instruction bytes, registers, branches and structure offsets remain unchanged.
Only actual read-only bytes, bounded local switch destinations, or the address of
the unchanged ROB assembly island replace objdump's nearest-symbol labels.
"""
import json,re,struct,threading
from pathlib import Path
from lbstall_artifacts import Elf
STATE=threading.local()
def install(audit):
 original_label=audit.LiteralPools
 original_asm=audit.normalize_asm
 class Pools(original_label):
  def __init__(self,path,nm):
   super().__init__(path,nm)
   elf=Elf(path);regions=[]
   for name,s in zip(elf.names,elf.sections):
    if name=='.rlfence':regions.append((s[3],s[3]+s[5],'.rlfence'))
   slots=Path(__file__).resolve().parents[1]/'docs/rlfix4/layout/slots.json'
   if slots.exists():
    wanted={f'__rlfix4_slot_{i}':s for i,s in enumerate(json.loads(slots.read_text())) if s['section']=='.rlfence'}
    for s in elf.symbols:
     if s['name'] in wanted:
      regions.append((s['value'],s['value']+wanted[s['name']]['size'],s['name']))
   STATE.regions=regions
  def label(self,asm):
   result=super().label(asm)
   if result:return result
   # mov r64 from an anonymous, read-only 8-byte scalar pool.
   m=re.fullmatch(r'mov\s+-?0x[0-9a-f]+\(%rip\),%(r(?:ax|bx|cx|dx|si|di|bp|sp|[89]|1[0-5]))\s+#\s+([0-9a-f]+) <[^<>]+>',asm)
   if not m:return None
   target=int(m[2],16)
   if any(a<target+8 and target<b for a,b in self.named):return None
   for start,data in self.sections:
    offset=target-start
    if 0<=offset<=len(data)-8:return 'literal-load-'+data[offset:offset+8].hex()
   return None
  def jump_label(self,index,body,instructions,addr,size):
   result=super().jump_label(index,body,instructions,addr,size)
   if result:return result
   # GCC reloads the same byte after a memory-bound switch check in KvObj.
   if index<4 or index+3>=len(body):return None
   ins=[instructions[x][1] for x in body]
   lea=re.fullmatch(r'lea\s+-?0x[0-9a-f]+\(%rip\),%(\w+)\s+#\s+([0-9a-f]+) <[^<>]+>',ins[index])
   reload=re.fullmatch(r'movzbl\s+(\([^)]*\)),%eax',ins[index-1])
   if not lea or not reload or not ins[index-2].startswith('ja '):return None
   bound=None
   for j in range(max(0,index-5),index-2):
    m=re.fullmatch(r'cmpb\s+\$0x([0-9a-f]+),'+re.escape(reload[1]),ins[j])
    if m:bound=int(m[1],16)+1
   if bound is None or not 1<=bound<=4096:return None
   base=lea[1]
   if ' '.join(ins[index+1].split())!=f'movslq (%{base},%rax,4),%rax':return None
   if ' '.join(ins[index+2].split())!=f'add %{base},%rax':return None
   if ' '.join(ins[index+3].split()) not in ('jmp *%rax','notrack jmp *%rax'):return None
   target=int(lea[2],16)
   if any(a<target+bound*4 and target<b for a,b in self.named):return None
   for start,data in self.sections:
    offset=target-start
    if 0<=offset<=len(data)-bound*4:
     destinations=[target+x[0] for x in struct.iter_unpack('<i',data[offset:offset+bound*4])]
     if any(not addr<=x<addr+size or x not in instructions for x in destinations):return None
     return 'local-switch-'+','.join(hex(x-addr) for x in destinations)
   return None
 def asm(text,addr,size,demangle,address_name=None,literal_name=None):
  names=address_name
  for match in audit.REFERENCE.finditer(text):
   target=int(match[1],16)
   for start,end,label in getattr(STATE,'regions',[]):
    if start<=target<end:
     if names is address_name:names=dict(address_name or {})
     names[target]=label+'+'+hex(target-start)
  return original_asm(text,addr,size,demangle,names,literal_name)
 audit.LiteralPools=Pools;audit.normalize_asm=asm
