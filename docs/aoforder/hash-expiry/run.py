from pathlib import Path
import json,subprocess,time
root=Path('build/aoforder/hash-expiry-final').resolve();root.mkdir(exist_ok=False)
rows=[]
for arm,binary,appendonly in [('pre','build/aoforder/pre/tomokv','yes'),('post','build/tomokv','yes'),('pre-off','build/aoforder/pre/tomokv','no')]:
    for mode in ('1s','2s'):
        label=arm+'-'+mode
        command=['taskset','-c','105-107','python3','docs/aoforder/hash-expiry/probe.py','--binary',binary,'--artifacts',str(root/label),'--mode',mode,'--appendonly',appendonly]
        start=time.monotonic()
        with (root/(label+'.log')).open('w') as log:r=subprocess.run(command,stdout=log,stderr=subprocess.STDOUT)
        text=(root/(label+'.log')).read_text()
        witnessed=r.returncode==1 and 'AssertionError: hash-field expiry tore an undecided MSET in the live keyspace' in text
        rows.append(dict(label=label,command=command,rc=r.returncode,expected_failure_witnessed=witnessed,seconds=time.monotonic()-start))
        (root/'summary.json').write_text(json.dumps(rows,indent=2)+'\n');print(rows[-1],flush=True)
raise SystemExit(not all(row['expected_failure_witnessed'] for row in rows))
