#!/usr/bin/env python3
"""Plant each repaired mechanism back to its broken state in a disposable tree.
Only four translation units change; link all other POST production objects verbatim.
"""
from pathlib import Path
import concurrent.futures, difflib, hashlib, json, os, shlex, shutil, subprocess
ROOT=Path(__file__).resolve().parents[2]
os.sched_setaffinity(0,set(range(32,48)))
OUT=ROOT/'build/multifix/regression';OUT.mkdir(exist_ok=True)
for name in ('src','third_party'):
 shutil.copytree(ROOT/name,OUT/name,dirs_exist_ok=True)
shutil.copy2(ROOT/'Makefile',OUT/'Makefile')
changes={}
def change(name,edit):
 p=OUT/name;before=p.read_text();after=edit(before);assert before!=after,name;p.write_text(after)
 changes[name]=''.join(difflib.unified_diff(before.splitlines(True),after.splitlines(True),fromfile=name,tofile=name))
def multi(s):
 s=s.replace('if (multi_name(op, "reset")) {','if (false && multi_name(op, "reset")) {')
 s=s.replace('if (private_head) {','if (false && private_head) {')
 s=s.replace('void multi_slowlog_record(MultiExecState& state, MultiCommand& command, uint32_t owner) {',
             'void multi_slowlog_record(MultiExecState& state, MultiCommand& command, uint32_t owner) {\n    return; // planted missing inner-command logging')
 s=s.replace('bool multi_pause_writes(const Client& client) {',
             'bool multi_pause_writes(const Client& client) {\n    return false; // planted missing EXEC write classification')
 s=s.replace('if (!command_client_pause(*state->server, *command->op))','if (true) // planted unsupported queued CLIENT PAUSE')
 return s
change('src/cmd/multi.inc',multi)
for name in ('src/cmd/xshard_commands.inc','src/cmd/notify.inc'):
 before=subprocess.check_output(['git','show','83e0b809d:'+name],cwd=ROOT,text=True)
 change(name,lambda s,before=before:before)
change('src/cmd/t_server.cc',lambda s:s.replace('client_pause_expiry_clock.store(server ? server->climon_pause_clock() : nullptr,','client_pause_expiry_clock.store(nullptr, // planted missing expiry pause'))
(ROOT/'docs/multifix/regression.patch').write_text(''.join(changes.values()))
recipe=subprocess.check_output(['make','-n','-B','all'],cwd=ROOT,text=True).splitlines()
selected=[];replacements={}
for ns in ('src','db0/src'):
 for source in ('xshard','t_server'):
  target=f'build/{ns}/cmd/{source}.o'
  argv=shlex.split(next(l for l in recipe if l.startswith('g++ ') and l.endswith(' -o '+target)))
  output=OUT/target;output.parent.mkdir(parents=True,exist_ok=True)
  argv[argv.index('-o')+1]=str(output);selected.append(argv);replacements[str(ROOT/target)]=str(output)
def compile(argv):
 path=Path(argv[-1]).with_suffix('.log')
 with path.open('w') as f:subprocess.run(argv,cwd=OUT,stdout=f,stderr=subprocess.STDOUT,check=True)
with concurrent.futures.ThreadPoolExecutor(4) as pool:list(pool.map(compile,selected))
link=shlex.split(next(l for l in recipe if l.startswith('g++ ') and ' -Wl,--wrap=main ' in l))
link=[str(ROOT/a) if a.startswith('build/') and a.endswith('.o') else a for a in link]
link=[replacements.get(a,a) for a in link]
binary=ROOT/'build/multifix/tomokv-regression';link[link.index('-o')+1]=str(binary)
subprocess.run(link,cwd=ROOT,check=True)
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
receipt=dict(post_sha256=sha(ROOT/'build/multifix/tomokv-post-final'),binary_sha256=sha(binary),compile=selected,link=link,
 inputs=[dict(path=a,sha256=sha(a)) for a in link if a.endswith('.o')],patch_sha256=sha(ROOT/'docs/multifix/regression.patch'))
(ROOT/'docs/multifix/regression-build.json').write_text(json.dumps(receipt,indent=2)+'\n')
print(receipt['binary_sha256'])
