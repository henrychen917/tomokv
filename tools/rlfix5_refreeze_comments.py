#!/usr/bin/env python3
"""Synchronize R7's comment, rebuild, and require identical runtime sections."""
import copy, hashlib, json, os, shutil, subprocess
from pathlib import Path
from rlfix5_elf import image
ROOT=Path(__file__).resolve().parents[1]
DOC=ROOT/'docs/rlfix5'
BUILD=ROOT/'build/rlfix5'
def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()
def comparable(value):
    value=copy.deepcopy(value)
    # GNU's build ID hashes debug information too. Everything else loaded by
    # the program, including section addresses and loader headers, must match.
    value['sections']=[r for r in value['sections'] if r['name']!='.note.gnu.build-id']
    return value
assert os.sched_getaffinity(0)<=set(range(24,32))
assert (DOC/'jobs/broad-uring.json').exists(), 'never mutate a running frozen arm'
source=ROOT/'src/core/reorder.cc'; old=source.read_text()
old_comment='            // Same classification result as the ordinary parser; spec is unchanged here.\n'
new_comment=('            // The shared classifier sets this exactly for armed GET/MGET. No intervening\n'
             '            // path changes spec; reuse that result instead of testing its flags again.\n')
assert old.count(old_comment)==1
expected=old.replace(old_comment,new_comment)
subprocess.run(['python3','tests/r7shadow_sync.py','--write'],check=True)
assert source.read_text()==expected, 'unexpected generated change'
post=BUILD/'POST'; before=image(post); before_sha=sha(post)
# Preserve the already-tested image until the replacement's exact comparison succeeds.
backup=BUILD/'POST-before-comment-sync';shutil.copy2(post,backup)
env=dict(os.environ,LC_ALL='C',CXX='g++ -gz=zlib',CC='cc -gz=zlib')
commands=[['make','-j8','all'],['make','-q','all'],['python3','tests/r7shadow_sync.py']]
with (DOC/'comment-sync-build.log').open('w') as log:
    for cmd in commands:subprocess.run(cmd,env=env,stdout=log,stderr=subprocess.STDOUT,check=True)
after=image(ROOT/'build/tomokv')
record=dict(old_sha256=before_sha,new_sha256=sha(ROOT/'build/tomokv'),
            old_image=before,new_image=after,commands=commands,
            only_source_change='one R7 enqueue comment expanded to match its generator',
            runtime_image_equal=comparable(before)==comparable(after),excluded_section='.note.gnu.build-id')
(DOC/'comment-sync-runtime-image.json').write_text(json.dumps(record,indent=2)+'\n')
assert record['runtime_image_equal'], 'runtime changed: previous proof cannot transfer'
shutil.copy2(ROOT/'build/tomokv',post)
print('R7 comment synchronized; runtime sections and loader metadata identical',flush=True)
# The main census and scatter census both bind the final linked production objects.
for action,arm in [('build','post'),('scatter-build','post'),('count','pre'),('count','post'),
                   ('scatter-count','pre'),('scatter-count','post'),('count','pad-a'),('compare','post')]:
    cmd=['python3','tools/rlfix5_proof.py',action,'--arm',arm]
    if action=='count' and arm=='pad-a':cmd+=['--only','GET,SET,INCR,MGET,MSET']
    with (DOC/('final-'+action+'-'+arm+'.log')).open('w') as log:
        subprocess.run(cmd,env=env,stdout=log,stderr=subprocess.STDOUT,check=True)
subprocess.run(['python3','tools/rlfix5_artifacts.py','identity'],env=env,check=True)
print('Final arm hashes and instruction receipts refreshed',flush=True)
