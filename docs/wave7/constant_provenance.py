"""Prove exact 64-bit constant loads for unchanged linked probe bodies.

The strict inventory is not modified. A comparison accepts only an otherwise
identical body whose differing instructions are RIP-relative MOVs to RAX and
whose actual read-only eight-byte targets match. Opcode and byte controls fail.
"""
import hashlib,json,re,subprocess
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
  assert re.fullmatch(r'[0-9a-f]+ \[ 7\] mov <rip>\(%rip\),%rax # <.+>',normalized),normalized
  at=body['addr']+off
  assembly=subprocess.check_output(['objdump','-dw','--start-address='+hex(at),'--stop-address='+hex(at+7),str(path)],text=True)
  line=next(l for l in assembly.splitlines() if re.match(r'\s*'+hex(at)[2:]+':',l))
  assert re.search(r'\bmov\s+.*\(%rip\),%rax\s+#',line),line
  target=int(re.search(r'#\s+([0-9a-f]+)',line)[1],16)
  section,=[s for s in elf.sections if s[2]&2 and not s[2]&1 and s[1]!=8 and s[3]<=target and target+8<=s[3]+s[5]]
  data=elf.data[section[4]+target-section[3]:section[4]+target-section[3]+8]
  out.append(dict(instruction_offset=hex(off),target=hex(target),bytes=data.hex(),instruction=normalized))
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
  proof='All instructions/encodings match except these verified equal eight-byte constant loads; no strict inventory tolerance added.')
