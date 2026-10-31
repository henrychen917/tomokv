import argparse, hashlib, io, json, shutil, tarfile
from pathlib import Path
ap=argparse.ArgumentParser();ap.add_argument('directory',type=Path);ap.add_argument('name');a=ap.parse_args()
root=a.directory;doc=Path('docs/flipfix6');archive=doc/(a.name+'-evidence.tar.gz')
assert root.is_dir() and root.resolve().is_relative_to(Path('build').resolve())
assert all((p.parent/'done').exists() for p in root.glob('jobs/*/output.log'))
files=[];jobs={}
for p in root.glob('jobs/*/done'):
    fields=p.read_text().split();jobs[p.parent.name]={'exit':int(fields[0]),'passed':int(fields[1]),'failed':int(fields[2])}
with tarfile.open(archive,'w:gz',compresslevel=6) as tar:
    for p in sorted(root.rglob('*')):
        if not p.is_file():continue
        data=p.read_bytes();relative=str(p.relative_to(root))
        rec={'path':relative,'bytes':len(data),'sha256':hashlib.sha256(data).hexdigest()}
        files.append(rec)
        if data.startswith(b'\x7fELF') or p.suffix in ('.rdb','.aof','.key','.pem'):
            rec['archived']=False;continue
        member=relative
        if b'shutdown_report ' in data or b'io_tenure ' in data:
            lines=data.splitlines();kept=[];removed=0;counts={}
            for line in lines:
                if line.startswith(b'io_tenure '):removed+=1;continue
                if line.startswith(b'shutdown_report '):
                    try:
                        report=json.loads(line[len(b'shutdown_report '):])
                        for t in report.get('threads',[]):
                            if 'io_tenures' in t:
                                n=len(t.pop('io_tenures'));t['io_tenure_count']=n;counts[str(t['tid'])]=n
                        line=b'derived_shutdown_report '+json.dumps(report,separators=(',',':')).encode()
                    except (ValueError,TypeError,KeyError):pass
                kept.append(line)
            data=(f'DERIVED LOG: raw SHA-256 {rec["sha256"]}; per-tenure timing lines/arrays retired after recording counts.\n'.encode()+b'\n'.join(kept)+b'\n')
            member+='.summary';rec.update(archived='derived',source_lines=len(lines),omitted_io_tenure_lines=removed,shutdown_tenure_counts=counts)
        else:rec['archived']=True
        rec['archive_member']=member
        info=tarfile.TarInfo(member);info.size=len(data);info.mtime=int(p.stat().st_mtime);info.mode=p.stat().st_mode & 0o777
        tar.addfile(info,io.BytesIO(data))
receipt={'source':str(root),'jobs':jobs,'files':files,'archive':str(archive),'archive_sha256':hashlib.sha256(archive.read_bytes()).hexdigest()}
(doc/(a.name+'-archive.json')).write_text(json.dumps(receipt,indent=2)+'\n')
shutil.rmtree(root)
print(a.name,len(files),'files',archive.stat().st_size,'compressed bytes; retired source')
