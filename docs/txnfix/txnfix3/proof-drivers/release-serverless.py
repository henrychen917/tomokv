import pathlib,json,time,subprocess,hashlib
root=pathlib.Path('docs/txnfix/txnfix3/release-serverless');root.mkdir(exist_ok=True)
while not pathlib.Path('docs/txnfix/txnfix3/release-extras/COMPLETE.json').exists():time.sleep(.5)
rows=[]
for name,cmd in [('gates-full',['python3','tests/gates_test.py']),('ledger-self-tests',['python3','tests/gate_ledger_fixture.py','--self-test'])]:
 command=['taskset','-c','112-127',*cmd];start=time.monotonic()
 with (root/(name+'.log')).open('w') as out:
  try:rc=subprocess.run(command,stdout=out,stderr=subprocess.STDOUT,timeout=1800).returncode
  except subprocess.TimeoutExpired:rc=124
 rows.append(dict(name=name,command=command,exit_code=rc,seconds=time.monotonic()-start))
 (root/'runs.json').write_text(json.dumps(rows,indent=2)+'\n');print(name,rc,flush=True)
(root/'COMPLETE.json').write_text(json.dumps(rows,indent=2)+'\n')
