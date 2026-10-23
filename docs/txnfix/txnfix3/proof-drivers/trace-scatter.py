import pathlib,subprocess,json,hashlib,re
root=pathlib.Path.cwd();out=root/'docs/txnfix/txnfix3/scatter-trace'
import os
for arm in os.environ.get('TXNFIX_TRACE_ARMS','pre,post').split(','):
 binary=root/'build/txnfix3/scatter-probe'/arm/'probe'
 if not binary.exists():raise SystemExit('probe not linked: '+str(binary))
 records=[]
 for line in subprocess.check_output(['nm','-S','--defined-only',str(binary)],text=True).splitlines():
  fields=line.split()
  if len(fields)==4 and fields[2] in ('t','T','W','w'):
   addr,size=int(fields[0],16),int(fields[1],16);records.append([addr,addr+size,fields[3]])
 names=subprocess.check_output(['c++filt'],input='\n'.join(r[2] for r in records),text=True).splitlines()
 selected=[]
 for row,name in zip(records,names):
  if 'tomo::' in name and ('xshard_' in name or 'Scatter' in name or 'free_state_' in name or 'finish_phase' in name or 'assemble_final' in name):selected.append([*row,name])
 (out/(arm+'-ranges.json')).write_text(json.dumps(selected))
 script='''set pagination off
set confirm off
set auto-load off
set print thread-events off
set disable-randomization on
python
import gdb,json,bisect
ranges=json.load(open(RANGES))
ranges.sort();starts=[r[0] for r in ranges]
def at(pc):
 i=bisect.bisect_right(starts,pc)-1
 return ranges[i] if i>=0 and pc<ranges[i][1] else None
begin=gdb.Breakpoint('scatter_trace_begin')
end=gdb.Breakpoint('scatter_trace_end')
gdb.execute('run',to_string=True)
delta=int(gdb.parse_and_eval('(void*)&scatter_trace_begin'))-ANCHOR
for r in ranges:r[0]+=delta;r[1]+=delta
starts=[r[0] for r in ranges]
begin.delete()
gdb.execute('finish',to_string=True)
arch=gdb.selected_frame().architecture()
rows=[]
for step in range(20000):
 pc=int(gdb.parse_and_eval('$pc'))
 label=gdb.execute('info symbol '+hex(pc),to_string=True).strip()
 if label.startswith('scatter_trace_end('):break
 insn=arch.disassemble(pc,count=1)[0]
 f=at(pc)
 if f:rows.append(dict(function=f[3],symbol=f[2],offset=pc-f[0],asm=insn['asm']))
 text=insn['asm']
 if text.startswith('call'):
  import re
  match=re.search(r'0x[0-9a-f]+',text)
  follow=match and at(int(match[0],16))
  gdb.execute('stepi' if follow else 'nexti',to_string=True)
 else:gdb.execute('stepi',to_string=True)
else:raise RuntimeError('instruction trace bound exceeded')
json.dump(rows,open(OUTPUT,'w'),indent=2)
end.delete()
gdb.execute('continue',to_string=True)
print('TRACE_INSTRUCTIONS',len(rows))
end
'''.replace('RANGES',repr(str(out/(arm+'-ranges.json')))).replace('OUTPUT',repr(str(out/(arm+'-trace.json')))).replace('ANCHOR',str(next(r[0] for r in records if r[2]=='_Z19scatter_trace_beginv')))
 p=root/'build/txnfix3'/('scatter-'+arm+'.gdb');p.write_text(script)
 cmd=['taskset','-c','112-127','gdb','-batch','-x',str(p),str(binary)]
 with (out/(arm+'-trace.log')).open('w') as log:
  rc=subprocess.run(cmd,stdout=log,stderr=subprocess.STDOUT,timeout=240).returncode
 print(arm,rc,flush=True)
