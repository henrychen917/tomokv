"""Verify every command residual against literal bytes, retaining strict residuals."""
import gzip, importlib.util, json, re, struct, subprocess, sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[3]
sys.path.insert(0,str(ROOT/'tools'))
from lbstall_artifacts import Elf
import identity
paths=[ROOT/'build/tomokv-PRE',ROOT/'build/tomokv']
inventories=[identity.audit.inventory(p) for p in paths]
images=[Elf(p) for p in paths]
dest=ROOT/'docs/trackfix/trackfix2/identity'
summary=json.loads((dest/'summary.json').read_text())
diffs=gzip.open(dest/'instruction-differences.txt.gz','rt').read()
blocks={b.splitlines()[0]:b for b in diffs.split('\nFUNCTION ') if b}
def read(image,address,size):
    for i,s in enumerate(image.sections):
        if s[1]!=8 and s[3]<=address and address+size<=s[3]+s[5]:
            return image.section_data(i)[address-s[3]:address-s[3]+size]
    raise AssertionError(hex(address))
def body(arm,name):
    bodies=inventories[arm]['groups'][name];assert len(bodies)==1
    b=bodies[0];base=int(b['address'],16)
    text=subprocess.check_output(['objdump','-d','--start-address='+hex(base),
        '--stop-address='+hex(base+b['size']),str(paths[arm])],text=True)
    lines={int(m[1],16)-base:m[2] for line in text.splitlines()
           if (m:=re.match(r'\s*([0-9a-f]+):\s*(.*)',line))}
    return base,lines
results=[]
for row in summary['all_commands']:
    if row['equal']:continue
    name=row['name'];block=blocks[name]
    left=[l[1:] for l in block.splitlines() if l.startswith('-') and not l.startswith('---')]
    right=[l[1:] for l in block.splitlines() if l.startswith('+') and not l.startswith('+++')]
    assert len(left)==len(right)>0,(name,left,right)
    bodies=[body(arm,name) for arm in (0,1)]
    refs=[]
    for a,b in zip(left,right):
        # Never mask an opcode, encoding, immediate, register, branch, or member offset.
        assert a.split(' # ')[0]==b.split(' # ')[0],(name,a,b)
        assert a.split(' | ')[1]==b.split(' | ')[1],(name,a,b)
        offset=int(a.split()[0],16)
        values=[]
        for arm in (0,1):
            base,lines=bodies[arm]
            line=lines[offset];match=re.search(r'#\s+([0-9a-f]+)',line);assert match,line
            address=int(match[1],16)
            if 'CSWTCH.' in (a if arm==0 else b):
                symbols=[s for s in images[arm].symbols if s['value']==address and s['name']==re.search(r'CSWTCH\.\d+',a if arm==0 else b)[0]]
                assert len(symbols)==1 and symbols[0]['size']>0
                values.append(dict(kind='complete switch table',bytes=read(images[arm],address,symbols[0]['size']).hex()))
            elif 'scan_home' in name and ' lea ' in a:
                # Both adjacent tables dispatch the six KvObj types (cmpb $5,
                # movslq table[reg*4], add table, indirect jump). Every instruction
                # is already checked above and by the strict whole-body comparison.
                assert any('$0x5' in lines[o] and 'cmpb' in lines[o] for o in lines if offset-20<=o<offset)
                targets=struct.unpack('<6i',read(images[arm],address,24))
                values.append(dict(kind='six jump destinations',function_offsets=[address+x-base for x in targets]))
            else:
                assert re.search(r'\] (?:mov|vcomisd|vucomisd) ',a),(name,a)
                values.append(dict(kind='64-bit scalar literal',bytes=read(images[arm],address,8).hex()))
        assert values[0]==values[1],(name,offset,values)
        refs.append(dict(offset=hex(offset),verified=values[0]))
    results.append(dict(name=name,status='PASS',references=refs))
    row['literal_verified']=True
for row in summary['changed']:
    if any(r['name']==row['name'] for r in results):
        row['reason']='Only relocation/literal labels differ: every instruction and normalized encoding plus all referenced scalar/table bytes or jump destinations independently match PRE (command-literals.json).'
summary['command_identity']=dict(groups=len(summary['all_commands']),strict_identical=sum(r['equal'] for r in summary['all_commands']),literal_verified=len(results),unexplained=[])
(dest/'command-literals.json').write_text(json.dumps(results,indent=2)+'\n')
(dest/'summary.json').write_text(json.dumps(summary,indent=2)+'\n')
print(json.dumps(summary['command_identity']))
