import pathlib,subprocess,time,json
b=pathlib.Path('build/txnfix3');receipt=pathlib.Path('docs/txnfix/txnfix3/certified-static');receipt.mkdir(exist_ok=True)
while not pathlib.Path('docs/txnfix/txnfix3/certified-build/freshness.json').exists():time.sleep(.5)
rows=[]
for name in ['run-identity-certified.py','build-scatter-certified.py','trace-scatter-certified.py','build-prepare-certified.py','trace-prepare-certified.py','build-prepare-stream-certified.py','trace-prepare-stream-certified.py']:
 cmd=['taskset','-c','112-127','python3',str(b/name)]
 with (receipt/(name+'.log')).open('w') as log:rc=subprocess.run(cmd,stdout=log,stderr=subprocess.STDOUT).returncode
 rows.append(dict(name=name,command=cmd,exit_code=rc));(receipt/'runs.json').write_text(json.dumps(rows,indent=2)+'\n');print(name,rc,flush=True)
 if rc:raise SystemExit(rc)
(b/'START-CERTIFIED-PROOF').touch()
