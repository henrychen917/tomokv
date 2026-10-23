import concurrent.futures,hashlib,json,pathlib,subprocess
root=pathlib.Path('docs/txnfix/txnfix3/identity-release');root.mkdir(parents=True,exist_ok=True)
cmds=[['python3','tools/lbstall_artifacts.py','compare','build/txnfix2/pre','build',str(root/'hot.json')],['python3','tools/ccfix_audit.py','build/txnfix2/pre','build',str(root/'full')],['python3','docs/deadswitch/linked_bytes.py','build/txnfix2/pre/tomokv','build/tomokv',str(root/'linked.json')]]
def run(item):
 n,cmd=item
 with (root/f'command-{n}.log').open('w') as log:rc=subprocess.run(['taskset','-c','112-127']+cmd,stdout=log,stderr=subprocess.STDOUT).returncode
 print(n,rc,flush=True);return dict(command=cmd,exit_code=rc)
start={p:hashlib.sha256(pathlib.Path(p).read_bytes()).hexdigest() for p in ('build/txnfix2/pre/tomokv','build/tomokv')}
with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:rows=list(pool.map(run,enumerate(cmds)))
end={p:hashlib.sha256(pathlib.Path(p).read_bytes()).hexdigest() for p in start}
assert start==end
(root/'commands.json').write_text(json.dumps(dict(commands=rows,sha256=start),indent=2)+'\n')
