#!/usr/bin/env python3
"""Drop only unit DWARF, preserving every allocated byte and target timestamp."""
import hashlib,json,os,subprocess,time
from pathlib import Path
from lbstall_artifacts import Elf
ROOT=Path(__file__).resolve().parents[1];BUILD=ROOT/'build'
os.sched_setaffinity(0,set(range(32,48)))
def allocated(e):
 return [(n,s[1],s[2],s[3],s[5],s[8],hashlib.sha256(e.section_data(i)).hexdigest() if s[1]!=8 else None)
         for i,(n,s) in enumerate(zip(e.names,e.sections)) if s[2]&2]
def digest(p):
 with p.open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()
receipt=ROOT/'docs/rlfix4/stripped-units.json'
rows=json.loads(receipt.read_text()) if receipt.exists() else []
candidates=list(BUILD.glob('*unit*'))+list(BUILD.glob('txnorder-episodes*'))+list(BUILD.glob('*controls/*/unit'))
for p in candidates:
 if not p.is_file() or p.is_symlink() or p.stat().st_size<10_000_000:continue
 before=p.stat()
 if time.time()-before.st_mtime<15:continue
 # Never replace a unit while a linker or test owns its inode.
 if subprocess.run(['fuser',str(p)],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL).returncode==0:continue
 e=Elf(p)
 if '.debug_info' not in e.names:continue
 original=digest(p);temp=p.with_name(p.name+'.rlfix4-stripped')
 subprocess.run(['objcopy','--strip-debug','--preserve-dates',str(p),str(temp)],check=True)
 f=Elf(temp);assert allocated(e)==allocated(f),(p,'allocated bytes changed')
 after=p.stat()
 if (after.st_ino,after.st_size,after.st_mtime_ns)!=(before.st_ino,before.st_size,before.st_mtime_ns) or subprocess.run(['fuser',str(p)],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL).returncode==0:
  temp.unlink();continue
 row=dict(path=str(p.relative_to(ROOT)),pre_sha256=original,post_sha256=digest(temp),bytes_before=before.st_size,bytes_after=temp.stat().st_size,allocated_sections_equal=True,mtime_preserved=True)
 os.replace(temp,p);rows.append(row);receipt.write_text(json.dumps(rows,indent=2)+'\n')
 print(p.name,before.st_size-row['bytes_after'],flush=True)
