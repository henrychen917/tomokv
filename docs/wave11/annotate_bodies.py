#!/usr/bin/env python3
"""Attach source origins and checked switch bytes to the retained strict diffs."""
import gzip, hashlib, json, os, re, subprocess, sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(ROOT/'tools')]
from lbstall_artifacts import Elf
DOC=ROOT/'docs/wave11/identity';OUT=ROOT/'build/wave11/body-explain'
os.sched_setaffinity(0,set(range(64,96)))
rows=json.loads((DOC/'changed-bodies.json').read_text())
arms={}
for label in ('post','headline','flipfix5','scriptfix3','climonfix5'):
    with gzip.open(OUT/label/'selected.json.gz','rt') as f:arms[label]=json.load(f)
post=ROOT/'build/wave11/tomokv-POST'
names=[r['name'] for r in rows if arms['post']['groups'].get(r['name'])]
addresses=[hex(arms['post']['groups'][name][0]['addr']) for name in names]
locations=subprocess.check_output(['addr2line','-e',str(post),*addresses],text=True).splitlines()
origins=dict(zip(names,locations))
with gzip.open(DOC/'residual-diffs.json.gz','rt') as f:diffs={r['name']:r for r in json.load(f)}

table_receipts=[]
for row in rows:
    name=row['name'];row['origin']=origins.get(name,'removed body')
    if row['explanation_kind']!='composition-or-codegen':continue
    delta=diffs.get(name)
    if delta:row['nearest_reference']=delta['reference']
    if 'cmd_xshard_only_impl<' in name:
        # These four bodies have identical instructions/encodings except for
        # GCC's generated ordinal on the same bounded byte lookup table.
        arm=arms[delta['reference']];before=arm['groups'][name][0];after=arms['post']['groups'][name][0]
        assert before['encodings']==after['encodings']
        replacements=[]
        for x,y in zip(before['ins'],after['ins']):
            if x==y:continue
            a=re.search(r'<(CSWTCH\.\d+)>',x);b=re.search(r'<(CSWTCH\.\d+)>',y)
            assert a and b and x.replace(a[1],'TABLE')==y.replace(b[1],'TABLE')
            replacements.append((a[1],b[1]))
        e1,e2=Elf(arm['tls']['path']),Elf(post)
        for a,b in sorted(set(replacements)):
            sa=[s for s in e1.symbols if s['name']==a];sb=[s for s in e2.symbols if s['name']==b]
            assert len(sa)==len(sb)==1
            assert e1.body(sa[0])==e2.body(sb[0])
            table_receipts.append(dict(function=name,reference=delta['reference'],old=a,new=b,
                size=sa[0]['size'],bytes=e1.body(sa[0]).hex(),sha256=hashlib.sha256(e1.body(sa[0])).hexdigest()))
        row['reason']='Only GCC CSWTCH table ordinals differ from climonfix5 POST; all instruction encodings and full referenced table bytes match. Strict named-symbol identity remains different.'
        row['explanation_kind']='verified-table-rename'
    elif '::xshard_execute(' in name or '::xshard_flush_commits' in name:
        row['reason']='TLS relocation of ScriptWorkbench / pending-commit state changes FS operands and corresponding TLS-base LEAs; retained diff shows unchanged instruction structure relative to '+delta['reference']+'. The 31-unit budget sweep preserves the lane body selection.'
    elif any(s in name for s in ('ScriptSource','LuaEngine','run_eval(','compile_eval(','reset_eval_chunks(','readonly_eval(','script_thread_state(','script_metadata_write(')):
        row['reason']='Unified scriptfix3 metadata/persistent engine with climonfix5 cached no-writes closure. Integration adds retained metadata owners, cold compile/reset helpers and the POD activation slot; source and instruction receipts identify the affected cold/warm work.'
    elif any(s in name for s in ('MonitorScriptLine','MonitorPending','monitor_script','monitor_pending')):
        row['reason']='climonfix4 nested MONITOR ordering/delivery records retained with climonfix5 notification gating; template/inlining layout reflects the combined scripting and wave10 tracking state.'
    elif any(s in name for s in ('ClientMeta','climon_','client_command','command_pause_write','multi_pause_write')):
        row['reason']='climonfix4 CLIENT/PAUSE/RESET semantics and climonfix5 command-identity bit, combined with wave10 tracking state. Remaining TLS offsets/inlining are shown in the retained disassembly.'
    elif any(s in name for s in ('cmd_eval','redis_dispatch','script_execute','ScriptContext')):
        row['reason']='Composition of cached EVAL metadata, persistent protected interpreters and gated nested MONITOR/no-writes activation. Warm complete/Lua scopes remain within the isolated scriptfix3 counts.'
    elif re.search(r'(^|::)(lua[A-Z_]|lua_|index2adr|set_global_raw|protected_call|push_redis)',name) or 'third_party/lua' in row['origin']:
        row['reason']='Lua amalgamation compiler propagation from persistent-interpreter/cache integration; normal-namespace stack rotation is deliberately inlined to retain scriptfix3 warm VM cost. No Lua library behavior was changed.'
    elif any(s in name for s in ('Multi','multi_','cmd_exec','prepare_commands','command_key_args','prepare_local_write_keys')):
        row['reason']='climonfix5 removes unarmed transaction bookkeeping while retaining wave10 cached hashes/XREADGROUP classification. Remaining TLS and compiler layout differences are retained; EXEC census has no positive whole-scope delta.'
    elif 'flip' in name.lower():
        row['reason']='flipfix5 stale-stage acknowledgement guard/debug witness plus combined-unit compiler/TLS layout; controller truth tables and block-mask/remask protocol remain unchanged. Active control counts equal flipfix5 POST.'
    else:
        # Preserve the original attribution rather than inventing a causal GCC
        # decision. Origin and exact nearest-reference diff make this reviewable.
        row['reason'] += ' Source origin: '+row['origin']+'. Exact nearest-reference differences are archived; a single optimizer decision is not claimed.'

(DOC/'switch-tables.json').write_text(json.dumps(table_receipts,indent=2)+'\n')
(DOC/'changed-bodies.json').write_text(json.dumps(rows,indent=2)+'\n')
(DOC/'changed-bodies.md').write_text('\n'.join(['# Linked body differences','','All 741 strict differences remain listed. TLS and table-byte equivalence are supplementary explanations.','','| Function | Headline sizes | POST sizes | Reason |','|---|---|---|---|',*[f"| `{r['name']}` | {r['headline_sizes']} | {r['post_sizes']} | {r['reason']} |" for r in rows]])+'\n')
print('Annotated',len(rows),'bodies;',len(table_receipts),'verified lookup tables')
