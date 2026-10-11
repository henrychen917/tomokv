import pathlib,subprocess,time,json
b=pathlib.Path('build/txnfix3');receipt=pathlib.Path('docs/txnfix/txnfix3/final4-static');receipt.mkdir(exist_ok=True)
while not pathlib.Path('docs/txnfix/txnfix3/final4-build/freshness.json').exists():time.sleep(.5)
rows=[]
for name in ['run-identity-final4.py','build-scatter-final4.py','trace-scatter-final4.py','build-prepare-final4.py','trace-prepare-final4.py','build-prepare-stream-final4.py','trace-prepare-stream-final4.py','build-read-final4.py','trace-read-final4.py']:
 cmd=['taskset','-c','112-127','python3',str(b/name)]
 with (receipt/(name+'.log')).open('w') as log:rc=subprocess.run(cmd,stdout=log,stderr=subprocess.STDOUT).returncode
 rows.append(dict(name=name,command=cmd,exit_code=rc));(receipt/'runs.json').write_text(json.dumps(rows,indent=2)+'\n');print(name,rc,flush=True)
 if rc:raise SystemExit(rc)
(b/'START-FINAL4-PROOF').touch()
