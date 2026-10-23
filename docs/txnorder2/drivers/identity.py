#!/usr/bin/env python3
"""Unmodified historical checkers, coherent production-object views, no execution."""
import concurrent.futures,hashlib,json,pathlib,subprocess
root=pathlib.Path.cwd();out=root/'docs/txnorder2/identity-final';out.mkdir(parents=True,exist_ok=True)
views={}
for arm,base in [('pre',root/'build/txnorder2/pre-source/build'),('post',root/'build')]:
 view=root/'build/txnorder2/object-views'/arm;views[arm]=view
 for prefix in ['src','db0/src']:
  for obj in (base/prefix).rglob('*.o'):
   link=view/obj.relative_to(base);link.parent.mkdir(parents=True,exist_ok=True)
   if link.is_symlink():link.unlink()
   link.symlink_to(obj)
cmds=[['python3','tools/lbstall_artifacts.py','compare',str(views['pre']),str(views['post']),str(out/'hot.json')],
      ['python3','tools/ccfix_audit.py',str(views['pre']),str(views['post']),str(out/'full')],
      ['python3','docs/deadswitch/linked_bytes.py','build/txnorder2/pre-source/build/tomokv','build/tomokv',str(out/'linked.json')],
      ['python3','tools/txnfix_scatter_audit.py',str(views['pre']),str(views['post']),str(out/'scatter')]]
files=[root/'build/tomokv',root/'build/txnorder2/pre-source/build/tomokv']
files += [p for view in views.values() for p in view.rglob('*.o')]
def digests():return {str(p.relative_to(root)):hashlib.sha256(p.read_bytes()).hexdigest() for p in files}
start=digests()
def run(item):
 n,cmd=item;cmd=['taskset','-c','64-95',*cmd]
 with (out/f'command-{n}.log').open('w') as log:rc=subprocess.run(cmd,stdout=log,stderr=subprocess.STDOUT).returncode
 print(n,rc,flush=True);return dict(command=cmd,exit_code=rc)
with concurrent.futures.ThreadPoolExecutor(4) as pool:rows=list(pool.map(run,enumerate(cmds)))
end=digests()
(out/'commands.json').write_text(json.dumps(dict(commands=rows,sha256=start,stable=start==end),indent=2)+'\n')
assert start==end,'input artifact changed during audit'
