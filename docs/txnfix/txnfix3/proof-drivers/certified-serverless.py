import pathlib,json,time,subprocess,hashlib,shutil
root=pathlib.Path('docs/txnfix/txnfix3/certified-serverless');root.mkdir(exist_ok=True)
while not pathlib.Path('docs/txnfix/txnfix3/certified-extras/COMPLETE.json').exists():time.sleep(.5)
# The final binary's complete 66-test invocation already passed at the start
# of this proof. Retain it rather than rerun an unchanged, successful family.
prior=next(r for r in json.loads(pathlib.Path('docs/txnfix/txnfix3/certified-proof/runs.json').read_text()) if r['name']=='gates-test')
assert prior['exit_code']==0
rows=[dict(prior, reused_from='docs/txnfix/txnfix3/certified-proof/gates-test/test.log')]
shutil.copy2(rows[0]['reused_from'],root/'gates-full.log')
for name,cmd in [('ledger-self-tests',['python3','tests/gate_ledger_fixture.py','--self-test'])]:
 command=['taskset','-c','112-127',*cmd];start=time.monotonic()
 with (root/(name+'.log')).open('w') as out:
  try:rc=subprocess.run(command,stdout=out,stderr=subprocess.STDOUT,timeout=1800).returncode
  except subprocess.TimeoutExpired:rc=124
 rows.append(dict(name=name,command=command,exit_code=rc,seconds=time.monotonic()-start))
 (root/'runs.json').write_text(json.dumps(rows,indent=2)+'\n');print(name,rc,flush=True)
(root/'COMPLETE.json').write_text(json.dumps(rows,indent=2)+'\n')
