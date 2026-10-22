"""Prove the four strict PAD differences are relocated read-local trampolines.

This is a separate byte proof. It does not turn the strict identity failure green.
"""
import hashlib,json,struct,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(ROOT/'tools'),str(ROOT/'docs/wave4d')]
from lbstall_artifacts import Elf
from target_bodies import bodies
pre=Elf(ROOT/'build/wave4c/tomokv-pre');pad=Elf(ROOT/'build/wave4d/tomokv-pad-a')
report=json.loads((ROOT/'docs/wave4d/pad-identity.json').read_text())
names=set(report['pad-a']['changed']);assert len(names)==4
assert all('drain_local_reads_bounded_impl' in n for n in names)
def section(e,name):
 i=e.names.index(name);return e.sections[i][3],e.section_data(i)
a,text0=section(pre,'.text');b,text1=section(pad,'.text');assert a==b
p0,tr0=section(pre,'.rlfence');p1,tr1=section(pad,'.rlfence')
assert p1-p0==32 and len(text1)-len(text0)==32
assert text1[len(text0):]==bytes([0x90])*32
assert len(tr0)==len(tr1)==112
assert section(pre,'.rodata')==section(pad,'.rodata')
assert section(pre,'.note.gnu.property')[1]==section(pad,'.note.gnu.property')[1]
ba=bodies(pre.path,names);bb=bodies(pad.path,names)
m0=bytearray(text0);m1=bytearray(text1[:len(text0)]);rows=[]
for name in sorted(names):
 aa=ba[name][0];zz=bb[name][0]
 assert aa['address']==zz['address'] and aa['encodings']==zz['encodings']
 base=int(aa['address'],16);at=base-a+0x39
 assert text0[at]==text1[at]==0xe9
 dest0=base+0x3e+struct.unpack_from('<i',text0,at+1)[0]
 dest1=base+0x3e+struct.unpack_from('<i',text1,at+1)[0]
 off0=dest0-p0;off1=dest1-p1
 assert off0==off1 and off0 in (0,28,56,84)
 s0=tr0[off0:off0+28];s1=tr1[off1:off1+28]
 assert s0[:24]==s1[:24] and s0[23]==0xe9
 back0=dest0+28+struct.unpack_from('<i',s0,24)[0]
 back1=dest1+28+struct.unpack_from('<i',s1,24)[0]
 assert back0==back1==base+0x3e
 m0[at+1:at+5]=m1[at+1:at+5]=bytes(4)
 rows.append(dict(name=name,entry=aa['address'],trampoline_offset=off0,return_address=hex(back0)))
assert m0==m1,'additional executable byte difference'
out=dict(status='PASS',strict_identity='8635/8639; four residuals retained',pre_sha256=hashlib.sha256(pre.data).hexdigest(),pad_sha256=hashlib.sha256(pad.data).hexdigest(),padding_bytes=32,text_prefix_equal_except_four_checked_rel32=True,rodata_equal=True,gnu_properties_equal=True,trampolines=rows)
(ROOT/'docs/wave4d/pad-relocations.json').write_text(json.dumps(out,indent=2)+'\n')
print(json.dumps(out,indent=2))
