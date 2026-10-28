#!/usr/bin/env python3
"""Bind each serverless scope executable to the ordinary production link inputs."""
import hashlib,json,shlex,subprocess
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
OUT=ROOT/'docs/streamfix/instructions'
rows={}
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
for arm in ['pre','post']:
    source,objects=(ROOT/'build/streamfix/pre-source',ROOT/'build/streamfix/pre') if arm=='pre' else (ROOT,ROOT/'build')
    recipe=subprocess.check_output(['make','-C',str(source),'BUILD_ROOT='+str(objects),'-n','-W',str(objects/'src/main.o'),'all'],text=True)
    production=shlex.split(next(line for line in recipe.splitlines() if ' -o '+str(objects/'tomokv')+' ' in line))
    production_objects=[x for x in production if x.endswith('.o')]
    for ns in ['normal','db0']:
        name=arm+'-'+ns;receipt=json.loads((OUT/(name+'-build.json')).read_text());link=receipt['link']
        fixture=ROOT/'build/streamfix/commands'/name/'probe.o'
        probe=fixture.parent/'probe';assert sha(probe)==receipt['sha256']
        renamed=fixture.parent/'original-main.o'
        expected=[str(renamed) if x==str(objects/'db0/src/main.o') else x for x in production_objects]+[str(fixture)]
        assert [x for x in link if x.endswith('.o')]==expected
        rows[name]=dict(probe_sha256=sha(probe),production_sha256=sha(objects/'tomokv'),production_link=production,
            fixture_last=True,original_main=str(objects/'db0/src/main.o'),rename_only=receipt['rename'],
            objects=[dict(path=x,sha256=sha(x)) for x in expected],
            scope='GDB scope_begin/scope_end in tests/txnorder_command_scope.cc; named production namespace bodies including inlines, excluding CoreConcurrencyTest fixture bodies and external callees. External-call counts retained separately. clock_gettime answers are deterministic in both arms.')
(OUT/'linkage.json').write_text(json.dumps(rows,indent=2)+'\n')
print('All four probes preserve production object order and put fixture COMDATs last.')
