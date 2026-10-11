import pathlib,time,subprocess,json
while not pathlib.Path('docs/txnfix/txnfix3/certified-controls/ALL-DONE').exists():time.sleep(.5)
rows=[]
for name in ['build-read-certified.py','trace-read-certified.py']:
 cmd=['taskset','-c','112-127','python3','build/txnfix3/'+name]
 with pathlib.Path('build/txnfix3/'+name+'.log').open('w') as f:rc=subprocess.run(cmd,stdout=f,stderr=subprocess.STDOUT).returncode
 print(name,rc,flush=True);rows.append(dict(command=cmd,exit_code=rc))
 if rc:raise SystemExit(rc)
pathlib.Path('docs/txnfix/txnfix3/read-certified/commands.json').write_text(json.dumps(rows,indent=2)+'\n')
