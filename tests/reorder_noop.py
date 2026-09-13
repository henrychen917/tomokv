#!/usr/bin/env python3
"""Offline instruction audit. Never runs a server or removes a non-address operand."""
import argparse, bisect, difflib, hashlib, json, re, subprocess
from collections import defaultdict
from pathlib import Path

POLICIES = {
    'fused_pass_impl': 7, 'fused_sweep_impl': 6, 'fused_pass': 1,
    'fused_baseline_pass': 1, 'fused_coarse_pass': 1, 'fused_three_way_pass': 2,
    'fused_pipeline_control': 1, 'fused_sweep': 1, 'fused_baseline_sweep': 1,
    'fused_coarse_sweep': 1, 'fused_pipeline_control_sweep': 1,
    'run': 1, 'run_loop': 7, 'run_fused_iofused_loop': 5,
    'genthread_three_way_pass': 4, 'genthread_iofused_pass': 4,
    'genthread_iofused_sweep': 4, 'flush_ready': 6,
}
HEADER = re.compile(r'^([0-9a-f]+) <(.+)>:$')
INSTRUCTION = re.compile(r'^\s*([0-9a-f]+):\s*((?:[0-9a-f]{2} )+)\s*(.*)$')
REFERENCE = re.compile(r'([0-9a-f]+) <([^<>]+)>')

def run(*args):
    return subprocess.check_output(args, text=True)

def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def canonical(name):
    # Map only the explicitly added compile-time FALSE argument; TRUE remains distinct.
    # Work inside-out because a filler closure names its enclosing IO specialization.
    pattern = re.compile(r'::([A-Za-z_][A-Za-z_0-9]*)<')
    matches = list(pattern.finditer(name))
    for match in reversed(matches):
        method = match[1]
        owner = name[:match.start()]
        if 'ExLoopT<' not in owner and 'IoLoop' not in owner: continue
        end = match.end(); depth = 1; parens = brackets = braces = 0; parts=[]; begin=end
        while end < len(name) and depth:
            if name[end] == '<': depth += 1
            elif name[end] == '>': depth -= 1
            elif name[end] == '(': parens += 1
            elif name[end] == ')': parens -= 1
            elif name[end] == '[': brackets += 1
            elif name[end] == ']': brackets -= 1
            elif name[end] == '{': braces += 1
            elif name[end] == '}': braces -= 1
            elif name[end] == ',' and depth == 1 and not (parens or brackets or braces):
                parts.append(name[begin:end].strip()); begin=end+1
            end += 1
        if depth: raise ValueError('unclosed demangled template')
        parts.append(name[begin:end-1].strip())
        expected=POLICIES.get(method)
        if method == 'sweep': expected=5
        if expected != len(parts): continue
        index=0 if method=='fused_three_way_pass' else len(parts)-1
        if parts[index] != 'false': continue
        del parts[index]
        replacement = ('<'+', '.join(parts)+'>') if parts else ''
        name=name[:match.end()-1]+replacement+name[end:]
    # Demangling prints the return type only for templates, not their former ordinary form.
    if name.startswith('void tomo::ExLoopT<') and '::run()' in name:
        name=name.removeprefix('void ')
    return name

def category(name):
    if 'drain_tasks_reordered' in name or 'ExReorderQueues' in name: return None
    if 'ex_schedule_batch' in name: return None  # Behind the inherited armed branch.
    if 'parse_and_dispatch' in name: return 'dispatch'
    if any(n in name for n in ['wb_retire_prepare<','collect_retire_work<','WbEngine::prepare_pipeline<']): return 'retire'
    if re.search(r'::cmd_(get|set)(?:<|\(|_tls\(|_notify\()',name): return 'commands'
    if any(n in name for n in ['xshard_prepare(', 'xshard_execute(', 'xshard_retire(', 'prepare_captured_local_mget(', 'cmd_xshard_only(']): return 'multi-key commands'
    if 'ExLoopT<' in name and any(n in name for n in [
        '::drain_tasks<','::drain_tasks_with_filler<','::drain_tasks_read_local_interleaved<',
        '::exec_batch<','::exec_batch_prefetched<','::execute<','::fused_pass_impl<',
        '::fused_sweep_impl<','::sweep<','::run()']): return 'scheduler'
    if 'IoLoop::' in name and any(n in name for n in [
        '::run_loop<','::run_fused_iofused_loop<','::genthread_three_way_pass<',
        '::genthread_iofused_sweep<','::flush_ready<']): return 'envelope'
    return None

def normalize_asm(asm,addr,size,demangle,address_name=None):
    def ref(m):
        target=int(m[1],16); label=m[2]
        base,sep,offset=label.partition('+0x')
        if addr<=target<addr+size: return '<+'+hex(target-addr)+'>'
        if address_name and target in address_name: return '<'+address_name[target]+'>'
        return '<'+demangle.get(base,base)+(sep+offset if sep else '')+'>'
    had_reference=bool(REFERENCE.search(asm))
    asm=REFERENCE.sub(ref,asm)
    if not had_reference: return asm
    return re.sub(r'-?0x[0-9a-f]+\(%rip\)','<rip>(%rip)',asm)

def normalized_encoding(raw, asm, at, function_address, function_size):
    """Keep every opcode/prefix/operand byte except a verified address displacement.

    objdump supplies the resolved target. Recompute its displacement rather than
    dropping all immediates or all bytes in an instruction that mentions a symbol.
    Internal branches keep their bytes: moving a basic block must fail the proof.
    """
    encoded = bytes.fromhex(' '.join(raw))
    masked = list(raw)
    refs = list(REFERENCE.finditer(asm))
    if not refs:
        return ' '.join(masked)
    if len(refs) != 1:
        raise ValueError(f'ambiguous relocation at {at:x}: {asm}')
    target = int(refs[0][1], 16)
    delta = target - (at + len(encoded))
    if '%rip' in asm:
        displacement = (delta & 0xffffffff).to_bytes(4, 'little')
        offsets = [i for i in range(1, len(encoded) - 3)
                   if encoded[i:i + 4] == displacement]
        if len(offsets) != 1:
            raise ValueError(f'cannot locate RIP displacement at {at:x}: {asm}')
        first, width = offsets[0], 4
    elif re.match(r'(?:bnd )?(?:call|jmp|j[a-z]+)\s+[0-9a-f]+ <', asm):
        if function_address <= target < function_address + function_size:
            return ' '.join(masked)
        # Direct calls/jumps and near conditional jumps have a final rel32;
        # short jumps have a final rel8. Prefix bytes remain part of the proof.
        width = 4 if len(encoded) >= 5 else 1
        displacement = (delta & ((1 << (8 * width)) - 1)).to_bytes(width, 'little')
        if encoded[-width:] != displacement:
            raise ValueError(f'cannot locate branch displacement at {at:x}: {asm}')
        first = len(encoded) - width
    else:
        # An unrecognized address form is deliberately left literal, never ignored.
        return ' '.join(masked)
    masked[first:first + width] = ['??'] * width
    return ' '.join(masked)

class Binary:
    def __init__(self,path,out):
        self.path=Path(path); self.sha256=digest(path)
        nm=run('nm','-S','--defined-only',str(path)); obj=run('objdump','-d','-w',str(path))
        (out/(self.path.name+'.'+self.sha256[:12]+'.objdump')).write_text(obj)
        entries=[]
        for line in nm.splitlines():
            parts=line.split(None,3)
            if len(parts)==4 and parts[2] in 'tTwW':
                entries.append((int(parts[0],16),int(parts[1],16),parts[3]))
        names={e[2] for e in entries}
        for line in obj.splitlines():
            if m:=HEADER.match(line): names.add(m[2])
            for m in REFERENCE.finditer(line):
                names.add(m[2].split('+0x')[0])
        names=sorted(names)
        decoded=run('c++filt',*names).splitlines()
        self.demangle={a:canonical(b) for a,b in zip(names,decoded)}
        self.instructions={}; self.headers={}
        for line in obj.splitlines():
            if m:=HEADER.match(line): self.headers[int(m[1],16)]=m[2]
            elif m:=INSTRUCTION.match(line):
                self.instructions[int(m[1],16)]=(m[2].split(),m[3])
        self.groups=defaultdict(list)
        self.entry_names=defaultdict(list)
        for addr,size,mangled in entries:
            self.entry_names[addr].append(self.demangle[mangled])
        # objdump chooses one arbitrary name for an ICF alias. Retain the full alias list,
        # but compare each physical body once under its lexicographically first alias.
        self.address_name={a:min(set(ns)) for a,ns in self.entry_names.items()}
        self.addresses=sorted(self.entry_names)
        instruction_addresses=sorted(self.instructions)
        for addr,size,mangled in entries:
            name=self.address_name[addr]
            # Aliases at one address represent one function, never duplicate test rows.
            if any(f['addr']==addr for f in self.groups[name]): continue
            ins=[]; encodings=[]
            for at in instruction_addresses[bisect.bisect_left(instruction_addresses,addr):bisect.bisect_left(instruction_addresses,addr+size)]:
                raw,asm=self.instructions[at]
                encodings.append(normalized_encoding(raw,asm,at,addr,size))
                asm=normalize_asm(asm,addr,size,self.demangle,self.address_name)
                # No source-line, register, member offset, immediate, branch condition,
                # relative block position, instruction width or padding is normalized away.
                ins.append(f'{at-addr:04x} [{len(raw):2}] '+' '.join(asm.split()))
            self.groups[name].append(dict(addr=addr,size=size,ins=ins,encodings=encodings,aliases=sorted(set(self.entry_names[addr]))))

def compare(pre,post,out):
    records=[]
    for name in sorted(pre.groups):
        kind=category(name)
        if not kind: continue
        a=sorted(pre.groups[name],key=lambda x:x['addr']); b=sorted(post.groups.get(name,[]),key=lambda x:x['addr'])
        # Preserve local clone occurrence; an unmatched clone is not silently discarded.
        for index,one in enumerate(a):
            other=b[index] if index<len(b) else None
            row=dict(category=kind,name=name,instance=index,pre_aliases=one['aliases'],post_aliases=other['aliases'] if other else [],pre_address=hex(one['addr']),pre_size=one['size'],pre_instructions=len(one['ins']),post_address=None,post_size=None,post_instructions=None,equal=False)
            lines=['Function: '+name+'\n',f'Occurrence: {index}\n']
            if other:
                row.update(post_address=hex(other['addr']),post_size=other['size'],post_instructions=len(other['ins']),equal=one['ins']==other['ins'] and one['encodings']==other['encodings'])
                lines.extend(l+'\n' for l in difflib.unified_diff(
                    [a+' | '+b for a,b in zip(one['ins'],one['encodings'])],
                    [a+' | '+b for a,b in zip(other['ins'],other['encodings'])],
                    fromfile='PRE',tofile='POST',lineterm=''))
            else: lines.append('POST symbol/clone absent; inspect replacement call graph.\n')
            row['diff']=f'{len(records):03}.diff'
            (out/row['diff']).write_text(''.join(lines))
            (out/(row['diff']+'.pre')).write_text('\n'.join(a+' | '+b for a,b in zip(one['ins'],one['encodings']))+'\n')
            if other: (out/(row['diff']+'.post')).write_text('\n'.join(a+' | '+b for a,b in zip(other['ins'],other['encodings']))+'\n')
            records.append(row)
    if not records: raise ValueError('no matching PRE scope: refusing an empty proof')
    return records

def self_test():
    assert canonical('void tomo::ExLoopT<true>::run<false>()')=='tomo::ExLoopT<true>::run()'
    assert canonical('void tomo::ExLoopT<true>::run<true>()')=='void tomo::ExLoopT<true>::run<true>()'
    a='unsigned int tomo::ExLoopT<true>::fused_pass_impl<128u, true, true, true, false, tomo::IoLoop::genthread_three_way_pass<false, false, false, false>(X)::{lambda()#1}, false>(X*)'
    b='unsigned int tomo::ExLoopT<true>::fused_pass_impl<128u, true, true, true, false, tomo::IoLoop::genthread_three_way_pass<false, false, false>(X)::{lambda()#1}>(X*)'
    assert canonical(a)==b
    assert canonical(a.replace('(X)', '(X&, bool&)'))==b.replace('(X)', '(X&, bool&)')
    # Register/field/immediate/extra-branch changes must remain literal inequalities.
    for lhs,rhs in [('mov 0x189(%rax),%edx','mov 0x190(%rax),%edx'),('mov %rax,%rdx','mov %rax,%rcx'),('mov $0x0,%eax','mov $0x1,%eax'),('0000 [ 1] ret','0000 [ 2] jne <+0x4>')]:
        assert normalize_asm(lhs,0,16,{})!=normalize_asm(rhs,0,16,{})
    assert normalize_asm('call 1234 <target>',0,16,{}) == normalize_asm('call 9876 <target>',0x100,16,{})
    assert normalize_asm('je 4 <f+0x4>',0,16,{}) == normalize_asm('je 104 <f+0x4>',0x100,16,{})
    assert normalize_asm('je 4 <f+0x4>',0,16,{}) != normalize_asm('je 8 <f+0x8>',0,16,{})
    assert normalized_encoding(['e8','2b','12','00','00'], 'call 1234 <target>', 4, 0, 16) == 'e8 ?? ?? ?? ??'
    assert normalized_encoding(['75','02'], 'jne 4 <f+0x4>', 0, 0, 16) == '75 02'
    assert normalized_encoding(['48','8b','05','2d','12','00','00'], 'mov 0x122d(%rip),%rax # 1234 <data>', 0, 0, 16) == '48 8b 05 ?? ?? ?? ??'
    print('normalizer self-checks PASS')

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('pre');p.add_argument('post');p.add_argument('output');p.add_argument('--report-only',action='store_true');p.add_argument('--expected-functions',type=int,default=217);args=p.parse_args()
    self_test();out=Path(args.output);out.mkdir(parents=True,exist_ok=True)
    pre=Binary(args.pre,out);post=Binary(args.post,out);rows=compare(pre,post,out)
    if len(rows) != args.expected_functions:
        raise ValueError(f'expected {args.expected_functions} PRE bodies, found {len(rows)}')
    result=dict(pre=str(pre.path),post=str(post.path),pre_sha256=pre.sha256,post_sha256=post.sha256,rows=rows,strict_noop=all(r['equal'] for r in rows))
    (out/'audit.json').write_text(json.dumps(result,indent=2)+'\n')
    for kind in ['scheduler','envelope','dispatch','retire','commands','multi-key commands']:
        rs=[r for r in rows if r['category']==kind]
        print(kind,len(rs),'identical',sum(r['equal'] for r in rs),'different/missing',sum(not r['equal'] for r in rs))
    print('strict_noop',result['strict_noop'])

    raise SystemExit(0 if args.report_only or result['strict_noop'] else 1)
