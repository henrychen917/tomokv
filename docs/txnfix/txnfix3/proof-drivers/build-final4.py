import pathlib,subprocess,json,time
root=pathlib.Path('docs/txnfix/txnfix3/final4-build');root.mkdir(exist_ok=True)
targets=['build/at15-unit', 'build/at15-db0-unit', 'build/execabort-watch-unit', 'build/execabort-watch-db0-unit', 'build/core-concurrency-unit', 'build/atomic-survivors-unit', 'build/netcmd-unit', 'build/encodingfix-unit', 'build/netcap-unit', 'build/waits-unit', 'build/rehash-waits-unit', 'build/multidb-unit', 'build/multidb-boundary-unit', 'build/storesize-unit', 'build/wb-rule-units', 'build/wbland-units', 'build/rltopo-unit', 'build/lbplanner-units', 'build/shutdown-unit', 'build/persistfix-units', 'build/exbatch-unit', 'build/exbatch-db0-unit', 'build/ktls-keyupdate', 'build/ktls-keyupdate-unit', 'build/flushfix-units', 'build/splitlocal-unit', 'build/reorder-engagement-unit', 'build/reorder-engagement-unit-db0', 'build/racefix-climon']
rows=[]
for name,cmd in [('all',['make','-j16','-W','src/cmd/xshard.cc','-W','src/cmd/t_server.cc','all']),('production',['make','-k','-j16',*targets]),('mdbqsbr',['make','-j16','mdbqsbr-live-arms'])]:
 cmd=['taskset','-c','112-127',*cmd];t=time.monotonic()
 with (root/(name+'.log')).open('w') as log:rc=subprocess.run(cmd,stdout=log,stderr=subprocess.STDOUT).returncode
 rows.append(dict(name=name,command=cmd,exit_code=rc,seconds=time.monotonic()-t));print(name,rc,flush=True)
 (root/'runs.json').write_text(json.dumps(rows,indent=2)+'\n')
fresh=[]
for target in targets+['mdbqsbr-live-arms']:
 cmd=['taskset','-c','112-127','make','-q',target]
 p=subprocess.run(cmd,capture_output=True,text=True)
 fresh.append(dict(target=target,command=cmd,exit_code=p.returncode,output=p.stdout+p.stderr))
(root/'freshness.json').write_text(json.dumps(fresh,indent=2)+'\n')
print('freshness',sum(r['exit_code']==0 for r in fresh),len(fresh),flush=True)
