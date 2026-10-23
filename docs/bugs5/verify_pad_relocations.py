"""Explain all six strict PAD residuals by checking the actual relocated targets.

The strict identity report is retained unchanged. This separate proof checks four
out-of-line rlfence jumps and three relative jump tables in two other functions.
"""
import hashlib,json,struct,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'tools'))
from lbstall_artifacts import Elf
pre=Elf(ROOT/'build/tomokv-PRE');pad=Elf(ROOT/'build/tomokv-PAD-A')
report=json.loads((ROOT/'docs/bugs5/pad-identity.json').read_text())
rows=json.loads((ROOT/'docs/bugs5/pad-differences.json').read_text())
assert {r['name'] for r in rows}=={r['name'] for r in report['pad_a']['changed']}
assert len(rows)==6
gap=json.loads((ROOT/'docs/bugs5/pad.json').read_text())['padding_bytes']
def section(e,name):
 i=e.names.index(name);return e.sections[i][3],e.section_data(i)
def read(e,address,size):
 for i,s in enumerate(e.sections):
  if s[1]!=8 and s[3]<=address and address+size<=s[3]+s[5]:
   return e.section_data(i)[address-s[3]:address-s[3]+size]
 raise AssertionError(hex(address))
a,text0=section(pre,'.text');b,text1=section(pad,'.text');assert a==b
p0,tr0=section(pre,'.rlfence');p1,tr1=section(pad,'.rlfence')
assert p1-p0==gap and len(text1)-len(text0)==gap
assert text1[len(text0):]==bytes([0x90])*gap
assert len(tr0)==len(tr1)==112
assert section(pre,'.note.gnu.property')[1]==section(pad,'.note.gnu.property')[1]
def functions(e):
 return sorted((s['name'],s['value'],s['size']) for s in e.symbols
               if s['info']&15==2 and s['sec']==e.names.index('.text'))
assert functions(pre)==functions(pad)
trampolines=[];tables=[]
for row in rows:
 assert len(row['pre'])==len(row['post'])==1
 aa=row['pre'][0];bb=row['post'][0];base=aa['addr']
 assert base==bb['addr'] and aa['size']==bb['size'] and aa['encodings']==bb['encodings']
 left=list(aa['ins']);right=list(bb['ins'])
 if 'drain_local_reads_bounded_impl' in row['name']:
  offsets=[0x39]
  r0=read(pre,base+0x39,5);r1=read(pad,base+0x39,5)
  assert r0[0]==r1[0]==0xe9
  d0=base+0x3e+struct.unpack_from('<i',r0,1)[0]
  d1=base+0x3e+struct.unpack_from('<i',r1,1)[0]
  off=d0-p0;assert off==d1-p1 and off in (0,28,56,84)
  s0=tr0[off:off+28];s1=tr1[off:off+28]
  assert s0[:24]==s1[:24] and s0[23]==0xe9
  back0=d0+28+struct.unpack_from('<i',s0,24)[0]
  back1=d1+28+struct.unpack_from('<i',s1,24)[0]
  assert back0==back1==base+0x3e
  trampolines.append(dict(name=row['name'],entry=hex(base),trampoline_offset=off,return_address=hex(back0)))
 else:
  specs=[(0x2c2,6),(0x317,6)] if 'scan_home' in row['name'] else [(0x16,18)]
  offsets=[off for off,count in specs]
  for off,count in specs:
   r0=read(pre,base+off,7);r1=read(pad,base+off,7)
   assert r0[:3]==r1[:3] and r0[:2]==b'\x48\x8d'
   d0=base+off+7+struct.unpack_from('<i',r0,3)[0]
   d1=base+off+7+struct.unpack_from('<i',r1,3)[0]
   targets0=[d0+x for x in struct.unpack('<'+'i'*count,read(pre,d0,4*count))]
   targets1=[d1+x for x in struct.unpack('<'+'i'*count,read(pad,d1,4*count))]
   assert targets0==targets1
   assert all(base<=x<base+aa['size'] for x in targets0)
   tables.append(dict(name=row['name'],instruction_offset=hex(off),entries=count,
                      pre_table=hex(d0),pad_table=hex(d1),targets=[hex(x) for x in targets0]))
 for offset in offsets:
  indices=[i for i,line in enumerate(left) if int(line.split()[0],16)==offset]
  assert len(indices)==1
  i=indices[0];assert int(right[i].split()[0],16)==offset
  left[i]=right[i]=f'{offset:04x} separately checked resolved target'
 assert left==right
out=dict(status='PASS',strict_identity='8635/8641; six residuals retained',
 pre_sha256=hashlib.sha256(pre.data).hexdigest(),pad_sha256=hashlib.sha256(pad.data).hexdigest(),
 padding_bytes=gap,all_pre_text_function_addresses_and_sizes_equal=True,
 gnu_properties_equal=True,trampolines=trampolines,jump_tables=tables,
 scope='All six strict normalized-body differences explained; total text size matches POST, individual POST function layout is not reproduced.')
(ROOT/'docs/bugs5/pad-relocations.json').write_text(json.dumps(out,indent=2)+'\n')
print(json.dumps(out,indent=2))
