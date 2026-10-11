import subprocess,pathlib
for name in ['build-release.py','release-proof.py','release-extras.py','release-serverless.py','release-cross-watch.py','release-controls.py']:
 with (pathlib.Path('build/txnfix3')/(name+'.log')).open('w') as log:
  rc=subprocess.run(['taskset','-c','112-127','python3',str(pathlib.Path('build/txnfix3')/name)],stdout=log,stderr=subprocess.STDOUT).returncode
 print(name,rc,flush=True)
 if rc:raise SystemExit(rc)
