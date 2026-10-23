#!/usr/bin/env python3
"""Preserve every normalized instruction/encoding delta without weakening identity."""
import difflib,gzip,importlib.util,json,os,re
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
assert os.sched_getaffinity(0)<=set(range(64,112))
spec=importlib.util.spec_from_file_location("audit",ROOT/"tests/reorder_noop.py")
audit=importlib.util.module_from_spec(spec);spec.loader.exec_module(audit)
out=ROOT/"build/wave5c/body-diffs";out.mkdir(parents=True,exist_ok=True)
pre=audit.Binary(Path("/home/user/Projects/bins/wave5b-2028fd77"),out,literal_pools=True)
post=audit.Binary(ROOT/"build/tomokv",out,literal_pools=True)
rows=json.loads((ROOT/"docs/wave5c/identity/wave5b-post-changed-bodies.json").read_text())
summary=[]
with gzip.open(ROOT/"docs/wave5c/identity/wave5b-post-deltas.txt.gz","wt") as f:
 for row in rows:
  name=row["name"]
  before=sorted(pre.groups.get(name,[]),key=lambda x:x["addr"])
  after=sorted(post.groups.get(name,[]),key=lambda x:x["addr"])
  def lines(bodies):
   return [f"clone {i}: {enc} | {ins}\n" for i,b in enumerate(bodies) for ins,enc in zip(b["ins"],b["encodings"])]
  diff=list(difflib.unified_diff(lines(before),lines(after),fromfile="wave5b: "+name,tofile="wave5c: "+name))
  f.writelines(diff)
  changes=[x.strip() for x in diff if x.startswith(("+","-")) and not x.startswith(("+++","---"))]
  minus=[s[1:] for s in changes if s.startswith('-')]
  plus=[s[1:] for s in changes if s.startswith('+')]
  enc_equal=[s.split(' | ')[0] for s in minus]==[s.split(' | ')[0] for s in plus]
  ref_only=enc_equal and [re.sub(r'<(?!\+)[^>]*>','<reference>',s) for s in minus]==[re.sub(r'<(?!\+)[^>]*>','<reference>',s) for s in plus]
  summary.append(dict(name=name,changed_lines=len(changes),sample=changes[:12],
                      changed_encodings_equal=enc_equal,global_references_only=ref_only))
(ROOT/"docs/wave5c/identity/delta-summary.json").write_text(json.dumps(summary,indent=2)+"\n")
for p in out.glob("*.objdump"):p.unlink()
