#!/usr/bin/env python3
"""Offline c12 source and emitted-code receipts. No server or measurement."""
import argparse
import difflib
import hashlib
import json
from pathlib import Path
import re
import subprocess
from lbstall_artifacts import Elf

ROOT = Path(__file__).resolve().parents[1]
def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def clean(source):
    source = re.sub(r'//[^\n]*|/\*[\s\S]*?\*/', '', source)
    return re.sub(r'\s+', '', source)

def balanced(source, start):
    opening = source.index('{', start)
    depth = 0
    for token in re.finditer(r'//[^\n]*|/\*[\s\S]*?\*/|"(?:\\.|[^"\\])*"|[{}]', source[opening:]):
        if token[0] == '{': depth += 1
        elif token[0] == '}': depth -= 1
        if depth == 0: return opening, opening + token.end()
    raise ValueError('unclosed C++ body')

def body(source, name):
    start = re.search(r'inline [^\n]*\b'+name+r'\(', source).start()
    a, b = balanced(source, start)
    return source[a:b]

def phase(source):
    start = source.index('// PHASE 2 --')
    end = source.index('\n    void enqueue_serve', start)
    return source[start:end]

def receipt(path):
    elf = Elf(path)
    sizes = {n:s[5] for n,s in zip(elf.names, elf.sections)}
    return dict(path=str(path), sha256=sha(path), text=sizes['.text'],
                tdata=sizes.get('.tdata',0), tbss=sizes.get('.tbss',0))

def phase_start(obj, symbol, source):
    low = source[:source.index('// PHASE 2 --')].count('\n')+1
    high = low+phase(source).count('\n')
    dump = subprocess.check_output(['objdump','-dlw','--disassemble='+symbol,str(obj)],text=True)
    line = None
    offsets = []
    for row in dump.splitlines():
        match = re.search(r'/src/core/io_loop.h:(\d+)',row)
        if match: line = int(match[1])
        elif re.match(r'/.*:\d+',row): line = None
        instruction = re.match(r'\s*([0-9a-f]+):\s+[0-9a-f]{2} ',row)
        if instruction and line is not None and low <= line <= high:
            offsets.append(int(instruction[1],16))
    assert offsets, (obj,symbol,'no PHASE 2 line records')
    return min(offsets)

def legacy_symbol(value):
    # The existing physical-role tag is now carried through these two call sites.
    # Drop only that new template argument when matching PRE callee identities.
    if isinstance(value, bytes): return value
    if isinstance(value, (tuple, list)): return tuple(legacy_symbol(v) for v in value)
    if not isinstance(value, str): return value
    for method, count in (("11flush_ready",5),("14r7_flush_ready",5),("5sweep",4),("8r7_sweep",4)):
        value = re.sub(r'(6IoLoop'+method+r'I)((?:Lb[01]E){'+str(count)+r'})Lb[01]E', r'\1\2', value)
    return value

def physical_split(label, method, fused_index):
    match=re.search(r'IoLoop::'+method+r'<([^<>]+)>',label)
    if not match: return False
    args=[arg.strip() for arg in match[1].split(',')]
    return args[fused_index]=='false' or (len(args)==6 and args[-1]=='true')

def audit(pre, post, oracle, output):
    candidate = (ROOT/'src/core/wb_rule.h').read_text()
    measured = (oracle/'tools/window4/window4_study.h').read_text()
    equality = {}
    for name in ('code_bytes','reply_bytes','defer'):
        a,b = body(measured,name),body(candidate,name)
        if name == 'defer':
            start = a.index('    if constexpr (unless_long)')
            _,end = balanced(a,start)
            a = a[:start]+a[end:]
            a = a.replace('c.window4_staged_bytes()', 'staged_bytes(c)').replace('send_bytes','kWbufInline')
            a = a.replace('const Op& op =', 'const auto& op =')
            a = a.replace('(n * (fraction == 4 ? 3u : 1u) + fraction - 1) / fraction','(n * 1 + 2 - 1) / 2')
            b = b.replace('kPolicyFraction.num','1').replace('kPolicyFraction.den','2')
        equality[name] = dict(equal=clean(a)==clean(b), normalized_sha256=hashlib.sha256(clean(a).encode()).hexdigest())
        assert equality[name]['equal'], name
    a = phase((oracle/'build/drainall/window4-src/src/core/io_loop.h').read_text())
    b = phase((ROOT/'src/core/io_loop.h').read_text())
    for text,name in ((a,'measured'),(b,'landing')):
        (output.parent/f'wbrule-phase2-{name}.inc').write_text(text)
    (output.parent/'wbrule-vs-window4-phase2.diff').write_text(''.join(difflib.unified_diff(a.splitlines(True),b.splitlines(True),fromfile='w4-c12 PHASE 2',tofile='landing PHASE 2')))
    tail = lambda s: s[s.index('c->set_serve_pending(false);'):s.index('work += served;')]
    equality['ordinary_serve'] = dict(equal=clean(tail(a))==clean(tail(b)))
    assert equality['ordinary_serve']['equal']
    fused_tail = tail(candidate).replace('loop.', '').replace('template ', '')
    fused_tail = fused_tail.replace('ServerType::', 'Server::').replace('auto*', 'TlsConn*')
    equality['fused_ordinary_serve'] = dict(equal=clean(tail(a).replace('Fused','true'))==clean(fused_tail))
    assert equality['fused_ordinary_serve']['equal']
    # The mode guard and FIFO lifecycle are additionally executed by the phase/stage witnesses.
    a_io = (pre.parent/'wbrule-pre-src/src/core/io_loop.h').read_text()
    b_io = (ROOT/'src/core/io_loop.h').read_text()
    old_split = phase(a_io)
    old_split = old_split[old_split.index('        uint32_t served = 0;'):]
    old_split = old_split[:old_split.rindex('\n    }')]
    old_split = old_split.replace('Fused ? kGenthreadWbBatchConns : kServeBudget', 'kServeBudget')
    split_else = phase(b_io)
    split_else = split_else.index('} else {', split_else.index('return work + wb_rule::Phase2'))
    p2 = phase(b_io)
    first,last = balanced(p2,split_else)
    equality['split_loop_tokens'] = dict(equal=clean(old_split)==clean(p2[first+1:last-1]))
    assert equality['split_loop_tokens']['equal']
    rows=[]
    for ns in ('src','db0/src'):
        for file in ('main.o','core/rl2s.o','cmd/t_string.o','cmd/t_string_notify.o'):
            a,b = Elf(pre/ns/file),Elf(post/ns/file)
            before,after = a.functions(),b.functions()
            names=list(after)
            labels=subprocess.check_output(['c++filt'],input='\n'.join(names)+'\n',text=True).splitlines()
            for name,label in zip(names,labels):
                split_phase=physical_split(label,'flush_ready',2)
                command=bool(re.search(r'::cmd_(get|set)(?:<|\(|_tls\(|_notify\()',label))
                other=bool(physical_split(label,'run_loop',3) or
                           'IoLoop::pipeline_pass<' in label or 'IoLoop::wb_gather<' in label or
                           'ExLoopT<false>::drain_tasks<' in label)
                if not(split_phase or command or other): continue
                old_name=legacy_symbol(name)
                assert old_name in before, (file,name,'missing PRE body')
                ca=legacy_symbol(a.canonical(before[old_name]));cb=legacy_symbol(b.canonical(after[name]))
                row=dict(object=ns+'/'+file,symbol=name,pre_symbol=old_name,name=label,whole_function_identical=ca==cb,
                         scope='split PHASE 2' if split_phase else 'GET/SET' if command else 'split caller/stage')
                if split_phase:
                    if ca==cb: row['phase2_identical']=True
                    else:
                        pa=phase_start(a.path,old_name,a_io)-before[old_name]['value']
                        pb=phase_start(b.path,name,b_io)-after[name]['value']
                        row.update(pre_phase2_offset=pa,post_phase2_offset=pb,
                                   phase2_identical=pa==pb and ca[0][pa:]==cb[0][pb:] and
                                   [r for r in ca[1] if r[0]>=pa]==[r for r in cb[1] if r[0]>=pb])
                    assert row['phase2_identical'], row
                if command: assert ca==cb,row
                rows.append(row)
    witnesses={}
    for group in ('policy','phase','stages'):
        path=post/f'wb-rule-{group}-proofs.json'
        proofs=json.loads(path.read_text())
        assert all(r['passed'] for r in proofs)
        for proof in proofs: assert sha(proof['binary'])==proof['sha256']
        witnesses[group]=dict(path=str(path),sha256=sha(path),positive=sum(r['expected_exit']==0 for r in proofs),negative=sum(r['expected_exit']==1 for r in proofs))
    result=dict(source_commit=subprocess.check_output(['git','log','-1','--format=%H','--','src','Makefile'],cwd=ROOT,text=True).strip(),
                production_patch_sha256=hashlib.sha256(subprocess.check_output(['git','diff','3e734cf2e','--','src'],cwd=ROOT)).hexdigest(),
                measured_inputs={str(p):sha(p) for p in (oracle/'tools/drainall_window4.patch',oracle/'tools/drainall_window4.mk',oracle/'tools/drainall_window4.py',oracle/'tools/window4/window4_study.h',ROOT/'build/drainall/window4-source.patch')},
                source_equality=equality,code_identity=rows,witnesses=witnesses,
                binaries=[receipt(p) for p in (pre/'tomokv',post/'tomokv',post/'tomokv-pad',Path('/home/user/Projects/cx-final/build/tomokv'))])
    assert result['binaries'][1]['text']==result['binaries'][2]['text'], 'stale PAD size'
    output.write_text(json.dumps(result,indent=2)+'\n')
    phases=[r for r in rows if r['scope']=='split PHASE 2']
    print(f"Split PHASE 2: {sum(r['phase2_identical'] for r in phases)}/{len(phases)}; whole emitted functions {sum(r['whole_function_identical'] for r in rows)}/{len(rows)}")
    print('Source clauses and all witness digests match; receipt',output)

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--pre',type=Path,default=ROOT/'build/wbrule-pre')
    p.add_argument('--post',type=Path,default=ROOT/'build')
    p.add_argument('--oracle',type=Path,default=Path('/home/user/Projects/cx-drainall-test'))
    p.add_argument('--output',type=Path,default=ROOT/'build/wbrule-artifacts.json')
    a=p.parse_args();audit(a.pre,a.post,a.oracle,a.output)
