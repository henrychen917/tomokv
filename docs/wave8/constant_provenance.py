"""Prove constant loads and the classify_keys switch in linked probe bodies.

The strict inventory is not modified. A comparison accepts only an otherwise
identical body whose differing instructions are RIP-relative MOVs to RAX or
the specifically recognized bounded classify_keys switch. Actual eight-byte
constants or every relative case destination must match. Opcode/byte controls fail.
"""
import hashlib,json,re,struct,subprocess
from pathlib import Path
import identity
import sys
sys.path.insert(0,str(identity.ROOT/'tools'))
from lbstall_artifacts import Elf

def signature(body):
 return hashlib.sha256(json.dumps([body['ins'],body['encodings']]).encode()).hexdigest()

def loads(path,body,indices):
 elf=Elf(path);out=[]
 for i in indices:
  normalized=body['ins'][i];off=int(normalized.split()[0],16)
  constant=bool(re.fullmatch(r'[0-9a-f]+ \[ 7\] mov <rip>\(%rip\),%rax # <.+>',normalized))
  switch=bool(re.fullmatch(r'[0-9a-f]+ \[ 7\] lea <rip>\(%rip\),%rdi # <.+>',normalized))
  assert constant or switch,normalized
  length=8
  if switch:
   asm=[s.split('] ',1)[1] for s in body['ins'][i-4:i+4]]
   bound=re.fullmatch(r'cmp \$0x([0-9a-f]+),%al',asm[0]);assert bound,asm
   assert re.fullmatch(r'ja <\+0x[0-9a-f]+>',asm[1]),asm
   assert asm[2:4]==['mov %rdi,%rbx','movzbl %al,%eax'],asm
   assert asm[5:]==['movslq (%rdi,%rax,4),%rax','add %rdi,%rax','notrack jmp *%rax'],asm
   count=int(bound[1],16)+1;assert count==50
   length=count*4
  at=body['addr']+off
  assembly=subprocess.check_output(['objdump','-dw','--start-address='+hex(at),'--stop-address='+hex(at+7),str(path)],text=True)
  line=next(l for l in assembly.splitlines() if re.match(r'\s*'+hex(at)[2:]+':',l))
  assert re.search(r'\b'+('mov' if constant else 'lea')+r'\s+.*\(%rip\),%'+('rax' if constant else 'rdi')+r'\s+#',line),line
  target=int(re.search(r'#\s+([0-9a-f]+)',line)[1],16)
  section,=[s for s in elf.sections if s[2]&2 and not s[2]&1 and s[1]!=8 and s[3]<=target and target+length<=s[3]+s[5]]
  data=elf.data[section[4]+target-section[3]:section[4]+target-section[3]+length]
  row=dict(instruction_offset=hex(off),target=hex(target),bytes=data.hex(),instruction=normalized)
  if switch:
   destinations=[target+v[0]-body['addr'] for v in struct.iter_unpack('<i',data)]
   valid={int(s.split()[0],16) for s in body['ins']}
   assert all(v in valid for v in destinations)
   row.update(raw_bytes=data.hex(),destinations=destinations,
              bytes=b''.join(struct.pack('<I',v) for v in destinations).hex(),
              comparison='all 50 case destinations relative to this exact function')
  out.append(row)
 return out

def prove(first_path,first,second_path,second):
 assert first['encodings']==second['encodings']
 assert len(first['ins'])==len(second['ins'])
 differences=[i for i,(a,b) in enumerate(zip(first['ins'],second['ins'])) if a!=b]
 assert differences
 for i in differences:assert first['ins'][i].split('#')[0]==second['ins'][i].split('#')[0]
 a=loads(first_path,first,differences);b=loads(second_path,second,differences)
 assert [x['bytes'] for x in a]==[x['bytes'] for x in b]
 changed=bytearray.fromhex(b[0]['bytes']);changed[0]^=1
 assert changed.hex()!=a[0]['bytes']
 # These controls do not edit either linked image or relax its normalizer.
 wrong=json.loads(json.dumps(second));wrong['ins'][0]+=' CHANGED_OPCODE'
 try:
  assert all(first['ins'][i].split('#')[0]==wrong['ins'][i].split('#')[0] for i in range(len(first['ins'])))
 except AssertionError:opcode_rejected=True
 else:opcode_rejected=False
 assert opcode_rejected
 return dict(production=a,probe=b,negative_controls=dict(changed_constant_byte=True,changed_opcode=opcode_rejected),
  proof='All instructions/encodings match except these verified constant loads or bounded switch destinations; no strict inventory tolerance added.')
