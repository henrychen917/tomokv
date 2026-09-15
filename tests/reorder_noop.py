#!/usr/bin/env python3
"""Offline instruction audit. Never runs a server or removes a non-address operand."""
import argparse, bisect, difflib, hashlib, json, re, struct, subprocess
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

def normalize_asm(asm,addr,size,demangle,address_name=None,literal_name=None):
    def ref(m):
        target=int(m[1],16); label=m[2]
        base,sep,offset=label.partition('+0x')
        if addr<=target<addr+size: return '<+'+hex(target-addr)+'>'
        if literal_name is not None: return '<'+literal_name+'>'
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

class LiteralPools:
    """Resolve unnamed read-only literals and bounded local switch tables.

    objdump labels anonymous constants relative to the nearest unrelated symbol
    (for example kNoThread+0x400, far outside that four-byte object). Adding a
    clock constant moves these offsets without changing the load. Opt in only:
    named objects, writable memory and unknown instructions keep the old strict
    comparison. Opcode/register/width checking and displacement verification are
    still performed by the original normalizer.
    """
    def __init__(self, path, nm):
        data = Path(path).read_bytes()
        if data[:6] != b'\x7fELF\x02\x01': raise ValueError('expected little-endian ELF64')
        table = struct.unpack_from('<Q', data, 40)[0]
        width, count, _ = struct.unpack_from('<HHH', data, 58)
        self.sections = []
        for i in range(count):
            h = struct.unpack_from('<IIQQQQIIQQ', data, table+i*width)
            # Allocated PROGBITS, neither writable nor executable.
            if h[1] == 1 and h[2] & 2 and not h[2] & (1 | 4):
                self.sections.append((h[3], data[h[4]:h[4]+h[5]]))
        self.named = []
        for line in nm.splitlines():
            parts = line.split(None, 3)
            if len(parts) == 4 and parts[2] not in 'tTwW':
                at, size = int(parts[0], 16), int(parts[1], 16)
                if size: self.named.append((at, at+size))

    def label(self, asm):
        m = re.fullmatch(r'(vmovdqa|vmovsd|lea)\s+-?0x[0-9a-f]+\(%rip\),%([a-z0-9]+)\s+#\s+([0-9a-f]+) <[^<>]+>', asm)
        if not m: return None
        mnemonic, register, target = m[1], m[2], int(m[3], 16)
        if mnemonic == 'vmovsd' and register.startswith('xmm'): width = 8
        elif mnemonic == 'vmovdqa' and register.startswith('xmm'): width = 16
        elif mnemonic == 'vmovdqa' and register.startswith('ymm'): width = 32
        elif mnemonic == 'lea' and register.startswith('r'): width = 0
        else: return None
        for start, data in self.sections:
            offset = target-start
            if not 0 <= offset < len(data): continue
            if width:
                literal = data[offset:offset+width]
                if len(literal) != width: return None
            else:
                # Only complete text literals, not pointer tables or arbitrary
                # binary objects reached by LEA. Include the terminating NUL.
                end = data.find(b'\0', offset, min(len(data), offset+4096))
                if end <= offset: return None
                literal = data[offset:end+1]
                if any(c not in (9, 10, 13) and not 32 <= c <= 126 for c in literal[:-1]):
                    return None
            if any(a < target+len(literal) and target < b for a, b in self.named):
                return None
            return ('literal-load-' if width else 'literal-string-') + literal.hex()
        return None

    def jump_label(self, index, body, instructions, addr, size):
        # GCC's bounded switch: cmp/ja, LEA table, optional zero extension,
        # signed table load, base add, indirect jump. Verify every table entry
        # against its actual instruction boundary in THIS function. A changed
        # case destination must fail even when the LEA's encoding still matches.
        if index < 2 or index+4 >= len(body): return None
        asm = instructions[body[index]][1]
        lea = re.fullmatch(r'lea\s+-?0x[0-9a-f]+\(%rip\),%([a-z0-9]+)\s+#\s+([0-9a-f]+) <[^<>]+>', asm)
        bound = re.fullmatch(r'cmp\s+\$0x([0-9a-f]+),%([a-z0-9]+)', instructions[body[index-2]][1])
        if not lea or not bound or not instructions[body[index-1]][1].startswith('ja '):
            return None
        count = int(bound[1], 16)+1
        if count > 4096: return None
        base, target = lea[1], int(lea[2], 16)
        cursor = index+1
        extend = re.fullmatch(r'movzbl\s+%([a-z0-9]+),%([a-z0-9]+)', instructions[body[cursor]][1])
        source = bound[2]
        if extend:
            if extend[1] != source: return None
            source = extend[2]
            cursor += 1
        if cursor+2 >= len(body): return None
        load = re.fullmatch(r'movslq\s+\(%([a-z0-9]+),%([a-z0-9]+),4\),%([a-z0-9]+)', instructions[body[cursor]][1])
        if not load or load[1] != base: return None
        families = {r: family for family, names in {
            'rax': ('rax','eax','ax','al'), 'rbx': ('rbx','ebx','bx','bl'),
            'rcx': ('rcx','ecx','cx','cl'), 'rdx': ('rdx','edx','dx','dl'),
            'rsi': ('rsi','esi','si','sil'), 'rdi': ('rdi','edi','di','dil'),
            **{f'r{i}': (f'r{i}',f'r{i}d',f'r{i}w',f'r{i}b') for i in range(8,16)}
        }.items() for r in names}
        if source not in families or families[source] != load[2]: return None
        if ' '.join(instructions[body[cursor+1]][1].split()) != f'add %{base},%{load[3]}': return None
        jump = ' '.join(instructions[body[cursor+2]][1].split())
        if jump not in (f'jmp *%{load[3]}', f'notrack jmp *%{load[3]}'): return None
        if any(a < target+count*4 and target < b for a,b in self.named): return None
        for start, data in self.sections:
            offset = target-start
            if not 0 <= offset <= len(data)-count*4: continue
            destinations = [target+x[0] for x in struct.iter_unpack('<i',data[offset:offset+count*4])]
            if any(not addr <= x < addr+size or x not in instructions for x in destinations):
                return None
            return 'local-switch-'+','.join(hex(x-addr) for x in destinations)
        return None

class Binary:
    def __init__(self,path,out,literal_pools=False):
        self.path=Path(path); self.sha256=digest(path)
        nm=run('nm','-S','--defined-only',str(path)); obj=run('objdump','-d','-w',str(path))
        literals=LiteralPools(path,nm) if literal_pools else None
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
            body=instruction_addresses[bisect.bisect_left(instruction_addresses,addr):bisect.bisect_left(instruction_addresses,addr+size)]
            for index,at in enumerate(body):
                raw,asm=self.instructions[at]
                encodings.append(normalized_encoding(raw,asm,at,addr,size))
                literal_name=(literals.label(asm) or literals.jump_label(index,body,self.instructions,addr,size)) if literals else None
                asm=normalize_asm(asm,addr,size,self.demangle,self.address_name,
                                  literal_name)
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
    # Literal relocation is not permission to hide changed constants, named
    # fields, a wider load, an unrecognized instruction or writable storage.
    pools=LiteralPools.__new__(LiteralPools)
    pools.sections=[(0x1000, bytes(range(32)))]; pools.named=[]
    load='vmovdqa 0x123(%rip),%xmm0 # 1000 <unrelated+0x400>'
    token=pools.label(load); assert token is not None
    pools.sections=[(0x2000, bytes(range(32)))]
    assert pools.label(load.replace('1000 <','2000 <')) == token
    pools.sections=[(0x1000, b'\xff'+bytes(range(1,32)))]
    assert pools.label(load) != token
    pools.sections=[(0x1000, bytes(range(32)))]; pools.named=[(0x1000,0x1004)]
    assert pools.label(load) is None
    pools.named=[]
    assert pools.label(load.replace('%xmm0','%ymm0')) != token
    assert pools.label(load.replace('vmovdqa','unknown')) is None
    pools.sections=[]
    assert pools.label(load) is None
    table=['cmp    $0x1,%al','ja     1010 <f+0x10>',
           'lea    0x123(%rip),%rdx # 2000 <unrelated+0x400>',
           'movzbl %al,%eax','movslq (%rdx,%rax,4),%rax',
           'add    %rdx,%rax','notrack jmp *%rax']
    body=list(range(0x1000,0x1000+len(table)))
    instructions={at:([],asm) for at,asm in zip(body,table)}
    pools.sections=[(0x2000,struct.pack('<ii',0x1000-0x2000,0x1001-0x2000))]
    token=pools.jump_label(2,body,instructions,0x1000,len(body))
    assert token == 'local-switch-0x0,0x1'
    pools.sections=[(0x2000,struct.pack('<ii',0x1000-0x2000,0x1002-0x2000))]
    assert pools.jump_label(2,body,instructions,0x1000,len(body)) != token
    pools.sections=[(0x2000,struct.pack('<ii',0x1000-0x2000,0x3000-0x2000))]
    assert pools.jump_label(2,body,instructions,0x1000,len(body)) is None
    print('normalizer self-checks PASS')

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('pre');p.add_argument('post');p.add_argument('output');p.add_argument('--report-only',action='store_true');p.add_argument('--expected-functions',type=int,default=217);p.add_argument('--literal-pools',action='store_true',help='verify anonymous read-only constants by complete consumed bytes');args=p.parse_args()
    self_test();out=Path(args.output);out.mkdir(parents=True,exist_ok=True)
    pre=Binary(args.pre,out,args.literal_pools);post=Binary(args.post,out,args.literal_pools);rows=compare(pre,post,out)
    if len(rows) != args.expected_functions:
        raise ValueError(f'expected {args.expected_functions} PRE bodies, found {len(rows)}')
    result=dict(pre=str(pre.path),post=str(post.path),pre_sha256=pre.sha256,post_sha256=post.sha256,literal_pools=args.literal_pools,rows=rows,strict_noop=all(r['equal'] for r in rows))
    (out/'audit.json').write_text(json.dumps(result,indent=2)+'\n')
    for kind in ['scheduler','envelope','dispatch','retire','commands','multi-key commands']:
        rs=[r for r in rows if r['category']==kind]
        print(kind,len(rs),'identical',sum(r['equal'] for r in rs),'different/missing',sum(not r['equal'] for r in rs))
    print('strict_noop',result['strict_noop'])

    raise SystemExit(0 if args.report_only or result['strict_noop'] else 1)
