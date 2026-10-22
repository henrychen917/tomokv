"""Throwaway tracking transition trace. Never used as POST or a merit arm."""
import json,shlex,shutil,subprocess
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2];BASE=ROOT/'build/bugs5/trace';SRC=BASE/'source';SRC.mkdir(parents=True,exist_ok=True)
shutil.copytree(ROOT/'build/bugs5/pre-source/src',SRC/'src',dirs_exist_ok=True)
shutil.copytree(ROOT/'third_party',SRC/'third_party',dirs_exist_ok=True)
p=SRC/'src/cmd/tracking.cc';s=p.read_text()
s=s.replace('        state.tracking_pending[keys.back()] = &op;', '''        state.tracking_pending[keys.back()] = &op;
        if (key.eq_icase("ck:10")) std::fprintf(stderr, "TRK register id=%llu op=%p state=%u\\n",
            (unsigned long long)client->id(), (void*)&op, (unsigned)op.state.load());''')
s=s.replace('        tracking_register_key(client.id(), key);', '''        if (key == "ck:10") std::fprintf(stderr, "TRK retire id=%llu op=%p\\n",
            (unsigned long long)client.id(), (void*)&op);
        tracking_register_key(client.id(), key);''')
s=s.replace('    const std::string name(key.p, key.n);\n    // 1. BCAST', '''    const std::string name(key.p, key.n);
    if (name == "ck:10") {
        std::fprintf(stderr, "TRK invalidate writer=%llu io=%u completed=%zu\\n",
            (unsigned long long)writer_id, self_->id(), climon_track_keys_.count(name));
        for (const auto& row : climon_conn_) {
            auto it = row.second.tracking_pending.find(name);
            if (it != row.second.tracking_pending.end())
                std::fprintf(stderr, "TRK pending id=%llu op=%p state=%u\\n",
                    (unsigned long long)row.first, (void*)it->second, (unsigned)it->second->state.load());
        }
    }
    // 1. BCAST''')
p.write_text(s)
commands=[shlex.split(l) for l in (ROOT/'docs/bugs5/build-pre.log').read_text().splitlines() if l.startswith('g++ ')]
replacements={}
for obj in ('build/src/cmd/tracking.o','build/db0/src/cmd/tracking.o'):
 c=next(c.copy() for c in commands if c[-1]==obj);dest=BASE/(obj.replace('/','_'));c[-1]=str(dest)
 subprocess.run(c,cwd=SRC,check=True);replacements[obj]=str(dest)
link=next(c.copy() for c in commands if ' -Wl,--wrap=main ' in shlex.join(c))
link=[replacements.get(a,str(ROOT/'build/bugs5/pre-source'/a) if a.startswith('build/') else a) for a in link]
link[link.index('-o')+1]=str(BASE/'tomokv')
subprocess.run(link,cwd=ROOT,check=True)
(ROOT/'docs/bugs5/trace-build.json').write_text(json.dumps(dict(link=link,scope=__doc__),indent=2)+'\n')
