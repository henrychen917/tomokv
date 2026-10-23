import subprocess,pathlib
for name in ['build-certified.py','certified-proof.py','certified-extras.py','certified-serverless.py','certified-cross-watch.py','certified-controls.py']:
 with (pathlib.Path('build/txnfix3')/(name+'.log')).open('w') as log:
  rc=subprocess.run(['taskset','-c','112-127','python3',str(pathlib.Path('build/txnfix3')/name)],stdout=log,stderr=subprocess.STDOUT).returncode
 print(name,rc,flush=True)
 if rc:raise SystemExit(rc)
