import pathlib,subprocess,json,concurrent.futures,re,hashlib,collections
root=pathlib.Path.cwd();out=root/'docs/txnfix/txnfix3/prepare-clock';out.mkdir(exist_ok=True)
template=(root/'build/txnfix3/scatter-pre.gdb').read_text()
def run(case):
 arm,ns,mode,values=case;label='-'.join(case);binary=root/'build/txnfix3/prepare-clock'/f'{arm}-{ns}'/'probe'
 records=[]
 for line in subprocess.check_output(['nm','-S','--defined-only',str(binary)],text=True).splitlines():
  f=line.split()
  if len(f)==4 and f[2] in ('t','T','W','w'):records.append([int(f[0],16),int(f[0],16)+int(f[1],16),f[3]])
 names=subprocess.check_output(['c++filt'],input='\n'.join(r[2] for r in records),text=True).splitlines()
 prefix='tomo::' if ns=='normal' else 'tomo_db0::'
 selected=[[*r,n] for r,n in zip(records,names) if prefix in n and ('xshard_' in n or 'Scatter' in n or 'free_state_' in n or 'finish_phase' in n or 'assemble_final' in n)]
 ranges=out/(label+'-ranges.json');ranges.write_text(json.dumps(selected))
 script=re.sub(r'ranges=json.load\(open\(.+?\)\)', 'ranges=json.load(open('+repr(str(ranges))+'))',template)
 anchor=next(r[0] for r in records if r[2]=='_Z19scatter_trace_beginv')
 script=re.sub(r"delta=int\(gdb.parse_and_eval\('\(void\*\)&scatter_trace_begin'\)\)-\d+", "delta=int(gdb.parse_and_eval('(void*)&scatter_trace_begin'))-"+str(anchor),script)
 trace=out/(label+'-trace.json')
 script=re.sub(r'json.dump\(rows,open\(.+?,.w.\),indent=2\)', 'json.dump(rows,open('+repr(str(trace))+",'w'),indent=2)",script)
 script=script.replace("gdb.execute('run',to_string=True)", "gdb.execute('run "+values+' '+mode+"',to_string=True)")
 path=root/'build/txnfix3/prepare-clock'/(label+'.gdb');path.write_text(script)
 cmd=['taskset','-c','112-127','gdb','-batch','-x',str(path),str(binary)]
 with (out/(label+'.log')).open('w') as log:
  try:rc=subprocess.run(cmd,stdout=log,stderr=subprocess.STDOUT,timeout=300).returncode
  except subprocess.TimeoutExpired:rc=124
 count=collections.Counter(r['function'] for r in json.loads(trace.read_text())) if trace.exists() else {}
 result=dict(arm=arm,namespace=ns,mode=mode,values=values,command=cmd,exit_code=rc,binary_sha256=hashlib.sha256(binary.read_bytes()).hexdigest(),counts=dict(count))
 (out/(label+'-result.json')).write_text(json.dumps(result,indent=2)+'\n');print(label,rc,sum(count.values()),flush=True);return result
cases=[(a,n,m,v) for a in ['post'] for n in ['db0'] for m in ['2s'] for v in ['MGET','SORT','KEYS','FLUSHDB','FLUSHALL']]
with concurrent.futures.ThreadPoolExecutor(2) as pool:rows=list(pool.map(run,cases))
(out/'runs.json').write_text(json.dumps(rows,indent=2)+'\n')
