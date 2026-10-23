import subprocess,pathlib
for name in ['build-final4.py','final4-proof.py','final4-extras.py','final4-serverless.py','final4-cross-watch.py','final4-controls.py']:
 with (pathlib.Path('build/txnfix3')/(name+'.log')).open('w') as log:
  rc=subprocess.run(['taskset','-c','112-127','python3',str(pathlib.Path('build/txnfix3')/name)],stdout=log,stderr=subprocess.STDOUT).returncode
 print(name,rc,flush=True)
 if rc:raise SystemExit(rc)
