import pathlib,time,subprocess,hashlib,json
root=pathlib.Path('docs/txnfix/txnfix3')
while not (root/'final4-controls/ALL-DONE').exists():time.sleep(1)
cmd=['taskset','-c','112-127','python3','tools/txnfix_pad.py','--output','build/txnfix3/pad-final4','--receipt','docs/txnfix/txnfix3/pad-final4']
subprocess.run(cmd,check=True)
pre=pathlib.Path('build/txnfix2/pre/tomokv');post=pathlib.Path('build/tomokv');frozen=pathlib.Path('build/txnfix3/post-final4/tomokv')
assert hashlib.sha256(post.read_bytes()).hexdigest()==hashlib.sha256(frozen.read_bytes()).hexdigest()=='1c808efda63159b31e45e7e960053052b8ac6cd3345049dc23e857bd3da845cc'
(root/'final4-frozen.json').write_text(json.dumps({str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in (pre,post,frozen,pathlib.Path('build/txnfix3/pad-final4/tomokv'))},indent=2)+'\n')
print('final4 PAD and frozen digests retained',flush=True)
