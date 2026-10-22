"""Use the gate normalizer verbatim, on an explicit named-function inventory."""
import bisect,collections,hashlib,json,subprocess,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'tests'))
import reorder_noop as audit

def bodies(path,names):
    nm=subprocess.check_output(['nm','-S','--defined-only',str(path)],text=True)
    entries=[]
    for line in nm.splitlines():
        p=line.split(None,3)
        if len(p)==4 and p[2] in 'tTwW':entries.append((int(p[0],16),int(p[1],16),p[3]))
    syms=sorted({s for a,n,s in entries})
    decoded=subprocess.check_output(['c++filt',*syms],text=True).splitlines()
    demangle={a:audit.canonical(b) for a,b in zip(syms,decoded)}
    aliases=collections.defaultdict(list)
    for a,n,s in entries:aliases[a].append(demangle[s])
    addrname={a:min(set(v)) for a,v in aliases.items()}
    select={a:(n,s) for a,n,s in entries if addrname[a] in names}
    literals=audit.LiteralPools(path,nm)
    result=collections.defaultdict(list)
    for a,(n,s) in select.items():
        obj=subprocess.check_output(['objdump','-dw','--start-address='+hex(a),'--stop-address='+hex(a+n),str(path)],text=True)
        extra={m[2].split('+0x')[0] for line in obj.splitlines() for m in audit.REFERENCE.finditer(line)}-set(demangle)
        if extra:
            extra=sorted(extra);ds=subprocess.check_output(['c++filt',*extra],text=True).splitlines()
            demangle.update((k,audit.canonical(v)) for k,v in zip(extra,ds))
        instructions={}
        for line in obj.splitlines():
            m=audit.INSTRUCTION.match(line)
            if m:instructions[int(m[1],16)]=(m[2].split(),m[3])
        order=sorted(instructions);ins=[];enc=[]
        for i,at in enumerate(order):
            raw,asm=instructions[at]
            enc.append(audit.normalized_encoding(raw,asm,at,a,n))
            literal=literals.label(asm) or literals.jump_label(i,order,instructions,a,n)
            normalized=audit.normalize_asm(asm,a,n,demangle,addrname,literal)
            ins.append(f'{at-a:04x} [{len(raw):2}] '+' '.join(normalized.split()))
        result[addrname[a]].append(dict(address=hex(a),size=n,ins=ins,encodings=enc))
    return dict(result)
