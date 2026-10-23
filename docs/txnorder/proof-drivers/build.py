#!/usr/bin/env python3
"""Compile all gate production targets, then check freshness; never execute them."""
import json,pathlib,re,subprocess,time
root=pathlib.Path('docs/txnorder/build-final');root.mkdir(exist_ok=True)
gate=pathlib.Path('tests/gate.sh').read_text();body=gate.split('job_production_units(){',1)[1].split('\n}',1)[0]
command=body.split('make -k -j"$BUILD_JOBS"',1)[1].split('>"$TMPDIR/build.log"',1)[0]
targets=re.findall(r'build/[a-zA-Z0-9_-]+',command)
assert len(targets)==29,targets
targets=['all',*targets,'mdbqsbr-live-arms']
cmd=['taskset','-c','48-63','make','-j16',*targets]
(root/'command.json').write_text(json.dumps(cmd,indent=2)+'\n');start=time.time()
with (root/'make.log').open('w') as f:r=subprocess.run(cmd,stdout=f,stderr=subprocess.STDOUT)
result=dict(command=cmd,exit_code=r.returncode,seconds=time.time()-start,freshness=[])
for target in targets:
 check=subprocess.run(['taskset','-c','48-63','make','-q',target],capture_output=True,text=True)
 result['freshness'].append(dict(target=target,exit_code=check.returncode,output=check.stdout+check.stderr))
(root/'result.json').write_text(json.dumps(result,indent=2)+'\n')
print('make exit',r.returncode,'freshness',[(x['target'],x['exit_code']) for x in result['freshness']],flush=True)
raise SystemExit(r.returncode or any(x['exit_code'] for x in result['freshness']))
