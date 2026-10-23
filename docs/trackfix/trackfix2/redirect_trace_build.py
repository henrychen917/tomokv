"""Build a disposable causal trace of the intermittent redirect flag failure."""
import json, shutil, subprocess
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
ROOT=Path(__file__).resolve().parents[3]
base=ROOT/'build/trackfix/gate-scheduled-POST-final';out=ROOT/'build/trackfix/redirect-trace'
source=out/'source';shutil.copytree(base/'source',source,dirs_exist_ok=True)
p=source/'src/cmd/tracking.cc';text=p.read_text()
patches={
    '        auto pending = state->tracking_pending.find(key);': '        if (key=="rd:1") std::fprintf(stderr,"TRACE retire io=%u client=%lu observed=%lu clock=%lu epoch=%lu cut=%lu\\n", self_->id(),client.id(),stamp,tracking_clock_observe(),srv_->atomic_snapshot(),op.read_cut(srv_->atomic_snapshot()));\n',
    '        auto pending = state.tracking_pending.find(name);': '        if (name=="rd:1") std::fprintf(stderr,"TRACE event io=%u client=%lu stamp=%lu enrolled=%lu pending=%zu redirect=%lu\\n",self_->id(),entry.first,stamp,state.tracking_enrolled.count(name)?state.tracking_enrolled[name]:0,state.tracking_pending.count(name),state.redirect);\n',
    '    if (!state.redirect) {': '    if (key.sv()=="rd:1") std::fprintf(stderr,"TRACE deliver io=%u client=%lu redirect=%lu\\n",self_->id(),owner_id,state.redirect);\n',
    '        state.broken_redirect = true;': '        std::fprintf(stderr,"TRACE broken io=%u client=%lu redirect=%lu\\n",self_->id(),owner_id,state.redirect);\n',
    '            if (!target || target->dead() || target->closing()) break;': '            if (event.channel=="rd:1") std::fprintf(stderr,"TRACE receive io=%u target=%lu live=%u found=%d closed=%d\\n",self_->id(),event.client_id,live_io,target!=nullptr,target?(target->dead()||target->closing()):1);\n',
}
# The scheduled-copy replay has its own same-name pending iterator. Only inject
# at the real retirement branch, after the observation has been read.
anchor='        if (stamp == UINT64_MAX) stamp = 0; // no successful observation certificate\n'
addition=patches.pop('        auto pending = state->tracking_pending.find(key);')
assert text.count(anchor)==1;text=text.replace(anchor,anchor+addition)
for anchor,addition in patches.items():
    assert text.count(anchor)==1,(anchor,text.count(anchor));text=text.replace(anchor,addition+anchor)
# Local Slice exposes p/n rather than requiring a new convenience method.
text=text.replace('key.sv()=="rd:1"','key.n==4 && std::memcmp(key.p,"rd:1",4)==0')
p.write_text(text)
commands=json.loads((base/'commands.json').read_text());replacements={};compiles=[]
for cmd in commands['compile']:
    if 'src/cmd/tracking.cc' not in cmd:continue
    cmd=cmd[:];i=cmd.index('-o')+1;replacements[cmd[i]]=str(out/Path(cmd[i]).name);cmd[i]=replacements[cmd[i]];compiles.append(cmd)
def run(pair):
    i,cmd=pair
    with (out/f'compile-{i}.log').open('w') as f:subprocess.run(cmd,cwd=source,stdout=f,stderr=subprocess.STDOUT,check=True)
with ThreadPoolExecutor(max_workers=2) as pool:list(pool.map(run,enumerate(compiles)))
link=[replacements.get(a,a) for a in commands['link']];link[link.index('-o')+1]=str(out/'tomokv')
with (out/'link.log').open('w') as f:subprocess.run(link,cwd=source,stdout=f,stderr=subprocess.STDOUT,check=True)
(out/'commands.json').write_text(json.dumps(dict(compile=compiles,link=link),indent=2)+'\n')
