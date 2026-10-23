"""Archive this lane's completed correctness receipts without replacing prior trackfix evidence."""
import ast, hashlib, json, re, shutil, tarfile
from collections import Counter
from pathlib import Path
ROOT=Path(__file__).resolve().parents[3]
DOC=ROOT/'docs/trackfix';DEST=DOC/'trackfix2'
SUFFIXES={'.log','.txt','.json','.held','.replayed','.pending','.overlapped','.primed'}
def archive(source,target):
    if target.exists():return
    files=[p for p in sorted(source.rglob('*')) if p.is_file() and not p.is_symlink() and
           (p.suffix in SUFFIXES or p.name in ('ledger','timings','done','returncode','stdout','stderr') or p.name.startswith('gate-srv-'))]
    with tarfile.open(target,'w:gz') as tar:
        for p in files:tar.add(p,arcname=str(p.relative_to(source)),recursive=False)
    target.with_suffix(target.suffix+'.json').write_text(json.dumps(dict(source=str(source),files=len(files),bytes=sum(p.stat().st_size for p in files),sha256=hashlib.sha256(target.read_bytes()).hexdigest()),indent=2)+'\n')
gates=[]
for dest in sorted((DOC/'proof').glob('trackfix2-*')):
    if not (dest/'returncode').exists():continue
    text=(dest/'gate.log').read_text(errors='replace')
    match=re.search(r'^  artifacts: (.+)$',text,re.M)
    if match:
        source=Path(match[1])/'jobs';archive(source,dest/'jobs.tar.gz')
        for job in ('trackfix_order','trackfix_accounting'):
            logs=sorted((source/job).glob('order-*.log'))
            if not logs:continue
            rows=dest/'rows'/job;rows.mkdir(parents=True,exist_ok=True)
            for log in logs:shutil.copy2(log,rows/log.name)
            windows={str(p.relative_to(source/job)):p.read_text() for p in sorted((source/job).rglob('*')) if p.suffix in {'.held','.replayed','.pending','.overlapped','.primed'}}
            (rows/'schedule-receipts.json').write_text(json.dumps(windows,indent=2)+'\n')
            results=[]
            for log in logs:
                data=log.read_text();m=re.search(r'trackfix (?:ordered|accounting): (\d+) passed, (\d+) failed',data)
                results.append(dict(leg=log.name,passed=int(m[1]) if m else None,failed=int(m[2]) if m else None,failures=[l for l in data.splitlines() if l.startswith('FAIL ')]))
            (rows/'summary.json').write_text(json.dumps(dict(legs=results,receipts=dict(Counter(Path(k).suffix for k in windows))),indent=2)+'\n')
    ledger=dest/'ledger.partial';counts=Counter(l.split('\t',1)[0] for l in ledger.read_text().splitlines()) if ledger.exists() else Counter()
    gates.append(dict(label=dest.name,returncode=int((dest/'returncode').read_text()),passed=counts['ok'],failed=counts['FAIL']))
(DEST/'gate-results.json').write_text(json.dumps(gates,indent=2)+'\n')
differs=[]
for dest in sorted((DOC/'differ').glob('*trackfix2-final-*')):
    if not dest.is_dir() or not (dest/'result.json').exists():continue
    archive(ROOT/'build/trackfix/differ'/dest.name,dest/'receipts.tar.gz')
    text=(dest/'output.log').read_text();m=re.search(r'DIFFER GATE: pass=(\d+) fail=(\d+)',text);assert m,dest
    result=json.loads((dest/'result.json').read_text());result.update(passed=int(m[1]),failed=int(m[2]),failures=[l for l in text.splitlines() if 'FAIL' in l]);differs.append(result)
(DEST/'differ-results.json').write_text(json.dumps(differs,indent=2)+'\n')
controls=[]
for arm in ('PRE','POST'):
    dest=DEST/('repeats-'+arm)
    if not (dest/'results.json').exists():continue
    results=json.loads((dest/'results.json').read_text());assert len(results)==20
    for row in results:
        lines=(dest/(arm+'-'+str(row['roll'])+'.log')).read_text().splitlines();frames=[]
        for i,l in enumerate(lines):
            if l.startswith('    target:'):
                target=ast.literal_eval(l.split(':',1)[1].strip());oracle=ast.literal_eval(lines[i+1].split(':',1)[1].strip())
                assert b'invalidate' in oracle and target==oracle*2,(row,l)
                frames.append(dict(target=target.hex(),oracle=oracle.hex()))
        assert len(frames)==row['duplicate_comparisons']
        controls.append(dict(arm=arm,roll=row['roll'],returncode=row['returncode'],duplicate_frames=len(frames),frames=frames))
    archive(ROOT/'build/trackfix/trackfix2-repeats'/arm,dest/'boots.tar.gz')
(DEST/'control-counts.json').write_text(json.dumps(controls,indent=2)+'\n')
for name in ('suppress-pending','suppress-pending-boots'):
    source=ROOT/'build/trackfix'/name
    if source.exists() and (DEST/'suppress-pending/result.json').exists():archive(source,DEST/('control-'+name+'.tar.gz'))
print('gate cohorts',len(gates),'standard legs',len(differs),'fresh repeats',len(controls))
