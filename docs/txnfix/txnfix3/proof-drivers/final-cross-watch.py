import pathlib,json,subprocess,time,hashlib
root=pathlib.Path('docs/txnfix/txnfix3/final-cross-watch');root.mkdir(exist_ok=True)
while not pathlib.Path('docs/txnfix/txnfix3/final-serverless/COMPLETE.json').exists():time.sleep(.5)
rows=[]
for arm,binary in [('pre','build/txnfix2/pre/tomokv'),('post','build/tomokv')]:
 for mode in ('2s','1s'):
  for atomic in ('0','1'):
   name=f'{arm}-{mode}-a{atomic}';folder=root/name;folder.mkdir(exist_ok=True)
   target=str(pathlib.Path(binary).resolve())
   if mode=='1s':
    wrapper=pathlib.Path('build/txnfix3/proof-data')/(arm+'-armed-server');target=str(wrapper.resolve())
   cmd=['taskset','-c','121-127','python3','tests/txnfix_audit/t19_crossed_watch.py','--binary',target,'--port','22601','--cores','112-119','--mode',mode,'--atomic',atomic,'--databases','16','--output',str(folder.resolve())]
   started=time.monotonic()
   with (folder/'test.log').open('w') as out:
    try:rc=subprocess.run(cmd,stdout=out,stderr=subprocess.STDOUT,timeout=100).returncode
    except subprocess.TimeoutExpired:rc=124
   rows.append(dict(name=name,command=cmd,exit_code=rc,seconds=time.monotonic()-started,sha256=hashlib.sha256(pathlib.Path(binary).read_bytes()).hexdigest()))
   (root/'runs.json').write_text(json.dumps(rows,indent=2)+'\n');print(name,rc,flush=True)
(root/'COMPLETE.json').write_text(json.dumps(rows,indent=2)+'\n')
